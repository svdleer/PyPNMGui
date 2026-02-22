# PyPNM Web GUI - PyPNM Routes
#
# Complete PyPNM API integration with plot support

from flask import Blueprint, request, jsonify, send_file
from typing import Dict, Any
import logging
import os
import tempfile
import zipfile
from io import BytesIO
import json

# Import spectrum plotter for generating matplotlib plots
from app.core.spectrum_plotter import generate_spectrum_plot_from_data
from app.core.constellation_plotter import generate_constellation_plots_from_data

logger = logging.getLogger(__name__)

pypnm_bp = Blueprint('pypnm', __name__, url_prefix='/api/pypnm')

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


def get_default_community():
    """Get default SNMP community for modems based on mode."""
    return os.environ.get('MODEM_COMMUNITY', 'public')


def get_default_write_community():
    """Get default SNMP write community for modem PNM operations (SET)."""
    return os.environ.get('MODEM_WRITE_COMMUNITY', 'private')


def get_cmts_community():
    """Get default SNMP read community for CMTS operations."""
    return os.environ.get('CMTS_COMMUNITY', 'public')


def get_cmts_write_community():
    """Get default SNMP write community for CMTS operations."""
    return os.environ.get('CMTS_WRITE_COMMUNITY', 'private')


def get_default_tftp():
    """Get default TFTP IP (used for CMTS-side operations like UTSC/RxMER)."""
    return os.environ.get('TFTP_IPV4', '172.16.6.101')


def get_alternate_tftp():
    """Get alternate TFTP IP (used for CM modem-side PNM operations)."""
    return os.environ.get('TFTP_IPV4_ALT', '172.22.147.18')


def get_tftp_for_cmts(cmts_ip: str) -> str:
    """Return TFTP IP for CMTS-side bulk upload (UTSC/US RxMER).
    
    Cisco uses alternate TFTP; all others use default.
    """
    from app.core.cmts_provider import CMTSProvider
    try:
        cmts = CMTSProvider.get_cmts_by_ip(cmts_ip)
        if cmts and cmts.get('Vendor', '').lower() == 'cisco':
            return get_alternate_tftp()
    except Exception:
        pass
    return get_default_tftp()


def get_tftp_for_cm() -> str:
    """Return TFTP IP for CM modem-side PNM uploads.
    
    Modems upload to the alternate TFTP server which is reachable
    from the modem subnet (10.x / 172.22.x networks).
    Always returns TFTP_IPV4_ALT regardless of CMTS vendor.
    """
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
            
            # Stop any existing UTSC measurement before starting a new one
            try:
                logger.info(f"Stopping any existing UTSC on {cmts_ip} port {rf_port_ifindex}")
                import time as _time
                client.stop_utsc(cmts_ip, rf_port_ifindex, community)
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
                community=community,
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
                resolved_cfg_index = result.get('cfg_index', 1)
                start_result = client.start_utsc(
                    cmts_ip, rf_port_ifindex, community,
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
        
        # Fetch matplotlib plots for successful measurements (regardless of output_type)
        import glob
        import os
        import base64
        import time
        
        plots = []
        plot_dir = "/pypnm-data/png"
        if os.path.exists(plot_dir):
            mac_clean = mac_address.replace(':', '')
            pattern = f"{plot_dir}/{mac_clean}*.png"
            plot_files = glob.glob(pattern)
            
            # Get files modified in the last 120 seconds
            recent_time = time.time() - 120
            plot_files = [f for f in plot_files if os.path.getmtime(f) > recent_time]
            plot_files.sort(key=os.path.getmtime, reverse=True)
            
            for filepath in plot_files[:10]:
                try:
                    with open(filepath, 'rb') as f:
                        img_data = f.read()
                        plots.append({
                            'filename': os.path.basename(filepath),
                            'data': base64.b64encode(img_data).decode('utf-8')
                        })
                except Exception as e:
                    logger.error(f"Failed to read plot {filepath}: {e}")
        
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
                    logger.error(f"Failed to generate spectrum plot: {e}")
        
        # Add plots to result
        result['plots'] = plots
            
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
    community = data.get('community', get_default_community())
    cmts_ip = data.get('cmts_ip')
    cmts_community = data.get('cmts_community', get_cmts_community())
    # CM operations always use alternate TFTP
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    # Use optimized PyPNM API endpoint (parallel bulk walks via agent)
    client = PyPNMClient()
    payload = {
        'mac_address': mac_address,
        'modem_ip': modem_ip,
        'community': community,
        'cmts_stats': True  # Fetch CMTS-side OFDMA MeanRxMer and IUC stats
    }
    
    # Add CMTS info for fiber node lookup if available
    if cmts_ip:
        payload['cmts_ip'] = cmts_ip
        payload['cmts_community'] = cmts_community
    
    result = client._post('/cm/channel-stats', payload)
    
    if result.get('success'):
        # Return the result directly - already in correct format
        return jsonify({
            "mac_address": mac_address,
            "status": 0,
            "fiber_node": result.get('fiber_node'),
            "downstream": result.get('downstream', {}),
            "upstream": result.get('upstream', {}),
            "timing": result.get('timing', {})
        })
    else:
        return jsonify({
            "status": "error",
            "message": result.get('error', 'Failed to get channel stats')
        }), 500


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
            
            # Check for partial service / NCP mode
            is_partial = entry.get('docsIf31CmDsOfdmChanIsPartialSvc',
                         entry.get('isPartialService',
                         entry.get('partialService', False)))
            
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
                'is_partial': bool(is_partial),
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
            
            # Check for partial service
            is_partial = entry.get('docsIf31CmUsOfdmaChanIsPartialSvc',
                        entry.get('isPartialService',
                        entry.get('partialService', False)))
            
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
                'is_partial': bool(is_partial),
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
    """
    Clean up old PNM files.
    
    POST body:
    {
        "max_age_days": 7,
        "dry_run": false
    }
    """
    data = request.get_json() or {}
    max_age_days = data.get('max_age_days', 7)
    dry_run = data.get('dry_run', False)
    
    try:
        import os
        import time
        from pathlib import Path
        
        # PyPNM data directories - PNM files land in tftpboot
        data_dirs = [
            '/var/lib/tftpboot',
            '/app/data',
            '/app/logs',
        ]
        
        max_age_seconds = max_age_days * 24 * 60 * 60
        current_time = time.time()
        deleted_files = []
        total_size = 0
        
        for dir_path in data_dirs:
            if not os.path.exists(dir_path):
                continue
                
            for root, dirs, files in os.walk(dir_path):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    try:
                        file_age = current_time - os.path.getmtime(file_path)
                        file_size = os.path.getsize(file_path)
                        
                        if file_age > max_age_seconds:
                            if not dry_run:
                                os.remove(file_path)
                            deleted_files.append({
                                'path': file_path,
                                'age_days': round(file_age / 86400, 1),
                                'size_mb': round(file_size / 1024 / 1024, 2)
                            })
                            total_size += file_size
                    except Exception as e:
                        logger.warning(f"Could not process file {file_path}: {e}")
        
        return jsonify({
            "status": "success",
            "dry_run": dry_run,
            "deleted_count": len(deleted_files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "files": deleted_files[:50]  # Return first 50
        })
        
    except Exception as e:
        logger.error(f"Housekeeping failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


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
    
    Discovers:
    1. All UTSC RF ports on the CMTS (for UTSC port selector)
    2. Modem's OFDMA channel (for US RxMER)
    
    Uses PyPNM API:
    - POST /pnm/us/utsc/ports → all RF ports
    - POST /pnm/us/ofdma/rxmer/discover → modem OFDMA channel
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "community": "optional"
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        client = PyPNMClient()
        
        # 1. Get all UTSC RF ports on CMTS
        rf_result = client.discover_rf_ports(
            cmts_ip=cmts_ip,
            community=community,
            cm_mac_address=mac_address
        )
        
        # Map RF ports to frontend format (frontend expects .ifindex)
        rf_ports = []
        if rf_result and rf_result.get('success'):
            for port in rf_result.get('rf_ports', []):
                rf_ports.append({
                    "ifindex": port.get('rf_port_ifindex'),
                    "rf_port_ifindex": port.get('rf_port_ifindex'),
                    "description": port.get('description', ''),
                    "cfg_index": port.get('cfg_index', 1)
                })
        else:
            logger.warning(f"RF port discovery failed: {rf_result.get('error') if rf_result else 'No response'}")
        
        # 2. Discover modem's specific RF port (for UTSC auto-select)
        modem_rf_port = None
        cm_index = None
        try:
            rf_modem_result = client.discover_modem_rf_port(
                cmts_ip=cmts_ip,
                cm_mac_address=mac_address,
                community=community
            )
            if rf_modem_result and rf_modem_result.get('success'):
                cm_index = rf_modem_result.get('cm_index')
                modem_rf_ifindex = rf_modem_result.get('rf_port_ifindex')
                rf_port_description = rf_modem_result.get('rf_port_description', '')
                
                # Casa CCAP mapping: OFDMA logical (16M) → physical port (4M)
                # If ifIndex is in 16M range and description contains "OFDMA", map to physical
                if modem_rf_ifindex and 16000000 <= modem_rf_ifindex < 17000000:
                    if 'OFDMA' in rf_port_description:
                        physical_ifindex = modem_rf_ifindex - 12000000  # Map to physical port
                        logger.info(f"Casa OFDMA port {modem_rf_ifindex} mapped to physical {physical_ifindex}")
                        modem_rf_ifindex = physical_ifindex
                        # Update description to match physical port
                        rf_port_description = rf_port_description.replace('OFDMA Upstream', 'Upstream Physical Interface')
                
                if modem_rf_ifindex:
                    modem_rf_port = {
                        "ifindex": modem_rf_ifindex,
                        "rf_port_ifindex": modem_rf_ifindex,
                        "description": rf_port_description,
                        "cfg_index": 1,
                        "is_modem_port": True
                    }
                    logger.info(f"Found modem RF port {modem_rf_ifindex} for {mac_address}")
        except Exception as e:
            logger.warning(f"Modem RF port discovery error (non-fatal): {e}")
        
        # Put modem's RF port first in the list
        scqam_channels = rf_ports
        if modem_rf_port:
            # Remove duplicate if present, then insert at front
            scqam_channels = [p for p in rf_ports if p.get('ifindex') != modem_rf_port.get('ifindex')]
            scqam_channels.insert(0, modem_rf_port)
        
        # 3. Discover modem's OFDMA channel for US RxMER
        ofdma_channels = []
        try:
            ofdma_result = client.discover_modem_ofdma(
                cmts_ip=cmts_ip,
                cm_mac_address=mac_address,
                community=community
            )
            if ofdma_result and ofdma_result.get('success'):
                if not cm_index:
                    cm_index = ofdma_result.get('cm_index')
                ofdma_ifindex = ofdma_result.get('ofdma_ifindex')
                if ofdma_ifindex:
                    ofdma_channels.append({
                        "ifindex": ofdma_ifindex,
                        "ofdma_ifindex": ofdma_ifindex,
                        "description": ofdma_result.get('ofdma_description', f'OFDMA {ofdma_ifindex}'),
                        "cm_index": cm_index
                    })
                    logger.info(f"Found OFDMA channel {ofdma_ifindex} for modem {mac_address}")
            else:
                logger.info(f"No OFDMA channel for modem {mac_address}: {ofdma_result.get('error') if ofdma_result else 'No response'}")
        except Exception as e:
            logger.warning(f"OFDMA discovery error (non-fatal): {e}")
        
        return jsonify({
            "success": True,
            "mac_address": mac_address,
            "cmts_ip": cmts_ip,
            "rf_ports": rf_ports,
            "ofdma_channels": ofdma_channels,
            "scqam_channels": scqam_channels,
            "cm_index": cm_index
        })
        
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
            tftp_server=data.get('tftp_server', get_tftp_for_cmts(cmts_ip))
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
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"success": False, "error": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        result = get_us_rxmer_status_sync(cmts_ip, ofdma_ifindex, community)
        
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
    Fetch US OFDMA RxMER capture as base64 PNG from PyPNM API.
    Returns: {"success": true, "image_data": "<base64 png>"}
    """
    from app.core.cmts_pnm import get_pypnm_api_url, PYPNM_AVAILABLE
    import base64
    
    if not PYPNM_AVAILABLE:
        return jsonify({"success": False, "error": "PyPNM not available"}), 503
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', get_cmts_community())
    
    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400
    
    try:
        import requests as req
        base_url = get_pypnm_api_url()
        url = f"{base_url}/pnm/us/ofdma/rxmer/getCapture"
        
        payload = {
            "cmts": {
                "cmts_ip": cmts_ip,
                "community": community
            },
            "ofdma_ifindex": data.get('ofdma_ifindex'),
            "filename": data.get('filename', f'usrxmer_{mac_address.replace(":", "")}'),
            "tftp_path": "/var/lib/tftpboot"
        }
        
        response = req.post(url, json=payload, timeout=60)
        
        if response.status_code == 200 and 'image/png' in response.headers.get('Content-Type', ''):
            image_b64 = base64.b64encode(response.content).decode('utf-8')
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "image_data": image_b64
            })
        else:
            # Try JSON error response
            try:
                err = response.json()
                return jsonify({"success": False, "error": err.get('error', f'API error {response.status_code}')}), 500
            except Exception:
                return jsonify({"success": False, "error": f"API error {response.status_code}"}), 500
        
    except Exception as e:
        logger.error(f"Get US RxMER data failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/config', methods=['GET'])
def get_config():
    """Return frontend configuration from environment variables."""
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
    
    logger.info(f"=== UTSC CONFIGURE === MAC: {mac_address}")
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', get_cmts_community())
    write_community = data.get('write_community', get_cmts_write_community())
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        trigger_mode = data.get('trigger_mode', 2)
        cm_mac = mac_address if trigger_mode == 6 else None
        
        # Convert repeat_period_ms to microseconds for the API
        # Casa minimum: 400ms satisfies both 100ms floor and 120s/300files constraints
        repeat_period_ms = data.get('repeat_period_ms', 400)
        repeat_period_us = repeat_period_ms * 1000

        output_format = data.get('output_format') or None  # None = auto-detect per vendor

        result = client.configure_utsc(
            cmts_ip=cmts_ip,
            rf_port_ifindex=rf_port_ifindex,
            community=community,
            write_community=write_community,
            trigger_mode=trigger_mode,
            center_freq_hz=data.get('center_freq_hz', 30000000),
            span_hz=data.get('span_hz', 60000000),
            num_bins=data.get('num_bins', 800),
            output_format=output_format,
            window_function=data.get('window_function', 2),
            repeat_period_us=repeat_period_us,
            freerun_duration_ms=data.get('freerun_duration_ms', 0),  # 0 = auto (service clamps to 120s min)
            trigger_count=data.get('trigger_count', 10),
            filename=data.get('filename', f'utsc_{mac_address.replace(":", "")}'),
            cm_mac_address=cm_mac,
            logical_ch_ifindex=data.get('logical_ch_ifindex')
        )
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
    freerun_duration_ms = data.get('freerun_duration_ms', 60000)  # Default 1 minute (can be overridden by GUI)
    repeat_period_ms = data.get('repeat_period_ms', 50)  # 50ms (E6000 minimum)
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        cfg_index = data.get('cfg_index', 1)

        # Just start — configure was already done by the caller
        result = client.start_utsc(cmts_ip, rf_port_ifindex, community, write_community, cfg_index=cfg_index)
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
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client.stop_utsc(cmts_ip, rf_port_ifindex, community, write_community)
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
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        result = client._post("/pnm/us/rxmer/start", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "cm_mac_address": mac_address,
            "pre_eq": data.get('pre_eq', True),
            "filename": data.get('filename', f'usrxmer_{mac_address.replace(":", "")}'),
            "community": community
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
    """
    Fetch UTSC spectrum data from TFTP server (local filesystem access).
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "filename": "optional",
        "community": "optional"
    }
    
    Returns spectrum data with frequencies and amplitudes for graphing.
    """
    import glob
    import os
    import struct
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    filename_base = data.get('filename', f'utsc_{mac_address.replace(":", "")}')
    # CMTS may prepend a path prefix (e.g. /pnm/utsc/) to the filename internally.
    # Strip to basename so we search correctly in /var/lib/tftpboot.
    filename_base = os.path.basename(filename_base.strip('/'))

    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400

    try:
        from app.core.pypnm_client import PyPNMClient
        client = PyPNMClient()

        # TFTP files are mounted at /var/lib/tftpboot (root, not subdirectories)
        tftp_base = '/var/lib/tftpboot'

        # Find the most recent UTSC file matching vendor-specific patterns:
        # 1. CommScope/Arris E6000: CMTS may prefix path e.g. /pnm/utsc/ to filename
        #    Files land at /var/lib/tftpboot/<cmts_path>/<filename_base>_<timestamp>
        # 2. Casa CCAP: same, root only
        # 3. Cisco cBR-8: PNMCcapUsSpecAn_{hostname}_{timestamp}_{rfport}

        # Query actual CMTS filename so we search the right path even if our SET failed
        rf_port_ifindex = data.get('rf_port_ifindex')
        cfg_index = data.get('cfg_index', 1)
        actual_filename_base = filename_base  # default to what GUI sent
        if cmts_ip and rf_port_ifindex:
            try:
                cmts_cfg = client.get_utsc_config(
                    cmts_ip=cmts_ip,
                    rf_port_ifindex=int(rf_port_ifindex),
                    community=data.get('community', get_cmts_community()),
                    cfg_index=int(cfg_index)
                )
                cmts_fn = cmts_cfg.get('filename', '')
                if cmts_fn:
                    actual_filename_base = os.path.basename(cmts_fn.strip('/'))
                    logger.info(f"CMTS-reported filename: '{cmts_fn}' → searching for basename '{actual_filename_base}'")
                    # Build search path from CMTS-reported path prefix
                    cmts_prefix = os.path.dirname(cmts_fn.strip('/'))
                    if cmts_prefix:
                        tftp_base = os.path.join('/var/lib/tftpboot', cmts_prefix)
                        logger.info(f"Adjusted TFTP search dir to: {tftp_base}")
            except Exception as e:
                logger.warning(f"Could not query CMTS config for filename: {e}")

        # Try exact basename match with timestamp suffix
        pattern = f"{tftp_base}/{actual_filename_base}_*"
        files = sorted(glob.glob(pattern), reverse=True)

        # Also try root in case CMTS path prefix wasn't reflected in actual write location
        if not files and tftp_base != '/var/lib/tftpboot':
            root_pattern = f"/var/lib/tftpboot/{actual_filename_base}_*"
            files = sorted(glob.glob(root_pattern), reverse=True)
            if files:
                logger.info(f"Found files in tftpboot root despite CMTS path prefix")

        # If still no files, try Cisco cBR-8 format
        if not files:
            if rf_port_ifindex:
                cisco_pattern = f"/var/lib/tftpboot/PNMCcapUsSpecAn_*_{rf_port_ifindex}"
                files = sorted(glob.glob(cisco_pattern), reverse=True)
                logger.info(f"Trying Cisco cBR-8 pattern: {cisco_pattern}, found {len(files)} files")
        
        if not files:
            # No files yet - return empty result (not an error)
            logger.info(f"No UTSC files found for {filename_base}")
            return jsonify({
                "success": True,
                "message": "No UTSC data available yet. Start a measurement to begin.",
                "data": None
            }), 200
        
        # Get the most recent file
        latest_file = files[0]
        logger.info(f"Reading UTSC file: {latest_file}")
        
        # Read the binary file
        with open(latest_file, 'rb') as f:
            binary_data = f.read()
        
        if len(binary_data) < 328:
            return jsonify({
                "success": False,
                "message": "File too small - invalid UTSC data"
            }), 400
        
        # Retrieve UTSC config from Redis FIRST to get correct span
        utsc_config = {}
        try:
            config_json = redis_client.get(f'utsc_config:{mac_address}')
            if config_json:
                utsc_config = json.loads(config_json)
                logger.info(f"Retrieved UTSC config: {utsc_config}")
        except Exception as e:
            logger.warning(f"Failed to retrieve UTSC config: {e}")
        
        # Basic parsing: skip 328-byte header, extract amplitude data
        # Vendor-specific parsing: CommScope uses little-endian signed int16, Cisco uses big-endian
        header = binary_data[:328]
        samples = binary_data[328:]
        
        # Try to detect vendor from filename
        is_cisco = 'PNMCcap' in os.path.basename(latest_file)
        
        # Convert binary samples to amplitude values
        amplitudes = []
        for i in range(0, len(samples), 2):
            if i+1 < len(samples):
                if is_cisco:
                    # Cisco cBR-8: big-endian signed int16, centidB (test with /100)
                    val = struct.unpack('>h', samples[i:i+2])[0]
                    amplitudes.append(val / 100.0)  # Test: centidB like CommScope
                else:
                    # CommScope E6000: little-endian signed int16, centidB
                    val = struct.unpack('<h', samples[i:i+2])[0]
                    amplitudes.append(val / 100.0)  # Scale to dB
        
        # Generate frequencies using configured span (defaults: 5-85 MHz = 80 MHz span, center 45 MHz)
        num_bins = len(amplitudes)
        span_hz = utsc_config.get('span_hz', 80000000)  # 80 MHz default
        center_freq_hz = utsc_config.get('center_freq_hz', 45000000)  # 45 MHz default
        freq_start = center_freq_hz - (span_hz / 2)
        freq_end = center_freq_hz + (span_hz / 2)
        freq_step = span_hz / num_bins if num_bins > 0 else 1
        frequencies = [freq_start + i * freq_step for i in range(num_bins)]
        
        logger.info(f"UTSC freq range: {freq_start/1e6:.1f} - {freq_end/1e6:.1f} MHz, {num_bins} bins")
        
        spectrum_data = {
            'filename': os.path.basename(latest_file),
            'num_samples': len(amplitudes),
            'frequencies': frequencies[:800],  # Limit to first 800 points
            'amplitudes': amplitudes[:800],
            'span_hz': span_hz,
            'center_freq_hz': center_freq_hz,
            'num_bins': num_bins
        }
        
        response = {
            "success": True,
            "mac_address": mac_address,
            "data": spectrum_data,
        }
        
        # Only generate matplotlib plot if explicitly requested (skip for live polling)
        if data.get('include_plot', False):
            from app.core.utsc_plotter import generate_utsc_plot_from_data
            rf_port_desc = data.get('rf_port_description', '')
            plot = generate_utsc_plot_from_data(spectrum_data, mac_address, rf_port_desc)
            response['plot'] = plot
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Get UTSC data failed: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


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
    import requests
    from flask import Response as FlaskResponse
    from app.core.cmts_pnm import get_pypnm_api_url
    
    data = request.get_json() or {}
    full_filename = data.get('filename')  # Full filename with timestamp from status response
    
    logger.info(f"US RxMER plot request for {mac_address}, filename: {full_filename}")
    
    if not full_filename:
        logger.error("No filename provided in request")
        return jsonify({"status": "error", "message": "filename required"}), 400
    
    try:
        pypnm_url = get_pypnm_api_url()
        api_url = f"{pypnm_url}/pnm/us/ofdma/rxmer/getCapture"
        
        logger.info(f"Fetching US RxMER plot from {api_url} for file {full_filename}")
        
        response = requests.post(
            api_url,
            json={
                "filename": full_filename,  # Full filename with timestamp from status
                "tftp_path": "/var/lib/tftpboot"
            },
            timeout=30
        )
        
        if response.status_code == 200 and response.headers.get('Content-Type', '').startswith('image/'):
            # Return the PNG image directly
            logger.info(f"Successfully fetched US RxMER plot for {mac_address}, size: {len(response.content)} bytes")
            return FlaskResponse(
                response.content,
                mimetype='image/png',
                headers={
                    'Content-Disposition': f'inline; filename=us_rxmer_{mac_address.replace(":", "")}.png'
                }
            )
        else:
            # Parse JSON error response
            logger.warning(f"PyPNM API returned non-image response: {response.status_code}, content-type: {response.headers.get('Content-Type')}")
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown error')
                logger.error(f"PyPNM error: {error_msg}")
            except Exception:
                error_msg = response.text or f"HTTP {response.status_code}"
                logger.error(f"PyPNM error (raw): {error_msg}")
            
            return jsonify({"status": "error", "message": error_msg}), response.status_code
            
    except requests.Timeout:
        logger.error("PyPNM API timeout fetching US RxMER plot")
        return jsonify({"status": "error", "message": "PyPNM API timeout"}), 504
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
