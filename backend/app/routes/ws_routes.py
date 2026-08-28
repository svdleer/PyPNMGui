# PyPNM Web GUI - Browser-facing WebSocket Routes

import json
import logging
import os
import time
from collections import deque

from flask import Blueprint

logger = logging.getLogger(__name__)
ws_bp = Blueprint('ws', __name__)

try:
    from flask_sock import Sock
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.warning("flask-sock not installed, WebSocket support disabled")

_utsc_sessions = {}


def _non_empty_community(value):
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


def _resolve_cmts_read_community(cmts_ip, explicit=None):
    """Preserve only a deliberate override; otherwise defer to the CMTS agent."""
    return _non_empty_community(explicit)


def _resolve_cmts_write_community(cmts_ip, explicit=None):
    """Preserve only a deliberate override; otherwise defer to the CMTS agent."""
    return _non_empty_community(explicit)


def start_utsc_via_pypnm(
    cmts_ip,
    rf_port_ifindex,
    community,
    write_community=None,
    cfg_index=0,
    trigger_mode=2,
):
    """Start UTSC through PyPNM, the sole owner of remote execution."""
    write_community = _non_empty_community(write_community)
    try:
        from app.core.pypnm_client import PyPNMClient

        result = PyPNMClient().start_utsc(
            cmts_ip=cmts_ip,
            rf_port_ifindex=int(rf_port_ifindex),
            community=community,
            write_community=write_community,
            cfg_index=int(cfg_index),
            trigger_mode=int(trigger_mode),
        )
        if not result.get('success'):
            logger.warning("UTSC start via PyPNM failed: %s", result)
        return result
    except Exception as exc:
        logger.error("UTSC start via PyPNM failed: %s", exc)
        return {'success': False, 'error': str(exc)}


def stop_utsc_via_pypnm(
    cmts_ip,
    rf_port_ifindex,
    community,
    write_community=None,
    cfg_index=1,
):
    """Stop UTSC through PyPNM using the row returned by start/configure."""
    write_community = _non_empty_community(write_community)
    try:
        from app.core.pypnm_client import PyPNMClient

        result = PyPNMClient().stop_utsc(
            cmts_ip=cmts_ip,
            rf_port_ifindex=int(rf_port_ifindex),
            community=community,
            write_community=write_community,
            cfg_index=int(cfg_index),
        )
        if not result.get('success'):
            logger.warning("UTSC stop via PyPNM failed: %s", result)
        return result
    except Exception as exc:
        logger.error("UTSC stop via PyPNM failed: %s", exc)
        return {'success': False, 'error': str(exc)}


def _vendor_hint(cmts_ip: str | None) -> str:
    """Return inventory metadata only; source policy remains in PyPNM."""
    if not cmts_ip:
        return ''
    try:
        from app.core.cmts_provider import CMTSProvider

        cmts = CMTSProvider.get_cmts_by_ip(cmts_ip)
        vendor_text = f"{(cmts or {}).get('Vendor', '')} {(cmts or {}).get('Type', '')}".lower()
        if 'cisco' in vendor_text or 'cbr' in vendor_text:
            return 'cisco'
        if any(token in vendor_text for token in ('casa', 'evo', 'vccap')):
            return 'casa'
        if any(token in vendor_text for token in ('arris', 'commscope', 'e6000')):
            return 'commscope'
    except Exception:
        pass
    return ''


def _spectrum_config(mac_address: str) -> tuple[int, int]:
    """Read the presentation frequency range retained by the GUI session."""
    try:
        from app import redis_client

        raw = redis_client.get(f'utsc_config:{mac_address}')
        config = json.loads(raw) if raw else {}
        return int(config.get('center_freq_hz', 50000000)), int(config.get('span_hz', 80000000))
    except Exception:
        return 50000000, 80000000


def init_websocket(app):
    """Initialize the browser-facing UTSC presentation stream."""
    if not WEBSOCKET_AVAILABLE:
        logger.warning("WebSocket not available")
        return None

    from app.core.pypnm_client import PyPNMClient

    sock = Sock(app)

    @sock.route('/ws/utsc/<mac_address>')
    def utsc_websocket(ws, mac_address):
        from flask import request

        refresh_ms = int(request.args.get('refresh', 500))
        duration_s = int(request.args.get('duration', 60))
        rf_port = request.args.get('rf_port')
        cfg_index = int(request.args.get('cfg_index', 0))
        cmts_ip = request.args.get('cmts_ip')
        community = _resolve_cmts_read_community(cmts_ip)
        write_community = _resolve_cmts_write_community(cmts_ip)
        externally_started = request.args.get('live', '').lower() in {'1', 'true', 'yes', 'on'}
        vendor = _vendor_hint(cmts_ip)
        mac_clean = mac_address.replace(':', '').replace('-', '').lower()
        default_center, default_span = _spectrum_config(mac_address)
        center_freq_hz = int(request.args.get('center_freq_hz', default_center))
        span_hz = int(request.args.get('span_hz', default_span))
        max_bins = max(1, min(int(request.args.get('num_bins', 1600)), 16384))

        prefixes = []
        if vendor == 'cisco':
            if rf_port:
                prefixes.append(f'PNMCcapUsSpecAn_*_{rf_port}')
            prefixes.extend(('PNMCcapUsSpecAn_*', f'utsc_{mac_clean}_*'))
        else:
            prefixes.append(f'utsc_{mac_clean}_*')
            if rf_port:
                prefixes.append(f'PNMCcapUsSpecAn_*_{rf_port}')
            prefixes.append('PNMCcapUsSpecAn_*')

        client = PyPNMClient()
        session_id = f"{mac_clean}_{id(ws)}"
        _utsc_sessions[session_id] = True
        processed_files: set[str] = set()
        file_buffer = deque(maxlen=500)
        heartbeat_interval = 5
        stream_interval = max(0.05, refresh_ms / 1000.0)
        connection_start_time = time.time()
        last_heartbeat = connection_start_time
        last_stream_time = 0.0
        last_fetch_time = 0.0
        last_new_file_time = connection_start_time
        fetch_interval = 2.0
        no_file_timeout = 120
        owns_utsc = False
        resolved_cfg_index = cfg_index
        run_counter = 0
        trigger_interval = 30
        last_trigger_time = connection_start_time

        logger.info(
            "UTSC WebSocket opened for %s: refresh=%sms duration=%ss port=%s live=%s",
            mac_address, refresh_ms, duration_s, rf_port, externally_started,
        )

        try:
            ws.send(json.dumps({
                'type': 'connected',
                'mac': mac_address,
                'message': f'UTSC stream connected: {stream_interval:.1f}s refresh, {duration_s}s duration',
                'refresh_ms': refresh_ms,
                'duration_s': duration_s,
            }))

            # The browser sends one initial JSON configuration message. Preserve
            # deliberate credential overrides there without exposing them in URLs;
            # omitted or blank values continue to resolve on the CMTS agent.
            try:
                initial_raw = ws.receive(timeout=5)
                initial_config = json.loads(initial_raw) if initial_raw else {}
                if isinstance(initial_config, dict):
                    community = _resolve_cmts_read_community(
                        cmts_ip, initial_config.get('community')
                    )
                    write_community = _resolve_cmts_write_community(
                        cmts_ip, initial_config.get('write_community')
                    )
            except Exception as exc:
                logger.debug("No usable UTSC WebSocket initial config: %s", exc)

            # Housekeeping executes in PyPNM and is restricted to aged UTSC files.
            cleanup = client.housekeeping_utsc_files(
                max_age_seconds=60,
                dry_run=False,
                vendor=vendor or None,
            )
            if cleanup.get('success'):
                logger.info("UTSC housekeeping removed %s aged file(s)", cleanup.get('deleted_count', 0))

            if rf_port and cmts_ip:
                if externally_started:
                    logger.info("UTSC WebSocket streaming existing run at cfg_index=%s", resolved_cfg_index)
                else:
                    start_result = start_utsc_via_pypnm(
                        cmts_ip,
                        int(rf_port),
                        community,
                        write_community=write_community,
                        cfg_index=cfg_index,
                    )
                    if not start_result.get('success'):
                        error = start_result.get('error') or 'PyPNM rejected UTSC start'
                        ws.send(json.dumps({'type': 'error', 'message': f'Failed to start UTSC: {error}'}))
                        return
                    resolved_cfg_index = int(start_result.get('cfg_index') or cfg_index)
                    if resolved_cfg_index <= 0:
                        ws.send(json.dumps({'type': 'error', 'message': 'UTSC start returned no usable config row'}))
                        return
                    owns_utsc = True
                    run_counter = 1
                    last_trigger_time = time.time()

            # Preserve the browser protocol used by the spectrum analyzer.
            ws.send(json.dumps({
                'type': 'buffering_complete',
                'message': 'PyPNM normalized sample stream ready',
                'buffer_size': len(file_buffer),
            }))

            while _utsc_sessions.get(session_id, False):
                current_time = time.time()
                elapsed = current_time - connection_start_time

                if owns_utsc and current_time - last_trigger_time >= trigger_interval:
                    start_result = start_utsc_via_pypnm(
                        cmts_ip,
                        int(rf_port),
                        community,
                        write_community=write_community,
                        cfg_index=resolved_cfg_index,
                    )
                    last_trigger_time = current_time
                    if start_result.get('success'):
                        resolved_cfg_index = int(start_result.get('cfg_index') or resolved_cfg_index)
                        run_counter += 1
                    else:
                        logger.warning("UTSC direct-session re-trigger failed: %s", start_result)

                if current_time - last_fetch_time >= fetch_interval:
                    listed: list[str] = []
                    for prefix in prefixes:
                        result = client.list_utsc_files(
                            prefix=prefix,
                            rf_port_ifindex=int(rf_port) if rf_port else None,
                            mac_address=mac_address,
                            vendor=vendor or None,
                            exclude=list(processed_files),
                        )
                        if result.get('success'):
                            listed.extend(result.get('files') or [])

                    ordered = []
                    seen = set()
                    for filename in listed:
                        basename = str(filename).rsplit('/', 1)[-1]
                        if basename and basename not in seen and basename not in processed_files:
                            seen.add(basename)
                            ordered.append(basename)

                    for filename in ordered[:25]:
                        sample = client.get_utsc_sample(
                            filename=filename,
                            vendor=vendor or None,
                            center_freq_hz=center_freq_hz,
                            span_hz=span_hz,
                            max_bins=max_bins,
                        )
                        if not sample.get('success'):
                            continue
                        processed_files.add(filename)
                        file_buffer.append(sample)
                        last_new_file_time = current_time
                    last_fetch_time = current_time

                if not file_buffer and current_time - last_new_file_time > no_file_timeout:
                    ws.send(json.dumps({
                        'type': 'error',
                        'message': f'No UTSC capture files received after {no_file_timeout}s. Check CMTS TFTP destination.',
                    }))
                    break

                if file_buffer and current_time - last_stream_time >= stream_interval:
                    sample = file_buffer.popleft()
                    last_stream_time = current_time
                    ws.send(json.dumps({
                        'type': 'spectrum',
                        'timestamp': sample.get('collected_at') or current_time,
                        'filename': sample.get('filename'),
                        'buffer_size': len(file_buffer),
                        'plot': None,
                        'raw_data': {
                            'freq_start_hz': sample.get('freq_start_hz'),
                            'freq_step_hz': sample.get('freq_step_hz'),
                            'bins': sample.get('bins') or [],
                            'span_hz': sample.get('span_hz'),
                            'center_freq_hz': sample.get('center_freq_hz'),
                            'units': sample.get('units', 'dBmV'),
                        },
                    }))

                if current_time - last_heartbeat > heartbeat_interval:
                    ws.send(json.dumps({
                        'type': 'heartbeat',
                        'timestamp': current_time,
                        'buffer_size': len(file_buffer),
                        'elapsed': elapsed,
                    }))
                    last_heartbeat = current_time

                time.sleep(0.05)

        except Exception as exc:
            logger.error("UTSC WebSocket error: %s", exc, exc_info=True)
            raise
        finally:
            if owns_utsc and rf_port and cmts_ip:
                stop_result = stop_utsc_via_pypnm(
                    cmts_ip,
                    int(rf_port),
                    community,
                    write_community=write_community,
                    cfg_index=resolved_cfg_index,
                )
                if not stop_result.get('success'):
                    logger.warning("UTSC stop failed on cleanup: %s", stop_result)
            _utsc_sessions.pop(session_id, None)
            logger.info("UTSC WebSocket closed for %s after %s owned run(s)", mac_address, run_counter)

    logger.info("WebSocket UTSC endpoint registered at /ws/utsc/<mac>")
    return sock
