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

# Import spectrum plotter for generating matplotlib plots
from app.core.spectrum_plotter import generate_spectrum_plot_from_data

logger = logging.getLogger(__name__)

pypnm_bp = Blueprint('pypnm', __name__, url_prefix='/api/pypnm')


def get_default_community():
    """Get default SNMP community based on mode."""
    return 'z1gg0m0n1t0r1ng' if os.environ.get('PYPNM_MODE') == 'lab' else 'm0d3m1nf0'


def get_default_tftp():
    """Get default TFTP IP."""
    return os.environ.get('TFTP_IPV4', '172.16.6.101')


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
    community = data.get('community', get_default_community())
    tftp_ip = data.get('tftp_ip', get_default_tftp())
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
            
            result = client.get_upstream_spectrum_capture(
                cmts_ip=cmts_ip,
                rf_port_ifindex=rf_port_ifindex,
                tftp_ipv4=tftp_ip,
                community=community,
                tftp_ipv6=None,
                output_type=output_type,
                trigger_mode=trigger_mode,
                center_freq_hz=center_freq_hz,
                span_hz=span_hz,
                num_bins=num_bins,
                filename=filename,
                cm_mac=cm_mac,
                logical_ch_ifindex=logical_ch_ifindex
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
        
        # Handle archive (ZIP) response - fetch matplotlib plots from PyPNM
        if requested_archive and isinstance(result, bytes):
            # PyPNM returned binary ZIP file
            import zipfile
            import io
            import base64
            from datetime import datetime
            
            # Save ZIP file
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            zip_filename = f"{measurement_type}_{mac_address}_{timestamp}.zip"
            zip_path = f"/app/data/{zip_filename}"
            
            with open(zip_path, 'wb') as f:
                f.write(result)
            
            # Extract PNG images from ZIP
            plots = []
            try:
                with zipfile.ZipFile(io.BytesIO(result), 'r') as zf:
                    for filename in zf.namelist():
                        if filename.endswith('.png'):
                            img_data = zf.read(filename)
                            plots.append({
                                'filename': filename,
                                'data': base64.b64encode(img_data).decode('utf-8')
                            })
            except Exception as e:
                logger.error(f"Failed to extract plots from ZIP: {e}")
            
            return jsonify({
                "status": 0,
                "message": f"Measurement complete - {len(plots)} plots generated",
                "output_type": "archive",
                "zip_file": zip_filename,
                "download_url": f"/api/pypnm/download/{zip_filename}",
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
    if data.get('status') != 0:
        return []
    results = data.get('results', {})
    
    # Log the raw data for debugging
    logger.debug(f"ATDMA raw results: {results}")
    
    if isinstance(results, list):
        channels = []
        for ch in results:
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
            
            channels.append({
                'channel_id': ch.get('channel_id', entry.get('docsIf31CmUsOfdmaChanChannelId',
                              entry.get('channelId'))),
                'frequency': freq,
                'frequency_mhz': round(freq / 1000000, 1) if freq and freq > 1000 else freq,
                'bandwidth': round(bandwidth / 1000000, 1) if bandwidth else None,
                'bandwidth_mhz': round(bandwidth / 1000000, 1) if bandwidth else None,
                'num_subcarriers': num_subcarriers,
                'tx_power': tx_power,
                'profiles': profiles
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


# ============== Upstream PNM Routes ==============

@pypnm_bp.route('/upstream/interfaces/<mac_address>', methods=['POST'])
def get_upstream_interfaces(mac_address):
    """
    Get upstream interface information for a modem from CMTS.
    Returns OFDMA channels and SC-QAM channels available.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "community": "optional"
    }
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_get_interfaces') if agent_manager else None
        
        if not agent:
            # Fallback to any CMTS-capable agent
            agent = agent_manager.get_agent_for_capability('cmts_snmp_direct') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for upstream interface discovery"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_get_interfaces',
            params={
                "cmts_ip": cmts_ip,
                "cm_mac_address": mac_address,
                "community": community
            },
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=90)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            "cmts_ip": cmts_ip,
            "cm_index": task_result.get('cm_index'),
            "rf_ports": task_result.get('rf_ports', []),  # Modem's specific RF port(s)
            "all_rf_ports": task_result.get('all_rf_ports', []),  # All us-conn ports
            "modem_rf_port": task_result.get('modem_rf_port'),  # Modem's detected RF port
            "modem_ofdma_ifindex": task_result.get('modem_ofdma_ifindex')
        })
        
    except Exception as e:
        logger.error(f"Get upstream interfaces failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/configure/<mac_address>', methods=['POST'])
def configure_utsc(mac_address):
    """
    Configure and start UTSC (Upstream Triggered Spectrum Capture) test via PyPNM API.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "trigger_mode": 2,  // 2=FreeRunning, 6=CM_MAC
        "center_freq_hz": 30000000,
        "span_hz": 80000000,
        "num_bins": 800,
        "filename": "utsc_capture",
        "logical_ch_ifindex": null,  // For CM_MAC trigger
        "community": "optional",
        "tftp_ip": "optional"
    }
    """
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', 'Z1gg0Sp3c1@l')  # UTSC needs CMTS write community
    tftp_ip = data.get('tftp_ip', get_default_tftp())
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        client = PyPNMClient()
        
        trigger_mode = data.get('trigger_mode', 2)
        cm_mac = mac_address if trigger_mode == 6 else None
        
        result = client.get_upstream_spectrum_capture(
            cmts_ip=cmts_ip,
            rf_port_ifindex=rf_port_ifindex,
            tftp_ipv4=tftp_ip,
            community=community,
            output_type='json',
            trigger_mode=trigger_mode,
            center_freq_hz=data.get('center_freq_hz', 30000000),
            span_hz=data.get('span_hz', 80000000),
            num_bins=data.get('num_bins', 800),
            filename=data.get('filename', f'utsc_{mac_address.replace(":", "")}'),
            cm_mac=cm_mac,
            logical_ch_ifindex=data.get('logical_ch_ifindex')
        )
        logger.info(f"UTSC API full response: {result}")
        return jsonify({
            "success": result.get('success', False),
            "mac_address": mac_address,
            "cmts_ip": result.get('cmts_ip'),
            "rf_port_ifindex": result.get('rf_port_ifindex'),
            "filename": result.get('filename'),
            "error": result.get('error'),
            "data": result.get('data')
        })
        
    except Exception as e:
        logger.error(f"Configure UTSC failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/start/<mac_address>', methods=['POST'])
def start_utsc(mac_address):
    """
    Start UTSC test on CMTS - Legacy endpoint, redirects to configure.
    Use /upstream/utsc/configure instead for combined configure+start.
    """
    # Just call configure which now does both
    return configure_utsc(mac_address)


@pypnm_bp.route('/upstream/utsc/stop/<mac_address>', methods=['POST'])
def stop_utsc(mac_address):
    """Stop UTSC test on CMTS."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_utsc_stop') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for UTSC"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_utsc_stop',
            params={
                "cmts_ip": cmts_ip,
                "rf_port_ifindex": rf_port_ifindex,
                "community": community
            },
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Stop UTSC failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/status/<mac_address>', methods=['POST'])
def get_utsc_status(mac_address):
    """
    Get UTSC test status from CMTS.
    
    Returns:
    - meas_status: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip or not rf_port_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and rf_port_ifindex required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_utsc_status') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for UTSC"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_utsc_status',
            params={
                "cmts_ip": cmts_ip,
                "rf_port_ifindex": rf_port_ifindex,
                "community": community
            },
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Get UTSC status failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/rxmer/start/<mac_address>', methods=['POST'])
def start_us_rxmer(mac_address):
    """
    Start Upstream OFDMA RxMER measurement on CMTS.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "ofdma_ifindex": 12345,
        "pre_eq": true,
        "filename": "optional",
        "community": "optional"
    }
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_rxmer_start') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for US RxMER"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_start',
            params={
                "cmts_ip": cmts_ip,
                "ofdma_ifindex": ofdma_ifindex,
                "cm_mac_address": mac_address,
                "pre_eq": data.get('pre_eq', True),
                "filename": data.get('filename', f'usrxmer_{mac_address.replace(":", "")}'),
                "community": community
            },
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Start US RxMER failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/rxmer/status/<mac_address>', methods=['POST'])
def get_us_rxmer_status(mac_address):
    """Get Upstream RxMER measurement status."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_rxmer_status') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for US RxMER"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_status',
            params={
                "cmts_ip": cmts_ip,
                "ofdma_ifindex": ofdma_ifindex,
                "community": community
            },
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER status failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/data/<mac_address>', methods=['POST'])
def get_utsc_data(mac_address):
    """
    Fetch UTSC spectrum data from TFTP server.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "filename": "optional",
        "community": "optional"
    }
    
    Returns spectrum data with frequencies and amplitudes for graphing.
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    rf_port_ifindex = data.get('rf_port_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_utsc_data') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for UTSC data"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_utsc_data',
            params={
                "cmts_ip": cmts_ip,
                "rf_port_ifindex": rf_port_ifindex,
                "filename": data.get('filename'),
                "community": community
            },
            timeout=120  # File fetch may take longer
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=120)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Get UTSC data failed: {e}")
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
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    ofdma_ifindex = data.get('ofdma_ifindex')
    community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_rxmer_data') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for US RxMER data"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_data',
            params={
                "cmts_ip": cmts_ip,
                "ofdma_ifindex": ofdma_ifindex,
                "filename": data.get('filename'),
                "community": community
            },
            timeout=120
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=120)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER data failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
