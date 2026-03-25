import os

from flask import jsonify, request, session
import requests

from app.core.data_store_db import data_store_db
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


def _poller_proxy(method: str, path: str, *, payload=None, params=None):
    timeout = int(os.environ.get("PYPNM_POLLER_API_TIMEOUT_SEC", "20"))
    url = f"{_poller_api_base()}{path}"
    resp = requests.request(method=method, url=url, json=payload, params=params, timeout=timeout, verify=False)
    return jsonify(resp.json() if resp.content else {"status": "success"}), resp.status_code


@api_bp.route('/admin/data-store/status', methods=['GET'])
def data_store_status():
    gate = _require_admin()
    if gate:
        return gate
    return jsonify({
        "status": "success",
        "backend": "remote-pypnm",
    })


@api_bp.route('/admin/poller-settings', methods=['GET'])
def list_poller_settings():
    gate = _require_admin()
    if gate:
        return gate
    return _poller_proxy("GET", "/poller-settings")


@api_bp.route('/admin/poller-settings', methods=['POST'])
def upsert_poller_setting():
    gate = _require_admin()
    if gate:
        return gate
    payload = request.get_json(silent=True) or {}
    return _poller_proxy("POST", "/poller-settings", payload=payload)


@api_bp.route('/admin/poller-settings/<int:poller_id>/run', methods=['POST'])
def run_poller_setting(poller_id):
    gate = _require_admin()
    if gate:
        return gate
    payload = request.get_json(silent=True) or {}
    return _poller_proxy("POST", f"/poller-settings/{int(poller_id)}/run", payload=payload)


@api_bp.route('/admin/data-jobs', methods=['GET'])
def list_data_jobs():
    gate = _require_admin()
    if gate:
        return gate
    status = request.args.get('status')
    limit = request.args.get('limit', 100)
    params = {"status": status, "limit": limit}
    return _poller_proxy("GET", "/poller-jobs", params=params)


@api_bp.route('/admin/queue-head', methods=['GET'])
def queue_head():
    gate = _require_admin()
    if gate:
        return gate
    snapshot = data_store_db.get_queue_heads()
    return jsonify({"status": "success", "queue": snapshot})


@api_bp.route('/admin/poller-jobs/<int:job_id>/cancel', methods=['POST'])
def cancel_poller_job(job_id):
    gate = _require_admin()
    if gate:
        return gate
    reason = (request.get_json(silent=True) or {}).get('reason') or 'Cancelled by admin'
    ok = data_store_db.cancel_poller_job(job_id, reason=reason)
    if not ok:
        return jsonify({"status": "error", "message": "Job not cancellable (not found or already finished)"}), 404
    return jsonify({"status": "success", "job_id": int(job_id)})


@api_bp.route('/admin/modem-refresh/<int:request_id>/cancel', methods=['POST'])
def cancel_modem_refresh(request_id):
    gate = _require_admin()
    if gate:
        return gate
    reason = (request.get_json(silent=True) or {}).get('reason') or 'Cancelled by admin'
    ok = data_store_db.cancel_refresh_request(request_id, reason=reason)
    if not ok:
        return jsonify({"status": "error", "message": "Refresh request not cancellable (not found or already finished)"}), 404
    return jsonify({"status": "success", "request_id": int(request_id)})


@api_bp.route('/modems/<mac>/refresh', methods=['POST'])
def request_modem_refresh(mac):
    payload = request.get_json(silent=True) or {}
    cmts = payload.get('cmts')
    if not cmts:
        return jsonify({"status": "error", "message": "cmts is required"}), 400

    requested_by = session.get("username") or session.get("user") or "user"
    req_id = data_store_db.enqueue_modem_refresh(mac=mac, cmts=cmts, requested_by=requested_by)
    return jsonify({"status": "success", "request_id": req_id})


@api_bp.route('/modems/<mac>/refresh/status', methods=['GET'])
def modem_refresh_status(mac):
    req = data_store_db.get_latest_refresh_request(mac)
    if not req:
        return jsonify({"status": "success", "request": None})
    return jsonify({"status": "success", "request": req})
