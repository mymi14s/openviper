import pytest

from openviper.app import OpenViper
from openviper.routing.router import Router


def create_application(**kwargs) -> OpenViper:
    """Factory to create a OpenViper application instance."""
    return OpenViper(**kwargs)


def create_router() -> Router:
    """Factory to create a Router instance."""
    return Router()
