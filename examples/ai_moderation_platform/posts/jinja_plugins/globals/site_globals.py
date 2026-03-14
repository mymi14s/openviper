import datetime

from openviper.conf import settings


def site_name():
    """Return the site name from settings."""
    return getattr(settings, "PROJECT_NAME", "AI Moderation Platform")


def current_year():
    """Return the current year."""
    return datetime.datetime.utcnow().year


def is_debug():
    """Return whether debug mode is enabled."""
    return getattr(settings, "DEBUG", False)
