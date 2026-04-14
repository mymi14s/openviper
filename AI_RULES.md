# AI Python Coding Rules

These rules apply to **all AI-generated Python code** in this repository.
AI assistants (Copilot, Cursor, LLM agents, etc.) must follow them at all times.

---

# Python Version

* All code **must target Python 3.14 or newer**.
* Use modern Python features where appropriate.
* Avoid deprecated or legacy syntax.
* **Python 3 syntax only is allowed**.

---

# Import Rules

* **Inline imports are not allowed.**
* All imports must appear **at the top of the module**.
* Imports should be grouped and ordered according to best practices.

Correct example:

```python
from pathlib import Path
import json
import typing as t
```

Incorrect example:

```python
def load_data():
    import json
```

---

# Comment Rules

Comments must explain **intent or reasoning**, not implementation mechanics.

The following are **not allowed**:

* Comments referencing **line numbers**
* Comments describing **what changed on a specific line**
* Comments such as:

```python
# changed line 42
# fixed line 18
# update on line 10
```

Acceptable comments explain **why** something exists.

Example:

```python
# Validate user input before performing database operations
```

---

# Code Quality Standards

All generated code must:

* Follow **PEP 8**
* Be **readable and maintainable**
* Prefer **explicit code over clever code**
* Avoid unnecessary complexity
* Use descriptive variable and function names
* Follow clean architecture principles where applicable

---

# Type Hints

* Use **type hints** for all public functions and methods.
* Prefer **explicit typing** instead of `Any` when possible.
* Ensure the code passes **MyPy type checking**.

Example:

```python
def load_config(path: str) -> dict[str, str]:
    ...
```

---

# Formatting and Linting Requirements

All generated code must be compatible with the following tools:

* **Black** – formatting
* **Ruff** – linting
* **MyPy** – static type checking
* **Flake8**
* **Pylint**

Code should pass these tools **without requiring manual fixes**.

---

# Testing Rules

Tests must follow **pytest best practices**.

Requirements:

* Tests must be **deterministic**
* Tests must be **isolated**
* Avoid unnecessary mocking
* Use clear and descriptive test names

Example:

```python
def test_user_creation_returns_valid_id() -> None:
    ...
```

The following are **not allowed in tests**:

* Comments referencing line numbers
* Inline imports
* Fragile assertions tied to specific implementation lines

---

## Documentation Rules

* **Only technical documentation is allowed.**
* Documentation must be **concise and necessary**.
* Avoid unnecessary explanations, verbose comments, or redundant documentation.
* Documentation must focus on:
  * API behavior
  * Parameters and return values
  * Constraints and assumptions

**Not allowed**:

* Redundant comments
* Narrative explanations
* Over-documentation
* Tutorial-style documentation
* Comments that restate obvious code behavior

**Correct example**:

```python
def hash_password(password: str) -> str:
    """Return a secure SHA-256 hash of the given password."""
```

---

# General AI Instructions

When generating Python code:

1. Ensure the code is compatible with **Python ≥3.14**.
2. Place **all imports at the module level**.
3. Never include comments referencing **line numbers**.
4. Ensure compatibility with **Black, Ruff, MyPy, Flake8, and Pylint**.
5. Prefer **clean, production-grade Python code**.
6. Follow **Python best practices and PEP 8** at all times.
7. Write code that is **clear, typed, and maintainable**.

---
### Requirements

1. **Efficient Data Structures:** Use the most appropriate data structures for the task (e.g., `dict` for fast lookups, `set` for uniqueness checks, `deque` for queue operations).
2. **Minimize Loops and Computations:** Avoid redundant loops, repeated calculations, or unnecessary iterations.
3 **Memory Efficiency:** Avoid excessive memory allocations; reuse objects where possible.
4. **Lazy Evaluation:** Use lazy loading or generators to handle large datasets efficiently.
5. **Standard Library Optimization:** Prefer optimized, built-in Python functions and libraries over manual implementations.
6. **Avoid Blocking Operations:** Use asynchronous operations when applicable to prevent bottlenecks.
7. **Scalability:** Write code that scales efficiently with larger inputs.
8. **Avoid Premature Optimization:** Optimize critical paths but maintain readability; do not sacrifice clarity for micro-optimizations.
9. **Security-Conscious Coding:** Always validate and sanitize inputs, handle exceptions properly, avoid exposing sensitive data, and follow best practices to prevent common vulnerabilities such as injection attacks, buffer overflows, or insecure data handling.

---

# Priority of Rules

If an AI tool generates code that violates these rules, the rules in this document **override the generated output**.

# ⚠️ Strict Context Modification Rule

## Objective
Ensure that only code directly related to the current task or context is modified.

## Rules

1. **Do NOT modify unrelated code**
   - Any feature, function, file, or logic not explicitly مرتبط (related) to the current request must remain unchanged.
   - Avoid refactoring, renaming, or optimizing unrelated sections.

2. **Limit changes strictly to scope**
   - Only edit the minimal set of lines required to complete the task.
   - Do not introduce changes outside the defined context.

3. **Preserve existing behavior**
   - Existing functionality must continue to work exactly as before unless explicitly instructed otherwise.

4. **No unsolicited improvements**
   - Do not “clean up,” “optimize,” or “improve” code outside the requested scope.
   - Do not upgrade dependencies, change formatting, or reorganize structure unless required.

5. **Respect surrounding code**
   - Maintain compatibility with the existing architecture and coding style.
   - Do not break integrations with other modules.

6. **Be explicit about changes**
   - Clearly indicate what was changed and why.
   - If unsure whether something is in scope, do not modify it.
