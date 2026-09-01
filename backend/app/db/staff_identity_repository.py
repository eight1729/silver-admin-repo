from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.admin_tables import staff_identities, staff_service_permissions
from app.domain.enums.enums import StaffRole
from app.domain.models.staff import StaffIdentity, StaffServicePermission


class SqlAlchemyStaffIdentityRepository:
    """Admin-owned lookup keyed only by the stable OIDC issuer + subject pair."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def find_by_oidc_identity(
        self, issuer: str, subject: str
    ) -> tuple[StaffIdentity, tuple[StaffServicePermission, ...]] | None:
        async with self._engine.connect() as conn:
            identity_row = (
                await conn.execute(
                    select(staff_identities).where(
                        staff_identities.c.identity_provider == issuer,
                        staff_identities.c.external_subject == subject,
                    )
                )
            ).mappings().first()
            if identity_row is None:
                return None
            permission_rows = (
                await conn.execute(
                    select(staff_service_permissions)
                    .where(
                        staff_service_permissions.c.staff_id
                        == identity_row["staff_id"]
                    )
                    .order_by(staff_service_permissions.c.service_id)
                )
            ).mappings().all()
        identity = StaffIdentity(
            staff_id=UUID(identity_row["staff_id"]),
            identity_provider=identity_row["identity_provider"],
            external_subject=identity_row["external_subject"],
            email=identity_row["email"],
            display_name=identity_row["display_name"],
            active=identity_row["active"],
        )
        permissions = tuple(
            StaffServicePermission(
                staff_id=identity.staff_id,
                service_id=row["service_id"],
                role=StaffRole(
                    "sender" if row["role"] == "operator" else row["role"]
                ),
            )
            for row in permission_rows
        )
        return identity, permissions
