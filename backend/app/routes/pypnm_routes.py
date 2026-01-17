# PyPNM Web GUI - PyPNM Routes
# SPDX-License-Identifier: Apache-2.0
#
# Complete PyPNM API integration with plot support

from flask import Blueprint, request, jsonify, send_file
from typing import Dict, Any
import logging
import os
import tempfile
import zipfile
from io import BytesIO

logger = logging.getLogger(__name__)

pypnm_bp = Blueprint('pypnm', __name__, url_prefix='/api/pypnm')


def get_default_community():
    """Get default SNMP community based on mode."""
    return 'z1gg0m0n1t0r1ng' if os.environ.get('PYPNM_MODE') == 'lab' else 'm0d3m1nf0'


def get_default_tftp():
    """Get default TFTP IP."""
    return os.environ.get('TFTP_IPV4', '172.22.147.18')


@pypnm_bp.route('/measurements/<measurement_type>/<mac_address>', methods=['POST'])
def pnm_measurement(measurement_type, mac_address):
    """
    Unified PNM measurement endpoint.
    
    Supported types:
    - rxmer: RxMER per subcarrier
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
    community = data.get('community', get_default_community())
    tftp_ip = data.get('tftp_ip', get_default_tftp())
    output_type = data.get('output_type', 'json')
    
    # PyPNM only supports json output currently - archive mode falls back to json
    if output_type == 'archive':
        output_type = 'json'
        requested_archive = True
    else:
        requested_archive = False
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    # Route to appropriate method
    try:
        if measurement_type == 'rxmer':
            result = client.get_rxmer_capture(
                mac_address, modem_ip, tftp_ip, community, 
                tftp_ipv6="::1", output_type=output_type
            )
        elif measurement_type == 'channel_estimation':
            result = client.get_channel_estimation(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
        elif measurement_type == 'modulation_profile':
            result = client.get_modulation_profile(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
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
            result = client.get_constellation_display(
                mac_address, modem_ip, tftp_ip, community,
                tftp_ipv6="::1", output_type=output_type
            )
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
        
        # Handle archive (ZIP) response
        if output_type == 'archive' and result.get('status') == 0:
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
            
            plots = []
            if result.get('status') == 0:
                # Give PyPNM a moment to finish writing files
                time.sleep(1)
                
                # Look for plots in /pypnm-data/png/
                plot_dir = "/pypnm-data/png"
                if os.path.exists(plot_dir):
                    # Find recent plots for this modem
                    mac_clean = mac_address.replace(':', '')
                    pattern = f"{plot_dir}/{mac_clean}*.png"
                    plot_files = glob.glob(pattern)
                    
                    # Get files modified in the last 60 seconds
                    recent_time = time.time() - 60
                    plot_files = [f for f in plot_files if os.path.getmtime(f) > recent_time]
                    plot_files.sort(key=os.path.getmtime, reverse=True)
                    
                    for filepath in plot_files[:10]:  # Max 10 plots
                        try:
                            with open(filepath, 'rb') as f:
                                img_data = f.read()
                                plots.append({
                                    'filename': os.path.basename(filepath),
                                    'data': base64.b64encode(img_data).decode('utf-8')
                                })
                        except Exception as e:
                            logger.error(f"Failed to read plot {filepath}: {e}")
            
            return jsonify({
                "status": 0,
                "message": result.get('message', 'Measurement complete'),
                "plots": plots,  # Matplotlib PNG plots
                "data": result.get('data', {})
            })
        
        # Handle errors
        if result.get('status') != 0:
            return jsonify(result), 500
            
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
    
    Returns DS/US channel info including:
    - Channel type (SC-QAM, OFDM, ATDMA, OFDMA)
    - Active profiles
    - Signal quality metrics
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', get_default_community())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    try:
        # Get all channel stats
        ds_scqam = client.get_ds_scqam_stats(mac_address, modem_ip, community)
        ds_ofdm = client.get_ds_ofdm_stats(mac_address, modem_ip, community)
        us_atdma = client.get_us_atdma_stats(mac_address, modem_ip, community)
        us_ofdma = client.get_us_ofdma_stats(mac_address, modem_ip, community)
        
        # Process and enhance data with profile info
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
        
    except Exception as e:
        logger.error(f"Channel stats failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def _extract_scqam_channels(data: Dict[str, Any]) -> list:
    """Extract SC-QAM channel info."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    if isinstance(results, list):
        # PyPNM may return list directly
        channels = []
        for ch in results:
            channels.append({
                'channel_id': ch.get('ifIndex', ch.get('channel_id')),
                'frequency': ch.get('frequency'),
                'modulation': ch.get('modulation'),
                'power': ch.get('power'),
                'snr': ch.get('rxMer', ch.get('snr'))
            })
        return channels
    # Handle dict format
    channels = []
    for ch in results.get('channels', []):
        channels.append({
            'channel_id': ch.get('ifIndex', ch.get('channel_id')),
            'frequency': ch.get('frequency'),
            'modulation': ch.get('modulation'),
            'power': ch.get('power'),
            'snr': ch.get('rxMer', ch.get('snr'))
        })
    return channels


def _extract_ofdm_channels(data: Dict[str, Any]) -> list:
    """Extract OFDM channel info with profile data."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    if isinstance(results, list):
        channels = []
        for ch in results:
            profiles = ch.get('profiles', [])
            channels.append({
                'channel_id': ch.get('channelId', ch.get('channel_id')),
                'frequency': ch.get('frequency'),
                'profiles': [p.get('profileId', p) for p in profiles if (p.get('profileId') if isinstance(p, dict) else p) != 255],
                'ncp_profile': 255 in [p.get('profileId', p) if isinstance(p, dict) else p for p in profiles],
                'active_profiles': len([p for p in profiles if (p.get('profileId') if isinstance(p, dict) else p) != 255])
            })
        return channels
    channels = []
    for ch in results.get('channels', []):
        profiles = ch.get('profiles', [])
        channels.append({
            'channel_id': ch.get('channelId', ch.get('channel_id')),
            'frequency': ch.get('frequency'),
            'profiles': [p.get('profileId', p) for p in profiles if (p.get('profileId') if isinstance(p, dict) else p) != 255],
            'ncp_profile': 255 in [p.get('profileId', p) if isinstance(p, dict) else p for p in profiles],
            'active_profiles': len([p for p in profiles if (p.get('profileId') if isinstance(p, dict) else p) != 255])
        })
    return channels


def _extract_atdma_channels(data: Dict[str, Any]) -> list:
    """Extract ATDMA channel info."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    if isinstance(results, list):
        channels = []
        for ch in results:
            channels.append({
                'channel_id': ch.get('ifIndex', ch.get('channel_id')),
                'frequency': ch.get('frequency'),
                'modulation': ch.get('channelType', ch.get('modulation')),
                'power': ch.get('txPower', ch.get('power'))
            })
        return channels
    channels = []
    for ch in results.get('channels', []):
        channels.append({
            'channel_id': ch.get('ifIndex', ch.get('channel_id')),
            'frequency': ch.get('frequency'),
            'modulation': ch.get('channelType', ch.get('modulation')),
            'power': ch.get('txPower', ch.get('power'))
        })
    return channels


def _extract_ofdma_channels(data: Dict[str, Any]) -> list:
    """Extract OFDMA channel info with profile data."""
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    if isinstance(results, list):
        channels = []
        for ch in results:
            channels.append({
                'channel_id': ch.get('channelId', ch.get('channel_id')),
                'frequency': ch.get('configuredCenterFrequency', ch.get('frequency')),
                'bandwidth': ch.get('channelWidth', ch.get('bandwidth')),
                'profiles': ch.get('activeProfiles', [])
            })
        return channels
    channels = []
    for ch in results.get('channels', []):
        channels.append({
            'channel_id': ch.get('channelId', ch.get('channel_id')),
            'frequency': ch.get('configuredCenterFrequency', ch.get('frequency')),
            'bandwidth': ch.get('channelWidth', ch.get('bandwidth')),
            'profiles': ch.get('activeProfiles', [])
        })
    return channels


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
        
        # PyPNM data directories
        data_dirs = [
            '/app/.data/pnm',
            '/app/.data/csv',
            '/app/.data/json',
            '/app/.data/png',
            '/app/.data/archive'
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
    
    # Sort by modification time (newest first) and limit to last 10
    plot_files.sort(key=os.path.getmtime, reverse=True)
    plot_files = plot_files[:10]
    
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
