"""
AST Safety Guardrail & Isolated Sandbox Execution for KintsugiPy.
Defense-in-depth static analysis and isolated validation.
Note: Static AST checks reduce risk substantially but do not replace OS-level isolation.
"""

import ast
import concurrent.futures
import logging
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

from kintsugi.privacy import redact_sensitive_text, sanitize_runtime_value

logger = logging.getLogger("kintsugi.sandbox")

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
    "pathlib",
    "io",
    "builtins",
    "types",
    "inspect",
    "gc",
    "runpy",
    "multiprocessing",
    "threading",
    "http.client",
    "urllib.request",
    "smtplib",
}

# Strict default allowlist for newly imported modules in patches
ALLOWED_MODULES: Set[str] = {
    "re",
    "json",
    "math",
    "datetime",
    "time",
    "decimal",
    "fractions",
    "urllib.parse",
    "typing",
    "collections",
    "itertools",
    "functools",
    "copy",
    "string",
    "bisect",
    "heapq",
    "hashlib",
    "base64",
    "uuid",
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
    "hasattr",
    "dir",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "memoryview",
    "__build_class__",
    "super",
}

HTTP_VERB_METHODS: Set[str] = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
}

ALLOWED_EXTERNAL_DATA_MODULES: Tuple[str, ...] = ("pydantic", "dataclasses")


def _patch_print(*args: Any, **kwargs: Any) -> None:
    """Wrapped print with prefix to prevent log injection and spoofing."""
    if args:
        first = f"[KINTSUGI-PATCH] {args[0]}"
        print(first, *args[1:], **kwargs)
    else:
        print("[KINTSUGI-PATCH]", **kwargs)


def _safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    """Restricted __import__ that only permits whitelisted data modules."""
    base_mod = name.split(".")[0]
    if base_mod in DANGEROUS_MODULES or (base_mod not in ALLOWED_MODULES and name not in ALLOWED_MODULES):
        raise SecurityViolationError(f"Forbidden runtime import: '{name}'")
    return __import__(name, globals, locals, fromlist, level)


SAFE_BUILTINS: Dict[str, Any] = {
    "__import__": _safe_import,
    # Basic types (real classes so isinstance(x, type) remains fully functional)
    "object": object,
    "type": type,
    "bool": bool,
    "int": int,
    "float": float,
    "complex": complex,
    "str": str,
    "bytes": bytes,
    "bytearray": bytearray,
    "list": list,
    "tuple": tuple,
    "dict": dict,
    "set": set,
    "frozenset": frozenset,
    "range": range,
    "slice": slice,
    # Data manipulation & iteration functions
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "sorted": sorted,
    "reversed": reversed,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "iter": iter,
    "next": next,
    "all": all,
    "any": any,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "repr": repr,
    "format": format,
    "hash": hash,
    "id": id,
    "hex": hex,
    "oct": oct,
    "bin": bin,
    "chr": chr,
    "ord": ord,
    "pow": pow,
    "divmod": divmod,
    "print": _patch_print,
    # Exception types
    "BaseException": BaseException,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "RuntimeError": RuntimeError,
    "ArithmeticError": ArithmeticError,
    "ZeroDivisionError": ZeroDivisionError,
    "NotImplementedError": NotImplementedError,
    "StopIteration": StopIteration,
    "LookupError": LookupError,
    "AssertionError": AssertionError,
    # Standard constants
    "True": True,
    "False": False,
    "None": None,
}


def is_allowed_global_object(obj: Any, target_module: Optional[str] = None) -> bool:
    """Determine if a global object from closure_globals is safe to pass to patch namespace.
    
    Trust boundary:
    1. Local helpers from same package: mod == pkg or mod.startswith(pkg + '.') where pkg = pkg_prefix.rstrip('.')
    2. Pydantic and Dataclasses models from external packages
    3. Whitelisted pure data stdlib modules
    All other external modules and functions (e.g. os.system, sys) are strictly excluded.
    """
    mod = getattr(obj, "__module__", "") or ""
    if target_module:
        pkg_prefix = target_module.rsplit(".", 1)[0] + "." if "." in target_module else target_module
        pkg = pkg_prefix.rstrip(".")
        if mod == pkg or mod.startswith(pkg + "."):
            return True

    for ext in ALLOWED_EXTERNAL_DATA_MODULES:
        if mod == ext or mod.startswith(ext + "."):
            return True

    # Pydantic BaseModel class or instance
    try:
        from pydantic import BaseModel
        if (isinstance(obj, type) and issubclass(obj, BaseModel)) or isinstance(obj, BaseModel):
            return True
    except (ImportError, TypeError):
        pass

    # Dataclass class or instance
    if hasattr(obj, "__dataclass_fields__"):
        return True

    if isinstance(obj, type(sys)):
        base_mod = obj.__name__.split(".")[0]
        if base_mod in ALLOWED_MODULES and base_mod not in DANGEROUS_MODULES:
            return True

    return False


class SecurityViolationError(Exception):
    """Raised when proposed code violates AST safety rules."""
    pass


class ASTSafetyChecker(ast.NodeVisitor):
    """Inspects an Abstract Syntax Tree to reject insecure or disallowed constructs."""

    def __init__(
        self,
        allowed_modules: Optional[Set[str]] = None,
        inherited_modules: Optional[Set[str]] = None,
    ) -> None:
        self.allowed_modules = (allowed_modules or ALLOWED_MODULES) | (inherited_modules or set())
        self.violations: List[str] = []

    def _check_module(self, mod_name: str, is_from: bool = False) -> None:
        base_mod = mod_name.split(".")[0]
        prefix = "Forbidden module import from:" if is_from else "Forbidden module import:"
        if base_mod in DANGEROUS_MODULES or mod_name in DANGEROUS_MODULES:
            self.violations.append(f"{prefix} '{mod_name}'")
        elif base_mod not in self.allowed_modules:
            self.violations.append(f"Module '{mod_name}' is not in allowed imports list")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name, is_from=False)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._check_module(node.module, is_from=True)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.violations.append("Forbidden statement: 'global'")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.violations.append("Forbidden statement: 'nonlocal'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct builtin calls (e.g. eval(), exec(), open(), getattr())
        if isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_BUILTINS:
                self.violations.append(f"Forbidden call to builtin: '{node.func.id}()'")
            # Prevent dynamic class creation bypassing __build_class__ via type(name, bases, dict)
            elif node.func.id == "type":
                has_starred = any(isinstance(a, ast.Starred) for a in node.args)
                has_kwargs = any(k.arg is None for k in node.keywords)
                if len(node.args) > 1 or node.keywords or has_starred or has_kwargs:
                    self.violations.append(
                        "Dynamic class creation via type(name, bases, dict) is forbidden in patches."
                    )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        # Blanket ban on all dunder attributes (__*)
        if attr.startswith("__"):
            self.violations.append(f"Forbidden access to sensitive dunder attribute: '{attr}'")
        # Blanket ban on Python frame, traceback, generator, and coroutine internal attributes
        elif attr.startswith(("f_", "tb_", "gi_", "cr_", "ag_")):
            self.violations.append(f"Forbidden access to reflection attribute: '{attr}'")
        self.generic_visit(node)


def verify_code_safety(
    code: str,
    expected_func_name: str,
    allowed_modules: Optional[Set[str]] = None,
    inherited_modules: Optional[Set[str]] = None,
) -> ast.AST:
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
    checker = ASTSafetyChecker(allowed_modules=allowed_modules, inherited_modules=inherited_modules)
    checker.visit(tree)
    if checker.violations:
        raise SecurityViolationError(
            f"Code rejected due to security policy: {'; '.join(checker.violations)}"
        )

    return tree


def compile_and_extract_function(
    code: str,
    expected_func_name: str,
    closure_globals: Optional[Dict[str, Any]] = None,
    allowed_modules: Optional[Set[str]] = None,
    target_module: Optional[str] = None,
) -> Callable:
    """Compile code into an isolated memory namespace and extract the callable."""
    inherited: Set[str] = set()
    if closure_globals:
        for v in closure_globals.values():
            if isinstance(v, type(sys)):
                inherited.add(v.__name__.split(".")[0])

    verify_code_safety(
        code,
        expected_func_name,
        allowed_modules=allowed_modules,
        inherited_modules=inherited,
    )

    # Isolated namespace with SAFE_BUILTINS explicitly populated
    namespace: Dict[str, Any] = {
        "__builtins__": dict(SAFE_BUILTINS),
        "__name__": target_module or (closure_globals.get("__name__") if closure_globals else None) or f"kintsugi_patch_{expected_func_name}",
    }

    # Inherit only whitelisted and package-local objects from original globals
    if closure_globals:
        pkg_target = target_module or closure_globals.get("__name__")
        for k, v in closure_globals.items():
            if k.startswith("__"):
                continue
            if k in DANGEROUS_MODULES or k in DANGEROUS_BUILTINS:
                continue
            if is_allowed_global_object(v, target_module=pkg_target):
                namespace[k] = v

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
        except Exception as pred_exc:
            logger.warning(
                "[Kintsugi] Custom validation predicate raised %s: %s",
                type(pred_exc).__name__,
                redact_sensitive_text(str(pred_exc)),
                exc_info=True,
            )
            is_valid = False
        if not is_valid:
            safe_res = sanitize_runtime_value(result, max_len=150)
            raise ValueError(f"Return value failed custom validation predicate: {safe_res}")

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
