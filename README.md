# KintsugiPy (金継ぎ)

> **"Treat breakage and repair as part of an application's history, rather than a catastrophic failure."**

[![CI](https://github.com/zakyirhab/kintsugi-py/actions/workflows/ci.yml/badge.svg)](https://github.com/zakyirhab/kintsugi-py/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/kintsugi-py.svg?color=blue)](https://pypi.org/project/kintsugi-py/)
[![Python versions](https://img.shields.io/pypi/pyversions/kintsugi-py.svg)](https://pypi.org/project/kintsugi-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/zakyirhab/kintsugi-py/blob/main/LICENSE)
[![Tests](https://img.shields.io/badge/tests-48%20passed-brightgreen.svg)]()

<p align="center">
  <img src="assets/demo.gif" alt="KintsugiPy Autonomous Runtime Repair Demo" width="850">
</p>

**KintsugiPy** is an autonomous, self-healing runtime engine for Python functions designed for **Web Scraping, ETL pipelines, and API integrations**. When a function encounters an unhandled exception, upstream layout shift, or malformed dirty payload, KintsugiPy:

1. **Captures Crime Scene Telemetry**: Extracts function AST source, local variables, traceback, and execution context.
2. **Scrubs Sensitive Data & PII**: Automatically redacts API keys, tokens, emails, and passwords before constructing the repair prompt.
3. **Generates Surgical Patches**: Calls your LLM of choice (Local, Groq, OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter).
4. **Defense-in-Depth AST Guardrail**: Verifies candidate patches against security policies—blocking dangerous imports (`os`, `sys`, `subprocess`, `shutil`), builtins (`eval`, `exec`, `open`, `getattr`), and dunder escape chains (`__subclasses__`).
5. **Validates Contracts with Timeout**: Dry-runs the patch in an isolated execution harness with strict timeouts to prevent stalls, and verifies return contracts using **Pydantic v2** or custom predicates.
6. **In-Memory Hot-Swapping (`mode="auto"`)**: Swaps the active callable pointer in place. Future calls run the repaired code natively with **zero LLM latency**.
7. **Human-in-the-Loop (`mode="propose"`)**: For high-compliance systems, generates patch diffs and emits `HealReport` proposals without modifying runtime execution.
8. **Tamper-Resistant Cache**: Persists validated patches with HMAC integrity checks and AST re-verification to `.kintsugi_cache/` for zero-token cold starts.

---

## ⚡ Key Highlights

- **Zero Heavy Vendor SDKs**: Engineered cleanly on top of `httpx` and `pydantic`. No bloated 500MB cloud client packages.
- **ParamSpec Type Preservation**: Full IDE autocompletion and type-checking remain 100% intact when using `@heal`.
- **Thundering Herd Concurrency Shield**: Built-in **Double-Checked Locking** (`asyncio.Lock` & `threading.Lock`). When 50 concurrent tasks fail simultaneously in `asyncio.gather()`, exactly **1** LLM repair call is made—the other 49 tasks wait and seamlessly reuse the hot-swapped function.
- **Automatic Secret & PII Redaction**: Strips OpenAI/Anthropic/Groq keys, JWTs, Bearer tokens, passwords, and credit cards before communicating with LLMs. Option to transmit `signature_only=True` (structural shapes only).
- **Dual Execution Modes**: Choose between autonomous in-memory hot-swapping (`mode="auto"`) or enterprise human-in-the-loop proposals (`mode="propose"`).
- **Rich Observability Telemetry**: Inspect runtime repairs with `HealReport`, providing unified git-style code diffs, root-cause tracebacks, attempt counts, and provider metadata.
- **AST-Aware Caching & Stale Pruning**: Ignores comments and whitespace variations when hashing, avoiding false cache invalidations. Obsolete patch versions are automatically cleaned up from `.kintsugi_cache/`.
- **Universal Provider Engine**: Direct REST wire adapters for Anthropic (`/v1/messages`), Google Gemini (`generateContent`), OpenAI-compatible endpoints (`/v1/chat/completions`), and local runtimes (LM Studio, Ollama, vLLM).

---

## 📦 Installation

```bash
# Using pip
pip install kintsugi-py

# Using uv
uv add kintsugi-py

# Using poetry
poetry add kintsugi-py
```

---

## 🚀 Quickstart

### 1. Basic Usage (Zero Configuration Auto-Detection)

Set an API key in your environment (or pass it directly):

```bash
export GROQ_API_KEY="gsk_..."
```

Decorate your brittle function with `@heal`:

```python
from kintsugi import heal

@heal()
def parse_price(data: dict) -> int:
    # Fragile code expects int under 'price' key
    return data["price"]

# Normal call passes natively
print(parse_price({"price": 100}))  # 100

# Upstream payload breaks: key changed to 'cost' with currency string!
# Kintsugi intercepts the KeyError, heals the function, and hot-swaps it in memory:
print(parse_price({"cost": "$250"}))  # 250

# All subsequent calls now run the healed code with 0ms LLM latency!
print(parse_price({"cost": "$500"}))  # 500
```

---

### 2. Enterprise Mode (`mode="propose"`)

In mission-critical or compliance-heavy pipelines, automated runtime code execution might be unacceptable. Use `mode="propose"` to generate patch proposals for human review without modifying active code:

```python
from kintsugi import heal, HealReport, ProposedPatchError

def alert_slack(report: HealReport):
    print(f"Proposed patch for {report.func_name}:\n{report.diff}")

@heal(mode="propose", on_heal=alert_slack)
def parse_invoice(data: dict) -> dict:
    return {"id": data["invoice_id"], "total": data["amount"]}

try:
    parse_invoice({"id": "INV-101", "sum": 250})
except ProposedPatchError as err:
    print("Function untouched in memory. Review the generated proposal.")
```

---

### 3. Silent Failure Detection with `validate` Predicate

Web scrapers often don't crash when selectors break; instead, they return empty lists `[]` or `{}`. The `validate` predicate catches silent semantic failures and triggers healing:

```python
from kintsugi import heal

@heal(validate=lambda items: isinstance(items, list) and len(items) > 0)
def scrape_catalog(html: str) -> list:
    # If the CSS selector changed, this might silently return []
    if 'class="product">' in html:
        return [html.split('product">')[1].split('<')[0]]
    return []
```

---

### 4. Privacy & Secret Redaction (`signature_only`)

For sensitive environments, prevent actual data values from ever leaving your machine:

```python
from kintsugi import heal

@heal(signature_only=True)
def process_user_record(payload: dict) -> str:
    # Kintsugi sends only types and shapes to LLM: e.g. <dict len=5 keys=['email', 'token']>
    # No passwords, tokens, or PII ever touch the network.
    return payload["username"]
```

---

### 5. Contract Enforcement with Pydantic v2

Guarantee strict data integrity even through automated repairs:

```python
from pydantic import BaseModel
from kintsugi import heal

class UserProfile(BaseModel):
    name: str
    age: int
    is_active: bool

@heal(schema=UserProfile)
def extract_user(raw_data: dict) -> dict:
    return {
        "name": raw_data["user_name"],
        "age": raw_data["years_old"],
        "is_active": raw_data["active_flag"]
    }

# Even if upstream API responds with string numbers or shifted keys:
dirty_payload = {"user_name": "Zaky", "years_old": "24", "active_flag": 1}
user = extract_user(dirty_payload)

assert isinstance(user, UserProfile)
assert user.age == 24
assert user.is_active is True
```

---

### 6. Local LLM / Privacy-First Mode (LM Studio / Ollama)

Run completely offline with zero API costs using local coding models:

```python
import kintsugi

kintsugi.configure(
    provider="local",
    base_url="http://localhost:1234/v1",
    model="qwen2.5-coder-14b-instruct"
)

@kintsugi.heal()
def calculate_tax(order: dict) -> float:
    return order["subtotal"] * order["tax_rate"]
```

---

### 7. Asynchronous Coroutines & Concurrency Shield

KintsugiPy fully supports modern `async`/`await` workflows with **Double-Checked Locking**. Only 1 LLM repair request is made even if 100 concurrent tasks fail simultaneously:

```python
import asyncio
from kintsugi import heal

@heal(max_retries=3)
async def fetch_stock_quote(symbol: str) -> dict:
    ...

# 50 concurrent calls crash on layout change -> exactly 1 LLM repair performed!
results = await asyncio.gather(*(fetch_stock_quote("AAPL") for _ in range(50)))
```

---

## 🛡️ AST Safety & Defense-in-Depth

> **Note on Security**: Kintsugi's guardrail is a static safety heuristic designed to prevent accidental damage and common sandbox escape vectors. It reduces risk substantially but **is not an OS-level sandbox**. For untrusted or multi-tenant code execution, always run inside isolated containers.

| Rule | Enforcement | Result |
| :--- | :--- | :--- |
| **Forbidden Modules** | `import os`, `sys`, `subprocess`, `shutil`, `pty`, `ctypes`, `importlib` | ❌ `SecurityViolationError` |
| **Forbidden Imports** | `from os import path`, `from subprocess import run` | ❌ `SecurityViolationError` |
| **Dangerous Builtins** | `eval()`, `exec()`, `open()`, `__import__()`, `input()`, `getattr()`, `globals()`, `locals()` | ❌ `SecurityViolationError` |
| **Dunder Escape Chains** | Access to `__subclasses__`, `__bases__`, `__globals__`, `__builtins__`, `__code__` | ❌ `SecurityViolationError` |
| **Loop/Timeout Protection** | Patches are tested with strict daemon thread timeouts | ❌ `TimeoutError` on stalls |
| **Safe Pure Logic** | `re`, `json`, `math`, `datetime`, `urllib.parse`, string slicing | ✅ Validated & Approved |

---

## ⚙️ Configuration Reference

### `@heal` Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `schema` | `Type[BaseModel]` / `Type` | `None` | Optional Pydantic model or expected return type. |
| `validate` | `Callable[[Any], bool]` | `None` | Custom validation predicate (catches silent empty results like `[]` or `{}`). |
| `mode` | `Literal["auto", "propose"]` | `"auto"` | `"auto"` hot-swaps in memory; `"propose"` generates patch proposals for human review. |
| `idempotent` | `bool` | `True` | Set `False` if failing inputs have external side effects (skips dry-run replay). |
| `signature_only` | `bool` | `False` | Send only parameter shapes/types to LLM without leaking real data values. |
| `include_args` | `bool` | `True` | Set `False` to omit runtime crash arguments entirely from the prompt. |
| `dry_run_timeout` | `float` | `5.0` | Maximum seconds allowed for dry-run testing before rejecting patch. |
| `max_retries` | `int` | `3` | Maximum LLM repair iterations on recurring errors. |
| `provider` | `str` | `None` | Explicit provider name (`openai`, `groq`, `anthropic`, `gemini`, `deepseek`, `openrouter`, `local`). |
| `model` | `str` | `None` | Model identifier (e.g. `llama-3.3-70b-versatile`, `claude-3-5-sonnet-20241022`). |
| `cache_dir` | `str` / `None` | `".kintsugi_cache"` | Directory for HMAC-signed patches. Set `None` to disable disk caching. |
| `chain` | `List[dict \| LLMProvider]` | `None` | Ordered list of fallback providers. |
| `on_heal` | `Callable[[HealReport], Any]` | `None` | Event callback triggered when a function is healed or proposed. |

---

## 📂 Runnable Examples

Explore the [`examples/`](https://github.com/zakyirhab/kintsugi-py/tree/main/examples) directory:

- [`01_quickstart.py`](https://github.com/zakyirhab/kintsugi-py/blob/main/examples/01_quickstart.py): Basic exception intercept & hot-swapping.
- [`02_pydantic_contracts.py`](https://github.com/zakyirhab/kintsugi-py/blob/main/examples/02_pydantic_contracts.py): Output coercion with strict data models.
- [`03_async_resilient_scraper.py`](https://github.com/zakyirhab/kintsugi-py/blob/main/examples/03_async_resilient_scraper.py): Asynchronous web scraping resilience.
- [`04_enterprise_propose_mode.py`](https://github.com/zakyirhab/kintsugi-py/blob/main/examples/04_enterprise_propose_mode.py): Human-in-the-loop proposals & secret redaction.

---

## 🧪 Testing

```bash
uv run pytest -v
```

---

## 📄 License

Released under the [MIT License](LICENSE). Designed and built with precision by [Zaky Irhab](https://zakyirhab.it.com/).
