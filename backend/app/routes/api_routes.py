# PyPNM Web GUI - API Routes

import os
import re
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from flask import jsonify, request, current_app, session
from . import api_bp
from app.core.cmts_provider import CMTSProvider
from app.core.pypnm_client import PyPNMClient
from app.core.modem_filters import filter_ignored_modems

# ── Viewer role guard — block mutating requests ─────────────────────────────
@api_bp.before_request
def _viewer_readonly():
    if session.get('role') == 'viewer' and request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return jsonify({'status': 'error', 'message': 'Viewer role is read-only'}), 403

# ── Background modem-load job store ─────────────────────────────────────────
# job_id -> {status, modems, count, enriched, capability_enriched, enriching,
#             enrichment_progress, error, cmts_ip, cmts_hostname, agent_id, started_at}
_modem_jobs: dict = {}
_modem_jobs_lock = threading.Lock()


def _run_modem_job(
    job_id: str,
    cmts_ip: str,
    cmts_name: str,
    community: str,
    limit: int,
    enrich: bool,
):
    """Run in a background thread. Calls PyPNM and updates the job store."""
    _log = logging.getLogger(__name__)
    try:
        client = PyPNMClient()
        result = client.get_cmts_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=limit,
            enrich=enrich,
        )
        if result.get('success'):
            modems = result.get('modems', [])
            for m in modems:
                m['cmts_ip'] = cmts_ip
                if community is not None:
                    m['cmts_community'] = community
                else:
                    m.pop('cmts_community', None)
            with _modem_jobs_lock:
                _modem_jobs[job_id].update({
                    'status': 'done',
                    'modems': modems,
                    'count': len(modems),
                    'enriched': result.get('enriched', False),
                    'capability_enriched': result.get('capability_enriched') is True,
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


MAX_CM_MODEM_LIMIT = 50000
_INVENTORY_METADATA_FIELDS = (
    'complete', 'truncated', 'requested_limit', 'row_count', 'snapshot_id',
    'capability_enriched', 'collected_at', 'revision_at', 'source',
    'inventory_source', 'critical_oid_errors',
)


def _bounded_modem_limit(value, default: int = MAX_CM_MODEM_LIMIT) -> int:
    try:
        return max(1, min(int(value), MAX_CM_MODEM_LIMIT))
    except (TypeError, ValueError):
        return default


def _cm_modem_limit_default() -> int:
    value = current_app.config.get(
        'CM_MODEM_LIMIT', os.environ.get('CM_MODEM_LIMIT', MAX_CM_MODEM_LIMIT)
    )
    return _bounded_modem_limit(value)


def _inventory_freshness_seconds() -> int:
    value = current_app.config.get(
        'INVENTORY_FRESHNESS_SECONDS',
        os.environ.get('INVENTORY_FRESHNESS_SECONDS', 172800),
    )
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 172800




# Default TFTP server (same as pypnm_routes.py)
DEFAULT_TFTP_IP = os.environ.get('TFTP_IPV4', '127.0.0.1')

def _non_empty_community(value):
    """Return a configured community while preserving non-empty values exactly."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _first_community(*values):
    for value in values:
        resolved = _non_empty_community(value)
        if resolved is not None:
            return resolved
    return None


def get_cmts_community():
    """Get the configured fallback SNMP read community for CMTS operations."""
    return _first_community(
        os.environ.get('CMTS_COMMUNITY'),
        os.environ.get('CMTS_SNMP_COMMUNITY'),
    )


def _pypnm_error_status(result: dict | None) -> int:
    """Map sanitized PyPNM failures without hiding safe application errors."""
    result = result if isinstance(result, dict) else {}
    try:
        upstream_status = int(result.get('upstream_http_status'))
    except (TypeError, ValueError):
        upstream_status = None

    if upstream_status is not None:
        if 400 <= upstream_status < 500 or upstream_status in (503, 504):
            return upstream_status
        if upstream_status >= 500:
            return 502

    failure_status = str(result.get('failure_status') or '').strip().lower()
    if failure_status == 'timeout':
        return 504
    if failure_status in ('service_unavailable', 'agent_unavailable'):
        return 503
    return 502


def _pypnm_error_response(result: dict | None, fallback: str):
    """Return a route-owned safe message while retaining routing metadata."""
    result = result if isinstance(result, dict) else {}
    body = {'status': 'error', 'message': fallback}
    if result.get('failure_status'):
        body['failure_status'] = result['failure_status']
    if result.get('upstream_http_status') is not None:
        body['upstream_http_status'] = result['upstream_http_status']
    return jsonify(body), _pypnm_error_status(result)


def _pypnm_exception_result(exc: Exception) -> dict:
    logger.warning("PyPNM client call raised %s", type(exc).__name__)
    return {
        'status': 'error',
        'success': False,
        'failure_status': 'service_unavailable',
        'upstream_http_status': None,
        'message': 'PyPNM API unavailable',
    }


def _cmts_inventory_refs(cmts: dict, requested_ref: str = '') -> list[str]:
    """Return distinct authoritative inventory keys in hostname/IP order."""
    values = (
        cmts.get('HostName'),
        cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address'),
    )
    refs = []
    seen = set()
    for value in values:
        ref = str(value or '').strip()
        normalized = ref.lower()
        if ref and normalized not in seen:
            seen.add(normalized)
            refs.append(ref)
    if not refs:
        requested = str(requested_ref or '').strip()
        if requested:
            refs.append(requested)
    return refs


def _inventory_lookup_absent(result: dict | None, record_key: str) -> bool:
    """Recognize only authoritative success-empty or explicit not-found contracts."""
    if not isinstance(result, dict):
        return False
    if result.get('status') == 'success':
        return not result.get(record_key)
    if result.get('upstream_http_status') == 404:
        return True
    message = str(result.get('message') or '').strip().lower().rstrip('.')
    return result.get('status') == 'error' and message == 'modem not found'


def _parse_inventory_timestamp(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
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


def _inventory_stale(metadata: dict, modems: list[dict]) -> bool | None:
    collected = _parse_inventory_timestamp(metadata.get('collected_at'))
    if collected is None:
        timestamps = [
            _parse_inventory_timestamp(m.get('updated_at') or m.get('last_seen_at'))
            for m in modems if isinstance(m, dict)
        ]
        timestamps = [value for value in timestamps if value is not None]
        collected = min(timestamps) if timestamps else None
    if collected is None:
        return None
    age_seconds = (datetime.now(timezone.utc) - collected).total_seconds()
    return age_seconds > _inventory_freshness_seconds()

def _snapshot_metadata(metadata: dict, modems: list[dict]) -> dict:
    """Preserve authoritative snapshot axes without deriving completeness from row count."""
    source = metadata.get('source') or metadata.get('inventory_source')
    inventory_source = metadata.get('inventory_source') or metadata.get('source')
    out = {
        key: metadata.get(key)
        for key in _INVENTORY_METADATA_FIELDS
        if key in metadata
    }
    out['row_count'] = metadata.get('row_count', len(modems))
    out['source'] = source or 'pypnm-inventory'
    out['inventory_source'] = inventory_source or out['source']
    out['critical_oid_errors'] = metadata.get('critical_oid_errors') or {}
    out['capability_enriched'] = metadata.get('capability_enriched') is True
    out['inventory_complete'] = (
        metadata.get('complete') is True and metadata.get('truncated') is not True
    )
    out['inventory_stale'] = _inventory_stale(metadata, modems)
    # Unknown legacy completeness is not authoritative; present it as partial
    # rather than implying a complete inventory from row count alone.
    out['partial'] = not out['inventory_complete']
    return out

# Values that mean an identity field has not actually been enriched.
_IDENTITY_PLACEHOLDERS = {'', 'unknown', 'n/a', 'na', 'none', 'null', '-', '—'}


def _identity_value_missing(value) -> bool:
    return str(value or '').strip().lower() in _IDENTITY_PLACEHOLDERS


def _docsis_version_rank(value) -> int:
    """Return a monotonic capability rank; unknown values rank as zero."""
    text = str(value or '').strip().lower()
    for marker, rank in (
        ('4.0', 40),
        ('3.1', 31),
        ('3.0', 30),
        ('2.0', 20),
        ('1.1', 11),
        ('1.0', 10),
    ):
        if marker in text:
            return rank
    return 0


def _positive_capability(value) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value > 0
    return str(value or '').strip().lower() in ('true', 'yes', 'on', 'active', 'available')


def _negative_capability(value) -> bool:
    if value is False:
        return True
    if value is True:
        return False
    if isinstance(value, (int, float)):
        return value <= 0
    return str(value or '').strip().lower() in (
        'false', 'no', 'off', 'inactive', 'unavailable', '0'
    )


def _positive_index(value) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _positive_channels(value) -> bool:
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    if isinstance(value, dict):
        if _positive_index(value.get('count')):
            return True
        return any(
            isinstance(value.get(key), list) and bool(value.get(key))
            for key in ('channels', 'entries', 'results')
        )
    return False


def _has_positive_ofdma_evidence(*sources: dict | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _positive_capability(source.get('ofdma_enabled')):
            return True
        if any(_positive_index(source.get(key)) for key in (
            'ofdma_ifindex', 'ofdma_rf_port_ifindex', 'upstream_ofdma_ifindex'
        )):
            return True
        if any('ofdma' in str(source.get(key) or '').lower() for key in (
            'upstream_interface', 'ofdma_interface', 'interface_name'
        )):
            return True
        if any(_positive_index(source.get(key)) for key in (
            'ofdma_count', 'ofdma_channel_count', 'upstream_ofdma_count'
        )):
            return True
        if any(_positive_channels(source.get(key)) for key in (
            'ofdma_channels', 'ofdma', 'upstream_ofdma_channels'
        )):
            return True
    return False


def _has_positive_ofdm_evidence(*sources: dict | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        if _positive_capability(source.get('ofdm_enabled')):
            return True
        if any(_positive_index(source.get(key)) for key in (
            'ofdm_ifindex', 'ofdm_rf_port_ifindex', 'downstream_ofdm_ifindex'
        )):
            return True
        if any(_positive_index(source.get(key)) for key in (
            'ofdm_count', 'ofdm_channel_count', 'downstream_ofdm_count'
        )):
            return True
        if any(_positive_channels(source.get(key)) for key in (
            'ofdm_channels', 'ofdm', 'downstream_ofdm_channels'
        )):
            return True
    return False


def _modem_is_online(*sources: dict | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        status = str(source.get('status') or '').strip().lower()
        if status in ('operational', 'online', 'registrationcomplete', 'ipcomplete'):
            return True
        try:
            if int(source.get('status_code')) in (6, 8):
                return True
        except (TypeError, ValueError):
            pass
    return False


def _normalize_modem_capability(modem: dict, *sources: dict | None) -> dict:
    """Merge capability evidence monotonically and enforce online invariants."""
    evidence = (modem, *sources)
    ofdma_positive = _has_positive_ofdma_evidence(*evidence)
    ofdm_positive = _has_positive_ofdm_evidence(*evidence)
    if ofdma_positive:
        modem['ofdma_enabled'] = True
    if ofdm_positive:
        modem['ofdm_enabled'] = True

    rank = max((_docsis_version_rank(row.get('docsis_version'))
                for row in evidence if isinstance(row, dict)), default=0)
    if ofdm_positive or ofdma_positive:
        rank = max(rank, 31)
    elif rank == 0 and _modem_is_online(*evidence):
        rank = 30

    labels = {
        10: 'DOCSIS 1.0', 11: 'DOCSIS 1.1', 20: 'DOCSIS 2.0',
        30: 'DOCSIS 3.0', 31: 'DOCSIS 3.1', 40: 'DOCSIS 4.0',
    }
    if rank in labels:
        modem['docsis_version'] = labels[rank]
    return modem


def _topology_fields_by_mac(mac_addresses: list[str]) -> dict[str, dict]:
    """Load topology identities through PyPNM, keyed by bare uppercase MAC."""
    if not mac_addresses:
        return {}

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    wanted = sorted({m for m in (_bare(v) for v in mac_addresses) if m})
    if not wanted:
        return {}

    out: dict[str, dict] = {}
    snapshot_date = None
    try:
        client = PyPNMClient()
    except Exception as exc:
        logger.warning("Topology MAC lookup client initialization failed: %s", exc)
        return out
    for offset in range(0, len(wanted), 5000):
        chunk = wanted[offset:offset + 5000]
        try:
            response = client.get_topology_modems_by_macs(
                chunk,
                date=snapshot_date,
                request_timeout=30,
            )
        except Exception as exc:
            logger.warning("Topology MAC lookup via PyPNM skipped: %s", exc)
            continue
        if not isinstance(response, dict):
            logger.warning("Topology MAC lookup via PyPNM returned an invalid response")
            continue
        if response.get("status") != "success":
            logger.warning(
                "Topology MAC lookup via PyPNM returned an error: %s",
                response.get("message") or response.get("detail") or "unknown error",
            )
            continue
        snapshot_date = response.get("snapshot_date") or snapshot_date
        for row in response.get("modems") or []:
            if not isinstance(row, dict):
                continue
            mac_norm = _bare(row.get("mac"))
            if mac_norm:
                out[mac_norm] = row
    return out


def _inventory_fields_by_mac(mac_addresses: list[str], cmts_name: str = "") -> dict[str, dict]:
    """Bulk lookup of inventory fields, chunked to the PyPNM API limit."""
    if not mac_addresses:
        return {}

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    wanted = sorted({m for m in (_bare(v) for v in mac_addresses) if m})
    if not wanted:
        return {}

    chunk_size = 5000
    chunk_count = (len(wanted) + chunk_size - 1) // chunk_size
    out: dict[str, dict] = {}
    try:
        client = PyPNMClient()
    except Exception as exc:
        logger.warning("Inventory MAC lookup via PyPNM API unavailable: %s", exc)
        return out
    for offset in range(0, len(wanted), chunk_size):
        chunk = wanted[offset:offset + chunk_size]
        chunk_number = (offset // chunk_size) + 1
        try:
            inv_resp = client.get_inventory_modems_bulk(chunk)
        except Exception as exc:
            logger.warning(
                "Inventory MAC lookup chunk %d/%d via PyPNM API skipped: %s",
                chunk_number,
                chunk_count,
                exc,
            )
            continue
        if inv_resp.get('status') != 'success':
            logger.warning(
                "Inventory MAC lookup chunk %d/%d via PyPNM API returned an error",
                chunk_number,
                chunk_count,
            )
            continue
        for m in (inv_resp.get('modems') or []):
            mac_norm = _bare(m.get('mac_address') or m.get('mac') or '')
            if mac_norm and mac_norm in wanted:
                out[mac_norm] = {
                    'fiber_node': m.get('fiber_node') or '',
                    'cable_mac': m.get('cable_mac') or '',
                    'ofdm_enabled': m.get('ofdm_enabled'),
                    'ofdma_enabled': m.get('ofdma_enabled'),
                    'ofdm_ifindex': m.get('ofdm_ifindex'),
                    'ofdma_ifindex': m.get('ofdma_ifindex'),
                    'ofdma_rf_port_ifindex': m.get('ofdma_rf_port_ifindex'),
                    'upstream_interface': m.get('upstream_interface') or '',
                    'ofdm_channels': m.get('ofdm_channels'),
                    'ofdma_channels': m.get('ofdma_channels'),
                    'ofdm': m.get('ofdm'),
                    'ofdma': m.get('ofdma'),
                    'ofdm_channel_count': m.get('ofdm_channel_count'),
                    'ofdma_channel_count': m.get('ofdma_channel_count'),
                    'docsis_version': m.get('docsis_version') or '',
                    'vendor': m.get('vendor') or '',
                    'model': m.get('model') or '',
                }
    return out


def _augment_modems_with_topology_fields(modems: list[dict], cmts_name: str = "") -> list[dict]:
    """In-place best-effort merge of topology and authoritative inventory fields."""
    if not modems:
        return modems

    def _bare(mac: str) -> str:
        return re.sub(r'[^A-F0-9]', '', str(mac or '').upper())

    topo = _topology_fields_by_mac([m.get("mac_address") for m in modems if isinstance(m, dict)])

    # Backfill fiber_node, cable_mac, capability, and identity fields from
    # modem_inventory_current when missing or when cache data represents a
    # lower capability. Modem capability cannot downgrade in place.
    inv: dict[str, dict] = {}
    need_inv = [m for m in modems if isinstance(m, dict) and (
        not m.get("fiber_node")
        or _identity_value_missing(m.get("model"))
        or m.get("ofdm_enabled") is None
        or m.get("ofdma_enabled") is None
        or _docsis_version_rank(m.get("docsis_version")) < 31
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
            if not m.get("topology_fiber_node") and t.get("fibernode"):
                m["topology_fiber_node"] = t["fibernode"]
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
            if _positive_capability(iv.get("ofdm_enabled")):
                m["ofdm_enabled"] = True
            elif m.get("ofdm_enabled") is None and _negative_capability(iv.get("ofdm_enabled")):
                m["ofdm_enabled"] = False
            if _positive_capability(iv.get("ofdma_enabled")):
                m["ofdma_enabled"] = True
            elif m.get("ofdma_enabled") is None and _negative_capability(iv.get("ofdma_enabled")):
                m["ofdma_enabled"] = False
            for field in ('ofdm_ifindex', 'ofdma_ifindex', 'ofdma_rf_port_ifindex'):
                if _positive_index(iv.get(field)) and not _positive_index(m.get(field)):
                    m[field] = iv[field]
            for field in ('ofdm_channels', 'ofdma_channels', 'ofdm', 'ofdma'):
                if _positive_channels(iv.get(field)) and not _positive_channels(m.get(field)):
                    m[field] = iv[field]
            for field in ('ofdm_channel_count', 'ofdma_channel_count'):
                if _positive_index(iv.get(field)) and not _positive_index(m.get(field)):
                    m[field] = iv[field]
            incoming_interface = str(iv.get("upstream_interface") or '').strip()
            current_interface = str(m.get("upstream_interface") or '').strip()
            if incoming_interface and (
                not current_interface
                or ('ofdma' in incoming_interface.lower() and 'ofdma' not in current_interface.lower())
            ):
                m["upstream_interface"] = incoming_interface
            if not m.get("vendor") and iv.get("vendor"):
                m["vendor"] = iv["vendor"]
            if _identity_value_missing(m.get("model")) and not _identity_value_missing(iv.get("model")):
                m["model"] = iv["model"]
        _normalize_modem_capability(m, iv)
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
    """Search authoritative cable modem inventory across one or all CMTS entries.

    Query params:
      - search_type: ip | mac | name
      - search_value: string to match
      - cmts: optional CMTS hostname to scope the search
      - interface: optional interface filter

    This endpoint reads persisted PyPNM inventory and never triggers a live SNMP walk.
    """
    search_type = (request.args.get('search_type') or '').strip().lower()
    search_value = (request.args.get('search_value') or '').strip().lower()
    cmts_filter = (request.args.get('cmts') or '').strip()
    iface_filter = (request.args.get('interface') or '').strip().lower()
    query_limit = _bounded_modem_limit(
        request.args.get('limit', _cm_modem_limit_default())
    )

    # CPE addresses are persisted and indexed by PyPNM. Keep the GUI as a
    # thin proxy for this search.
    if search_type == 'cpe_ip':
        if not search_value:
            return jsonify({'status': 'error', 'message': 'CPE address is required'}), 400
        try:
            response = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type='cpe_ip',
                search_value=search_value,
                interface=iface_filter or None,
                limit=query_limit,
            )
        except Exception as exc:
            logger.exception('PyPNM CPE inventory search failed')
            return _pypnm_error_response(
                _pypnm_exception_result(exc), 'CPE inventory search failed'
            )
        if not isinstance(response, dict):
            return _pypnm_error_response(None, 'PyPNM returned an invalid CPE inventory response')
        if response.get('status') != 'success':
            logger.warning(
                'PyPNM CPE inventory search failed: %s',
                response.get('message') or 'unknown error',
            )
            return _pypnm_error_response(response, 'CPE inventory search failed')
        # CPE matches are authoritative. Do not hide them based on the
        # linked modem's IP address matching MODEM_IGNORE_CIDRS.
        modems = response.get('modems') or []
        return jsonify({
            'status': 'success',
            'modems': modems,
            'count': len(modems),
            'cached': True,
            'source': response.get('source') or 'pypnm-inventory',
        })

    def _fallback_for_mac(query_mac: str):
        mac_bare = re.sub(r'[^a-f0-9]', '', (query_mac or '').lower())
        if len(mac_bare) != 12:
            return None

        client = PyPNMClient()
        try:
            inv_resp = client.get_inventory_modem_by_mac(mac_bare, request_timeout=10)
        except Exception as exc:
            return _pypnm_error_response(
                _pypnm_exception_result(exc), 'PyPNM inventory lookup failed'
            )
        if not isinstance(inv_resp, dict):
            return _pypnm_error_response(None, 'PyPNM returned an invalid inventory response')
        inv_modem = inv_resp.get('modem')
        if inv_resp.get('status') == 'success' and inv_modem:
            _normalize_modem_capability(inv_modem)
            _augment_modems_with_topology_fields(
                [inv_modem], cmts_name=str(inv_modem.get('cmts') or '')
            )
            return jsonify({
                'status': 'success',
                'modems': [inv_modem],
                'count': 1,
                'cached': True,
                'source': inv_resp.get('source') or 'pypnm-inventory',
            })
        if not _inventory_lookup_absent(inv_resp, 'modem'):
            return _pypnm_error_response(inv_resp, 'PyPNM inventory lookup failed')

        # Topology is an exact fallback only after authoritative inventory absence.
        try:
            topo_resp = client.get_topology_modem_by_mac(mac_bare, request_timeout=10)
        except Exception as exc:
            return _pypnm_error_response(
                _pypnm_exception_result(exc), 'PyPNM topology lookup failed'
            )
        if not isinstance(topo_resp, dict):
            return _pypnm_error_response(None, 'PyPNM returned an invalid topology response')
        topo_modem = topo_resp.get('modem')
        if topo_resp.get('status') == 'success' and topo_modem:
            modem = {
                "mac_address": topo_modem.get('mac') or query_mac,
                "name": topo_modem.get('mac') or query_mac,
                "ip_address": "",
                "status": "topology-only",
                "vendor": "Unknown",
                "model": "N/A",
                "docsis_version": "Unknown",
                "cmts": topo_modem.get('cmts') or "",
                "cmts_ip": topo_modem.get('cmts_ip') or "",
                "fiber_node": "",
                "topology_fiber_node": topo_modem.get('fibernode') or "",
                "customer_id": topo_modem.get('customer_id') or "",
                "postalcode": topo_modem.get('postalcode') or "",
                "house_number": topo_modem.get('house_number') or "",
                "house_number_extension": topo_modem.get('house_number_extension') or "",
                "topology_path": topo_modem.get('hierarchy_path') or "",
                "topology_link_id": topo_modem.get('topology_link_id') or "",
                "linked_node_id": topo_modem.get('linked_node_id') or "",
                "linked_node_type": topo_modem.get('linked_node_type') or "",
                "link_match": bool(topo_modem.get('link_match')),
                "source": "topology-mysql",
            }
            return jsonify({
                "status": "success",
                "modems": [modem],
                "count": 1,
                "cached": False,
                "source": "topology-mysql",
            })
        if not _inventory_lookup_absent(topo_resp, 'modem'):
            return _pypnm_error_response(topo_resp, 'PyPNM topology lookup failed')
        return jsonify({
            "status": "success",
            "modems": [],
            "count": 0,
            "cached": True,
            "source": "pypnm-inventory",
        })

    def _inventory_fallback_error(response):
        if isinstance(response, dict) and response.get('status') == 'success':
            return None
        logger.warning(
            'PyPNM inventory fallback failed: %s',
            response.get('message') if isinstance(response, dict) else 'invalid response',
        )
        return _pypnm_error_response(response, 'PyPNM inventory search failed')

    # Full MAC addresses use one authoritative primary-key lookup followed by
    # one topology fallback; do not repeat the chain through general search.
    if search_type == 'mac' and len(re.sub(r'[^a-f0-9]', '', search_value)) == 12:
        return _fallback_for_mac(search_value)

    try:
        modems_resp = PyPNMClient().get_inventory_modems(
            cmts=cmts_filter or None,
            search_type=search_type or None,
            search_value=search_value or None,
            interface=iface_filter or None,
            limit=query_limit,
        )
        inventory_error = _inventory_fallback_error(modems_resp)
        if inventory_error:
            return inventory_error

        modems = filter_ignored_modems(modems_resp.get('modems') or [])
        if not modems and search_type == 'mac' and search_value:
            mac_fallback = _fallback_for_mac(search_value)
            if mac_fallback is not None:
                return mac_fallback

        # Keep ordering deterministic across authoritative inventory pages and
        # enforce the bounded browser-facing limit after ignored-row filtering.
        modems.sort(
            key=lambda modem: (
                str(modem.get('cmts') or modem.get('cmts_ip') or '').lower(),
                re.sub(r'[^a-f0-9]', '', str(modem.get('mac_address') or '').lower()),
            )
        )
        modems = modems[:query_limit]
        _augment_modems_with_topology_fields(modems)

        metadata = _snapshot_metadata(modems_resp, modems)
        return jsonify({
            "status": "success",
            "modems": modems,
            "count": len(modems),
            "cached": True,
            **metadata,
        })
    except Exception as exc:
        logger.exception("PyPNM inventory search failed")
        return _pypnm_error_response(
            _pypnm_exception_result(exc), 'PyPNM inventory search failed'
        )


@api_bp.route('/modems/cpe-suggestions', methods=['GET'])
def get_cpe_suggestions():
    """Proxy CPE address autocomplete to PyPNM's persisted CPE index."""
    query = (request.args.get('q') or '').strip()
    try:
        limit = max(1, min(int(request.args.get('limit') or 10), 50))
    except (TypeError, ValueError):
        limit = 10
    if not query:
        return jsonify({'status': 'success', 'suggestions': []})

    try:
        response = PyPNMClient().get_inventory_cpe_suggestions(query, limit=limit)
        if response.get('status') != 'success':
            logger.warning(
                'PyPNM CPE suggestions unavailable: %s',
                response.get('message') or 'unknown error',
            )
            return jsonify({'status': 'success', 'suggestions': []})
        return jsonify({
            'status': 'success',
            'suggestions': (response.get('suggestions') or [])[:limit],
            'source': 'pypnm-inventory',
        })
    except Exception as exc:
        logger.warning('PyPNM CPE suggestions unavailable: %s', exc)
        return jsonify({'status': 'success', 'suggestions': []})


@api_bp.route('/modems/<mac_address>', methods=['GET'])
def get_modem(mac_address):
    """Get a specific modem by authoritative MAC lookup or topology fallback."""
    # Normalise both to bare hex (no separators) for comparison so that
    # 5CFA25A1CA92, 5c:fa:25:a1:ca:92, and 5c-fa-25-a1-ca-92 all match.
    def _bare(mac):
        return re.sub(r'[^a-f0-9]', '', (mac or '').lower())

    def _backfill_topology(modem: dict) -> None:
        """Fill missing topology fields without replacing CMTS/inventory data."""
        _augment_modems_with_topology_fields(
            [modem],
            cmts_name=str(modem.get('cmts') or ''),
        )

    mac_bare = _bare(mac_address)

    # Authoritative inventory lookup is a primary-key query. Topology is only
    # consulted after the inventory positively confirms absence.
    try:
        modem_resp = PyPNMClient().get_inventory_modem_by_mac(mac_bare, request_timeout=10)
    except Exception as exc:
        return _pypnm_error_response(
            _pypnm_exception_result(exc), 'PyPNM modem inventory lookup failed'
        )
    if not isinstance(modem_resp, dict):
        return _pypnm_error_response(None, 'PyPNM returned an invalid inventory response')
    modem = modem_resp.get('modem')
    if modem_resp.get('status') == 'success' and modem:
        _normalize_modem_capability(modem)
        _backfill_topology(modem)
        return jsonify({
            "status": "success",
            "modem": modem,
            "cached": True,
            "source": modem_resp.get('source') or "pypnm-inventory",
        })
    if not _inventory_lookup_absent(modem_resp, 'modem'):
        return _pypnm_error_response(modem_resp, 'PyPNM modem inventory lookup failed')

    # Final fallback: exact topology snapshot for a positively absent inventory row.
    try:
        topo_resp = PyPNMClient().get_topology_modem_by_mac(mac_bare, request_timeout=10)
    except Exception as exc:
        return _pypnm_error_response(
            _pypnm_exception_result(exc), 'PyPNM topology modem lookup failed'
        )
    if not isinstance(topo_resp, dict):
        return _pypnm_error_response(None, 'PyPNM returned an invalid topology response')
    topo_modem = topo_resp.get('modem')
    if topo_resp.get('status') == 'success' and topo_modem:
        mac_norm = topo_modem.get('mac') or mac_address
        modem = {
            "mac_address": mac_norm,
            "name": mac_norm,
            "ip_address": "",
            "cpe_ipv4": [],
            "cpe_ipv6": [],
            "status": "topology-only",
            "vendor": "Unknown",
            "model": "N/A",
            "docsis_version": "Unknown",
            "cmts": topo_modem.get('cmts') or "",
            "cmts_ip": topo_modem.get('cmts_ip') or "",
            "fiber_node": "",
            "topology_fiber_node": topo_modem.get('fibernode') or "",
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
            "cached": False,
            "source": "topology-mysql",
        })
    if not _inventory_lookup_absent(topo_resp, 'modem'):
        return _pypnm_error_response(topo_resp, 'PyPNM topology modem lookup failed')

    return jsonify({
        "status": "error",
        "message": "Modem not found in inventory or topology snapshot."
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
    """Return persisted PyPNM interface choices for a configured CMTS."""
    cmts = (
        CMTSProvider.get_cmts_by_hostname(cmts_name)
        or CMTSProvider.get_cmts_by_ip(cmts_name)
    )
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found"
        }), 404

    canonical_name = str(cmts.get('HostName') or cmts_name).strip()
    cmts_ip = str(
        cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address') or ''
    ).strip()

    def _interface_value(item):
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ('interface', 'name', 'if_name', 'interface_name', 'value'):
                value = str(item.get(key) or '').strip()
                if value:
                    return value
        return ''

    def _values(*sources):
        values = []
        seen = set()
        for source in sources:
            if not isinstance(source, list):
                continue
            for item in source:
                value = _interface_value(item)
                normalized = value.lower()
                if value and normalized not in seen:
                    seen.add(normalized)
                    values.append(value)
        return values

    def _response_values(response):
        return _values(
            response.get('interfaces'),
            response.get('downstream_interfaces'), response.get('downstream'),
            response.get('upstream_interfaces'), response.get('upstream'),
            response.get('cable_macs'),
        )

    client = PyPNMClient()
    result = None
    used_ref = canonical_name
    empty_successes = []
    first_error = None
    for candidate in _cmts_inventory_refs(cmts, cmts_name):
        try:
            response = client.get_inventory_interfaces(candidate)
        except Exception as exc:
            response = _pypnm_exception_result(exc)
        if isinstance(response, dict) and response.get('status') == 'success':
            if _response_values(response):
                result = response
                used_ref = candidate
                break
            empty_successes.append((candidate, response))
        elif first_error is None:
            first_error = response

    if result is None:
        if first_error is not None:
            return _pypnm_error_response(first_error, 'Inventory interfaces unavailable')
        if not empty_successes:
            return _pypnm_error_response(None, 'Inventory interfaces unavailable')
        # Every distinct hostname/IP lookup succeeded empty.
        used_ref, result = empty_successes[0]

    downstream = _values(
        result.get('downstream_interfaces'), result.get('downstream'),
    )
    upstream = _values(
        result.get('upstream_interfaces'), result.get('upstream'),
    )
    cable_macs = _values(result.get('cable_macs'))
    flat = _values(result.get('interfaces'), downstream, upstream, cable_macs)
    categorized = {value.lower() for value in downstream + upstream + cable_macs}
    other = [value for value in flat if value.lower() not in categorized]

    # Categorize an upstream flat response without changing its interface labels.
    for value in list(other):
        lowered = value.lower()
        if 'upstream' in lowered or lowered.startswith(('us', 'cable-up')):
            upstream.append(value)
            other.remove(value)
        elif 'downstream' in lowered or lowered.startswith(
            ('ds', 'cable-down', 'wideband-cable', 'integrated-cable')
        ):
            downstream.append(value)
            other.remove(value)

    interfaces = _values(downstream, upstream, cable_macs, other)
    return jsonify({
        "status": "success",
        "cmts": canonical_name,
        "cmts_hostname": canonical_name,
        "cmts_ip": cmts_ip,
        "inventory_ref": used_ref,
        "interfaces": interfaces,
        "downstream_interfaces": _values(downstream),
        "upstream_interfaces": _values(upstream),
        "cable_macs": _values(cable_macs),
        "other_interfaces": _values(other),
    })


@api_bp.route('/cmts/<cmts_name>/modems', methods=['GET'])
def get_cmts_modems(cmts_name):
    """Return persisted CMTS inventory first; discover live only when explicitly needed."""
    logger = logging.getLogger(__name__)

    cmts = (
        CMTSProvider.get_cmts_by_hostname(cmts_name)
        or CMTSProvider.get_cmts_by_ip(cmts_name)
    )
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found"
        }), 404

    community = _first_community(
        request.args.get('community'),
        cmts.get('snmp_community'),
        get_cmts_community(),
    )
    limit = _bounded_modem_limit(request.args.get('limit', _cm_modem_limit_default()))
    enrich = request.args.get('enrich', 'false').lower() == 'true'
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    include_topology = request.args.get('include_topology', 'true').lower() == 'true'

    try:
        cmts_ip = cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address')
        canonical_name = str(cmts.get('HostName') or cmts_name).strip()
        if not cmts_ip:
            logger.error(f"CMTS {cmts_name} has no IP address: {cmts}")
            return jsonify({
                "status": "error",
                "message": f"CMTS '{cmts_name}' has no IP address configured"
            }), 500

        def _prepare_rows(rows):
            prepared = filter_ignored_modems(rows or [])[:limit]
            for modem in prepared:
                modem['cmts'] = canonical_name
                modem['cmts_ip'] = cmts_ip
                if community is not None:
                    modem['cmts_community'] = community
                else:
                    modem.pop('cmts_community', None)
            if include_topology:
                _augment_modems_with_topology_fields(prepared, cmts_name=canonical_name)
            return prepared

        def _success_response(rows, metadata, agent_id, cached):
            snapshot = _snapshot_metadata(metadata or {}, rows)
            return jsonify({
                "status": "success",
                "cmts": canonical_name,
                "cmts_hostname": canonical_name,
                "cmts_ip": cmts_ip,
                "agent_id": agent_id,
                "modems": rows,
                "count": len(rows),
                "cached": cached,
                "enriched": (metadata or {}).get('enriched') is True,
                "enriching": (metadata or {}).get('enriching') is True,
                "enrichment_progress": (
                    (metadata or {}).get('enrichment_progress')
                    or (metadata or {}).get('enrich_progress')
                ),
                **snapshot,
            })

        # Query every distinct authoritative hostname/IP inventory key. A live
        # non-refresh discovery is safe only when all of them succeed empty.
        if not force_refresh:
            client = PyPNMClient()
            inventory_refs = _cmts_inventory_refs(cmts, cmts_name)
            empty_success_count = 0
            first_inventory_error = None
            for normalized_ref in inventory_refs:
                try:
                    inventory_resp = client.get_inventory_modems(
                        cmts=normalized_ref,
                        limit=limit,
                    )
                except Exception as exc:
                    inventory_resp = _pypnm_exception_result(exc)

                if not isinstance(inventory_resp, dict):
                    inventory_resp = {
                        'status': 'error',
                        'success': False,
                        'failure_status': 'unexpected_error',
                        'upstream_http_status': None,
                        'message': 'PyPNM returned an invalid inventory response',
                    }

                if inventory_resp.get('status') != 'success':
                    if first_inventory_error is None:
                        first_inventory_error = inventory_resp
                    logger.warning(
                        "Persisted inventory lookup failed for %s: %s",
                        normalized_ref,
                        inventory_resp.get('message') or inventory_resp.get('error'),
                    )
                    continue

                inventory_rows = inventory_resp.get('modems') or []
                if not inventory_rows:
                    empty_success_count += 1
                    continue

                rows = _prepare_rows(inventory_rows)
                inventory_resp.setdefault('source', 'pypnm-inventory')
                logger.info(
                    "Returning %d persisted modems for %s via inventory key %s",
                    len(rows), canonical_name, normalized_ref,
                )
                return _success_response(rows, inventory_resp, 'inventory', True)

            if first_inventory_error is not None:
                return _pypnm_error_response(
                    first_inventory_error, 'PyPNM inventory unavailable'
                )
            if not inventory_refs or empty_success_count != len(inventory_refs):
                return _pypnm_error_response(None, 'PyPNM inventory unavailable')

        # Live base discovery is reserved for refresh=true or confirmed absence
        # from every persisted hostname/IP inventory key.
        client = PyPNMClient()
        live_query = {
            'cmts_ip': cmts_ip,
            'limit': limit,
            'enrich': enrich,
            'refresh': force_refresh,
            'cmts_hostname': canonical_name,
        }
        if community is not None:
            live_query['community'] = community
        result = client.get_cmts_modems(**live_query)
        if not isinstance(result, dict):
            return _pypnm_error_response(None, 'PyPNM returned an invalid live modem response')

        if result.get('success'):
            rows = _prepare_rows(result.get('modems') or [])
            result.setdefault('source', 'pypnm-live')
            logger.info(
                "Retrieved %d modems from %s via PyPNM live query",
                len(rows), canonical_name,
            )
            return _success_response(rows, result, result.get('agent_id', 'agent'), False)

        logger.error(
            "PyPNM live modem query failed for %s: failure_status=%s upstream_status=%s",
            canonical_name,
            result.get('failure_status'),
            result.get('upstream_http_status'),
        )
        return _pypnm_error_response(result, 'PyPNM live modem query failed')

    except Exception:
        logger.exception("Error getting modems from %s", cmts_name)
        return jsonify({
            "status": "error",
            "message": "Unexpected error while loading CMTS modems",
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
    """Clear PyPNM-owned modem cache state for one configured CMTS."""
    cmts = (
        CMTSProvider.get_cmts_by_hostname(cmts_name)
        or CMTSProvider.get_cmts_by_ip(cmts_name)
    )
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found",
        }), 404

    cmts_ip = cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address')
    canonical_name = str(cmts.get('HostName') or cmts_name).strip()
    if not cmts_ip:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' has no IP address configured",
        }), 500

    result = PyPNMClient().clear_cmts_modem_cache(str(cmts_ip))
    if not isinstance(result, dict):
        return _pypnm_error_response(None, 'PyPNM returned an invalid cache-clear response')
    if result.get('status') == 'success' or result.get('success') is True:
        response = dict(result)
        response['status'] = 'success'
        response.setdefault('cmts', canonical_name)
        response.setdefault('cmts_ip', cmts_ip)
        response.setdefault('message', f"Cache cleared for {canonical_name}")
        return jsonify(response)

    return _pypnm_error_response(result, 'PyPNM cache clear failed')


@api_bp.route('/cmts/<cmts_name>/enrich/delta', methods=['POST'])
def enqueue_delta_enrichment(cmts_name):
    """Ask PyPNM to select and queue this CMTS inventory's enrichment delta."""
    cmts = (
        CMTSProvider.get_cmts_by_hostname(cmts_name)
        or CMTSProvider.get_cmts_by_ip(cmts_name)
    )
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found",
        }), 404

    canonical_name = str(cmts.get('HostName') or cmts_name).strip()
    payload = request.get_json(silent=True) or {}
    try:
        max_batch = max(1, min(int(payload.get('max_batch') or 25), 25))
    except (TypeError, ValueError):
        max_batch = 25

    result = PyPNMClient().enqueue_delta_enrichment(canonical_name, max_batch=max_batch)
    if not isinstance(result, dict):
        return _pypnm_error_response(None, 'PyPNM returned an invalid delta-enrichment response')
    if result.get('status') == 'success' or result.get('success') is True:
        response = dict(result)
        response['status'] = 'success'
        response.setdefault('cmts', canonical_name)
        response.setdefault('total_modems', 0)
        response.setdefault('missing_count', 0)
        response.setdefault('enqueued', 0)
        response.setdefault('already_queued', 0)
        response.setdefault('max_batch', max_batch)
        return jsonify(response)

    return _pypnm_error_response(result, 'PyPNM delta enrichment failed')


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

