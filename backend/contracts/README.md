# LINE internal API contract artifact

`line-internal-api-v1.openapi.json` is the versioned, LINE-provider-owned
contract artifact for the future Admin-to-LINE boundary. It can be distributed
to consumers without granting access to the provider source repository.

This is a consumer copy. Regenerate it in the LINE repository using its
`backend/scripts/export_line_internal_openapi.py`, then copy the versioned
artifact here and run the Admin consumer compatibility tests. Do not generate
LINE-owned artifacts from this repository.

The full semantic contract version is declared by
`LINE_INTERNAL_CONTRACT_VERSION`; the filename carries its major version.
Backward-compatible additive changes increment the minor or patch version.
Removing or changing an existing field, status, or endpoint requires a new
major version and a new artifact filename. The checked-in artifact must match
the provider schema, which is enforced by the focused contract test.

This artifact describes interfaces only. It is not a runtime API registration,
durable command store, delivery implementation, or authentication mechanism.

`admin-api-v1.openapi.json` is the current Admin-owned public artifact.
Regenerate it deterministically from the backend directory with:

```text
python scripts/export_application_openapi.py
```

The Admin LINE-internal client consumes the distributable models in
`app/contracts/admin_line_internal_v1.py`; production Admin code does not
import the LINE provider's private schema module.

The consumer copy is synchronized with LINE Internal v1 **1.2.0**. Batch linkage
responses include `job_notification_status` for Admin preflight validation.
The previous Admin consumer rejects this added field, so coordinate the Admin
and LINE upgrade while notification processing is stopped; do not run the old
Admin consumer against LINE 1.2.0. Scope-denial responses and the LINE recovery
operation (which Admin does not call) remain part of the contract.

The single incoming LINE Bearer identifies our Admin Backend; staff service
authorization remains in Admin. LINE requires an exact service-to-organization
mapping and returns `403 / scope_forbidden` for unauthorized scopes. Admin treats
submission denial as permanent failure, never as an unlinked member or success.
For an already accepted command, this denial on result GET ends local polling as
`unknown` / `line_result_scope_forbidden`, because delivery may already have
occurred. It never resubmits the command, and it preserves any concurrent terminal
result. Restoring configuration does not automatically retry this unknown result;
an operator must investigate it before considering any further action. Deep-link
failures use the existing safe 503 dependency response. Capability failures keep
sending disabled.

`tests/test_line_scope_integration.py` runs real Admin HTTP serialization against
the sibling `silver-line-repo/backend` ASGI routes over a subprocess stdio bridge.
It uses fictional values and disposable SQLite with LINE's network/dotenv guards;
no real server, DB or LINE connection is required. It explicitly skips when the
sibling checkout is unavailable. Run it together with `test_line_scope_failure.py`
from `backend` for the cross-repository scope and Admin failure-convergence checks.

## Admin internal business API (Slice 1.2)

`admin-internal-api-v1.openapi.json` is owned by the **Admin Repository**, which
is the source of truth for the LINE-to-Admin business contract. LINE consumers
use this checked-in artifact without importing Admin Python source. Admin does
not import LINE provider Python source. Do not silently change request/response
semantics: breaking changes require a new major version/path or an explicit
consumer migration; additive compatible changes update the contract version.

Generate the dedicated artifact from `backend` without reading any `.env`:

```text
python scripts/export_admin_internal_openapi.py
```

The exporter uses the same router and schemas as the Admin runtime. The internal
router is deliberately excluded from the public Admin OpenAPI document; its
dedicated artifact includes the four operations, schemas, errors, Bearer security
scheme and version `1.0.0`. Its version is independent of the opposite-direction
LINE internal contract. Focused tests compare the artifact with runtime schemas.

See [External Business Integration Requirements](../../docs/EXTERNAL_BUSINESS_INTEGRATION.md)
for business semantics, configuration and the runtime boundary.

## Contract ownership and distribution

Admin Internal API v1 and Admin Staff API v1 are owned by this repository.
`admin-internal-api-v1.openapi.json` is consumed by the LINE repository; the
Admin Staff API is consumed by the Admin Frontend. LINE Internal API v1 is owned
by the LINE repository and consumed here. Generate provider artifacts, copy the
versioned file to the consumer, compare bytes or hashes, and run compatibility
tests. No shared Python contract package is used.

## Notification safety revision 1.2.1

The LINE internal artifact is synchronized at 1.2.1. Wire fields/statuses stay compatible with 1.2.0. Final text includes separators, canonical URL and local prefix and is limited to 5,000 UTF-16 units. Generic provider 400 is bad_request. New never-called invalid messages become failed/message_too_long or failed/invalid_message; refusal after a possible call is unknown/preference_changed_after_call. Existing ambiguous pending bodies/keys are never rewritten. Admin validation additionally returns validated_at for UI freshness. Admin result and skipped counts use frozen selection S; legacy history is projected only with consistent saved evidence.

会員ライフサイクル更新: Admin内部契約1.1.0、LINE内部契約2.0.0。指定のartifactファイル名とURLは維持しますが、LINEの必須世代追加は破壊的変更です。旧新モデルを停止区間なしに混在させないでください。
