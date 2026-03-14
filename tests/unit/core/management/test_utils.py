"""Unit tests for openviper.core.management.utils — management command utilities."""

from unittest.mock import Mock, patch

from openviper.core.management.base import BaseCommand
from openviper.core.management.utils import get_banner, print_banner


class TestGetBanner:
    """Test get_banner function."""

    def test_get_banner_basic(self, capsys):
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "127.0.0.1", 8000)

        captured = capsys.readouterr()
        assert "OpenViper" in captured.out
        assert "http://127.0.0.1:8000/" in captured.out
        assert "Ctrl+C" in captured.out

    def test_get_banner_custom_host_port(self, capsys):
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "0.0.0.0", 3000)

        captured = capsys.readouterr()
        assert "http://0.0.0.0:3000/" in captured.out

    def test_get_banner_styled_output(self, capsys):
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "localhost", 8080)

        captured = capsys.readouterr()
        # Should have green color codes from style_success
        assert "\033[32m" in captured.out
        assert "\033[0m" in captured.out

    def test_get_banner_ascii_art(self, capsys):
        """Test that ASCII art is displayed."""
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "127.0.0.1", 8000)

        captured = capsys.readouterr()
        # Check for some ASCII art patterns
        assert "OOOOO" in captured.out
        assert "PPPPP" in captured.out
        assert "EEEEE" in captured.out
        assert "RRRR" in captured.out  # Changed from "VIPER" to match actual ASCII art


class TestPrintBanner:
    """Test print_banner function."""

    def test_print_banner_with_cmd_obj(self, capsys):
        cmd_obj = BaseCommand()
        print_banner("127.0.0.1", 8000, cmd_obj=cmd_obj)

        captured = capsys.readouterr()
        assert "OpenViper" in captured.out
        assert "http://127.0.0.1:8000/" in captured.out

    def test_print_banner_without_cmd_obj(self, capsys):
        """Test that print_banner creates a BaseCommand if none provided."""
        print_banner("localhost", 3000, cmd_obj=None)

        captured = capsys.readouterr()
        assert "OpenViper" in captured.out
        assert "http://localhost:3000/" in captured.out

    def test_print_banner_custom_host_port(self, capsys):
        print_banner("0.0.0.0", 5000)

        captured = capsys.readouterr()
        assert "http://0.0.0.0:5000/" in captured.out

    def test_print_banner_ipv6(self, capsys):
        """Test with IPv6 address."""
        print_banner("::1", 8000)

        captured = capsys.readouterr()
        assert "http://::1:8000/" in captured.out

    def test_print_banner_high_port(self, capsys):
        """Test with high port number."""
        print_banner("127.0.0.1", 65535)

        captured = capsys.readouterr()
        assert "http://127.0.0.1:65535/" in captured.out


class TestBannerIntegration:
    """Test banner functions integration."""

    def test_get_banner_calls_stdout(self):
        """Test that get_banner uses cmd_obj.stdout."""
        mock_cmd = Mock()
        mock_cmd.style_success = Mock(side_effect=lambda x: f"[STYLED]{x}")

        get_banner(mock_cmd, "127.0.0.1", 8000)

        # Should have called stdout once
        mock_cmd.stdout.assert_called_once()

        # Get the call argument
        call_args = mock_cmd.stdout.call_args[0][0]
        assert "OpenViper" in call_args
        assert "127.0.0.1:8000" in call_args

    def test_print_banner_creates_basecommand_internally(self):
        """Test that print_banner creates BaseCommand when cmd_obj is None."""
        with patch("openviper.core.management.utils.BaseCommand") as MockBaseCommand:
            mock_instance = Mock()
            MockBaseCommand.return_value = mock_instance
            mock_instance.style_success = Mock(side_effect=lambda x: x)

            print_banner("127.0.0.1", 8000, cmd_obj=None)

            MockBaseCommand.assert_called_once()

    def test_banner_content_includes_all_elements(self, capsys):
        """Test that banner includes all expected elements."""
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "127.0.0.1", 8000)

        captured = capsys.readouterr()
        output = captured.out

        # Check all expected elements
        assert "OpenViper" in output
        assert "development server" in output
        assert "http://127.0.0.1:8000/" in output
        assert "Ctrl+C" in output or "Ctrl-C" in output
        assert "stop" in output


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_get_banner_with_mock_styling(self):
        """Test banner with mocked styling functions."""
        mock_cmd = Mock()
        mock_cmd.stdout = Mock()

        def mock_style(text):
            return f"<styled>{text}</styled>"

        mock_cmd.style_success = mock_style

        get_banner(mock_cmd, "127.0.0.1", 8000)

        mock_cmd.stdout.assert_called_once()
        call_arg = mock_cmd.stdout.call_args[0][0]
        assert "<styled>" in call_arg
        assert "</styled>" in call_arg

    def test_print_banner_port_zero(self, capsys):
        """Test with port 0 (system-assigned port)."""
        print_banner("127.0.0.1", 0)

        captured = capsys.readouterr()
        assert "http://127.0.0.1:0/" in captured.out

    def test_get_banner_empty_host(self, capsys):
        """Test with empty host string."""
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "", 8000)

        captured = capsys.readouterr()
        assert "http://:8000/" in captured.out

    def test_banner_output_format(self, capsys):
        """Test that banner has proper formatting and line breaks."""
        cmd_obj = BaseCommand()
        get_banner(cmd_obj, "127.0.0.1", 8000)

        captured = capsys.readouterr()
        output = captured.out

        # Should have multiple lines
        lines = output.split("\n")
        assert len(lines) > 5

        # Should have some indentation or spacing
        assert any(line.strip() != line for line in lines if line)
