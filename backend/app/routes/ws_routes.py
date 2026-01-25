# PyPNM Web GUI - WebSocket Routes for Agents
# SPDX-License-Identifier: Apache-2.0

import logging
import json
import time
import glob
import os
import struct
import threading
import requests
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


def trigger_utsc_via_agent(cmts_ip, rf_port_ifindex, community):
    """Trigger UTSC test via agent's snmp_set capability."""
    from app.core.simple_ws import get_simple_agent_manager
    
    try:
        agent_manager = get_simple_agent_manager()
        if not agent_manager:
            logger.error("Agent manager not available")
            return False
        
        agent = agent_manager.get_agent_for_capability('snmp_set')
        if not agent:
            logger.error("No agent with snmp_set capability")
            return False
        
        oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf_port_ifindex}.1"
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_set',
            params={
                'target_ip': cmts_ip,
                'oid': oid,
                'value': 1,  # 1 = start
                'type': 'i',
                'community': community
            },
            timeout=5
        )
        result = agent_manager.wait_for_task(task_id, timeout=5)
        # Agent returns: {'type': 'response', 'result': {'success': True, ...}}
        if result and result.get('result', {}).get('success'):
            logger.debug(f"UTSC triggered via agent on port {rf_port_ifindex}")
            return True
        else:
            logger.warning(f"UTSC trigger failed: {result}")
            return False
    except Exception as e:
        logger.error(f"UTSC trigger error: {e}")
        return False


def stop_utsc_via_agent(cmts_ip, rf_port_ifindex, community):
    """Stop UTSC test via agent's snmp_set capability."""
    from app.core.simple_ws import get_simple_agent_manager
    
    try:
        agent_manager = get_simple_agent_manager()
        if not agent_manager:
            logger.error("Agent manager not available")
            return False
        
        agent = agent_manager.get_agent_for_capability('snmp_set')
        if not agent:
            logger.error("No agent with snmp_set capability")
            return False
        
        oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{rf_port_ifindex}.1"
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_set',
            params={
                'target_ip': cmts_ip,
                'oid': oid,
                'value': 2,  # 2 = abort
                'type': 'i',
                'community': community
            },
            timeout=5
        )
        result = agent_manager.wait_for_task(task_id, timeout=5)
        # Agent returns: {'type': 'response', 'result': {'success': True, ...}}
        if result and result.get('result', {}).get('success'):
            logger.debug(f"UTSC stopped via agent on port {rf_port_ifindex}")
            return True
        else:
            logger.warning(f"UTSC stop failed: {result}")
            return False
    except Exception as e:
        logger.error(f"UTSC stop error: {e}")
        return False


# UTSC Status values (from CMTS MIB)
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
        last_status = None
        initial_buffer_target = 3  # Start streaming quickly after few files
        streaming_started = False
        # Single trigger only - no re-triggering, let freerun complete naturally
        
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
            
            # Look for recent files from this MAC (last 60 seconds)
            pattern = f"{tftp_base}/utsc_{mac_clean}_*"
            all_files = glob.glob(pattern)
            current_time = time.time()
            recent_files = [f for f in all_files if (current_time - os.path.getmtime(f)) < 60]
            old_files = [f for f in all_files if f not in recent_files]
            
            # Delete only OLD files (>60s), keep recent ones
            if old_files:
                logger.info(f"UTSC WebSocket: Deleting {len(old_files)} old files (>60s)")
                filenames = [os.path.basename(f) for f in old_files]
                deleted = delete_utsc_files_via_ftp(ftp_server, ftp_user, ftp_pass, filenames)
                logger.info(f"UTSC WebSocket: Deleted {deleted}/{len(old_files)} old files")
                time.sleep(0.2)
            
            # Mark recent files as ready to stream
            if recent_files:
                logger.info(f"UTSC WebSocket: Found {len(recent_files)} recent files (<60s old) - will stream these")
            else:
                logger.info(f"UTSC WebSocket: No recent files found - waiting for new captures")
            
            # DO NOT TRIGGER! PyPNM API already triggered UTSC in FreeRunning mode
            # Start collecting files from NOW - E6000 generates continuously for 60s
            stream_start_time = time.time()
            logger.info(f"UTSC WebSocket: Streaming files from NOW (API-triggered freerun runs for 60s)")
            
            while _utsc_sessions.get(session_id, False):
                current_time = time.time()
                elapsed = current_time - connection_start_time
                
                # Collect new files continuously - no time limit
                pattern = f"{tftp_base}/utsc_{mac_clean}_*"
                files = glob.glob(pattern)
                # Filter: not processed AND created after stream start
                new_files = [f for f in files 
                            if f not in processed_files 
                            and os.path.getmtime(f) >= stream_start_time]
                
                if len(new_files) > 0:
                    logger.info(f"UTSC WebSocket: Found {len(new_files)} new files to process")
                
                for filepath in sorted(new_files, key=os.path.getmtime):
                    processed_files.add(filepath)
                    
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
                            logger.info(f"Parsed {len(all_amplitudes)} amplitude samples from {os.path.basename(filepath)}")
                    except Exception as e:
                        logger.error(f"Error parsing UTSC file {filepath}: {e}")
                
                # Wait for initial buffer to fill before starting stream (must be exactly target or more)
                if not streaming_started:
                    current_buffer_size = len(file_buffer)
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
                
                # NO RE-TRIGGERING - Single trigger, let freerun complete naturally
                
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
            # Don't auto-stop UTSC - let freerun complete naturally
            # User can manually stop via /upstream/utsc/stop endpoint if needed
            # if rf_port and cmts_ip:
            #     logger.info(f"UTSC WebSocket: Stopping UTSC on {cmts_ip} port {rf_port}")
            #     try:
            #         stop_utsc_via_agent(cmts_ip, int(rf_port), community)
            #     except Exception as e:
            #         logger.warning(f"UTSC stop failed on cleanup: {e}")
            
            _utsc_sessions.pop(session_id, None)
            logger.info(f"UTSC WebSocket closed for {mac_address} (UTSC continues running)")
    
    logger.info("WebSocket agent endpoint registered at /ws/agent")
    logger.info("WebSocket UTSC endpoint registered at /ws/utsc/<mac>")
    return sock
