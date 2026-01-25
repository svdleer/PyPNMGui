"""
WebSocket UTSC Streaming Endpoint
Streams live upstream spectrum data by running multiple UTSC windows
Workaround for E6000 firmware limitation (max 10 captures per run)
"""

import asyncio
import json
import logging
import os
import struct
import time
import glob
from flask import request
from flask_sock import Sock

logger = logging.getLogger(__name__)

# Will be initialized by app
sock = None

def init_utsc_stream(app):
    """Initialize WebSocket endpoint for UTSC streaming"""
    global sock
    sock = Sock(app)
    
    @sock.route('/ws/utsc/stream')
    async def utsc_stream(ws):
        """
        WebSocket endpoint for streaming UTSC data
        
        Client sends initial config:
        {
            "cmts_ip": "172.16.6.212",
            "rf_port_ifindex": 1079058432,
            "community": "Z1gg0Sp3c1@l",
            "mac_address": "fc:01:7c:bf:73:e3",
            "center_freq_hz": 30000000,
            "span_hz": 80000000,
            "num_bins": 800,
            "duration_sec": 120,  # Total streaming duration
            "refresh_hz": 2       # Frames per second
        }
        """
        try:
            # Receive configuration
            config_msg = await ws.receive()
            config = json.loads(config_msg)
            
            logger.info(f"Starting UTSC stream: {config}")
            
            cmts_ip = config['cmts_ip']
            rf_port = config['rf_port_ifindex']
            community = config.get('community', 'Z1gg0Sp3c1@l')
            mac = config['mac_address']
            center_freq = config.get('center_freq_hz', 30000000)
            span = config.get('span_hz', 80000000)
            num_bins = config.get('num_bins', 800)
            duration_sec = config.get('duration_sec', 120)
            refresh_hz = config.get('refresh_hz', 2)
            
            # Calculate timing
            repeat_period_ms = int(1000 / refresh_hz)  # ms between captures
            window_sec = 10  # E6000 max practical window
            num_runs = int(duration_sec / window_sec)
            
            await ws.send(json.dumps({
                'type': 'config',
                'runs': num_runs,
                'captures_per_run': int(window_sec * refresh_hz),
                'total_captures': int(duration_sec * refresh_hz)
            }))
            
            # Run streaming loop
            run_id = 0
            for run in range(num_runs):
                run_id = int(time.time())
                filename = f"stream_{mac.replace(':', '')}_{run_id}"
                
                # Start UTSC via PyPNM API
                success = await start_utsc_run(
                    cmts_ip, rf_port, community,
                    center_freq, span, num_bins,
                    filename, repeat_period_ms, window_sec * 1000
                )
                
                if not success:
                    await ws.send(json.dumps({
                        'type': 'error',
                        'message': f'Failed to start UTSC run {run}'
                    }))
                    break
                
                # Wait for files and stream them
                await stream_utsc_files(ws, filename, num_bins, refresh_hz, window_sec)
                
                # Progress update
                progress = int((run + 1) / num_runs * 100)
                await ws.send(json.dumps({
                    'type': 'progress',
                    'run': run + 1,
                    'total_runs': num_runs,
                    'percent': progress
                }))
            
            # Completion
            await ws.send(json.dumps({
                'type': 'complete',
                'message': f'Streaming complete: {num_runs} runs'
            }))
            
        except Exception as e:
            logger.error(f"UTSC stream error: {e}", exc_info=True)
            try:
                await ws.send(json.dumps({
                    'type': 'error',
                    'message': str(e)
                }))
            except:
                pass


async def start_utsc_run(cmts_ip, rf_port, community, center_freq, span, num_bins, 
                         filename, repeat_period_ms, freerun_duration_ms):
    """Start a single UTSC run via PyPNM API"""
    from app.core.pypnm_client import PyPNMClient
    
    try:
        client = PyPNMClient()
        
        # Stop any existing capture
        try:
            client.stop_utsc(cmts_ip, rf_port, community)
            await asyncio.sleep(0.5)
        except:
            pass
        
        # Start new capture
        result = await asyncio.to_thread(
            client.get_upstream_spectrum_capture,
            cmts_ip=cmts_ip,
            rf_port_ifindex=rf_port,
            tftp_ipv4="172.16.6.101",
            community=community,
            output_type='json',
            trigger_mode=2,  # FreeRunning
            center_freq_hz=center_freq,
            span_hz=span,
            num_bins=num_bins,
            filename=filename,
            repeat_period_ms=repeat_period_ms,
            freerun_duration_ms=freerun_duration_ms
        )
        
        return result.get('success', False)
        
    except Exception as e:
        logger.error(f"Failed to start UTSC: {e}")
        return False


async def stream_utsc_files(ws, filename_prefix, num_bins, refresh_hz, window_sec):
    """
    Wait for UTSC files to arrive and stream them as JSON frames
    E6000 delivers ~10 files per 10-second window via TFTP
    """
    tftp_dir = "/var/lib/tftpboot"
    
    # Calculate expected captures
    expected = int(window_sec * refresh_hz)
    timeout = window_sec + 10  # Extra time for file delivery
    start_time = time.time()
    
    sent_files = set()
    
    while time.time() - start_time < timeout:
        # Find matching files
        pattern = f"{tftp_dir}/{filename_prefix}*"
        files = glob.glob(pattern)
        
        # Send new files
        for filepath in sorted(files):
            if filepath not in sent_files:
                try:
                    spectrum = parse_utsc_file(filepath, num_bins)
                    
                    if spectrum:
                        await ws.send(json.dumps({
                            'type': 'spectrum',
                            'timestamp': time.time(),
                            'filename': os.path.basename(filepath),
                            'power': spectrum
                        }))
                        
                        sent_files.add(filepath)
                        
                except Exception as e:
                    logger.error(f"Failed to parse {filepath}: {e}")
        
        # Check if we got enough
        if len(sent_files) >= expected:
            break
        
        await asyncio.sleep(0.1)
    
    logger.info(f"Streamed {len(sent_files)} files for {filename_prefix}")


def parse_utsc_file(filepath, num_bins):
    """
    Parse UTSC file and extract FFT power spectrum
    
    File format:
    - 328 bytes header
    - Payload: num_bins × int16 (big endian) power values in tenths of dB
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        
        if len(data) < 328 + num_bins * 2:
            return None
        
        # Skip header
        payload = data[328:]
        
        # Parse power values (int16, big endian, in tenths of dB)
        bins = struct.unpack(f">{num_bins}h", payload[:num_bins * 2])
        
        # Convert to dB
        spectrum = [b / 10.0 for b in bins]
        
        return spectrum
        
    except Exception as e:
        logger.error(f"Parse error for {filepath}: {e}")
        return None
