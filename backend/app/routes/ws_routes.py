# PyPNM Web GUI - WebSocket Routes for Agents
# SPDX-License-Identifier: Apache-2.0

import logging
import json
import time
import glob
import os
import struct
import threading
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
        """WebSocket endpoint for streaming UTSC spectrum data."""
        logger.info(f"UTSC WebSocket opened for {mac_address}")
        
        # Clean MAC address format
        mac_clean = mac_address.replace(':', '').replace('-', '').lower()
        session_id = f"{mac_clean}_{id(ws)}"
        _utsc_sessions[session_id] = True
        
        processed_files = set()  # Track files we've already sent
        tftp_base = '/var/lib/tftpboot'
        heartbeat_interval = 5  # Send heartbeat every 5 seconds
        last_heartbeat = time.time()
        last_send_time = 0
        connection_start_time = time.time()  # Track when WebSocket connected
        
        try:
            # Send initial connected message
            ws.send(json.dumps({
                'type': 'connected',
                'mac': mac_address,
                'message': 'UTSC stream connected'
            }))
            
            # Pre-populate processed_files with existing files to avoid sending old data
            pattern = f"{tftp_base}/utsc_{mac_clean}_*"
            existing_files = glob.glob(pattern)
            processed_files.update(existing_files)
            logger.info(f"UTSC WebSocket: Skipping {len(existing_files)} existing files for {mac_address}")
            
            while _utsc_sessions.get(session_id, False):
                current_time = time.time()
                
                # Send heartbeat to keep connection alive
                if current_time - last_heartbeat > heartbeat_interval:
                    ws.send(json.dumps({
                        'type': 'heartbeat',
                        'timestamp': current_time
                    }))
                    last_heartbeat = current_time
                
                # Check for UTSC files
                pattern = f"{tftp_base}/utsc_{mac_clean}_*"
                files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
                
                # Process only NEW files (created after connection)
                for filepath in files:
                    if filepath in processed_files:
                        continue  # Already sent this one
                    
                    processed_files.add(filepath)
                    last_send_time = current_time
                    
                    try:
                        # Read and parse the file
                        with open(filepath, 'rb') as f:
                            binary_data = f.read()
                        
                        if len(binary_data) >= 328:
                                # Parse amplitudes - UTSC format: big-endian int16, units 0.1 dBmV
                                samples = binary_data[328:]
                                amplitudes = []
                                for i in range(0, len(samples), 2):
                                    if i+1 < len(samples):
                                        val = struct.unpack('>h', samples[i:i+2])[0]  # Big-endian
                                        amplitudes.append(val / 10.0)  # Convert 0.1 dBmV to dBmV
                                
                                # Get config from Redis for frequency calculation
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
                                
                                # Generate frequencies
                                num_bins = len(amplitudes)
                                freq_start = center_freq_hz - (span_hz / 2)
                                freq_step = span_hz / num_bins if num_bins > 0 else 1
                                frequencies = [freq_start + i * freq_step for i in range(num_bins)]
                                
                                # Generate plot
                                from app.core.utsc_plotter import generate_utsc_plot_from_data
                                spectrum_data = {
                                    'frequencies': frequencies[:3200],
                                    'amplitudes': amplitudes[:3200],
                                    'span_hz': span_hz,
                                    'center_freq_hz': center_freq_hz,
                                    'num_bins': num_bins
                                }
                                
                                plot = generate_utsc_plot_from_data(spectrum_data, mac_address, '')

                                if plot:
                                    # Send both plot AND raw data via websocket for interactive mode
                                    ws.send(json.dumps({
                                        'type': 'spectrum',
                                        'timestamp': current_time,
                                        'filename': os.path.basename(filepath),
                                        'plot': plot,
                                        'raw_data': {
                                            'frequencies': frequencies[:3200],
                                            'amplitudes': amplitudes[:3200],
                                            'span_hz': span_hz,
                                            'center_freq_hz': center_freq_hz
                                        }
                                    }))
                                
                    except Exception as e:
                        logger.error(f"Error processing UTSC file {filepath}: {e}")
                
                # Small sleep to prevent CPU spinning (1ms)
                time.sleep(0.001)
                    
        except Exception as e:
            logger.error(f"UTSC WebSocket error: {e}")
        finally:
            _utsc_sessions.pop(session_id, None)
            logger.info(f"UTSC WebSocket closed for {mac_address}")
    
    logger.info("WebSocket agent endpoint registered at /ws/agent")
    logger.info("WebSocket UTSC endpoint registered at /ws/utsc/<mac>")
    return sock
