"""Public domain gateway contracts."""

from app.domain.ports.line_messaging import LineMessageGateway
from app.domain.ports.staff_auth import StaffAuthenticator

__all__ = ["LineMessageGateway", "StaffAuthenticator"]
