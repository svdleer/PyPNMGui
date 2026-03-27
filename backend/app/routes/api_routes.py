# PyPNM Web GUI - API Routes

import os
import re
import json
import logging
import time
import threading
import uuid
from datetime import datetime, timezone
from flask import jsonify, request, current_app
from . import api_bp
from app.core.cmts_provider import CMTSProvider
from app.core.pypnm_client import PyPNMClient
from app.core.topology_db import topology_db
from app.core.modem_filters import filter_ignored_modems

# ── Background modem-load job store ─────────────────────────────────────────
# job_id -> {status, modems, count, enriched, enriching, enrichment_progress,
#             error, cmts_ip, cmts_hostname, agent_id, started_at}
_modem_jobs: dict = {}
_modem_jobs_lock = threading.Lock()


def _run_modem_job(job_id: str, cmts_ip: str, cmts_name: str,
                   community: str, limit: int, enrich: bool,
                   modem_community: str):
    """Run in a background thread. Calls PyPNM and updates the job store."""
    _log = logging.getLogger(__name__)
    try:
        client = PyPNMClient()
        result = client.get_cmts_modems(
            cmts_ip=cmts_ip, community=community,
            limit=limit, enrich=enrich, modem_community=modem_community
        )
        if result.get('success'):
            modems = result.get('modems', [])
            for m in modems:
                m['cmts_ip'] = cmts_ip
                m['cmts_community'] = community
            with _modem_jobs_lock:
                _modem_jobs[job_id].update({
                    'status': 'done',
                    'modems': modems,
                    'count': len(modems),
                    'enriched': result.get('enriched', False),
                    'enriching': result.get('enriching', False),
                    'enrichment_progress': result.get('enrichment_progress') or result.get('enrich_progress'),
                    'agent_id': result.get('agent_id', 'agent'),
                    'cmts_hostname': cmts_name,
                })
        else:
            with _modem_jobs_lock:
                _modem_jobs[job_id]['status'] = 'error'
                _modem_jobs[job_id]['error'] = result.get('error', 'Unknown error')
    except Exception as exc:
        _log.exception('Background modem job failed')
        with _modem_jobs_lock:
            _modem_jobs[job_id]['status'] = 'error'
            _modem_jobs[job_id]['error'] = str(exc)

logger = logging.getLogger(__name__)

# Default TFTP server (same as pypnm_routes.py)
DEFAULT_TFTP_IP = os.environ.get('TFTP_IPV4', '127.0.0.1')


def get_default_community():
    """Get default SNMP community for modems."""
    return os.environ.get('MODEM_COMMUNITY', os.environ.get('CM_SNMP_COMMUNITY', 'private'))


def get_cmts_community():
    """Get default SNMP community for CMTS operations."""
    return os.environ.get('CMTS_COMMUNITY', os.environ.get('CMTS_SNMP_COMMUNITY', 'public'))


# Redis for caching modem data
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    REDIS_TTL = int(os.environ.get('REDIS_TTL', '86400'))  # 24 hour cache
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    print(f"[INFO] Redis cache connected: {REDIS_HOST}:{REDIS_PORT}", flush=True)
except Exception as e:
    REDIS_AVAILABLE = False
    redis_client = None
    print(f"[WARNING] Redis not available: {e}", flush=True)


def _redis_cache_modems_for_key(cache_key: str, cmts_name: str, modems: list[dict], requested_limit: int = 10000) -> None:
    if not REDIS_AVAILABLE or not redis_client or not cache_key:
        return
    try:
        modems = filter_ignored_modems(modems)
        payload = json.dumps({
            "cmts": cmts_name,
            "requested_limit": requested_limit,
            "modems": modems,
            "timestamp": int(time.time()),
            "source": "pypnm-inventory",
        })
        redis_client.setex(cache_key, REDIS_TTL, payload)
    except Exception as exc:
        logger.warning(f"Redis modem cache write error for {cache_key}: {exc}")


def _backfill_redis_from_inventory(modems: list[dict], requested_limit: int = 10000) -> None:
    if not REDIS_AVAILABLE or not redis_client or not modems:
        return

    modems = filter_ignored_modems(modems)

    grouped: dict[str, list[dict]] = {}
    aliases: dict[str, str] = {}
    for modem in modems:
        cmts_name = str(modem.get('cmts') or '').strip()
        cmts_ip = str(modem.get('cmts_ip') or '').strip()
        if cmts_name:
            grouped.setdefault(cmts_name, []).append(modem)
            if cmts_ip and cmts_ip != cmts_name:
                aliases[cmts_ip] = cmts_name
        elif cmts_ip:
            grouped.setdefault(cmts_ip, []).append(modem)

    for group_name, rows in grouped.items():
        _redis_cache_modems_for_key(f"modems:{group_name}", group_name, rows, requested_limit=requested_limit)

    for alias_key, group_name in aliases.items():
        rows = grouped.get(group_name) or []
        if rows:
            _redis_cache_modems_for_key(f"modems:{alias_key}", group_name, rows, requested_limit=requested_limit)


def _parse_inventory_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _inventory_snapshot_is_fresh(modems: list[dict]) -> bool:
    if not modems:
        return False
    timestamps = [_parse_inventory_timestamp(m.get("updated_at")) for m in modems]
    timestamps = [dt for dt in timestamps if dt is not None]
    if not timestamps:
        return False
    oldest = min(timestamps)
    age_seconds = (datetime.now(timezone.utc) - oldest).total_seconds()
    return age_seconds <= REDIS_TTL


# Minimum fraction of modems that must have both vendor AND firmware populated
# for the dataset to be considered truly enriched.
_ENRICH_QUALITY_THRESHOLD = 0.40


def _modems_are_enriched(modems: list[dict]) -> bool:
    """Return True only when a meaningful portion of modems have vendor+firmware data."""
    if not modems:
        return False
    sample = modems[:200]  # Check up to 200 rows for speed
    enriched_count = sum(
        1 for m in sample
        if (m.get('vendor') or '').strip().lower() not in ('', 'unknown')
        and (m.get('software_version') or m.get('firmware') or '').strip()
    )
    return (enriched_count / len(sample)) >= _ENRICH_QUALITY_THRESHOLD


def _modem_missing_enrichment(modem: dict) -> bool:
    vendor = str(modem.get('vendor') or '').strip().lower()
    fw = str(modem.get('software_version') or modem.get('firmware') or '').strip().lower()
    vendor_missing = vendor in ('', 'unknown', 'n/a')
    fw_missing = fw in ('', 'unknown', 'n/a')
    return vendor_missing or fw_missing


def _topology_fields_by_mac(mac_addresses: list[str]) -> dict[str, dict]:
    """Best-effort lookup of topology fields keyed by bare uppercase MAC."""
    if not mac_addresses:
        return {}

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    wanted = sorted({m for m in (_bare(v) for v in mac_addresses) if m})
    if not wanted:
        return {}

    out: dict[str, dict] = {}
    conn = None
    try:
        conn = topology_db._connect()
        cur = conn.cursor()
        marker = "%s"
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            placeholders = ",".join([marker] * len(chunk))
            sql = (
                "SELECT UPPER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-','')) AS mac_norm, "
                "MIN(linked_node_id) AS linked_node_id, MIN(lat) AS lat, MIN(lon) AS lon, "
                "MIN(fibernode) AS fibernode, MIN(customer_id) AS customer_id, MIN(address) AS address "
                "FROM topology_modems "
                f"WHERE UPPER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-','')) IN ({placeholders}) "
                "GROUP BY UPPER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-',''))"
            )
            cur.execute(sql, tuple(chunk))
            rows = cur.fetchall() or []
            for row in rows:
                r = dict(row) if hasattr(row, "keys") else row
                mac_norm = str(r.get("mac_norm") or "").strip().upper()
                if not mac_norm:
                    continue
                out[mac_norm] = {
                    "linked_node_id": r.get("linked_node_id") or "",
                    "lat": r.get("lat"),
                    "lon": r.get("lon"),
                    "fibernode": r.get("fibernode") or "",
                    "customer_id": r.get("customer_id") or "",
                    "address": r.get("address") or "",
                }
    except Exception as exc:
        logger.warning(f"Topology MAC lookup skipped: {exc}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return out


def _inventory_fields_by_mac(mac_addresses: list[str], cmts_name: str = "") -> dict[str, dict]:
    """Bulk lookup of fiber_node/cable_mac from PyPNM inventory API."""
    if not mac_addresses:
        return {}

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    wanted = {m for m in (_bare(v) for v in mac_addresses) if m}
    if not wanted:
        return {}

    out: dict[str, dict] = {}
    try:
        client = PyPNMClient()
        inv_resp = client.get_inventory_modems_bulk([v for v in mac_addresses if v])
        for m in (inv_resp.get('modems') or []):
            mac_norm = _bare(m.get('mac_address') or m.get('mac') or '')
            if mac_norm and mac_norm in wanted:
                fn = m.get('fiber_node') or ''
                if fn:
                    out[mac_norm] = {
                        'fiber_node': fn,
                        'cable_mac': m.get('cable_mac') or '',
                        'ofdm_enabled': m.get('ofdm_enabled'),
                        'ofdma_enabled': m.get('ofdma_enabled'),
                        'docsis_version': m.get('docsis_version') or '',
                        'vendor': m.get('vendor') or '',
                    }
    except Exception as exc:
        logger.warning(f"Inventory MAC lookup via PyPNM API skipped: {exc}")
    return out


def _augment_modems_with_topology_fields(modems: list[dict], cmts_name: str = "") -> list[dict]:
    """In-place best-effort merge of linked_node_id/lat/lon and inventory fiber_node/cable_mac."""
    if not modems:
        return modems

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    topo = _topology_fields_by_mac([m.get("mac_address") for m in modems if isinstance(m, dict)])

    # Backfill fiber_node / cable_mac / ofdm(a)_enabled / docsis_version from
    # modem_inventory_current when missing. Critical for the FN scanner.
    inv: dict[str, dict] = {}
    need_inv = [m for m in modems if isinstance(m, dict) and (
        not m.get("fiber_node") or m.get("ofdm_enabled") is None
    )]
    if need_inv:
        inv = _inventory_fields_by_mac([m.get("mac_address") for m in need_inv], cmts_name=cmts_name)

    for m in modems:
        if not isinstance(m, dict):
            continue
        bare = _bare(m.get("mac_address"))
        t = topo.get(bare) if topo else None
        if t:
            if not m.get("linked_node_id") and t.get("linked_node_id"):
                m["linked_node_id"] = t.get("linked_node_id")
            if (m.get("lat") is None or m.get("lat") == "") and t.get("lat") is not None:
                m["lat"] = t.get("lat")
            if (m.get("lon") is None or m.get("lon") == "") and t.get("lon") is not None:
                m["lon"] = t.get("lon")
            if not m.get("fiber_node") and t.get("fibernode"):
                m["fiber_node"] = t["fibernode"]
            if not m.get("customer_id") and t.get("customer_id"):
                m["customer_id"] = t["customer_id"]
            if not m.get("address") and t.get("address"):
                m["address"] = t["address"]
        iv = inv.get(bare)
        if iv:
            if not m.get("fiber_node") and iv.get("fiber_node"):
                m["fiber_node"] = iv["fiber_node"]
            if not m.get("cable_mac") and iv.get("cable_mac"):
                m["cable_mac"] = iv["cable_mac"]
            if m.get("ofdm_enabled") is None and iv.get("ofdm_enabled") is not None:
                m["ofdm_enabled"] = bool(iv["ofdm_enabled"])
            if m.get("ofdma_enabled") is None and iv.get("ofdma_enabled") is not None:
                m["ofdma_enabled"] = bool(iv["ofdma_enabled"])
            if not m.get("docsis_version") and iv.get("docsis_version"):
                m["docsis_version"] = iv["docsis_version"]
            if not m.get("vendor") and iv.get("vendor"):
                m["vendor"] = iv["vendor"]
    return modems


# Helper function to handle agent task results
def handle_agent_result(result, success_field='success'):
    """Handle agent task result with proper None checking."""
    logger = logging.getLogger(__name__)
    
    if not result:
        logger.warning("Agent task returned None (timeout or no response)")
        return jsonify({"status": "error", "message": "Agent task timeout or no response"}), 504
    
    result_data = result.get('result')
    if not result_data:
        logger.warning(f"Agent task returned empty result: {result}")
        return jsonify({"status": "error", "message": "No result from agent"}), 500
    
    if result_data.get(success_field):
        return jsonify(result_data)
    
    error_msg = result_data.get('error', 'Unknown error')
    logger.warning(f"Agent task failed: {error_msg}")
    return jsonify({"status": "error", "message": error_msg}), 500


# ============== Cable Modem Endpoints ==============

@api_bp.route('/modems', methods=['GET'])
def get_modems():
    """Search cached cable modems across one or all CMTS entries.

    Query params:
      - search_type: ip | mac | name
      - search_value: string to match
      - cmts: optional CMTS hostname to scope the search
      - interface: optional interface filter

    Notes:
      - This endpoint is cache-backed and intentionally does not trigger live SNMP walks.
      - Call /api/cmts/<hostname>/modems first to load cache for a CMTS.
    """
    search_type = (request.args.get('search_type') or '').strip().lower()
    search_value = (request.args.get('search_value') or '').strip().lower()
    cmts_filter = (request.args.get('cmts') or '').strip()
    iface_filter = (request.args.get('interface') or '').strip().lower()

    # MySQL inventory fallback path when Redis is unavailable.
    if not REDIS_AVAILABLE or not redis_client:
        try:
            modems_resp = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type=search_type or None,
                search_value=search_value or None,
                interface=iface_filter or None,
                limit=10000,
            )
            modems = filter_ignored_modems(modems_resp.get('modems') or [])
            _augment_modems_with_topology_fields(modems)
            return jsonify({
                "status": "success",
                "modems": modems,
                "count": len(modems),
                "cached": False,
                "source": modems_resp.get('source') or "pypnm-inventory",
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Modem cache unavailable and PyPNM inventory fallback failed: {e}"
            }), 503

    try:
        keys = [f"modems:{cmts_filter}"] if cmts_filter else redis_client.keys('modems:*')
        seen_macs: set[str] = set()
        modems = []

        for key in keys:
            cached = redis_client.get(key)
            if not cached:
                continue
            payload = json.loads(cached)
            cmts_name = str(payload.get('cmts') or key.split(':', 1)[-1])
            for m in payload.get('modems', []):
                mac_key = str(m.get('mac_address', '')).lower().replace(':', '').replace('-', '')
                if mac_key in seen_macs:
                    continue
                seen_macs.add(mac_key)
                row = dict(m)
                row.setdefault('cmts', cmts_name)
                modems.append(row)

        modems = filter_ignored_modems(modems)

        if not modems:
            # If Redis has no records yet, fallback to PyPNM inventory snapshot.
            db_resp = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type=search_type or None,
                search_value=search_value or None,
                interface=iface_filter or None,
                limit=10000,
            )
            db_modems = filter_ignored_modems(db_resp.get('modems') or [])
            if db_modems:
                _backfill_redis_from_inventory(db_modems, requested_limit=10000)
                _augment_modems_with_topology_fields(db_modems)
                return jsonify({
                    "status": "success",
                    "modems": db_modems,
                    "count": len(db_modems),
                    "cached": False,
                    "source": db_resp.get('source') or "pypnm-inventory",
                })
            msg = f"No cached modems for CMTS '{cmts_filter}'. Load modems first." if cmts_filter else "No cached modems found. Load modems from a CMTS first."
            return jsonify({"status": "success", "modems": [], "count": 0, "message": msg})

        def _norm_mac(v: str) -> str:
            return ''.join(ch for ch in (v or '').lower() if ch.isalnum())

        # Apply search filter (if requested)
        if search_value:
            if search_type == 'ip':
                modems = [m for m in modems if search_value in str(m.get('ip_address', '')).lower()]
            elif search_type == 'mac':
                q = _norm_mac(search_value)
                modems = [m for m in modems if q in _norm_mac(str(m.get('mac_address', '')))]
            elif search_type == 'name':
                modems = [
                    m for m in modems
                    if search_value in str(m.get('name', '')).lower()
                    or search_value in str(m.get('hostname', '')).lower()
                    or search_value in str(m.get('alias', '')).lower()
                ]
            elif search_type == 'fiber_node':
                modems = [
                    m for m in modems
                    if search_value in str(m.get('fiber_node', '')).lower()
                ]

        # Apply interface filter (if requested)
        if iface_filter:
            def _iface_match(m: dict) -> bool:
                fields = (
                    str(m.get('interface', '')).lower(),
                    str(m.get('cmts_interface', '')).lower(),
                    str(m.get('upstream_interface', '')).lower(),
                    str(m.get('cable_mac', '')).lower(),
                )
                return any(iface_filter in f for f in fields)
            modems = [m for m in modems if _iface_match(m)]

        # Stable ordering for UI
        modems.sort(key=lambda m: (str(m.get('cmts', '')), str(m.get('mac_address', ''))))

        # Enrich inventory results with topology fields (fibernode, customer_id, lat/lon)
        _augment_modems_with_topology_fields(modems)

        return jsonify({
            "status": "success",
            "modems": modems,
            "count": len(modems),
            "cached": True,
        })
    except Exception as e:
        logger.error(f"Error searching cached modems: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modems/<mac_address>', methods=['GET'])
def get_modem(mac_address):
    """Get a specific modem by MAC address from cache or mock data."""
    # Normalise both to bare hex (no separators) for comparison so that
    # 5CFA25A1CA92, 5c:fa:25:a1:ca:92, and 5c-fa-25-a1-ca-92 all match.
    def _bare(mac):
        return re.sub(r'[^a-f0-9]', '', (mac or '').lower())

    mac_bare = _bare(mac_address)

    # Try to find in Redis cache first
    if REDIS_AVAILABLE and redis_client:
        try:
            keys = redis_client.keys('modems:*')
            for key in keys:
                cached = redis_client.get(key)
                if cached:
                    data = json.loads(cached)
                    modems = data.get('modems', [])
                    for modem in modems:
                        if _bare(modem.get('mac_address', '')) == mac_bare:
                            # Merge enrichment fields from inventory when Redis
                            # cache lacks them (vendor/model/software/ofdm come
                            # from sysDescr refresh, stored in MySQL only).
                            if (not modem.get('vendor') or not modem.get('model')
                                    or not modem.get('software_version')
                                    or modem.get('ofdm_enabled') is None
                                    or modem.get('ofdma_enabled') is None):
                                try:
                                    inv = PyPNMClient().get_inventory_modem_by_mac(mac_bare)
                                    inv_m = inv.get('modem') if isinstance(inv, dict) else None
                                    if inv_m:
                                        for field in ('vendor', 'model', 'software_version',
                                                      'docsis_version', 'ofdm_enabled', 'ofdma_enabled',
                                                      'ofdma_ifindex', 'fiber_node', 'cable_mac'):
                                            if inv_m.get(field) and not modem.get(field):
                                                modem[field] = inv_m[field]
                                except Exception:
                                    pass
                            return jsonify({
                                "status": "success",
                                "modem": modem
                            })
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis search error: {e}")

    # Fallback to PyPNM inventory snapshot (pass bare hex so DB REPLACE works)
    try:
        modem_resp = PyPNMClient().get_inventory_modem_by_mac(mac_bare)
        modem = modem_resp.get('modem')
        if modem:
            return jsonify({
                "status": "success",
                "modem": modem,
                "source": modem_resp.get('source') or "pypnm-inventory",
            })
    except Exception as e:
        logging.getLogger(__name__).warning(f"PyPNM modem inventory fallback error: {e}")

    # Final fallback: topology MySQL snapshot (for topology-origin modems that
    # are not present in live CMTS Redis cache/inventory).
    try:
        topo_resp = PyPNMClient().get_topology_modem_by_mac(mac_bare)
        topo_modem = topo_resp.get('modem') if isinstance(topo_resp, dict) else None
        if topo_modem:
            mac_norm = topo_modem.get('mac') or mac_address
            modem = {
                "mac_address": mac_norm,
                "name": mac_norm,
                "ip_address": "",
                "status": "topology-only",
                "vendor": "Unknown",
                "model": "N/A",
                "docsis_version": "Unknown",
                "cmts": topo_modem.get('cmts') or "",
                "cmts_ip": topo_modem.get('cmts_ip') or "",
                "fiber_node": topo_modem.get('fibernode') or "",
                "customer_id": topo_modem.get('customer_id') or "",
                "postalcode": topo_modem.get('postalcode') or "",
                "house_number": topo_modem.get('house_number') or "",
                "house_number_extension": topo_modem.get('house_number_extension') or "",
                "topology_path": topo_modem.get('hierarchy_path') or "",
                "topology_link_id": topo_modem.get('topology_link_id') or "",
                "linked_node_id": topo_modem.get('linked_node_id') or "",
                "lat": topo_modem.get('lat'),
                "lon": topo_modem.get('lon'),
                "linked_node_type": topo_modem.get('linked_node_type') or "",
                "link_match": bool(topo_modem.get('link_match')),
                "source": "topology-mysql",
            }
            return jsonify({
                "status": "success",
                "modem": modem,
                "source": "topology-mysql",
            })
    except Exception as e:
        logging.getLogger(__name__).warning(f"PyPNM topology modem fallback error: {e}")
    
    return jsonify({
        "status": "error",
        "message": "Modem not found in cache/inventory/topology snapshot."
    }), 404


# ============== CMTS Endpoints ==============

@api_bp.route('/cmts', methods=['GET'])
def get_cmts_list():
    """
    Get list of CMTS devices from appdb.
    
    Query params:
        - vendor: Filter by vendor (Arris, Casa, Cisco)
        - type: Filter by type (E6000, C100G, cBR-8)
        - search: Search by hostname, alias, or IP
        - refresh: Force cache refresh (true/false)
    """
    vendor = request.args.get('vendor')
    cmts_type = request.args.get('type')
    search = request.args.get('search')
    refresh = request.args.get('refresh', '').lower() == 'true'
    
    # Get CMTS data (from cache or API)
    if vendor:
        cmts_list = CMTSProvider.get_cmts_by_vendor(vendor)
    elif cmts_type:
        cmts_list = CMTSProvider.get_cmts_by_type(cmts_type)
    elif search:
        cmts_list = CMTSProvider.search_cmts(search)
    else:
        cmts_list = CMTSProvider.get_all_cmts(force_refresh=refresh)
    
    return jsonify({
        "status": "success",
        "count": len(cmts_list),
        "cmts_list": cmts_list,
        "cache_info": CMTSProvider.get_cache_info()
    })


@api_bp.route('/cmts/summary', methods=['GET'])
def get_cmts_summary():
    """Get summary of CMTS systems by vendor and type."""
    return jsonify({
        "status": "success",
        "total": CMTSProvider.get_cmts_count(),
        "by_vendor": CMTSProvider.get_vendors_summary(),
        "by_type": CMTSProvider.get_types_summary(),
        "cache_info": CMTSProvider.get_cache_info()
    })


@api_bp.route('/cmts/<hostname>', methods=['GET'])
def get_cmts_by_hostname(hostname):
    """Get a specific CMTS by hostname."""
    cmts = CMTSProvider.get_cmts_by_hostname(hostname)
    
    if cmts:
        return jsonify({
            "status": "success",
            "cmts": cmts
        })
    else:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{hostname}' not found"
        }), 404


@api_bp.route('/cmts/<cmts_name>/interfaces', methods=['GET'])
def get_cmts_interfaces(cmts_name):
    """Get interfaces for a specific CMTS (placeholder - needs PyPNM integration)."""
    cmts = CMTSProvider.get_cmts_by_hostname(cmts_name)
    
    if cmts:
        # TODO: Integrate with PyPNM to get real interface data
        return jsonify({
            "status": "success",
            "cmts": cmts_name,
            "interfaces": [],
            "message": "Interface discovery requires PyPNM agent connection"
        })
    
    return jsonify({
        "status": "error",
        "message": f"CMTS '{cmts_name}' not found"
    }), 404


@api_bp.route('/cmts/<cmts_name>/modems', methods=['GET'])
def get_cmts_modems(cmts_name):
    """Get modems from a specific CMTS via PyPNM API -> Agent -> SNMP."""
    logger = logging.getLogger(__name__)
    
    # Get CMTS info from provider
    cmts = CMTSProvider.get_cmts_by_hostname(cmts_name)
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found"
        }), 404
    
    # Get query parameters
    community = request.args.get('community', get_cmts_community())
    limit = int(request.args.get('limit', 10000))
    enrich = request.args.get('enrich', 'true').lower() == 'true'  # Enable enrichment by default
    modem_community = request.args.get('modem_community') or get_default_community()
    if not request.args.get('modem_community'):
        logger.warning(f"modem_community not provided for {cmts_name} — using configured default '{modem_community}'")
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        # CMTSProvider returns 'IPAddress' from appdb format
        cmts_ip = cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address')
        
        if not cmts_ip:
            logger.error(f"CMTS {cmts_name} has no IP address: {cmts}")
            return jsonify({
                "status": "error",
                "message": f"CMTS '{cmts_name}' has no IP address configured"
            }), 500
        
        # Check Redis cache first (unless force_refresh)
        if REDIS_AVAILABLE and redis_client and not force_refresh:
            try:
                cache_key = f"modems:{cmts_name}"
                cached = redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    cached_modems = filter_ignored_modems(data.get('modems', []))
                    cached_count = len(cached_modems)
                    cached_requested_limit = int(data.get('requested_limit') or 0)
                    cache_limit_mismatch = False
                    cache_needs_enrich = False

                    # Ignore cache entries built with a smaller request limit.
                    if cached_requested_limit and cached_requested_limit < limit:
                        cache_limit_mismatch = True
                        logger.info(
                            f"Using partial Redis cache for {cmts_name}: cached_limit={cached_requested_limit} < requested_limit={limit}"
                        )
                    elif not cached_requested_limit and cached_count < limit:
                        # Legacy entries have no requested_limit metadata.
                        cache_limit_mismatch = True
                        logger.info(
                            f"Using partial legacy Redis cache for {cmts_name}: cached_count={cached_count} < requested_limit={limit}"
                        )

                    # Fill missing CMTS fields on cached rows.
                    for m in cached_modems:
                        if not m.get('cmts_ip'):
                            m['cmts_ip'] = cmts_ip
                        if not m.get('cmts_community'):
                            m['cmts_community'] = community
                    _augment_modems_with_topology_fields(cached_modems, cmts_name=cmts_name)
                    cache_is_enriched = _modems_are_enriched(cached_modems)
                    if not cache_is_enriched and enrich:
                        cache_needs_enrich = True
                        logger.info(
                            f"Returning non-enriched Redis cache for {cmts_name} immediately; live enrichment may continue in background."
                        )

                    # Guard against stale/partial empty cache loops.
                    # If Redis has 0 rows while marked partial/non-enriched, returning it causes
                    # the frontend to spin forever with empty selector state. Fall through to live
                    # CMTS query so cache can be repopulated.
                    if cached_count == 0 and (cache_limit_mismatch or cache_needs_enrich):
                        logger.warning(
                            f"Bypassing empty partial Redis cache for {cmts_name} "
                            f"(cached_limit={cached_requested_limit}, requested_limit={limit}, "
                            f"needs_enrich={cache_needs_enrich})"
                        )
                        raise RuntimeError("stale-empty-partial-cache")

                    logger.info(
                        f"Returning {len(cached_modems)} modems from Redis cache for {cmts_name} "
                        f"(enriched={cache_is_enriched}, partial={cache_limit_mismatch or cache_needs_enrich})"
                    )
                    return jsonify({
                        "status": "success",
                        "cmts": cmts_name,
                        "cmts_hostname": cmts_name,
                        "cmts_ip": cmts_ip,
                        "agent_id": "cached",
                        "modems": cached_modems,
                        "count": len(cached_modems),
                        "enriched": cache_is_enriched,
                        "cached": True,
                        "enriching": bool(cache_needs_enrich),
                        "partial": bool(cache_limit_mismatch or cache_needs_enrich),
                        "cached_requested_limit": cached_requested_limit,
                        "requested_limit": limit,
                    })
            except Exception as e:
                logger.warning(f"Redis cache read error: {e}")

        # Reuse fresh poller inventory before starting another enrichment cycle.
        if enrich and not force_refresh:
            try:
                client = PyPNMClient()
                inventory_resp = client.get_inventory_modems(
                    cmts=cmts_name,
                    limit=limit,
                )
                inventory_modems = inventory_resp.get('modems') or []
                inventory_modems = filter_ignored_modems(inventory_modems)
                if inventory_modems and _inventory_snapshot_is_fresh(inventory_modems):
                    inventory_enriched = _modems_are_enriched(inventory_modems)
                    if not inventory_enriched:
                        logger.info(
                            f"Inventory for {cmts_name} is fresh but lacks vendor/firmware — falling through to live SNMP enrichment."
                        )
                    else:
                        for m in inventory_modems:
                            m['cmts'] = cmts_name
                            m['cmts_ip'] = cmts_ip
                            m['cmts_community'] = community
                        _augment_modems_with_topology_fields(inventory_modems, cmts_name=cmts_name)
                        _backfill_redis_from_inventory(inventory_modems, requested_limit=limit)
                        logger.info(
                            f"Returning {len(inventory_modems)} modems for {cmts_name} from fresh poller inventory instead of re-enriching"
                        )
                        return jsonify({
                            "status": "success",
                            "cmts": cmts_name,
                            "cmts_hostname": cmts_name,
                            "cmts_ip": cmts_ip,
                            "agent_id": "inventory",
                            "modems": inventory_modems,
                            "count": len(inventory_modems),
                            "enriched": True,
                            "cached": True,
                            "enriching": False,
                            "source": inventory_resp.get('source') or "pypnm-inventory",
                        })
            except Exception as e:
                logger.warning(f"Poller inventory reuse skipped for {cmts_name}: {e}")
        
        # Query PyPNM for modem data and optional enrichment.
        client = PyPNMClient()
        result = client.get_cmts_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=limit,
            enrich=enrich,
            modem_community=modem_community
        )
        
        if result.get('success'):
            modems = filter_ignored_modems(result.get('modems', []))
            logger.info(f"Retrieved {len(modems)} modems from {cmts_name} via PyPNM API/agent")

            # Stamp CMTS fields onto every modem record.
            for m in modems:
                m['cmts'] = cmts_name
                m['cmts_ip'] = cmts_ip
                m['cmts_community'] = community

            _augment_modems_with_topology_fields(modems, cmts_name=cmts_name)

            is_enriched = result.get('enriched', False)
            is_enriching = result.get('enriching', False)

            # Cache successful modem data immediately so subsequent CMTS searches
            # can reuse inventory even while enrichment is still running.
            if REDIS_AVAILABLE and redis_client:
                try:
                    cache_payload = {
                        "cmts": cmts_name,
                        "requested_limit": limit,
                        "modems": modems,
                        "timestamp": result.get('timestamp'),
                        "enriched": is_enriched,
                        "enriching": is_enriching,
                        "source": "pypnm-live",
                    }
                    redis_client.setex(f"modems:{cmts_name}", REDIS_TTL, json.dumps(cache_payload))
                    # Alias by CMTS IP so lookups by either hostname or IP hit cache.
                    if cmts_ip and cmts_ip != cmts_name:
                        redis_client.setex(f"modems:{cmts_ip}", REDIS_TTL, json.dumps(cache_payload))
                    logger.info(
                        f"Cached {len(modems)} modems for {cmts_name} (enriched={is_enriched}, enriching={is_enriching}, TTL={REDIS_TTL}s)"
                    )
                except Exception as e:
                    logger.warning(f"Redis cache error: {e}")
            
            return jsonify({
                "status": "success",
                "cmts": cmts_name,
                "cmts_hostname": cmts_name,
                "cmts_ip": cmts_ip,
                "agent_id": result.get('agent_id', 'agent'),
                "modems": modems,
                "count": len(modems),
                "enriched": result.get('enriched', False),
                "cached": result.get('cached', False),
                "enriching": result.get('enriching', False),
                # PyPNM stores it as 'enrich_progress' — pass through under both names for compat
                "enrichment_progress": result.get('enrichment_progress') or result.get('enrich_progress'),
            })
        else:
            error_msg = result.get('error', 'Unknown error from PyPNM API')
            logger.error(f"PyPNM API error for {cmts_name}: {error_msg}")
            return jsonify({
                "status": "error",
                "message": error_msg
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting modems from {cmts_name}: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============== System Information Endpoints ==============

@api_bp.route('/modem/<mac_address>/system-info', methods=['POST'])
def get_system_info(mac_address):
    """Get system information for a modem.

    NOTE: Disabled — /docs/pnm/ds/status/getChannelStatus does not exist in PyPNM.
    Endpoint returns 501 until a /pnm equivalent is implemented.
    """
    return jsonify({
        "status": "error",
        "message": "system-info endpoint not yet implemented (backing route /docs/pnm/ds/status/getChannelStatus removed)"
    }), 501


# ============== Removed Endpoints ==============
# The following endpoints were removed (Phase 3 migration).
# Use /api/pypnm/* endpoints instead, which route through PyPNM API.
# ============================================================


# ============== Health Check ==============

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "PyPNM Web GUI",
        "use_mock_data": current_app.config.get('USE_MOCK_DATA', True)
    })


@api_bp.route('/pypnm/health', methods=['GET'])
def pypnm_health_check():
    """Check PyPNM API health by testing connection to pypnm-api service."""
    import requests
    pypnm_api_url = os.environ.get('PYPNM_BASE_URL', os.environ.get('PYPNM_API_URL', 'http://localhost:8000'))
    
    try:
        # Use /docs endpoint as health check (root returns 404)
        response = requests.get(f"{pypnm_api_url}/docs", timeout=3)
        if response.status_code == 200:
            return jsonify({
                "status": "ok",
                "pypnm_healthy": True,
                "pypnm_api_url": pypnm_api_url
            })
        else:
            return jsonify({
                "status": "error",
                "pypnm_healthy": False,
                "message": f"PyPNM API returned status {response.status_code}"
            })
    except requests.exceptions.RequestException as e:
        return jsonify({
            "status": "error",
            "pypnm_healthy": False,
            "message": str(e)
        })


# ============== Cache Management ==============

@api_bp.route('/cmts/<cmts_name>/cache/clear', methods=['POST'])
def clear_cmts_modem_cache(cmts_name):
    """Clear all cached modem data for a specific CMTS (Redis + API in-memory)."""
    logger = logging.getLogger(__name__)
    cleared = []

    # 1. Clear Redis cache for this CMTS — delete hostname key AND the IP-alias key
    #    that is written alongside it in get_cmts_modems / _backfill_redis_from_inventory.
    if REDIS_AVAILABLE and redis_client:
        try:
            keys_to_delete = [f"modems:{cmts_name}"]
            # Resolve the CMTS IP so we can also purge the IP-alias key.
            cmts_info = CMTSProvider.get_cmts_by_hostname(cmts_name)
            cmts_ip = None
            if cmts_info:
                cmts_ip = cmts_info.get('IPAddress') or cmts_info.get('ip') or cmts_info.get('ip_address')
            if cmts_ip and cmts_ip != cmts_name:
                keys_to_delete.append(f"modems:{cmts_ip}")
            deleted = redis_client.delete(*keys_to_delete)
            if deleted:
                cleared.append(f"Redis keys {keys_to_delete} ({deleted} deleted)")
        except Exception as e:
            logger.warning(f"Redis cache clear error: {e}")

    # 2. Clear PyPNM API in-memory enrichment cache
    try:
        import requests
        pypnm_url = os.environ.get('PYPNM_BASE_URL', os.environ.get('PYPNM_API_URL', 'http://localhost:8000'))
        resp = requests.post(f"{pypnm_url}/cache/clear", timeout=5)
        if resp.status_code == 200:
            cleared.append("API enrichment cache")
    except Exception as e:
        logger.warning(f"API cache clear error: {e}")

    msg = f"Cleared cache for {cmts_name}: {', '.join(cleared)}" if cleared else f"No cache found for {cmts_name}"
    logger.info(msg)
    return jsonify({"status": "success", "message": msg})


@api_bp.route('/cmts/<cmts_name>/enrich/delta', methods=['POST'])
def enqueue_delta_enrichment(cmts_name):
    """Queue refresh only for modems missing enrichment fields in current CMTS cache."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503

    payload = request.get_json(silent=True) or {}
    max_batch = max(1, min(int(payload.get('max_batch') or 200), 1000))

    cached = redis_client.get(f"modems:{cmts_name}")
    if not cached:
        return jsonify({"status": "error", "message": f"No cached modems for {cmts_name}"}), 404

    try:
        data = json.loads(cached)
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Invalid cache payload: {exc}"}), 500

    modems = data.get('modems') or []
    if not modems:
        return jsonify({
            "status": "success",
            "cmts": cmts_name,
            "total_modems": 0,
            "missing_count": 0,
            "enqueued": 0,
            "already_queued": 0,
            "max_batch": max_batch,
        })

    missing = [m for m in modems if _modem_missing_enrichment(m)]
    enqueued = []

    pypnm_base = (os.environ.get("PYPNM_API_URL") or os.environ.get("PYPNM_BASE_URL") or "http://172.17.0.1:8081").rstrip("/")
    for modem in missing:
        if len(enqueued) >= max_batch:
            break
        mac = str(modem.get('mac_address') or '').strip()
        if not mac:
            continue
        try:
            import requests as _req
            _req.post(
                f"{pypnm_base}/api/admin/modem-refresh",
                json={"mac": mac, "cmts": cmts_name, "requested_by": "delta-enrich"},
                timeout=5,
                verify=False,
            )
            enqueued.append(mac)
        except Exception:
            pass

    return jsonify({
        "status": "success",
        "cmts": cmts_name,
        "total_modems": len(modems),
        "missing_count": len(missing),
        "enqueued": len(enqueued),
        "max_batch": max_batch,
        "sample_enqueued_macs": enqueued[:20],
    })


@api_bp.route('/cache/flush', methods=['POST'])
def flush_cache():
    """Flush all Redis cache."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        redis_client.flushdb()
        return jsonify({"status": "success", "message": "Cache flushed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/flush/modems', methods=['POST'])
def flush_modem_cache():
    """Flush modem cache (modems:*)."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        keys = redis_client.keys("modems:*")
        if keys:
            redis_client.delete(*keys)
            count = len(keys)
        else:
            count = 0
        return jsonify({"status": "success", "message": f"Flushed {count} modem cache keys"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/flush/cmts', methods=['POST'])
def flush_cmts_cache():
    """Flush CMTS cache (cmts:*)."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        keys = redis_client.keys("cmts:*")
        if keys:
            redis_client.delete(*keys)
            count = len(keys)
        else:
            count = 0
        return jsonify({"status": "success", "message": f"Flushed {count} CMTS cache keys"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/stats', methods=['GET'])
def cache_stats():
    """Get Redis cache statistics."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        info = redis_client.info()
        stats = {
            "status": "ok",
            "keys": redis_client.dbsize(),
            "memory_used": info.get('used_memory_human', 'N/A'),
            "memory_peak": info.get('used_memory_peak_human', 'N/A'),
            "hits": info.get('keyspace_hits', 0),
            "misses": info.get('keyspace_misses', 0),
            "hit_rate": f"{info.get('keyspace_hits', 0) / max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 1), 1) * 100:.1f}%"
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/agent/status', methods=['GET'])
def agent_status():
    """Get WebSocket agent connection status from PyPNM API."""
    try:
        import requests as _requests
        from app.core.config import Config
        base_url = Config.PYPNM_API_URL.rstrip('/')
        resp = _requests.get(f"{base_url}/api/agents", timeout=5)
        response = resp.json() if resp.status_code == 200 else None
        
        # Check if we got a valid response
        if response and isinstance(response, dict):
            agents = response.get('agents', [])
            # Normalize: add status field based on is_alive so frontend filter works
            for a in agents:
                if 'status' not in a:
                    a['status'] = 'connected' if a.get('is_alive') else 'disconnected'
            connected_count = len([a for a in agents if a.get('status') == 'connected'])
            return jsonify({
                "status": "ok",
                "agents": agents,
                "count": connected_count
            })
        else:
            # PyPNM API doesn't have agents endpoint or returned error
            return jsonify({
                "status": "ok",
                "agents": [],
                "count": 0
            })
    except Exception as e:
        logger.warning(f"Failed to get agent status: {e}")
        return jsonify({
            "status": "ok",
            "agents": [],
            "count": 0
        })


# ============== Agent-Based CMTS Modem Lookup ==============

