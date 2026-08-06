# PyPNM Web GUI - API Routes

import os
import re
import json
import ipaddress
import logging
import time
import threading
import uuid
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
                m['cmts_community'] = community
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


def _cm_modem_limit_default() -> int:
    value = current_app.config.get('CM_MODEM_LIMIT', os.environ.get('CM_MODEM_LIMIT', 50000))
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 50000
    except (TypeError, ValueError):
        return 50000

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
    # Hard safety cap: modem data must never survive more than 24 hours,
    # even if REDIS_TTL is accidentally configured to a larger value.
    REDIS_TTL = max(1, min(int(os.environ.get('REDIS_TTL', '86400')), 86400))
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    print(f"[INFO] Redis cache connected: {REDIS_HOST}:{REDIS_PORT}", flush=True)
except Exception as e:
    REDIS_AVAILABLE = False
    redis_client = None
    print(f"[WARNING] Redis not available: {e}", flush=True)


_CPE_REDIS_KEY = 'cpe:ip-index:v1'
_CPE_REDIS_TTL = 1800
_cpe_cache_lock = threading.Lock()


def _normalize_cpe_query(value: str) -> dict:
    query = str(value or '').strip()
    if not query:
        raise ValueError('CPE address is required')
    if ':' in query:
        try:
            address = ipaddress.ip_address(query)
        except ValueError as exc:
            raise ValueError('Enter a complete valid IPv6 address') from exc
        if address.version != 6:
            raise ValueError('Enter a complete valid IPv6 address')
        return {'family': 'ipv6', 'value': address.compressed, 'prefix': False}

    trailing_dot = query.endswith('.')
    parts = query[:-1].split('.') if trailing_dot else query.split('.')
    if not 1 <= len(parts) <= 4 or any(not part.isdigit() for part in parts):
        raise ValueError('Enter a valid dotted IPv4 address prefix')
    octets = [int(part) for part in parts]
    if any(not 0 <= octet <= 255 for octet in octets):
        raise ValueError('IPv4 prefix octets must be between 0 and 255')
    if len(octets) == 4 and not trailing_dot:
        return {'family': 'ipv4', 'value': str(ipaddress.ip_address(query)), 'prefix': False}
    if len(octets) == 4:
        raise ValueError('A complete IPv4 address cannot end with a dot')
    return {
        'family': 'ipv4',
        'value': '.'.join(str(o) for o in octets) + '.',
        'prefix': True,
    }


def warm_cpe_search_cache(force: bool = False) -> bool:
    """Warm a separate CPE address-to-CM Redis hash from persisted rows."""
    if not REDIS_AVAILABLE or not redis_client:
        return False
    if not force and redis_client.exists(_CPE_REDIS_KEY):
        return True
    with _cpe_cache_lock:
        if not force and redis_client.exists(_CPE_REDIS_KEY):
            return True
        response = PyPNMClient().get_inventory_cpe_index(request_timeout=30)
        rows = response.get('rows') or []
        if (response.get('status') != 'success'
                or response.get('truncated') is True
                or int(response.get('row_count') or 0) != len(rows)):
            return False
        grouped: dict[str, set[str]] = {}
        for row in rows:
            try:
                address = ipaddress.ip_address(str(row.get('ip_address') or '')).compressed
            except ValueError:
                return False
            mac = str(row.get('modem_mac') or '').strip().lower()
            if not mac:
                return False
            grouped.setdefault(address, set()).add(mac)
        temp_key = f'{_CPE_REDIS_KEY}:build:{uuid.uuid4().hex}'
        pipe = redis_client.pipeline(transaction=False)
        pipe.hset(temp_key, '__empty__', '[]')
        for address, macs in grouped.items():
            pipe.hset(temp_key, address, json.dumps(sorted(macs)))
        pipe.expire(temp_key, _CPE_REDIS_TTL)
        pipe.execute()
        redis_client.rename(temp_key, _CPE_REDIS_KEY)
        logger.info('Warmed CPE Redis index with %s addresses', len(grouped))
        return True


def _cpe_cached_matches(
    value: str,
    max_macs: int = 50000,
) -> tuple[set[str], list[str], bool]:
    normalized = _normalize_cpe_query(value)
    if not warm_cpe_search_cache():
        return set(), [], False
    if normalized['prefix']:
        iterator = redis_client.hscan_iter(_CPE_REDIS_KEY, match=f"{normalized['value']}*")
    else:
        payload = redis_client.hget(_CPE_REDIS_KEY, normalized['value'])
        iterator = [(normalized['value'], payload)] if payload else []
    macs: set[str] = set()
    addresses: list[str] = []
    truncated = False
    for address, payload in iterator:
        if address == '__empty__':
            continue
        addresses.append(str(address))
        try:
            macs.update(json.loads(payload or '[]'))
        except (TypeError, json.JSONDecodeError):
            continue
        if len(macs) >= max_macs:
            truncated = True
            break
    return macs, sorted(set(addresses)), truncated


def _redis_cache_modems_for_key(
    cache_key: str,
    cmts_name: str,
    modems: list[dict],
    requested_limit: int | None = None,
    *,
    capability_enriched: bool = False,
    complete: bool = False,
    truncated: bool = False,
    collected_at=None,
    inventory_revision=None,
    critical_oid_errors: dict | None = None,
) -> None:
    if not REDIS_AVAILABLE or not redis_client or not cache_key:
        return
    if requested_limit is None:
        requested_limit = _cm_modem_limit_default()
    try:
        modems = filter_ignored_modems(modems)
        payload_data = {
            "cmts": cmts_name,
            "requested_limit": requested_limit,
            "modems": modems,
            "timestamp": int(time.time()),
            "source": "pypnm-inventory",
            "capability_enriched": capability_enriched is True,
            "complete": complete is True,
            "truncated": truncated is True,
            "collected_at": collected_at,
            "inventory_revision": inventory_revision,
            "critical_oid_errors": critical_oid_errors or {},
        }
        ttl = _cache_remaining_ttl(payload_data)
        if ttl <= 0:
            redis_client.delete(cache_key)
            logger.info("Skipped stale modem cache write for %s", cache_key)
            return
        redis_client.setex(cache_key, ttl, json.dumps(payload_data))
    except Exception as exc:
        logger.warning(f"Redis modem cache write error for {cache_key}: {exc}")


def _backfill_redis_from_inventory(
    modems: list[dict],
    requested_limit: int | None = None,
    *,
    capability_enriched: bool = False,
    complete: bool = False,
    truncated: bool = False,
    collected_at=None,
    inventory_revision=None,
    critical_oid_errors: dict | None = None,
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

    def _group_cache_metadata(rows: list[dict]):
        if collected_at is not None:
            return collected_at, inventory_revision
        timestamps = [
            _parse_inventory_timestamp(row.get("updated_at"))
            for row in rows
            if isinstance(row, dict)
        ]
        timestamps = [value for value in timestamps if value is not None]
        if not timestamps:
            return None, inventory_revision
        # The dataset is only as fresh as its oldest row, while its revision
        # is the newest row change represented by this payload.
        return min(timestamps).isoformat(), inventory_revision or max(timestamps).isoformat()

    for group_name, rows in grouped.items():
        group_collected_at, group_revision = _group_cache_metadata(rows)
        _redis_cache_modems_for_key(
            f"modems:{group_name}",
            group_name,
            rows,
            requested_limit=requested_limit,
            capability_enriched=capability_enriched,
            complete=complete,
            truncated=truncated,
            collected_at=group_collected_at,
            inventory_revision=group_revision,
            critical_oid_errors=critical_oid_errors,
        )

    for alias_key, group_name in aliases.items():
        rows = grouped.get(group_name) or []
        if rows:
            group_collected_at, group_revision = _group_cache_metadata(rows)
            _redis_cache_modems_for_key(
                f"modems:{alias_key}",
                group_name,
                rows,
                requested_limit=requested_limit,
                capability_enriched=capability_enriched,
                complete=complete,
                truncated=truncated,
                collected_at=group_collected_at,
                inventory_revision=group_revision,
                critical_oid_errors=critical_oid_errors,
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


def _cache_reference_time(payload: dict):
    return _parse_inventory_timestamp(payload.get("collected_at")) or _parse_inventory_timestamp(
        payload.get("timestamp")
    )


def _cache_remaining_ttl(payload: dict) -> int:
    """Cap Redis lifetime at 24 hours from authoritative collection time."""
    reference = _cache_reference_time(payload)
    if reference is None:
        # Legacy payloads are still bounded by their existing Redis TTL.
        return REDIS_TTL
    age = max(0.0, (datetime.now(timezone.utc) - reference).total_seconds())
    return max(0, min(REDIS_TTL, int(REDIS_TTL - age)))


def _inventory_revision_map() -> dict[str, datetime]:
    """Load lightweight CMTS revisions; fail open if PyPNM is unavailable."""
    revisions: dict[str, datetime] = {}
    try:
        response = PyPNMClient().get_inventory_snapshots(request_timeout=5)
        for snapshot in response.get("snapshots") or []:
            revision = _parse_inventory_timestamp(
                snapshot.get("revision_at") or snapshot.get("collected_at")
            )
            if revision is None:
                continue
            for alias in (snapshot.get("cmts"), snapshot.get("cmts_ip")):
                key = str(alias or "").strip().lower()
                if key:
                    revisions[key] = revision
    except Exception as exc:
        logger.warning("Inventory revision lookup skipped: %s", exc)
    return revisions


def _cache_payload_is_current(payload: dict, revisions: dict[str, datetime] | None = None) -> bool:
    if _cache_remaining_ttl(payload) <= 0:
        return False
    if not revisions:
        return True

    aliases = [str(payload.get("cmts") or "").strip().lower()]
    modems = payload.get("modems") or []
    if modems and isinstance(modems[0], dict):
        aliases.append(str(modems[0].get("cmts_ip") or "").strip().lower())
    current = max((revisions[a] for a in aliases if a in revisions), default=None)
    if current is None:
        return True

    cached_revision = _parse_inventory_timestamp(payload.get("inventory_revision"))
    cached_revision = cached_revision or _cache_reference_time(payload)
    return cached_revision is not None and current <= cached_revision


def _read_modem_cache(cache_key: str, revisions: dict[str, datetime] | None = None):
    """Read a valid modem cache payload and delete stale generations."""
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
        if redis_client:
            redis_client.delete(cache_key)
        logger.info("Invalidated stale modem cache key %s", cache_key)
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
    cable_mac = str(modem.get('cable_mac') or '').strip()
    return (
        _identity_value_missing(modem.get('vendor'))
        or _identity_value_missing(modem.get('software_version') or modem.get('firmware'))
        or not cable_mac
    )


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

    # CPE lookup is a CM search only. The separate Redis index resolves the
    # address to modem MACs; indexed bulk inventory lookup supplies list rows
    # without exposing CPE addresses outside the detail endpoint.
    if search_type == 'cpe_ip':
        if not search_value:
            return jsonify({'status': 'error', 'message': 'CPE address is required'}), 400
        try:
            _normalize_cpe_query(search_value)
        except ValueError as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 400

        try:
            matched_macs, _, matches_truncated = _cpe_cached_matches(search_value)
            if (
                not matches_truncated
                and REDIS_AVAILABLE
                and redis_client
                and redis_client.exists(_CPE_REDIS_KEY)
            ):
                modems = []
                client = PyPNMClient()
                ordered_macs = sorted(matched_macs)
                for offset in range(0, len(ordered_macs), 5000):
                    response = client.get_inventory_modems_bulk(
                        ordered_macs[offset:offset + 5000]
                    )
                    if response.get('status') != 'success':
                        raise RuntimeError(response.get('message') or 'Inventory lookup failed')
                    modems.extend(response.get('modems') or [])
                modems = filter_ignored_modems(modems)
                if cmts_filter:
                    expected = cmts_filter.lower()
                    modems = [
                        modem for modem in modems
                        if expected in {
                            str(modem.get('cmts') or '').lower(),
                            str(modem.get('cmts_ip') or '').lower(),
                        }
                    ]
                if iface_filter:
                    modems = [
                        modem for modem in modems
                        if any(iface_filter in str(modem.get(field) or '').lower()
                               for field in ('interface', 'cmts_interface',
                                             'upstream_interface', 'cable_mac'))
                    ]
                _augment_modems_with_topology_fields(modems)
                modems.sort(key=lambda modem: (
                    str(modem.get('cmts') or ''), str(modem.get('mac_address') or '')
                ))
                return jsonify({
                    'status': 'success', 'modems': modems, 'count': len(modems),
                    'cached': True, 'source': 'cpe-redis-index',
                })
        except Exception as exc:
            logger.warning('CPE Redis lookup falling back to MySQL: %s', exc)

        try:
            response = PyPNMClient().get_inventory_modems(
                cmts=cmts_filter or None,
                search_type='cpe_ip',
                search_value=search_value,
                interface=iface_filter or None,
                limit=_cm_modem_limit_default(),
            )
            if response.get('status') != 'success':
                return jsonify({
                    'status': 'error',
                    'message': response.get('message') or 'CPE inventory search failed',
                }), 503
            modems = filter_ignored_modems(response.get('modems') or [])
            _augment_modems_with_topology_fields(modems)
            return jsonify({
                'status': 'success', 'modems': modems, 'count': len(modems),
                'cached': False, 'source': 'pypnm-inventory',
            })
        except Exception as exc:
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

    # MySQL inventory fallback path when Redis is unavailable.
    if not REDIS_AVAILABLE or not redis_client:
        try:
            default_limit = _cm_modem_limit_default()
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
        keys = [f"modems:{cmts_filter}"] if cmts_filter else list(redis_client.scan_iter('modems:*'))
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
            default_limit = _cm_modem_limit_default()
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
                    capability_enriched=db_resp.get('capability_enriched') is True,
                    complete=(
                        db_resp.get('complete') is True
                        and db_resp.get('truncated') is not True
                    ),
                    truncated=db_resp.get('truncated') is True,
                    collected_at=db_resp.get('collected_at'),
                    inventory_revision=db_resp.get('revision_at'),
                    critical_oid_errors=db_resp.get('critical_oid_errors') or {},
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

        if not modems and search_type == 'mac' and search_value:
            mac_fallback = _fallback_for_mac(search_value)
            if mac_fallback is not None:
                return mac_fallback

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


@api_bp.route('/modems/cpe-suggestions', methods=['GET'])
def get_cpe_suggestions():
    """Suggest CPE addresses for the CM search box."""
    query = (request.args.get('q') or '').strip()
    try:
        limit = max(1, min(int(request.args.get('limit') or 10), 50))
    except (TypeError, ValueError):
        limit = 10
    if not query:
        return jsonify({'status': 'success', 'suggestions': []})
    try:
        _, suggestions, _ = _cpe_cached_matches(query)
        if REDIS_AVAILABLE and redis_client and redis_client.exists(_CPE_REDIS_KEY):
            return jsonify({
                'status': 'success', 'suggestions': suggestions[:limit], 'cached': True,
            })
    except ValueError:
        return jsonify({'status': 'success', 'suggestions': []})
    except Exception as exc:
        logger.warning('CPE suggestion Redis fallback: %s', exc)
    try:
        response = PyPNMClient().get_inventory_cpe_suggestions(query, limit=limit)
        return jsonify({
            'status': response.get('status', 'success'),
            'suggestions': (response.get('suggestions') or [])[:limit],
            'cached': False,
        })
    except Exception:
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

    # Try to find in Redis cache first
    if REDIS_AVAILABLE and redis_client:
        try:
            revisions = _inventory_revision_map()
            keys = list(redis_client.scan_iter('modems:*'))
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
    limit = int(request.args.get('limit', _cm_modem_limit_default()))
    enrich = request.args.get('enrich', 'false').lower() == 'true'
    modem_community = request.args.get('modem_community') or get_default_community()
    if not request.args.get('modem_community'):
        logger.warning("modem_community not provided for %s — using configured default", cmts_name)
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    # Some consumers (notably the Fiber Node modem selector) can use a
    # non-empty cached inventory even when an older agent cannot prove that
    # every source OID walk completed. Full inventory searches keep the strict
    # completeness requirement.
    allow_partial_cache = (
        request.args.get('allow_partial', 'false').lower() == 'true'
        and not enrich
    )
    
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
                revisions = _inventory_revision_map()
                data = _read_modem_cache(cache_key, revisions)
                if data:
                    cached_modems = filter_ignored_modems(data.get('modems', []))
                    cached_count = len(cached_modems)
                    cached_requested_limit = int(data.get('requested_limit') or 0)
                    cached_source = str(data.get('source') or '')
                    cached_complete = data.get('complete') is True
                    cache_limit_mismatch = not (
                        cached_count >= limit
                        or (
                            cached_complete
                            and data.get('truncated') is not True
                        )
                    )
                    cache_needs_enrich = False

                    # A complete, non-truncated walk proves that the CMTS had
                    # fewer rows than the configured safety cap. Row count alone
                    # is only needed for explicitly limited partial responses.
                    if cache_limit_mismatch:
                        logger.info(
                            f"Using partial Redis cache for {cmts_name}: "
                            f"cached_count={cached_count}, cached_limit={cached_requested_limit}, "
                            f"requested_limit={limit}, source={cached_source or 'unknown'}"
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
                            f"Redis cache for {cmts_name} is not enriched; live enrichment state must be fetched from PyPNM."
                        )

                    # Never serve a cache that does not cover the requested
                    # inventory footprint unless the caller explicitly accepts
                    # a non-empty partial inventory. Enrichment quality matters
                    # only when enrichment was requested.
                    serve_partial_cache = allow_partial_cache and cached_count > 0
                    if (
                        (cache_limit_mismatch and not serve_partial_cache)
                        or (enrich and cache_needs_enrich)
                    ):
                        logger.info(
                            f"Bypassing Redis cache for {cmts_name} "
                            f"(partial={cache_limit_mismatch}, needs_enrich={cache_needs_enrich})"
                        )
                        raise RuntimeError("bypass-redis-incomplete-cache")
                    if serve_partial_cache and cache_limit_mismatch:
                        logger.info(
                            f"Serving accepted partial Redis cache for {cmts_name}: "
                            f"cached_count={cached_count}, requested_limit={limit}"
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

                    response_modems = cached_modems[:limit] if limit else cached_modems
                    logger.info(
                        f"Returning {len(response_modems)}/{cached_count} modems from Redis cache for {cmts_name} "
                        f"(enriched={cache_is_enriched}, partial={cache_limit_mismatch or cache_needs_enrich})"
                    )
                    return jsonify({
                        "status": "success",
                        "cmts": cmts_name,
                        "cmts_hostname": cmts_name,
                        "cmts_ip": cmts_ip,
                        "agent_id": "cached",
                        "modems": response_modems,
                        "count": cached_count,
                        "enriched": cache_is_enriched,
                        "capability_enriched": data.get('capability_enriched') is True,
                        "cached": True,
                        "enriching": bool(cache_needs_enrich),
                        "complete": cached_complete,
                        "truncated": data.get('truncated') is True,
                        "partial": bool(not cached_complete or data.get('truncated') is True or cache_limit_mismatch),
                        "cached_requested_limit": cached_requested_limit,
                        "requested_limit": cached_requested_limit,
                        "source": data.get('source'),
                        "collected_at": data.get('collected_at'),
                        "critical_oid_errors": data.get('critical_oid_errors') or {},
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
                inventory_complete = (
                    inventory_resp.get('complete') is True
                    and inventory_resp.get('truncated') is not True
                )
                inventory_covers_request = (
                    inventory_complete
                    or limit <= 200
                    or len(inventory_modems) >= limit
                )
                if (
                    inventory_modems
                    and inventory_covers_request
                    and _inventory_snapshot_is_fresh(inventory_modems)
                ):
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
                        _backfill_redis_from_inventory(
                            inventory_modems,
                            requested_limit=inventory_resp.get('requested_limit') or limit,
                            capability_enriched=inventory_resp.get('capability_enriched') is True,
                            complete=inventory_complete,
                            truncated=inventory_resp.get('truncated') is True,
                            collected_at=inventory_resp.get('collected_at'),
                            inventory_revision=inventory_resp.get('revision_at'),
                            critical_oid_errors=inventory_resp.get('critical_oid_errors') or {},
                        )
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
                            "capability_enriched": inventory_resp.get('capability_enriched') is True,
                            "cached": True,
                            "enriching": False,
                            "source": inventory_resp.get('source') or "pypnm-inventory",
                            "complete": inventory_complete,
                            "truncated": inventory_resp.get('truncated') is True,
                            "partial": not inventory_complete,
                            "requested_limit": inventory_resp.get('requested_limit'),
                            "collected_at": inventory_resp.get('collected_at'),
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
            refresh=force_refresh,
            modem_community=modem_community,
            cmts_hostname=cmts_name,
        )
        
        if result.get('success'):
            raw_modems = result.get('modems', [])
            returned_row_count = len(raw_modems)
            modems = filter_ignored_modems(raw_modems)
            logger.info(f"Retrieved {len(modems)} modems from {cmts_name} via PyPNM API/agent")

            # Stamp CMTS fields onto every modem record.
            for m in modems:
                m['cmts'] = cmts_name
                m['cmts_ip'] = cmts_ip
                m['cmts_community'] = community

            _augment_modems_with_topology_fields(modems, cmts_name=cmts_name)

            is_enriched = result.get('enriched', False)
            is_enriching = result.get('enriching', False)
            # A complete upstream generation may still be sliced to this
            # endpoint's requested preview limit. Do not label that sliced
            # Redis payload as a complete inventory; the background full-load
            # request must be allowed to bypass it and retrieve every row.
            cache_contains_complete_generation = bool(
                result.get('complete') is True
                and returned_row_count < limit
            )

            # Cache successful modem data immediately so subsequent CMTS searches
            # can reuse inventory even while enrichment is still running.
            if REDIS_AVAILABLE and redis_client:
                try:
                    cache_payload = {
                        "cmts": cmts_name,
                        "requested_limit": result.get('requested_limit') or limit,
                        "modems": modems,
                        "timestamp": int(time.time()),
                        "enriched": is_enriched,
                        "enriching": is_enriching,
                        "capability_enriched": result.get('capability_enriched') is True,
                        "source": "pypnm-live" if result.get('source') == 'snmp-live' else (result.get('source') or 'pypnm-inventory'),
                        "complete": cache_contains_complete_generation,
                        "truncated": result.get('truncated') is True,
                        "collected_at": result.get('collected_at'),
                        "inventory_revision": result.get('revision_at'),
                        "critical_oid_errors": result.get('critical_oid_errors') or {},
                    }
                    ttl = _cache_remaining_ttl(cache_payload)
                    cache_keys = [f"modems:{cmts_name}"]
                    if cmts_ip and cmts_ip != cmts_name:
                        cache_keys.append(f"modems:{cmts_ip}")
                    if ttl > 0:
                        payload_json = json.dumps(cache_payload)
                        for cache_key in cache_keys:
                            redis_client.setex(cache_key, ttl, payload_json)
                        logger.info(
                            f"Cached {len(modems)} modems for {cmts_name} "
                            f"(enriched={is_enriched}, enriching={is_enriching}, TTL={ttl}s)"
                        )
                    else:
                        redis_client.delete(*cache_keys)
                        logger.info("Skipped stale modem cache write for %s", cmts_name)
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
                "capability_enriched": result.get('capability_enriched') is True,
                "cached": result.get('cached', False),
                "enriching": result.get('enriching', False),
                "source": result.get('source'),
                "complete": result.get('complete') is True,
                "truncated": result.get('truncated') is True,
                "partial": bool(
                    result.get('complete') is not True
                    or result.get('truncated') is True
                ),
                "requested_limit": result.get('requested_limit'),
                "collected_at": result.get('collected_at'),
                "critical_oid_errors": result.get('critical_oid_errors') or {},
                "raw_legacy_mac_count": result.get('raw_legacy_mac_count'),
                "raw_d3_mac_count": result.get('raw_d3_mac_count'),
                # PyPNM stores it as 'enrich_progress' — pass through under both names for compat
                "enrichment_progress": result.get('enrichment_progress') or result.get('enrich_progress'),
            })
        else:
            error_value = result.get('error') or result.get('message') or result.get('detail')
            if isinstance(error_value, (dict, list)):
                error_msg = json.dumps(error_value, default=str)
            else:
                error_msg = str(error_value or 'Unknown error from PyPNM API')
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

    # 3. Clear PyPNM MySQL inventory rows for this CMTS scope
    try:
        import requests
        pypnm_url = os.environ.get('PYPNM_BASE_URL', os.environ.get('PYPNM_API_URL', 'http://localhost:8000'))
        payload = {"cmts": cmts_name}
        cmts_info = CMTSProvider.get_cmts_by_hostname(cmts_name)
        cmts_ip = None
        if cmts_info:
            cmts_ip = cmts_info.get('IPAddress') or cmts_info.get('ip') or cmts_info.get('ip_address')
        if cmts_ip:
            payload["cmts_ip"] = cmts_ip
        inv_resp = requests.post(f"{pypnm_url}/api/admin/inventory/modems/clear", json=payload, timeout=8)
        if inv_resp.status_code == 200:
            inv_data = inv_resp.json() if inv_resp.content else {}
            deleted = int(inv_data.get('deleted') or 0)
            cleared.append(f"Inventory rows ({deleted} deleted)")
    except Exception as e:
        logger.warning(f"Inventory cache clear error: {e}")

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
            capability_enriched=inv_resp.get('capability_enriched') is True,
            complete=(
                inv_resp.get('complete') is True
                and inv_resp.get('truncated') is not True
            ),
            truncated=inv_resp.get('truncated') is True,
            collected_at=inv_resp.get('collected_at'),
            inventory_revision=inv_resp.get('revision_at'),
            critical_oid_errors=inv_resp.get('critical_oid_errors') or {},
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
    max_batch = max(1, min(int(payload.get('max_batch') or 10), 25))

    data = _read_modem_cache(
        f"modems:{cmts_name}",
        _inventory_revision_map(),
    )
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

