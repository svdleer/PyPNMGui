# PyPNM Web GUI - PyPNM Routes
#
# Complete PyPNM API integration with plot support

from flask import Blueprint, request, jsonify, send_file, current_app
from typing import Dict, Any
import logging
import math
import os
import tempfile
import time
import zipfile
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json

# Import spectrum plotter for generating matplotlib plots
from app.core.spectrum_plotter import generate_spectrum_plot_from_data
from app.core.constellation_plotter import generate_constellation_plots_from_data

logger = logging.getLogger(__name__)

PYPNM_API_TIMEOUT = int(os.environ.get('PYPNM_API_TIMEOUT', '45'))
PYPNM_OFDMA_TIMEOUT = int(os.environ.get('PYPNM_OFDMA_TIMEOUT', '120'))
DEFAULT_VELOCITY_FACTOR = 0.87
MIN_VELOCITY_FACTOR = 0.50
MAX_VELOCITY_FACTOR = 1.00


def _parse_velocity_factor(value: object) -> float:
    """Validate a user-selected velocity factor without coercing booleans."""
    if value is None:
        return DEFAULT_VELOCITY_FACTOR
    if isinstance(value, bool):
        raise ValueError('velocity_factor must be a number, not a boolean')
    try:
        velocity_factor = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('velocity_factor must be a finite number from 0.50 to 1.00') from exc
    if not math.isfinite(velocity_factor):
        raise ValueError('velocity_factor must be a finite number from 0.50 to 1.00')
    if not MIN_VELOCITY_FACTOR <= velocity_factor <= MAX_VELOCITY_FACTOR:
        raise ValueError('velocity_factor must be between 0.50 and 1.00 inclusive')
    return velocity_factor

pypnm_bp = Blueprint('pypnm', __name__, url_prefix='/api/pypnm')


def _cm_index_cache_key(cmts_ip: str, mac_address: str) -> str:
    return f"cm_index:{cmts_ip}:{mac_address.lower()}"

# Redis client for caching
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
except:
    redis_client = None
    REDIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fiber node scan progress helpers
# ---------------------------------------------------------------------------
_SCAN_PROGRESS_TTL = 300   # seconds — Redis key lifetime

# DS chan-est progress when Redis is unavailable.
import threading as _threading
_ds_progress_store: dict = {}
_ds_progress_lock = _threading.Lock()
_scan_abort_store: dict = {}


def _build_tap_profile_dto(preeq_full_data: dict) -> dict:
    """Return display-only tap coordinates without mutating source/DSP data."""
    series = []
    for mac, modem in (preeq_full_data or {}).items():
        for channel in modem.get("channels", []):
            taps = channel.get("taps") or []
            magnitudes = []
            for tap in taps:
                try:
                    value = float(tap.get("magnitude"))
                    magnitudes.append(value if math.isfinite(value) and value >= 0 else 0.0)
                except (AttributeError, TypeError, ValueError):
                    magnitudes.append(0.0)
            if not magnitudes:
                continue
            main_index = channel.get("main_tap_location")
            if not isinstance(main_index, int) or not 0 <= main_index < len(magnitudes):
                main_index = max(range(len(magnitudes)), key=magnitudes.__getitem__)
            main_magnitude = magnitudes[main_index]
            points = []
            for index, magnitude in enumerate(magnitudes):
                relative_db = None
                if magnitude > 0 and main_magnitude > 0:
                    relative_db = round(20.0 * math.log10(magnitude / main_magnitude), 3)
                points.append({
                    "tap_offset": index - main_index,
                    "magnitude": magnitude,
                    "magnitude_db_relative": relative_db,
                })
            series.append({
                "mac_address": str(modem.get("mac") or mac),
                "us_ifindex": channel.get("us_ifindex"),
                "main_tap_location": main_index,
                "sample_period_us": (channel.get("group_delay") or {}).get("sample_period_us"),
                "points": points,
            })
    return {
        "x_axis": "tap_offset",
        "y_axis": "magnitude_db_relative",
        "series": series,
    }


def _set_ds_scan_progress(scan_id: str, **fields):
    """Write DS scan progress to Redis (if available) and in-memory dict."""
    if not scan_id:
        return
    data = {k: str(v) for k, v in fields.items()}
    # Keep an in-memory copy for polling.
    with _ds_progress_lock:
        if scan_id not in _ds_progress_store:
            _ds_progress_store[scan_id] = {}
        _ds_progress_store[scan_id].update(data)
    # Mirror to Redis when available.
    if REDIS_AVAILABLE:
        try:
            key = _scan_progress_key(scan_id)
            redis_client.hset(key, mapping=data)
            redis_client.expire(key, _SCAN_PROGRESS_TTL)
        except Exception:
            pass

def _scan_progress_key(scan_id: str) -> str:
    return f"scan_progress:{scan_id}"

def _scan_abort_key(scan_id: str) -> str:
    return f"scan_abort:{scan_id}"

def _set_scan_abort(scan_id: str, abort: bool):
    if not scan_id:
        return
    with _ds_progress_lock:
        _scan_abort_store[scan_id] = bool(abort)
    if REDIS_AVAILABLE:
        try:
            key = _scan_abort_key(scan_id)
            if abort:
                redis_client.set(key, "1", ex=_SCAN_PROGRESS_TTL)
            else:
                redis_client.delete(key)
        except Exception:
            pass

def _is_scan_abort_requested(scan_id: str) -> bool:
    if not scan_id:
        return False
    with _ds_progress_lock:
        if _scan_abort_store.get(scan_id):
            return True
    if REDIS_AVAILABLE:
        try:
            return bool(redis_client.get(_scan_abort_key(scan_id)))
        except Exception:
            return False
    return False

def _set_scan_progress(scan_id: str, **fields):
    """Write progress fields to Redis (or no-op if unavailable)."""
    if not scan_id or not REDIS_AVAILABLE:
        return
    try:
        key = _scan_progress_key(scan_id)
        redis_client.hset(key, mapping={k: str(v) for k, v in fields.items()})
        redis_client.expire(key, _SCAN_PROGRESS_TTL)
    except Exception:
        pass

@pypnm_bp.route('/ds/chan_est/scan/progress', methods=['GET'])
def get_ds_chan_est_scan_progress():
    """Poll current progress for a running DS suckout scan."""
    scan_id = request.args.get('scan_id', '')
    if not scan_id:
        return jsonify({"found": False})
    # Check in-memory store first (always populated), then Redis
    with _ds_progress_lock:
        raw = dict(_ds_progress_store.get(scan_id, {}))
    if not raw and REDIS_AVAILABLE:
        try:
            raw = redis_client.hgetall(_scan_progress_key(scan_id)) or {}
        except Exception:
            raw = {}
    if not raw:
        return jsonify({"found": False})
    return jsonify({
        "found":     True,
        "total":     int(raw.get('total', 0)),
        "started":   int(raw.get('started', 0)),
        "completed": int(raw.get('completed', 0)),
        "pct":       int(raw.get('pct', 0)),
        "modem":     raw.get('modem', ''),
        "action":    raw.get('action', ''),
    })


@pypnm_bp.route('/cmts/ofdma/rxmer/fibernode/scan/progress', methods=['GET'])
def get_fibernode_scan_progress():
    """Poll current progress for a running fiber node scan."""
    scan_id = request.args.get('scan_id', '')
    if not scan_id or not REDIS_AVAILABLE:
        return jsonify({"found": False})
    try:
        raw = redis_client.hgetall(_scan_progress_key(scan_id))
        if not raw:
            return jsonify({"found": False})
        return jsonify({
            "found":       True,
            "step":        int(raw.get('step', 0)),
            "total":       int(raw.get('total', 0)),
            "modem":       raw.get('modem', ''),
            "modem_idx":   int(raw.get('modem_idx', 0)),
            "modem_total": int(raw.get('modem_total', 0)),
            "channel":     raw.get('channel', ''),
            "action":      raw.get('action', ''),
            "phase":       raw.get('phase', ''),
            "phase_current": int(raw.get('phase_current', 0)),
            "phase_total": int(raw.get('phase_total', 0)),
            "pct":         float(raw.get('pct', 0)),
            "done":        raw.get('done', 'false') == 'true',
        })
    except Exception as e:
        return jsonify({"found": False, "error": str(e)})


_SCAN_RESULT_TTL = 3600  # 1 hour


def _store_scan_result(scan_id: str, result: dict):
    """Persist scan result to Redis for async retrieval."""
    if not scan_id or not REDIS_AVAILABLE:
        return
    try:
        import json as _json
        redis_client.set(f"scan_result:{scan_id}", _json.dumps(result), ex=_SCAN_RESULT_TTL)
    except Exception:
        pass


@pypnm_bp.route('/cmts/ofdma/rxmer/fibernode/scan/result', methods=['GET'])
def get_fibernode_scan_result():
    """Return stored result for a completed fibernode scan (async mode)."""
    import json as _json
    scan_id = request.args.get('scan_id', '')
    if not scan_id or not REDIS_AVAILABLE:
        return jsonify({"found": False})
    try:
        raw = redis_client.get(f"scan_result:{scan_id}")
        if not raw:
            return jsonify({"found": False})
        return jsonify({"found": True, **_json.loads(raw)})
    except Exception as e:
        return jsonify({"found": False, "error": str(e)})


@pypnm_bp.route('/cmts/ofdma/rxmer/fibernode/scan/abort', methods=['POST'])
def abort_fibernode_scan():
    """Request cooperative cancellation of a running fiber node scan."""
    data = request.get_json(silent=True) or {}
    scan_id = (data.get('scan_id') or '').strip()
    if not scan_id:
        return jsonify({"success": False, "error": "scan_id required"}), 400
    _set_scan_abort(scan_id, True)
    _set_scan_progress(scan_id, action='Abort requested…', done='false')
    return jsonify({"success": True, "scan_id": scan_id})


def get_default_community():
    """Get default SNMP community for modems based on mode."""
    return os.environ.get('MODEM_COMMUNITY', os.environ.get('CM_SNMP_COMMUNITY', 'private'))


def get_default_write_community():
    """Get default SNMP write community for modem PNM operations (SET)."""
    return os.environ.get('MODEM_WRITE_COMMUNITY', 'private')


def get_cmts_community():
    """Get default SNMP read community for CMTS operations."""
    return os.environ.get('CMTS_COMMUNITY', 'public')


def get_cmts_write_community():
    """Get default SNMP write community for CMTS operations."""
    return os.environ.get('CMTS_WRITE_COMMUNITY', 'private')


def get_alternate_tftp():
    """CM modem-side TFTP IP (TFTP_ALT → TFTP_IPV4_ALT)."""
    return os.environ.get('TFTP_ALT') or os.environ.get('TFTP_IPV4_ALT', '127.0.0.1')


def get_tftp_for_cm() -> str:
    """Return TFTP IP for CM modem-side PNM uploads."""
    return get_alternate_tftp()


def get_community_for_cmts(cmts_ip: str) -> str:
    """Return SNMP read community for a CMTS IP, looked up from config."""
    from app.core.cmts_provider import CMTSProvider
    try:
        cmts = CMTSProvider.get_cmts_by_ip(cmts_ip)
        if cmts and cmts.get('snmp_community'):
            return cmts['snmp_community']
    except Exception:
        pass
    return get_cmts_community()


def get_write_community_for_cmts(cmts_ip: str) -> str:
    """Return SNMP write community for a CMTS IP, looked up from config."""
    from app.core.cmts_provider import CMTSProvider
    try:
        cmts = CMTSProvider.get_cmts_by_ip(cmts_ip)
        if cmts and cmts.get('write_community'):
            return cmts['write_community']
        if cmts and cmts.get('snmp_community'):
            return cmts['snmp_community']
    except Exception:
        pass
    return get_cmts_write_community()


# ============== Compatibility Routes ==============
# These routes support frontend calls using /modem/<mac>/... pattern
# The canonical routes are /channel-stats/<mac>, /event-log/<mac>, etc.

@pypnm_bp.route('/modem/<mac_address>/channel-stats', methods=['POST'])
def modem_channel_stats_compat(mac_address):
    """Compatibility route - redirects to /channel-stats/<mac>."""
    return channel_stats(mac_address)


@pypnm_bp.route('/modem/<mac_address>/event-log', methods=['POST'])
def modem_event_log(mac_address):
    """Get modem event log via PyPNM API."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', get_default_community())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    # Status code translation for better user messages
    STATUS_MESSAGES = {
        1: "Modem not reachable (ping failed)",
        2: "Modem SNMP not responding - check community string or modem SNMP configuration",
        25: "MAC address mismatch",
    }
    
    try:
        result = client.get_event_log(mac_address, modem_ip, community)
        
        if result.get('status') == 0:
            return jsonify(result)
        else:
            # Get user-friendly message
            status_code = result.get('status', -1)
            message = result.get('message', '')
            
            # Check if message contains "SNMP check failed" or similar
            if 'SNMP check failed' in message:
                try:
                    error_code = int(message.split(':')[-1].strip())
                    message = STATUS_MESSAGES.get(error_code, message)
                except:
                    pass
            elif status_code in STATUS_MESSAGES:
                message = STATUS_MESSAGES[status_code]
            elif not message:
                message = f"Failed to get event log (error code: {status_code})"
            
            return jsonify({
                "status": "error",
                "message": message
            }), 500
            
    except Exception as e:
        logger.error(f"Event log failed for {mac_address}: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@pypnm_bp.route('/modem/<mac_address>/pre-eq', methods=['POST'])
def modem_pre_eq(mac_address):
    """Get upstream pre-equalization via PyPNM API."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', get_default_write_community())
    tftp_ip = data.get('tftp_ip', get_tftp_for_cm())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    try:
        result = client.get_us_ofdma_pre_equalization(
            mac_address, modem_ip, tftp_ip, community
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Pre-EQ failed for {mac_address}: {e}")
        return jsonify({
            "status": "error", 
            "message": str(e)
        }), 500


# ============== End Compatibility Routes ==============


@pypnm_bp.route('/measurements/<measurement_type>/<mac_address>', methods=['POST'])
def pnm_measurement(measurement_type, mac_address):
    """
    Unified PNM measurement endpoint.
    
    Supported types:
    - rxmer: RxMER per subcarrier
    - spectrum: Downstream spectrum analyzer (DOCSIS 3.x/4.0)
    - us_spectrum: Upstream spectrum analyzer (UTSC)
    - channel_estimation: Channel estimation coefficients
    - modulation_profile: Modulation profile
    - fec_summary: FEC summary stats
    - histogram: Power histogram
    - constellation: Constellation display
    - us_pre_eq: Upstream OFDMA pre-equalization
    
    POST body:
    {
        "modem_ip": "10.x.x.x",
        "community": "optional",
        "output_type": "json" | "archive",
        "fec_summary_type": 2,  # Only for FEC (2=10min, 3=24hr)
        "sample_duration": 60    # Only for histogram
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    # Use write community for PNM operations that require SET
    community = data.get('community', get_default_write_community())
    # CM PNM operations (modem-side) always use alternate TFTP —
    # modems upload to a server reachable from the modem subnet.
    tftp_ip = data.get('tftp_ip', get_tftp_for_cm())
    output_type = data.get('output_type', 'json')
    
    # Spectrum analyzer: always use JSON mode from PyPNM, then generate plots ourselves
    if measurement_type == 'spectrum':
        output_type = 'json'  # PyPNM returns JSON, we generate plots in backend
        requested_archive = data.get('output_type') == 'archive'  # Track if user wanted archive
    # PyPNM only supports json output currently - archive mode falls back to json
    elif output_type == 'archive':
        # Keep archive mode - PyPNM will return ZIP with plots
        requested_archive = True
    else:
        requested_archive = False
    
    if not modem_ip and measurement_type != 'us_spectrum':
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    # Route to appropriate method
    try:
        if measurement_type == 'rxmer':
            result = client.get_rxmer_capture(
                mac_address, modem_ip, tftp_ip, community, 
                tftp_ipv6="::1", output_type=output_type
            )
        elif measurement_type == 'spectrum':
            result = client.get_spectrum_capture(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
        elif measurement_type == 'us_spectrum':
            # UTSC is CMTS-based, not modem-based - requires different parameters
            cmts_ip = data.get('cmts_ip')
            rf_port_ifindex = data.get('rf_port_ifindex')
            trigger_mode = data.get('trigger_mode', 2)  # 2=FreeRunning
            center_freq_hz = data.get('center_freq_hz', 30000000)  # 30 MHz
            span_hz = data.get('span_hz', 80000000)  # 80 MHz
            num_bins = data.get('num_bins', 800)
            filename = data.get('filename', f'utsc_{mac_address.replace(":", "")}')
            cm_mac = data.get('cm_mac') if trigger_mode == 6 else None
            logical_ch_ifindex = data.get('logical_ch_ifindex')
            
            if not cmts_ip or rf_port_ifindex is None:
                return jsonify({
                    "status": "error", 
                    "message": "cmts_ip and rf_port_ifindex required for UTSC"
                }), 400
            
            # UTSC is CMTS-side — use CMTS write community, not modem community
            cmts_write = get_write_community_for_cmts(cmts_ip)

            # Stop any existing UTSC measurement before starting a new one
            try:
                logger.info(f"Stopping any existing UTSC on {cmts_ip} port {rf_port_ifindex}")
                import time as _time
                client.stop_utsc(cmts_ip, rf_port_ifindex, cmts_write)
                _time.sleep(0.5)  # Brief delay to ensure stop completes
            except Exception as e:
                logger.warning(f"Failed to stop existing UTSC (may not be running): {e}")
            
            # Convert repeat_period_ms to microseconds for the API
            # Casa minimum: 400ms (satisfies both 100ms floor and 120s/300files constraints)
            repeat_period_ms = data.get('repeat_period_ms', 400)
            repeat_period_us = repeat_period_ms * 1000

            # Configure UTSC
            result = client.configure_utsc(
                cmts_ip=cmts_ip,
                rf_port_ifindex=rf_port_ifindex,
                community=cmts_write,
                trigger_mode=trigger_mode,
                center_freq_hz=center_freq_hz,
                span_hz=span_hz,
                num_bins=num_bins,
                output_format=data.get('output_format') or None,  # None = auto-detect
                repeat_period_us=repeat_period_us,
                freerun_duration_ms=data.get('freerun_duration_ms', 0),  # 0 = auto (service clamps to 120s min)
                filename=filename,
                cm_mac_address=cm_mac,
                logical_ch_ifindex=logical_ch_ifindex
            )
            
            if result.get('success'):
                # Start the capture — use cfg_index returned by configure (probed index)
                resolved_cfg_index = result.get('cfg_index', 0)
                start_result = client.start_utsc(
                    cmts_ip, rf_port_ifindex, cmts_write,
                    cfg_index=resolved_cfg_index
                )
                if not start_result.get('success'):
                    result = start_result
            
            # Store UTSC config in Redis for later plot generation
            try:
                redis_client.setex(
                    f'utsc_config:{mac_address}',
                    3600,  # 1 hour TTL
                    json.dumps({
                        'span_hz': span_hz,
                        'center_freq_hz': center_freq_hz,
                        'num_bins': num_bins
                    })
                )
            except Exception as e:
                logger.warning(f"Failed to cache UTSC config: {e}")
        elif measurement_type == 'channel_estimation':
            result = client.get_channel_estimation(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
        elif measurement_type == 'modulation_profile':
            result = client.get_modulation_profile(
                mac_address, modem_ip, tftp_ip, community
            )
            # New endpoint returns success bool, normalize to status int for downstream handling
            if 'status' not in result:
                result['status'] = 0 if result.get('success') else 1
                result['message'] = result.get('error') or 'Modulation profile captured'
        elif measurement_type == 'fec_summary':
            fec_type = data.get('fec_summary_type', 2)
            result = client.get_fec_summary(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", fec_summary_type=fec_type, output_type=output_type
            )
        elif measurement_type == 'histogram':
            duration = data.get('sample_duration', 60)
            result = client.get_histogram(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", sample_duration=duration, output_type=output_type
            )
        elif measurement_type == 'constellation':
            logger.info(f"=== CONSTELLATION DEBUG START ===")
            logger.info(f"Requesting constellation for {mac_address} at {modem_ip}")
            logger.info(f"Output type: {output_type}, Requested archive: {requested_archive}")
            result = client.get_constellation_display(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
            logger.info(f"=== CONSTELLATION RAW RESULT ===")
            logger.info(f"Result type: {type(result)}")
            if isinstance(result, dict):
                logger.info(f"Result keys: {result.keys()}")
                logger.info(f"Result status: {result.get('status')}")
                logger.info(f"Result message: {result.get('message')}")
                if 'data' in result:
                    logger.info(f"Data keys: {result['data'].keys() if isinstance(result['data'], dict) else 'not a dict'}")
            elif isinstance(result, bytes):
                logger.info(f"Result is bytes, length: {len(result)}")
            else:
                logger.info(f"Result: {result}")
            
            # Generate matplotlib plots for constellation data (like other measurements)
            # PyPNM returns: {data: [{channel_id, samples: [(I, Q), ...]}, ...]}
            if isinstance(result, dict) and result.get('status') == 0:
                raw_data = result.get('data', [])
                if isinstance(raw_data, list) and len(raw_data) > 0:
                    try:
                        constellation_plots = generate_constellation_plots_from_data(raw_data, mac_address)
                        if constellation_plots:
                            # Add plots to result (like other measurements)
                            if 'plots' not in result:
                                result['plots'] = []
                            result['plots'].extend(constellation_plots)
                            logger.info(f"Generated {len(constellation_plots)} matplotlib constellation plots")
                    except Exception as e:
                        logger.error(f"Failed to generate constellation plots: {e}", exc_info=True)
            
            logger.info(f"=== CONSTELLATION DEBUG END ===")
        elif measurement_type == 'us_pre_eq':
            result = client.get_us_ofdma_pre_equalization(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
        else:
            return jsonify({
                "status": "error",
                "message": f"Unknown measurement type: {measurement_type}"
            }), 400
        
        # Handle archive (tar.gz) response - fetch matplotlib plots from PyPNM
        if requested_archive and isinstance(result, bytes):
            # Check if the "bytes" is actually a JSON error response
            if len(result) < 1000:
                try:
                    error_json = json.loads(result.decode('utf-8'))
                    if isinstance(error_json, dict) and error_json.get('status', 0) != 0:
                        logger.error(f"PyPNM returned error: {error_json}")
                        return jsonify({
                            "status": error_json.get('status', 'error'),
                            "message": error_json.get('message', 'Measurement failed'),
                            "mac_address": mac_address
                        }), 400
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # Not JSON, continue processing as binary
            
            # PyPNM returns binary archive file (ZIP or tar.gz)
            import tarfile
            import zipfile
            import io
            import base64
            from datetime import datetime
            
            # Detect archive type
            is_zip = result.startswith(b'PK')  # ZIP magic number
            
            # Save archive file
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            archive_ext = 'zip' if is_zip else 'tar.gz'
            archive_filename = f"{measurement_type}_{mac_address}_{timestamp}.{archive_ext}"
            archive_path = f"/app/data/{archive_filename}"
            
            with open(archive_path, 'wb') as f:
                f.write(result)
            
            # Extract PNG images and JSON from archive
            plots = []
            json_data = None
            try:
                if is_zip:
                    # Handle ZIP archive
                    with zipfile.ZipFile(io.BytesIO(result), 'r') as zf:
                        archive_files = zf.namelist()
                        logger.info(f"ZIP archive contains {len(archive_files)} files")
                        for filename in archive_files:
                            if filename.endswith('.png'):
                                img_data = zf.read(filename)
                                plots.append({
                                    'filename': filename.split('/')[-1],  # Get basename
                                    'data': base64.b64encode(img_data).decode('utf-8')
                                })
                            elif filename.endswith('.json'):
                                json_content = zf.read(filename).decode('utf-8')
                                json_data = json.loads(json_content)
                        logger.info(f"Extracted {len(plots)} PNG plots from ZIP")
                else:
                    # Handle tar.gz archive
                    with tarfile.open(fileobj=io.BytesIO(result), mode='r:gz') as tf:
                        archive_files = tf.getnames()
                        logger.info(f"TAR archive contains {len(archive_files)} files")
                        for filename in archive_files:
                            if filename.endswith('.png'):
                                member = tf.getmember(filename)
                                img_data = tf.extractfile(member).read()
                                plots.append({
                                    'filename': filename.split('/')[-1],  # Get basename
                                    'data': base64.b64encode(img_data).decode('utf-8')
                                })
                            elif filename.endswith('.json'):
                                member = tf.getmember(filename)
                                json_content = tf.extractfile(member).read().decode('utf-8')
                                json_data = json.loads(json_content)
                        logger.info(f"Extracted {len(plots)} PNG plots from TAR")
            except Exception as e:
                logger.error(f"Failed to extract from archive: {e}")
            
            # For constellation, generate matplotlib plots from extracted JSON data
            # (PyPNM constellation archives don't contain pre-generated PNGs)
            if measurement_type == 'constellation' and json_data and len(plots) == 0:
                logger.info(f"Generating constellation plots from extracted JSON data")
                raw_data = json_data if isinstance(json_data, list) else json_data.get('data', [])
                if isinstance(raw_data, list) and len(raw_data) > 0:
                    try:
                        constellation_plots = generate_constellation_plots_from_data(raw_data, mac_address)
                        if constellation_plots:
                            plots.extend(constellation_plots)
                            logger.info(f"Generated {len(constellation_plots)} matplotlib constellation plots")
                    except Exception as e:
                        logger.error(f"Failed to generate constellation plots: {e}", exc_info=True)
            
            # If we extracted JSON, return it with plots
            if json_data:
                response = json_data
                # CRITICAL: Ensure status field exists (frontend requires it)
                if 'status' not in response:
                    response['status'] = 0  # SUCCESS - use PyPNM status codes
                response['plots'] = plots
                response['output_type'] = 'archive'
                response['archive_file'] = archive_filename
                response['download_url'] = f"/api/pypnm/download/{archive_filename}"
                return jsonify(response)
            
            # Fallback if no JSON found
            return jsonify({
                "status": 0,
                "message": f"Measurement complete - {len(plots)} plots generated",
                "output_type": "archive",
                "archive_file": archive_filename,
                "download_url": f"/api/pypnm/download/{archive_filename}",
                "plots": plots,
                "mac_address": mac_address
            })
        
        # Handle archive (ZIP) response - fetch matplotlib plots from PyPNM
        if requested_archive and result.get('status') == 0:
            # PyPNM returns archive data, extract plots and save ZIP
            import zipfile
            import io
            import base64
            from datetime import datetime
            
            # Get the archive data from PyPNM
            archive_data = result.get('archive_data')
            if archive_data:
                # Save ZIP and extract plot images
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                zip_filename = f"{measurement_type}_{mac_address}_{timestamp}.zip"
                zip_path = f"/app/data/{zip_filename}"
                
                # Write ZIP file
                with open(zip_path, 'wb') as f:
                    f.write(base64.b64decode(archive_data) if isinstance(archive_data, str) else archive_data)
                
                # Extract PNG images from ZIP
                plots = []
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        for filename in zf.namelist():
                            if filename.endswith('.png'):
                                img_data = zf.read(filename)
                                plots.append({
                                    'filename': filename,
                                    'data': base64.b64encode(img_data).decode('utf-8')
                                })
                except Exception as e:
                    logger.error(f"Failed to extract plots: {e}")
                
                return jsonify({
                    "status": 0,
                    "message": result.get('message', 'Archive generated successfully'),
                    "output_type": "archive",
                    "zip_file": zip_filename,
                    "download_url": f"/api/pypnm/download/{zip_filename}",
                    "plots": plots,
                    "data": result.get('data', {})
                })
            
            # Archive data not available, return JSON
            # But fetch matplotlib plots if they were generated
            import glob
            import os
            import base64
            import time
            
            logger.info(f"=== Plot Fetching Debug ===")
            logger.info(f"requested_archive: {requested_archive}")
            logger.info(f"result status: {result.get('status')}")
            
            plots = []
            if result.get('status') == 0:
                # Give PyPNM a moment to finish writing files
                time.sleep(1)
                
                # Look for plots in /pypnm-data/png/
                plot_dir = "/pypnm-data/png"
                logger.info(f"Plot dir exists: {os.path.exists(plot_dir)}")
                
                if os.path.exists(plot_dir):
                    # Find recent plots for this modem
                    mac_clean = mac_address.replace(':', '')
                    pattern = f"{plot_dir}/{mac_clean}*.png"
                    plot_files = glob.glob(pattern)
                    logger.info(f"Pattern: {pattern}")
                    logger.info(f"Found {len(plot_files)} total files")
                    
                    # Get files modified in the last 60 seconds
                    recent_time = time.time() - 60
                    plot_files = [f for f in plot_files if os.path.getmtime(f) > recent_time]
                    logger.info(f"Found {len(plot_files)} recent files (last 60s)")
                    plot_files.sort(key=os.path.getmtime, reverse=True)
                    
                    for filepath in plot_files[:10]:  # Max 10 plots
                        try:
                            with open(filepath, 'rb') as f:
                                img_data = f.read()
                                plots.append({
                                    'filename': os.path.basename(filepath),
                                    'data': base64.b64encode(img_data).decode('utf-8')
                                })
                                logger.info(f"Added plot: {os.path.basename(filepath)}")
                        except Exception as e:
                            logger.error(f"Failed to read plot {filepath}: {e}")
            
            logger.info(f"Returning {len(plots)} plots")
            
            # For spectrum analyzer, generate matplotlib plots from the JSON data
            if measurement_type == 'spectrum' and result.get('status') == 0:
                spectrum_data = result.get('data', {})
                if spectrum_data:
                    logger.info(f"Generating spectrum plot for {mac_address}")
                    try:
                        spectrum_plot = generate_spectrum_plot_from_data(spectrum_data, mac_address)
                        if spectrum_plot:
                            plots.append(spectrum_plot)
                            logger.info(f"Successfully generated spectrum plot: {spectrum_plot['filename']}")
                    except Exception as e:
                        logger.error(f"Failed to generate spectrum plot: {e}", exc_info=True)
            
            return jsonify({
                "status": 0,
                "message": result.get('message', 'Measurement complete'),
                "plots": plots,  # Matplotlib PNG plots
                "data": result.get('data', {})
            })
        
        # Handle errors
        if result.get('status') != 0:
            return jsonify(result), 500
        
        # Interactive JSON mode returns structured measurement data only.
        # Archive/Matplotlib handling has already returned above; attaching recent
        # PNG files here can mix stale plots into JSON responses and suppress the
        # browser's Chart.js renderer.
        result['plots'] = []
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"PNM measurement {measurement_type} failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@pypnm_bp.route('/channel-stats/<mac_address>', methods=['POST'])
def channel_stats(mac_address):
    """
    Get comprehensive channel statistics with profile information.
    
    Uses optimized PyPNM API endpoint with parallel bulk walks via agent (~10s).
    
    Returns DS/US channel info including:
    - Channel type (SC-QAM, OFDM, ATDMA, OFDMA)
    - Active profiles
    - Signal quality metrics
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community') or get_default_community()
    cmts_ip = data.get('cmts_ip')
    cmts_community = data.get('cmts_community') or get_cmts_community()
    # Full stats by default for GUI completeness.
    # Clients can explicitly set cmts_stats=false for lean mode.
    cmts_stats = bool(data.get('cmts_stats', True))
    # Experimental speed mode: compact SNMP roots with parser-compatible rebucketing.
    # Default OFF — broad root walks (esp. docsIf31) return thousands of OIDs
    # on D3.1 modems, causing agent timeouts.  Canonical tables are smaller and
    # more reliable with the serialized parallel-walk agent.
    experimental_compact_walk = bool(data.get('experimental_compact_walk', False))
    # Slow CMTS can require longer CMTS walk budget for cm-index/rxmer/profile tables.
    cmts_task_timeout_s = float(data.get('cmts_task_timeout_s', 60.0))
    cm_index = data.get('cm_index')

    # Reuse known cm_index from redis cache if caller didn't include it.
    if cm_index is None and cmts_ip and REDIS_AVAILABLE:
        try:
            cached = redis_client.get(_cm_index_cache_key(cmts_ip, mac_address))
            if cached:
                cm_index = int(cached)
                logger.info(f"Using cached cm_index={cm_index} for {mac_address} on {cmts_ip}")
        except Exception as e:
            logger.debug(f"Failed to read cached cm_index: {e}")
    # CM operations always use alternate TFTP
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    # Use optimized PyPNM API endpoint (parallel bulk walks via agent)
    client = PyPNMClient()
    payload = {
        'mac_address': mac_address,
        'modem_ip': modem_ip,
        'community': community,
        'cmts_stats': cmts_stats,
        'experimental_compact_walk': experimental_compact_walk,
        'cmts_task_timeout_s': cmts_task_timeout_s,
        'skip_connectivity_check': True,  # modem is known online from enrichment; skip redundant 5s snmp_get
    }

    if cm_index is not None:
        payload['cm_index'] = cm_index
    
    # Add CMTS info for fiber node lookup if available
    if cmts_ip:
        payload['cmts_ip'] = cmts_ip
        payload['cmts_community'] = cmts_community
    
    result = client._post('/cm/channel-stats', payload)

    # Pass CMTS-side data through even on modem-side failure so downstream/
    # upstream tables can still show partial results when available.
    has_data = bool(result.get('downstream') or result.get('upstream') or result.get('ofdm_stats'))
    if result.get('success') or has_data:
        return jsonify({
            "success": result.get('success', False),
            "mac_address": mac_address,
            "status": 0 if result.get('success') else result.get('status', -1),
            "error": result.get('error'),
            "fiber_node": result.get('fiber_node'),
            "downstream": result.get('downstream', {}),
            "upstream": result.get('upstream', {}),
            "ofdm_stats": result.get('ofdm_stats'),
            "timing": result.get('timing', {})
        })

    # All SNMP walks failed entirely — return the error so the GUI can
    # display it. Do not fall back to legacy calls: they hit the same
    # unreachable modem and produce the same 10s-per-table timeout, making
    # things worse and masking the real problem.
    logger.warning(f"channel-stats failed for {mac_address}: {result.get('error')}")
    return jsonify({
        "success": False,
        "mac_address": mac_address,
        "status": result.get('status', -1),
        "error": result.get('error') or "SNMP walk failed — modem unreachable or SNMP not responding",
    }), 200


def _channel_stats_legacy(mac_address: str, modem_ip: str, community: str):
    """Legacy channel stats using 4 separate PyPNMClient calls."""
    from app.core.pypnm_client import PyPNMClient
    import concurrent.futures
    
    def get_scqam():
        return PyPNMClient().get_ds_scqam_stats(mac_address, modem_ip, community)
    
    def get_ofdm():
        return PyPNMClient().get_ds_ofdm_stats(mac_address, modem_ip, community)
    
    def get_atdma():
        return PyPNMClient().get_us_atdma_stats(mac_address, modem_ip, community)
    
    def get_ofdma():
        return PyPNMClient().get_us_ofdma_stats(mac_address, modem_ip, community)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_scqam = executor.submit(get_scqam)
        future_ofdm = executor.submit(get_ofdm)
        future_atdma = executor.submit(get_atdma)
        future_ofdma = executor.submit(get_ofdma)
        
        ds_scqam = future_scqam.result()
        ds_ofdm = future_ofdm.result()
        us_atdma = future_atdma.result()
        us_ofdma = future_ofdma.result()
    
    downstream = {
        "scqam": {
            "type": "SC-QAM (DOCSIS 3.0)",
            "channels": _extract_scqam_channels(ds_scqam),
            "count": len(_extract_scqam_channels(ds_scqam))
        },
        "ofdm": {
            "type": "OFDM (DOCSIS 3.1)",
            "channels": _extract_ofdm_channels(ds_ofdm),
            "count": len(_extract_ofdm_channels(ds_ofdm))
        }
    }
    
    upstream = {
        "atdma": {
            "type": "ATDMA (DOCSIS 3.0)",
            "channels": _extract_atdma_channels(us_atdma),
            "count": len(_extract_atdma_channels(us_atdma))
        },
        "ofdma": {
            "type": "OFDMA (DOCSIS 3.1)",
            "channels": _extract_ofdma_channels(us_ofdma),
            "count": len(_extract_ofdma_channels(us_ofdma))
        }
    }
    
    return jsonify({
        "mac_address": mac_address,
        "status": 0,
        "downstream": downstream,
        "upstream": upstream
    })


def _extract_scqam_channels(data: Dict[str, Any]) -> list:
    """Extract SC-QAM channel info."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    
    # Log the raw data for debugging
    logger.debug(f"SC-QAM raw results: {results}")
    
    if isinstance(results, list):
        channels = []
        for ch in results:
            # Data may be nested in 'entry' object (like OFDM/OFDMA)
            entry = ch.get('entry', ch)
            
            # Get frequency - try various DOCSIS 3.0 field names
            freq = entry.get('docsIfDownChannelFrequency',
                   entry.get('frequency', 0))
            
            # Get modulation
            modulation = entry.get('docsIfDownChannelModulation',
                         entry.get('modulation', ''))
            
            # Get power
            power = entry.get('docsIfDownChannelPower',
                    entry.get('power', None))
            
            # Get SNR/RxMER
            snr = entry.get('docsIf3CmStatusUsSnr',
                  entry.get('rxMer',
                  entry.get('snr', None)))
            
            channels.append({
                'channel_id': ch.get('channel_id', entry.get('docsIfDownChannelId',
                              entry.get('ifIndex'))),
                'frequency': freq,
                'frequency_mhz': round(freq / 1000000, 1) if freq and freq > 1000 else freq,
                'modulation': modulation,
                'power': power,
                'snr': snr
            })
        return channels
    
    return []


def _extract_ofdm_channels(data: Dict[str, Any]) -> list:
    """Extract OFDM channel info with profile data, MER, and power."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    
    # Log the raw data for debugging
    logger.debug(f"OFDM raw results: {results}")
    
    if isinstance(results, list):
        channels = []
        for ch in results:
            # Data may be nested in 'entry' object
            entry = ch.get('entry', ch)
            
            # Get frequency - SubcarrierZeroFreq is the start frequency
            freq = entry.get('docsIf31CmDsOfdmChanSubcarrierZeroFreq',
                   entry.get('docsIf31CmDsOfdmChannelLowerFrequency',
                   entry.get('lowerFrequency',
                   entry.get('frequency', 0))))
            
            # PLC frequency is the center/reference frequency
            plc_freq = entry.get('docsIf31CmDsOfdmChanPlcFreq', 0)
            
            # Calculate bandwidth from subcarriers
            num_subcarriers = entry.get('docsIf31CmDsOfdmChanNumActiveSubcarriers', 0)
            subcarrier_spacing = entry.get('docsIf31CmDsOfdmChanSubcarrierSpacing', 50000)  # Default 50kHz
            bandwidth = (num_subcarriers * subcarrier_spacing) if num_subcarriers else 0
            
            # Get power level (in tenths of dBmV)
            power_raw = entry.get('docsIf31CmDsOfdmChannelPower',
                        entry.get('power', 0))
            power_dbmv = power_raw / 10 if power_raw and abs(power_raw) > 100 else power_raw
            
            # Get MER (in tenths of dB)
            mer_raw = entry.get('docsIf31CmDsOfdmChanMer',
                      entry.get('docsIf31CmDsOfdmChanRxMer',
                      entry.get('mer', entry.get('rxMer', 0))))
            mer_db = mer_raw / 10 if mer_raw and abs(mer_raw) > 100 else mer_raw
            
            # Get modulation profile - can be primary modulation type
            modulation = entry.get('docsIf31CmDsOfdmChanModulationFormat',
                         entry.get('modulationFormat',
                         entry.get('modulation', None)))
            
            # Try various field names for profiles
            profiles_raw = entry.get('docsIf31CmDsOfdmProfileStatsProfileList', 
                          entry.get('profiles', 
                          entry.get('activeProfiles', [])))
            
            # Parse profiles
            if isinstance(profiles_raw, str):
                profiles = [int(p.strip()) for p in profiles_raw.split(',') if p.strip().isdigit()]
            elif isinstance(profiles_raw, list):
                profiles = []
                for p in profiles_raw:
                    if isinstance(p, dict):
                        pid = p.get('profileId', p.get('profile_id'))
                        if pid is not None and pid != 255:
                            profiles.append(pid)
                    elif isinstance(p, int) and p != 255:
                        profiles.append(p)
            else:
                profiles = []
            
            channels.append({
                'channel_id': ch.get('channel_id', entry.get('docsIf31CmDsOfdmChanChannelId', 
                              entry.get('channelId'))),
                'frequency': freq,
                'frequency_mhz': round(freq / 1000000, 1) if freq else None,
                'plc_freq_mhz': round(plc_freq / 1000000, 1) if plc_freq else None,
                'bandwidth_mhz': round(bandwidth / 1000000, 1) if bandwidth else None,
                'num_subcarriers': num_subcarriers,
                'subcarrier_spacing_khz': subcarrier_spacing / 1000 if subcarrier_spacing else None,
                'power_dbmv': round(power_dbmv, 1) if power_dbmv else None,
                'mer_db': round(mer_db, 1) if mer_db else None,
                'modulation': modulation,
                'profiles': profiles,
                'ncp_profile': 255 in [p.get('profileId', p) if isinstance(p, dict) else p for p in (profiles_raw if isinstance(profiles_raw, list) else [])],
                'active_profiles': len(profiles)
            })
        return channels
    
    return []


def _extract_atdma_channels(data: Dict[str, Any]) -> list:
    """Extract ATDMA channel info."""
    logger.debug(f"_extract_atdma_channels called with data keys: {list(data.keys())}")
    logger.debug(f"_extract_atdma_channels status check: data.get('status')={data.get('status')}, != 0? {data.get('status') != 0}")
    
    if data.get('status') != 0:
        logger.warning(f"ATDMA data has non-zero status: {data.get('status')}, message: {data.get('message')}")
        return []
    
    results = data.get('results', {})
    
    # Results can be either a dict with 'entries' key or a list
    if isinstance(results, dict):
        logger.debug(f"ATDMA results is dict with keys: {list(results.keys())}")
        entries_list = results.get('entries', [])
    else:
        entries_list = results
    
    # Log the raw data for debugging
    logger.debug(f"ATDMA raw results type: {type(results)}, entries count: {len(entries_list) if isinstance(entries_list, list) else 0}")
    
    if isinstance(entries_list, list):
        channels = []
        for ch in entries_list:
            # Data may be nested in 'entry' object (like OFDM/OFDMA)
            entry = ch.get('entry', ch)
            
            # Get frequency - try various DOCSIS 3.0 field names
            freq = entry.get('docsIfUpChannelFrequency',
                   entry.get('frequency', 0))
            
            # Get modulation/channel type
            modulation = entry.get('docsIfUpChannelType',
                         entry.get('channelType',
                         entry.get('modulation', '')))
            
            # Get TX power
            tx_power = entry.get('docsIf3CmStatusUsTxPower',
                       entry.get('txPower',
                       entry.get('power', None)))
            
            channels.append({
                'channel_id': ch.get('channel_id', entry.get('docsIfUpChannelId',
                              entry.get('ifIndex'))),
                'frequency': freq,
                'frequency_mhz': round(freq / 1000000, 1) if freq and freq > 1000 else freq,
                'modulation': modulation,
                'power': tx_power
            })
        return channels
    
    return []


def _extract_ofdma_channels(data: Dict[str, Any]) -> list:
    """Extract OFDMA channel info with profile data."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    
    # Log the raw data for debugging
    logger.debug(f"OFDMA raw results: {results}")
    
    if isinstance(results, list):
        channels = []
        for ch in results:
            # Data may be nested in 'entry' object
            entry = ch.get('entry', ch)
            
            # Get frequency - SubcarrierZeroFreq is the start frequency
            freq = entry.get('docsIf31CmUsOfdmaChanSubcarrierZeroFreq',
                   entry.get('docsIf31CmUsOfdmaChannelConfiguredCenterFrequency',
                   entry.get('configuredCenterFrequency',
                   entry.get('centerFrequency',
                   entry.get('frequency', 0)))))
            
            # Calculate bandwidth from subcarriers
            num_subcarriers = entry.get('docsIf31CmUsOfdmaChanNumActiveSubcarriers', 0)
            # OFDMA subcarrier spacing is in kHz (usually 25 or 50 kHz)
            subcarrier_spacing_khz = entry.get('docsIf31CmUsOfdmaChanSubcarrierSpacing', 50)
            bandwidth = (num_subcarriers * subcarrier_spacing_khz * 1000) if num_subcarriers else 0
            
            # Get TX power
            tx_power = entry.get('docsIf31CmUsOfdmaChanTxPower', None)
            
            # Get RxMER (from CMTS perspective)
            rx_mer = entry.get('docsIf31CmUsOfdmaChanRxMer', 
                     entry.get('rxMer',
                     entry.get('mer', None)))
            
            # Get current IUC
            current_iuc = entry.get('docsIf31CmUsOfdmaChanIuc',
                         entry.get('currentIuc',
                         entry.get('iuc', None)))
            
            # Get profiles
            profiles_raw = entry.get('docsIf31CmUsOfdmaProfileStatsList',
                          entry.get('activeProfiles',
                          entry.get('profiles', [])))
            
            if isinstance(profiles_raw, str):
                profiles = [int(p.strip()) for p in profiles_raw.split(',') if p.strip().isdigit()]
            elif isinstance(profiles_raw, list):
                profiles = []
                for p in profiles_raw:
                    if isinstance(p, dict):
                        pid = p.get('profileId', p.get('profile_id'))
                        if pid is not None:
                            profiles.append(pid)
                    elif isinstance(p, int):
                        profiles.append(p)
            else:
                profiles = []
            
            # iuc_stats: per-profile IUC stats from docsIf31CmUsOfdmaProfileStatsList
            iuc_stats_raw = entry.get('docsIf31CmUsOfdmaProfileStatsList',
                           entry.get('iuc_stats', []))
            if isinstance(iuc_stats_raw, list):
                iuc_stats = iuc_stats_raw
            else:
                iuc_stats = []

            channels.append({
                'channel_id': ch.get('channel_id', entry.get('docsIf31CmUsOfdmaChanChannelId',
                              entry.get('channelId'))),
                'frequency': freq,
                'frequency_mhz': round(freq / 1000000, 1) if freq and freq > 1000 else freq,
                'bandwidth': round(bandwidth / 1000000, 1) if bandwidth else None,
                'bandwidth_mhz': round(bandwidth / 1000000, 1) if bandwidth else None,
                'num_subcarriers': num_subcarriers,
                'tx_power': tx_power,
                'tx_power_dbmv': round(tx_power / 10, 1) if tx_power is not None else None,
                'rx_mer': round(rx_mer / 10, 1) if rx_mer is not None else None,
                'current_iuc': current_iuc,
                'profiles': profiles,
                # IUC fields for GUI badge display
                'active_iucs': profiles,          # profiles list doubles as active IUC list
                'iuc_list': profiles,             # template uses iuc_list for badge loop
                'iuc_stats': iuc_stats,
            })
        return channels
    
    return []


@pypnm_bp.route('/housekeeping', methods=['POST'])
def housekeeping():
    """Delegate aged UTSC capture housekeeping to authoritative PyPNM storage."""
    from app.core.pypnm_client import PyPNMClient

    data = request.get_json() or {}
    try:
        max_age_days = max(1, int(data.get('max_age_days', 7)))
        result = PyPNMClient().housekeeping_utsc_files(
            max_age_seconds=max_age_days * 86400,
            dry_run=bool(data.get('dry_run', True)),
        )
        if not result.get('success'):
            return jsonify({
                'status': 'error',
                'message': result.get('error') or 'PyPNM housekeeping failed',
            }), 502
        return jsonify({
            'status': 'success',
            'dry_run': result.get('dry_run', True),
            'candidate_count': result.get('candidate_count', 0),
            'deleted_count': result.get('deleted_count', 0),
            'total_size_mb': round(result.get('total_size_bytes', 0) / 1024 / 1024, 2),
            'files': result.get('files', []),
            'truncated': result.get('truncated', False),
        })
    except Exception as exc:
        logger.error("Housekeeping failed: %s", exc)
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@pypnm_bp.route('/download/<filename>', methods=['GET'])
def download_archive(filename):
    """
    Download a PNM archive ZIP file.
    
    GET /api/pypnm/download/<filename>
    """
    import os
    from flask import send_file
    
    file_path = f"/app/data/{filename}"
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "File not found"}), 404
    
    return send_file(
        file_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )


@pypnm_bp.route('/plots/<mac_address>', methods=['GET'])
def get_plots(mac_address):
    """
    Get matplotlib plots generated by PyPNM for a specific modem.
    Plots are stored in PyPNM container at /app/.data/png/
    
    Returns base64-encoded plot images.
    """
    import os
    import base64
    import glob
    from flask import request
    
    # PyPNM stores plots in /pypnm-data/png/ (mounted volume)
    plot_dir = "/pypnm-data/png"
    timestamp = request.args.get('timestamp')  # Optional filter by timestamp
    
    if not os.path.exists(plot_dir):
        return jsonify({
            "status": "error",
            "message": "PyPNM plot directory not accessible. Ensure volume is mounted."
        }), 500
    
    # Find PNG files for this modem (MAC address in filename)
    pattern = f"{plot_dir}/{mac_address.replace(':', '')}*.png"
    plot_files = glob.glob(pattern)
    
    if timestamp:
        plot_files = [f for f in plot_files if timestamp in f]
    
    # Sort by modification time (newest first) and limit to last 50
    plot_files.sort(key=os.path.getmtime, reverse=True)
    plot_files = plot_files[:50]
    
    plots = []
    for filepath in plot_files:
        try:
            with open(filepath, 'rb') as f:
                img_data = f.read()
                plots.append({
                    'filename': os.path.basename(filepath),
                    'data': base64.b64encode(img_data).decode('utf-8'),
                    'timestamp': os.path.getmtime(filepath)
                })
        except Exception as e:
            logger.error(f"Failed to read plot {filepath}: {e}")
    
    return jsonify({
        "status": "success",
        "count": len(plots),
        "plots": plots
    })


# ============== Upstream PNM Routes ==============

@pypnm_bp.route('/upstream/discover-rf-port/<mac_address>', methods=['POST'])
def discover_rf_port(mac_address):
    """
    Fast discovery of the correct UTSC RF port for a modem.
    Uses PyPNM API -> agent SNMP for RF port discovery.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "community": "optional"  // Defaults to CMTS write community
    }
    
    Returns:
    {
        "success": true,
        "rf_port_ifindex": 1078534144,
        "rf_port_description": "MND-GT02-1 us-conn 0",
        "cm_index": 3,
        "us_channels": [843071811, 843071813, ...]
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400
    
    logger.info(f"RF port discovery for {mac_address} on CMTS {cmts_ip}")
    
    try:
        client = PyPNMClient()
        result = client.discover_modem_rf_port(
            cmts_ip=cmts_ip,
            cm_mac_address=mac_address,
            community=community
        )
        
        if not result or not result.get('success'):
            error_msg = result.get('error', 'RF port discovery failed') if result else 'No response'
            return jsonify({"success": False, "error": error_msg}), 404
        
        return jsonify({
            "success": True,
            "rf_port_ifindex": result.get('rf_port_ifindex'),
            "rf_port_description": result.get('rf_port_description', ''),
            "cm_index": result.get('cm_index'),
            "us_channels": result.get('us_channels', [])
        })
        
    except Exception as e:
        logger.error(f"RF port discovery failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/interfaces/<mac_address>', methods=['POST'])
def get_upstream_interfaces(mac_address):
    """
    Get upstream interface information for a modem from CMTS.

    Discovers (per-modem only — no expensive full-CMTS walks):
    1. Modem's UTSC RF port  (discoverRfPort)
    2. Modem's OFDMA channel (ofdma/rxmer/discover)

    Results are cached in Redis for 1 hour so repeat lookups are instant.
    """
    from app.core.pypnm_client import PyPNMClient

    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())

    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400

    # ---- Redis cache check (instant return) ----
    # Versioned cache key to avoid stale payload shape after upstream interface
    # enrichment changes (e.g., active/secondary OFDMA channel metadata).
    cache_key = f"pypnm:upstream_if:v2:{cmts_ip}:{mac_address}"
    if REDIS_AVAILABLE:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                import json as _json
                result = _json.loads(cached)
                result['cached'] = True
                logger.debug(f"upstream_interfaces cache hit for {mac_address}")
                return jsonify(result)
        except Exception as e:
            logger.debug(f"upstream_interfaces cache read error: {e}")

    try:
        client = PyPNMClient()

        # Only per-modem calls — skip the expensive full-CMTS /utsc/ports walk.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as executor:
            rf_modem_future = executor.submit(
                client.discover_modem_rf_port,
                cmts_ip=cmts_ip,
                cm_mac_address=mac_address,
                community=community,
            )
            ofdma_future = executor.submit(
                client.discover_modem_ofdma,
                cmts_ip=cmts_ip,
                cm_mac_address=mac_address,
                community=community,
            )
            rf_modem_result = rf_modem_future.result()
            ofdma_result = ofdma_future.result()

        # ---- Build modem RF port from per-modem discovery ----
        modem_rf_port = None
        cm_index = None
        modem_logical_channel = None
        try:
            if rf_modem_result and rf_modem_result.get('success'):
                cm_index = rf_modem_result.get('cm_index')
                modem_rf_ifindex = rf_modem_result.get('rf_port_ifindex')
                rf_port_description = rf_modem_result.get('rf_port_description', '')
                modem_logical_channel = rf_modem_result.get('logical_channel')

                try:
                    modem_rf_ifindex = int(modem_rf_ifindex) if modem_rf_ifindex is not None else None
                except Exception:
                    modem_rf_ifindex = None

                if modem_rf_ifindex is not None:
                    modem_rf_port = {
                        "ifindex": modem_rf_ifindex,
                        "rf_port_ifindex": modem_rf_ifindex,
                        "description": rf_port_description,
                        "cfg_index": 1,
                        "is_modem_port": True
                    }
                    logger.info(f"Found modem RF port {modem_rf_ifindex} for {mac_address}")
                else:
                    logger.warning(f"Modem RF discovery returned invalid ifIndex for {mac_address}")
        except Exception as e:
            logger.warning(f"Modem RF port discovery error (non-fatal): {e}")

        # scqam_channels = just the modem's own port (no full CMTS walk)
        scqam_channels = [modem_rf_port] if modem_rf_port else []

        # ---- Build OFDMA channels ----
        ofdma_channels = []
        try:
            if ofdma_result and ofdma_result.get('success'):
                if not cm_index:
                    cm_index = ofdma_result.get('cm_index')
                raw_channels = ofdma_result.get('ofdma_channels') or []
                if not raw_channels:
                    single = ofdma_result.get('ofdma_ifindex')
                    if single:
                        raw_channels = [{"ifindex": single, "description": ofdma_result.get('ofdma_description')}]
                for i, ch in enumerate(raw_channels):
                    ifindex = ch.get('ifindex')
                    if ifindex:
                        ofdma_channels.append({
                            "ifindex": ifindex,
                            "ofdma_ifindex": ifindex,
                            "index": i + 1,
                            "description": ch.get('description') or f'OFDMA {ifindex}',
                            "cm_index": cm_index,
                            "active": True,
                            "secondary": False,
                        })
                logger.info(f"Found {len(ofdma_channels)} OFDMA channel(s) for modem {mac_address}")
            else:
                logger.info(f"No OFDMA channel for modem {mac_address}: {ofdma_result.get('error') if ofdma_result else 'No response'}")

            # Fallback: reuse logical_channel from modem RF discovery
            if not ofdma_channels and rf_modem_result and rf_modem_result.get('success'):
                logical_if = rf_modem_result.get('logical_channel')
                try:
                    logical_if = int(logical_if) if logical_if is not None else None
                except Exception:
                    logical_if = None
                if logical_if:
                    ofdma_channels.append({
                        "ifindex": logical_if,
                        "ofdma_ifindex": logical_if,
                        "index": 1,
                        "description": f"OFDMA {logical_if}",
                        "cm_index": cm_index
                    })
        except Exception as e:
            logger.warning(f"OFDMA discovery error (non-fatal): {e}")

        # Second OFDMA fallback from modem_logical_channel
        if not ofdma_channels and modem_logical_channel:
            try:
                logical_if = int(modem_logical_channel)
                if logical_if > 0:
                    ofdma_channels = [{
                        "ifindex": logical_if,
                        "ofdma_ifindex": logical_if,
                        "index": 1,
                        "description": f"OFDMA {logical_if}",
                        "cm_index": cm_index,
                        "active": True,
                        "secondary": False,
                    }]
            except Exception:
                pass

        # ---- Enrich with secondary OFDMA channels from the CMTS channel list ----
        # Per-modem discovery only returns OFDMA blocks with timing_offset > 0.
        # On some CMTSes the same modem is associated with a secondary OFDMA block
        # that is visible in the CMTS channel inventory but not currently active.
        # Surface those sibling blocks in the GUI so operators can inspect them.
        if ofdma_channels:
            try:
                channel_list = client._get(
                    "/pnm/us/ofdma/rxmer/channel/list",
                    params={"cmts_ip": cmts_ip, "community": community},
                    request_timeout=65,
                )
                all_channels = channel_list.get("channels") or []
                by_ifindex = {}
                for row in all_channels:
                    try:
                        by_ifindex[int(row.get("ifindex"))] = row
                    except Exception:
                        continue

                active_ifindexes = {int(ch["ifindex"]) for ch in ofdma_channels if ch.get("ifindex") is not None}
                sibling_domains = set()
                sibling_fns = set()
                for ifindex in active_ifindexes:
                    row = by_ifindex.get(ifindex) or {}
                    mac_domain = str(row.get("mac_domain") or "").strip()
                    suggested_fn = str(row.get("suggested_fn") or "").strip()
                    if mac_domain:
                        sibling_domains.add(mac_domain)
                    if suggested_fn:
                        sibling_fns.add(suggested_fn)

                secondary_rows = []
                for row in all_channels:
                    try:
                        ifindex = int(row.get("ifindex"))
                    except Exception:
                        continue
                    if ifindex in active_ifindexes:
                        continue
                    mac_domain = str(row.get("mac_domain") or "").strip()
                    suggested_fn = str(row.get("suggested_fn") or "").strip()
                    if ((mac_domain and mac_domain in sibling_domains)
                            or (suggested_fn and suggested_fn in sibling_fns)):
                        secondary_rows.append(row)

                for row in sorted(secondary_rows, key=lambda item: int(item.get("ifindex") or 0)):
                    try:
                        ifindex = int(row.get("ifindex"))
                    except Exception:
                        continue
                    ofdma_channels.append({
                        "ifindex": ifindex,
                        "ofdma_ifindex": ifindex,
                        "index": len(ofdma_channels) + 1,
                        "description": row.get("description") or f"OFDMA {ifindex}",
                        "cm_index": cm_index,
                        "active": False,
                        "secondary": True,
                        "mac_domain": row.get("mac_domain"),
                        "suggested_fn": row.get("suggested_fn"),
                        "modem_count": row.get("modem_count"),
                    })

                if secondary_rows:
                    logger.info(
                        f"Added {len(secondary_rows)} secondary OFDMA channel(s) for modem {mac_address} "
                        f"from channel-list sibling matching"
                    )
            except Exception as e:
                logger.debug(f"Failed to enrich secondary OFDMA channels for {mac_address}: {e}")

        if cm_index is not None and cmts_ip and REDIS_AVAILABLE:
            try:
                redis_client.set(_cm_index_cache_key(cmts_ip, mac_address), int(cm_index), ex=3600)
            except Exception as e:
                logger.debug(f"Failed to cache cm_index: {e}")

        # ---- Persist discovered channel ifindices to PyPNM inventory (durable, survives Redis TTL) ----
        discovered_ofdma_ifindex  = ofdma_channels[0]["ifindex"] if ofdma_channels else None
        discovered_upstream_ifindex = modem_rf_port["ifindex"] if modem_rf_port else None
        # Note: modem-refresh (sysDescr enrichment) is intentionally NOT queued here.
        # It is a slow per-modem SNMP call that the user triggers explicitly from the
        # modem detail panel. Auto-queuing it on every channel discovery caused the
        # detail panel to show a permanent "refreshing" spinner.

        result = {
            "success": True,
            "mac_address": mac_address,
            "cmts_ip": cmts_ip,
            "modem_rf_port": modem_rf_port,
            "rf_ports": scqam_channels,
            "ofdma_channels": ofdma_channels,
            "scqam_channels": scqam_channels,
            "cm_index": cm_index
        }

        # ---- Cache result in Redis for 1 hour ----
        if REDIS_AVAILABLE:
            try:
                import json as _json
                redis_client.set(cache_key, _json.dumps(result), ex=3600)
            except Exception as e:
                logger.debug(f"upstream_interfaces cache write error: {e}")

        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Get upstream interfaces failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== PyPNM pysnmp-based CMTS Operations ==============

@pypnm_bp.route('/cmts/ofdma/discover/<mac_address>', methods=['POST'])
def discover_modem_ofdma(mac_address):
    """
    Discover modem's OFDMA channel on CMTS using PyPNM pysnmp.
    
    This endpoint uses PyPNM's Snmp_v2c class for direct CMTS SNMP queries.
    Returns the OFDMA ifIndex needed for US RxMER measurements.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "community": "optional"
    }
    
    Returns:
    {
        "success": true,
        "cm_index": 12345,
        "ofdma_ifindex": 843087001,
        "ofdma_description": "cable-us-ofdma 1/ofd/4.0"
    }
    """
    from app.core.cmts_pnm import discover_modem_ofdma_sync, PYPNM_AVAILABLE
    
    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400
    
    try:
        result = discover_modem_ofdma_sync(cmts_ip, mac_address, community)
        
        if result.get("success"):
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "cmts_ip": cmts_ip,
                **result
            })
        else:
            return jsonify({
                "success": False,
                "mac_address": mac_address,
                "cmts_ip": cmts_ip,
                "error": result.get("error", "Discovery failed")
            }), 404
            
    except Exception as e:
        logger.error(f"OFDMA discovery failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/start/<mac_address>', methods=['POST'])
def start_cmts_us_rxmer(mac_address):
    """
    Start US OFDMA RxMER measurement on CMTS using PyPNM pysnmp.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "ofdma_ifindex": 843087001,
        "pre_eq": true,
        "filename": "optional",
        "community": "optional"
    }
    """
    from app.core.cmts_pnm import start_us_rxmer_sync, UsOfdmaRxMerConfig, PYPNM_AVAILABLE
    
    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())

    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"success": False, "error": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        config = UsOfdmaRxMerConfig(
            cmts_ip=cmts_ip,
            ofdma_ifindex=ofdma_ifindex,
            cm_mac_address=mac_address,
            community=community,
            write_community=write_community,
            filename=data.get('filename', f'usrxmer_{mac_address.replace(":", "")}'),
            pre_eq=data.get('pre_eq', True),
            num_averages=data.get('num_averages', 1),
        )
        
        result = start_us_rxmer_sync(config)
        
        return jsonify({
            "mac_address": mac_address,
            **result
        })
        
    except Exception as e:
        logger.error(f"Start US RxMER failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/status/<mac_address>', methods=['POST'])
def get_cmts_us_rxmer_status(mac_address):
    """
    Get US OFDMA RxMER measurement status from CMTS using PyPNM pysnmp.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "ofdma_ifindex": 843087001,
        "community": "optional"
    }
    """
    from app.core.cmts_pnm import get_us_rxmer_status_sync, PYPNM_AVAILABLE
    
    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"success": False, "error": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        result = get_us_rxmer_status_sync(cmts_ip, ofdma_ifindex, community, write_community)
        
        logger.info(f"US RxMER status response from PyPNM: {result}")
        
        return jsonify({
            "mac_address": mac_address,
            **result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER status failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/data/<mac_address>', methods=['POST'])
def get_cmts_us_rxmer_data(mac_address):
    """
    Fetch US OFDMA RxMER capture as base64 PNG + parsed JSON from PyPNM API.

    Uses the combined /getCaptureAndData endpoint so the file is fetched from
    FTP only once (eliminates the ~14s double-fetch penalty).
    Returns: {"success": true, "image_data": "<base64 png>", "rxmer_data": {...}}
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE

    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503

    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())

    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400

    try:
        import requests as req
        base_url = get_pypnm_api_url()

        _filename = data.get('filename', f'usrxmer_{mac_address.replace(":", "")}')
        payload = {"filename": _filename}

        # Single call — file fetched once, returns PNG (base64) + JSON data
        resp = req.post(
            f"{base_url}/pnm/us/ofdma/rxmer/getCaptureAndData",
            json=payload,
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()
            if result.get('success') and result.get('image_base64'):
                return jsonify({
                    "success": True,
                    "mac_address": mac_address,
                    "image_data": result['image_base64'],
                    "rxmer_data": result,
                })
            return jsonify({
                "success": False,
                "error": result.get('error', 'No image data returned'),
            }), 500

        try:
            err = resp.json()
            return jsonify({"success": False, "error": err.get('error', f'API error {resp.status_code}')}), 500
        except Exception:
            return jsonify({"success": False, "error": f"API error {resp.status_code}"}), 500

    except Exception as e:
        logger.error(f"Get US RxMER data failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/comparison/<mac_address>', methods=['POST'])
def get_cmts_us_rxmer_comparison(mac_address):
    """
    Fetch US OFDMA RxMER comparison (pre-eq ON vs OFF) → FiberNodeAnalysis JSON + overlay PNG.
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import base64

    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503

    data = request.get_json() or {}
    filename_on  = data.get('filename_preeq_on')
    filename_off = data.get('filename_preeq_off')

    if not filename_on or not filename_off:
        return jsonify({"success": False, "error": "filename_preeq_on and filename_preeq_off required"}), 400

    try:
        import requests as req
        base_url = get_pypnm_api_url()
        payload = {
            "filename_preeq_on": filename_on,
            "filename_preeq_off": filename_off,
        }

        img_resp  = req.post(f"{base_url}/pnm/us/ofdma/rxmer/getComparison",     json=payload, timeout=60)
        data_resp = req.post(f"{base_url}/pnm/us/ofdma/rxmer/getComparisonData", json=payload, timeout=30)

        if img_resp.status_code != 200 or 'image/png' not in img_resp.headers.get('Content-Type', ''):
            try:
                err = img_resp.json()
            except Exception:
                err = {}
            return jsonify({"success": False, "error": err.get('error', f'Comparison plot failed: {img_resp.status_code}')}), 500

        return jsonify({
            "success": True,
            "mac_address": mac_address,
            "image_data": base64.b64encode(img_resp.content).decode('utf-8'),
            "analysis": data_resp.json() if data_resp.status_code == 200 else None,
        })

    except Exception as e:
        logger.error(f"Get US RxMER comparison failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/fibernode', methods=['POST'])
def get_cmts_us_rxmer_fibernode():
    """
    Fiber node group RxMER analysis — N captures across multiple modems.
    Body: {"captures": [{"cm_mac_address":..., "filename":..., "preeq_enabled": true}, ...]}
    Returns: {"success": true, "image_data": "<b64 png>", "analysis": <FiberNodeAnalysis>}
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import base64

    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503

    data = request.get_json() or {}
    captures = data.get('captures', [])

    if not captures:
        return jsonify({"success": False, "error": "captures[] required"}), 400

    try:
        import requests as req
        base_url = get_pypnm_api_url()
        payload = {"captures": captures}

        img_resp  = req.post(f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/plot",    json=payload, timeout=120)
        data_resp = req.post(f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/analyze", json=payload, timeout=60)

        if img_resp.status_code != 200 or 'image/png' not in img_resp.headers.get('Content-Type', ''):
            try:
                err = img_resp.json()
            except Exception:
                err = {}
            return jsonify({"success": False, "error": err.get('error', f'Plot failed: {img_resp.status_code}')}), 500

        return jsonify({
            "success": True,
            "image_data": base64.b64encode(img_resp.content).decode('utf-8'),
            "analysis": data_resp.json() if data_resp.status_code == 200 else None,
        })

    except Exception as e:
        logger.error(f"Fiber node analysis failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/channels', methods=['POST'])
def get_cmts_ofdma_channels():
    """
    Walk a CMTS via SNMP (through PyPNM API) to list all OFDMA upstream channels.
    Groups channels by MAC domain to suggest fiber node names.
    Body: {cmts_ip, community}
    Returns: {channels: [{ifindex, description, mac_domain, suggested_fn}], fiber_nodes: [...]}
    """
    import re as _re
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import requests as req

    data = request.get_json() or {}
    cmts_ip   = data.get('cmts_ip')
    community = data.get('community', 'public')
    refresh   = data.get('refresh', False)

    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400

    try:
        base_url = get_pypnm_api_url()
        params = {"cmts_ip": cmts_ip, "community": community}
        if refresh:
            params["refresh"] = "true"
        r = req.get(
            f"{base_url}/pnm/us/ofdma/rxmer/channel/list",
            params=params,
            timeout=90 if refresh else 45,
        )
        if r.status_code != 200:
            return jsonify({"success": False, "error": f"PyPNM channel list failed: {r.status_code}"}), 500

        d = r.json()
        channels    = d.get('channels', [])
        fiber_nodes = d.get('fiber_nodes', [])
        cached      = d.get('_cached', False)
        result = {"success": True, "channels": channels, "fiber_nodes": fiber_nodes}
        if cached:
            result["_cached"] = True
            result["_cache_age_s"] = d.get("_cache_age_s", 0)
        return jsonify(result)

    except Exception as e:
        logger.error(f"OFDMA channel walk failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/channel/modems', methods=['POST'])
def get_cmts_ofdma_channel_modems():
    """
    Get online modem count for an OFDMA upstream channel.
    Body: {cmts_ip, community, ofdma_ifindex, max_modems}
    Returns: {success: true, modems: [{cm_mac_address, cm_index}]}
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import requests as req

    data = request.get_json() or {}
    cmts_ip       = data.get('cmts_ip')
    community     = data.get('community', 'public')
    ofdma_ifindex = data.get('ofdma_ifindex')
    max_modems    = data.get('max_modems', 100)
    force_snmp    = bool(data.get('force_snmp', False))

    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"success": False, "error": "cmts_ip and ofdma_ifindex required"}), 400

    try:
        base_url = get_pypnm_api_url()
        params = {
            "cmts_ip":       cmts_ip,
            "community":     community,
            "ofdma_ifindex": int(ofdma_ifindex),
            "max_modems":    int(max_modems),
        }
        if force_snmp:
            params["force_snmp"] = "true"
        r = req.get(
            f"{base_url}/pnm/us/ofdma/rxmer/channel/modems",
            params=params,
            timeout=PYPNM_OFDMA_TIMEOUT
        )
        if r.status_code != 200:
            return jsonify({"success": False, "error": f"PyPNM channel modems failed: {r.status_code}"}), 500

        d = r.json()
        return jsonify({"success": d.get('success', False), "modems": d.get('modems', []), "source": d.get('source', 'snmp')})

    except Exception as e:
        logger.error(f"OFDMA channel modems failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/cmts/ofdma/rxmer/fibernode/scan', methods=['POST'])
def get_cmts_us_rxmer_fibernode_scan():
    """
    Full fiber node / service group scan:
      1. Walk modems registered on the OFDMA channel via SNMP
      2. Trigger RxMER capture for each, poll until sampleReady
      3. Optionally collect pre-EQ data and group delay for each modem
      4. Run fiberNode/analyze + fiberNode/plot on all captures
      
    If compare_preeq=true, captures both pre-EQ ON and OFF for each modem and
    returns comparison analysis (preeq_delta per modem).
    
    If include_group_delay=true, also queries ATDMA pre-EQ coefficients and
    computes group delay variation for each modem.
    
    Body: {cmts_ip, community, write_community, ofdma_ifindex,
           preeq_enabled, max_modems, fiber_node, compare_preeq,
            include_group_delay, selected_macs}
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import base64, time, threading

    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503

    data = request.get_json() or {}
    cmts_ip             = data.get('cmts_ip')
    community           = data.get('community', 'public')
    write_community     = data.get('write_community', community)
    preeq_enabled       = data.get('preeq_enabled', True)
    compare_preeq       = data.get('compare_preeq', False)
    include_group_delay = data.get('include_group_delay', False)

    max_modems          = int(data.get('max_modems') or 20)
    scan_id             = data.get('scan_id', '')
    def _norm_mac(v: str) -> str:
        return ''.join(ch for ch in str(v or '').lower() if ch.isalnum())

    selected_macs       = {
        _norm_mac(m)
        for m in (data.get('selected_macs') or [])
        if (m or '').strip()
    }

    # Accept either ofdma_ifindices (list) or legacy ofdma_ifindex (single)
    _raw_ifindices = data.get('ofdma_ifindices') or []
    if not _raw_ifindices and data.get('ofdma_ifindex'):
        _raw_ifindices = [data['ofdma_ifindex']]
    ofdma_ifindices = [int(i) for i in _raw_ifindices if i]
    ofdma_ifindex   = ofdma_ifindices[0] if ofdma_ifindices else None  # primary (for legacy use)

    if not cmts_ip or not ofdma_ifindices:
        return jsonify({"success": False, "error": "cmts_ip and ofdma_ifindex(es) required"}), 400


    def _run_scan():
        try:
            import requests as req
            base_url = get_pypnm_api_url()
            last_progress_pct = 0.0

            def _progress(*, pct: float | None = None, **fields):
                """Publish monotonic weighted progress for every scan phase."""
                nonlocal last_progress_pct
                if pct is not None:
                    numeric_pct = max(0.0, min(100.0, float(pct)))
                    last_progress_pct = max(last_progress_pct, numeric_pct)
                fields['pct'] = round(last_progress_pct, 1)
                _set_scan_progress(scan_id, **fields)

            def _aborted() -> bool:
                return _is_scan_abort_requested(scan_id)

            def _finish_aborted(action: str, pct: float | None = None):
                _store_scan_result(scan_id, {
                    "success": False,
                    "error": "Scan aborted by user",
                    "aborted": True,
                })
                _progress(done='true', action=action, pct=pct)

            _progress(
                pct=2,
                phase='discovery', phase_current=0, phase_total=len(ofdma_ifindices),
                step=0, total=0, modem='', modem_idx=0, modem_total=0, channel='',
                action='Discovering modems…', done='false',
            )

            # Build modem list + per-modem channel mapping.
            mac_info: dict[str, dict] = {}        # mac -> modem dict
            mac_ifindices: dict[str, list] = {}   # mac -> [ifidx, ...]

            if selected_macs:
                # User already selected specific modems — use them directly
                # with the primary ofdma_ifindex. No SNMP walk needed.
                # Use only the primary ifindex; the capture loop will try
                # each modem on it. If a FN has multiple channels, each
                # modem is typically on just one — we rely on the CMTS to
                # resolve via the cm_mac_address in the capture request.
                primary_ifidx = ofdma_ifindex or ofdma_ifindices[0]
                for raw_mac in (data.get('selected_macs') or []):
                    mac = (raw_mac or '').strip()
                    if not mac:
                        continue
                    mac_info[mac] = {'cm_mac_address': mac}
                    mac_ifindices[mac] = [primary_ifidx]
                logger.info(f"FN scan: using {len(mac_info)} pre-selected modems on ifindex {primary_ifidx}")
                _progress(
                    pct=7, phase='discovery', phase_current=1, phase_total=1,
                    action=f'{len(mac_info)} selected modems ready', done='false',
                )
            else:
                # No selection — discover modems via SNMP walk.
                for channel_idx, ifidx in enumerate(ofdma_ifindices, start=1):
                    _progress(
                        pct=2 + (4 * (channel_idx - 1) / max(1, len(ofdma_ifindices))),
                        phase='discovery', phase_current=channel_idx - 1, phase_total=len(ofdma_ifindices),
                        channel=str(ifidx), action=f'Discovering modems on channel {channel_idx}/{len(ofdma_ifindices)}…',
                        done='false',
                    )
                    modem_resp = req.get(
                        f"{base_url}/pnm/us/ofdma/rxmer/channel/modems",
                        params={
                            "cmts_ip":       cmts_ip,
                            "community":     community,
                            "ofdma_ifindex": ifidx,
                            "max_modems":    max_modems,
                        },
                        timeout=60
                    )
                    if modem_resp.status_code != 200:
                        logger.warning(f"Could not list modems for ifindex {ifidx}: {modem_resp.status_code}")
                        continue
                    for m in modem_resp.json().get('modems', []):
                        mac = m.get('cm_mac_address') or m.get('mac_address') or ''
                        if not mac:
                            continue
                        if mac not in mac_info:
                            mac_info[mac] = m
                        mac_ifindices.setdefault(mac, [])
                        if ifidx not in mac_ifindices[mac]:
                            mac_ifindices[mac].append(ifidx)

            modems = list(mac_info.values())
            if not modems:
                _progress(
                    done='true', phase='discovery', phase_current=len(ofdma_ifindices),
                    phase_total=len(ofdma_ifindices), action='No modems found',
                )
                _store_scan_result(scan_id, {"success": False, "error": "No modems found on requested OFDMA channel(s)"})
                return

            _progress(
                pct=7, phase='setup', phase_current=0, phase_total=2,
                modem_total=len(modems), action=f'Preparing {len(modems)} modems…', done='false',
            )
            if _aborted():
                _finish_aborted('Aborted before capture start')
                return

            # Total capture steps for progress tracking.
            preeq_modes_tmp = [True, False] if compare_preeq else [preeq_enabled]
            total_steps = sum(len(mac_ifindices.get(m.get('cm_mac_address') or m.get('mac_address',''), [ofdma_ifindex])) * len(preeq_modes_tmp) for m in modems)
            _progress(
                pct=8, phase='setup', phase_current=1, phase_total=2,
                step=0, total=total_steps, modem='', modem_idx=0, modem_total=len(modems),
                channel='', action='Preparing capture requests…', done='false',
            )

            captures = []
            group_delay_data = {}  # MAC -> group delay summary
            preeq_full_data  = {}  # MAC -> full preeq channels list (including taps)

            # Capture one or both pre-eq modes.
            preeq_modes = [True, False] if compare_preeq else [preeq_enabled]

            # PyPNM provisions the vendor-specific destination for each start.
            _progress(
                pct=10, phase='capture', phase_current=0, phase_total=total_steps,
                step=0, total=total_steps, action='Capture setup complete', done='false',
            )

            def _capture_modem(mac: str, pre_eq: bool, modem_ifindex: int) -> dict | None:
                """Capture a single modem with the given pre-eq setting on its channel."""
                if _aborted():
                    return None
                mac_safe = mac.replace(':', '').lower()
                preeq_suffix = 'on' if pre_eq else 'off'
                # Include ifindex in filename so 2 captures on different channels don't collide
                unique_filename = f"rxmer_{mac_safe}_{preeq_suffix}_{modem_ifindex}"

                start_resp = req.post(
                    f"{base_url}/pnm/us/ofdma/rxmer/start",
                    json={
                        "cmts": {"cmts_ip": cmts_ip, "community": community, "write_community": write_community},
                        "cm_mac_address": mac,
                        "ofdma_ifindex": modem_ifindex,
                        "pre_eq": pre_eq,
                        "filename": unique_filename,
                        "destination_index": 0,
                    },
                    timeout=30
                )
                start_data = start_resp.json() if start_resp.status_code == 200 else {}
                if not start_data.get('success'):
                    logger.warning(f"Scan: start failed for {mac} ifindex={modem_ifindex} (pre_eq={pre_eq}): {start_data.get('error')}")
                    return None

                # Wait briefly to avoid stale SAMPLE_READY state.
                time.sleep(2)
                deadline = time.time() + 90
                # Keep our filename; the CMTS may report an older internal path.
                import os as _os
                while time.time() < deadline:
                    if _aborted():
                        return None
                    status_resp = req.get(
                        f"{base_url}/pnm/us/ofdma/rxmer/status",
                        params={
                            "cmts_ip":         cmts_ip,
                            "community":       community,
                            "write_community": write_community,
                            "ofdma_ifindex":   modem_ifindex,
                        },
                        timeout=15
                    )
                    s = status_resp.json() if status_resp.status_code == 200 else {}
                    if s.get('is_ready') or s.get('meas_status') in (4, 7):
                        # Verify that SAMPLE_READY belongs to this capture.
                        status_fn = _os.path.basename(s.get('filename') or '')
                        if status_fn.startswith(f"rxmer_{mac_safe}_{preeq_suffix}"):
                            break  # confirmed our capture is ready
                    if s.get('is_error') or s.get('meas_status') in (5, 6):
                        logger.warning(f"Scan: {mac} status error: {s.get('meas_status_name')}")
                        return None
                    time.sleep(1)  # 1s poll — was 3s, halves scan time

                if unique_filename:
                    return {
                        "cm_mac_address":  mac,
                        "filename":        unique_filename,
                        "preeq_enabled":   pre_eq,
                        "ofdma_ifindex":   modem_ifindex,
                    }
                return None

            # Capture each modem on every registered channel.
            step_done = 0
            for modem_idx, modem in enumerate(modems):
                capture_pct = 10 + (65 * step_done / total_steps) if total_steps else 10
                if _aborted():
                    _finish_aborted('Aborted during capture loop', capture_pct)
                    return
                mac = modem.get('cm_mac_address') or modem.get('mac_address')
                if not mac:
                    continue
                mac_short = mac[-8:]  # last 3 octets for display
                # All OFDMA ifindices this modem appeared on (could be 1 or 2)
                ch_ifindices = mac_ifindices.get(mac) or [ofdma_ifindex]

                for modem_ifindex in ch_ifindices:
                    for pre_eq in preeq_modes:
                        capture_pct = 10 + (65 * step_done / total_steps) if total_steps else 10
                        if _aborted():
                            _finish_aborted('Aborted during modem capture', capture_pct)
                            return
                        _progress(
                            pct=capture_pct,
                            phase='capture', phase_current=step_done, phase_total=total_steps,
                            step=step_done, total=total_steps,
                            modem=mac_short, modem_idx=modem_idx + 1, modem_total=len(modems),
                            channel=str(modem_ifindex),
                            action=f"{'Pre-EQ ON' if pre_eq else 'Pre-EQ OFF'} — capturing…",
                            done='false',
                        )
                        capture = _capture_modem(mac, pre_eq, modem_ifindex)
                        if capture:
                            captures.append(capture)
                        step_done += 1
                        capture_pct = 10 + (65 * step_done / total_steps) if total_steps else 75
                        _progress(
                            pct=capture_pct,
                            phase='capture', phase_current=step_done, phase_total=total_steps,
                            step=step_done, total=total_steps,
                            modem=mac_short, modem_idx=modem_idx + 1, modem_total=len(modems),
                            channel=str(modem_ifindex),
                            action=f"Capture {step_done}/{total_steps} complete",
                            done='false',
                        )

            # Step 2b: collect group delay data for all modems in parallel.
            # Each preeq call walks the full CMTS EqData table (~43 s on loaded
            # CMTSes), so firing them serially would take N×43 s.  Using a thread
            # pool caps total elapsed time to roughly max(individual_call_times).
            if include_group_delay:
                if _aborted():
                    _finish_aborted('Aborted before group delay collection', 75)
                    return
                gd_macs = [
                    (modem.get('cm_mac_address') or modem.get('mac_address'))
                    for modem in modems
                    if (modem.get('cm_mac_address') or modem.get('mac_address'))
                ]

                def _fetch_group_delay(mac: str) -> tuple[str, dict | None]:
                    try:
                        preeq_resp = req.post(
                            f"{base_url}/pnm/us/ofdma/rxmer/preeq",
                            json={
                                "cmts": {"cmts_ip": cmts_ip, "community": community, "write_community": write_community},
                                "cm_mac_address": mac,
                            },
                            timeout=150,   # EqData walk can take 60-120 s on large CMTSes
                        )
                        if preeq_resp.status_code == 200:
                            return mac, preeq_resp.json()
                        return mac, None
                    except Exception as gd_err:
                        logger.warning(f"Failed to get group delay for {mac}: {gd_err}")
                        return mac, None

                from concurrent.futures import ThreadPoolExecutor as _GdPool, as_completed as _as_completed
                gd_done = 0
                _progress(
                    pct=75, phase='group_delay', phase_current=0, phase_total=len(gd_macs),
                    action='Collecting group delay…', done='false',
                )
                with _GdPool(max_workers=min(len(gd_macs), 10)) as _gd_pool:
                    _gd_futures = {_gd_pool.submit(_fetch_group_delay, m): m for m in gd_macs}
                    for _fut in _as_completed(_gd_futures):
                        if _aborted():
                            _finish_aborted('Aborted during group delay collection')
                            return
                        _mac, _preeq_data = _fut.result()
                        gd_done += 1
                        _progress(
                            pct=75 + (15 * gd_done / max(1, len(gd_macs))),
                            phase='group_delay', phase_current=gd_done, phase_total=len(gd_macs),
                            modem=_mac[-8:] if _mac else '',
                            action=f'Group delay {gd_done}/{len(gd_macs)} complete', done='false',
                        )
                        if not _preeq_data or not _preeq_data.get('success') or not _preeq_data.get('channels'):
                            continue
                        preeq_full_data[_mac] = {"mac": _mac, "channels": _preeq_data['channels']}
                        gd_summary = {"cm_mac_address": _mac, "channels": []}
                        for ch in _preeq_data.get('channels', []):
                            ch_summary = {
                                "us_ifindex": ch.get('us_ifindex'),
                                "num_taps":   ch.get('num_taps'),
                            }
                            if ch.get('metrics'):
                                ch_summary["mtc_dB"]   = ch['metrics'].get('mtc_dB')
                                ch_summary["nmter_dB"] = ch['metrics'].get('nmter_dB')
                            if ch.get('group_delay'):
                                gd = ch['group_delay']
                                ch_summary["delay_pp_us"]  = gd.get('delay_pp_us')
                                ch_summary["delay_rms_us"] = gd.get('delay_rms_us')
                            if ch.get('tap_delay_summary'):
                                tds = ch['tap_delay_summary']
                                ch_summary["pre_main_cable_ft"]  = tds.get('pre_main_cable_ft')
                                ch_summary["post_main_cable_ft"] = tds.get('post_main_cable_ft')
                            gd_summary["channels"].append(ch_summary)
                        group_delay_data[_mac] = gd_summary

            if not captures:
                _progress(done='true', phase='capture', action='No captures completed')
                _store_scan_result(scan_id, {"success": False, "error": "No captures completed"})
                return

            if _aborted():
                _finish_aborted('Aborted before file retrieval')
                return

            _progress(
                pct=94, phase='retrieval', phase_current=0, phase_total=len(captures),
                action='PyPNM is locating capture files…', done='false',
            )
            payload = {"captures": captures}
            _progress(
                pct=95, phase='analysis', phase_current=0, phase_total=4,
                action='Generating RxMER plot…', done='false',
            )
            img_resp = req.post(f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/plot", json=payload, timeout=180)
            _progress(
                pct=97, phase='analysis', phase_current=1, phase_total=4,
                action='Analyzing RxMER captures…', done='false',
            )
            data_resp = req.post(f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/analyze", json=payload, timeout=60)
            _progress(
                pct=98, phase='analysis', phase_current=2, phase_total=4,
                action='Building scan results…', done='false',
            )

            if img_resp.status_code == 200 and 'image/png' in img_resp.headers.get('Content-Type', ''):
                _image_data = base64.b64encode(img_resp.content).decode('utf-8')
            else:
                logger.error(f"Fiber node plot failed: HTTP {img_resp.status_code} content-type={img_resp.headers.get('Content-Type')} body={img_resp.text[:200]}")
                _image_data = None

            result = {
                "success":    True,
                "image_data": _image_data,
                "analysis":   data_resp.json() if data_resp.status_code == 200 else None,
                "captures":   captures,
            }

            # Include group delay data if collected
            if group_delay_data:
                result["group_delay"] = list(group_delay_data.values())

            # Chart-ready tap coordinates derived only from the already-collected
            # pre-EQ response. The full source channels remain untouched.
            if preeq_full_data:
                result["tap_profile"] = _build_tap_profile_dto(preeq_full_data)

            # Plant vs in-home assessment — requires pre-eq taps + subcarrier MER stats
            if preeq_full_data and data_resp.status_code == 200:
                _progress(
                    pct=99, phase='analysis', phase_current=3, phase_total=4,
                    action='Assessing plant and tap distances…', done='false',
                )
                try:
                    analyze_json = data_resp.json()
                    sc_stats     = analyze_json.get('subcarrier_stats', [])
                    pa_resp = req.post(
                        f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/plant-assessment",
                        json={
                            "modems_preeq": list(preeq_full_data.values()),
                            "subcarrier_stats": sc_stats,
                            "mer_bad_threshold_db": 28.0,
                        },
                        timeout=30,
                    )
                    if pa_resp.status_code == 200:
                        result["plant_assessment"] = pa_resp.json()
                    else:
                        logger.warning(f"plant-assessment call failed: {pa_resp.status_code}")

                    # Tap distance plot (matplotlib PNG from PyPNM API)
                    try:
                        tp_resp = req.post(
                            f"{base_url}/pnm/us/ofdma/rxmer/fiberNode/tap-plot",
                            json={
                                "modems_preeq": list(preeq_full_data.values()),
                                "subcarrier_stats": sc_stats,
                                "mer_bad_threshold_db": 28.0,
                            },
                            timeout=30,
                        )
                        if tp_resp.status_code == 200 and 'image/png' in tp_resp.headers.get('Content-Type', ''):
                            result["tap_plot_image"] = base64.b64encode(tp_resp.content).decode('utf-8')
                        else:
                            logger.warning(f"tap-plot call failed: {tp_resp.status_code}")
                    except Exception as _tp_err:
                        logger.warning(f"tap-plot skipped: {_tp_err}")
                except Exception as _pa_err:
                    logger.warning(f"plant-assessment skipped: {_pa_err}")

            _store_scan_result(scan_id, result)
            _progress(
                pct=100, done='true', phase='complete', phase_current=4, phase_total=4,
                action='Complete',
            )
        except Exception as e:
            logger.error(f"Fiber node scan failed: {e}")
            _store_scan_result(scan_id, {'success': False, 'error': str(e)})
            _progress(done='true', phase='error', action=f'Error: {e}')
        finally:
            _set_scan_abort(scan_id, False)

    threading.Thread(target=_run_scan, daemon=True).start()
    return jsonify({"started": True, "scan_id": scan_id})


@pypnm_bp.route('/ds/chan_est/scan', methods=['POST'])
def ds_chan_est_scan():
    """DS OFDM Channel Estimation Suckout Scan — agent-based.

    Uses POST /pnm/ds/channel-estimation (PyPNM Agent, no direct SNMP).
    Fetches OFDM-capable modems from CMTS, runs channel estimation on each
    in parallel (5 concurrent), and returns per-modem amplitude profiles
    suitable for client-side suckout heatmap rendering.

    Request body:
        cmts_hostname         CMTS hostname (resolves IP + CMTS community)
        cmts_ip               CMTS IP (alternative / override)
        community             SNMP read community for CMTS (optional override)
        modem_write_community SNMP write community for modems (for PNM SETs)
        max_modems            Max modems to scan (default 20)

    Response:
        {success, total_modems, success_count,
         modems: [{mac_address, ip_address, success, error,
                   channels: [{channel_id, center_freq_mhz,
                               amplitudes_db, subcarrier_count}]}]}
    """
    data = request.json or {}
    cmts_hostname         = data.get('cmts_hostname') or data.get('cmts')
    cmts_ip               = data.get('cmts_ip')
    community             = data.get('community')              # CMTS read community
    modem_write_community = data.get('modem_write_community')  # modem SNMP write community
    max_modems            = int(data.get('max_modems', 20))

    # Resolve CMTS IP + CMTS community from provider if only hostname given
    if not cmts_ip:
        from app.core.cmts_provider import CMTSProvider
        cmts_rec = (CMTSProvider.get_cmts_by_hostname(cmts_hostname)
                    if cmts_hostname else None)
        if cmts_rec:
            cmts_ip   = cmts_rec.get('IPAddress')
            community = community or cmts_rec.get('snmp_community')

    community             = community or get_default_community()
    # Modem write community (PNM SNMP SETs) is always separate from CMTS community
    modem_write_community = modem_write_community or get_default_write_community()

    if not cmts_ip:
        return jsonify({"success": False,
                        "error": "cmts_ip or cmts_hostname required"}), 400

    # If the frontend supplies a pre-filtered modem list (from fiber node
    # selection), use it directly — no CMTS re-discovery needed.
    supplied_modems = data.get('modems')  # [{mac_address, ip_address}, ...]
    if supplied_modems and isinstance(supplied_modems, list) and len(supplied_modems) > 0:
        eligible = [{'mac_address': m['mac_address'], 'ip_address': m['ip_address']}
                    for m in supplied_modems
                    if m.get('mac_address') and m.get('ip_address')]
        eligible = eligible[:max_modems]
    else:
        # Fallback: discover from CMTS
        try:
            from app.core.pypnm_client import PyPNMClient as _PNMClient
            _c = _PNMClient()
            modem_resp = _c.get_cmts_modems(
                cmts_ip=cmts_ip,
                community=community,
                limit=max_modems * 5,
                enrich=True,
            )
            raw_modems = modem_resp.get('modems', []) if modem_resp.get('success') else []
        except Exception as exc:
            return jsonify({"success": False,
                            "error": f"Could not load modems: {exc}"}), 500

        def _is_provisioned(ip: str) -> bool:
            return ip and not (
                ip.startswith('10.254.')
                or ip.startswith('10.255.')
                or ip.startswith('0.')
                or ip == '0.0.0.0'
            )

        operational = {'operational', 'online', ''}
        eligible = [m for m in raw_modems
                    if _is_provisioned(m.get('ip_address', ''))
                    and m.get('status', '').lower() in operational]
        eligible = eligible[:max_modems]

    if not eligible:
        return jsonify({"success": False,
                        "error": "No eligible modems found"}), 400

    scan_id = data.get('scan_id', '')
    n_total = len(eligible)
    _set_ds_scan_progress(scan_id, total=n_total, completed=0, started=0, pct=0,
                          modem='', action='dispatching modems…')

    tftp_ip = get_tftp_for_cm()
    from app.core.pypnm_client import PyPNMClient
    client  = PyPNMClient()
    _started_count   = [0]
    _completed_count = [0]
    _progress_lock   = _threading.Lock()

    def _capture(modem: dict) -> dict:
        mac = modem.get('mac_address', '')
        ip  = modem.get('ip_address', '')
        # Phase 1: modem dispatched — fill bar 0→50%
        with _progress_lock:
            _started_count[0] += 1
            started = _started_count[0]
        pct_start = int(started * 50 / n_total)
        _set_ds_scan_progress(scan_id, total=n_total,
                              started=started, completed=_completed_count[0],
                              pct=pct_start, modem=mac, action='measuring…')
        try:
            # Use the proven /docs/pnm/ds/ofdm/channelEstCoeff/getCapture
            # endpoint which handles agent-based file retrieval correctly.
            result = client.get_channel_estimation(
                mac, ip, tftp_ip, modem_write_community,
                tftp_ipv6="::1", output_type="json"
            )
            status = result.get('status', '')
            if isinstance(status, int):
                ok = status == 0
            else:
                ok = str(status).upper() in ('SUCCESS', '0')

            if not ok:
                return {'mac_address': mac, 'ip_address': ip,
                        'success': False,
                        'error': result.get('message') or result.get('error') or 'capture failed',
                        'channels': []}

            channels = []
            for ch_data in (result.get('data', {}).get('analysis') or []):
                cv = ch_data.get('carrier_values') or {}
                amps_db = cv.get('magnitudes') or []
                if not amps_db:
                    continue
                # Compute center frequency from header fields
                sz_hz = ch_data.get('subcarrier_zero_frequency', 0)
                sp_hz = ch_data.get('subcarrier_spacing', 0)
                fa    = ch_data.get('first_active_subcarrier_index', 0)
                n     = len(amps_db)
                center_mhz = round((sz_hz + (fa + n / 2) * sp_hz) / 1e6, 3) if sz_hz and sp_hz else None
                channels.append({
                    'channel_id':       ch_data.get('channel_id', 0),
                    'center_freq_mhz':  center_mhz,
                    'amplitudes_db':    [round(a, 2) for a in amps_db],
                    'subcarrier_count': n,
                })

            return {
                'mac_address': mac,
                'ip_address':  ip,
                'success':     bool(channels),
                'error':       None if channels else 'no channel data returned',
                'channels':    channels,
            }
        except Exception as exc:
            logger.warning(f"DS chan_est scan: {mac} failed: {exc}")
            return {'mac_address': mac, 'ip_address': ip,
                    'success': False, 'error': str(exc), 'channels': []}

    # Fire all modems concurrently — PyPNM API is async (FastAPI/uvicorn) and
    # handles N simultaneous requests.  Sequential batching of 5 would multiply
    # total time by ceil(N/5); with all-at-once every modem's 30s poll window
    # overlaps and total scan time stays ~30s regardless of modem count.
    modem_results = []
    concurrency = len(eligible)          # all at once
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_capture, m): m for m in eligible}
        for fut in as_completed(futures):
            res = fut.result()
            modem_results.append(res)
            with _progress_lock:
                _completed_count[0] += 1
                done = _completed_count[0]
            # Phase 2: modem returned — fill bar 50→100%
            pct = 50 + int(done * 50 / n_total)
            _set_ds_scan_progress(scan_id, total=n_total,
                                   started=_started_count[0], completed=done,
                                   pct=pct, modem=res.get('mac_address',''),
                                   action='ok' if res.get('success') else 'no data')
    # Clean up in-memory store after a short delay (leave it for final poll)
    with _ds_progress_lock:
        _ds_progress_store.pop(scan_id, None)

    modem_results.sort(key=lambda r: r.get('mac_address', ''))
    success_count = sum(1 for r in modem_results if r.get('success'))

    # ── Generate matplotlib overlay plot ────────────────────────────────
    plot_b64 = None
    try:
        import io
        import base64
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.ticker import AutoMinorLocator

        ok_modems = [m for m in modem_results if m.get('success') and m.get('channels')]
        if len(ok_modems) >= 1:
            fig, (ax_overlay, ax_hist) = plt.subplots(
                2, 1, figsize=(14, 7), height_ratios=[3, 1],
                sharex=True, gridspec_kw={'hspace': 0.08})

            threshold = float(data.get('threshold', 3.0))

            for m in ok_modems:
                for ch in m['channels']:
                    amps = ch.get('amplitudes_db', [])
                    if not amps:
                        continue
                    n = len(amps)
                    center = ch.get('center_freq_mhz') or 0
                    # Approximate freq axis: 192 MHz OFDM channel centred on center_freq
                    bw = 192.0
                    freqs = np.linspace(center - bw / 2, center + bw / 2, n)
                    ax_overlay.plot(freqs, amps, linewidth=0.5, alpha=0.35, color='#6b7280')

            # Compute and plot median across all modems (per subcarrier)
            # Group by channel_id → stack amplitudes → compute median
            chan_stacks = {}  # channel_id → list of amp arrays
            for m in ok_modems:
                for ch in m['channels']:
                    cid = ch.get('channel_id', 0)
                    amps = ch.get('amplitudes_db', [])
                    if amps:
                        chan_stacks.setdefault(cid, []).append(amps)

            suckout_freqs = []   # will hold per-bin modem counts
            hist_bins = 100
            all_freq_min, all_freq_max = np.inf, -np.inf

            for cid, stack in sorted(chan_stacks.items()):
                min_len = min(len(a) for a in stack)
                arr = np.array([a[:min_len] for a in stack])
                median = np.median(arr, axis=0)
                # Frequency axis for this channel
                ch0 = next(ch for m in ok_modems for ch in m['channels'] if ch.get('channel_id') == cid)
                center = ch0.get('center_freq_mhz') or 0
                bw = 192.0
                freqs = np.linspace(center - bw / 2, center + bw / 2, min_len)
                all_freq_min = min(all_freq_min, freqs[0])
                all_freq_max = max(all_freq_max, freqs[-1])

                ax_overlay.plot(freqs, median, linewidth=1.8, color='#2563eb',
                                label=f'Median (Ch {cid})' if cid == sorted(chan_stacks.keys())[0] else None)

                # Per-modem suckout detection: track which freq bins each modem dips in
                bin_edges = np.linspace(freqs[0], freqs[-1], hist_bins + 1)
                modem_hits = np.zeros(hist_bins, dtype=int)  # count of unique modems per bin
                for row in arr:
                    x = np.arange(min_len)
                    coeffs = np.polyfit(x, row, 1)
                    trend = np.polyval(coeffs, x)
                    dip_mask_row = (row - trend) < -threshold
                    if np.any(dip_mask_row):
                        dip_freqs = freqs[dip_mask_row]
                        # Find which bins this modem has at least one dip in
                        bin_idx = np.clip(np.digitize(dip_freqs, bin_edges) - 1, 0, hist_bins - 1)
                        unique_bins = np.unique(bin_idx)
                        modem_hits[unique_bins] += 1  # +1 per modem, not per subcarrier

                suckout_freqs.append((bin_edges, modem_hits))

                # Highlight suckout zones on median
                x_idx = np.arange(min_len)
                m_coeffs = np.polyfit(x_idx, median, 1)
                m_trend = np.polyval(m_coeffs, x_idx)
                dip_mask = (median - m_trend) < -threshold
                if np.any(dip_mask):
                    ax_overlay.fill_between(freqs, median, m_trend,
                                            where=dip_mask, alpha=0.25, color='#dc3545',
                                            label='Suckout zone' if cid == sorted(chan_stacks.keys())[0] else None)

            ax_overlay.set_ylabel('Amplitude (dB)', fontsize=10)
            ax_overlay.set_title(f'DS OFDM Channel Estimation — {len(ok_modems)} modems', fontsize=12)
            ax_overlay.legend(loc='lower right', fontsize=8, framealpha=0.8)
            ax_overlay.grid(True, alpha=0.2)
            ax_overlay.xaxis.set_minor_locator(AutoMinorLocator())

            # ── Suckout histogram: unique modems affected per freq bin ──
            for bin_edges, modem_hits in suckout_freqs:
                bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
                bin_width = bin_edges[1] - bin_edges[0]
                ax_hist.bar(bin_centers, modem_hits, width=bin_width * 0.9,
                            color='#dc3545', alpha=0.7, edgecolor='#b91c1c')
            ax_hist.set_xlabel('Frequency (MHz)', fontsize=10)
            ax_hist.set_ylabel('Modems\naffected', fontsize=9)
            ax_hist.yaxis.get_major_locator().set_params(integer=True)
            ax_hist.grid(True, alpha=0.2)
            ax_hist.xaxis.set_minor_locator(AutoMinorLocator())

            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            plt.close(fig)
            buf.seek(0)
            plot_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as plot_err:
        logger.warning(f"DS suckout matplotlib plot failed: {plot_err}", exc_info=True)

    return jsonify({
        "success":       True,
        "total_modems":  len(eligible),
        "success_count": success_count,
        "modems":        modem_results,
        "plot_png_b64":  plot_b64,
    })


@pypnm_bp.route('/config', methods=['GET'])
def get_config():
    """Return frontend configuration from environment variables."""
    return jsonify({
        'snmpCommunity': get_cmts_community(),
        'snmpCommunityRW': get_cmts_write_community(),
        'snmpCommunityModem': get_default_community(),
    })


# ================================================================
# DS Fullband Spectrum Scan — multi-modem overlay + detection
# ================================================================

# Known LTE bands that can ingress into cable plant (US frequencies in MHz)
_LTE_BANDS = [
    {'name': 'LTE B12/17', 'start': 699, 'end': 746},
    {'name': 'LTE B13',    'start': 746, 'end': 787},
    {'name': 'LTE B14',    'start': 758, 'end': 768},
    {'name': 'LTE B5',     'start': 824, 'end': 849},
]


@pypnm_bp.route('/ds/fullband/scan', methods=['POST'])
def ds_fullband_scan():
    """DS Fullband Spectrum Scan — multi-modem.

    Triggers fullband spectrum capture on each modem via
    /docs/pnm/ds/spectrumAnalyzer/getCapture and returns
    per-modem amplitude data plus a matplotlib overlay plot
    with automated LTE / suckout / splitter detection.
    """
    import math
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    data = request.json or {}
    cmts_hostname         = data.get('cmts_hostname') or data.get('cmts')
    cmts_ip               = data.get('cmts_ip')
    community             = data.get('community')
    modem_write_community = data.get('modem_write_community')
    max_modems            = int(data.get('max_modems', 10))
    scan_id               = data.get('scan_id', '')
    strict_in_channel     = bool(data.get('strict_in_channel', True))

    if not cmts_ip:
        from app.core.cmts_provider import CMTSProvider
        cmts_rec = (CMTSProvider.get_cmts_by_hostname(cmts_hostname)
                    if cmts_hostname else None)
        if cmts_rec:
            cmts_ip   = cmts_rec.get('IPAddress')
            community = community or cmts_rec.get('snmp_community')

    community             = community or get_default_community()
    modem_write_community = modem_write_community or get_default_write_community()

    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip or cmts_hostname required"}), 400

    supplied_modems = data.get('modems')
    if supplied_modems and isinstance(supplied_modems, list) and len(supplied_modems) > 0:
        eligible = [{'mac_address': m['mac_address'], 'ip_address': m['ip_address']}
                    for m in supplied_modems
                    if m.get('mac_address') and m.get('ip_address')]
        eligible = eligible[:max_modems]
    else:
        try:
            from app.core.pypnm_client import PyPNMClient as _PNMClient
            _c = _PNMClient()
            modem_resp = _c.get_cmts_modems(cmts_ip=cmts_ip, community=community,
                                             limit=max_modems * 5, enrich=False)
            raw = modem_resp.get('modems', []) if modem_resp.get('success') else []
        except Exception as exc:
            return jsonify({"success": False, "error": f"Could not load modems: {exc}"}), 500

        operational = {'operational', 'online', ''}
        eligible = [m for m in raw
                    if m.get('ip_address') and m.get('status', '').lower() in operational
                    and not m['ip_address'].startswith(('10.254.', '10.255.', '0.'))]
        eligible = eligible[:max_modems]

    if not eligible:
        return jsonify({"success": False, "error": "No eligible modems found"}), 400

    n_total = len(eligible)
    from app.core.pypnm_client import PyPNMClient
    client = PyPNMClient()
    # Modem-side captures must use CM-reachable TFTP (TFTP_ALT / TFTP_IPV4_ALT),
    # never a localhost fallback.
    tftp_ip = get_tftp_for_cm()

    _started = [0]
    _completed = [0]
    _lock = threading.Lock()

    if scan_id:
        _set_ds_scan_progress(scan_id, total=n_total, completed=0, started=0, pct=0,
                              modem='', action='starting fullband scan…')

    def _capture(modem):
        mac = modem['mac_address']
        ip  = modem['ip_address']
        with _lock:
            _started[0] += 1
            s = _started[0]
        if scan_id:
            _set_ds_scan_progress(scan_id, total=n_total, started=s,
                                  completed=_completed[0],
                                  pct=int(s * 50 / n_total),
                                  modem=mac, action='capturing…')
        try:
            result = client.get_spectrum_capture(
                mac, ip, tftp_ip, modem_write_community,
                tftp_ipv6="::1", output_type="json"
            )
            status = result.get('status', '')
            if isinstance(status, int):
                ok = status == 0
            else:
                ok = str(status).upper() in ('SUCCESS', '0')

            if not ok:
                return {'mac_address': mac, 'ip_address': ip, 'success': False,
                        'error': result.get('message') or 'capture failed',
                        'frequencies_mhz': [], 'amplitudes_dbmv': []}

            resp_data = result.get('data', {})
            freq_hz  = []
            amp_dbmv = []

            # Primary path: data.analysis[].signal_analysis.frequencies/magnitudes
            for a in (resp_data.get('analysis') or []):
                sig = a.get('signal_analysis', {})
                f = sig.get('frequencies') or []
                m = sig.get('magnitudes') or []
                if f and m:
                    freq_hz  = f
                    amp_dbmv = m
                    break

            # Fallback paths
            if not freq_hz:
                freq_hz  = resp_data.get('frequency_array') or []
                amp_dbmv = resp_data.get('amplitude_array') or []

            if not freq_hz or not amp_dbmv:
                return {'mac_address': mac, 'ip_address': ip, 'success': False,
                        'error': 'no spectrum data returned',
                        'frequencies_mhz': [], 'amplitudes_dbmv': []}

            n = min(len(freq_hz), len(amp_dbmv))
            freq_mhz = [f / 1e6 if f > 1e6 else f for f in freq_hz[:n]]
            amps     = [round(a, 2) for a in amp_dbmv[:n]]

            return {'mac_address': mac, 'ip_address': ip, 'success': True,
                    'error': None,
                    'frequencies_mhz': freq_mhz, 'amplitudes_dbmv': amps}
        except Exception as exc:
            logger.warning(f"Fullband scan: {mac} failed: {exc}")
            return {'mac_address': mac, 'ip_address': ip, 'success': False,
                    'error': str(exc), 'frequencies_mhz': [], 'amplitudes_dbmv': []}

    modem_results = []
    # Cap concurrency at 25: each capture fires ~5 SNMP agent tasks (diplexer read,
    # snmp_set_sequence tasks take 25-30 s each and run on the agent's long pool
    # (10 threads). Capping at 10 keeps concurrent tasks ≤ long pool size so the
    # agent never queues more than it can run simultaneously, preventing FD/socket
    # exhaustion on large scans (50+ modems).
    _MAX_CONCURRENT_CAPTURES = 10
    with ThreadPoolExecutor(max_workers=min(len(eligible), _MAX_CONCURRENT_CAPTURES)) as pool:
        futures = {pool.submit(_capture, m): m for m in eligible}
        for fut in as_completed(futures):
            res = fut.result()
            modem_results.append(res)
            with _lock:
                _completed[0] += 1
                d = _completed[0]
            if scan_id:
                _set_ds_scan_progress(scan_id, total=n_total, started=_started[0],
                                      completed=d,
                                      pct=50 + int(d * 50 / n_total),
                                      modem=res.get('mac_address', ''),
                                      action='ok' if res.get('success') else 'failed')

    if scan_id:
        with _ds_progress_lock:
            _ds_progress_store.pop(scan_id, None)

    modem_results.sort(key=lambda r: r.get('mac_address', ''))
    success_count = sum(1 for r in modem_results if r.get('success'))

    # ── Matplotlib plot with automated detection ──────────────────
    plot_b64 = None
    detections = []
    try:
        import io
        import base64
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.ticker import AutoMinorLocator, MultipleLocator
        ok_modems = [m for m in modem_results if m.get('success') and m.get('frequencies_mhz')]
        if ok_modems:
            # ax_main and ax_lte share the frequency x-axis.
            # ax_ripple has an independent x-axis (fault distance in metres).
            fig = plt.figure(figsize=(16, 11))
            gs  = fig.add_gridspec(3, 1, height_ratios=[4, 1, 1], hspace=0.45)
            ax_main   = fig.add_subplot(gs[0])
            ax_lte    = fig.add_subplot(gs[1], sharex=ax_main)
            ax_ripple = fig.add_subplot(gs[2])

            # ── Top: overlay all modem traces + median ──
            all_freqs = []
            all_amps  = []
            for m in ok_modems:
                f = np.array(m['frequencies_mhz'])
                a = np.array(m['amplitudes_dbmv'])
                ax_main.plot(f, a, linewidth=0.4, alpha=0.3, color='#6b7280')
                all_freqs.append(f)
                all_amps.append(a)

            # Interpolate to common frequency grid for median
            min_f = min(f[0] for f in all_freqs)
            max_f = max(f[-1] for f in all_freqs)
            n_pts = max(len(f) for f in all_freqs)
            common_f = np.linspace(min_f, max_f, n_pts)
            interp_amps = []
            for f, a in zip(all_freqs, all_amps):
                interp_amps.append(np.interp(common_f, f, a))
            arr = np.array(interp_amps)
            median = np.median(arr, axis=0)

            ax_main.plot(common_f, median, linewidth=1.8, color='#2563eb', label='Median')

            # ── Suckout detection on median ──
            # Sliding window: 5 MHz window, flag dips > 6 dB below local mean
            window_mhz = 5.0
            step = common_f[1] - common_f[0] if len(common_f) > 1 else 1
            win_pts = max(3, int(window_mhz / step))

            def _moving_avg(a, w):
                """Numpy-only uniform moving average (no scipy)."""
                kernel = np.ones(w) / w
                # Pad edges to avoid shrinkage
                pad = w // 2
                padded = np.pad(a, pad, mode='edge')
                return np.convolve(padded, kernel, mode='valid')[:len(a)]

            smoothed = _moving_avg(median, win_pts)

            # Guard against false positives in expected guard-bands between
            # adjacent SC-QAM channels: only count dips inside occupied carrier regions
            # (when strict_in_channel is True, which is the default).
            raw_suckout_mask = (median - smoothed) < -6
            occupied_core = None

            if strict_in_channel:
                noise_floor = float(np.percentile(median, 15))
                occupied_core = median > (noise_floor + 4.0)
                occupied_mask = occupied_core.copy()
                # Expand occupied mask by ~0.4 MHz to include channel skirts.
                expand_pts = max(1, int(0.4 / max(step, 1e-6)))
                if expand_pts > 0:
                    k = np.ones(2 * expand_pts + 1, dtype=int)
                    occupied_mask = np.convolve(occupied_mask.astype(int), k, mode='same') > 0
                suckout_mask = raw_suckout_mask & occupied_mask
            else:
                suckout_mask = raw_suckout_mask

            suckout_label = 'Suckout (>6 dB, in-channel)' if strict_in_channel else 'Suckout (>6 dB)'
            # SC-QAM channel roll-off at band edges creates narrow dips (1.0–1.8 MHz).
            # Real plant suckouts (trap, resonance, impedance) are at least 2.5 MHz wide.
            # Build a "clean" mask that strips any contiguous dip region narrower than
            # MIN_SUCKOUT_WIDTH_MHZ — this removes edge-of-channel artifacts from both
            # the plot shading AND the detection summary list.
            MIN_SUCKOUT_WIDTH_MHZ = 2.5
            min_width_pts = max(2, int(MIN_SUCKOUT_WIDTH_MHZ / max(step, 1e-6)))

            clean_mask = suckout_mask.copy()
            trans = np.diff(np.concatenate(([0], suckout_mask.astype(int), [0])))
            r_starts = np.where(trans == 1)[0]
            r_ends   = np.where(trans == -1)[0] - 1
            for rs, re in zip(r_starts, r_ends):
                if (re - rs + 1) < min_width_pts:
                    clean_mask[rs:re + 1] = False
                elif strict_in_channel and occupied_core is not None:
                    if float(np.mean(occupied_core[rs:re + 1])) < 0.55:
                        clean_mask[rs:re + 1] = False

            if np.any(clean_mask):
                ax_main.fill_between(common_f, median, smoothed,
                                     where=clean_mask, alpha=0.3, color='#dc3545',
                                     label=suckout_label)
                # Record detections from the already-filtered clean_mask regions
                trans2 = np.diff(np.concatenate(([0], clean_mask.astype(int), [0])))
                starts = np.where(trans2 == 1)[0]
                ends   = np.where(trans2 == -1)[0] - 1
                for s_idx, e_idx in zip(starts, ends):
                    f_start = common_f[s_idx]
                    f_end   = common_f[min(e_idx, len(common_f) - 1)]
                    local_delta = median[s_idx:e_idx + 1] - smoothed[s_idx:e_idx + 1]
                    depth = round(float(np.min(local_delta)), 1)
                    detections.append({
                        'type': 'suckout', 'freq_start_mhz': round(f_start, 1),
                        'freq_end_mhz': round(f_end, 1), 'depth_db': depth})

            # ── LTE ingress detection ──
            for band in _LTE_BANDS:
                mask = (common_f >= band['start']) & (common_f <= band['end'])
                if not np.any(mask):
                    continue
                band_power = np.mean(median[mask])
                # Compare to neighbors: 20 MHz below and above
                below = (common_f >= band['start'] - 20) & (common_f < band['start'])
                above = (common_f > band['end']) & (common_f <= band['end'] + 20)
                neighbor_mask = below | above
                if not np.any(neighbor_mask):
                    continue
                neighbor_power = np.mean(median[neighbor_mask])
                elevation = band_power - neighbor_power
                if elevation > 3:  # 3 dB above neighbors = likely ingress
                    ax_main.axvspan(band['start'], band['end'],
                                    alpha=0.15, color='#f59e0b',
                                    label=band['name'] if band == _LTE_BANDS[0] else None)
                    ax_main.text((band['start'] + band['end']) / 2,
                                ax_main.get_ylim()[1] - 2,
                                band['name'], ha='center', fontsize=7,
                                color='#d97706', fontweight='bold')
                    detections.append({
                        'type': 'lte_ingress', 'band': band['name'],
                        'freq_start_mhz': band['start'], 'freq_end_mhz': band['end'],
                        'elevation_db': round(elevation, 1)})

            ax_main.set_ylabel('Amplitude (dBmV)', fontsize=10)
            ax_main.set_title(f'DS Fullband Spectrum — {len(ok_modems)} modems', fontsize=12)
            ax_main.legend(loc='lower right', fontsize=8, framealpha=0.8)
            ax_main.grid(True, alpha=0.2)
            # x-axis: ticks every 50 MHz, minor every 10 MHz; labels suppressed (shared with ax_lte below)
            ax_main.xaxis.set_major_locator(MultipleLocator(50))
            ax_main.xaxis.set_minor_locator(MultipleLocator(10))
            ax_main.tick_params(axis='x', labelbottom=False)

            # ── Middle: per-frequency modem count with dip ──
            # Count how many modems have a dip at each frequency
            modem_dip_count = np.zeros(n_pts, dtype=int)
            for row in arr:
                row_smooth = _moving_avg(row, win_pts)
                dips = (row - row_smooth) < -6
                modem_dip_count += dips.astype(int)

            ax_lte.bar(common_f, modem_dip_count, width=step * 0.9,
                       color='#dc3545', alpha=0.6)
            ax_lte.set_ylabel('Modems\nw/ dip', fontsize=9)
            ax_lte.set_xlabel('Frequency (MHz)', fontsize=10)
            ax_lte.yaxis.get_major_locator().set_params(integer=True)
            ax_lte.xaxis.set_major_locator(MultipleLocator(50))
            ax_lte.xaxis.set_minor_locator(MultipleLocator(10))
            ax_lte.tick_params(axis='x', labelsize=8)
            ax_lte.grid(True, alpha=0.2)
            ax_lte.tick_params(axis='x', labelrotation=45)

            # ── Bottom: ripple / standing wave detection via FFT ──
            # x-axis = estimated fault distance (m), computed from ripple period
            # d = c / (2 * f_ripple * vf),  vf=0.87,  f_ripple = 1/(period_MHz * 1e6)
            # Short distance (near fault) on the left; long distance (far fault) on right.
            ripple_strength = np.zeros(n_pts // 2)
            for row in arr:
                detrended = row - _moving_avg(row, min(len(row), 200))
                fft_mag = np.abs(np.fft.rfft(detrended))
                if len(fft_mag) > len(ripple_strength):
                    fft_mag = fft_mag[:len(ripple_strength)]
                elif len(fft_mag) < len(ripple_strength):
                    fft_mag = np.pad(fft_mag, (0, len(ripple_strength) - len(fft_mag)))
                ripple_strength += fft_mag
            ripple_strength /= max(len(arr), 1)

            freq_range = max_f - min_f  # MHz
            ripple_period = np.zeros(len(ripple_strength))
            for i in range(1, len(ripple_strength)):
                ripple_period[i] = freq_range / i  # MHz per cycle

            # Convert period → fault distance in metres
            # Show a practical field range for HFC troubleshooting (0-500 m), exclude bin 0 (DC)
            MAX_FAULT_DISTANCE_M = 500
            VF = 0.87
            C  = 3e8
            with np.errstate(divide='ignore', invalid='ignore'):
                dist_m_arr = np.where(
                    ripple_period > 0,
                    C / (2 * (ripple_period * 1e6) * VF),
                    0.0
                )
            valid = (dist_m_arr >= 1) & (dist_m_arr <= MAX_FAULT_DISTANCE_M)
            if np.any(valid):
                d_vals  = dist_m_arr[valid]
                rs_vals = ripple_strength[valid]
                # Sort by distance for a clean left-to-right plot
                sort_idx = np.argsort(d_vals)
                d_sorted  = d_vals[sort_idx]
                rs_sorted = rs_vals[sort_idx]

                ax_ripple.plot(d_sorted, rs_sorted, color='#8b5cf6', linewidth=1.2)
                ax_ripple.fill_between(d_sorted, rs_sorted, alpha=0.15, color='#8b5cf6')

                peak_idx   = np.argmax(rs_sorted)
                peak_dist  = d_sorted[peak_idx]
                peak_val   = rs_sorted[peak_idx]
                noise_floor = np.median(rs_sorted)
                if peak_val > noise_floor * 3:
                    peak_period = freq_range / (np.where(ripple_period[valid] > 0)[0][sort_idx[peak_idx]] + 1)
                    ax_ripple.annotate(
                        f'≈{peak_dist:.0f} m',
                        xy=(peak_dist, peak_val), fontsize=8,
                        xytext=(peak_dist + peak_dist * 0.1, peak_val),
                        arrowprops=dict(arrowstyle='->', color='#6d28d9'),
                        color='#6d28d9', fontweight='bold')
                    dist_ft = peak_dist * 3.281
                    period_mhz = C / (2 * peak_dist * VF * 1e6)
                    detections.append({
                        'type': 'ripple', 'period_mhz': round(period_mhz, 1),
                        'estimated_distance_m': round(peak_dist, 1),
                        'estimated_distance_ft': round(dist_ft, 0),
                        'strength_ratio': round(peak_val / noise_floor, 1)})

            ax_ripple.set_xlabel('Estimated fault distance (m)', fontsize=10)
            ax_ripple.set_ylabel('Ripple\nstrength', fontsize=9)
            ax_ripple.grid(True, alpha=0.2)
            ax_ripple.set_xlim(0, MAX_FAULT_DISTANCE_M)
            # Keep distance ticks readable in the 0-500 m troubleshooting range
            ax_ripple.xaxis.set_major_locator(MultipleLocator(50))
            ax_ripple.tick_params(axis='x', labelsize=8, labelrotation=45)
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            plt.close(fig)
            buf.seek(0)
            plot_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as plot_err:
        logger.warning(f"Fullband matplotlib plot failed: {plot_err}", exc_info=True)

    return jsonify({
        "success":       True,
        "total_modems":  len(eligible),
        "success_count": success_count,
        "modems":        modem_results,
        "detections":    detections,
        "plot_png_b64":  plot_b64,
    })
    return jsonify({
        'snmpCommunity': get_cmts_community(),
        'snmpCommunityRW': get_cmts_write_community(),
        'snmpCommunityModem': get_default_community(),
    })


@pypnm_bp.route('/upstream/utsc/limits', methods=['GET'])
def get_utsc_limits():
    """
    Get E6000 UTSC parameter limits and supported values.
    
    Returns validation constraints for:
    - Frequency range (center_freq_hz, span_hz)
    - Number of bins (num_bins)
    - Timing parameters (repeat_period_ms, freerun_duration_ms)
    - Trigger parameters (trigger_count)
    """
    try:
        from app.core.utsc_validation import get_limits_summary
        limits = get_limits_summary()
        return jsonify(limits), 200
    except Exception as e:
        logger.error(f"Failed to get UTSC limits: {e}")
        return jsonify({"error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/validate', methods=['POST'])
def validate_utsc_parameters():
    """
    Validate UTSC parameters before configuration.
    
    POST body:
    {
        "center_freq_hz": 30000000,
        "span_hz": 60000000,
        "num_bins": 800,
        "trigger_mode": 2,
        "repeat_period_ms": 400,
        "freerun_duration_ms": 120000,
        "trigger_count": 10
    }
    
    Returns:
    {
        "is_valid": true/false,
        "errors": ["error1", "error2"],
        "warnings": ["warning1"],
        "parameters": {...}
    }
    """
    try:
        from app.core.utsc_validation import validate_all_parameters
        
        data = request.json
        result = validate_all_parameters(
            center_freq_hz=data.get('center_freq_hz', 30000000),
            span_hz=data.get('span_hz', 80000000),
            num_bins=data.get('num_bins', 800),
            trigger_mode=data.get('trigger_mode', 2),
            repeat_period_ms=data.get('repeat_period_ms', 1000),
            freerun_duration_ms=data.get('freerun_duration_ms', 60000),
            trigger_count=data.get('trigger_count') if 'trigger_count' in data else None  # Only set if explicitly provided
        )
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Parameter validation failed: {e}")
        return jsonify({"error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/configure/<mac_address>', methods=['POST'])
def configure_utsc(mac_address):
    """
    Configure UTSC (Upstream Triggered Spectrum Capture) test via PyPNM API.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "trigger_mode": 2,
        "center_freq_hz": 30000000,
        "span_hz": 80000000,
        "num_bins": 800,
        "community": "optional"
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    logger.info(
        f"=== UTSC CONFIGURE === MAC: {mac_address} cmts_ip={cmts_ip} "
        f"rf_port_ifindex={rf_port_ifindex} communities=<redacted>"
    )
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        client = PyPNMClient()
        logical_ch_ifindex = data.get('logical_ch_ifindex')

        # Normalize client-provided RF port first.
        try:
            rf_port_ifindex = int(rf_port_ifindex) if rf_port_ifindex is not None else None
        except Exception:
            rf_port_ifindex = None

        # Authoritative source: modem-specific RF port discovery.
        discovered = client.discover_modem_rf_port(
            cmts_ip=cmts_ip,
            cm_mac_address=mac_address,
            community=community,
        )
        discovered_ifindex = None
        if discovered and discovered.get('success') and discovered.get('rf_port_ifindex'):
            try:
                discovered_ifindex = int(discovered.get('rf_port_ifindex'))
            except Exception:
                discovered_ifindex = None

        if discovered_ifindex:
            if rf_port_ifindex and rf_port_ifindex != discovered_ifindex:
                logger.warning(
                    f"UTSC configure overriding client rf_port_ifindex={rf_port_ifindex} "
                    f"with authoritative modem_rf_port={discovered_ifindex}"
                )
            rf_port_ifindex = discovered_ifindex
            logger.info(f"UTSC configure selected modem RF port {rf_port_ifindex} for {mac_address}")
            # Keep UTSC target on physical RF port, but provide logical OFDMA
            # channel ifIndex for vendors that require LogicalChIfIndex.
            if logical_ch_ifindex is None:
                try:
                    discovered_logical = discovered.get('logical_channel')
                    logical_ch_ifindex = int(discovered_logical) if discovered_logical is not None else None
                except Exception:
                    logical_ch_ifindex = None
            if logical_ch_ifindex is not None:
                logger.info(
                    f"UTSC configure using logical_ch_ifindex={logical_ch_ifindex} "
                    f"for rf_port_ifindex={rf_port_ifindex}"
                )
        elif not rf_port_ifindex:
            return jsonify({
                "success": False,
                "error": "No valid rf_port_ifindex and modem RF port discovery failed",
                "rf_port_ifindex": None,
            }), 400

        trigger_mode = data.get('trigger_mode', 2)
        cm_mac = mac_address if trigger_mode == 6 else None
        
        # Convert repeat_period_ms to microseconds for the API
        # Casa minimum: 400ms satisfies both 100ms floor and 120s/300files constraints
        repeat_period_ms = data.get('repeat_period_ms', 400)
        repeat_period_us = repeat_period_ms * 1000

        output_format = data.get('output_format') or None  # None = auto-detect per vendor

        def _configure_once():
            return client.configure_utsc(
                cmts_ip=cmts_ip,
                rf_port_ifindex=rf_port_ifindex,
                community=community,
                write_community=write_community,
                trigger_mode=trigger_mode,
                center_freq_hz=data.get('center_freq_hz', 50000000),
                span_hz=data.get('span_hz', 80000000),
                num_bins=data.get('num_bins', 800),
                output_format=output_format,
                window_function=data.get('window_function', 2),
                repeat_period_us=repeat_period_us,
                freerun_duration_ms=data.get('freerun_duration_ms', 0),  # 0 = auto (service clamps to 120s min)
                trigger_count=data.get('trigger_count', 1),
                filename=data.get('filename', f'utsc_{mac_address.replace(":", "")}'),
                cm_mac_address=cm_mac,
                logical_ch_ifindex=logical_ch_ifindex,
            )

        # Row management (probe / clear / createAndWait for Arris) is handled
        # inside PyPNM's UTSC service — no GUI-side retry needed.
        result = _configure_once()

        if isinstance(result, dict):
            result['rf_port_ifindex'] = rf_port_ifindex
        logger.info(f"UTSC configure result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Configure UTSC failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/start/<mac_address>', methods=['POST'])
def start_utsc(mac_address):
    """
    Start UTSC test on CMTS via PyPNM API.
    
    Automatically configures with optimal defaults before starting:
    - TriggerMode = 2 (FreeRunning)
    - TriggerCount = 0 (auto-cleared for FreeRunning)  
    - RepeatPeriod = 50ms (E6000 minimum)
    - FreeRunDuration = 180s (3 minutes)
    - Window = rectangular(2)
    """
    from app.core.pypnm_client import PyPNMClient
    
    logger.info(f"=== UTSC START === MAC: {mac_address}")
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    # Optional overrides (use correct defaults if not provided)
    trigger_mode = data.get('trigger_mode', 2)  # FreeRunning
    freerun_duration_ms = data.get('freerun_duration_ms', 120000)
    repeat_period_ms = data.get('repeat_period_ms', 400)
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        cfg_index = int(data.get('cfg_index', 0) or 0)
        trigger_mode = data.get('trigger_mode', 2)

        # Just start — configure was already done by the caller
        result = client.start_utsc(cmts_ip, rf_port_ifindex, community, write_community, cfg_index=cfg_index, trigger_mode=trigger_mode)
        logger.info(f"UTSC start result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Start UTSC failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/stop/<mac_address>', methods=['POST'])
def stop_utsc(mac_address):
    """Stop UTSC test on CMTS via PyPNM API."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    cfg_index = int(data.get('cfg_index', 1) or 1)
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client.stop_utsc(
            cmts_ip,
            rf_port_ifindex,
            community,
            write_community,
            cfg_index=cfg_index,
        )
        return jsonify({
            "success": result.get('success', True),
            **result
        })
        
    except Exception as e:
        logger.error(f"Stop UTSC failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/clear/<mac_address>', methods=['POST'])
def clear_utsc(mac_address):
    """
    Clear/reset UTSC configuration on CMTS by setting RowStatus=6 (destroy).
    
    Use this to force reconfiguration with updated parameters.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 1074339840,
        "community": "optional"
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    logger.info(f"=== UTSC CLEAR === MAC: {mac_address}")
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client.clear_utsc(cmts_ip, rf_port_ifindex, community, write_community)
        logger.info(f"UTSC clear result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Clear UTSC failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/status/<mac_address>', methods=['POST'])
def get_utsc_status(mac_address):
    """
    Get UTSC test status from CMTS via PyPNM API.
    
    Returns:
    - meas_status: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client.get_utsc_status(cmts_ip, rf_port_ifindex, community, write_community)
        
        return jsonify({
            "success": result.get('success', True),
            "mac_address": mac_address,
            **result
        })
        
    except Exception as e:
        logger.error(f"Get UTSC status failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/rxmer/start/<mac_address>', methods=['POST'])
def start_us_rxmer(mac_address):
    """
    Start Upstream OFDMA RxMER measurement on CMTS via PyPNM API.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "ofdma_ifindex": 12345,
        "pre_eq": true,
        "filename": "optional",
        "community": "optional"
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        # PyPNM detects the CMTS vendor and owns destination provisioning.
        result = client._post("/pnm/us/ofdma/rxmer/start", {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community,
                "write_community": write_community,
            },
            "ofdma_ifindex": ofdma_ifindex,
            "cm_mac_address": mac_address,
            "pre_eq": data.get('pre_eq', True),
            "num_averages": data.get('num_averages', 1),
            "filename": data.get('filename', f'usrxmer_{mac_address.replace(":", "")}'),
            "destination_index": int(data.get('destination_index') or 0),
        })
        
        if not result or result.get('status') == 'error':
            error_msg = result.get('error', result.get('message', 'Start failed')) if result else 'No response'
            return jsonify({"status": "error", "message": error_msg}), 500
        
        response = {
            "success": result.get('success', True),
            "mac_address": mac_address,
            **result
        }
        
        logger.info(f"US RxMER started for {mac_address}, filename: {response.get('filename')}, result: {result}")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Start US RxMER failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/rxmer/status/<mac_address>', methods=['POST'])
def get_us_rxmer_status(mac_address):
    """Get Upstream RxMER measurement status via PyPNM API."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client._post("/pnm/us/rxmer/status", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "community": community
        })
        
        if not result or result.get('status') == 'error':
            error_msg = result.get('error', result.get('message', 'Status check failed')) if result else 'No response'
            return jsonify({"status": "error", "message": error_msg}), 500
        
        return jsonify({
            "success": result.get('success', True),
            "mac_address": mac_address,
            **result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER status failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/data/<mac_address>', methods=['POST'])
def get_utsc_data(mac_address):
    """Return the latest normalized UTSC sample from PyPNM."""
    from app.core.pypnm_client import PyPNMClient

    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    if not cmts_ip:
        return jsonify({'status': 'error', 'message': 'cmts_ip required'}), 400

    vendor = None
    try:
        from app.core.cmts_provider import CMTSProvider
        cmts = CMTSProvider.get_cmts_by_ip(cmts_ip) or {}
        vendor_text = f"{cmts.get('Vendor', '')} {cmts.get('Type', '')}".lower()
        if 'cisco' in vendor_text or 'cbr' in vendor_text:
            vendor = 'cisco'
        elif any(token in vendor_text for token in ('casa', 'evo', 'vccap')):
            vendor = 'casa'
        elif any(token in vendor_text for token in ('arris', 'commscope', 'e6000')):
            vendor = 'commscope'
    except Exception:
        pass

    config = {}
    try:
        config_json = redis_client.get(f'utsc_config:{mac_address}')
        config = json.loads(config_json) if config_json else {}
    except Exception as exc:
        logger.warning("Failed to retrieve UTSC presentation config: %s", exc)

    mac_clean = mac_address.replace(':', '').replace('-', '').lower()
    rf_port = data.get('rf_port_ifindex')
    requested = data.get('filename')
    requested_pattern = f"{str(requested).rsplit('/', 1)[-1]}*" if requested else None
    patterns = [requested_pattern] if requested_pattern else [f'utsc_{mac_clean}*']
    if rf_port:
        patterns.append(f'PNMCcapUsSpecAn_*_{rf_port}')
    patterns.append('PNMCcapUsSpecAn_*')

    try:
        client = PyPNMClient()
        filenames = []
        for pattern in patterns:
            result = client.list_utsc_files(
                prefix=pattern,
                rf_port_ifindex=int(rf_port) if rf_port else None,
                mac_address=mac_address,
                vendor=vendor,
            )
            if result.get('success'):
                filenames.extend(result.get('files') or [])
        filenames = sorted({str(name).rsplit('/', 1)[-1] for name in filenames}, reverse=True)
        if not filenames:
            return jsonify({
                'success': True,
                'message': 'No UTSC data available yet. Start a measurement to begin.',
                'data': None,
            })

        sample = client.get_utsc_sample(
            filename=filenames[0],
            vendor=vendor,
            center_freq_hz=int(config.get('center_freq_hz', 45000000)),
            span_hz=int(config.get('span_hz', 80000000)),
            max_bins=1600,
        )
        if not sample.get('success'):
            return jsonify({'success': False, 'message': sample.get('error', 'UTSC parse failed')}), 502

        bins = sample.get('bins') or []
        freq_start = float(sample.get('freq_start_hz') or 0)
        freq_step = float(sample.get('freq_step_hz') or 1)
        spectrum_data = {
            'filename': sample.get('filename'),
            'file_mtime': sample.get('collected_at'),
            'file_size': sample.get('file_size'),
            'num_samples': len(bins),
            'frequencies': [freq_start + index * freq_step for index in range(min(800, len(bins)))],
            'amplitudes': bins[:800],
            'span_hz': sample.get('span_hz'),
            'center_freq_hz': sample.get('center_freq_hz'),
            'num_bins': sample.get('num_bins', len(bins)),
            'units': sample.get('units', 'dBmV'),
        }
        response = {'success': True, 'mac_address': mac_address, 'data': spectrum_data}
        if data.get('include_plot', False):
            from app.core.utsc_plotter import generate_utsc_plot_from_data
            response['plot'] = generate_utsc_plot_from_data(
                spectrum_data,
                mac_address,
                data.get('rf_port_description', ''),
            )
        return jsonify(response)
    except Exception as exc:
        logger.error("Get UTSC data failed: %s", exc, exc_info=True)
        return jsonify({'status': 'error', 'message': str(exc)}), 500


@pypnm_bp.route('/upstream/rxmer/data/<mac_address>', methods=['POST'])
def get_us_rxmer_data(mac_address):
    """
    Fetch Upstream RxMER data from TFTP server.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "ofdma_ifindex": 12345,
        "filename": "optional",
        "community": "optional"
    }
    
    Returns RxMER per subcarrier for graphing.
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        client = PyPNMClient()
        result = client._post("/pnm/us/rxmer/data", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "filename": data.get('filename'),
            "community": community
        })
        
        if not result or result.get('status') == 'error':
            error_msg = result.get('error', result.get('message', 'Data retrieval failed')) if result else 'No response'
            return jsonify({"status": "error", "message": error_msg}), 500
        
        return jsonify({
            "success": result.get('success', True),
            "mac_address": mac_address,
            **result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER data failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/rxmer/plot/<mac_address>', methods=['POST'])
def get_us_rxmer_plot(mac_address):
    """
    Fetch Upstream RxMER plot from PyPNM API.
    
    POST body:
    {
        "filename": "usrxmer_90324bc81373_2026-01-28_12.13.25.870"
    }
    
    Returns PNG image of the RxMER spectrum.
    """
    import io
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from flask import Response as FlaskResponse
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    full_filename = data.get('filename')  # Optional: may be ignored by agent path
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', get_cmts_community())
    
    logger.info(f"US RxMER plot request for {mac_address}, filename: {full_filename}")
    
    if not cmts_ip:
        logger.error("No cmts_ip provided in request")
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        # Source of truth for modem-side US RxMER is the agent-backed data endpoint.
        # Avoid file-based /getCapture path that can fail when files are not local.
        client = PyPNMClient()
        data_resp = client._post("/pnm/us/rxmer/data", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "filename": full_filename,
            "community": community,
        })

        if not data_resp or data_resp.get('status') == 'error' or not data_resp.get('success'):
            error_msg = (data_resp or {}).get('error') or (data_resp or {}).get('message') or 'Data retrieval failed'
            return jsonify({"status": "error", "message": error_msg}), 500

        payload = data_resp.get('data') or {}
        subcarriers = payload.get('subcarriers') or []
        rxmer_values = payload.get('rxmer_values') or []
        if not subcarriers or not rxmer_values:
            return jsonify({"status": "error", "message": "No RxMER data available yet"}), 404

        # Keep arrays aligned.
        n = min(len(subcarriers), len(rxmer_values))
        subcarriers = subcarriers[:n]
        rxmer_values = rxmer_values[:n]

        fig, ax = plt.subplots(figsize=(12, 4.5))
        ax.plot(subcarriers, rxmer_values, color='#2563eb', linewidth=1.2)
        ax.fill_between(subcarriers, rxmer_values, alpha=0.15, color='#2563eb')
        ax.axhline(y=35, color='#16a34a', linestyle='--', alpha=0.7, linewidth=1, label='Good (>=35 dB)')
        ax.axhline(y=30, color='#f59e0b', linestyle='--', alpha=0.7, linewidth=1, label='Marginal (>=30 dB)')
        ax.set_xlabel('Subcarrier Index')
        ax.set_ylabel('RxMER (dB)')
        ax.set_title(f'Upstream OFDMA RxMER - {mac_address}')
        ax.grid(True, alpha=0.25)
        ax.legend(loc='lower right', fontsize=8)
        plt.tight_layout()

        out = io.BytesIO()
        fig.savefig(out, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        out.seek(0)

        return FlaskResponse(
            out.getvalue(),
            mimetype='image/png',
            headers={'Content-Disposition': f'inline; filename=us_rxmer_{mac_address.replace(":", "")}.png'}
        )

    except Exception as e:
        logger.error(f"Get US RxMER plot failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/cleanup', methods=['POST'])
def cleanup_old_files():
    """Clean up old PNM measurement files."""
    try:
        import glob
        import time
        
        # Clean up temp files older than 1 hour
        temp_dir = tempfile.gettempdir()
        cleanup_count = 0
        cutoff_time = time.time() - 3600  # 1 hour ago
        
        # Clean PNG, CSV, and ZIP files in temp directory
        patterns = ['*_rxmer*.png', '*_spectrum*.png', '*_channel*.png', '*_modulation*.png', 
                   '*.csv', 'pnm_*.zip']
        
        for pattern in patterns:
            for filepath in glob.glob(os.path.join(temp_dir, pattern)):
                try:
                    if os.path.getmtime(filepath) < cutoff_time:
                        os.remove(filepath)
                        cleanup_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {filepath}: {e}")
        
        logger.info(f"Cleaned up {cleanup_count} old PNM files")
        return jsonify({"success": True, "files_removed": cleanup_count})
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============== OFDM/OFDMA Impulse Response (existing files by default) ==============

_impulse_job_progress: dict[str, dict] = {}
_impulse_job_results: dict[str, dict] = {}
_impulse_job_abort: set[str] = set()
_impulse_job_lock = _threading.Lock()
_IMPULSE_JOB_TTL = 3600


def _impulse_progress_key(job_id: str) -> str:
    return f"impulse_progress:{job_id}"


def _impulse_result_key(job_id: str) -> str:
    return f"impulse_result:{job_id}"


def _set_impulse_job_progress(job_id: str, **fields):
    if not job_id:
        return
    with _impulse_job_lock:
        current = _impulse_job_progress.setdefault(job_id, {})
        current.update(fields)
    if REDIS_AVAILABLE:
        try:
            redis_client.hset(_impulse_progress_key(job_id), mapping={k: str(v) for k, v in fields.items()})
            redis_client.expire(_impulse_progress_key(job_id), _IMPULSE_JOB_TTL)
        except Exception:
            pass


def _store_impulse_job_result(job_id: str, result: dict):
    with _impulse_job_lock:
        _impulse_job_results[job_id] = result
    if REDIS_AVAILABLE:
        try:
            redis_client.set(_impulse_result_key(job_id), json.dumps(result), ex=_IMPULSE_JOB_TTL)
        except Exception:
            pass


def _get_impulse_job_result(job_id: str) -> dict | None:
    with _impulse_job_lock:
        result = _impulse_job_results.get(job_id)
    if result is not None:
        return result
    if REDIS_AVAILABLE:
        try:
            raw = redis_client.get(_impulse_result_key(job_id))
            return json.loads(raw) if raw else None
        except Exception:
            return None
    return None


def _is_impulse_job_aborted(job_id: str) -> bool:
    with _impulse_job_lock:
        return job_id in _impulse_job_abort


def _capture_response_ok(result: dict) -> bool:
    status = result.get('status')
    if isinstance(status, int):
        return status == 0
    if status is not None:
        return str(status).upper() in {'SUCCESS', '0'}
    return result.get('success') is True


def _analysis_pnm_file_type(analysis: dict, direction: str) -> str:
    """Return the decoded PNM type without inventing a channel identity."""
    fallback = 'PNN2' if direction == 'downstream' else 'PNN6'
    header = analysis.get('pnm_header')
    if not isinstance(header, dict):
        return fallback

    file_type = str(header.get('file_type') or '').strip().upper()
    version = str(header.get('file_type_version') or '').strip()
    decoded_type = f'{file_type}{version}'
    if decoded_type in {'PNN2', 'PNN6', 'PNN7'}:
        return decoded_type
    return fallback


def _capture_analysis_items(result: dict, direction: str) -> list[dict]:
    data = result.get('data')
    if isinstance(data, dict):
        analyses = data.get('analysis') or data.get('data') or []
    else:
        analyses = data or []
    if isinstance(analyses, dict):
        analyses = [analyses]
    if not isinstance(analyses, list):
        return []

    return [
        {
            'file_id': '',
            'filename': '',
            'pnm_file_type': _analysis_pnm_file_type(analysis, direction),
            'direction': direction,
            'analysis': analysis,
        }
        for analysis in analyses
        if isinstance(analysis, dict)
    ]


def _select_primary_impulse_items(items: list[dict], direction: str) -> list[dict]:
    """Keep one current measurement per decoded channel for impulse display."""
    selected = items
    if direction == 'upstream':
        current_pre_equalizer = [
            item for item in items
            if item.get('pnm_file_type') == 'PNN6'
        ]
        if current_pre_equalizer:
            selected = current_pre_equalizer

    unique_items: list[dict] = []
    seen_channels: set[str] = set()
    for item in selected:
        analysis = item.get('analysis')
        channel_id = analysis.get('channel_id') if isinstance(analysis, dict) else None
        if channel_id is None:
            unique_items.append(item)
            continue
        channel_key = str(channel_id)
        if channel_key in seen_channels:
            continue
        seen_channels.add(channel_key)
        unique_items.append(item)
    return unique_items


_BULK_IMPULSE_CHART_MAX_POINTS = 1024


def _paired_vector_extrema(
    x_values: object,
    y_values: object,
    *,
    max_points: int = _BULK_IMPULSE_CHART_MAX_POINTS,
    max_x: float | None = None,
) -> tuple[list[tuple[float, float]], int]:
    """Return finite paired samples with endpoints and per-bucket extrema preserved."""
    if not isinstance(x_values, list) or not isinstance(y_values, list):
        return [], 0

    pairs: list[tuple[int, float, float]] = []
    for index, (raw_x, raw_y) in enumerate(zip(x_values, y_values)):
        try:
            x_value = float(raw_x)
            y_value = float(raw_y)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            continue
        if max_x is not None:
            boundary_tolerance = max(abs(max_x) * 1e-12, 1e-15)
            if x_value > max_x + boundary_tolerance:
                continue
        pairs.append((index, x_value, y_value))

    source_count = len(pairs)
    max_points = max(2, int(max_points))
    if source_count <= max_points:
        return [(x_value, y_value) for _, x_value, y_value in pairs], source_count

    bucket_count = max(1, (max_points - 2) // 2)
    bucket_size = math.ceil((source_count - 2) / bucket_count)
    sampled = [pairs[0]]
    for start in range(1, source_count - 1, bucket_size):
        bucket = pairs[start:min(source_count - 1, start + bucket_size)]
        minimum = min(bucket, key=lambda pair: pair[2])
        maximum = max(bucket, key=lambda pair: pair[2])
        if minimum[0] == maximum[0]:
            sampled.append(minimum)
        elif minimum[0] < maximum[0]:
            sampled.extend((minimum, maximum))
        else:
            sampled.extend((maximum, minimum))
    sampled.append(pairs[-1])
    return [(x_value, y_value) for _, x_value, y_value in sampled[:max_points]], source_count


def _linear_carrier_magnitudes(carrier: dict) -> object:
    """Prefer unambiguous complex amplitudes; fall back to schema-declared linear magnitudes."""
    complex_values = carrier.get('complex')
    if not isinstance(complex_values, list):
        return carrier.get('magnitudes')

    amplitudes: list[float] = []
    valid_count = 0
    for value in complex_values:
        try:
            if isinstance(value, complex):
                amplitude = abs(value)
            elif isinstance(value, (list, tuple)) and len(value) == 2:
                amplitude = math.hypot(float(value[0]), float(value[1]))
            else:
                amplitude = float('nan')
        except (TypeError, ValueError):
            amplitude = float('nan')
        if math.isfinite(amplitude):
            valid_count += 1
        amplitudes.append(amplitude)
    return amplitudes if valid_count else carrier.get('magnitudes')


def _compact_bulk_impulse_result(item: dict) -> dict:
    """Keep bulk manifests bounded while retaining display-only comparison vectors."""
    analysis = item.get('analysis') or {}
    echo = analysis.get('echo') or {}
    report = dict(echo.get('report') or {})
    time_response = report.pop('time_response', None) or {}
    carrier = analysis.get('carrier_values') or {}
    chart_data: dict[str, dict] = {}

    frequency_pairs, frequency_source_count = _paired_vector_extrema(
        carrier.get('frequency'),
        _linear_carrier_magnitudes(carrier),
    )
    frequency_points = [
        (frequency_hz / 1e6, 20.0 * math.log10(max(magnitude, 1e-12)))
        for frequency_hz, magnitude in frequency_pairs
        if magnitude >= 0
    ]
    if frequency_points:
        chart_data['frequency_response'] = {
            'frequency_mhz': [round(point[0], 6) for point in frequency_points],
            'magnitude_db': [round(point[1], 4) for point in frequency_points],
            'source_point_count': frequency_source_count,
            'display_point_count': len(frequency_points),
        }

    max_delay_s = report.get('max_delay_s')
    try:
        max_delay_s = float(max_delay_s) if max_delay_s is not None else None
        if max_delay_s is not None and (not math.isfinite(max_delay_s) or max_delay_s < 0):
            max_delay_s = None
    except (TypeError, ValueError):
        max_delay_s = None
    impulse_pairs, impulse_source_count = _paired_vector_extrema(
        time_response.get('time_axis_s'),
        time_response.get('time_response'),
        max_x=max_delay_s,
    )
    positive_amplitudes = [amplitude for _, amplitude in impulse_pairs if amplitude >= 0]
    reference = max(positive_amplitudes, default=0.0)
    impulse_points = [
        (delay_s * 1e6, 20.0 * math.log10(max(amplitude, 1e-12) / max(reference, 1e-12)))
        for delay_s, amplitude in impulse_pairs
        if amplitude >= 0
    ]
    if impulse_points:
        chart_data['impulse_response'] = {
            'delay_us': [round(point[0], 6) for point in impulse_points],
            'relative_db': [round(point[1], 4) for point in impulse_points],
            'source_point_count': impulse_source_count,
            'display_point_count': len(impulse_points),
            'max_delay_us': round(max_delay_s * 1e6, 6) if max_delay_s is not None else None,
            'response_kind': report.get('response_kind', 'detector_windowed'),
        }

    return {
        'file_id': item.get('file_id', ''),
        'filename': item.get('filename', ''),
        'pnm_file_type': item.get('pnm_file_type', ''),
        'direction': item.get('direction', ''),
        'chart_data': chart_data,
        'analysis': {
            'channel_id': analysis.get('channel_id'),
            'subcarrier_spacing': analysis.get('subcarrier_spacing'),
            'first_active_subcarrier_index': analysis.get('first_active_subcarrier_index'),
            'subcarrier_zero_frequency': analysis.get('subcarrier_zero_frequency'),
            'carrier_values': {
                'carrier_count': carrier.get('carrier_count'),
                'occupied_channel_bandwidth': carrier.get('occupied_channel_bandwidth'),
            },
            'echo': {'type': echo.get('type'), 'report': report},
        },
    }


def _impulse_failure_status(response: dict | None) -> str:
    """Classify a capture failure without relying on one endpoint's wording."""
    response = response if isinstance(response, dict) else {}
    explicit = str(response.get('failure_status') or '').lower()
    if explicit in {'timeout', 'capture_failed', 'analysis_failed', 'agent_unavailable'}:
        return explicit
    text = ' '.join(str(response.get(key) or '') for key in ('error', 'message', 'detail')).lower()
    if 'timed out' in text or 'timeout' in text:
        return 'timeout'
    if any(marker in text for marker in (
        'no connected agent', 'no agent available', 'agent manager',
        'agent is not connected', 'pinned agent',
    )):
        return 'agent_unavailable'
    return 'capture_failed'


def _bulk_impulse_direction_statuses(response: dict, requested_direction: str, source: str) -> list[dict]:
    """Summarize each requested direction without exposing paths or agent details."""
    directions = [requested_direction] if requested_direction != 'both' else ['downstream', 'upstream']
    results = response.get('results') or []
    outcomes = {
        str(item.get('direction')): item
        for item in (response.get('direction_outcomes') or [])
        if isinstance(item, dict) and item.get('direction')
    }
    warnings = [str(item) for item in (response.get('warnings') or [])]
    warning_text = ' '.join(warnings).lower()
    error = str(response.get('error') or response.get('message') or '')
    error_text = error.lower()
    statuses: list[dict] = []

    for item_direction in directions:
        outcome = outcomes.get(item_direction)
        if outcome:
            status = str(outcome.get('status') or 'capture_failed')
            message = str(outcome.get('message') or 'Fresh capture failed')
        elif any(item.get('direction') == item_direction for item in results):
            status = 'analyzed' if source == 'existing' else 'captured_analyzed'
            message = (
                'Fresh agent catalog entry retrieved and analyzed'
                if source == 'existing'
                else 'Fresh capture analyzed'
            )
        elif source == 'fresh':
            status = _impulse_failure_status(response)
            message = error or 'Fresh capture did not produce analyzable data'
        elif 'no connected file agent' in error_text or 'agent manager unavailable' in error_text:
            status = 'agent_unavailable'
            message = 'No connected file agent supports PNM retrieval'
        elif f'no existing {item_direction}' in warning_text:
            status = 'missing'
            message = 'No matching file in the fresh agent catalog'
        elif f'fresh retrieval of {item_direction}' in warning_text or f'{item_direction} file unavailable' in warning_text:
            status = 'retrieval_failed'
            message = 'Catalog match existed but current file retrieval failed'
        elif 'analysis failed for' in warning_text or 'no matching existing pnm file could be analyzed' in error_text:
            status = 'analysis_failed'
            message = 'Retrieved data could not be parsed or analyzed'
        else:
            status = 'unavailable'
            message = error or 'No current file could be analyzed'
        statuses.append({'direction': item_direction, 'status': status, 'message': message})
    return statuses


def _run_fresh_impulse_capture(
    client,
    mac_address: str,
    modem_ip: str,
    direction: str,
    community: str,
    tftp_ip: str,
    velocity_factor: float,
) -> dict:
    """Explicit side-effecting path. Existing-file callers never enter here."""
    results: list[dict] = []
    warnings: list[str] = []
    outcomes: list[dict] = []
    directions = [direction] if direction != 'both' else ['downstream', 'upstream']
    for item_direction in directions:
        try:
            if item_direction == 'downstream':
                response = client.get_channel_estimation(
                    mac_address, modem_ip, tftp_ip, community,
                    tftp_ipv6='::1', output_type='json', velocity_factor=velocity_factor,
                )
            else:
                response = client.get_us_ofdma_pre_equalization(
                    mac_address, modem_ip, tftp_ip, community,
                    tftp_ipv6='::1', output_type='json', velocity_factor=velocity_factor,
                )
        except Exception as exc:
            response = {'success': False, 'error': str(exc)}

        if not isinstance(response, dict) or not _capture_response_ok(response):
            message = response.get('message') or response.get('error') if isinstance(response, dict) else 'invalid response'
            status = _impulse_failure_status(response)
            warnings.append(f'{item_direction} capture failed: {message}')
            outcomes.append({
                'direction': item_direction,
                'status': status,
                'message': str(message or 'Fresh capture failed'),
            })
            continue
        items = _select_primary_impulse_items(
            _capture_analysis_items(response, item_direction),
            item_direction,
        )
        if not items:
            message = 'Fresh capture returned no analyzable data'
            warnings.append(f'{item_direction} capture returned no analysis')
            outcomes.append({'direction': item_direction, 'status': 'analysis_failed', 'message': message})
            continue
        results.extend(items)
        outcomes.append({
            'direction': item_direction,
            'status': 'captured_analyzed',
            'message': 'Fresh capture analyzed',
        })
    return {
        'success': bool(results),
        'source': 'fresh_capture',
        'mac_address': mac_address,
        'direction': direction,
        'velocity_factor': velocity_factor,
        'results': results,
        'direction_outcomes': outcomes,
        'warnings': warnings,
        'error': None if results else 'No fresh capture could be analyzed',
    }


def _impulse_job_direction_counts(modem_results: list[dict]) -> dict:
    """Aggregate direction outcomes independently from modem-level success."""
    status_counts: dict[str, int] = {}
    for modem in modem_results:
        for item in modem.get('direction_statuses') or []:
            status = str(item.get('status') or 'unavailable')
            status_counts[status] = status_counts.get(status, 0) + 1
    analyzed_count = sum(status_counts.get(status, 0) for status in ('analyzed', 'captured_analyzed'))
    direction_attempt_count = sum(status_counts.values())
    known_failures = sum(status_counts.get(status, 0) for status in (
        'timeout', 'capture_failed', 'analysis_failed', 'agent_unavailable',
    ))
    return {
        'direction_attempt_count': direction_attempt_count,
        'analyzed_direction_count': analyzed_count,
        'timeout_count': status_counts.get('timeout', 0),
        'capture_failed_count': status_counts.get('capture_failed', 0),
        'analysis_failed_count': status_counts.get('analysis_failed', 0),
        'agent_unavailable_count': status_counts.get('agent_unavailable', 0),
        'other_failure_count': max(0, direction_attempt_count - analyzed_count - known_failures),
    }


def _impulse_failure_summary(counts: dict) -> str:
    labels = (
        ('timeout_count', 'timed out'),
        ('capture_failed_count', 'capture failed'),
        ('analysis_failed_count', 'analysis failed'),
        ('agent_unavailable_count', 'agent unavailable'),
        ('other_failure_count', 'other failure'),
    )
    parts = [f"{int(counts.get(key, 0))} {label}" for key, label in labels if int(counts.get(key, 0))]
    return ', '.join(parts) if parts else 'no direction failures'


@pypnm_bp.route('/impulse-response/<mac_address>/files', methods=['GET'])
def list_impulse_response_files(mac_address):
    """List sanitized existing PNN2/PNN6/PNN7 files through the PyPNM API."""
    from app.core.pypnm_client import PyPNMClient

    direction = request.args.get('direction', 'both')
    if direction not in {'downstream', 'upstream', 'both'}:
        return jsonify({'success': False, 'error': 'Invalid direction'}), 400
    result = PyPNMClient().list_remote_impulse_files(mac_address, direction)
    http_status = 200 if result.get('success') else 503
    return jsonify(result), http_status


@pypnm_bp.route('/impulse-response/<mac_address>/analyze', methods=['POST'])
def analyze_impulse_response(mac_address):
    """Always capture and analyze fresh OFDM/OFDMA impulse-response data."""
    from app.core.pypnm_client import PyPNMClient

    data = request.get_json(silent=True) or {}
    direction = data.get('direction', 'both')
    if direction not in {'downstream', 'upstream', 'both'}:
        return jsonify({'success': False, 'status': 1, 'error': 'Invalid direction'}), 400
    try:
        velocity_factor = _parse_velocity_factor(data.get('velocity_factor'))
    except ValueError as exc:
        return jsonify({'success': False, 'status': 1, 'error': str(exc)}), 400

    modem_ip = str(data.get('modem_ip') or '').strip()
    if not modem_ip:
        return jsonify({'success': False, 'status': 1, 'error': 'modem_ip required for fresh capture'}), 400

    result = _run_fresh_impulse_capture(
        client=PyPNMClient(),
        mac_address=mac_address,
        modem_ip=modem_ip,
        direction=direction,
        community=data.get('community') or get_default_write_community(),
        tftp_ip=data.get('tftp_ip') or get_tftp_for_cm(),
        velocity_factor=velocity_factor,
    )

    result['status'] = 0 if result.get('success') else 1
    return jsonify(result), 200 if result.get('success') else 404


@pypnm_bp.route('/impulse-response/fibernode/jobs', methods=['POST'])
def start_fibernode_impulse_job():
    """Start a bounded-concurrency bulk impulse analysis over an immutable modem snapshot."""
    from app.core.pypnm_client import PyPNMClient
    import uuid

    data = request.get_json(silent=True) or {}
    source = data.get('source', 'existing')
    direction = data.get('direction', 'both')
    if source not in {'existing', 'fresh'} or direction not in {'downstream', 'upstream', 'both'}:
        return jsonify({'success': False, 'error': 'Invalid source or direction'}), 400
    try:
        velocity_factor = _parse_velocity_factor(data.get('velocity_factor'))
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    raw_targets = data.get('targets') or []
    targets: list[dict] = []
    seen: set[str] = set()
    for raw in raw_targets[:100]:
        mac = str(raw.get('mac_address') or '').strip()
        normalized = re.sub(r'[^0-9a-f]', '', mac.lower())
        if len(normalized) != 12 or normalized in seen:
            continue
        seen.add(normalized)
        targets.append({'mac_address': mac, 'ip_address': str(raw.get('ip_address') or '').strip()})
    if not targets:
        return jsonify({'success': False, 'error': 'At least one valid modem target is required'}), 400
    if source == 'fresh' and any(not target['ip_address'] for target in targets):
        return jsonify({'success': False, 'error': 'Every fresh-capture target requires an IP address'}), 400

    job_id = str(data.get('job_id') or uuid.uuid4())
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', job_id):
        return jsonify({'success': False, 'error': 'Invalid job_id'}), 400
    with _impulse_job_lock:
        existing_job = _impulse_job_progress.get(job_id)
        if existing_job and str(existing_job.get('done', False)).lower() != 'true':
            return jsonify({'success': False, 'error': 'A job with this ID is already running'}), 409
    concurrency = max(1, min(int(data.get('concurrency') or 3), 5))
    # Fiber impulse is modem-side PNM. Resolve its configured modem community
    # server-side; never reuse the CMTS scan/write community from the browser.
    community = get_default_community() if source == 'fresh' else ''
    tftp_ip = (data.get('tftp_ip') or get_tftp_for_cm()) if source == 'fresh' else ''
    topology_date = data.get('topology_date')
    fiber_node = data.get('fiber_node')
    target_snapshot = [dict(target) for target in targets]
    operations_per_modem = (2 if direction == 'both' else 1) if source == 'fresh' else 1
    timeout_budget_s = math.ceil(len(target_snapshot) / concurrency) * operations_per_modem * 180 + 60
    empty_direction_counts = _impulse_job_direction_counts([])

    job_started_monotonic = time.monotonic()
    with _impulse_job_lock:
        _impulse_job_abort.discard(job_id)
    _set_impulse_job_progress(
        job_id,
        total=len(target_snapshot), completed=0, success_count=0, failure_count=0,
        running_count=0, queued_count=len(target_snapshot),
        modem='', action='Queued', state='queued', elapsed_s=0, pct=0, done=False,
        velocity_factor=velocity_factor,
        **empty_direction_counts,
    )

    def _worker(target: dict) -> dict:
        if _is_impulse_job_aborted(job_id):
            return {'mac_address': target['mac_address'], 'success': False, 'aborted': True, 'results': []}
        worker_client = PyPNMClient()
        if source == 'existing':
            response = worker_client.analyze_remote_impulse(target['mac_address'], direction)
        else:
            response = _run_fresh_impulse_capture(
                worker_client,
                target['mac_address'],
                target['ip_address'],
                direction,
                community,
                tftp_ip,
                velocity_factor,
            )
        return {
            'mac_address': target['mac_address'],
            'ip_address': target['ip_address'] if source == 'fresh' else '',
            'success': bool(response.get('success')),
            'velocity_factor': velocity_factor if source == 'fresh' else None,
            'retrieval_mode': 'fresh_agent_catalog' if source == 'existing' else 'fresh_capture',
            'direction_statuses': _bulk_impulse_direction_statuses(response, direction, source),
            'results': [_compact_bulk_impulse_result(item) for item in (response.get('results') or [])],
            'warnings': response.get('warnings') or [],
            'error': response.get('error') or response.get('message'),
        }

    def _run_job():
        modem_results: list[dict] = []
        completed = 0
        success_count = 0
        total = len(target_snapshot)
        active_workers = min(concurrency, total)
        try:
            _set_impulse_job_progress(
                job_id,
                total=total, completed=0, success_count=0, failure_count=0,
                running_count=active_workers, queued_count=max(0, total - active_workers),
                action=f'Analyzing {total} modem attempt{"s" if total != 1 else ""}',
                state='running', elapsed_s=round(time.monotonic() - job_started_monotonic, 2),
                pct=0, done=False,
                **empty_direction_counts,
            )
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                future_map = {pool.submit(_worker, target): target for target in target_snapshot}
                for future in as_completed(future_map):
                    target = future_map[future]
                    try:
                        modem_result = future.result()
                    except Exception as exc:
                        failure_response = {
                            'success': False,
                            'error': str(exc),
                            'failure_status': _impulse_failure_status({'error': str(exc)}),
                        }
                        modem_result = {
                            'mac_address': target['mac_address'],
                            'ip_address': target['ip_address'],
                            'success': False,
                            'direction_statuses': _bulk_impulse_direction_statuses(
                                failure_response, direction, source,
                            ),
                            'results': [],
                            'warnings': [],
                            'error': str(exc),
                        }
                    modem_results.append(modem_result)
                    completed += 1
                    if modem_result.get('success'):
                        success_count += 1
                    failure_count = completed - success_count
                    direction_counts = _impulse_job_direction_counts(modem_results)
                    remaining = total - completed
                    running_count = min(concurrency, remaining)
                    queued_count = max(0, remaining - running_count)
                    _set_impulse_job_progress(
                        job_id,
                        total=total, completed=completed,
                        success_count=success_count, failure_count=failure_count,
                        running_count=running_count, queued_count=queued_count,
                        modem='',
                        action=f'{completed} attempt{"s" if completed != 1 else ""} finished',
                        state='running',
                        elapsed_s=round(time.monotonic() - job_started_monotonic, 2),
                        pct=round(completed * 100 / total, 1),
                        done=False,
                        **direction_counts,
                    )
                    if _is_impulse_job_aborted(job_id):
                        for pending in future_map:
                            pending.cancel()
                        break

            aborted = _is_impulse_job_aborted(job_id)
            failure_count = completed - success_count
            direction_counts = _impulse_job_direction_counts(modem_results)
            elapsed_s = round(time.monotonic() - job_started_monotonic, 2)
            modem_results.sort(key=lambda item: item.get('mac_address', ''))
            result = {
                'success': success_count > 0,
                'job_id': job_id,
                'source': source,
                'direction': direction,
                'velocity_factor': velocity_factor,
                'retrieval_mode': 'fresh_agent_catalog' if source == 'existing' else 'fresh_capture',
                'topology_date': topology_date,
                'fiber_node': fiber_node,
                'aborted': aborted,
                'target_snapshot': target_snapshot,
                'total': total,
                'completed': completed,
                'success_count': success_count,
                'failure_count': failure_count,
                'elapsed_s': elapsed_s,
                'modems': modem_results,
                **direction_counts,
            }
            _store_impulse_job_result(job_id, result)
            terminal_state = 'aborted' if aborted else 'completed'
            terminal_action = (
                'Aborted'
                if aborted
                else f'Complete: {success_count} modems with analysis; {_impulse_failure_summary(direction_counts)}'
            )
            _set_impulse_job_progress(
                job_id,
                total=total, completed=completed,
                success_count=success_count, failure_count=failure_count,
                running_count=0, queued_count=max(0, total - completed),
                modem='', action=terminal_action, state=terminal_state,
                elapsed_s=elapsed_s,
                pct=round(completed * 100 / total, 1), done=True,
                **direction_counts,
            )
        except Exception as exc:
            logger.exception('Fiber-node impulse job %s failed', job_id)
            elapsed_s = round(time.monotonic() - job_started_monotonic, 2)
            direction_counts = _impulse_job_direction_counts(modem_results)
            _store_impulse_job_result(job_id, {
                'success': False,
                'job_id': job_id,
                'velocity_factor': velocity_factor,
                'error': str(exc),
                'total': total,
                'completed': completed,
                'success_count': success_count,
                'failure_count': completed - success_count,
                'elapsed_s': elapsed_s,
                **direction_counts,
            })
            _set_impulse_job_progress(
                job_id,
                total=total, completed=completed,
                success_count=success_count, failure_count=completed - success_count,
                running_count=0, queued_count=max(0, total - completed),
                action='Error', state='failed', elapsed_s=elapsed_s,
                pct=round(completed * 100 / total, 1), done=True,
                **direction_counts,
            )

    _threading.Thread(target=_run_job, daemon=True).start()
    return jsonify({
        'success': True,
        'started': True,
        'job_id': job_id,
        'source': source,
        'direction': direction,
        'velocity_factor': velocity_factor,
        'target_count': len(target_snapshot),
        'concurrency': concurrency,
        'timeout_budget_s': timeout_budget_s,
    })


@pypnm_bp.route('/impulse-response/fibernode/jobs/<job_id>', methods=['GET'])
def get_fibernode_impulse_job(job_id):
    with _impulse_job_lock:
        progress = dict(_impulse_job_progress.get(job_id, {}))
    if not progress and REDIS_AVAILABLE:
        try:
            progress = redis_client.hgetall(_impulse_progress_key(job_id)) or {}
        except Exception:
            progress = {}
    if not progress:
        return jsonify({'found': False}), 404

    def _as_bool(value):
        return value is True or str(value).lower() == 'true'

    return jsonify({
        'found': True,
        'job_id': job_id,
        'total': int(progress.get('total', 0)),
        'completed': int(progress.get('completed', 0)),
        'success_count': int(progress.get('success_count', 0)),
        'failure_count': int(progress.get('failure_count', 0)),
        'direction_attempt_count': int(progress.get('direction_attempt_count', 0)),
        'analyzed_direction_count': int(progress.get('analyzed_direction_count', 0)),
        'timeout_count': int(progress.get('timeout_count', 0)),
        'capture_failed_count': int(progress.get('capture_failed_count', 0)),
        'analysis_failed_count': int(progress.get('analysis_failed_count', 0)),
        'agent_unavailable_count': int(progress.get('agent_unavailable_count', 0)),
        'other_failure_count': int(progress.get('other_failure_count', 0)),
        'running_count': int(progress.get('running_count', 0)),
        'queued_count': int(progress.get('queued_count', 0)),
        'modem': progress.get('modem', ''),
        'action': progress.get('action', ''),
        'state': progress.get('state', 'running'),
        'velocity_factor': float(progress.get('velocity_factor', DEFAULT_VELOCITY_FACTOR)),
        'elapsed_s': float(progress.get('elapsed_s', 0)),
        'pct': float(progress.get('pct', 0)),
        'done': _as_bool(progress.get('done', False)),
    })


@pypnm_bp.route('/impulse-response/fibernode/jobs/<job_id>/results', methods=['GET'])
def get_fibernode_impulse_job_results(job_id):
    result = _get_impulse_job_result(job_id)
    if result is None:
        return jsonify({'found': False}), 404
    return jsonify({'found': True, **result})


@pypnm_bp.route('/impulse-response/fibernode/jobs/<job_id>', methods=['DELETE'])
def cancel_fibernode_impulse_job(job_id):
    with _impulse_job_lock:
        _impulse_job_abort.add(job_id)
    _set_impulse_job_progress(job_id, action='Cancellation requested', done=False)
    return jsonify({'success': True, 'job_id': job_id})