# SPDX-License-Identifier: Apache-2.0
"""Data / poller admin routes — pure proxy to PyPNM API.

Every request is forwarded to PyPNM's ``/api/admin/*`` endpoints.
No local database access. No business logic.
"""

import os
import uuid

import requests
from flask import Response, jsonify, request, session, stream_with_context

from app.core.auth_providers import is_authenticated_session
from app.core.feature_flags import (
    is_cm_bulk_reset_enabled,
    is_custom_snmp_enabled,
    is_network_rxmer_analytics_enabled,
    is_topology_scopes_enabled,
)

from . import api_bp


def _require_admin():
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Admin role required"}), 403
    return None


def _require_topology_scopes():
    """Reject only requests that attempt to use topology-dependent Fiber Node data."""
    if is_topology_scopes_enabled():
        return None

    def has_value(value):
        if value is None:
            return False
        if isinstance(value, (list, tuple, set)):
            return any(has_value(item) for item in value)
        return bool(str(value).strip())

    uses_topology = request.path.rstrip("/").endswith("/options/fiber-nodes")
    uses_topology = uses_topology or has_value(request.args.getlist("fiber_node"))

    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        uses_topology = uses_topology or has_value(payload.get("fiber_node"))
        scope = payload.get("scope")
        if isinstance(scope, dict):
            scope_type = str(scope.get("type") or "").strip().lower()
            uses_topology = uses_topology or scope_type == "fiber_node"
            uses_topology = uses_topology or has_value(scope.get("fiber_nodes"))

    if uses_topology:
        return jsonify({
            "status": "error",
            "message": "Topology-dependent Fiber Node scopes are disabled",
        }), 404
    return None


def _normalize_modem_community_payload(payload, *, write=False):
    """Copy a payload and add an optional direction-specific modem community."""
    normalized = dict(payload) if isinstance(payload, dict) else {}
    if "community" in normalized:
        community = normalized.get("community")
        if isinstance(community, str) and community.strip():
            return normalized
        normalized.pop("community", None)

    env_names = (
        ("MODEM_WRITE_COMMUNITY", "CM_RW_COMMUNITY")
        if write
        else ("MODEM_COMMUNITY", "CM_SNMP_COMMUNITY")
    )
    for env_name in env_names:
        configured = os.environ.get(env_name)
        if configured is not None and configured.strip():
            normalized["community"] = configured
            break
    return normalized


def _poller_api_base() -> str:
    explicit = (os.environ.get("PYPNM_POLLER_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    pypnm_base = (os.environ.get("PYPNM_API_URL") or os.environ.get("PYPNM_BASE_URL") or "http://172.17.0.1:8081").rstrip("/")
    return f"{pypnm_base}/api/admin"


def _proxy(method: str, path: str, *, payload=None, params=None, timeout=None):
    request_timeout = timeout or int(os.environ.get("PYPNM_POLLER_API_TIMEOUT_SEC", "30"))
    url = f"{_poller_api_base()}{path}"
    try:
        resp = requests.request(
            method=method,
            url=url,
            json=payload,
            params=params,
            timeout=request_timeout,
            verify=False,
        )
    except requests.Timeout:
        return jsonify({
            "status": "error",
            "message": "PyPNM request timed out; the operation may still complete",
        }), 504
    except requests.RequestException:
        return jsonify({"status": "error", "message": "PyPNM API unavailable"}), 502
    return jsonify(resp.json() if resp.content else {"status": "success"}), resp.status_code


def _get_pypnm_json(path: str, *, params=None, timeout=None):
    """Fetch one PyPNM JSON object for local authorization or response filtering."""
    request_timeout = timeout or int(os.environ.get("PYPNM_POLLER_API_TIMEOUT_SEC", "30"))
    try:
        response = requests.get(
            f"{_poller_api_base()}{path}",
            params=params,
            timeout=request_timeout,
            verify=False,
        )
    except requests.Timeout:
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM request timed out",
        }), 504)
    except requests.RequestException:
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM API unavailable",
        }), 502)

    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {"status": "error", "message": "PyPNM returned an invalid response"}
    if not response.ok:
        return None, (jsonify(body), response.status_code)
    if not isinstance(body, dict):
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM returned an invalid response",
        }), 502)
    return body, None


def _require_non_topology_job(path: str):
    """Fail closed when starting a persisted Fiber Node-scoped job while disabled."""
    if is_topology_scopes_enabled():
        return None

    body, error = _get_pypnm_json(path)
    if error:
        return error
    job = body.get("job")
    if not isinstance(job, dict):
        return jsonify({
            "status": "error",
            "message": "Unable to verify the persisted job scope",
        }), 502

    scope = job.get("scope")
    scope = scope if isinstance(scope, dict) else {}
    scope_type = str(job.get("scope_type") or scope.get("type") or "").strip().lower()
    uses_topology = scope_type == "fiber_node" or bool(scope.get("fiber_nodes"))
    if uses_topology:
        return jsonify({
            "status": "error",
            "message": "This Fiber Node job cannot be started while topology scopes are disabled",
        }), 404
    return None


def _stream_proxy(path: str, *, params=None):
    url = f"{_poller_api_base()}{path}"
    try:
        upstream = requests.get(
            url,
            params=params,
            stream=True,
            timeout=(10, 600),
            verify=False,
        )
    except requests.Timeout:
        return jsonify({"status": "error", "message": "PyPNM report timed out"}), 504
    except requests.RequestException:
        return jsonify({"status": "error", "message": "PyPNM API unavailable"}), 502
    if not upstream.ok:
        try:
            body = upstream.json()
        except ValueError:
            body = {"status": "error", "message": "PyPNM report unavailable"}
        status_code = upstream.status_code
        upstream.close()
        return jsonify(body), status_code

    @stream_with_context
    def generate():
        try:
            yield from upstream.iter_content(chunk_size=64 * 1024)
        finally:
            upstream.close()

    headers = {}
    disposition = upstream.headers.get("Content-Disposition")
    if disposition:
        headers["Content-Disposition"] = disposition
    return Response(
        generate(),
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        headers=headers,
    )


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


@api_bp.route('/admin/inventory/snapshots', methods=['GET'])
def inventory_snapshots():
    gate = _require_admin()
    if gate:
        return gate
    return _proxy("GET", "/inventory/snapshots/current")


# ── Inventory summary (vendor / model / firmware counts) ─────


@api_bp.route('/admin/inventory-summary', methods=['GET'])
def inventory_summary():
    gate = _require_admin()
    if gate:
        return gate

    cmts_filter_raw = (request.args.get("cmts") or "").strip()
    area_filter = (request.args.get("area") or "").strip().lower()
    if area_filter not in {"", "fziggo", "fupc", "vfz"}:
        return jsonify({
            "status": "error",
            "message": f"Unsupported inventory area: {area_filter}",
        }), 400
    try:
        top_n = max(1, min(int(request.args.get("top_n", 25)), 100))
    except (TypeError, ValueError):
        top_n = 25

    # A filtered CMTS can use one exact cache key. Never scan all full modem
    # payloads to build a fleet summary: that transfers and decodes millions
    # of rows in Python and alias keys can double-count the same CMTS.
    if cmts_filter_raw and not area_filter:
        try:
            import collections as _collections

            from app.routes.api_routes import (
                REDIS_AVAILABLE,
                _inventory_revision_map,
                _read_modem_cache,
                filter_ignored_modems,
                redis_client,
            )

            if REDIS_AVAILABLE and redis_client:
                revisions = _inventory_revision_map()
                cache_keys = list(dict.fromkeys([
                    f"modems:{cmts_filter_raw}",
                    f"modems:{cmts_filter_raw.lower()}",
                ]))
                requested_ref = cmts_filter_raw.lower()
                payload = None
                payload_modems = []
                for cache_key in cache_keys:
                    candidate = _read_modem_cache(cache_key, revisions)
                    if not candidate:
                        continue

                    candidate_modems = [
                        modem
                        for modem in filter_ignored_modems(
                            candidate.get("modems") or []
                        )
                        if isinstance(modem, dict)
                    ]
                    try:
                        authoritative_row_count = int(candidate["row_count"])
                    except (KeyError, TypeError, ValueError):
                        continue

                    payload_cmts = str(candidate.get("cmts") or "").strip().lower()
                    payload_cmts_ips = {
                        str(modem.get("cmts_ip") or "").strip().lower()
                        for modem in candidate_modems
                        if str(modem.get("cmts_ip") or "").strip()
                    }
                    scope_matches = (
                        requested_ref == payload_cmts
                        or requested_ref in payload_cmts_ips
                    )
                    complete_generation = (
                        candidate.get("complete") is True
                        and candidate.get("truncated") is not True
                        and 0 <= authoritative_row_count <= len(candidate_modems)
                    )
                    if scope_matches and complete_generation:
                        payload = candidate
                        payload_modems = candidate_modems
                        break

                if payload is not None:
                    placeholders = {
                        "", "unknown", "n/a", "na", "none", "null", "-", "(unknown)",
                    }
                    enriched_placeholders = {"", "unknown", "n/a"}

                    def _meaningful(value):
                        text = str(value or "").strip()
                        return "" if text.lower() in placeholders else text

                    vendor_counts = _collections.Counter()
                    model_counts = _collections.Counter()
                    firmware_counts = _collections.Counter()
                    docsis_counts = _collections.Counter()
                    total = 0
                    enriched = 0
                    for modem in payload_modems:
                        total += 1
                        vendor_text = str(modem.get("vendor") or "").strip()
                        model_text = str(modem.get("model") or "").strip()
                        firmware_text = str(
                            modem.get("software_version")
                            or modem.get("firmware")
                            or ""
                        ).strip()
                        vendor = _meaningful(vendor_text)
                        model = _meaningful(model_text)
                        firmware = _meaningful(firmware_text)
                        docsis = _meaningful(modem.get("docsis_version"))
                        if vendor:
                            vendor_counts[vendor] += 1
                        if model:
                            model_counts[model] += 1
                        if firmware:
                            firmware_counts[firmware] += 1
                        if docsis:
                            docsis_counts[docsis] += 1
                        if (
                            vendor_text.lower() not in enriched_placeholders
                            and (
                                bool(firmware_text)
                                or model_text.lower() not in enriched_placeholders
                            )
                        ):
                            enriched += 1

                    def _top(counter):
                        return [
                            {"value": value, "count": count}
                            for value, count in counter.most_common(top_n)
                        ]

                    return jsonify({
                        "status": "success",
                        "source": "redis",
                        "total": total,
                        "enriched": enriched,
                        "enriched_pct": round(enriched / total * 100, 1) if total else 0.0,
                        "last_updated": str(
                            payload.get("collected_at")
                            or payload.get("cache_written_at")
                            or ""
                        ),
                        "area": None,
                        "vendors": _top(vendor_counts),
                        "models": _top(model_counts),
                        "firmwares": _top(firmware_counts),
                        "docsis_versions": _top(docsis_counts),
                    })
        except Exception:
            pass

    # Fleet and area summaries use the authoritative one-scan MySQL aggregate.
    params = {"top_n": top_n}
    if cmts_filter_raw:
        params["cmts"] = cmts_filter_raw
    if area_filter:
        params["area"] = area_filter
    return _proxy("GET", "/inventory/summary", params=params)


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


# ── Network RxMER analytics ─────────────────────────────────


def _require_network_rxmer_analytics():
    if not is_authenticated_session(session):
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    if not is_network_rxmer_analytics_enabled():
        return jsonify({"status": "error", "message": "Network RxMER Analytics is disabled"}), 404
    return _require_topology_scopes()


@api_bp.route('/admin/rxmer-analytics/capabilities', methods=['GET'])
def network_rxmer_capabilities():
    gate = _require_network_rxmer_analytics()
    return gate or _proxy("GET", "/rxmer-analytics/capabilities")


@api_bp.route('/admin/rxmer-analytics/options/cmts', methods=['GET'])
def network_rxmer_cmts_options():
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {key: value for key, value in request.args.items() if key in {"q", "limit"}}
    return _proxy("GET", "/rxmer-analytics/options/cmts", params=params)


@api_bp.route('/admin/rxmer-analytics/options/fiber-nodes', methods=['GET'])
def network_rxmer_fiber_node_options():
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params: dict[str, object] = {"cmts": request.args.getlist("cmts")}
    for key in ("q", "limit"):
        value = request.args.get(key)
        if value is not None:
            params[key] = value
    return _proxy("GET", "/rxmer-analytics/options/fiber-nodes", params=params)


@api_bp.route('/admin/rxmer-analytics/jobs', methods=['GET'])
def network_rxmer_jobs():
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    return _proxy("GET", "/rxmer-analytics/jobs", params={"limit": request.args.get("limit", 100)})


@api_bp.route('/admin/rxmer-analytics/jobs/plan', methods=['POST'])
def network_rxmer_plan():
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    payload = request.get_json(silent=True) or {}
    payload["requested_by"] = session.get("username") or "admin"
    plan_timeout = max(
        30,
        min(int(os.environ.get("PYPNM_RXMER_PLAN_TIMEOUT_SEC", "600")), 600),
    )
    return _proxy(
        "POST",
        "/rxmer-analytics/jobs/plan",
        payload=payload,
        timeout=plan_timeout,
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>', methods=['GET'])
def network_rxmer_job(public_id):
    gate = _require_network_rxmer_analytics()
    return gate or _proxy("GET", f"/rxmer-analytics/jobs/{public_id}")


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/options', methods=['GET'])
def network_rxmer_job_options(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    path = f"/rxmer-analytics/jobs/{public_id}/options"
    if is_topology_scopes_enabled():
        return _proxy("GET", path)
    body, error = _get_pypnm_json(path)
    if error:
        return error
    body.pop("fiber_nodes", None)
    return jsonify(body)


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/modems', methods=['GET'])
def network_rxmer_modems(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {
        key: value
        for key, value in request.args.items()
        if key in {"cursor", "limit", "cmts", "fiber_node"}
    }
    params.setdefault("cursor", 0)
    params.setdefault("limit", 200)
    return _proxy(
        "GET",
        f"/rxmer-analytics/jobs/{public_id}/modems",
        params=params,
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/aggregates', methods=['GET'])
def network_rxmer_aggregates(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {key: value for key, value in request.args.items() if key in {"bucket_db", "cmts", "fiber_node"}}
    return _proxy("GET", f"/rxmer-analytics/jobs/{public_id}/aggregates", params=params)


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/report', methods=['GET'])
def network_rxmer_report(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {
        key: value
        for key, value in request.args.items()
        if key in {"format", "cmts", "fiber_node"}
    }
    return _stream_proxy(f"/rxmer-analytics/jobs/{public_id}/report", params=params)


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/subcarriers/report', methods=['GET'])
def network_rxmer_subcarrier_report(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {
        key: value
        for key, value in request.args.items()
        if key in {"format", "cmts", "fiber_node", "statistic"}
    }
    return _stream_proxy(
        f"/rxmer-analytics/jobs/{public_id}/subcarriers/report",
        params=params,
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/modems/subcarriers/report', methods=['GET'])
def network_rxmer_per_modem_subcarrier_report(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {
        key: value
        for key, value in request.args.items()
        if key in {"format", "cmts", "fiber_node"}
    }
    return _stream_proxy(
        f"/rxmer-analytics/jobs/{public_id}/modems/subcarriers/report",
        params=params,
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/spectrum', methods=['GET'])
def network_rxmer_spectrum(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    params = {
        key: value
        for key, value in request.args.items()
        if key in {"max_points", "cmts", "fiber_node", "statistic"}
    }
    params.setdefault("max_points", 1600)
    return _proxy(
        "GET",
        f"/rxmer-analytics/jobs/{public_id}/spectrum",
        params=params,
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/spectrum/materialize', methods=['POST'])
def network_rxmer_materialize_spectrum(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    return _proxy("POST", f"/rxmer-analytics/jobs/{public_id}/spectrum/materialize")


def _network_rxmer_pdf_source_get(path: str, *, params=None, timeout=120):
    """Read one authoritative stored-result payload for PDF formatting."""
    url = f"{_poller_api_base()}{path}"
    try:
        response = requests.get(
            url,
            params=params,
            timeout=(10, timeout),
        )
    except requests.Timeout:
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM stored-result request timed out",
        }), 504)
    except requests.RequestException:
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM API unavailable",
        }), 502)
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {"status": "error", "message": "PyPNM returned an invalid response"}
    if not response.ok:
        return None, (jsonify(body), response.status_code)
    if not isinstance(body, dict):
        return None, (jsonify({
            "status": "error",
            "message": "PyPNM returned an invalid stored-result payload",
        }), 502)
    return body, None


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/pdf', methods=['POST'])
def network_rxmer_pdf_start(public_id):
    """Queue a branded PDF from completed persisted RxMER analytics only."""
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    try:
        parsed_id = uuid.UUID(str(public_id))
    except (ValueError, AttributeError):
        return jsonify({"status": "error", "message": "Invalid RxMER job ID"}), 400
    if str(parsed_id) != str(public_id).lower():
        return jsonify({"status": "error", "message": "Invalid RxMER job ID"}), 400

    payload = request.get_json(silent=True) or {}
    allowed_fields = {"cmts", "fiber_node", "statistic"}
    if not isinstance(payload, dict) or set(payload) - allowed_fields:
        return jsonify({
            "status": "error",
            "message": "PDF request accepts only cmts, fiber_node, and statistic filters",
        }), 400
    cmts = str(payload.get("cmts") or "").strip()
    fiber_node = str(payload.get("fiber_node") or "").strip()
    statistic = str(payload.get("statistic") or "average").strip().lower()
    if len(cmts) > 128 or len(fiber_node) > 128:
        return jsonify({"status": "error", "message": "Report filters must not exceed 128 characters"}), 400
    if statistic not in {"average", "best", "worst"}:
        return jsonify({"status": "error", "message": "Invalid subcarrier statistic"}), 400

    job_path = f"/rxmer-analytics/jobs/{public_id}"
    job_response, error = _network_rxmer_pdf_source_get(job_path)
    if error:
        return error
    job = job_response.get("job") or {}
    allowed_statuses = {"completed", "completed_with_errors", "partial"}
    if job.get("status") not in allowed_statuses:
        return jsonify({
            "status": "error",
            "message": "PDF reports are available only for completed RxMER jobs",
        }), 409
    if int(job.get("channels_succeeded") or 0) <= 0:
        return jsonify({
            "status": "error",
            "message": "The selected RxMER job has no successful channel results",
        }), 409

    result_params = {}
    if cmts:
        result_params["cmts"] = cmts
    if fiber_node:
        result_params["fiber_node"] = fiber_node
    aggregates, error = _network_rxmer_pdf_source_get(
        f"{job_path}/aggregates",
        params={**result_params, "bucket_db": "0.5"},
    )
    if error:
        return error
    modem_payload, error = _network_rxmer_pdf_source_get(
        f"{job_path}/modems",
        params={**result_params, "cursor": "0", "limit": "200"},
    )
    if error:
        return error
    spectrum, error = _network_rxmer_pdf_source_get(
        f"{job_path}/spectrum",
        params={**result_params, "max_points": "1600", "statistic": statistic},
        timeout=600,
    )
    if error:
        return error
    if spectrum.get("state") != "ready" or not spectrum.get("points"):
        return jsonify({
            "status": "error",
            "message": spectrum.get("message") or "Build the stored RxMER spectrum before generating the PDF",
        }), 409

    final_job_response, error = _network_rxmer_pdf_source_get(job_path)
    if error:
        return error
    final_job = final_job_response.get("job") or {}
    stable_fields = (
        "status", "updated_at", "targets_total", "targets_succeeded",
        "targets_partial", "targets_failed", "channels_succeeded", "channels_failed",
    )
    if any(job.get(field) != final_job.get(field) for field in stable_fields):
        return jsonify({
            "status": "error",
            "message": "RxMER results changed while preparing the report; try again",
        }), 409

    source = {
        "success": True,
        "report_type": "network_rxmer",
        "public_id": public_id,
        "filters": {"cmts": cmts, "fiber_node": fiber_node, "statistic": statistic},
        "job": final_job,
        "aggregates": aggregates,
        "modems": modem_payload.get("targets") or [],
        "modems_truncated": bool(modem_payload.get("has_more")),
        "spectrum": spectrum,
    }
    from app.routes.pypnm_routes import _queue_stored_bulk_report
    report_id, total = _queue_stored_bulk_report(
        "network_rxmer",
        source,
        total_steps=4,
        access_scope="network_rxmer_authenticated",
    )
    return jsonify({"status": "success", "report_id": report_id, "total": total})


def _network_rxmer_report_job(report_id: str):
    if len(report_id) != 32 or any(char not in "0123456789abcdef" for char in report_id.lower()):
        return None
    from app.routes.pypnm_routes import _report_jobs, _report_lock
    with _report_lock:
        job = _report_jobs.get(report_id)
    if not job or job.get("report_type") != "network_rxmer":
        return None
    return job


@api_bp.route('/admin/rxmer-analytics/pdf/status/<report_id>', methods=['GET'])
def network_rxmer_pdf_status(report_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    if not _network_rxmer_report_job(report_id):
        return jsonify({"success": False, "error": "Report job not found"}), 404
    from app.routes.pypnm_routes import pnm_report_status
    return pnm_report_status(report_id)


@api_bp.route('/admin/rxmer-analytics/pdf/download/<report_id>', methods=['GET'])
def network_rxmer_pdf_download(report_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    if not _network_rxmer_report_job(report_id):
        return jsonify({"success": False, "error": "Report job not found"}), 404
    from app.routes.pypnm_routes import pnm_report_download
    return pnm_report_download(report_id)


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/results', methods=['DELETE'])
def network_rxmer_delete_results(public_id):
    gate = _require_network_rxmer_analytics()
    return gate or _proxy("DELETE", f"/rxmer-analytics/jobs/{public_id}/results")


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>', methods=['DELETE'])
def network_rxmer_delete_job(public_id):
    gate = _require_network_rxmer_analytics()
    return gate or _proxy("DELETE", f"/rxmer-analytics/jobs/{public_id}")


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/start', methods=['POST'])
def network_rxmer_start(public_id):
    gate = _require_network_rxmer_analytics()
    if gate:
        return gate
    scope_gate = _require_non_topology_job(f"/rxmer-analytics/jobs/{public_id}")
    if scope_gate:
        return scope_gate
    return _proxy(
        "POST",
        f"/rxmer-analytics/jobs/{public_id}/start",
        payload=_normalize_modem_community_payload(
            request.get_json(silent=True) or {"max_concurrency": 10},
            write=True,
        ),
    )


@api_bp.route('/admin/rxmer-analytics/jobs/<public_id>/cancel', methods=['POST'])
def network_rxmer_cancel(public_id):
    gate = _require_network_rxmer_analytics()
    return gate or _proxy("POST", f"/rxmer-analytics/jobs/{public_id}/cancel")


# ── CM Bulk Reset ────────────────────────────────────────────


def _require_cm_bulk_reset():
    gate = _require_admin()
    if gate:
        return gate
    if not is_cm_bulk_reset_enabled():
        return jsonify({"status": "error", "message": "CM Bulk Reset is disabled"}), 404
    return _require_topology_scopes()


@api_bp.route('/admin/cm-reset/capabilities', methods=['GET'])
def cm_reset_capabilities():
    gate = _require_cm_bulk_reset()
    return gate or _proxy("GET", "/cm-reset/capabilities")


@api_bp.route('/admin/cm-reset/options/cmts', methods=['GET'])
def cm_reset_cmts_options():
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"limit"}}
    return _proxy("GET", "/cm-reset/options/cmts", params=params)


@api_bp.route('/admin/cm-reset/options/fiber-nodes', methods=['GET'])
def cm_reset_fiber_node_options():
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"cmts", "limit"}}
    return _proxy("GET", "/cm-reset/options/fiber-nodes", params=params)


@api_bp.route('/admin/cm-reset/jobs', methods=['GET'])
def cm_reset_jobs():
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"limit"}}
    return _proxy("GET", "/cm-reset/jobs", params=params)


@api_bp.route('/admin/cm-reset/jobs/plan', methods=['POST'])
def cm_reset_plan():
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    return _proxy("POST", "/cm-reset/jobs/plan", payload=request.get_json(silent=True) or {})


@api_bp.route('/admin/cm-reset/jobs/<public_id>', methods=['GET'])
def cm_reset_job(public_id):
    gate = _require_cm_bulk_reset()
    return gate or _proxy("GET", f"/cm-reset/jobs/{public_id}")


@api_bp.route('/admin/cm-reset/jobs/<public_id>/start', methods=['POST'])
def cm_reset_start(public_id):
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    scope_gate = _require_non_topology_job(f"/cm-reset/jobs/{public_id}")
    if scope_gate:
        return scope_gate
    return _proxy(
        "POST",
        f"/cm-reset/jobs/{public_id}/start",
        payload=request.get_json(silent=True) or {},
    )


@api_bp.route('/admin/cm-reset/jobs/<public_id>/cancel', methods=['POST'])
def cm_reset_cancel(public_id):
    gate = _require_cm_bulk_reset()
    return gate or _proxy("POST", f"/cm-reset/jobs/{public_id}/cancel")


@api_bp.route('/admin/cm-reset/jobs/<public_id>', methods=['DELETE'])
def cm_reset_delete(public_id):
    gate = _require_cm_bulk_reset()
    return gate or _proxy("DELETE", f"/cm-reset/jobs/{public_id}")


@api_bp.route('/admin/cm-reset/jobs/<public_id>/targets', methods=['GET'])
def cm_reset_targets(public_id):
    gate = _require_cm_bulk_reset()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"cursor", "limit", "state"}}
    return _proxy("GET", f"/cm-reset/jobs/{public_id}/targets", params=params)


# ── Custom SNMP Query ────────────────────────────────────────


def _require_custom_snmp():
    gate = _require_admin()
    if gate:
        return gate
    if not is_custom_snmp_enabled():
        return jsonify({"status": "error", "message": "Custom SNMP is disabled"}), 404
    return _require_topology_scopes()


@api_bp.route('/admin/custom-snmp/capabilities', methods=['GET'])
def custom_snmp_capabilities():
    gate = _require_custom_snmp()
    return gate or _proxy("GET", "/custom-snmp/capabilities")


@api_bp.route('/admin/custom-snmp/options/cmts', methods=['GET'])
def custom_snmp_cmts_options():
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"limit"}}
    return _proxy("GET", "/custom-snmp/options/cmts", params=params)


@api_bp.route('/admin/custom-snmp/options/fiber-nodes', methods=['GET'])
def custom_snmp_fiber_node_options():
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"cmts", "limit"}}
    return _proxy("GET", "/custom-snmp/options/fiber-nodes", params=params)


@api_bp.route('/admin/custom-snmp/templates', methods=['GET'])
def custom_snmp_templates():
    gate = _require_custom_snmp()
    return gate or _proxy("GET", "/custom-snmp/templates")


@api_bp.route('/admin/custom-snmp/templates', methods=['POST'])
def custom_snmp_create_template():
    gate = _require_custom_snmp()
    if gate:
        return gate
    return _proxy("POST", "/custom-snmp/templates", payload=request.get_json(silent=True) or {})


@api_bp.route('/admin/custom-snmp/templates/<int:template_id>', methods=['DELETE'])
def custom_snmp_delete_template(template_id):
    gate = _require_custom_snmp()
    return gate or _proxy("DELETE", f"/custom-snmp/templates/{template_id}")


@api_bp.route('/admin/custom-snmp/jobs', methods=['GET'])
def custom_snmp_jobs():
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"limit"}}
    return _proxy("GET", "/custom-snmp/jobs", params=params)


@api_bp.route('/admin/custom-snmp/jobs/plan', methods=['POST'])
def custom_snmp_plan():
    gate = _require_custom_snmp()
    if gate:
        return gate
    return _proxy("POST", "/custom-snmp/jobs/plan", payload=request.get_json(silent=True) or {})


@api_bp.route('/admin/custom-snmp/jobs/<public_id>', methods=['GET'])
def custom_snmp_job(public_id):
    gate = _require_custom_snmp()
    return gate or _proxy("GET", f"/custom-snmp/jobs/{public_id}")


@api_bp.route('/admin/custom-snmp/jobs/<public_id>/start', methods=['POST'])
def custom_snmp_start(public_id):
    gate = _require_custom_snmp()
    if gate:
        return gate
    scope_gate = _require_non_topology_job(f"/custom-snmp/jobs/{public_id}")
    if scope_gate:
        return scope_gate
    return _proxy(
        "POST",
        f"/custom-snmp/jobs/{public_id}/start",
        payload=_normalize_modem_community_payload(request.get_json(silent=True) or {}),
    )


@api_bp.route('/admin/custom-snmp/jobs/<public_id>/cancel', methods=['POST'])
def custom_snmp_cancel(public_id):
    gate = _require_custom_snmp()
    return gate or _proxy("POST", f"/custom-snmp/jobs/{public_id}/cancel")


@api_bp.route('/admin/custom-snmp/jobs/<public_id>', methods=['DELETE'])
def custom_snmp_delete(public_id):
    gate = _require_custom_snmp()
    return gate or _proxy("DELETE", f"/custom-snmp/jobs/{public_id}")


@api_bp.route('/admin/custom-snmp/jobs/<public_id>/targets', methods=['GET'])
def custom_snmp_targets(public_id):
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"cursor", "limit"}}
    return _proxy("GET", f"/custom-snmp/jobs/{public_id}/targets", params=params)


@api_bp.route('/admin/custom-snmp/jobs/<public_id>/report', methods=['GET'])
def custom_snmp_report(public_id):
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"format"}}
    return _stream_proxy(f"/custom-snmp/jobs/{public_id}/report", params=params)



@api_bp.route('/admin/custom-snmp/verify-oid', methods=['POST'])
def custom_snmp_verify_oid():
    gate = _require_custom_snmp()
    if gate:
        return gate
    return _proxy(
        "POST",
        "/custom-snmp/verify-oid",
        payload=_normalize_modem_community_payload(request.get_json(silent=True) or {}),
    )


@api_bp.route('/admin/custom-snmp/mib-search', methods=['GET'])
def custom_snmp_mib_search():
    gate = _require_custom_snmp()
    if gate:
        return gate
    params = {k: v for k, v in request.args.items() if k in {"q", "limit"}}
    return _proxy("GET", "/custom-snmp/mib-search", params=params)


@api_bp.route('/admin/custom-snmp/jobs', methods=['DELETE'])
def custom_snmp_delete_all():
    gate = _require_custom_snmp()
    return gate or _proxy("DELETE", "/custom-snmp/jobs")
