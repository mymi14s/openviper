"""Configuration package for OpenViper."""

from openviper.conf.settings import (
    Settings,
    generate_secret_key,
    settings,
    validate_settings,
)

__all__ = ["Settings", "settings", "validate_settings", "generate_secret_key"]
