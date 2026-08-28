# PyPNM Web GUI - API Routes

import os
import re
import json
import logging
import time
import threading
import uuid
from datetime import datetime, timezone
from flask import jsonify, request, current_app, session
from . import api_bp
from app.core.cmts_provider import CMTSProvider
from app.core.pypnm_client import PyPNMClient
from app.core.topology_db import topology_db
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


def get_default_community():
    """Get the configured SNMP read community for modems."""
    return _first_community(
        os.environ.get('MODEM_COMMUNITY'),
        os.environ.get('CM_SNMP_COMMUNITY'),
    )


def get_cmts_community():
    """Get the configured fallback SNMP read community for CMTS operations."""
    return _first_community(
        os.environ.get('CMTS_COMMUNITY'),
        os.environ.get('CMTS_SNMP_COMMUNITY'),
    )


# Redis for caching modem data
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    # Redis accelerates authoritative MySQL inventory reads. Cache entries are
    # revision-checked, so their lifetime can safely exceed inventory freshness.
    REDIS_TTL = max(1, min(int(os.environ.get('REDIS_TTL', '604800')), 2592000))
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    print(f"[INFO] Redis cache connected: {REDIS_HOST}:{REDIS_PORT}", flush=True)
except Exception as e:
    REDIS_AVAILABLE = False
    redis_client = None
    print(f"[WARNING] Redis not available: {e}", flush=True)


def _redis_cache_modems_for_key(
    cache_key: str,
    cmts_name: str,
    modems: list[dict],
    requested_limit: int | None = None,
    metadata: dict | None = None,
) -> None:
    if not REDIS_AVAILABLE or not redis_client or not cache_key:
        return
    if requested_limit is None:
        requested_limit = _cm_modem_limit_default()
    try:
        modems = filter_ignored_modems(modems)
        snapshot_id = str((metadata or {}).get("snapshot_id") or "").strip()
        if not snapshot_id:
            logger.info("Skipped unverifiable modem cache write for %s", cache_key)
            return
        payload = {
            "cmts": cmts_name,
            "requested_limit": requested_limit,
            "cache_query_limit": requested_limit,
            "modems": modems,
            "cache_written_at": int(time.time()),
            "source": "pypnm-inventory",
        }
        payload.update(_snapshot_metadata(metadata or {}, modems))
        for state_key in ('enriched', 'enriching', 'enrichment_progress'):
            if state_key in (metadata or {}):
                payload[state_key] = metadata.get(state_key)
        ttl = _cache_remaining_ttl(payload)
        if ttl <= 0:
            redis_client.delete(cache_key)
            logger.info("Skipped stale modem cache write for %s", cache_key)
            return
        redis_client.setex(cache_key, ttl, json.dumps(payload))
    except Exception as exc:
        logger.warning(f"Redis modem cache write error for {cache_key}: {exc}")


def _backfill_redis_from_inventory(
    modems: list[dict],
    requested_limit: int | None = None,
    metadata: dict | None = None,
) -> None:
    if not REDIS_AVAILABLE or not redis_client or not modems:
        return
    if requested_limit is None:
        requested_limit = _cm_modem_limit_default()

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
        _redis_cache_modems_for_key(
            f"modems:{group_name}", group_name, rows,
            requested_limit=requested_limit, metadata=metadata,
        )

    for alias_key, group_name in aliases.items():
        rows = grouped.get(group_name) or []
        if rows:
            _redis_cache_modems_for_key(
                f"modems:{alias_key}", group_name, rows,
                requested_limit=requested_limit, metadata=metadata,
            )


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

def _cache_reference_time(payload: dict):
    return _parse_inventory_timestamp(payload.get("collected_at")) or _parse_inventory_timestamp(
        payload.get("timestamp")
    )


def _cache_remaining_ttl(payload: dict) -> int:
    """Bound Redis lifetime from cache write time, not inventory collection time."""
    written_at = _parse_inventory_timestamp(payload.get("cache_written_at"))
    if written_at is None:
        # Legacy payloads remain bounded by their existing Redis TTL.
        return REDIS_TTL
    age = max(0.0, (datetime.now(timezone.utc) - written_at).total_seconds())
    return max(0, min(REDIS_TTL, int(REDIS_TTL - age)))


def _inventory_revision_map() -> dict[str, dict] | None:
    """Load authoritative CMTS revisions; return None when verification is unavailable."""
    revisions: dict[str, dict] = {}
    try:
        response = PyPNMClient().get_inventory_snapshots(request_timeout=5)
        if response.get("status") != "success":
            raise RuntimeError(response.get("message") or "revision lookup failed")
        for snapshot in response.get("snapshots") or []:
            revision = _parse_inventory_timestamp(
                snapshot.get("revision_at") or snapshot.get("collected_at")
            )
            if revision is None:
                continue
            state = {
                "revision": revision,
                "snapshot_id": str(snapshot.get("snapshot_id") or "").strip(),
            }
            for alias in (snapshot.get("cmts"), snapshot.get("cmts_ip")):
                key = str(alias or "").strip().lower()
                if key:
                    revisions[key] = state
    except Exception as exc:
        logger.warning("Inventory revision lookup unavailable: %s", exc)
        return None
    return revisions


def _cache_payload_is_current(payload: dict, revisions: dict[str, dict] | None = None) -> bool:
    if _cache_remaining_ttl(payload) <= 0 or revisions is None:
        return False

    aliases = [str(payload.get("cmts") or "").strip().lower()]
    modems = payload.get("modems") or []
    if modems and isinstance(modems[0], dict):
        aliases.append(str(modems[0].get("cmts_ip") or "").strip().lower())
    states = [revisions[a] for a in aliases if a in revisions]
    current_state = max(states, key=lambda state: state["revision"], default=None)
    if current_state is None:
        return False

    current_snapshot_id = current_state.get("snapshot_id")
    cached_snapshot_id = str(payload.get("snapshot_id") or "").strip()
    if current_snapshot_id and current_snapshot_id != cached_snapshot_id:
        return False

    cached_revision = _parse_inventory_timestamp(payload.get("revision_at"))
    cached_revision = cached_revision or _parse_inventory_timestamp(
        payload.get("inventory_revision")
    )
    cached_revision = cached_revision or _cache_reference_time(payload)
    return cached_revision is not None and current_state["revision"] <= cached_revision


def _read_modem_cache(cache_key: str, revisions: dict[str, dict] | None = None):
    """Read a verified modem cache payload; retain keys during verifier outages."""
    cached = redis_client.get(cache_key) if redis_client else None
    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except Exception:
        if redis_client:
            redis_client.delete(cache_key)
        return None
    if not isinstance(payload, dict) or not _cache_payload_is_current(payload, revisions):
        # None means PyPNM verification was unavailable. Bypass but retain the
        # cache so a transient outage does not destroy a valid generation.
        if redis_client and revisions is not None:
            redis_client.delete(cache_key)
            logger.info("Invalidated stale modem cache key %s", cache_key)
        else:
            logger.info("Bypassed unverifiable modem cache key %s", cache_key)
        return None
    return payload


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


# Values that mean an identity field has not actually been enriched.
_IDENTITY_PLACEHOLDERS = {'', 'unknown', 'n/a', 'na', 'none', 'null', '-', '—'}


def _identity_value_missing(value) -> bool:
    return str(value or '').strip().lower() in _IDENTITY_PLACEHOLDERS


def _modems_are_enriched(modems: list[dict]) -> bool:
    """Return True only when a meaningful portion of modems have vendor+firmware data."""
    if not modems:
        return False
    sample = modems[:200]  # Check up to 200 rows for speed
    enriched_count = sum(
        1 for m in sample
        if not _identity_value_missing(m.get('vendor'))
        and not _identity_value_missing(m.get('software_version') or m.get('firmware'))
    )
    return (enriched_count / len(sample)) >= _ENRICH_QUALITY_THRESHOLD


def _modem_missing_enrichment(modem: dict) -> bool:
    vendor = str(modem.get('vendor') or '').strip().lower()
    fw = str(modem.get('software_version') or modem.get('firmware') or '').strip().lower()
    vendor_missing = vendor in ('', 'unknown', 'n/a')
    fw_missing = fw in ('', 'unknown', 'n/a')
    return vendor_missing or fw_missing


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
        cur.execute("SELECT MAX(id) AS id FROM topology_snapshots")
        snapshot_row = cur.fetchone() or {}
        snapshot_id = snapshot_row.get("id") if hasattr(snapshot_row, "get") else None
        if snapshot_id is None:
            return out

        marker = "%s"
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            # topology_modems is indexed by (snapshot_id, mac). Query common
            # stored MAC formats directly so MySQL can use that index instead
            # of repeatedly scanning the table through REPLACE/UPPER.
            candidates = set()
            for mac in chunk:
                pairs = [mac[j:j + 2] for j in range(0, 12, 2)]
                candidates.add(mac)
                candidates.add(":".join(pairs))
                candidates.add("-".join(pairs))
                candidates.add(f"{mac[:4]}.{mac[4:8]}.{mac[8:12]}")
            candidate_list = sorted(candidates)
            placeholders = ",".join([marker] * len(candidate_list))
            sql = (
                "SELECT mac, linked_node_id, lat, lon, fibernode, customer_id, address "
                "FROM topology_modems "
                f"WHERE snapshot_id={marker} AND mac IN ({placeholders})"
            )
            cur.execute(sql, tuple([snapshot_id, *candidate_list]))
            rows = cur.fetchall() or []
            for row in rows:
                r = dict(row) if hasattr(row, "keys") else row
                mac_norm = _bare(r.get("mac"))
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
    query_limit = _bounded_modem_limit(
        request.args.get('limit', _cm_modem_limit_default())
    )

    # CPE addresses are persisted and indexed by PyPNM. Keep the GUI as a
    # thin proxy and bypass its per-worker Redis modem caches for this search.
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
            if response.get('status') != 'success':
                message = response.get('message') or 'CPE inventory search failed'
                logger.warning('PyPNM CPE inventory search failed: %s', message)
                return jsonify({'status': 'error', 'message': message}), 503
            # CPE matches are authoritative. Do not hide them based on the
            # linked modem's IP address matching MODEM_IGNORE_CIDRS.
            modems = response.get('modems') or []
            return jsonify({
                'status': 'success',
                'modems': modems,
                'count': len(modems),
                'cached': bool(response.get('cached')),
                'source': response.get('source') or 'pypnm-inventory',
            })
        except Exception as exc:
            logger.exception('PyPNM CPE inventory search failed')
            return jsonify({'status': 'error', 'message': str(exc)}), 503

    def _fallback_for_mac(query_mac: str):
        mac_bare = re.sub(r'[^a-f0-9]', '', (query_mac or '').lower())
        if len(mac_bare) != 12:
            return None
        try:
            inv_resp = PyPNMClient().get_inventory_modem_by_mac(mac_bare, request_timeout=10)
            inv_modem = inv_resp.get('modem') if isinstance(inv_resp, dict) else None
            if inv_modem:
                _normalize_modem_capability(inv_modem)
                return jsonify({
                    'status': 'success',
                    'modems': [inv_modem],
                    'count': 1,
                    'cached': False,
                    'source': inv_resp.get('source') or 'pypnm-inventory',
                })
        except Exception:
            pass
        try:
            topo_resp = PyPNMClient().get_topology_modem_by_mac(mac_bare, request_timeout=10)
            topo_modem = topo_resp.get('modem') if isinstance(topo_resp, dict) else None
            if not topo_modem:
                return None
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
                "fiber_node": topo_modem.get('fibernode') or "",
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
        except Exception:
            return None

    # Full MAC addresses are primary-key lookups. Resolve them before scanning
    # large Redis payloads or invoking the general inventory search endpoint.
    if search_type == 'mac' and len(re.sub(r'[^a-f0-9]', '', search_value)) == 12:
        exact_mac_result = _fallback_for_mac(search_value)
        if exact_mac_result is not None:
            return exact_mac_result

    # MySQL inventory fallback path when Redis is unavailable.
    if not REDIS_AVAILABLE or not redis_client:
        try:
            default_limit = query_limit
            modems_resp = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type=search_type or None,
                search_value=search_value or None,
                interface=iface_filter or None,
                limit=default_limit,
            )
            modems = filter_ignored_modems(modems_resp.get('modems') or [])
            if not modems and search_type == 'mac' and search_value:
                mac_fallback = _fallback_for_mac(search_value)
                if mac_fallback is not None:
                    return mac_fallback
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
        keys = (
            [f"modems:{cmts_filter}"]
            if cmts_filter
            else redis_client.scan_iter(match='modems:*', count=500)
        )
        revisions = _inventory_revision_map()
        seen_macs: set[str] = set()
        modems = []

        for key in keys:
            payload = _read_modem_cache(key, revisions)
            if not payload:
                continue
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
            default_limit = query_limit
            db_resp = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type=search_type or None,
                search_value=search_value or None,
                interface=iface_filter or None,
                limit=default_limit,
            )
            db_modems = filter_ignored_modems(db_resp.get('modems') or [])
            if db_modems:
                _backfill_redis_from_inventory(
                    db_modems,
                    requested_limit=db_resp.get('requested_limit') or default_limit,
                    metadata=db_resp,
                )
                _augment_modems_with_topology_fields(db_modems)
                return jsonify({
                    "status": "success",
                    "modems": db_modems,
                    "count": len(db_modems),
                    "cached": False,
                    "source": db_resp.get('source') or "pypnm-inventory",
                })
            if search_type == 'mac' and search_value:
                mac_fallback = _fallback_for_mac(search_value)
                if mac_fallback is not None:
                    return mac_fallback
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

        # Redis may contain rows for other searches while having no match for
        # this query. Always ask persisted PyPNM inventory before MAC/topology
        # fallback so expiration or a sparse acceleration cache cannot hide data.
        if not modems:
            default_limit = query_limit
            db_resp = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type=search_type or None,
                search_value=search_value or None,
                interface=iface_filter or None,
                limit=default_limit,
            )
            db_modems = filter_ignored_modems(db_resp.get('modems') or [])
            if db_modems:
                _backfill_redis_from_inventory(
                    db_modems,
                    requested_limit=db_resp.get('requested_limit') or default_limit,
                    metadata=db_resp,
                )
                _augment_modems_with_topology_fields(db_modems)
                return jsonify({
                    "status": "success",
                    "modems": db_modems,
                    "count": len(db_modems),
                    "cached": False,
                    "source": db_resp.get('source') or "pypnm-inventory",
                })

        if not modems and search_type == 'mac' and search_value:
            mac_fallback = _fallback_for_mac(search_value)
            if mac_fallback is not None:
                return mac_fallback

        # Stable ordering for UI and honor the bounded caller limit.
        modems.sort(key=lambda m: (str(m.get('cmts', '')), str(m.get('mac_address', ''))))
        modems = modems[:query_limit]

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
    """Get a specific modem by MAC address from cache or mock data."""
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

    # Authoritative inventory lookup is a primary-key query and avoids scanning
    # every CMTS cache payload as Redis retention grows.
    try:
        modem_resp = PyPNMClient().get_inventory_modem_by_mac(mac_bare, request_timeout=10)
        modem = modem_resp.get('modem') if isinstance(modem_resp, dict) else None
        if modem:
            _normalize_modem_capability(modem)
            _backfill_topology(modem)
            return jsonify({
                "status": "success",
                "modem": modem,
                "source": modem_resp.get('source') or "pypnm-inventory",
            })
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "PyPNM primary modem inventory lookup error: %s", exc
        )

    # Try to find in a revision-current Redis cache.
    if REDIS_AVAILABLE and redis_client:
        try:
            revisions = _inventory_revision_map()
            keys = redis_client.scan_iter(match='modems:*', count=500)
            for key in keys:
                data = _read_modem_cache(key, revisions)
                if data:
                    modems = data.get('modems', [])
                    for modem in modems:
                        if _bare(modem.get('mac_address', '')) == mac_bare:
                            # Merge enrichment fields from inventory when Redis
                            # cache lacks them (vendor/model/software/ofdm come
                            # from sysDescr refresh, stored in MySQL only).
                            inv_m = None
                            if (_identity_value_missing(modem.get('vendor'))
                                    or _identity_value_missing(modem.get('model'))
                                    or _identity_value_missing(modem.get('software_version') or modem.get('firmware'))
                                    or not modem.get('fiber_node')
                                    or not modem.get('cable_mac')
                                    or modem.get('ofdm_enabled') is None
                                    or modem.get('ofdma_enabled') is None
                                    or 'cpe_ipv4' not in modem
                                    or 'cpe_ipv6' not in modem
                                    or _docsis_version_rank(modem.get('docsis_version')) < 31):
                                try:
                                    inv = PyPNMClient().get_inventory_modem_by_mac(mac_bare, request_timeout=10)
                                    inv_m = inv.get('modem') if isinstance(inv, dict) else None
                                    if inv_m:
                                        for field in ('vendor', 'model', 'software_version'):
                                            incoming = inv_m.get(field)
                                            if (not _identity_value_missing(incoming)
                                                    and _identity_value_missing(modem.get(field))):
                                                modem[field] = incoming
                                        for field in ('fiber_node', 'cable_mac'):
                                            incoming = inv_m.get(field)
                                            if incoming and not modem.get(field):
                                                modem[field] = incoming
                                        for field in ('ofdm_ifindex', 'ofdma_ifindex',
                                                      'ofdma_rf_port_ifindex'):
                                            if (_positive_index(inv_m.get(field))
                                                    and not _positive_index(modem.get(field))):
                                                modem[field] = inv_m[field]
                                        for field in ('ofdm_channels', 'ofdma_channels',
                                                      'ofdm', 'ofdma'):
                                            if (_positive_channels(inv_m.get(field))
                                                    and not _positive_channels(modem.get(field))):
                                                modem[field] = inv_m[field]
                                        incoming_interface = str(inv_m.get('upstream_interface') or '').strip()
                                        current_interface = str(modem.get('upstream_interface') or '').strip()
                                        if incoming_interface and (
                                                not current_interface
                                                or ('ofdma' in incoming_interface.lower()
                                                    and 'ofdma' not in current_interface.lower())):
                                            modem['upstream_interface'] = incoming_interface
                                        modem['cpe_ipv4'] = inv_m.get('cpe_ipv4') or []
                                        modem['cpe_ipv6'] = inv_m.get('cpe_ipv6') or []
                                except Exception:
                                    pass
                            _normalize_modem_capability(modem, inv_m)
                            _backfill_topology(modem)
                            return jsonify({
                                "status": "success",
                                "modem": modem
                            })
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis search error: {e}")

    # Fallback to PyPNM inventory snapshot (pass bare hex so DB REPLACE works)
    try:
        modem_resp = PyPNMClient().get_inventory_modem_by_mac(mac_bare, request_timeout=10)
        modem = modem_resp.get('modem')
        if modem:
            _normalize_modem_capability(modem)
            _backfill_topology(modem)
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
        topo_resp = PyPNMClient().get_topology_modem_by_mac(mac_bare, request_timeout=10)
        topo_modem = topo_resp.get('modem') if isinstance(topo_resp, dict) else None
        if topo_modem:
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
    """Return persisted CMTS inventory first; discover live only when explicitly needed."""
    logger = logging.getLogger(__name__)

    cmts = CMTSProvider.get_cmts_by_hostname(cmts_name)
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
    modem_community = _first_community(
        request.args.get('modem_community'),
        get_default_community(),
    )
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'

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

        # Redis accelerates reads, but it is not the inventory authority. Read
        # canonical hostname first and then the configured-IP alias.
        cache_candidate = None
        if REDIS_AVAILABLE and redis_client and not force_refresh:
            revisions = _inventory_revision_map()
            seen_keys = set()
            for cache_ref in (canonical_name, cmts_ip):
                cache_key = f"modems:{cache_ref}"
                if cache_key in seen_keys:
                    continue
                seen_keys.add(cache_key)
                try:
                    data = _read_modem_cache(cache_key, revisions)
                    if not data:
                        continue
                    cached_rows = filter_ignored_modems(data.get('modems') or [])
                    if not cached_rows:
                        continue
                    cache_candidate = (cached_rows, data)
                    cached_limit = _bounded_modem_limit(
                        data.get('cache_query_limit'), default=0
                    ) if data.get('cache_query_limit') else 0
                    try:
                        authoritative_row_count = int(data.get('row_count'))
                    except (TypeError, ValueError):
                        authoritative_row_count = len(cached_rows)
                    cache_contains_complete_generation = (
                        authoritative_row_count <= len(cached_rows)
                    )
                    cache_covers_request = (
                        (
                            data.get('complete') is True
                            and data.get('truncated') is not True
                            and cache_contains_complete_generation
                        )
                        or cached_limit == 0
                        or cached_limit >= limit
                    )
                    if cache_covers_request:
                        rows = _prepare_rows(cached_rows)
                        logger.info(
                            "Returning %d persisted modems from Redis key %s",
                            len(rows), cache_key,
                        )
                        return _success_response(rows, data, 'cached', True)
                    # A smaller partial cache is retained as a fallback while
                    # the authoritative persisted inventory is queried below.
                    break
                except Exception as exc:
                    logger.warning("Redis cache read error for %s: %s", cache_key, exc)

        # Query authoritative persisted inventory by canonical hostname and then
        # configured IP. Age, completeness, truncation, and identity metadata do
        # not invalidate rows.
        if not force_refresh:
            client = PyPNMClient()
            seen_refs = set()
            for inventory_ref in (canonical_name, cmts_ip):
                normalized_ref = str(inventory_ref or '').strip()
                if not normalized_ref or normalized_ref.lower() in seen_refs:
                    continue
                seen_refs.add(normalized_ref.lower())
                try:
                    inventory_resp = client.get_inventory_modems(
                        cmts=normalized_ref,
                        limit=limit,
                    )
                except Exception as exc:
                    logger.warning(
                        "Persisted inventory lookup failed for %s: %s",
                        normalized_ref, exc,
                    )
                    continue
                inventory_rows = inventory_resp.get('modems') or []
                if not inventory_rows:
                    continue
                rows = _prepare_rows(inventory_rows)
                inventory_resp.setdefault('source', 'pypnm-inventory')
                _backfill_redis_from_inventory(
                    rows,
                    requested_limit=limit,
                    metadata=inventory_resp,
                )
                logger.info(
                    "Returning %d persisted modems for %s via inventory key %s",
                    len(rows), canonical_name, normalized_ref,
                )
                return _success_response(rows, inventory_resp, 'inventory', True)

            if cache_candidate:
                cached_rows, data = cache_candidate
                rows = _prepare_rows(cached_rows)
                logger.info(
                    "Returning %d partial Redis rows for %s after persisted lookup miss",
                    len(rows), canonical_name,
                )
                return _success_response(rows, data, 'cached', True)

        # Live base discovery is reserved for refresh=true or genuinely absent
        # persisted inventory. Forward refresh so PyPNM owns that policy.
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
        if modem_community is not None:
            live_query['modem_community'] = modem_community
        result = client.get_cmts_modems(**live_query)

        if result.get('success'):
            rows = _prepare_rows(result.get('modems') or [])
            result.setdefault('source', 'pypnm-live')
            if rows:
                _redis_cache_modems_for_key(
                    f"modems:{canonical_name}", canonical_name, rows,
                    requested_limit=limit,
                    metadata=result,
                )
                if cmts_ip != canonical_name:
                    _redis_cache_modems_for_key(
                        f"modems:{cmts_ip}", canonical_name, rows,
                        requested_limit=limit,
                        metadata=result,
                    )
            logger.info(
                "Retrieved %d modems from %s via PyPNM live query",
                len(rows), canonical_name,
            )
            return _success_response(rows, result, result.get('agent_id', 'agent'), False)

        error_value = result.get('error') or result.get('message') or 'Unknown error from PyPNM API'
        error_msg = json.dumps(error_value, default=str) if isinstance(error_value, (dict, list)) else str(error_value)
        logger.error(f"PyPNM API error for {canonical_name}: {error_msg}")
        return jsonify({"status": "error", "message": error_msg}), 500

    except Exception as exc:
        logger.exception("Error getting modems from %s", cmts_name)
        return jsonify({"status": "error", "message": str(exc)}), 500


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


@api_bp.route('/cmts/<cmts_name>/cache/refresh', methods=['POST'])
def refresh_cmts_modem_cache(cmts_name):
    """Re-pull enriched modem data from PyPNM inventory and rewrite Redis.

    Called fire-and-forget by the frontend when enrichment completes, so that
    cable_mac / fiber_node fields are present in the Redis cache for subsequent
    modem searches without waiting for the next full CMTS modem load.
    """
    _log = logging.getLogger(__name__)
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "skipped", "reason": "Redis not available"})
    try:
        default_limit = _cm_modem_limit_default()
        inv_resp = PyPNMClient().get_inventory_modems(cmts=cmts_name, limit=default_limit)
        inv_modems = filter_ignored_modems(inv_resp.get('modems') or [])
        if not inv_modems:
            return jsonify({"status": "skipped", "reason": "no inventory modems yet"})
        for m in inv_modems:
            m.setdefault('cmts', cmts_name)
        _backfill_redis_from_inventory(
            inv_modems,
            requested_limit=inv_resp.get('requested_limit') or default_limit,
            metadata=inv_resp,
        )
        _log.info(f"cache/refresh: wrote {len(inv_modems)} enriched modems to Redis for {cmts_name}")
        return jsonify({"status": "success", "count": len(inv_modems)})
    except Exception as exc:
        _log.warning(f"cache/refresh failed for {cmts_name}: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500


@api_bp.route('/cmts/<cmts_name>/enrich/delta', methods=['POST'])
def enqueue_delta_enrichment(cmts_name):
    """Queue refresh only for modems missing enrichment fields in current CMTS cache."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503

    payload = request.get_json(silent=True) or {}
    try:
        max_batch = max(1, min(int(payload.get('max_batch') or 25), 25))
    except (TypeError, ValueError):
        max_batch = 25

    cache_key = f"modems:{cmts_name}"
    data = _read_modem_cache(cache_key, _inventory_revision_map())
    if not data:
        return jsonify({"status": "error", "message": f"No current cached modems for {cmts_name}"}), 404

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
        count = 0
        batch = []
        for key in redis_client.scan_iter(match="modems:*", count=500):
            batch.append(key)
            if len(batch) >= 500:
                count += redis_client.delete(*batch)
                batch = []
        if batch:
            count += redis_client.delete(*batch)
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

