# AGENTS.md

## System Instructions for AI Coding Agents
**File Scope:** Global repository constraints
**Applicability:** All AI assistants, LLM agents, Copilot, and IDE extensions (Cursor, VS Code)
**Strict Enforcement:** Any generated code violating these guidelines will be rejected. Code generation must prioritize security, architectural isolation, and deterministic performance.

---

## 1. Python Environment & Syntax

* **Target Runtime:** Python 3.14 or newer (`target-version = "py314"`).
* **Syntax Version:** Modern Python 3 syntax only. Legacy, fallback, or deprecated constructs are strictly forbidden.
* **Type Safety:**
  * Strict static typing is mandatory for all modules, public functions, and methods.
  * Avoid the use of `Any`. Prefer explicit structural typing (`t.Protocol`), generics (`t.TypeVar`), or exact matching type hints.
  * Code must pass rigid `mypy --strict` verification without type-ignore overrides.

---

## 2. Compilation, Import, & Clean Architecture Rules

* **Naming Conventions:**
  * Functions and methods **must not start with a leading underscore (`_`)** unless strictly necessary (e.g., explicitly declared private class methods or required framework lifecycle overrides). Global/module-level functions must never use a leading underscore.
  * **Alias Renaming Prohibition:** Defining a public symbol with a leading underscore and then reassigning it to an underscore-free name is strictly forbidden. For example, `_MissingDriverAsyncEngine = MissingDriverAsyncEngine` is rejected - define the symbol directly as `MissingDriverAsyncEngine` without the leading-underscore prefix. This pattern obscures intent, pollutes module namespaces with redundant bindings, and violates the principle that naming should be explicit at the point of definition.
* **Import Placement:** All imports must be positioned cleanly at the module level (the top of the file).
* **Inline Imports:** Inline imports (`import` statements nested inside functions, methods, or loops) are completely forbidden.
* **DRY Principle (Don't Repeat Yourself):** Code duplication is strictly prohibited. Abstract repetitive logic into clean, reusable utility functions, classes, or helper modules.
* **Performance-First Architecture:**
  * Select algorithmic data structures based on time/space complexity profiles (e.g., `dict` or `set` for $O(1)$ lookups, `collections.deque` for fast queue-like modifications).
  * Eliminate redundant iterations, nested loops over heavy collections, or repetitive computational pipelines.
  * Utilize lazy evaluation patterns, stream abstractions, or generators when processing massive runtime payloads.
  * Always optimize critical execution paths to guarantee high-performance throughput without micro-optimizing at the cost of baseline readability.

---

## 3. Strict Context Modification Guardrail

* **Zero-Unsolicited Scope Changes:** Do not alter, refactor, reorganize, or "clean up" any section of the codebase outside the exact lines required to fulfill the current explicit prompt.
* **Preservation of Behavior:** Maintain intact logic boundaries for all existing surrounding modules. Ensure total structural compatibility with unchanged integrations.
* **Explicit Change Tracking:** Modify only the minimal footprint required. Do not perform unsolicited upgrades on project dependencies, file formatting, or layout paradigms.

---

## 4. Mandatory Security Matrix

AI agents must proactively implement protections against the following framework and platform security vulnerabilities:

### A. HTTP Handling & Routing
* **Path Normalization:** Sanitize paths cleanly before routing or file evaluation. Explicitly neutralize directory traversal tokens (`../`), encoded slashes (`%2f`), and double-decoding edge cases.
* **Host Header Validation:** Do not trust the raw `Host` header for building redirect URLs, password reset links, or determining multi-tenant boundaries. Force validation against a strict whitelist.
* **Open Redirects:** Explicitly block open redirects by forcing redirect targets to pass an internal/whitelist verification routine.
* **Parameter Pollution & Methods:** Ensure middleware and router chains handle duplicate query parameters and HTTP method-override structures cleanly and safely without state confusion.

### B. State Isolation & Middleware
* **Concurrency State Overlap:** Never use class variables, mutable globals, or unmanaged shared instances to store temporary request parameters or session data.
* **Async Context Locks:** Enforce request isolation inside async tasks exclusively using `contextvars` to prevent multi-tenant or multi-user state bleeding under heavy load.

### C. Input Neutralization & Data Layers
* **Injection Defense:** All database interactions must use parameterized queries or explicit ORM filters. Raw SQL interpolation, unvalidated string manipulation, and unchecked NoSQL operator parsing (e.g., `$ne`, `$gt`) are completely banned.
* **Mass Assignment Mitigation:** Do not bind incoming raw JSON objects or request forms directly to internal models or database records. Implement explicit schema serialization and payload mapping whitelists.
* **XSS & Template Injection:** Ensure all dynamic output rendering defaults to auto-escaping. Explicitly separate HTML context from inline Javascript/CSS variable bindings.

### D. File Handling & Authentication
* **Upload Security:** Validate file uploads using structural contents, not MIME-type or file extension strings alone. Prevent Zip-Slip vulnerabilities by asserting that absolute destination paths match targeted directories.
* **Session Lifecycle:** Always rotate session tokens upon authentication state mutations. Long-lived credentials or tokens must be cryptographically protected using verified algorithms (e.g., Argon2id, HS256/RS256 with strict expiration checks).

---

## 5. Commenting, Documentation, & Error Suppression

* **Intent-Driven Meaningful Comments:** Comments must be meaningful and only added when **strictly necessary**. They must explain the systemic *intent* or underlying architectural *reasoning* (the "why"), rather than restating what the code visibly does.
* **PEP 8 Compliance:** All comments must fully adhere to **PEP 8 standards** (e.g., use complete sentences, include a single space after the `#` character, maintain proper indentation relative to the block, and keep line lengths under 72 characters for blocks/inline comments).
* **Forbidden Comment Practices:**
  * Do not write structural narration or describe literal line mechanics (the "what").
  * Never include tracking notes, git-like summaries, or comments that reference specific line numbers (e.g., `# fixed line 42` or `# updated block`).
  * Never include the file name or any references to standards, guidelines, or other source code files (e.g., referencing `AGENTS.md` or the current file name) in any comment.
  * **Feature-Only Commentary:** Comments and documentation strings must describe the current feature, capability, or behavior only. Never describe the reason for an edit, what a block replaces, what was migrated from, or how code used to be written. Phrases such as "replaces hand-written ...", "replaces the old ...", "migrates from ...", "formerly ...", or "legacy ..." that narrate the editing rationale are strictly forbidden. Describe what the code does now, not what it superseded.
* **Concise Documentation:** Codebase documentation strings (`__doc__`) must be minimal, objective, and technical. Focus directly on parameter typing, output bounds, side effects, and structural constraints. Eliminate tutorial-like, conversational, or narrative prose.
* **Hyphen Restriction:** The long dash character (`—`, U+2014 EM DASH) is strictly forbidden in all code, comments, documentation strings, and generated text. Use only the standard short hyphen-minus (`-`, U+002D HYPHEN-MINUS) for dashes, ranges, and compound terms. This applies universally across Python source, Markdown, configuration files, and any other generated content.

---

## 6. Formatting & Validation Pipeline

All generated or refactored code must pass standard programmatic linting checks cleanly without requiring developer intervention. Ensure code satisfies:
* **Ruff:** Security (`S`), Bugbear (`B`), and Asynchronous (`ASYNC`) checking rules enabled.
* **MyPy:** Full strict type checking compliance.
* **Pylint & Flake8:** Clean evaluations without legacy warnings.

---

## 7. Deterministic Testing Requirements

Tests must be written under the **pytest** framework and maintain the following strict engineering constraints:
* **Determinism:** Tests must yield identical outcomes regardless of execution order, execution count, or timing parameters.
* **Isolation:** Tests must reside within cleanly isolated execution cycles. External states, network layers, and file dependencies must be mocked or managed deterministically.
* **Minimal Mocking:** Avoid abstract or deep mocking chains; favor thin structural fixtures or tightly defined interfaces.
* **Naming Standards:** Test function names must be explicitly descriptive of the scenario under test (e.g., `test_endpoint_rejects_unvalidated_host_header`).

---

## 8. Explicit Reference Target Implementation

Ensure all generated source code mirrors the structural and defensive patterns demonstrated below:

```python
import typing as t
from urllib.parse import urlparse
from contextvars import ContextVar

# Module-level imports only. Strict typing enforced.
tenant_context: ContextVar[str] = ContextVar("tenant_context")


class SecurityGateway:
    """Core request pipeline guard enforcing safe routing bounds."""

    def __init__(self, allowed_hosts: t.Sequence[str]) -> None:
        self.allowed_hosts: set[str] = set(allowed_hosts)

    def resolve_safe_redirect(self, target: str, host_header: str) -> str:
        """Evaluate a target URL path and filter out path traversal or open redirect risks.

        Raises RuntimeError if contextual isolation boundary checks fail.
        """
        # Mitigate Host Header injection and directory parsing attacks.
        # This implementation scales efficiently via O(1) set host lookups.
        if host_header not in self.allowed_hosts:
            return "/error/invalid-host"

        sanitized = target.strip()
        if sanitized.startswith("/") and not sanitized.startswith("//"):
            if ".." in sanitized:
                return "/error/unsafe-path"
            return sanitized

        parsed = urlparse(sanitized)
        if parsed.scheme in {"http", "https"} and parsed.netloc == host_header:
            return sanitized

        return "/error/unsafe-redirect"
