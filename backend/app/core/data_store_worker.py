import json
import logging
import os
import threading
import time
import fcntl
from datetime import datetime, timedelta

from app.core.cmts_provider import CMTSProvider
from app.core.data_store_db import data_store_db
from app.core.modem_filters import filter_ignored_modems, is_ignored_modem_ip
from app.core.pypnm_client import PyPNMClient

logger = logging.getLogger(__name__)

_worker_started = False
_refresh_threads = []
_poller_threads = []
_scheduler_thread = None
_scheduler_started = False
_leader_lock_fd = None
_scheduler_last_tick = None
_scheduler_enabled_override = None
_scheduler_poll_sec_override = None
_scheduler_last_agent_load = None
_scheduler_last_decisions = []


def _effective_scheduler_enabled():
    if _scheduler_enabled_override is not None:
        return bool(_scheduler_enabled_override)
    return os.environ.get("DATA_STORE_SCHEDULER_ENABLED", "true").lower() == "true"


def _effective_scheduler_poll_sec():
    if _scheduler_poll_sec_override is not None:
        return int(_scheduler_poll_sec_override)
    return int(os.environ.get("DATA_STORE_SCHEDULER_POLL_SEC", "60"))


def _extract_scqam_payload(modem_row):
    # Keep broad key support to tolerate schema differences from agents/PyPNM.
    keys = [
        "downstream", "upstream", "scqam", "scqam_levels", "levels",
        "downstream_power", "upstream_power", "snr", "mer",
    ]
    out = {}
    for k in keys:
        v = modem_row.get(k)
        if v is not None:
            out[k] = v
    return out


def _extract_rxmer_payload(modem_row):
    keys = [
        "rxmer", "rx_mer", "rxmer_avg", "rx_mer_avg",
        "rxmer_data", "rx_mer_data", "ofdma_rxmer", "ofdm_rxmer",
    ]
    out = {}
    for k in keys:
        v = modem_row.get(k)
        if v is not None:
            out[k] = v
    return out


def _is_error_response(resp):
    if resp is None:
        return True
    if isinstance(resp, dict):
        if str(resp.get("status", "")).lower() == "error":
            return True
        if resp.get("success") is False:
            return True
    return False


def _collect_modem_heavy_rf(client, modem, modem_community, tftp_ipv4, collect_scqam, collect_rxmer):
    mac = modem.get("mac_address")
    ip = modem.get("ip_address")
    if not mac or not ip:
        return None

    scqam_payload = None
    rxmer_payload = None

    if collect_scqam:
        scqam_resp = client.get_ds_scqam_stats(mac_address=mac, ip_address=ip, community=modem_community)
        if not _is_error_response(scqam_resp):
            scqam_payload = scqam_resp

    if collect_rxmer:
        rxmer_resp = client.get_rxmer_capture(
            mac_address=mac,
            ip_address=ip,
            tftp_ipv4=tftp_ipv4,
            community=modem_community,
            output_type="json",
        )
        if not _is_error_response(rxmer_resp):
            rxmer_payload = rxmer_resp

    if scqam_payload is None and rxmer_payload is None:
        return None
    return {
        "scqam_json": json.dumps(scqam_payload) if scqam_payload is not None else None,
        "rxmer_json": json.dumps(rxmer_payload) if rxmer_payload is not None else None,
    }


def _cmts_targets_for_poller(poller):
    scope_type = (poller.get("scope_type") or "all_cmts").lower()
    if scope_type == "all_cmts":
        all_cmts = CMTSProvider.get_all_cmts()
        return [
            {
                "name": c.get("HostName") or c.get("hostname") or c.get("name"),
                "ip": c.get("IPAddress") or c.get("ip") or c.get("ip_address"),
            }
            for c in all_cmts
            if (c.get("IPAddress") or c.get("ip") or c.get("ip_address"))
        ]

    raw_scope = poller.get("scope_json")
    if not raw_scope:
        return []
    try:
        scope = json.loads(raw_scope) if isinstance(raw_scope, str) else raw_scope
    except Exception:
        logger.warning("Invalid scope_json in poller id=%s", poller.get("id"))
        return []

    targets = []
    if isinstance(scope, list):
        for item in scope:
            if isinstance(item, str):
                by_name = CMTSProvider.get_cmts_by_hostname(item)
                by_ip = CMTSProvider.get_cmts_by_ip(item)
                src = by_name or by_ip
                if src:
                    targets.append({
                        "name": src.get("HostName") or item,
                        "ip": src.get("IPAddress") or item,
                    })
            elif isinstance(item, dict):
                ip = item.get("ip") or item.get("cmts_ip") or item.get("IPAddress")
                name = item.get("name") or item.get("hostname") or item.get("HostName") or ip
                if ip:
                    targets.append({"name": name, "ip": ip})
    return targets


def _run_poller_job(job):
    poller = data_store_db.get_poller_setting_by_id(job.get("poller_id"))
    if not poller:
        data_store_db.complete_job(job.get("id"), rows_collected=0, error_text="Poller not found")
        return

    if not int(poller.get("enabled", 1)):
        data_store_db.complete_job(job.get("id"), rows_collected=0, error_text="Poller disabled")
        return

    targets = _cmts_targets_for_poller(poller)
    if not targets:
        data_store_db.complete_job(job.get("id"), rows_collected=0, error_text="No CMTS targets")
        return

    total_targets = len(targets)
    start_offset = int(poller.get("last_target_offset") or 0) % total_targets
    if start_offset:
        targets = targets[start_offset:] + targets[:start_offset]

    community = os.environ.get("CMTS_COMMUNITY", os.environ.get("CMTS_SNMP_COMMUNITY", "public"))
    modem_community = os.environ.get("MODEM_COMMUNITY", os.environ.get("CM_SNMP_COMMUNITY", "private"))
    tftp_ipv4 = os.environ.get("TFTP_IPV4", "127.0.0.1")
    heavy_max_modems = max(1, int(poller.get("heavy_max_modems") or 300))
    heavy_delay_ms = max(0, int(poller.get("heavy_delay_ms") or 0))

    modems_attempted = 0
    modems_succeeded = 0
    modems_failed = 0

    now_local = datetime.now()
    heavy_allowed = True

    env_runtime_default = int(os.environ.get("DATA_STORE_JOB_MAX_RUNTIME_SEC", "14400"))
    poller_runtime = poller.get("max_runtime_sec")
    max_runtime_sec = int(poller_runtime) if poller_runtime is not None else env_runtime_default
    if max_runtime_sec > 0:
        max_runtime_sec = max(60, max_runtime_sec)
        job_deadline = time.monotonic() + max_runtime_sec
    else:
        # 0 disables runtime timeout for very large CMTS batches.
        job_deadline = None

    cmts_breakdown = {}  # {cmts_name: {rows, failed, error}}

    client = PyPNMClient()
    total_written = 0
    rf_snapshots = []
    timeout_hit = False
    cancelled = False
    processed_targets = 0
    # Check cancellation every N targets to avoid hammering the DB.
    _cancel_check_interval = 3
    for t in targets:
        cmts_ip = t.get("ip")
        cmts_name = t.get("name") or cmts_ip
        if not cmts_ip:
            continue
        if job_deadline is not None and time.monotonic() >= job_deadline:
            logger.warning("Job %s exceeded max runtime (%ss) — stopping early", job.get("id"), max_runtime_sec)
            timeout_hit = True
            break
        # Periodically check if the job was cancelled from the admin UI.
        if processed_targets % _cancel_check_interval == 0 and processed_targets > 0:
            if data_store_db.is_job_cancelled(job.get("id")):
                logger.info("Job %s cancelled by admin — stopping after %d targets", job.get("id"), processed_targets)
                cancelled = True
                break

        cmts_breakdown[cmts_name] = {"rows": 0, "rf_snapshots": 0, "error": None}
        processed_targets += 1

        # Enrich true gives us vendor/docsis/upstream/ofdm/ofdma fields for inventory table.
        # First call triggers background enrichment in PyPNM; poll back until enriched
        # or timeout so we get fiber_node / cable_mac / vendor from the cache.
        result = client.get_cmts_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=10000,
            enrich=True,
            modem_community=modem_community,
        )
        if not result.get("success"):
            logger.warning("Data-store job %s CMTS %s failed: %s", job.get("id"), cmts_ip, result.get("error"))
            cmts_breakdown[cmts_name]["error"] = result.get("error") or "CMTS walk failed"
            continue

        # Wait for CMTS-level enrichment (fiber_node, cable_mac, ofdm_enabled).
        # PyPNM sets cmts_enriched=True after Step 1 (_enrich_cmts_interfaces),
        # which is fast (~5-15s). We don't wait for per-modem enrichment (vendor,
        # firmware) which can take 20+ minutes per CMTS.
        _enrich_poll_interval = 5  # seconds between polls
        _enrich_max_wait = 120     # max 2 minutes for CMTS-level enrichment
        _enrich_waited = 0
        while (not result.get("enriched") and not result.get("cmts_enriched")
               and result.get("enriching") and _enrich_waited < _enrich_max_wait):
            if job_deadline is not None and time.monotonic() >= job_deadline:
                break
            time.sleep(_enrich_poll_interval)
            _enrich_waited += _enrich_poll_interval
            result = client.get_cmts_modems(
                cmts_ip=cmts_ip,
                community=community,
                limit=10000,
                enrich=True,
                modem_community=modem_community,
            )
            if not result.get("success"):
                break
        if _enrich_waited > 0:
            logger.info(
                "Enrichment wait for %s: %ss, cmts_enriched=%s, enriched=%s",
                cmts_name, _enrich_waited,
                result.get("cmts_enriched"), result.get("enriched"),
            )

        modems = result.get("modems") or []
        modems = filter_ignored_modems(modems)
        for m in modems:
            m["cmts"] = cmts_name
            m["cmts_ip"] = cmts_ip

        if int(poller.get("collect_identity", 1)):
            n = data_store_db.upsert_inventory_rows(modems, source_poller=poller.get("name"))
            total_written += n
            cmts_breakdown[cmts_name]["rows"] += n

        collect_scqam = int(poller.get("collect_scqam", 0)) == 1 and heavy_allowed
        collect_rxmer = int(poller.get("collect_rxmer", 0)) == 1 and heavy_allowed
        if collect_scqam or collect_rxmer:
            for m in modems[:heavy_max_modems]:
                mac = m.get("mac_address")
                if not mac:
                    continue
                modems_attempted += 1
                rf_result = _collect_modem_heavy_rf(
                    client=client,
                    modem=m,
                    modem_community=modem_community,
                    tftp_ipv4=tftp_ipv4,
                    collect_scqam=collect_scqam,
                    collect_rxmer=collect_rxmer,
                )
                if rf_result is None:
                    # Fallback to any RF data that may already be in enriched modem row.
                    scqam_payload = _extract_scqam_payload(m) if collect_scqam else {}
                    rxmer_payload = _extract_rxmer_payload(m) if collect_rxmer else {}
                    if not scqam_payload and not rxmer_payload:
                        modems_failed += 1
                        continue
                    rf_result = {
                        "scqam_json": json.dumps(scqam_payload) if scqam_payload else None,
                        "rxmer_json": json.dumps(rxmer_payload) if rxmer_payload else None,
                    }

                if rf_result.get("scqam_json") is None and rf_result.get("rxmer_json") is None:
                    modems_failed += 1
                    continue
                modems_succeeded += 1
                rf_snapshots.append(
                    {
                        "mac": mac,
                        "cmts": cmts_name,
                        "collected_at": None,
                        "scqam_json": rf_result.get("scqam_json"),
                        "rxmer_json": rf_result.get("rxmer_json"),
                    }
                )
                cmts_breakdown[cmts_name]["rf_snapshots"] = cmts_breakdown[cmts_name].get("rf_snapshots", 0) + 1
                if heavy_delay_ms > 0:
                    time.sleep(heavy_delay_ms / 1000.0)

    if rf_snapshots:
        total_written += data_store_db.insert_rf_snapshots(rf_snapshots, poller_name=poller.get("name"))

    # Keep RF snapshot table bounded per poller policy.
    try:
        data_store_db.cleanup_old_snapshots(poller.get("retention_days", 30))
    except Exception:
        logger.exception("Snapshot cleanup failed for poller id=%s", poller.get("id"))

    # Always save progress so the next job resumes from where we stopped,
    # whether we completed, timed out, or were cancelled.
    try:
        data_store_db.advance_poller_target_offset(poller.get("id"), total_targets, processed_targets)
    except Exception:
        logger.exception("Failed to advance target offset for poller id=%s", poller.get("id"))

    # If already cancelled in DB, don't overwrite the status — just log.
    if cancelled:
        logger.info("Job %s: saved progress (%d targets, %d rows) before cancel exit", job.get("id"), processed_targets, total_written)
        return

    timeout_error = None
    timeout_status = None
    if timeout_hit:
        timeout_error = f"Timed out after {max_runtime_sec}s; processed {processed_targets}/{total_targets} targets; partial results saved"
        timeout_status = "timed_out"

    data_store_db.complete_job(
        job.get("id"),
        rows_collected=total_written,
        error_text=timeout_error,
        modems_attempted=modems_attempted,
        modems_succeeded=modems_succeeded,
        modems_failed=modems_failed,
        cmts_breakdown=cmts_breakdown,
        status_override=timeout_status,
    )


def _run_refresh_request(req):
    req_id = req.get("id")
    mac = (req.get("mac") or "").lower().replace("-", ":")
    cmts_ref = req.get("cmts")
    if not mac or not cmts_ref:
        data_store_db.complete_refresh_request(req_id, error_text="Invalid refresh request")
        return

    cmts = CMTSProvider.get_cmts_by_hostname(cmts_ref) or CMTSProvider.get_cmts_by_ip(cmts_ref)
    cmts_ip = None
    cmts_name = cmts_ref
    if cmts:
        cmts_ip = cmts.get("IPAddress") or cmts.get("ip") or cmts.get("ip_address")
        cmts_name = cmts.get("HostName") or cmts_name
    if not cmts_ip:
        # allow direct IP in request when not in provider cache
        cmts_ip = cmts_ref

    community = os.environ.get("CMTS_COMMUNITY", os.environ.get("CMTS_SNMP_COMMUNITY", "public"))
    modem_community = os.environ.get("MODEM_COMMUNITY", os.environ.get("CM_SNMP_COMMUNITY", "private"))
    client = PyPNMClient()

    result = client.get_cmts_modems(
        cmts_ip=cmts_ip,
        community=community,
        limit=10000,
        enrich=True,
        modem_community=modem_community,
    )
    if not result.get("success"):
        data_store_db.complete_refresh_request(req_id, error_text=result.get("error", "CMTS refresh failed"))
        return

    modems = result.get("modems") or []
    mac_norm = mac.replace(":", "")
    target = None
    for m in modems:
        mm = (m.get("mac_address") or "").lower().replace(":", "").replace("-", "")
        if mm == mac_norm:
            target = m
            break

    if not target:
        data_store_db.complete_refresh_request(req_id, error_text="Modem not found on CMTS during refresh")
        return

    target["cmts"] = cmts_name
    target["cmts_ip"] = cmts_ip
    if is_ignored_modem_ip(target.get("ip_address")):
        data_store_db.complete_refresh_request(req_id, error_text="Ignored by MODEM_IGNORE_CIDRS")
        return
    data_store_db.upsert_inventory_rows([target], source_poller="manual-refresh")
    data_store_db.complete_refresh_request(req_id, error_text=None)


def _refresh_worker_loop():
    poll_sec = int(os.environ.get("DATA_STORE_JOB_POLL_SEC", "10"))
    logger.info("Data-store refresh worker started (poll=%ss)", poll_sec)
    while True:
        try:
            refresh_req = data_store_db.claim_next_refresh_request()
            if refresh_req:
                _run_refresh_request(refresh_req)
                continue
            time.sleep(poll_sec)
        except Exception as exc:
            logger.exception("Data-store refresh worker error: %s", exc)
            time.sleep(poll_sec)


def _poller_worker_loop():
    poll_sec = int(os.environ.get("DATA_STORE_JOB_POLL_SEC", "10"))
    logger.info("Data-store poller worker started (poll=%ss)", poll_sec)
    while True:
        try:
            job = data_store_db.claim_next_job()
            if not job:
                time.sleep(poll_sec)
                continue
            _run_poller_job(job)
        except Exception as exc:
            logger.exception("Data-store poller worker error: %s", exc)
            time.sleep(poll_sec)


def _in_poller_window(poller, now_local):
    start = _normalize_clock_value(poller.get("run_window_start"), "")
    end = _normalize_clock_value(poller.get("run_window_end"), "")
    if not start or not end:
        return True
    try:
        t_now = now_local.time()
        t_start = _parse_clock_time(start)
        t_end = _parse_clock_time(end)
    except Exception:
        return True
    if t_start <= t_end:
        return t_start <= t_now <= t_end
    # overnight window (e.g. 23:00-04:00)
    return t_now >= t_start or t_now <= t_end


def _last_job_due(poller, now_local):
    last_created = data_store_db.get_poller_last_job_created_at(poller.get("id"))
    if not last_created:
        return True
    try:
        ts = datetime.fromisoformat(str(last_created).replace("Z", ""))
    except Exception:
        return True
    interval_min = max(1, int(poller.get("interval_minutes") or 1440))
    elapsed = (now_local - ts).total_seconds() / 60.0
    return elapsed >= interval_min


def _in_heavy_window(poller, now_local):
    # Heavy RF tasks should only run during low-impact hours.
    start = _normalize_clock_value(poller.get("heavy_window_start"), "00:30")
    end = _normalize_clock_value(poller.get("heavy_window_end"), "05:30")
    try:
        t_now = now_local.time()
        t_start = _parse_clock_time(start)
        t_end = _parse_clock_time(end)
    except Exception:
        return True
    if t_start <= t_end:
        return t_start <= t_now <= t_end
    return t_now >= t_start or t_now <= t_end


def _scheduler_loop():
    logger.info("Data-store scheduler started")
    while True:
        try:
            if _effective_scheduler_enabled():
                run_scheduler_once()
        except Exception as exc:
            logger.exception("Data-store scheduler error: %s", exc)
        time.sleep(_effective_scheduler_poll_sec())


def _normalize_clock_value(value, default=""):
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip()
        return v or default
    if isinstance(value, timedelta):
        total = int(value.total_seconds()) % 86400
        hh = total // 3600
        mm = (total % 3600) // 60
        ss = total % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%H:%M:%S")
        except Exception:
            pass
    v = str(value).strip()
    return v or default


def _parse_clock_time(text):
    for fmt in ("%H:%M:%S", "%H:%M", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).time()
        except Exception:
            continue
    raise ValueError(f"Invalid clock value: {text}")


def run_scheduler_once():
    global _scheduler_last_tick, _scheduler_last_agent_load, _scheduler_last_decisions
    _scheduler_last_tick = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Auto-timeout stale running jobs before scheduling new ones.
    try:
        timed_out = data_store_db.timeout_stale_jobs()
        if timed_out:
            logger.warning("Auto-timed-out stale jobs: %s", timed_out)
    except Exception as exc:
        logger.exception("timeout_stale_jobs failed: %s", exc)

    pollers = data_store_db.list_poller_settings()
    now_local = datetime.now()
    agent_load = _get_agent_load_score()
    _scheduler_last_agent_load = agent_load
    queued = 0
    decisions = []
    running_heavy = data_store_db.get_running_heavy_job_count()
    for p in pollers:
        pid = p.get("id")
        pname = p.get("name") or f"poller-{pid}"

        if int(p.get("enabled", 1)) != 1:
            decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "disabled"})
            continue
        heavy_poller = int(p.get("collect_scqam", 0)) == 1 or int(p.get("collect_rxmer", 0)) == 1
        if not _in_poller_window(p, now_local):
            decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "outside_poller_window"})
            continue
        active_count = data_store_db.get_active_job_count_for_poller(p.get("id"))
        max_concurrency = max(1, int(p.get("max_concurrency") or 1))
        if active_count >= max_concurrency:
            decisions.append({
                "poller_id": pid,
                "poller_name": pname,
                "decision": "skip",
                "reason": "concurrency_limit",
                "detail": f"active={active_count}, max={max_concurrency}",
            })
            continue
        if not _last_job_due(p, now_local):
            decisions.append({"poller_id": pid, "poller_name": pname, "decision": "skip", "reason": "interval_not_due"})
            continue

        if heavy_poller:
            daytime_max = max(1, int(os.environ.get("DATA_STORE_HEAVY_MAX_RUNNING_DAY", "2")))
            nighttime_max = max(daytime_max, int(os.environ.get("DATA_STORE_HEAVY_MAX_RUNNING_NIGHT", "4")))
            heavy_cap = nighttime_max if _in_heavy_window(p, now_local) else daytime_max
            if running_heavy >= heavy_cap:
                decisions.append({
                    "poller_id": pid,
                    "poller_name": pname,
                    "decision": "skip",
                    "reason": "heavy_running_limit",
                    "detail": f"running_heavy={running_heavy}, cap={heavy_cap}",
                })
                continue

        queue_depth = data_store_db.get_internal_queue_depth()
        effective_load = queue_depth + agent_load
        threshold = max(1, int(p.get("max_agent_queue_depth") or 20))
        if effective_load > threshold:
            decisions.append({
                "poller_id": pid,
                "poller_name": pname,
                "decision": "skip",
                "reason": "load_too_high",
                "effective_load": effective_load,
                "threshold": threshold,
            })
            continue

        data_store_db.enqueue_poller_run(
            poller_id=p.get("id"),
            trigger_type="scheduled",
            requested_by="scheduler",
            payload={
                "reason": "interval-window",
                "queue_depth": queue_depth,
                "agent_load": agent_load,
                "effective_load": effective_load,
            },
        )
        queued += 1
        logger.info("Scheduled poller run queued (poller_id=%s)", p.get("id"))
        if heavy_poller:
            running_heavy += 1

        decisions.append({
            "poller_id": pid,
            "poller_name": pname,
            "decision": "queued",
            "reason": "ok",
            "effective_load": effective_load,
            "threshold": threshold,
        })

    _scheduler_last_decisions = decisions[:100]

    # Persist decisions so history survives restarts.
    try:
        data_store_db.log_scheduler_decisions(_scheduler_last_tick, decisions)
    except Exception as exc:
        logger.exception("log_scheduler_decisions failed: %s", exc)

    return queued


def _agent_int(v):
    try:
        return int(v)
    except Exception:
        return 0


def _get_agent_load_score():
    """Best-effort busy/queued score across connected agents.

    Falls back to 0 when agent endpoint is unavailable.
    """
    try:
        client = PyPNMClient()
        data = client.get_agents() or {}
        agents = data.get("agents") or []
        total = 0
        for a in agents:
            status = str(a.get("status") or "").lower()
            is_alive = bool(a.get("is_alive", False))
            connected = status == "connected" or is_alive
            if not connected:
                continue
            total += _agent_int(a.get("current_tasks"))
            total += _agent_int(a.get("active_tasks"))
            total += _agent_int(a.get("queued_tasks"))
            total += _agent_int(a.get("queue_depth"))
            total += _agent_int(a.get("in_progress"))
        return max(0, total)
    except Exception:
        logger.exception("Failed to compute agent load score")
        return 0


def set_scheduler_enabled(enabled):
    global _scheduler_enabled_override
    _scheduler_enabled_override = bool(enabled)


def set_scheduler_poll_sec(poll_sec):
    global _scheduler_poll_sec_override
    _scheduler_poll_sec_override = max(5, int(poll_sec))


def start_data_store_worker():
    global _worker_started, _refresh_threads, _poller_threads, _scheduler_started, _scheduler_thread, _leader_lock_fd
    if _worker_started:
        return
    enabled = os.environ.get("DATA_STORE_WORKER_ENABLED", "true").lower() == "true"
    if not enabled:
        logger.info("Data-store worker disabled by DATA_STORE_WORKER_ENABLED=false")
        return

    # Ensure only one process starts the background loops in multi-process servers.
    lock_path = os.environ.get("DATA_STORE_WORKER_LOCK_FILE", "/tmp/pypnm_data_store_worker.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _leader_lock_fd = fd
    except OSError:
        logger.info("Data-store worker not started in this process (leader lock held by another process)")
        return

    refresh_workers = max(1, int(os.environ.get("DATA_STORE_REFRESH_WORKER_THREADS", "10")))
    poller_workers = max(1, int(os.environ.get("DATA_STORE_POLLER_WORKER_THREADS", "4")))

    _refresh_threads = []
    for idx in range(refresh_workers):
        t = threading.Thread(target=_refresh_worker_loop, name=f"data-store-refresh-{idx+1}", daemon=True)
        t.start()
        _refresh_threads.append(t)

    _poller_threads = []
    for idx in range(poller_workers):
        t = threading.Thread(target=_poller_worker_loop, name=f"data-store-poller-{idx+1}", daemon=True)
        t.start()
        _poller_threads.append(t)

    logger.info(
        "Data-store worker pools started (refresh_threads=%s, poller_threads=%s)",
        refresh_workers,
        poller_workers,
    )

    _worker_started = True

    if not _scheduler_started:
        _scheduler_thread = threading.Thread(target=_scheduler_loop, name="data-store-scheduler", daemon=True)
        _scheduler_thread.start()
        _scheduler_started = True


def get_scheduler_status():
    return {
        "enabled": _effective_scheduler_enabled(),
        "running": _scheduler_started,
        "last_tick": _scheduler_last_tick,
        "agent_load": _scheduler_last_agent_load,
        "decisions": _scheduler_last_decisions,
        "poll_sec": _effective_scheduler_poll_sec(),
        "override_enabled": _scheduler_enabled_override,
        "override_poll_sec": _scheduler_poll_sec_override,
    }
