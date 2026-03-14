from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openviper.viperctl import viperctl


def test_viperctl_unknown_command():
    runner = CliRunner()
    result = runner.invoke(viperctl, ["invalid-cmd"])
    assert result.exit_code == 1
    assert "Unknown command" in result.output


@patch("openviper.utils.module_resolver.resolve_target")
@patch("openviper.utils.settings_discovery.discover_settings_module")
@patch("openviper.core.flexible_adapter.bootstrap_and_run")
def test_viperctl_success(mock_run, mock_settings, mock_resolve):
    mock_resolve.return_value = MagicMock()
    mock_settings.return_value = "myapp.settings"

    runner = CliRunner()
    result = runner.invoke(viperctl, ["migrate"])

    assert result.exit_code == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["command"] == "migrate"


@patch("openviper.utils.module_resolver.resolve_target")
@patch("openviper.utils.settings_discovery.discover_settings_module")
@patch("openviper.core.flexible_adapter.bootstrap_and_run")
def test_viperctl_with_settings(mock_run, mock_settings, mock_resolve):
    mock_settings.return_value = "custom.settings"
    runner = CliRunner()
    result = runner.invoke(viperctl, ["--settings", "custom.settings", "shell"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["settings_module"] == "custom.settings"
    mock_settings.assert_called_once()
    assert mock_settings.call_args[1]["explicit"] == "custom.settings"
