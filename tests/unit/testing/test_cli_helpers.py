"""Tests for OpenViper CLI testing helpers."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from openviper.testing.cli import assert_exit_code, build_cli_runner


@click.command()
def success_command() -> None:
    click.echo("done")


@click.command()
def failure_command() -> None:
    raise SystemExit(1)


@click.command()
@click.argument("name")
def greet_command(name: str) -> None:
    click.echo(f"Hello, {name}!")


def test_build_cli_runner_returns_click_runner() -> None:
    runner = build_cli_runner()

    assert isinstance(runner, CliRunner)


def test_cli_runner_can_invoke_a_successful_command() -> None:
    runner = build_cli_runner()

    result = runner.invoke(success_command)

    assert result.exit_code == 0
    assert "done" in result.output


def test_cli_runner_captures_command_output() -> None:
    runner = build_cli_runner()

    result = runner.invoke(greet_command, ["World"])

    assert "Hello, World!" in result.output


def test_assert_exit_code_passes_for_expected_zero() -> None:
    runner = build_cli_runner()
    result = runner.invoke(success_command)

    assert_exit_code(result, 0)


def test_assert_exit_code_fails_for_unexpected_code() -> None:
    runner = build_cli_runner()
    result = runner.invoke(success_command)

    with pytest.raises(AssertionError, match="exit code"):
        assert_exit_code(result, 1)


def test_assert_exit_code_default_expected_is_zero() -> None:
    runner = build_cli_runner()
    result = runner.invoke(success_command)

    assert_exit_code(result)


def test_assert_exit_code_includes_output_in_failure_message() -> None:
    runner = build_cli_runner()
    result = runner.invoke(greet_command, ["Test"])

    with pytest.raises(AssertionError, match="Hello, Test!"):
        assert_exit_code(result, 99)
