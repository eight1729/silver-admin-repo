"""Offline LINE ASGI peer for the optional sibling-repository contract test.

Runs in a separate interpreter because both repositories own an `app` package.
Only fictional JSON travels over stdio; no server socket or real DB is opened.
"""
import asyncio
import json
from pathlib import Path
import sys
from dataclasses import replace

backend = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(backend / "tests"), str(backend)]
import conftest  # LINE's dotenv isolation, before any application imports
import pytest
from test_internal_scope_authorization import api, runtime
from test_line_command_recovery_snapshot import Database
from app.adapter.canonical_deep_link import SettingsCanonicalDeepLinkResolver


async def main():
    monkeypatch = pytest.MonkeyPatch()
    conftest.no_external_connections.__wrapped__(monkeypatch)
    # The fixture installs its guard immediately (it is not a generator).
    db = Database()
    try:
        for line in sys.stdin:
            envelope = json.loads(line)
            scopes = envelope["scopes"]
            boundary = runtime(db, scopes)
            for seed in envelope.get("preferences", []):
                linkage = await boundary.recipients.register_linkage(
                    organization_id=seed["org"], service_id=seed["service"],
                    external_member_id=seed["member"], line_subject=f"fictional-{seed['member']}")
                if seed["enabled"] is not None:
                    await boundary.recipients.update_preferences(linkage,
                        job_notifications_enabled=seed["enabled"], center_notifications_enabled=False)
            boundary = replace(boundary, deep_links=SettingsCanonicalDeepLinkResolver({
                org: {service: "https://liff.line.me/offline"}
                for service, org in scopes.items()
            }))
            async with api(monkeypatch, boundary, scopes) as client:
                response = await client.request(envelope["method"], envelope["path"],
                    headers=envelope["headers"], content=envelope["body"])
            print(json.dumps({"status": response.status_code, "body": response.json()}), flush=True)
    finally:
        db.connection.close()
        db.engine.dispose()
        monkeypatch.undo()


asyncio.run(main())
