"""BFF tests for the Signal Quality routes. No database or PyPNM API is contacted."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("AUTH_DB_HOST", "127.0.0.1")
os.environ.setdefault("AUTH_DB_USER", "test")
os.environ.setdefault("AUTH_DB_PASSWORD", "test")
os.environ.setdefault("AUTH_DB_NAME", "test")
os.environ["PYPNM_API_BASE"] = "http://pypnm.test/api"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from flask import Flask  # noqa: E402

from app.core import feature_flags  # noqa: E402
from app.routes import data_routes  # noqa: E402

BASE = "http://pypnm.test/api/admin/signal-quality"


class FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, chunks: list[bytes] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        self._body = {"status": "success"} if body is None else body
        self.status_code = status
        self.ok = status < 400
        self.content = b"x"
        self.headers = headers or {}
        self._chunks = chunks or []
        self.closed = False

    def json(self) -> Any:
        return self._body

    def iter_content(self, chunk_size: int = 0):
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(data_routes.api_bp, url_prefix="/api")
    calls: list[dict[str, Any]] = []
    timeouts: list[Any] = []
    state = {"enabled": True, "topology": True, "response": FakeResponse(), "get_response": FakeResponse()}

    def fake_request(method, url, json=None, params=None, **kwargs):
        calls.append({"method": method, "url": url, "json": json, "params": params})
        timeouts.append(kwargs.get("timeout"))
        return state["response"]

    def fake_get(url, params=None, **kwargs):
        calls.append({"method": "GET", "url": url, "params": params, "stream": kwargs.get("stream")})
        return state["get_response"]

    monkeypatch.setattr(data_routes.requests, "request", fake_request)
    monkeypatch.setattr(data_routes.requests, "get", fake_get)
    monkeypatch.setattr(data_routes, "is_signal_quality_enabled", lambda: state["enabled"])
    monkeypatch.setattr(data_routes, "is_topology_scopes_enabled", lambda: state["topology"])

    def client(role: str | None = "user", username: str = "alice"):
        test_client = app.test_client()
        if role:
            with test_client.session_transaction() as session:
                session["role"] = role
                session["username"] = username
        return test_client

    client.timeouts = timeouts  # type: ignore[attr-defined]
    return client, calls, state


@pytest.mark.parametrize("role", [None, "viewer"])
def test_requires_admin_or_user_role(env, role) -> None:
    client, calls, _ = env
    assert client(role).get("/api/admin/signal-quality/jobs").status_code == 403
    assert calls == []


@pytest.mark.parametrize("role", ["admin", "user"])
def test_admin_and_user_are_allowed(env, role) -> None:
    client, calls, _ = env
    assert client(role).get("/api/admin/signal-quality/jobs?limit=5&evil=1").status_code == 200
    assert calls == [{"method": "GET", "url": f"{BASE}/jobs", "json": None, "params": {"limit": "5"}}]


def test_disabled_flag_hides_every_route(env) -> None:
    client, calls, state = env
    state["enabled"] = False
    c = client("admin")
    for method, path in [("get", "/jobs"), ("get", "/options/cmts"), ("post", "/jobs/plan"),
                         ("post", "/jobs/x/start"), ("get", "/jobs/x/download"), ("delete", "/jobs/x")]:
        assert getattr(c, method)(f"/api/admin/signal-quality{path}").status_code == 404, path
    assert calls == []


def test_plan_forwards_payload_and_injects_requester(env) -> None:
    client, calls, _ = env
    payload = {"scope": {"type": "cmts", "cmts": "ccap1"}, "window_start": "01:00", "window_end": "06:00",
               "modems_per_fiber_node": 10, "modems_per_cmts": 25, "confirmation_password": "kensentme",
               "requested_by": "mallory"}
    assert client("user", "alice").post("/api/admin/signal-quality/jobs/plan", json=payload).status_code == 200
    sent = calls[0]
    assert sent["method"] == "POST" and sent["url"] == f"{BASE}/jobs/plan"
    assert sent["json"]["requested_by"] == "alice"  # a client cannot spoof the requester
    assert sent["json"]["confirmation_password"] == "kensentme"
    assert sent["json"]["modems_per_fiber_node"] == 10 and sent["json"]["modems_per_cmts"] == 25  # sample sizes reach the API untouched
    assert client.timeouts == [120]  # fiber-node scopes resolve slowly; do not cut them off at 30 s


def test_fiber_node_scope_is_blocked_when_topology_disabled(env) -> None:
    client, calls, state = env
    state["topology"] = False
    c = client("admin")
    assert c.get("/api/admin/signal-quality/options/fiber-nodes?cmts=ccap1").status_code == 404
    plan = {"scope": {"type": "fiber_node", "cmts": "ccap1", "fiber_nodes": ["FN1"]}, "confirmation_password": "x"}
    assert c.post("/api/admin/signal-quality/jobs/plan", json=plan).status_code == 404
    assert calls == []
    cmts_plan = {"scope": {"type": "cmts", "cmts": "ccap1"}, "confirmation_password": "x"}
    assert c.post("/api/admin/signal-quality/jobs/plan", json=cmts_plan).status_code == 200
    assert len(calls) == 1


def test_starting_a_persisted_fiber_node_job_is_blocked_when_topology_disabled(env) -> None:
    client, calls, state = env
    state["topology"] = False
    state["get_response"] = FakeResponse({"status": "success", "job": {"scope_type": "fiber_node"}})
    response = client("admin").post("/api/admin/signal-quality/jobs/abc/start", json={"confirmation_password": "x"})
    assert response.status_code == 404
    assert [c["method"] for c in calls] == ["GET"]  # the start was never forwarded


def test_start_is_forwarded_for_cmts_job_when_topology_disabled(env) -> None:
    client, calls, state = env
    state["topology"] = False
    state["get_response"] = FakeResponse({"status": "success", "job": {"scope_type": "cmts"}})
    body = {"confirmation_password": "kensentme", "override_window": True}
    assert client("admin").post("/api/admin/signal-quality/jobs/abc/start", json=body).status_code == 200
    assert calls[-1] == {"method": "POST", "url": f"{BASE}/jobs/abc/start", "json": body, "params": None}


def test_targets_only_forwards_whitelisted_params(env) -> None:
    client, calls, _ = env
    client("user").get("/api/admin/signal-quality/jobs/abc/targets?cursor=5&limit=10&state=failed&sql=1")
    assert calls[0]["params"] == {"cursor": "5", "limit": "10", "state": "failed"}


def test_cancel_and_delete_are_proxied(env) -> None:
    client, calls, _ = env
    c = client("user")
    assert c.post("/api/admin/signal-quality/jobs/abc/cancel").status_code == 200
    assert c.delete("/api/admin/signal-quality/jobs/abc").status_code == 200
    assert [(x["method"], x["url"]) for x in calls] == [("POST", f"{BASE}/jobs/abc/cancel"), ("DELETE", f"{BASE}/jobs/abc")]


def test_download_streams_package_with_filename(env) -> None:
    client, calls, state = env
    upstream = FakeResponse(chunks=[b"PK\x03", b"\x04data"], headers={
        "Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="signal_quality_x.zip"'})
    state["get_response"] = upstream
    response = client("user").get("/api/admin/signal-quality/jobs/abc/download")
    assert response.status_code == 200 and response.data == b"PK\x03\x04data"
    assert response.headers["Content-Type"] == "application/zip"
    assert "signal_quality_x.zip" in response.headers["Content-Disposition"]
    assert calls[0]["url"] == f"{BASE}/jobs/abc/download" and calls[0]["stream"] is True
    assert upstream.closed


def test_download_error_is_passed_through(env) -> None:
    client, _, state = env
    state["get_response"] = FakeResponse({"detail": "Package not available"}, status=404)
    response = client("user").get("/api/admin/signal-quality/jobs/abc/download")
    assert response.status_code == 404 and response.get_json()["detail"] == "Package not available"


def test_flag_defaults_off_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert feature_flags.FEATURE_FLAG_DEFAULTS[feature_flags.SIGNAL_QUALITY_SETTING] == "false"

    def boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(feature_flags.auth_db, "get_bool_setting", boom)
    assert feature_flags.is_signal_quality_enabled() is False
