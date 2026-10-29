# Contributing to KintsugiPy

Thank you for your interest in improving KintsugiPy! We welcome bug reports, documentation enhancements, feature proposals, and pull requests.

---

## 🛠️ Development Setup

KintsugiPy uses [`uv`](https://docs.astral.sh/uv/) for fast, deterministic Python environment management.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/zakyirhab/kintsugi-py.git
   cd kintsugi-py
   ```

2. **Install dependencies**:
   ```bash
   uv sync --extra dev
   ```

3. **Run tests**:
   ```bash
   uv run pytest -v
   ```

---

## 📐 Code Style & Conventions

- **Type Annotations**: All public APIs and internal functions must include Python type hints.
- **AST Safety Rules**: Any modification to `kintsugi/sandbox.py` must maintain strict blocking of arbitrary system code execution (`os`, `sys`, `subprocess`, `eval`, `exec`, `open`).
- **Zero Heavy SDKs**: We deliberately avoid adding vendor SDKs (like `openai` or `anthropic`) as hard dependencies. Providers are implemented via direct, lightweight `httpx` REST calls.

---

## 🧪 Submitting Pull Requests

1. Fork the repo and create your feature branch:
   ```bash
   git checkout -b feat/my-new-feature
   ```

2. Add corresponding unit tests in `tests/`.

3. Ensure all tests pass:
   ```bash
   uv run pytest
   ```

4. Commit your changes with concise messages and submit a Pull Request against `main`.

---

## 📄 License
By contributing to KintsugiPy, you agree that your contributions will be licensed under the [MIT License](LICENSE).
