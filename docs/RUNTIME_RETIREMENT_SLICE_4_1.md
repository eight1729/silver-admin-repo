# Slice 4.1 — runtime business provider retirement

The canonical Admin Internal API always builds `CurrentDbExternalBusinessGateway`
behind `ExternalBusinessGateway`; APP_ENV does not select its business source.
Explicit gateway injection remains available for isolated tests.

The remaining reachable Fake path was:
`main_admin.create_admin_app` → enabled local integration composition →
`build_local_integration_external_business` → scoped fixture-backed Fake.
The composition now defaults to Current DB with `current_db_business_centers`.
Missing configuration fails closed. It never loads `normal.json` or selects a
Fake. Existing explicit test gateway/queue injection is retained.

Current DB supports the four Phase 1 business reads/verification capabilities.
Its job search, candidate search, link eligibility and notification validation
remain explicitly not configured. Local integration no longer returns fabricated
success/data for those capabilities. No new provider capability is implemented
in this slice. The default public Admin application remains unavailable unless
its existing composition is enabled/injected; broad deployment composition is
not redesigned here.

## LINE entrypoint audit

`main_line.create_line_app` mounts `liff_canonical` in all six environments.
It uses verified LINE identity, trusted configured scope,
`line_recipient_linkages`, and the Admin HTTP consumer. No M001 auto-link,
process-local linkage, fixture business response, or local business-table fallback
is reachable through the canonical LIFF routes. No LINE source change was needed.

The environment branch still controls ancillary router availability, not which
LIFF member/job/linkage source is selected. Centers, partner, webhook and internal
notification responsibilities were not removed or expanded to other environments.

## Search-hit classification and retained files

| Hits | Classification / decision |
| --- | --- |
| LINE `api/liff_member_deps.py`, `api/routes/liff_member.py` | Noncanonical staging files; not registered/imported by canonical entrypoint wiring. Retained. |
| LINE legacy `api/routes/liff.py` member/link/jobs handlers | Unregistered legacy handlers. Only its separate centers router is mounted; importing the module does not mount the old business routes. |
| `testing/**`, Fake/ScopedFake/Staging gateway, `normal.json`, M001 fixtures | Test dependencies/data. Admin runtime no longer imports the fixture builder; explicit tests may still use it. |
| LINE `db/tables.py`, `db/repositories.py`, old linkage/business schema and migrations | Retained schema/compatibility code. Canonical LIFF never uses those business reads. |
| LINE partner link-token/notification utilities | Existing noncanonical partner responsibilities remain reachable outside staging. They still use legacy member/linkage repositories. These are not LIFF fallback paths; removing or redesigning unrelated partner notifications is outside this slice. |
| Admin `current_db_external_business.py` recommendation-table reads | Canonical provider-owned Current DB mapping, intentionally retained. |
| APP_ENV in settings/entrypoints/auth/transport/send gates | Environment validation, staff auth, transport restrictions and send safety retained. No environment selects Fake member/job data. |
| docs and historical contract artifacts | Historical/migration documentation retained; not runtime providers. |

## Preserved safety and boundaries

LINE staging sender enable, recipient allowlist, recipient cap, prefix, disabled
sender and readiness checks remain unchanged. Login channel resolution and token
verification remain unchanged. Notification forward lookup continues to use
canonical persistent linkage. Staff authentication, queues, delivery/recovery,
partner and webhook behavior are not refactored.

No actual dotenv, real DB, Admin/LINE network, Git mutation, table DROP or migration
deletion was performed. Test Fake/Mock/Stub classes and fixtures remain intact.

## Validation and remaining gates

- Admin: 89 focused tests passed (Current DB, Internal API, all-environment
  provider selection, local integration, fail-closed configuration, injected Fakes).
- LINE Backend: 114 passed, 5 PostgreSQL integration tests deselected (canonical
  LIFF/contract, Admin consumer, linkage/notification, staging send safety).
- LINE Frontend: 22 focused tests passed (Member Gate and navigation regression).

Manual gates: provision Current DB center/scope mappings; exercise real persistent
linkage and S2S/LIFF flows in an approved environment; verify recipient allowlist
and disabled/enabled send behavior without broadening recipients.

Slice 4.2 notes: configuration/deployment naming, local composition enablement,
public Admin unsupported capability readiness, Docker/entrypoint validation,
README/LOCAL_RUN, contract distribution and send-readiness naming. Phase 5 retains
notification reliability work. Slice 4.2 has not been implemented.
