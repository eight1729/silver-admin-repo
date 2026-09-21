"""Explicit Staff-only preparation and approved manual registration."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from app.db.admin_tables import staff_identities, staff_service_permissions


ADMIN_STAFF_TABLES = (staff_identities, staff_service_permissions)


def create_admin_staff_tables(connection: Connection) -> tuple[str, ...]:
    for table in ADMIN_STAFF_TABLES:
        table.create(connection, checkfirst=True)
    return tuple(table.name for table in ADMIN_STAFF_TABLES)


class StaffRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    staff_id: UUID
    identity_provider: str
    external_subject: str
    email: str | None = None
    display_name: str | None = None
    active: StrictBool
    service_id: str
    role: Literal["viewer", "sender", "admin"]

    @field_validator("identity_provider", "external_subject", "service_id")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must be nonempty")
        return value  # No identity normalization or aliasing here.

    @field_validator("identity_provider")
    @classmethod
    def canonical_issuer(cls, value: str) -> str:
        if value != value.rstrip("/"):
            raise ValueError("issuer must match the canonical OIDC issuer without trailing slashes")
        return value


def register_admin_staff(connection: Connection, registration: StaffRegistration) -> None:
    """Upsert one approved identity/service pair; never rebind an existing identity.

    The caller owns the outer transaction. A savepoint also prevents partial
    registration if a caller catches a uniqueness/permission write failure.
    """
    registration = StaffRegistration.model_validate(registration.model_dump())
    staff_id = str(registration.staff_id)
    with connection.begin_nested():
        current = connection.execute(select(staff_identities).where(
            staff_identities.c.staff_id == staff_id).with_for_update()).mappings().first()
        identity = dict(identity_provider=registration.identity_provider,
                        external_subject=registration.external_subject)
        if current is not None and any(current[key] != value for key, value in identity.items()):
            raise ValueError("existing staff identity cannot be rebound")
        values = dict(**identity, email=registration.email,
                      display_name=registration.display_name, active=registration.active)
        if current is None:
            connection.execute(insert(staff_identities).values(staff_id=staff_id, **values))
        else:
            connection.execute(update(staff_identities).where(
                staff_identities.c.staff_id == staff_id).values(**values))
        scope = (staff_service_permissions.c.staff_id == staff_id) & (
            staff_service_permissions.c.service_id == registration.service_id)
        exists = connection.execute(select(staff_service_permissions.c.staff_id).where(scope)).first()
        if exists is None:
            connection.execute(insert(staff_service_permissions).values(
                staff_id=staff_id, service_id=registration.service_id, role=registration.role))
        else:
            connection.execute(update(staff_service_permissions).where(scope).values(role=registration.role))
