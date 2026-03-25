from __future__ import annotations

import json
import os
import re
from io import BytesIO

import requests
from flask import Response, current_app, jsonify, render_template, request, session

from . import topology_bp


try:
    import redis
    _REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    _REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    _TOPOLOGY_CACHE_TTL = int(os.environ.get('TOPOLOGY_CACHE_TTL', '604800'))
    _topology_redis = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
    _topology_redis.ping()
    _TOPOLOGY_REDIS_AVAILABLE = True
except Exception:
    _topology_redis = None
    _TOPOLOGY_REDIS_AVAILABLE = False


def _topology_cache_key(selected_date: str | None = None) -> str:
    return f"topology:summary:{selected_date or '__latest__'}"


def _clear_topology_cache(selected_date: str | None = None) -> None:
    if not _TOPOLOGY_REDIS_AVAILABLE or not _topology_redis:
        return
    try:
        _topology_redis.delete(_topology_cache_key(selected_date))
        _topology_redis.delete(_topology_cache_key(None))
    except Exception:
        pass


def _pypnm_base_url() -> str:
    return (os.environ.get('PYPNM_API_URL') or os.environ.get('PYPNM_BASE_URL') or 'http://127.0.0.1:8000').rstrip('/')


def _normalize_mac_display(mac: str) -> str:
    """Normalize MAC to canonical xx:xx:xx:xx:xx:xx when possible."""
    raw = str(mac or '').strip()
    if not raw:
        return ''
    clean = re.sub(r'[^0-9a-fA-F]', '', raw)
    if len(clean) != 12:
        return raw
    return ':'.join(clean.lower()[i:i + 2] for i in range(0, 12, 2))


def _load_topology_summary(selected_date: str | None = None) -> dict:
    base_url = _pypnm_base_url()
    connect_timeout = int(os.environ.get('PYPNM_API_CONNECT_TIMEOUT', '5'))
    read_timeout = int(os.environ.get('PYPNM_TOPOLOGY_READ_TIMEOUT', '120'))
    params: dict[str, str] = {'auto_import': 'false'}
    if selected_date:
        params['date'] = selected_date

    if _TOPOLOGY_REDIS_AVAILABLE and _topology_redis:
        try:
            cached = _topology_redis.get(_topology_cache_key(selected_date))
            if cached:
                payload = json.loads(cached)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass

    response = requests.get(f"{base_url}/api/topology/summary", params=params, timeout=(connect_timeout, read_timeout))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {'status': 'error', 'error': 'invalid topology summary payload'}

    if _TOPOLOGY_REDIS_AVAILABLE and _topology_redis:
        try:
            _topology_redis.setex(_topology_cache_key(selected_date), _TOPOLOGY_CACHE_TTL, json.dumps(payload))
        except Exception:
            pass
    return payload


def _is_admin() -> bool:
    return bool(session.get('user_id')) and session.get('role') == 'admin'


@topology_bp.route('/topology')
def topology_page():
    """Render topology explorer page using topology data from PyPNM API."""
    base_path = current_app.config.get('APP_ROOT', '') or os.environ.get('APPLICATION_ROOT', '').rstrip('/')
    selected_date = (request.args.get('date') or '').strip() or None
    try:
        data = _load_topology_summary(selected_date=selected_date)
    except Exception as exc:
        data = {
            'files': {
                'topology_file': None,
                'modemlocation_file': None,
                'pair_date': None,
                'available_pair_dates': [],
                'warnings': [f'failed to load topology from PyPNM API: {exc}'],
                'image_files': [],
            },
            'stats': {
                'topology_nodes': 0,
                'topology_edges': 0,
                'modems': 0,
                'fiber_nodes': 0,
                'matched_by_linkid': 0,
                'potential_fibernode_match': 0,
                'unmatched_modems': 0,
                'node_type_counts': {},
            },
            'topology_nodes': [],
            'topology_edges': [],
            'modems': [],
        }
    data_files = data.setdefault('files', {})
    data_files['selected_date'] = selected_date
    return render_template(
        'topology.html',
        base_path=base_path,
        auth_username=session.get('username', ''),
        auth_role=session.get('role', 'user'),
        topology=data,
    )


@topology_bp.route('/api/topology/summary')
def topology_summary_api():
    """Provide topology summary data from PyPNM API for UI use."""
    try:
        selected_date = (request.args.get('date') or '').strip() or None
        data = _load_topology_summary(selected_date=selected_date)
        sample_modems = data.get('modems', [])[:200]
        if isinstance(sample_modems, list):
            for m in sample_modems:
                if isinstance(m, dict) and 'mac' in m:
                    m['mac'] = _normalize_mac_display(m.get('mac', ''))

        return jsonify(
            {
                'status': 'success',
                'files': data.get('files', {}),
                'stats': data.get('stats', {}),
                'sample_nodes': data.get('topology_nodes', [])[:200],
                'sample_modems': sample_modems,
            }
        )
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 502


@topology_bp.route('/api/topology/datasets')
def topology_datasets_api():
    """List available topology filedate datasets from PyPNM API."""
    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        response = requests.get(f"{base_url}/api/topology/datasets", timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'datasets': []}
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 502


@topology_bp.route('/api/topology/search/suggest')
def topology_search_suggest_api():
    """Suggest topology search values (fibernode, postal_house, customer_id)."""
    search_type = (request.args.get('type') or '').strip().lower()
    query = (request.args.get('q') or '').strip()
    selected_date = (request.args.get('date') or '').strip() or None
    limit = int(request.args.get('limit') or 10)

    if search_type not in {'fibernode', 'postal_house', 'customer_id'}:
        return jsonify({'status': 'error', 'message': 'invalid type'}), 400

    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        params = {'type': search_type, 'q': query, 'limit': str(limit)}
        if selected_date:
            params['date'] = selected_date
        response = requests.get(f"{base_url}/api/topology/search/suggest", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'suggestions': []}
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc), 'suggestions': []}), 502


@topology_bp.route('/api/topology/search/modems')
def topology_search_modems_api():
    """Search topology modems by fibernode, postal+house, or customer_id."""
    search_type = (request.args.get('type') or '').strip().lower()
    value = (request.args.get('value') or '').strip()
    house_number = (request.args.get('house_number') or '').strip()
    selected_date = (request.args.get('date') or '').strip() or None
    limit = int(request.args.get('limit') or 200)

    if search_type not in {'fibernode', 'postal_house', 'customer_id'}:
        return jsonify({'status': 'error', 'message': 'invalid type'}), 400

    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '45'))
        params = {'type': search_type, 'value': value, 'limit': str(limit)}
        if selected_date:
            params['date'] = selected_date
        if house_number:
            params['house_number'] = house_number
        response = requests.get(f"{base_url}/api/topology/search/modems", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'modems': []}
        if isinstance(payload, dict) and isinstance(payload.get('modems'), list):
            for modem in payload['modems']:
                if isinstance(modem, dict) and 'mac' in modem:
                    modem['mac'] = _normalize_mac_display(modem.get('mac', ''))
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc), 'modems': []}), 502


@topology_bp.route('/api/topology/path')
def topology_path_api():
    """Lookup topology hierarchy path for a given node id (typically fibernode)."""
    node_id = (request.args.get('node_id') or '').strip()
    selected_date = (request.args.get('date') or '').strip() or None
    if not node_id:
        return jsonify({'status': 'error', 'message': 'node_id is required'}), 400
    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        params = {'node_id': node_id}
        if selected_date:
            params['date'] = selected_date
        response = requests.get(f"{base_url}/api/topology/path/by-node", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'path': None}
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc), 'path': None}), 502


@topology_bp.route('/api/topology/node-meta')
def topology_node_meta_api():
    """Lookup structured topology metadata for one or more node ids."""
    node_ids = (request.args.get('node_ids') or '').strip()
    direction = (request.args.get('direction') or '').strip() or None
    selected_date = (request.args.get('date') or '').strip() or None
    if not node_ids:
        return jsonify({'status': 'error', 'message': 'node_ids is required', 'node_meta': {}}), 400
    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        params = {'node_ids': node_ids}
        if direction:
            params['direction'] = direction
        if selected_date:
            params['date'] = selected_date
        response = requests.get(f"{base_url}/api/topology/node-meta", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'node_meta': {}}
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc), 'node_meta': {}}), 502


@topology_bp.route('/api/topology/serving-group-meta')
def topology_serving_group_meta_api():
    """Lookup topology metadata for one or more serving groups."""
    groups = (request.args.get('groups') or '').strip()
    direction = (request.args.get('direction') or '').strip() or None
    selected_date = (request.args.get('date') or '').strip() or None
    if not groups:
        return jsonify({'status': 'error', 'message': 'groups is required', 'serving_group_meta': {}}), 400
    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        params = {'groups': groups}
        if direction:
            params['direction'] = direction
        if selected_date:
            params['date'] = selected_date
        response = requests.get(f"{base_url}/api/topology/serving-group-meta", params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json() if response.content else {'status': 'success', 'serving_group_meta': {}}
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc), 'serving_group_meta': {}}), 502


@topology_bp.route('/api/topology/import', methods=['POST'])
def topology_import_api():
    """Admin-only trigger — starts a background import and returns the initial job status."""
    if not _is_admin():
        return jsonify({'status': 'error', 'message': 'admin role required'}), 403

    payload = request.get_json(silent=True) or {}
    selected_date = (str(payload.get('date') or '')).strip()
    force = bool(payload.get('force', False))
    if not selected_date:
        return jsonify({'status': 'error', 'message': 'date is required'}), 400

    try:
        _clear_topology_cache(selected_date)
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
        response = requests.post(
            f"{base_url}/api/topology/import",
            params={'date': selected_date, 'force': 'true' if force else 'false'},
            timeout=timeout,
        )
        if response.status_code >= 400:
            detail = None
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return jsonify({'status': 'error', 'message': f'import failed for {selected_date}', 'detail': detail}), 502
        return jsonify(response.json() if response.content else {'status': 'success', 'snapshot_date': selected_date})
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 502


@topology_bp.route('/api/topology/import/status')
def topology_import_status_api():
    """Proxy import job status from PyPNM API for GUI progress polling."""
    selected_date = (request.args.get('date') or '').strip()
    if not selected_date:
        return jsonify({'status': 'error', 'message': 'date is required'}), 400
    try:
        base_url = _pypnm_base_url()
        timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '15'))
        response = requests.get(
            f"{base_url}/api/topology/import/status",
            params={'date': selected_date},
            timeout=timeout,
        )
        if response.status_code == 404:
            return jsonify({'status': 'error', 'message': 'no import job found', 'state': 'none'}), 404
        if response.status_code >= 400:
            return jsonify({'status': 'error', 'message': 'status check failed'}), 502
        payload = response.json() if response.content else {'status': 'error'}
        if isinstance(payload, dict) and payload.get('state') == 'done':
            _clear_topology_cache(selected_date)
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 502


@topology_bp.route('/topology/assets/<path:filename>')
def topology_asset(filename: str):
    """Proxy topology relation images from PyPNM API volume endpoint."""
    safe_name = os.path.basename(filename)
    base_url = _pypnm_base_url()
    timeout = int(os.environ.get('PYPNM_API_TIMEOUT', '30'))
    response = requests.get(f"{base_url}/api/topology/assets/{safe_name}", timeout=timeout)
    if response.status_code >= 400:
        return jsonify({'status': 'error', 'message': f'asset not found: {safe_name}'}), 404
    return Response(BytesIO(response.content).read(), mimetype=response.headers.get('content-type', 'application/octet-stream'))
