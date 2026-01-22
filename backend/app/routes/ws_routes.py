# PyPNM Web GUI - WebSocket Routes for Agents
# SPDX-License-Identifier: Apache-2.0

import logging
import json
import time
import glob
import os
import struct
import threading
import subprocess
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

# Track active UTSC streaming sessions
_utsc_sessions = {}


def trigger_utsc_via_snmp(cmts_ip, rf_port_ifindex, community):
    """Trigger UTSC test directly via SNMP (fast, bypasses PyPNM API)."""
    try:
        oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf_port_ifindex}.1"
        cmd = ['snmpset', '-v2c', '-c', community, cmts_ip, oid, 'i', '1']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.debug(f"UTSC re-triggered via SNMP on port {rf_port_ifindex}")
            return True
        else:
            logger.warning(f"SNMP trigger failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"SNMP trigger error: {e}")
        return False


def get_utsc_status(cmts_ip, rf_port_ifindex, community):
    """Get UTSC measurement status via SNMP."""
    try:
        oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1.{rf_port_ifindex}.1"
        cmd = ['snmpget', '-v2c', '-c', community, cmts_ip, oid]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            # Parse "INTEGER: sampleReady(4)" -> 4
            output = result.stdout.strip()
            if 'INTEGER:' in output:
                match = output.split('(')[-1].rstrip(')')
                try:
                    return int(match)
                except:
                    pass
        return None
    except Exception as e:
        logger.debug(f"SNMP status error: {e}")
        return None


# UTSC Status values
STATUS_INACTIVE = 2
STATUS_BUSY = 3
STATUS_SAMPLE_READY = 4
STATUS_ERROR = 5


def init_websocket(app):
    """Initialize WebSocket support."""
    if not WEBSOCKET_AVAILABLE:
        logger.warning("WebSocket not available")
        return None
    
    sock = Sock(app)
    
    # Initialize the simple agent manager
    from app.core.simple_ws import init_simple_agent_manager
    auth_token = app.config.get('AGENT_AUTH_TOKEN', 'dev-token-change-me')
    agent_manager = init_simple_agent_manager(auth_token)
    
    @sock.route('/ws/agent')
    def agent_websocket(ws):
        """WebSocket endpoint for agent connections."""
        logger.info("Agent WebSocket connection opened")
        
        try:
            while True:
                message = ws.receive()
                if message is None:
                    break
                
                # Handle message
                response = agent_manager.handle_message(ws, message)
                if response:
                    ws.send(response)
                    
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            agent_manager.remove_agent(ws)
            logger.info("Agent WebSocket connection closed")
    
    @sock.route('/ws/utsc/<mac_address>')
    def utsc_websocket(ws, mac_address):
        """WebSocket endpoint for streaming UTSC spectrum data with buffering."""
        from flask import request
        
        # Parse query parameters
        refresh_ms = int(request.args.get('refresh', 500))  # Refresh rate in ms
        duration_s = int(request.args.get('duration', 60))  # Duration in seconds
        rf_port = request.args.get('rf_port')
        cmts_ip = request.args.get('cmts_ip')
        community = request.args.get('community', 'public')
        
        logger.info(f"UTSC WebSocket opened for {mac_address}: refresh={refresh_ms}ms, duration={duration_s}s")
        
        # Clean MAC address format
        mac_clean = mac_address.replace(':', '').replace('-', '').lower()
        session_id = f"{mac_clean}_{id(ws)}"
        _utsc_sessions[session_id] = True
        
        processed_files = set()  # Track files we've already processed
        file_buffer = deque(maxlen=500)  # Buffer for smooth streaming (max 500 samples)
        tftp_base = '/var/lib/tftpboot'
        heartbeat_interval = 5
        last_heartbeat = time.time()
        last_stream_time = 0
        stream_interval = refresh_ms / 1000.0  # Convert to seconds
        connection_start_time = time.time()
        last_trigger_time = 0
        can_trigger = True
        last_status = None
        initial_buffer_target = 20  # Wait for 20 files before starting stream
        streaming_started = False
        
        try:
            # Send initial connected message
            ws.send(json.dumps({
                'type': 'connected',
                'mac': mac_address,
                'message': f'UTSC stream connected: {stream_interval:.1f}s refresh, {duration_s}s duration',
                'refresh_ms': refresh_ms,
                'duration_s': duration_s
            }))
            
            # Pre-populate processed_files with existing files
            pattern = f"{tftp_base}/utsc_{mac_clean}_*"
            existing_files = glob.glob(pattern)
            processed_files.update(existing_files)
            logger.info(f"UTSC WebSocket: Skipping {len(existing_files)} existing files")
            
            # Initial SNMP trigger if we have the parameters
            if rf_port and cmts_ip:
                logger.info(f"UTSC WebSocket: Initial trigger on {cmts_ip} port {rf_port}")
                trigger_utsc_via_snmp(cmts_ip, int(rf_port), community)
                last_trigger_time = time.time()
                can_trigger = False
            
            while _utsc_sessions.get(session_id, False):
                current_time = time.time()
                elapsed = current_time - connection_start_time
                
                # Check duration limit
                if elapsed > duration_s:
                    logger.info(f"UTSC WebSocket: Duration {duration_s}s reached, closing")
                    ws.send(json.dumps({
                        'type': 'complete',
                        'message': f'Duration {duration_s}s reached',
                        'files_streamed': len(processed_files) - len(existing_files)
                    }))
                    break
                
                # Poll UTSC status via SNMP (if we have params)
                if rf_port and cmts_ip:
                    status = get_utsc_status(cmts_ip, int(rf_port), community)
                    if status != last_status:
                        last_status = status
                        if status == STATUS_BUSY:
                            can_trigger = False
                        elif status in [STATUS_SAMPLE_READY, STATUS_INACTIVE]:
                            can_trigger = True
                
                # Collect new files into buffer
                pattern = f"{tftp_base}/utsc_{mac_clean}_*"
                files = glob.glob(pattern)
                new_files = [f for f in files if f not in processed_files]
                
                for filepath in sorted(new_files, key=os.path.getmtime):
                    processed_files.add(filepath)
                    
                    try:
                        with open(filepath, 'rb') as f:
                            binary_data = f.read()
                        
                        if len(binary_data) >= 328:
                            # Parse amplitudes
                            samples = binary_data[328:]
                            amplitudes = []
                            for i in range(0, len(samples), 2):
                                if i+1 < len(samples):
                                    val = struct.unpack('>h', samples[i:i+2])[0]
                                    amplitudes.append(val / 10.0)
                            
                            # Get config from Redis
                            try:
                                from app import redis_client
                                config_json = redis_client.get(f'utsc_config:{mac_address}')
                                if config_json:
                                    config = json.loads(config_json)
                                    span_hz = config.get('span_hz', 100000000)
                                    center_freq_hz = config.get('center_freq_hz', 50000000)
                                else:
                                    span_hz = 100000000
                                    center_freq_hz = 50000000
                            except:
                                span_hz = 100000000
                                center_freq_hz = 50000000
                            
                            # Add to buffer
                            file_buffer.append({
                                'filepath': filepath,
                                'amplitudes': amplitudes,
                                'span_hz': span_hz,
                                'center_freq_hz': center_freq_hz,
                                'collected_at': current_time
                            })
                    except Exception as e:
                        logger.error(f"Error parsing UTSC file {filepath}: {e}")
                
                # Wait for initial buffer to fill before starting stream
                if not streaming_started:
                    if len(file_buffer) >= initial_buffer_target:
                        streaming_started = True
                        logger.info(f"UTSC WebSocket: Initial buffer of {len(file_buffer)} files ready, starting stream")
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
                    freq_start = item['center_freq_hz'] - (item['span_hz'] / 2)
                    freq_step = item['span_hz'] / num_bins if num_bins > 0 else 1
                    frequencies = [freq_start + i * freq_step for i in range(num_bins)]
                    
                    # Limit to 1600 points for WebSocket
                    raw_frequencies = frequencies[:1600]
                    raw_amplitudes = amplitudes[:1600]
                    
                    message = {
                        'type': 'spectrum',
                        'timestamp': current_time,
                        'filename': os.path.basename(item['filepath']),
                        'buffer_size': len(file_buffer),
                        'plot': None,
                        'raw_data': {
                            'frequencies': raw_frequencies,
                            'amplitudes': raw_amplitudes,
                            'span_hz': item['span_hz'],
                            'center_freq_hz': item['center_freq_hz']
                        }
                    }
                    
                    try:
                        ws.send(json.dumps(message))
                    except Exception as send_err:
                        logger.error(f"Failed to send UTSC data: {send_err}")
                        raise
                
                # Re-trigger via SNMP when buffer gets low to maintain buffer
                # E6000 generates 10 files per burst in ~11 seconds
                # At 1 file/sec stream rate, we need to trigger before consuming all 10
                # Trigger at 5 files remaining = 5 seconds before empty = enough time for CMTS
                time_since_trigger = current_time - last_trigger_time
                buffer_low = len(file_buffer) <= 5  # Trigger when 5 or fewer files remain
                time_ok = time_since_trigger >= 2.0  # Minimum 2s between triggers
                if rf_port and cmts_ip and time_ok and (buffer_low or can_trigger):
                    logger.debug(f"UTSC WebSocket: Re-triggering (buffer={len(file_buffer)}, next batch in ~11s)")
                    trigger_utsc_via_snmp(cmts_ip, int(rf_port), community)
                    last_trigger_time = current_time
                    can_trigger = False
                
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
            logger.error(f"UTSC WebSocket error: {e}")
        finally:
            _utsc_sessions.pop(session_id, None)
            logger.info(f"UTSC WebSocket closed for {mac_address}")
    
    logger.info("WebSocket agent endpoint registered at /ws/agent")
    logger.info("WebSocket UTSC endpoint registered at /ws/utsc/<mac>")
    return sock
