# SPDX-License-Identifier: Apache-2.0
"""Data / poller admin routes — pure proxy to PyPNM API.

Every request is forwarded to PyPNM's ``/api/admin/*`` endpoints.
No local database access. No business logic.
"""

import os

from flask import jsonify, request, session
import requests

from . import api_bp


def _require_admin():
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Admin role required"}), 403
    return None


def _poller_api_base() -> str:
    explicit = (os.environ.get("PYPNM_POLLER_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    pypnm_base = (os.environ.get("PYPNM_API_URL") or os.environ.get("PYPNM_BASE_URL") or "http://172.17.0.1:8081").rstrip("/")
    return f"{pypnm_base}/api/admin"


def _proxy(method: str, path: str, *, payload=None, params=None):
    timeout = int(os.environ.get("PYPNM_POLLER_API_TIMEOUT_SEC", "30"))
    url = f"{_poller_api_base()}{path}"
    resp = requests.request(method=method, url=url, json=payload, params=params, timeout=timeout, verify=False)
    return jsonify(resp.json() if resp.content else {"status": "success"}), resp.status_code


# ── Data-store status ────────────────────────────────────────


@api_bp.route('/admin/data-store/status', methods=['GET'])
def data_store_status():
    gate = _require_admin()
    if gate:
        return gate
    return jsonify({"status": "success", "backend": "remote-pypnm"})


# ── Poller settings ──────────────────────────────────────────


@api_bp.route('/admin/poller-settings', methods=['GET'])
def list_poller_settings():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("GET", "/poller-settings")


@api_bp.route('/admin/poller-settings', methods=['POST'])
def upsert_poller_setting():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", "/poller-settings", payload=request.get_json(silent=True) or {})


@api_bp.route('/admin/poller-settings/<int:poller_id>/run', methods=['POST'])
def run_poller_setting(poller_id):
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", f"/poller-settings/{int(poller_id)}/run", payload=request.get_json(silent=True) or {})


# ── Poller jobs ──────────────────────────────────────────────


@api_bp.route('/admin/data-jobs', methods=['GET'])
def list_data_jobs():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("GET", "/poller-jobs", params={"limit": request.args.get("limit", 100)})


@api_bp.route('/admin/queue-head', methods=['GET'])
def queue_head():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("GET", "/queue-head")


@api_bp.route('/admin/poller-jobs/<int:job_id>/cancel', methods=['POST'])
def cancel_poller_job(job_id):
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", f"/poller-jobs/{int(job_id)}/kill", payload=request.get_json(silent=True) or {})


# ── Modem refresh (on-demand single-modem enrichment) ────────


@api_bp.route('/admin/modem-refresh/<int:request_id>/cancel', methods=['POST'])
def cancel_modem_refresh(request_id):
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", f"/modem-refresh/{int(request_id)}/cancel")


@api_bp.route('/modems/<mac>/refresh', methods=['POST'])
def request_modem_refresh(mac):
    payload = request.get_json(silent=True) or {}
    cmts = payload.get('cmts')
    if not cmts:
        return jsonify({"status": "error", "message": "cmts is required"}), 400
    requested_by = session.get("username") or session.get("user") or "user"
    return _proxy("POST", "/modem-refresh", payload={"mac": mac, "cmts": cmts, "requested_by": requested_by})


@api_bp.route('/modems/<mac>/refresh/status', methods=['GET'])
def modem_refresh_status(mac):
    return _proxy("GET", f"/modem-refresh/{mac}/status")


# ── Enrichment progress ─────────────────────────────────────


@api_bp.route('/admin/enrichment-progress', methods=['GET'])
def enrichment_progress():
    cmts = request.args.get("cmts")
    return _proxy("GET", "/inventory/enrichment-progress", params={"cmts": cmts} if cmts else None)


# ── Scheduler control ────────────────────────────────────────


@api_bp.route('/admin/poller-scheduler/status', methods=['GET'])
def poller_scheduler_status():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("GET", "/poller-scheduler/status")


@api_bp.route('/admin/poller-scheduler/toggle', methods=['POST'])
def toggle_poller_scheduler():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", "/poller-scheduler/toggle", payload=request.get_json(silent=True) or {})


@api_bp.route('/admin/poller-scheduler/run-once', methods=['POST'])
def run_poller_scheduler_once():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("POST", "/poller-scheduler/run-once")
