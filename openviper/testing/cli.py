"""CLI command testing utilities."""

from click.testing import CliRunner, Result


def build_cli_runner() -> CliRunner:
    """Return a Click runner with isolated filesystem support."""

    return CliRunner()


def assert_exit_code(result: Result, expected: int = 0) -> None:
    actual = result.exit_code
    output = result.output
    assert actual == expected, f"Expected exit code {expected}, got {actual}. Output: {output}"
