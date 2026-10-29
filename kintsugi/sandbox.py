"""
AST Safety Guardrail & Isolated Sandbox Execution for KintsugiPy.
Defense-in-depth static analysis and isolated validation.
Note: Static AST checks reduce risk substantially but do not replace OS-level isolation.
"""

import ast
import concurrent.futures
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

DANGEROUS_MODULES: Set[str] = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pty",
    "posix",
    "nt",
    "winreg",
    "ctypes",
    "socket",
    "pickle",
    "marshal",
    "importlib",
    "shelve",
    "tempfile",
}

DANGEROUS_BUILTINS: Set[str] = {
    "eval",
    "exec",
    "__import__",
    "compile",
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
}

# Forbidden dunder attributes used in Python sandbox escapes
FORBIDDEN_DUNDER_ATTRS: Set[str] = {
    "__subclasses__",
    "__bases__",
    "__globals__",
    "__builtins__",
    "__code__",
    "__closure__",
    "__dict__",
    "__class__",
    "__base__",
    "__mro__",
}


class SecurityViolationError(Exception):
    """Raised when proposed code violates AST safety rules."""
    pass


class ASTSafetyChecker(ast.NodeVisitor):
    """Inspects an Abstract Syntax Tree to reject insecure or disallowed constructs."""

    def __init__(self, allowed_modules: Optional[Set[str]] = None) -> None:
        self.disallowed_modules = DANGEROUS_MODULES - (allowed_modules or set())
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_mod = alias.name.split(".")[0]
            if base_mod in self.disallowed_modules:
                self.violations.append(f"Forbidden module import: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_mod = node.module.split(".")[0]
            if base_mod in self.disallowed_modules:
                self.violations.append(f"Forbidden module import from: '{node.module}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct builtin calls (e.g. eval(), exec(), open(), getattr())
        if isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_BUILTINS:
                self.violations.append(f"Forbidden call to builtin: '{node.func.id}()'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Prevent dunder escape chains (e.g. ().__class__.__bases__[0].__subclasses__())
        if node.attr in FORBIDDEN_DUNDER_ATTRS:
            self.violations.append(f"Forbidden access to sensitive dunder attribute: '{node.attr}'")
        self.generic_visit(node)


def verify_code_safety(code: str, expected_func_name: str) -> ast.AST:
    """Parse code and ensure it is syntactically sound, contains the expected function, and is safe."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SecurityViolationError(f"Syntax error in generated patch: {str(e)}") from e

    # Check for target function definition
    has_target = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == expected_func_name:
                has_target = True
                break

    if not has_target:
        raise SecurityViolationError(
            f"Generated code does not contain the required function '{expected_func_name}'."
        )

    # Check for dangerous nodes
    checker = ASTSafetyChecker()
    checker.visit(tree)
    if checker.violations:
        raise SecurityViolationError(
            f"Code rejected due to security policy: {'; '.join(checker.violations)}"
        )

    return tree


def compile_and_extract_function(
    code: str, expected_func_name: str, closure_globals: Optional[Dict[str, Any]] = None
) -> Callable:
    """Compile code into an isolated memory namespace and extract the callable."""
    verify_code_safety(code, expected_func_name)

    # Inherit necessary globals from original function (e.g. imports, classes)
    namespace: Dict[str, Any] = dict(closure_globals or {})
    # Strip any dangerous overrides
    for b in DANGEROUS_BUILTINS:
        namespace.pop(b, None)

    compiled = compile(code, f"<kintsugi_patch_{expected_func_name}>", "exec")
    exec(compiled, namespace)

    if expected_func_name not in namespace or not callable(namespace[expected_func_name]):
        raise RuntimeError(f"Failed to extract callable '{expected_func_name}' from compiled patch.")

    return namespace[expected_func_name]


def execute_with_timeout(
    func: Callable,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    timeout_sec: float = 5.0,
) -> Any:
    """Execute a callable in a daemon thread with a strict timeout to protect against infinite loops or stalls."""
    result: List[Any] = []
    error: List[Exception] = []
    done_event = threading.Event()

    def worker() -> None:
        try:
            res = func(*args, **kwargs)
            result.append(res)
        except Exception as e:
            error.append(e)
        finally:
            done_event.set()

    # Daemon thread allows Python to exit cleanly without waiting if thread is stuck in an infinite loop
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    if not done_event.wait(timeout=timeout_sec):
        raise TimeoutError(
            f"Execution timed out after {timeout_sec}s (possible infinite loop or stall in patch)."
        )

    if error:
        raise error[0]

    return result[0] if result else None


def validate_contract(
    result: Any,
    schema: Optional[Type] = None,
    predicate: Optional[Callable[[Any], bool]] = None,
) -> Any:
    """Validate return value against a Pydantic schema, standard type, and optional custom predicate."""
    # 1. Custom predicate evaluation (e.g. lambda res: len(res) > 0)
    if predicate is not None:
        try:
            is_valid = bool(predicate(result))
        except Exception:
            # If predicate raises an exception (e.g. TypeError on object without len), treat gracefully as validation failure
            is_valid = False
        if not is_valid:
            raise ValueError(f"Return value failed custom validation predicate: {repr(result)}")

    if schema is None:
        return result

    # 2. Check Pydantic v2 BaseModel
    if hasattr(schema, "model_validate"):
        if isinstance(result, schema):
            return result
        validated = schema.model_validate(result)
        return validated

    # 3. Standard python type check
    if isinstance(schema, type) and not isinstance(result, schema):
        raise TypeError(
            f"Return value of type '{type(result).__name__}' does not match expected '{schema.__name__}'."
        )

    return result
