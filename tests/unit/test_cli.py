from unittest.mock import patch

from click.testing import CliRunner

from openviper.cli import cli


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "OpenViper" in result.output


def test_cli_create_project_invalid_name():
    runner = CliRunner()
    result = runner.invoke(cli, ["create-project", "invalid-name!"])
    assert result.exit_code == 1
    assert "not a valid Python identifier" in result.output


@patch("openviper.cli.Path.exists")
@patch("openviper.cli.Path.mkdir")
@patch("openviper.cli.Path.write_text")
@patch("openviper.cli.generate_secret_key")
@patch("os.chmod")
def test_cli_create_project_success(mock_chmod, mock_gen_key, mock_write, mock_mkdir, mock_exists):
    mock_exists.return_value = False
    mock_gen_key.return_value = "secret"

    runner = CliRunner()
    result = runner.invoke(cli, ["create-project", "myproject"])

    assert result.exit_code == 0
    assert "Project 'myproject' created" in result.output
    mock_mkdir.assert_called()
    mock_write.assert_called()


@patch("openviper.cli.subprocess.run")
def test_cli_create_app(mock_run):
    mock_run.return_value.returncode = 0
    runner = CliRunner()
    result = runner.invoke(cli, ["create-app", "myapp"])
    assert result.exit_code == 0
    mock_run.assert_called_once()


@patch("uvicorn.run")
@patch("openviper.cli.get_banner")
def test_cli_run(mock_banner, mock_uvicorn):
    runner = CliRunner()
    # Test with reload default (True)
    result = runner.invoke(cli, ["run", "app.py"])
    assert result.exit_code == 0
    mock_uvicorn.assert_called_once()
    assert mock_uvicorn.call_args[1]["reload"] is True


@patch("uvicorn.run")
def test_cli_run_no_reload(mock_uvicorn):
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "app.py", "--no-reload", "--workers", "4"])
    assert result.exit_code == 0
    assert mock_uvicorn.call_args[1]["reload"] is False
    assert mock_uvicorn.call_args[1]["workers"] == 4
