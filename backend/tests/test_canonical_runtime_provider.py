import pytest
from starlette.requests import Request

from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from app.api.admin_internal_deps import get_admin_internal_service
from app.core.settings_admin import AdminSettings
from app.main_admin import create_admin_app


@pytest.mark.parametrize("environment", ["local", "development", "demo", "test", "staging", "production"])
def test_internal_entrypoint_selects_current_db_in_every_environment(monkeypatch, environment):
    engine = object()
    monkeypatch.setattr("app.api.admin_internal_deps.get_engine", lambda: engine)
    settings = AdminSettings(
        _env_file=None, database_url="postgresql://unused/unused", app_env=environment,
        admin_internal_api_scopes={"svc": "org"}, current_db_business_centers={"org": "center"},
    )
    app = create_admin_app(settings)
    request = Request({"type": "http", "app": app})
    service = get_admin_internal_service(request, None)
    assert isinstance(service._gateway, CurrentDbExternalBusinessGateway)
    assert service._gateway._engine is engine
    assert service._organization("svc") == "org"
    assert all("testing" not in route.endpoint.__module__ for route in app.routes)
