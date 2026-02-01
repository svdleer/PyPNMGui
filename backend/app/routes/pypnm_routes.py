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
    return os.environ.get('TFTP_IPV4', '172.22.147.18')


@pypnm_bp.route('/measurements/<measurement_type>/<mac_address>', methods=['POST'])
def pnm_measurement(measurement_type, mac_address):
    """
    Unified PNM measurement endpoint.
    
    For RxMER: Agent triggers SNMP capture, then calls PyPNM API to get parsed data.
    For others: Routes through agent.
    
    Supported types:
    - rxmer: RxMER per subcarrier (agent triggers, PyPNM parses)
    - spectrum: Spectrum analyzer
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
    import requests
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', get_default_community())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    # Special handling for RxMER - use PyPNM API
    if measurement_type == 'rxmer':
        return _handle_rxmer_measurement(mac_address, modem_ip, community)
    
    # Map measurement types to agent commands
    agent_command_map = {
        'spectrum': 'pnm_spectrum',
        'channel_estimation': 'pnm_ofdm_capture',
        'modulation_profile': 'pnm_ofdm_capture',
        'fec_summary': 'pnm_fec',
        'histogram': 'pnm_spectrum',
        'constellation': 'pnm_ofdm_capture',
        'us_pre_eq': 'pnm_pre_eq',
    }
    
    agent_command = agent_command_map.get(measurement_type)
    if not agent_command:
        return jsonify({
            "status": "error",
            "message": f"Unknown measurement type: {measurement_type}"
        }), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability(agent_command) if agent_manager else None
        
        if not agent:
            # Fallback: try any agent with cm_direct capability
            agent = agent_manager.get_agent_for_capability('cm_direct') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": f"No agent available for {measurement_type}"}), 503
        
        # Build params for agent
        params = {
            "modem_ip": modem_ip,
            "mac_address": mac_address,
            "community": community,
            "measurement_type": measurement_type
        }
        
        # Add measurement-specific params
        if measurement_type == 'fec_summary':
            params['fec_type'] = data.get('fec_summary_type', 2)
        elif measurement_type == 'histogram':
            params['sample_duration'] = data.get('sample_duration', 60)
        
        logger.info(f"Sending {agent_command} to agent {agent.agent_id} for {mac_address}")
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command=agent_command,
            params=params,
            timeout=120
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=120)
        
        if result is None:
            return jsonify({"status": "error", "message": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"status": "error", "message": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        # Return 'data' field for frontend compatibility
        return jsonify({
            "status": 0 if task_result.get('success', False) else 1,
            "message": task_result.get('message', 'Measurement complete'),
            "data": task_result.get('data', task_result),
            "mac_address": mac_address
        })
        
    except Exception as e:
        logger.error(f"PNM measurement {measurement_type} failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _handle_rxmer_measurement(mac_address: str, modem_ip: str, community: str):
    """
    Handle RxMER measurement.
    
    Flow:
    1. Agent triggers SNMP capture (modem uploads file to TFTP)
    2. Upload file to PyPNM and get transaction_id
    3. Call PyPNM getAnalysis to parse and get data + plot
    """
    import time
    import requests
    from app.core.simple_ws import get_simple_agent_manager
    
    pypnm_url = os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://localhost:8000'))
    tftp_dir = '/var/lib/tftpboot'  # PyPNM container has this mounted
    
    try:
        # Step 1: Have agent trigger SNMP capture
        logger.info(f"Triggering RxMER capture via agent for {mac_address} ({modem_ip})")
        
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_ofdm_rxmer') if agent_manager else None
        
        if not agent:
            agent = agent_manager.get_agent_for_capability('cm_direct') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for RxMER capture"}), 503
        
        # Trigger capture via agent
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_ofdm_rxmer',
            params={
                "modem_ip": modem_ip,
                "mac_address": mac_address,
                "community": community
            },
            timeout=60
        )
        
        trigger_result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if not trigger_result or not trigger_result.get('result', {}).get('success'):
            error = trigger_result.get('result', {}).get('error', 'Agent trigger failed') if trigger_result else 'Timeout'
            logger.error(f"Agent RxMER trigger failed: {error}")
            return jsonify({"status": "error", "message": f"Capture trigger failed: {error}"}), 500
        
        logger.info(f"Agent triggered RxMER capture, waiting for file upload...")
        agent_result = trigger_result.get('result', {})
        channels = agent_result.get('channels', [])
        
        # Step 2: Wait for modem to upload file to TFTP
        time.sleep(5)
        
        # Step 3: Upload each file to PyPNM and get analysis
        all_channel_data = []
        
        for channel in channels:
            filename = channel.get('filename')
            if not filename:
                continue
            
            filepath = f"{tftp_dir}/{filename}"
            logger.info(f"Processing RxMER file: {filename}")
            
            try:
                # Upload file to PyPNM (reads from container's mounted TFTP dir)
                # Note: GUI container can call PyPNM API, PyPNM reads file from its own mount
                upload_response = requests.post(
                    f"{pypnm_url}/docs/pnm/files/upload",
                    files={'file': (filename, open(filepath, 'rb'), 'application/octet-stream')},
                    timeout=30
                )
                
                if upload_response.status_code not in [200, 201]:
                    logger.warning(f"File upload failed: {upload_response.status_code}")
                    continue
                
                upload_result = upload_response.json()
                tx_id = upload_result.get('transaction_id')
                
                if not tx_id:
                    logger.warning(f"No transaction_id in upload response")
                    continue
                
                logger.info(f"File uploaded, transaction_id: {tx_id}")
                
                # Get analysis
                analysis_response = requests.post(
                    f"{pypnm_url}/docs/pnm/files/getAnalysis",
                    json={
                        "search": {"transaction_id": tx_id},
                        "analysis": {
                            "type": "basic",
                            "output": {"type": "json"},
                            "plot": {"ui": {"theme": "light"}}
                        }
                    },
                    timeout=60
                )
                
                if analysis_response.status_code == 200:
                    result = analysis_response.json()
                    channel_data = _transform_pypnm_rxmer_response(result, mac_address)
                    channel_data['channel_index'] = channel.get('channel_index')
                    channel_data['if_index'] = channel.get('if_index')
                    all_channel_data.append(channel_data)
                    logger.info(f"Analysis complete for channel {channel.get('channel_index')}")
                else:
                    logger.warning(f"Analysis failed: {analysis_response.status_code}")
                    
            except FileNotFoundError:
                logger.warning(f"File not found: {filepath} - modem may not have uploaded yet")
            except Exception as e:
                logger.warning(f"Failed to process file {filename}: {e}")
        
        if all_channel_data:
            # Merge all channel data into unified response
            return jsonify({
                "status": 0,
                "message": "RxMER capture complete",
                "data": {
                    "channels": all_channel_data,
                    "mac_address": mac_address,
                    "modem_ip": modem_ip
                },
                "mac_address": mac_address
            })
        
        # Fallback: Return trigger result with file info
        return jsonify({
            "status": 0,
            "message": "RxMER capture triggered - file pending upload",
            "data": agent_result,
            "mac_address": mac_address
        })
            
    except Exception as e:
        logger.error(f"RxMER measurement failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _transform_pypnm_rxmer_response(pypnm_response: dict, mac_address: str) -> dict:
    """Transform PyPNM RxMER file analysis response to frontend expected format.
    
    PyPNM returns:
    {
        "mac_address": "...",
        "pnm_file_type": "RECEIVE_MODULATION_ERROR_RATIO",
        "status": "success",
        "analysis": {
            "channel_id": 34,
            "subcarrier_spacing": 50000,
            "subcarrier_zero_frequency": 1019600000,
            "first_active_subcarrier_index": 148,
            "carrier_values": {
                "magnitude": [42.5, 43.0, ...],  # Per-subcarrier MER in dB
                "frequency": [...]
            },
            "modulation_statistics": {...}
        }
    }
    """
    # Get analysis data from PyPNM response
    analysis = pypnm_response.get('analysis', pypnm_response)
    
    rxmer_measurements = []
    
    # Extract carrier values (per-subcarrier MER)
    carrier_values = analysis.get('carrier_values', {})
    magnitudes = carrier_values.get('magnitude', [])
    frequencies = carrier_values.get('frequency', [])
    
    if magnitudes:
        first_idx = analysis.get('first_active_subcarrier_index', 0)
        zero_freq = analysis.get('subcarrier_zero_frequency', 0)
        spacing = analysis.get('subcarrier_spacing', 50000)
        channel_id = analysis.get('channel_id', 1)
        
        # Build subcarrier samples for graphing
        subcarrier_samples = []
        for i, mer in enumerate(magnitudes):
            freq = frequencies[i] if i < len(frequencies) else (zero_freq + (first_idx + i) * spacing)
            subcarrier_samples.append({
                'subcarrier_index': first_idx + i,
                'frequency_hz': freq,
                'mer_db': mer
            })
        
        # Calculate statistics
        avg_mer = sum(magnitudes) / len(magnitudes) if magnitudes else 0
        min_mer = min(magnitudes) if magnitudes else 0
        max_mer = max(magnitudes) if magnitudes else 0
        
        rxmer_measurements.append({
            'channel_id': channel_id,
            'subcarrier_zero_freq': zero_freq,
            'subcarrier_spacing_khz': spacing // 1000,
            'subcarrier_count': len(magnitudes),
            'first_active_subcarrier': first_idx,
            'average_mer_db': round(avg_mer, 2),
            'min_mer_db': round(min_mer, 2),
            'max_mer_db': round(max_mer, 2),
            'subcarrier_samples': subcarrier_samples
        })
    
    return {
        'mac_address': mac_address,
        'rxmer_measurements': rxmer_measurements,
        'signal_statistics': analysis.get('regression', {}),
        'modulation_statistics': analysis.get('modulation_statistics', {})
    }


@pypnm_bp.route('/channel-stats/<mac_address>', methods=['POST'])
def channel_stats(mac_address):
    """
    Get comprehensive channel statistics via agent.
    
    Returns DS/US channel info including:
    - Channel type (SC-QAM, OFDM, ATDMA, OFDMA)
    - Signal quality metrics
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', get_default_community())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_channel_info') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for channel stats"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_channel_info',
            params={
                "modem_ip": modem_ip,
                "mac_address": mac_address,
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
        
        if not task_result.get('success'):
            return jsonify({"status": "error", "message": task_result.get('error', 'Query failed')}), 500
        
        # Transform agent result to expected format
        ds_channels = task_result.get('downstream', [])
        us_channels = task_result.get('upstream', [])
        
        downstream = {
            "scqam": {
                "type": "SC-QAM (DOCSIS 3.0)",
                "channels": [c for c in ds_channels if c.get('type') == 'SC-QAM'],
                "count": len([c for c in ds_channels if c.get('type') == 'SC-QAM'])
            },
            "ofdm": {
                "type": "OFDM (DOCSIS 3.1)",
                "channels": [c for c in ds_channels if c.get('type') == 'OFDM'],
                "count": len([c for c in ds_channels if c.get('type') == 'OFDM'])
            }
        }
        
        upstream = {
            "atdma": {
                "type": "ATDMA (DOCSIS 3.0)",
                "channels": [c for c in us_channels if c.get('type') == 'ATDMA'],
                "count": len([c for c in us_channels if c.get('type') == 'ATDMA'])
            },
            "ofdma": {
                "type": "OFDMA (DOCSIS 3.1)",
                "channels": [c for c in us_channels if c.get('type') == 'OFDMA'],
                "count": len([c for c in us_channels if c.get('type') == 'OFDMA'])
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
    status = data.get('status')
    if status != 0:
        # Log the status for debugging OFDMA channel loading issues
        message = data.get('message', 'Unknown error')
        if status == 121:  # NO_OFDMA_CHANNELS_EXIST
            logger.debug(f"OFDMA: No OFDMA channels exist on this modem (status=121)")
        elif status == "error":
            logger.warning(f"OFDMA: PyPNM returned error: {message}")
        else:
            logger.warning(f"OFDMA: PyPNM returned non-zero status {status}: {message}")
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

@pypnm_bp.route('/upstream/discover-rf-port/<mac_address>', methods=['POST'])
def discover_rf_port(mac_address):
    """
    Fast discovery of the correct UTSC RF port for a modem.
    For E6000, UTSC can be configured on logical OFDMA channels directly.
    Returns ALL OFDMA channel ifindexes to use for UTSC.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "community": "optional"
    }
    
    Returns:
    {
        "success": true,
        "ofdma_channels": [
            {"ifindex": 843087883, "description": "cable-us-ofdma 1/ofd/4.0"}
        ],
        "rf_port_ifindex": 843087883,  // First OFDMA channel (for backward compat)
        "us_channels": [843087883]
    }
    """
    import requests
    
    data = request.get_json() or {}
    cmts_ip = data.get('cmts_ip')
    # CMTS queries need CMTS community string (Z1gg0@LL for read), not modem community
    cmts_community = data.get('community', 'Z1gg0@LL')
    
    if not cmts_ip:
        return jsonify({"success": False, "error": "cmts_ip required"}), 400
    
    logger.info(f"RF port discovery for {mac_address} on CMTS {cmts_ip} - using OFDMA channels")
    
    try:
        # Use the interfaces endpoint which returns ALL OFDMA channels
        interfaces_url = f"http://localhost:5050/api/pypnm/upstream/interfaces/{mac_address}"
        
        response = requests.post(interfaces_url, json={
            "cmts_ip": cmts_ip,
            "community": cmts_community
        }, timeout=90)
        
        if response.status_code == 200:
            result = response.json()
            ofdma_channels = result.get('ofdma_channels', [])
            
            if result.get('success') and ofdma_channels:
                # Return all OFDMA channels
                us_channels = [ch['ifindex'] for ch in ofdma_channels]
                return jsonify({
                    "success": True,
                    "ofdma_channels": ofdma_channels,
                    "rf_port_ifindex": ofdma_channels[0]['ifindex'],  # First for backward compat
                    "rf_port_description": ofdma_channels[0].get('description', 'OFDMA Channel'),
                    "logical_channel": ofdma_channels[0]['ifindex'],
                    "cm_index": result.get('cm_index'),
                    "us_channels": us_channels
                })
            else:
                return jsonify({"success": False, "error": "No OFDMA channels found"}), 404
        else:
            return jsonify({"success": False, "error": f"Interfaces API returned {response.status_code}"}), 500
            
    except Exception as e:
        logger.error(f"RF port discovery failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/interfaces/<mac_address>', methods=['POST'])
def get_upstream_interfaces(mac_address):
    """
    Get upstream interface information for a modem from CMTS via agent.
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
            return jsonify({"success": False, "error": "No agent available for OFDMA discovery"}), 503
        
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
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"success": False, "error": "Task timed out"}), 504
        
        if result.get('error'):
            return jsonify({"success": False, "error": result.get('error')}), 500
        
        task_result = result.get('result', {})
        
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            "cmts_ip": cmts_ip,
            "scqam_channels": task_result.get('scqam_channels', []),
            "ofdma_channels": task_result.get('ofdma_channels', [])
        })
            
    except Exception as e:
        logger.error(f"Get upstream interfaces failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/configure/<mac_address>', methods=['POST'])
def configure_utsc(mac_address):
    """
    Configure UTSC (Upstream Triggered Spectrum Capture) test.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "trigger_mode": 2,  // 2=FreeRunning, 5=IdleSID, 6=CM_MAC
        "center_freq_hz": 30000000,
        "span_hz": 80000000,
        "num_bins": 800,
        "output_format": 2,  // 2=fftPower
        "filename": "utsc_capture",
        "repeat_period_ms": 0,  // 0=single, >0=repeat
        "freerun_duration_ms": 1000,
        "logical_ch_ifindex": null,  // For IdleSID/CM_MAC
        "community": "optional"
    }
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
        agent = agent_manager.get_agent_for_capability('pnm_utsc_configure') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for UTSC"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_utsc_configure',
            params={
                "cmts_ip": cmts_ip,
                "rf_port_ifindex": rf_port_ifindex,
                "trigger_mode": data.get('trigger_mode', 2),
                "center_freq_hz": data.get('center_freq_hz', 30000000),
                "span_hz": data.get('span_hz', 80000000),
                "num_bins": data.get('num_bins', 800),
                "output_format": data.get('output_format', 2),
                "filename": data.get('filename', f'utsc_{mac_address.replace(":", "")}'),
                "repeat_period_ms": data.get('repeat_period_ms', 0),
                "freerun_duration_ms": data.get('freerun_duration_ms', 1000),
                "cm_mac_address": mac_address if data.get('trigger_mode') == 6 else None,
                "logical_ch_ifindex": data.get('logical_ch_ifindex'),
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
        logger.error(f"Configure UTSC failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@pypnm_bp.route('/upstream/utsc/start/<mac_address>', methods=['POST'])
def start_utsc(mac_address):
    """
    Start UTSC test on CMTS.
    
    POST body:
    {
        "cmts_ip": "x.x.x.x",
        "rf_port_ifindex": 12345,
        "community": "optional"
    }
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
        agent = agent_manager.get_agent_for_capability('pnm_utsc_start') if agent_manager else None
        
        if not agent:
            return jsonify({"status": "error", "message": "No agent available for UTSC"}), 503
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_utsc_start',
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
        logger.error(f"Start UTSC failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
    Start Upstream OFDMA RxMER measurement on CMTS via agent.
    
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
    community = data.get('community', 'Z1gg0Sp3c1@l')  # CMTS write community
    
    if not cmts_ip or not ofdma_ifindex:
        return jsonify({"status": "error", "message": "cmts_ip and ofdma_ifindex required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_rxmer_start') if agent_manager else None
        
        if not agent:
            return jsonify({"success": False, "error": "No agent available for US RxMER"}), 503
        
        params = {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "cm_mac_address": mac_address,
            "community": community,
            "pre_eq": data.get('pre_eq', True),
            "filename": data.get('filename', f'usrxmer_{mac_address.replace(":", "")}')
        }
        
        logger.info(f"Starting US RxMER via agent {agent.agent_id} for {mac_address}")
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_start',
            params=params,
            timeout=60
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result is None:
            return jsonify({"success": False, "error": "Task timed out"}), 504
        
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
    """Get Upstream RxMER measurement status via agent."""
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
            return jsonify({"success": False, "error": "No agent available for US RxMER"}), 503
        
        params = {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "community": community
        }
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_status',
            params=params,
            timeout=30
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=30)
        
        if result is None:
            return jsonify({"success": False, "error": "Task timed out"}), 504
        
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
    Fetch Upstream RxMER data via agent.
    
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
    filename = data.get('filename')
    
    if not cmts_ip:
        return jsonify({"status": "error", "message": "cmts_ip required"}), 400
    
    try:
        agent_manager = get_simple_agent_manager()
        agent = agent_manager.get_agent_for_capability('pnm_us_rxmer_data') if agent_manager else None
        
        if not agent:
            return jsonify({"success": False, "error": "No agent available for US RxMER"}), 503
        
        params = {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "community": community,
            "cm_mac_address": mac_address
        }
        
        if filename:
            import os
            params["filename"] = os.path.basename(filename)
        
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_us_rxmer_data',
            params=params,
            timeout=120
        )
        
        result = agent_manager.wait_for_task(task_id, timeout=120)
        
        if result is None:
            return jsonify({"success": False, "error": "Task timed out"}), 504
        
        task_result = result.get('result', {})
        return jsonify({
            "success": task_result.get('success', False),
            "mac_address": mac_address,
            **task_result
        })
        
    except Exception as e:
        logger.error(f"Get US RxMER data failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
