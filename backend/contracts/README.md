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
