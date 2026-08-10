# PyPNM Web GUI - WebSocket Routes for Agents

import logging
import json
import time
import glob
import os
import struct
import threading
import requests
import base64
from collections import deque
from flask import Blueprint, current_app

logger = logging.getLogger(__name__)

ws_bp = Blueprint('ws', __name__)

try:
    from flask_sock import Sock
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.warning("flask-sock not installed, WebSocket support disabled")

try:
    import tftpy
    TFTP_AVAILABLE = True
except ImportError:
    TFTP_AVAILABLE = False
    logger.warning("tftpy not installed, TFTP delete support disabled")

try:
    from ftplib import FTP
    FTP_AVAILABLE = True
except ImportError:
    FTP_AVAILABLE = False
    logger.warning("ftplib not available, FTP delete support disabled")

# Track active UTSC streaming sessions
_utsc_sessions = {}


def delete_tftp_files(tftp_ip, filenames):
    """Delete files via TFTP."""
    if not TFTP_AVAILABLE:
        logger.warning("TFTP not available, cannot delete files")
        return 0
    
    deleted = 0
    for filename in filenames:
        try:
            # TFTP uses WRQ (write request) with 0 bytes to delete
            client = tftpy.TftpClient(tftp_ip, 69)
            # Send empty file to "delete" it (standard TFTP behavior)
            client.upload(filename, None, timeout=2)
            deleted += 1
        except Exception as e:
            logger.debug(f"TFTP delete {filename} failed: {e}")
    
    return deleted


def delete_utsc_files_via_ftp(ftp_server, ftp_user, ftp_pass, filenames):
    """Delete UTSC files via FTP."""
    if not FTP_AVAILABLE:
        logger.warning("FTP not available, cannot delete files")
        return 0
    
    deleted = 0
    try:
        ftp = FTP()
        ftp.connect(ftp_server, 21, timeout=10)
        ftp.login(ftp_user, ftp_pass)
        
        # Navigate to tftpboot directory
        try:
            ftp.cwd('/var/lib/tftpboot')
        except Exception as e:
            logger.warning(f"FTP: Could not change to /var/lib/tftpboot: {e}")
            ftp.quit()
            return 0
        
        for filename in filenames:
            try:
                ftp.delete(filename)
                deleted += 1
            except Exception as e:
                logger.debug(f"FTP delete {filename} failed: {e}")
        
        ftp.quit()
    except Exception as e:
        logger.error(f"FTP connection failed: {e}")
    
    return deleted


def delete_rxmer_files_by_mac_via_ftp(ftp_server, ftp_user, ftp_pass, mac_list, tftp_dir='/var/lib/tftpboot'):
    """
    Delete all rxmer capture files for the given MACs via FTP.
    Lists the TFTP directory and removes files matching rxmer_<mac>* or usrxmer_<mac>*.
    Used for housekeeping before a fiber node scan to clear stale captures.
    Returns number of deleted files.
    """
    if not FTP_AVAILABLE:
        logger.warning("FTP not available, cannot delete stale captures")
        return 0

    # Normalise MACs to bare hex (no colons, lowercase)
    mac_keys = [m.replace(':', '').lower() for m in mac_list if m]

    deleted = 0
    try:
        ftp = FTP()
        ftp.connect(ftp_server, 21, timeout=10)
        ftp.login(ftp_user, ftp_pass)
        try:
            ftp.cwd(tftp_dir)
        except Exception as e:
            logger.warning(f"FTP housekeeping: could not cd to {tftp_dir}: {e}")
            ftp.quit()
            return 0

        # List all filenames in the directory
        all_files = ftp.nlst()
        for fname in all_files:
            bare = fname.split('/')[-1]  # strip any path prefix
            for mac in mac_keys:
                if bare.startswith(f'rxmer_{mac}') or bare.startswith(f'usrxmer_{mac}'):
                    try:
                        ftp.delete(bare)
                        deleted += 1
                        logger.debug(f"FTP housekeeping: deleted {bare}")
                    except Exception as e:
                        logger.warning(f"FTP housekeeping: could not delete {bare}: {e}")
                    break

        ftp.quit()
    except Exception as e:
        logger.error(f"FTP housekeeping connection failed: {e}")

    return deleted


def start_utsc_via_pypnm(
    cmts_ip,
    rf_port_ifindex,
    community,
    write_community=None,
    cfg_index=0,
    trigger_mode=2,
):
    """Start UTSC through PyPNM, the sole owner of remote-agent execution."""
    try:
        from app.core.pypnm_client import PyPNMClient

        result = PyPNMClient().start_utsc(
            cmts_ip=cmts_ip,
            rf_port_ifindex=int(rf_port_ifindex),
            community=community,
            write_community=write_community or community,
            cfg_index=int(cfg_index),
            trigger_mode=int(trigger_mode),
        )
        if result.get('success'):
            logger.debug(
                "UTSC started via PyPNM on port %s cfg_index=%s",
                rf_port_ifindex,
                result.get('cfg_index'),
            )
        else:
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
    try:
        from app.core.pypnm_client import PyPNMClient

        result = PyPNMClient().stop_utsc(
            cmts_ip=cmts_ip,
            rf_port_ifindex=int(rf_port_ifindex),
            community=community,
            write_community=write_community or community,
            cfg_index=int(cfg_index),
        )
        if result.get('success'):
            logger.debug(
                "UTSC stopped via PyPNM on port %s cfg_index=%s",
                rf_port_ifindex,
                cfg_index,
            )
        else:
            logger.warning("UTSC stop via PyPNM failed: %s", result)
        return result
    except Exception as exc:
        logger.error("UTSC stop via PyPNM failed: %s", exc)
        return {'success': False, 'error': str(exc)}


# UTSC Status values (from CMTS MIB)
STATUS_INACTIVE = 2
STATUS_BUSY = 3
STATUS_SAMPLE_READY = 4
STATUS_ERROR = 5



def init_websocket(app):
    """Initialize browser-facing WebSocket support."""
    if not WEBSOCKET_AVAILABLE:
        logger.warning("WebSocket not available")
        return None
    
    sock = Sock(app)
    
    @sock.route('/ws/utsc/<mac_address>')
    def utsc_websocket(ws, mac_address):
        """WebSocket endpoint for streaming UTSC spectrum data with buffering."""
        from flask import request
        
        logger.info(f"=== UTSC WebSocket handler called for {mac_address} ===")
        
        try:
            # Parse query parameters
            refresh_ms = int(request.args.get('refresh', 500))  # Refresh rate in ms
            duration_s = int(request.args.get('duration', 60))  # Duration in seconds
            rf_port = request.args.get('rf_port')
            cfg_index = int(request.args.get('cfg_index', 0))
            cmts_ip = request.args.get('cmts_ip')
            community = request.args.get('community', 'public')
            write_community = request.args.get('write_community', community)
            externally_started = request.args.get('live', '').lower() in {'1', 'true', 'yes', 'on'}
            
            logger.info(
                f"UTSC WebSocket opened for {mac_address}: refresh={refresh_ms}ms, "
                f"duration={duration_s}s, rf_port={rf_port}, cfg_index={cfg_index}, "
                f"cmts_ip={cmts_ip}, externally_started={externally_started}"
            )
        except Exception as e:
            logger.error(f"UTSC WebSocket parameter parsing failed: {e}")
            raise
        
        # Clean MAC address format
        mac_clean = mac_address.replace(':', '').replace('-', '').lower()

        # Determine CMTS vendor for file pattern and retrieval mode hints.
        vendor_hint = ''
        try:
            from app.core.cmts_provider import CMTSProvider

            if cmts_ip:
                cmts = CMTSProvider.get_cmts_by_ip(cmts_ip)
                if cmts:
                    vendor_text = f"{cmts.get('Vendor', '')} {cmts.get('Type', '')}".strip().lower()
                    if 'cisco' in vendor_text or 'cbr' in vendor_text:
                        vendor_hint = 'cisco'
                    elif 'casa' in vendor_text or 'evo' in vendor_text or 'vccap' in vendor_text:
                        vendor_hint = 'casa'
                    elif 'arris' in vendor_text or 'commscope' in vendor_text or 'e6000' in vendor_text:
                        vendor_hint = 'commscope'
        except Exception:
            vendor_hint = ''

        # Build filename prefixes by vendor; keep both patterns as fallback for unknowns.
        filename_prefixes = []
        if vendor_hint == 'cisco':
            if rf_port:
                filename_prefixes.append(f'PNMCcapUsSpecAn_*_{rf_port}')
            filename_prefixes.append('PNMCcapUsSpecAn_*')
            filename_prefixes.append(f'utsc_{mac_clean}_*')
        else:
            filename_prefixes.append(f'utsc_{mac_clean}_*')
            if rf_port:
                filename_prefixes.append(f'PNMCcapUsSpecAn_*_{rf_port}')
            filename_prefixes.append('PNMCcapUsSpecAn_*')

        def _all_candidate_files(base_dir: str) -> list[str]:
            candidates: list[str] = []
            if not base_dir:
                return candidates
            for pfx in filename_prefixes:
                candidates.extend(glob.glob(f"{base_dir}/{pfx}"))
            # Keep only regular files
            return [p for p in set(candidates) if os.path.isfile(p)]

        def _prefetch_via_api_to_local(max_files: int = 20) -> int:
            """Prefetch matching UTSC files via PyPNM API into local stream folder.

            Keeps websocket flow unchanged: files are still parsed from local filesystem.
            This only adds a vendor-aware source (agent/ftp/local decided by PyPNM API).
            """
            base_url = os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://localhost:8000')).rstrip('/')
            listed: list[str] = []

            # 1) List candidate files using the same UTSC API route for all vendors.
            for pfx in filename_prefixes:
                try:
                    r = requests.post(
                        f"{base_url}/pnm/us/utsc/files/list",
                        json={
                            'prefix': pfx,
                            'rf_port_ifindex': int(rf_port) if rf_port else None,
                            'mac_address': mac_address,
                            'vendor': vendor_hint or None,
                            'exclude': list(processed_files),
                        },
                        timeout=8,
                    )
                    if r.status_code >= 400:
                        continue
                    payload = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
                    if payload.get('success'):
                        listed.extend(payload.get('files', []) or [])
                except Exception:
                    continue

            # De-duplicate while preserving order.
            seen = set()
            ordered = []
            for fname in listed:
                bname = os.path.basename(str(fname))
                if bname and bname not in seen:
                    seen.add(bname)
                    ordered.append(bname)

            # 2) Retrieve new files and write them into local stream folder.
            fetched = 0
            for bname in ordered:
                if fetched >= max_files:
                    break
                if bname in processed_files:
                    continue
                local_path = os.path.join(tftp_base, bname)
                if os.path.exists(local_path):
                    continue

                try:
                    r = requests.post(
                        f"{base_url}/pnm/us/utsc/files/retrieve",
                        json={'filename': bname, 'glob': False, 'vendor': vendor_hint or None},
                        timeout=12,
                    )
                    if r.status_code >= 400:
                        continue
                    payload = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
                    if not payload.get('success'):
                        continue
                    content_b64 = payload.get('content_base64')
                    if not content_b64:
                        continue
                    with open(local_path, 'wb') as fh:
                        fh.write(base64.b64decode(content_b64))
                    fetched += 1
                except Exception:
                    continue

            if fetched:
                logger.info(f"UTSC WebSocket: API prefetched {fetched} file(s) for vendor={vendor_hint or 'unknown'}")
            return fetched

        session_id = f"{mac_clean}_{id(ws)}"
        _utsc_sessions[session_id] = True
        _prefetch_running = [False]  # Guard: only one prefetch thread at a time

        processed_files = set()  # Track files we've already processed
        file_buffer = deque(maxlen=500)  # Buffer for smooth streaming (max 500 samples)
        from app.core.pnm_file_source import local_tftp_path
        tftp_base = local_tftp_path()  # /app/data/pnm_cache in FTP mode, /var/lib/tftpboot in local mode
        heartbeat_interval = 5
        last_heartbeat = time.time()
        last_stream_time = 0
        stream_interval = refresh_ms / 1000.0  # Convert to seconds
        connection_start_time = time.time()
        last_status = None
        initial_buffer_target = 0
        streaming_started = False
        
        # Sessions opened after the normal GUI start call stream only. Direct
        # analyzer sessions own their PyPNM start/retrigger/stop lifecycle.
        run_counter = 0
        trigger_interval = 30  # seconds between direct-session re-triggers
        owns_utsc = False
        resolved_cfg_index = cfg_index
        last_trigger_time = time.time()
        
        try:
            # Send initial connected message
            ws.send(json.dumps({
                'type': 'connected',
                'mac': mac_address,
                'message': f'UTSC stream connected: {stream_interval:.1f}s refresh, {duration_s}s duration',
                'refresh_ms': refresh_ms,
                'duration_s': duration_s
            }))
            
            # Delete old UTSC files via FTP before starting (but only if no active session exists)
            # Clean up ALL UTSC files, not just current MAC - prevents disk buildup
            # Always define FTP credentials
            ftp_server = current_app.config.get('FTP_SERVER_IP', '127.0.0.1')
            ftp_user = current_app.config.get('FTP_USER', 'ftpaccess')
            ftp_pass = current_app.config.get('FTP_PASSWORD', 'ftpaccessftp')
            
            # Look for recent files from this stream (last 60 seconds)
            all_files = _all_candidate_files(tftp_base)
            current_time = time.time()
            recent_files = [f for f in all_files if (current_time - os.path.getmtime(f)) < 60]
            old_files = [f for f in all_files if f not in recent_files]
            
            # Delete only OLD files (>60s), keep recent ones
            if old_files:
                logger.info(f"UTSC WebSocket: Deleting {len(old_files)} old files (>60s)")
                filenames = [os.path.basename(f) for f in old_files]
                deleted =delete_utsc_files_via_ftp(ftp_server, ftp_user, ftp_pass, filenames)
                logger.info(f"UTSC WebSocket: Deleted {deleted}/{len(old_files)} old files")
                time.sleep(0.2)
            
            # Mark recent files as ready to stream
            if recent_files:
                logger.info(f"UTSC WebSocket: Found {len(recent_files)} recent files (<60s old) - will stream these")
            else:
                logger.info(f"UTSC WebSocket: No recent files found - waiting for new captures")
            
            # The normal GUI flow starts UTSC before opening this stream. A direct
            # analyzer session without live=1 starts UTSC through canonical PyPNM.
            stream_start_time = time.time()
            last_trigger_time = stream_start_time
            
            if rf_port and cmts_ip:
                if externally_started:
                    logger.info(
                        "UTSC WebSocket: streaming existing run at cfg_index=%s",
                        resolved_cfg_index,
                    )
                else:
                    logger.info("UTSC WebSocket: starting direct analyzer run via PyPNM")
                    start_result = start_utsc_via_pypnm(
                        cmts_ip,
                        int(rf_port),
                        community,
                        write_community=write_community,
                        cfg_index=cfg_index,
                    )
                    if not start_result.get('success'):
                        error = start_result.get('error') or 'PyPNM rejected UTSC start'
                        logger.error("UTSC initial start failed: %s", error)
                        ws.send(json.dumps({'type': 'error', 'message': f'Failed to start UTSC: {error}'}))
                        return
                    resolved_cfg_index = int(start_result.get('cfg_index') or cfg_index)
                    if resolved_cfg_index <= 0:
                        logger.error("UTSC start returned invalid cfg_index=%s", resolved_cfg_index)
                        ws.send(json.dumps({'type': 'error', 'message': 'UTSC start returned no usable config row'}))
                        return
                    owns_utsc = True
                    run_counter += 1
            else:
                logger.info("UTSC WebSocket: passive mode - streaming pre-existing files only")
            
            last_ftp_fetch_time = 0
            FTP_FETCH_INTERVAL = 2.0  # seconds between FTP polls
            last_new_file_time = time.time()  # track when we last saw a new file
            NO_FILE_TIMEOUT = 120  # give up after 2 min with no new files

            while _utsc_sessions.get(session_id, False):
                current_time = time.time()
                elapsed = current_time - connection_start_time
                
                # Only direct analyzer sessions own periodic retriggers. GUI-started
                # sessions are already running and must not be triggered twice.
                if owns_utsc and (current_time - last_trigger_time) >= trigger_interval:
                    logger.info(
                        "UTSC WebSocket: re-triggering direct run #%s via PyPNM",
                        run_counter,
                    )
                    start_result = start_utsc_via_pypnm(
                        cmts_ip,
                        int(rf_port),
                        community,
                        write_community=write_community,
                        cfg_index=resolved_cfg_index,
                    )
                    last_trigger_time = current_time
                    if start_result.get('success'):
                        resolved_cfg_index = int(
                            start_result.get('cfg_index') or resolved_cfg_index
                        )
                        run_counter += 1
                    else:
                        logger.warning(
                            "UTSC direct-session re-trigger failed: %s",
                            start_result.get('error') or start_result,
                        )
                
                # Fetch new files — throttled to every FTP_FETCH_INTERVAL seconds.
                # Agent mode: API prefetch handles retrieval; skip FTP entirely.
                # FTP/local mode: use fetch_pnm_files as before.
                if (current_time - last_ftp_fetch_time) >= FTP_FETCH_INTERVAL:
                    # Resolve effective file source mode for this vendor.
                    def _resolve_mode(vh: str) -> str:
                        vendor_keys: list[str] = []
                        if 'cisco' in vh or 'cbr' in vh:
                            vendor_keys = ['CISCO_TFTP', 'CMTS_TFTP_CISCO']
                        elif 'commscope' in vh or 'arris' in vh or 'e6000' in vh:
                            vendor_keys = ['COMMSCOPE_TFTP', 'CMTS_TFTP_COMMSCOPE']
                        elif 'casa' in vh or 'evo' in vh:
                            vendor_keys = ['CASA_TFTP', 'CMTS_TFTP_CASA']
                        for k in vendor_keys:
                            v = (os.environ.get(k) or '').strip().lower()
                            if v in ('ftp', 'agent', 'local'):
                                return v
                        return (os.environ.get('CMTS_TFTP') or os.environ.get('PNM_FILE_SOURCE', 'local')).strip().lower()

                    effective_mode = _resolve_mode(vendor_hint)

                    if effective_mode != 'agent':
                        # FTP or local: use existing fetch helper.
                        from app.core.pnm_file_source import fetch_pnm_files
                        for pfx in filename_prefixes:
                            fetch_pnm_files(pfx.split('*')[0])

                    # API prefetch (vendor-aware agent/ftp/local via PyPNM).
                    # Guard: skip if a previous prefetch thread is still running.
                    if not _prefetch_running[0]:
                        def _run_prefetch():
                            _prefetch_running[0] = True
                            try:
                                _prefetch_via_api_to_local(max_files=25)
                            finally:
                                _prefetch_running[0] = False
                        import threading as _threading
                        _threading.Thread(target=_run_prefetch, daemon=True).start()

                    last_ftp_fetch_time = current_time

                # Timeout: close if no new files arrive for NO_FILE_TIMEOUT seconds
                if not streaming_started and (current_time - last_new_file_time) > NO_FILE_TIMEOUT:
                    logger.warning(f"UTSC WebSocket: No files received for {NO_FILE_TIMEOUT}s, closing")
                    ws.send(json.dumps({
                        'type': 'error',
                        'message': f'No UTSC capture files received after {NO_FILE_TIMEOUT}s. Check CMTS TFTP destination.'
                    }))
                    break
                
                # Collect new files continuously
                files = _all_candidate_files(tftp_base)
                # Filter: not yet processed
                new_files = [
                    f for f in files
                    if f not in processed_files and os.path.basename(f) not in processed_files
                ]
                
                if len(new_files) > 0:
                    last_new_file_time = current_time
                    logger.info(f"UTSC WebSocket: Found {len(new_files)} new files to process")
                
                for filepath in sorted(new_files, key=os.path.getmtime):
                    processed_files.add(filepath)
                    processed_files.add(os.path.basename(filepath))
                    
                    try:
                        with open(filepath, 'rb') as f:
                            binary_data = f.read()
                        
                        # UTSC file format: 328-byte header + amplitude data
                        # After 328 bytes: signed 16-bit big-endian integers in 0.1 dBmV units
                        
                        if len(binary_data) < 328:
                            continue
                        
                        # Parse amplitude data after 328-byte header
                        amp_data = binary_data[328:]
                        num_samples = len(amp_data) // 2
                        
                        all_amplitudes = []
                        if num_samples > 0:
                            try:
                                # UTSC format: signed 16-bit big-endian, divided by 10.0 for dBmV (0.1 dBmV units)
                                amplitudes = struct.unpack(f'>{num_samples}h', amp_data[:num_samples * 2])
                                all_amplitudes = [a / 10.0 for a in amplitudes]
                            except struct.error as e:
                                logger.error(f"Error unpacking amplitude data: {e}")
                        
                        if all_amplitudes:
                            # Get center freq and span from Redis or use defaults (80 MHz is E6000-supported)
                            try:
                                from app import redis_client
                                config_json = redis_client.get(f'utsc_config:{mac_address}')
                                if config_json:
                                    config = json.loads(config_json)
                                    span_hz = config.get('span_hz', 80000000)
                                    center_freq_hz = config.get('center_freq_hz', 50000000)
                                else:
                                    span_hz = 80000000
                                    center_freq_hz = 50000000
                            except:
                                span_hz = 80000000
                                center_freq_hz = 50000000
                            
                            # Add to buffer
                            file_buffer.append({
                                'filepath': filepath,
                                'amplitudes': all_amplitudes,
                                'span_hz': span_hz,
                                'center_freq_hz': center_freq_hz,
                                'collected_at': current_time
                            })
                            logger.info(f"Parsed {len(all_amplitudes)} amplitude samples from {os.path.basename(filepath)} - Buffer size now: {len(file_buffer)}")
                    except Exception as e:
                        logger.error(f"Error parsing UTSC file {filepath}: {e}")
                
                # Wait for initial buffer to fill before starting stream (must be exactly target or more)
                if not streaming_started:
                    current_buffer_size = len(file_buffer)
                    logger.info(f"UTSC: Buffer check - size={current_buffer_size}, target={initial_buffer_target}")
                    if current_buffer_size >= initial_buffer_target:
                        streaming_started = True
                        logger.info(f"UTSC WebSocket: Initial buffer of {current_buffer_size} files ready (target was {initial_buffer_target}), starting stream")
                        ws.send(json.dumps({
                            'type': 'buffering_complete',
                            'message': f'Buffered {len(file_buffer)} samples, starting stream',
                            'buffer_size': len(file_buffer)
                        }))
                    else:
                        # Send buffering status
                        if current_time - last_heartbeat > 2:
                            ws.send(json.dumps({
                                'type': 'buffering',
                                'message': f'Buffering... {len(file_buffer)}/{initial_buffer_target} samples',
                                'buffer_size': len(file_buffer),
                                'target': initial_buffer_target
                            }))
                            last_heartbeat = current_time
                
                # Stream from buffer at configured rate (only after initial buffering)
                if streaming_started and file_buffer and (current_time - last_stream_time) >= stream_interval:
                    item = file_buffer.popleft()
                    last_stream_time = current_time
                    
                    amplitudes = item['amplitudes']
                    num_bins = len(amplitudes)
                    
                    # UTSC amplitudes are normalized/linear (0...1), need to convert to dBmV
                    # Mapping: 0.0 → -60 dBmV, 1.0 → -10 dBmV (realistic upstream PSD range)
                    raw_amplitudes = [max(-60.0, -60.0 + v * 50.0) for v in amplitudes[:1600]]
                    actual_bins = len(raw_amplitudes)
                    
                    # Calculate correct axis: span over actual bins sent
                    span_hz = item['span_hz']
                    center_freq_hz = item['center_freq_hz']
                    freq_start_hz = center_freq_hz - (span_hz / 2)
                    freq_step_hz = span_hz / actual_bins if actual_bins > 0 else 1
                    
                    # Send in new format (spectrum analyzer expects this)
                    message = {
                        'type': 'spectrum',
                        'timestamp': current_time,
                        'filename': os.path.basename(item['filepath']),
                        'buffer_size': len(file_buffer),
                        'plot': None,
                        'raw_data': {
                            # New format (preferred by spectrum analyzer)
                            'freq_start_hz': freq_start_hz,
                            'freq_step_hz': freq_step_hz,
                            'bins': raw_amplitudes,  # Now in dBmV/MHz
                            # Metadata
                            'span_hz': span_hz,
                            'center_freq_hz': center_freq_hz
                        }
                    }
                    
                    try:
                        ws.send(json.dumps(message))
                    except Exception as send_err:
                        logger.error(f"Failed to send UTSC data: {send_err}")
                        raise
                
                # Send heartbeat
                if current_time - last_heartbeat > heartbeat_interval:
                    ws.send(json.dumps({
                        'type': 'heartbeat',
                        'timestamp': current_time,
                        'buffer_size': len(file_buffer),
                        'elapsed': elapsed
                    }))
                    last_heartbeat = current_time
                
                time.sleep(0.05)  # 50ms polling
                    
        except Exception as e:
            logger.error(f"UTSC WebSocket error: {e}", exc_info=True)
            raise
        finally:
            logger.info(f"UTSC WebSocket closing for {mac_address}")
            # Only a direct analyzer session stops the run it started. Normal GUI
            # sessions are stopped by the matching authenticated stop endpoint.
            if owns_utsc and rf_port and cmts_ip:
                logger.info(
                    "UTSC WebSocket: stopping owned run on port %s cfg_index=%s "
                    "after %s successful start(s)",
                    rf_port,
                    resolved_cfg_index,
                    run_counter,
                )
                stop_result = stop_utsc_via_pypnm(
                    cmts_ip,
                    int(rf_port),
                    community,
                    write_community=write_community,
                    cfg_index=resolved_cfg_index,
                )
                if not stop_result.get('success'):
                    logger.warning(
                        "UTSC stop failed on cleanup: %s",
                        stop_result.get('error') or stop_result,
                    )
            
            _utsc_sessions.pop(session_id, None)
            logger.info(f"UTSC WebSocket closed for {mac_address}")
            logger.info(f"UTSC WebSocket closed for {mac_address} after {run_counter} runs")
    
    logger.info("WebSocket UTSC endpoint registered at /ws/utsc/<mac>")
    return sock
