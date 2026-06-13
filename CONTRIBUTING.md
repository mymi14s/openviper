# Contributing to OpenViper

First off, thank you for considering contributing to OpenViper! It's people like you that make OpenViper such a great tool.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the existing issues as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible.

### Suggesting Enhancements

If you have a great idea for OpenViper, please open an issue to discuss it.

### Your First Code Contribution

Unsure where to begin contributing to OpenViper? You can start by looking through `help wanted` and `good first issue` issues.

### Pull Requests

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints.

## Styleguides

### Git Commit Messages

* Use the present tense ("Add feature" not "Added feature")
* Use the imperative mood ("Move cursor to..." not "Moves cursor to...")
* Limit the first line to 72 characters or less
* Reference issues and pull requests liberally after the first line

### Python Styleguide

All Python code is formatted with `black` and linted with `ruff`.

Key conventions (see `AGENTS.md` for full details):

- **Python 3.14+** syntax only. No legacy constructs.
- **Strict typing** - `mypy --strict` must pass. Avoid `Any`.
- **No leading underscores** on functions or methods unless truly necessary (e.g., framework dunder overrides). Global/module-level functions must never use a leading underscore.
- **No alias renaming** - defining `_Foo = Foo` is forbidden. Name symbols directly without the underscore prefix.
- **DRY** - extract repetitive logic into shared helpers. No duplicated code blocks.
- **All imports at module level** - inline imports inside functions are forbidden.
- **No inline comments describing what the code does** - comments explain *why*, not *what*.
- **Security-first** - parameterized queries, input validation, path normalization, session rotation, and no raw string interpolation in SQL.

### Documentation Styleguide

We use Sphinx and reStructuredText (RST) for documentation. Please ensure any new features are documented in the `docs/` directory.

## Questions?

Feel free to open an issue with your questions or join our community discussions.
