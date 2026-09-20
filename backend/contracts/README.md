# LINE internal API contract artifact

`line-internal-api-v1.openapi.json` is the versioned, LINE-provider-owned
contract artifact for the future Admin-to-LINE boundary. It can be distributed
to consumers without granting access to the provider source repository.

Regenerate it deterministically from the backend directory:

```text
python scripts/export_line_internal_openapi.py
```

The full semantic contract version is declared by
`LINE_INTERNAL_CONTRACT_VERSION`; the filename carries its major version.
Backward-compatible additive changes increment the minor or patch version.
Removing or changing an existing field, status, or endpoint requires a new
major version and a new artifact filename. The checked-in artifact must match
the provider schema, which is enforced by the focused contract test.

This artifact describes interfaces only. It is not a runtime API registration,
durable command store, delivery implementation, or authentication mechanism.

`line-api-v1.openapi.json` and `admin-api-v1.openapi.json` are the versioned
public artifacts for the separated application entrypoints. Regenerate all
owner artifacts deterministically with:

```text
python scripts/export_application_openapi.py all
```

The Admin LINE-internal client consumes the distributable models in
`app/contracts/admin_line_internal_v1.py`; production Admin code does not
import the LINE provider's private schema module.

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
