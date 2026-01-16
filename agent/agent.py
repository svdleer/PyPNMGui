# PyPNM Jump Server Agent
# SPDX-License-Identifier: Apache-2.0
# 
# This agent runs on the Jump Server and connects OUT to the GUI Server
# via WebSocket. It executes SNMP/SSH commands and returns results.

import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import websocket
except ImportError:
    print("ERROR: websocket-client not installed. Run: pip install websocket-client")
    exit(1)

try:
    import paramiko
except ImportError:
    paramiko = None
    print("WARNING: paramiko not installed. SSH proxy features disabled.")

try:
    import redis
except ImportError:
    redis = None
    print("INFO: redis not installed. Caching disabled. Run: pip install redis")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('PyPNM-Agent')


@dataclass
class AgentConfig:
    """Agent configuration for Jump Server deployment."""
    agent_id: str
    pypnm_server_url: str
    auth_token: str
    reconnect_interval: int = 5
    
    # SSH Tunnel to PyPNM Server (WebSocket connection)
    pypnm_ssh_tunnel_enabled: bool = False
    pypnm_ssh_host: Optional[str] = None
    pypnm_ssh_port: int = 22
    pypnm_ssh_user: Optional[str] = None
    pypnm_ssh_key: Optional[str] = None
    pypnm_tunnel_local_port: int = 8080
    pypnm_tunnel_remote_port: int = 8080
    
    # CMTS Access (can be direct SNMP or via SSH)
    cmts_snmp_direct: bool = True
    cmts_ssh_enabled: bool = False
    cmts_ssh_user: Optional[str] = None
    cmts_ssh_key: Optional[str] = None
    
    # CM Proxy - Server with connectivity to Cable Modems
    # SNMP commands to modems are executed on this server via SSH
    cm_proxy_host: Optional[str] = None
    cm_proxy_port: int = 22
    cm_proxy_user: Optional[str] = None
    cm_proxy_key: Optional[str] = None
    
    # Equalizer Server - for SNMP queries via SSH (has best CMTS connectivity)
    equalizer_host: Optional[str] = None
    equalizer_port: int = 22
    equalizer_user: Optional[str] = None
    equalizer_key: Optional[str] = None
    
    # Redis caching for modem data
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_ttl: int = 300  # Cache TTL in seconds
    
    # TFTP/FTP Server - accessed via SSH for PNM file retrieval
    tftp_ssh_host: Optional[str] = None
    tftp_ssh_port: int = 22
    tftp_ssh_user: Optional[str] = None
    tftp_ssh_key: Optional[str] = None
    tftp_path: str = "/tftpboot"
    
    @classmethod
    def from_file(cls, path: str) -> 'AgentConfig':
        """Load configuration from JSON file."""
        with open(path) as f:
            data = json.load(f)
        
        # Expand ~ in paths
        def expand_path(p):
            return os.path.expanduser(p) if p else None
        
        # Support both old 'gui_server' and new 'pypnm_server' keys
        server_config = data.get('pypnm_server') or data.get('gui_server', {})
        tunnel_config = data.get('pypnm_ssh_tunnel') or data.get('gui_ssh_tunnel', {})
        
        cmts = data.get('cmts_access', {})
        cm_proxy = data.get('cm_proxy', {})
        equalizer = data.get('equalizer', {})
        redis_config = data.get('redis', {})
        tftp = data.get('tftp_server', {})
        
        return cls(
            agent_id=data['agent_id'],
            pypnm_server_url=server_config['url'],
            auth_token=server_config['auth_token'],
            reconnect_interval=server_config.get('reconnect_interval', 5),
            # SSH Tunnel to PyPNM Server
            pypnm_ssh_tunnel_enabled=tunnel_config.get('enabled', False),
            pypnm_ssh_host=tunnel_config.get('ssh_host'),
            pypnm_ssh_port=tunnel_config.get('ssh_port', 22),
            pypnm_ssh_user=tunnel_config.get('ssh_user'),
            pypnm_ssh_key=expand_path(tunnel_config.get('ssh_key_file')),
            pypnm_tunnel_local_port=tunnel_config.get('local_port', 8080),
            pypnm_tunnel_remote_port=tunnel_config.get('remote_port', 8080),
            # CMTS Access
            cmts_snmp_direct=cmts.get('snmp_direct', True),
            cmts_ssh_enabled=cmts.get('ssh_enabled', False),
            cmts_ssh_user=cmts.get('ssh_user'),
            cmts_ssh_key=expand_path(cmts.get('ssh_key_file')),
            # CM Proxy (for reaching modems)
            cm_proxy_host=cm_proxy.get('host'),
            cm_proxy_port=cm_proxy.get('port', 22),
            cm_proxy_user=cm_proxy.get('username'),
            cm_proxy_key=expand_path(cm_proxy.get('key_file')),
            # Equalizer (for CMTS SNMP via SSH)
            equalizer_host=equalizer.get('host'),
            equalizer_port=equalizer.get('port', 22),
            equalizer_user=equalizer.get('username') or equalizer.get('user'),
            equalizer_key=expand_path(equalizer.get('key_file')),
            # Redis caching
            redis_host=redis_config.get('host'),
            redis_port=redis_config.get('port', 6379),
            redis_ttl=redis_config.get('ttl', 300),
            # TFTP Server (via SSH)
            tftp_ssh_host=tftp.get('host'),
            tftp_ssh_port=tftp.get('port', 22),
            tftp_ssh_user=tftp.get('username'),
            tftp_ssh_key=expand_path(tftp.get('key_file')),
            tftp_path=tftp.get('tftp_path', '/tftpboot'),
        )
    
    @classmethod
    def from_env(cls) -> 'AgentConfig':
        """Load configuration from environment variables."""
        def expand_path(p):
            return os.path.expanduser(p) if p else None
        
        return cls(
            agent_id=os.environ.get('PYPNM_AGENT_ID', 'agent-01'),
            pypnm_server_url=os.environ.get('PYPNM_SERVER_URL', 'ws://127.0.0.1:5050/ws/agent'),
            auth_token=os.environ.get('PYPNM_AUTH_TOKEN', 'dev-token'),
            reconnect_interval=int(os.environ.get('PYPNM_RECONNECT_INTERVAL', '5')),
            # SSH Tunnel to PyPNM
            pypnm_ssh_tunnel_enabled=os.environ.get('PYPNM_SSH_TUNNEL', 'false').lower() == 'true',
            pypnm_ssh_host=os.environ.get('PYPNM_SSH_HOST'),
            pypnm_ssh_port=int(os.environ.get('PYPNM_SSH_PORT', '22')),
            pypnm_ssh_user=os.environ.get('PYPNM_SSH_USER'),
            pypnm_ssh_key=expand_path(os.environ.get('PYPNM_SSH_KEY')),
            pypnm_tunnel_local_port=int(os.environ.get('PYPNM_LOCAL_PORT', '8080')),
            pypnm_tunnel_remote_port=int(os.environ.get('PYPNM_REMOTE_PORT', '8080')),
            # CMTS
            cmts_snmp_direct=os.environ.get('PYPNM_CMTS_SNMP_DIRECT', 'true').lower() == 'true',
            cmts_ssh_enabled=os.environ.get('PYPNM_CMTS_SSH_ENABLED', 'false').lower() == 'true',
            cmts_ssh_user=os.environ.get('PYPNM_CMTS_SSH_USER'),
            cmts_ssh_key=expand_path(os.environ.get('PYPNM_CMTS_SSH_KEY')),
            # CM Proxy
            cm_proxy_host=os.environ.get('PYPNM_CM_PROXY_HOST'),
            cm_proxy_port=int(os.environ.get('PYPNM_CM_PROXY_PORT', '22')),
            cm_proxy_user=os.environ.get('PYPNM_CM_PROXY_USER'),
            cm_proxy_key=expand_path(os.environ.get('PYPNM_CM_PROXY_KEY')),
            # TFTP
            tftp_ssh_host=os.environ.get('PYPNM_TFTP_SSH_HOST'),
            tftp_ssh_port=int(os.environ.get('PYPNM_TFTP_SSH_PORT', '22')),
            tftp_ssh_user=os.environ.get('PYPNM_TFTP_SSH_USER'),
            tftp_ssh_key=expand_path(os.environ.get('PYPNM_TFTP_SSH_KEY')),
            tftp_path=os.environ.get('PYPNM_TFTP_PATH', '/tftpboot'),
        )


class SSHProxyExecutor:
    """Executes commands on remote server via SSH."""
    
    def __init__(self, host: str, port: int, username: str, key_file: Optional[str] = None):
        self.host = host
        self.port = port
        self.username = username
        self.key_file = key_file
        self._client: Optional[paramiko.SSHClient] = None
        self.logger = logging.getLogger(f'{__name__}.SSHProxy')
    
    def connect(self) -> bool:
        """Establish SSH connection."""
        if paramiko is None:
            self.logger.error("paramiko not installed")
            return False
        
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
            }
            
            if self.key_file:
                connect_kwargs['key_filename'] = self.key_file
            
            self._client.connect(**connect_kwargs)
            self.logger.info(f"Connected to SSH proxy: {self.host}")
            return True
            
        except Exception as e:
            self.logger.error(f"SSH connection failed: {e}")
            return False
    
    def execute(self, command: str, timeout: int = 30) -> tuple[int, str, str]:
        """Execute command on remote server."""
        if not self._client:
            if not self.connect():
                return -1, "", "SSH connection failed"
        
        try:
            stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            return exit_code, stdout.read().decode(), stderr.read().decode()
        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            return -1, "", str(e)
    
    def close(self):
        """Close SSH connection."""
        if self._client:
            self._client.close()
            self._client = None


class SNMPExecutor:
    """Executes SNMP commands, optionally through SSH proxy."""
    
    # Allowed SNMP commands (whitelist for security)
    ALLOWED_COMMANDS = {
        'snmpget', 'snmpwalk', 'snmpbulkget', 'snmpbulkwalk', 'snmpset'
    }
    
    def __init__(self, ssh_proxy: Optional[SSHProxyExecutor] = None):
        self.ssh_proxy = ssh_proxy
        self.logger = logging.getLogger(f'{__name__}.SNMP')
    
    def execute_snmp(self, 
                     command: str,
                     target_ip: str,
                     oid: str,
                     community: str = 'private',
                     version: str = '2c',
                     timeout: int = 5,
                     retries: int = 1) -> dict:
        """Execute SNMP command."""
        
        # Validate command
        if command not in self.ALLOWED_COMMANDS:
            return {
                'success': False,
                'error': f'Command not allowed: {command}'
            }
        
        # Build SNMP command
        snmp_cmd = f"{command} -v{version} -c {community} -t {timeout} -r {retries} {target_ip} {oid}"
        
        self.logger.info(f"Executing: {snmp_cmd}")
        
        if self.ssh_proxy:
            # Execute through SSH proxy
            exit_code, stdout, stderr = self.ssh_proxy.execute(snmp_cmd)
        else:
            # Execute locally
            try:
                result = subprocess.run(
                    snmp_cmd.split(),
                    capture_output=True,
                    text=True,
                    timeout=timeout + 5
                )
                exit_code = result.returncode
                stdout = result.stdout
                stderr = result.stderr
            except subprocess.TimeoutExpired:
                return {'success': False, 'error': 'Command timeout'}
            except FileNotFoundError:
                return {'success': False, 'error': f'{command} not found'}
        
        if exit_code == 0:
            return {
                'success': True,
                'output': stdout.strip(),
                'command': command
            }
        else:
            return {
                'success': False,
                'error': stderr.strip() or f'Exit code: {exit_code}',
                'output': stdout.strip()
            }


class TFTPExecutor:
    """Handles TFTP file transfers."""
    
    def __init__(self, tftp_host: str, tftp_port: int = 69):
        self.tftp_host = tftp_host
        self.tftp_port = tftp_port
        self.logger = logging.getLogger(f'{__name__}.TFTP')
    
    def get_file(self, remote_path: str, local_path: Optional[str] = None) -> dict:
        """Download file from TFTP server."""
        if local_path is None:
            local_path = f"/tmp/{os.path.basename(remote_path)}"
        
        cmd = f"tftp {self.tftp_host} {self.tftp_port} -c get {remote_path} {local_path}"
        
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and os.path.exists(local_path):
                with open(local_path, 'rb') as f:
                    content = f.read()
                
                return {
                    'success': True,
                    'path': local_path,
                    'size': len(content),
                    'content_base64': content.hex()  # Send as hex for binary safety
                }
            else:
                return {
                    'success': False,
                    'error': result.stderr or 'File not found'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class PyPNMAgent:
    """Main agent class that connects to GUI Server and handles requests."""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.logger = logging.getLogger('PyPNM-Agent')
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = False
        
        # SSH Tunnel to PyPNM Server (if enabled)
        self.pypnm_tunnel = None
        self.pypnm_tunnel_monitor = None
        
        # Initialize SSH executor for CM Proxy (to reach modems)
        self.cm_proxy: Optional[SSHProxyExecutor] = None
        if config.cm_proxy_host:
            self.cm_proxy = SSHProxyExecutor(
                host=config.cm_proxy_host,
                port=config.cm_proxy_port,
                username=config.cm_proxy_user,
                key_file=config.cm_proxy_key
            )
            self.logger.info(f"CM Proxy configured: {config.cm_proxy_host}")
        
        # Equalizer executor for CMTS SNMP
        self.equalizer: Optional[SSHProxyExecutor] = None
        if config.equalizer_host:
            self.equalizer = SSHProxyExecutor(
                host=config.equalizer_host,
                port=config.equalizer_port,
                username=config.equalizer_user,
                key_file=config.equalizer_key
            )
            self.logger.info(f"Equalizer configured: {config.equalizer_host}")
        
        # SNMP Executor - direct SNMP for CMTS queries
        self.snmp_executor_direct = SNMPExecutor(ssh_proxy=None)
        
        # SNMP Executor via CM Proxy - for modem access through hop-access
        self.snmp_executor = SNMPExecutor(ssh_proxy=self.cm_proxy)
        
        # SSH executor for TFTP server
        self.tftp_ssh: Optional[SSHProxyExecutor] = None
        if config.tftp_ssh_host:
            self.tftp_ssh = SSHProxyExecutor(
                host=config.tftp_ssh_host,
                port=config.tftp_ssh_port,
                username=config.tftp_ssh_user,
                key_file=config.tftp_ssh_key
            )
            self.logger.info(f"TFTP SSH configured: {config.tftp_ssh_host}")
        
        # SSH executor for CMTS (if SSH access enabled)
        self.cmts_ssh: Optional[SSHProxyExecutor] = None
        if config.cmts_ssh_enabled and config.cmts_ssh_user:
            self.logger.info("CMTS SSH access enabled")
        
        # Command handlers
        self.handlers: dict[str, Callable] = {
            'ping': self._handle_ping,
            'snmp_get': self._handle_snmp_get,
            'snmp_walk': self._handle_snmp_walk,
            'snmp_set': self._handle_snmp_set,
            'snmp_bulk_get': self._handle_snmp_bulk_get,
            'tftp_get': self._handle_tftp_get,
            'cmts_command': self._handle_cmts_command,
            'execute_pnm': self._handle_pnm_command,
            'cmts_get_modems': self._handle_cmts_get_modems,
            'cmts_get_modem_info': self._handle_cmts_get_modem_info,
            'enrich_modems': self._handle_enrich_modems,
            # PNM measurement commands
            'pnm_rxmer': self._handle_pnm_rxmer,
            'pnm_spectrum': self._handle_pnm_spectrum,
            'pnm_fec': self._handle_pnm_fec,
            'pnm_pre_eq': self._handle_pnm_pre_eq,
            'pnm_channel_info': self._handle_pnm_channel_info,
            'pnm_event_log': self._handle_pnm_event_log,
            # OFDM capture commands
            'pnm_ofdm_channels': self._handle_pnm_ofdm_channels,
            'pnm_ofdm_capture': self._handle_pnm_ofdm_capture,
            'pnm_ofdm_rxmer': self._handle_pnm_ofdm_rxmer,
        }
    
    def _snmp_via_ssh(self, ssh_host: str, ssh_user: str, target_ip: str, oid: str, 
                       community: str, command: str = 'snmpbulkwalk') -> dict:
        """Execute SNMP command via SSH to remote server (e.g., Equalizer)."""
        if not paramiko:
            return {'success': False, 'error': 'paramiko not installed'}
        
        try:
            # Build SNMP command
            snmp_cmd = f"{command} -v2c -c {community} {target_ip} {oid}"
            
            # Connect via SSH
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ssh_host, username=ssh_user, timeout=30)
            
            self.logger.info(f"Executing via SSH to {ssh_host}: {command} {target_ip} {oid}")
            
            # Execute command
            stdin, stdout, stderr = ssh.exec_command(snmp_cmd, timeout=120)
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            ssh.close()
            
            if error and 'Timeout' in error:
                return {'success': False, 'error': f'SNMP timeout: {error}'}
            
            return {
                'success': True,
                'output': output,
                'error': error if error else None
            }
        except Exception as e:
            self.logger.error(f"SSH SNMP failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def _setup_pypnm_tunnel(self) -> bool:
        """Set up SSH tunnel to PyPNM Server if configured."""
        if not self.config.pypnm_ssh_tunnel_enabled:
            return True  # No tunnel needed
        
        if not self.config.pypnm_ssh_host:
            self.logger.error("PyPNM SSH tunnel enabled but no ssh_host configured")
            return False
        
        try:
            from ssh_tunnel import SSHTunnelConfig, SSHTunnelManager, TunnelMonitor
            
            tunnel_config = SSHTunnelConfig(
                ssh_host=self.config.pypnm_ssh_host,
                ssh_port=self.config.pypnm_ssh_port,
                ssh_user=self.config.pypnm_ssh_user,
                ssh_key_file=self.config.pypnm_ssh_key,
                local_port=self.config.pypnm_tunnel_local_port,
                remote_port=self.config.pypnm_tunnel_remote_port,
            )
            
            self.pypnm_tunnel = SSHTunnelManager(tunnel_config, use_paramiko=False)
            
            if not self.pypnm_tunnel.start_tunnel():
                self.logger.error("Failed to start PyPNM SSH tunnel")
                return False
            
            # Start tunnel monitor for auto-reconnect
            self.pypnm_tunnel_monitor = TunnelMonitor(self.pypnm_tunnel)
            self.pypnm_tunnel_monitor.start()
            
            self.logger.info(f"PyPNM SSH tunnel established: localhost:{self.config.pypnm_tunnel_local_port} → {self.config.pypnm_ssh_host}:{self.config.pypnm_tunnel_remote_port}")
            return True
            
        except ImportError:
            self.logger.error("ssh_tunnel module not available")
            return False
        except Exception as e:
            self.logger.error(f"Failed to set up PyPNM tunnel: {e}")
            return False
    
    def _get_websocket_url(self) -> str:
        """Get the WebSocket URL (through tunnel if enabled)."""
        if self.config.pypnm_ssh_tunnel_enabled:
            # Connect to local tunnel endpoint
            return f"ws://127.0.0.1:{self.config.pypnm_tunnel_local_port}/ws/agent"
        else:
            return self.config.pypnm_server_url
    
    def _on_open(self, ws):
        """Called when WebSocket connection is established."""
        ws_url = self._get_websocket_url()
        self.logger.info(f"Connected to PyPNM Server: {ws_url}")
        
        # Send authentication message
        auth_msg = {
            'type': 'auth',
            'agent_id': self.config.agent_id,
            'token': self.config.auth_token,
            'capabilities': self._get_capabilities()
        }
        ws.send(json.dumps(auth_msg))
    
    def _on_message(self, ws, message):
        """Called when a message is received."""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'auth_success':
                self.logger.info(f"Authentication successful as {data.get('agent_id')}")
                
            elif msg_type == 'auth_response':
                # Legacy support
                if data.get('success'):
                    self.logger.info("Authentication successful")
                else:
                    self.logger.error(f"Authentication failed: {data.get('error')}")
                    ws.close()
                    
            elif msg_type == 'command':
                self._handle_command(ws, data)
                
            elif msg_type == 'heartbeat_ack':
                pass  # Server acknowledged heartbeat
                
            elif msg_type == 'ping':
                ws.send(json.dumps({'type': 'pong', 'timestamp': time.time()}))
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON message: {e}")
    
    def _on_error(self, ws, error):
        """Called when an error occurs."""
        self.logger.error(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Called when connection is closed."""
        self.logger.warning(f"Connection closed: {close_status_code} - {close_msg}")
    
    def _get_capabilities(self) -> list[str]:
        """Return list of agent capabilities."""
        caps = ['snmp_get', 'snmp_walk', 'snmp_set', 'snmp_bulk_get']
        
        if self.cm_proxy:
            caps.append('cm_proxy')
        
        if self.tftp_ssh:
            caps.append('tftp_get')
        
        if self.config.cmts_ssh_enabled:
            caps.append('cmts_command')
        
        if self.config.cmts_snmp_direct:
            caps.append('cmts_snmp_direct')
            caps.append('cmts_get_modems')  # SNMP-based modem discovery
            caps.append('cmts_get_modem_info')
            caps.append('enrich_modems')
        
        caps.append('execute_pnm')
        
        # OFDM capture capabilities (requires PyPNM integration)
        caps.extend(['pnm_ofdm_channels', 'pnm_ofdm_capture', 'pnm_ofdm_rxmer'])
        
        return caps
    
    def _handle_command(self, ws, data: dict):
        """Handle incoming command from PyPNM Server."""
        request_id = data.get('request_id')
        command = data.get('command')
        params = data.get('params', {})
        
        self.logger.info(f"Received command: {request_id} - {command}")
        
        # Find handler
        handler = self.handlers.get(command)
        
        if handler:
            try:
                result = handler(params)
                response = {
                    'type': 'response',
                    'request_id': request_id,
                    'result': result
                }
                self.logger.info(f"Handler returned for {request_id}")
            except Exception as e:
                self.logger.exception(f"Command execution error: {e}")
                response = {
                    'type': 'error',
                    'request_id': request_id,
                    'error': str(e)
                }
        else:
            response = {
                'type': 'error',
                'request_id': request_id,
                'error': f'Unknown command: {command}'
            }
        
        self.logger.info(f"Sending response for {request_id}")
        ws.send(json.dumps(response))
        self.logger.info(f"Response sent for {request_id}")
    
    # ============== Command Handlers ==============
    
    def _handle_ping(self, params: dict) -> dict:
        """Handle ping/connectivity check."""
        target = params.get('target')
        
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '2', target],
            capture_output=True,
            text=True
        )
        
        return {
            'success': result.returncode == 0,
            'reachable': result.returncode == 0,
            'target': target,
            'output': result.stdout
        }
    
    def _handle_snmp_get(self, params: dict) -> dict:
        """Handle SNMP GET request via cm_proxy."""
        target_ip = params['target_ip']
        oid = params['oid']
        community = params.get('community', 'private')
        
        # Use cm_proxy if configured
        if self.config.cm_proxy_host:
            return self._query_modem_via_cm_proxy(target_ip, oid, community, walk=False)
        
        # Fallback to direct SNMP
        return self.snmp_executor.execute_snmp(
            command='snmpget',
            target_ip=target_ip,
            oid=oid,
            community=community,
            version=params.get('version', '2c'),
            timeout=params.get('timeout', 5),
            retries=params.get('retries', 1)
        )
    
    def _handle_snmp_walk(self, params: dict) -> dict:
        """Handle SNMP WALK request via cm_proxy."""
        target_ip = params['target_ip']
        oid = params['oid']
        community = params.get('community', 'private')
        
        # Use cm_proxy if configured
        if self.config.cm_proxy_host:
            return self._query_modem_via_cm_proxy(target_ip, oid, community, walk=True)
        
        # Fallback to direct SNMP
        return self.snmp_executor.execute_snmp(
            command='snmpwalk',
            target_ip=target_ip,
            oid=oid,
            community=community,
            version=params.get('version', '2c'),
            timeout=params.get('timeout', 5),
            retries=params.get('retries', 1)
        )
    
    def _handle_snmp_set(self, params: dict) -> dict:
        """Handle SNMP SET request via cm_proxy."""
        target_ip = params['target_ip']
        oid = params['oid']
        value = params['value']
        value_type = params.get('type', 'i')
        community = params.get('community', 'private')
        
        # Use cm_proxy if configured
        if self.config.cm_proxy_host:
            return self._set_modem_via_cm_proxy(target_ip, oid, value, value_type, community)
        
        # Fallback to direct SNMP (not typical for modems)
        oid_with_value = f"{oid} {value_type} {value}"
        return self.snmp_executor.execute_snmp(
            command='snmpset',
            target_ip=target_ip,
            oid=oid_with_value,
            community=community,
            version=params.get('version', '2c'),
            timeout=params.get('timeout', 5),
            retries=params.get('retries', 1)
        )
    
    def _handle_snmp_bulk_get(self, params: dict) -> dict:
        """Handle multiple SNMP GET requests."""
        oids = params.get('oids', [])
        target_ip = params['target_ip']
        community = params.get('community', 'private')
        version = params.get('version', '2c')
        
        results = {}
        for oid in oids:
            result = self.snmp_executor.execute_snmp(
                command='snmpget',
                target_ip=target_ip,
                oid=oid,
                community=community,
                version=version,
                timeout=params.get('timeout', 5),
                retries=params.get('retries', 1)
            )
            results[oid] = result
        
        return {
            'success': True,
            'results': results
        }
    
    def _handle_tftp_get(self, params: dict) -> dict:
        """Handle TFTP/PNM file retrieval via SSH to TFTP server."""
        if not self.tftp_ssh:
            return {'success': False, 'error': 'TFTP SSH not configured'}
        
        remote_path = params.get('path', '')
        filename = os.path.basename(remote_path)
        
        # Full path on TFTP server
        tftp_full_path = os.path.join(self.config.tftp_path, remote_path)
        
        try:
            # Read file via SSH
            exit_code, stdout, stderr = self.tftp_ssh.execute(
                f"cat '{tftp_full_path}'",
                timeout=60
            )
            
            if exit_code == 0:
                # File content retrieved
                content = stdout.encode() if isinstance(stdout, str) else stdout
                return {
                    'success': True,
                    'filename': filename,
                    'path': remote_path,
                    'size': len(content),
                    'content_base64': content.hex()
                }
            else:
                return {
                    'success': False,
                    'error': stderr or f'Failed to read file: exit code {exit_code}'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _handle_cmts_command(self, params: dict) -> dict:
        """Execute command on CMTS via SSH."""
        cmts_host = params.get('cmts_host')
        command = params.get('command')
        
        if not cmts_host or not command:
            return {'success': False, 'error': 'cmts_host and command required'}
        
        if not self.config.cmts_ssh_enabled:
            return {'success': False, 'error': 'CMTS SSH not enabled'}
        
        # Create temporary SSH executor for this CMTS
        cmts_ssh = SSHProxyExecutor(
            host=cmts_host,
            port=22,
            username=self.config.cmts_ssh_user,
            key_file=self.config.cmts_ssh_key
        )
        
        try:
            if not cmts_ssh.connect():
                return {'success': False, 'error': f'Failed to connect to CMTS {cmts_host}'}
            
            exit_code, stdout, stderr = cmts_ssh.execute(command, timeout=30)
            
            return {
                'success': exit_code == 0,
                'cmts_host': cmts_host,
                'command': command,
                'output': stdout,
                'error': stderr if exit_code != 0 else None
            }
        finally:
            cmts_ssh.close()
    
    def _handle_pnm_command(self, params: dict) -> dict:
        """Handle PyPNM-specific commands (trigger PNM tests via SNMP)."""
        pnm_type = params.get('pnm_type')
        target_ip = params.get('target_ip')
        community = params.get('community', 'private')
        
        # PNM OIDs for different tests
        pnm_oids = {
            'rxmer': '1.3.6.1.4.1.4491.2.1.27.1.3.1',
            'spectrum': '1.3.6.1.4.1.4491.2.1.27.1.3.2',
            'fec': '1.3.6.1.4.1.4491.2.1.27.1.3.3',
        }
        
        if pnm_type not in pnm_oids:
            return {'success': False, 'error': f'Unknown PNM type: {pnm_type}'}
        
        # This would trigger the actual PNM measurement via SNMP
        # For now, return a placeholder
        return {
            'success': True,
            'pnm_type': pnm_type,
            'message': f'PNM {pnm_type} triggered for {target_ip}'
        }
    
    def _get_cm_proxy_ssh(self):
        """Get or create a persistent SSH connection to cm_proxy."""
        if not hasattr(self, '_cm_proxy_ssh') or self._cm_proxy_ssh is None:
            if not self.config.cm_proxy_host:
                return None
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # Get key file path, expanding ~ to home directory
                key_file = None
                if self.config.cm_proxy_key:
                    key_file = os.path.expanduser(self.config.cm_proxy_key)
                    self.logger.debug(f"Using SSH key: {key_file}")
                
                ssh.connect(
                    self.config.cm_proxy_host,
                    username=self.config.cm_proxy_user or 'svdleer',
                    key_filename=key_file,
                    timeout=30
                )
                self._cm_proxy_ssh = ssh
                self.logger.info(f"Persistent SSH connection to {self.config.cm_proxy_host} established")
            except Exception as e:
                self.logger.error(f"Failed to connect to cm_proxy: {e}")
                self._cm_proxy_ssh = None
        
        # Check if connection is still alive
        if self._cm_proxy_ssh:
            try:
                transport = self._cm_proxy_ssh.get_transport()
                if transport is None or not transport.is_active():
                    self.logger.warning("SSH connection lost, reconnecting...")
                    self._cm_proxy_ssh = None
                    return self._get_cm_proxy_ssh()  # Reconnect
            except:
                self._cm_proxy_ssh = None
                return self._get_cm_proxy_ssh()  # Reconnect
        
        return self._cm_proxy_ssh
    
    def _query_modem_via_cm_proxy(self, modem_ip: str, oid: str, community: str, walk: bool = False) -> dict:
        """Query a modem via cm_proxy using persistent SSH connection."""
        ssh = self._get_cm_proxy_ssh()
        if not ssh:
            return {'success': False, 'error': 'cm_proxy not configured or connection failed'}
        
        try:
            cmd = 'snmpwalk' if walk else 'snmpget'
            snmp_cmd = f"{cmd} -v2c -c {community} -t 5 -r 1 {modem_ip} {oid}"
            
            stdin, stdout, stderr = ssh.exec_command(snmp_cmd, timeout=30)
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            return {
                'success': 'Timeout' not in error and 'No Response' not in error,
                'output': output,
                'error': error if error else None
            }
        except Exception as e:
            # Connection might have died, clear it so next call reconnects
            self._cm_proxy_ssh = None
            return {'success': False, 'error': str(e)}
    
    def _set_modem_via_cm_proxy(self, modem_ip: str, oid: str, value: str, value_type: str, community: str) -> dict:
        """Set an SNMP value on a modem via cm_proxy using persistent SSH connection."""
        ssh = self._get_cm_proxy_ssh()
        if not ssh:
            return {'success': False, 'error': 'cm_proxy not configured or connection failed'}
        
        try:
            snmp_cmd = f"snmpset -v2c -c {community} -t 5 -r 1 {modem_ip} {oid} {value_type} {value}"
            
            stdin, stdout, stderr = ssh.exec_command(snmp_cmd, timeout=30)
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            return {
                'success': 'Timeout' not in error and 'No Response' not in error and error == '',
                'output': output,
                'error': error if error else None
            }
        except Exception as e:
            # Connection might have died, clear it so next call reconnects
            self._cm_proxy_ssh = None
            return {'success': False, 'error': str(e)}
    
    def _batch_query_modem(self, modem_ip: str, oids: dict, community: str) -> dict:
        """Query multiple OIDs using EXACT same paramiko method as _enrich_modems_parallel."""
        if not self.config.cm_proxy_host:
            return {'success': False, 'error': 'cm_proxy not configured'}
        
        try:
            # Use EXACT same SSH connection as enrichment
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.config.cm_proxy_host, 
                username=self.config.cm_proxy_user or 'svdleer',
                timeout=30
            )
            
            self.logger.info(f"SSH connected to {self.config.cm_proxy_host} for modem query")
            
            # Build batch command with section markers
            cmds = []
            for name, oid in oids.items():
                cmds.append(f"echo '=={name}==' ; snmpwalk -v2c -c {community} -t 10 -r 0 {modem_ip} {oid} 2>&1")
            
            batch_cmd = ' ; '.join(cmds)
            
            self.logger.info(f"Executing batch SNMP query with community={community}")
            
            # Execute command - EXACT same as enrichment
            stdin, stdout, stderr = ssh.exec_command(batch_cmd, timeout=120)
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            ssh.close()
            
            self.logger.info(f"SSH command completed, got {len(output)} bytes stdout")
            
            # Parse results by section markers
            results = {}
            current_section = None
            current_lines = []
            
            for line in output.split('\n'):
                if line.startswith('==') and line.endswith('=='):
                    if current_section:
                        results[current_section] = '\n'.join(current_lines)
                    current_section = line.strip('=')
                    current_lines = []
                elif current_section:
                    current_lines.append(line)
            
            if current_section:
                results[current_section] = '\n'.join(current_lines)
            
            return {
                'success': True,
                'results': results,
                'raw_output': output
            }
            
        except Exception as e:
            self.logger.exception(f"Batch query failed: {e}")
            return {
                'success': False,
                'error': f'SNMP query failed: {str(e)}'
            }
    
    def _handle_pnm_rxmer(self, params: dict) -> dict:
        """Get RxMER (Receive Modulation Error Ratio) data from modem."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting RxMER for modem {modem_ip}")
        
        # DOCSIS 3.1 RxMER OIDs (docsIf31CmDsOfdmChannelPowerTable)
        OID_OFDM_POWER = '1.3.6.1.4.1.4491.2.1.28.1.5'  # docsIf31CmDsOfdmChannelPowerTable
        OID_DS_MER = '1.3.6.1.4.1.4491.2.1.20.1.24.1.1'  # docsIf3CmStatusUsTxPower (for reference)
        
        result = self._query_modem_via_cm_proxy(modem_ip, OID_OFDM_POWER, community, walk=True)
        
        if not result.get('success'):
            return {'success': False, 'error': result.get('error', 'SNMP query failed')}
        
        # Parse RxMER values
        measurements = []
        for line in result.get('output', '').split('\n'):
            if '=' in line and ('INTEGER' in line or 'Gauge' in line):
                try:
                    parts = line.split('=')
                    oid_part = parts[0].strip()
                    value_part = parts[1].strip()
                    
                    # Extract channel index from OID
                    idx = oid_part.split('.')[-1]
                    
                    # Extract value
                    val = ''.join(c for c in value_part.split(':')[-1] if c.isdigit() or c == '-')
                    if val:
                        measurements.append({
                            'channel_id': int(idx),
                            'mer_db': float(val) / 10 if abs(int(val)) > 100 else float(val)
                        })
                except:
                    pass
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'measurements': measurements,
            'average_mer_db': sum(m['mer_db'] for m in measurements) / len(measurements) if measurements else 0
        }
    
    def _handle_pnm_spectrum(self, params: dict) -> dict:
        """Get spectrum analysis data from modem."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting spectrum for modem {modem_ip}")
        
        # DOCSIS CM spectrum OIDs
        OID_DS_FREQ = '1.3.6.1.2.1.10.127.1.1.1.1.2'  # docsIfDownChannelFrequency
        OID_DS_POWER = '1.3.6.1.2.1.10.127.1.1.1.1.6'  # docsIfDownChannelPower
        OID_US_FREQ = '1.3.6.1.2.1.10.127.1.1.2.1.2'  # docsIfUpChannelFrequency
        OID_US_POWER = '1.3.6.1.4.1.4491.2.1.20.1.2.1.1'  # docsIf3CmStatusUsTxPower
        
        ds_freq_result = self._query_modem_via_cm_proxy(modem_ip, OID_DS_FREQ, community, walk=True)
        ds_power_result = self._query_modem_via_cm_proxy(modem_ip, OID_DS_POWER, community, walk=True)
        us_power_result = self._query_modem_via_cm_proxy(modem_ip, OID_US_POWER, community, walk=True)
        
        ds_channels = []
        us_channels = []
        
        # Parse downstream
        freq_map = {}
        for line in ds_freq_result.get('output', '').split('\n'):
            if '=' in line:
                try:
                    idx = line.split('=')[0].strip().split('.')[-1]
                    val = ''.join(c for c in line.split('=')[1] if c.isdigit())
                    if val:
                        freq_map[idx] = int(val)
                except:
                    pass
        
        for line in ds_power_result.get('output', '').split('\n'):
            if '=' in line:
                try:
                    idx = line.split('=')[0].strip().split('.')[-1]
                    val = ''.join(c for c in line.split('=')[1] if c.isdigit() or c == '-')
                    if val and idx in freq_map:
                        ds_channels.append({
                            'channel_id': int(idx),
                            'frequency_hz': freq_map[idx],
                            'power_dbmv': float(val) / 10
                        })
                except:
                    pass
        
        # Parse upstream power
        for line in us_power_result.get('output', '').split('\n'):
            if '=' in line:
                try:
                    idx = line.split('=')[0].strip().split('.')[-1]
                    val = ''.join(c for c in line.split('=')[1] if c.isdigit() or c == '-')
                    if val:
                        us_channels.append({
                            'channel_id': int(idx),
                            'power_dbmv': float(val) / 10
                        })
                except:
                    pass
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'downstream_channels': ds_channels,
            'upstream_channels': us_channels
        }
    
    def _handle_pnm_fec(self, params: dict) -> dict:
        """Get FEC (Forward Error Correction) statistics from modem."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting FEC stats for modem {modem_ip}")
        
        # DOCSIS FEC OIDs
        OID_UNERRORED = '1.3.6.1.2.1.10.127.1.1.4.1.2'  # docsIfSigQUnerroreds
        OID_CORRECTED = '1.3.6.1.2.1.10.127.1.1.4.1.3'  # docsIfSigQCorrecteds
        OID_UNCORRECTABLE = '1.3.6.1.2.1.10.127.1.1.4.1.4'  # docsIfSigQUncorrectables
        OID_SNR = '1.3.6.1.2.1.10.127.1.1.4.1.5'  # docsIfSigQSignalNoise
        
        unerrored = self._query_modem_via_cm_proxy(modem_ip, OID_UNERRORED, community, walk=True)
        corrected = self._query_modem_via_cm_proxy(modem_ip, OID_CORRECTED, community, walk=True)
        uncorrectable = self._query_modem_via_cm_proxy(modem_ip, OID_UNCORRECTABLE, community, walk=True)
        snr = self._query_modem_via_cm_proxy(modem_ip, OID_SNR, community, walk=True)
        
        def parse_values(result):
            values = {}
            for line in result.get('output', '').split('\n'):
                if '=' in line:
                    try:
                        idx = line.split('=')[0].strip().split('.')[-1]
                        val = ''.join(c for c in line.split('=')[1] if c.isdigit())
                        if val:
                            values[idx] = int(val)
                    except:
                        pass
            return values
        
        unerrored_map = parse_values(unerrored)
        corrected_map = parse_values(corrected)
        uncorrectable_map = parse_values(uncorrectable)
        snr_map = parse_values(snr)
        
        channels = []
        for idx in unerrored_map:
            total = unerrored_map.get(idx, 0) + corrected_map.get(idx, 0) + uncorrectable_map.get(idx, 0)
            channels.append({
                'channel_id': int(idx),
                'unerrored': unerrored_map.get(idx, 0),
                'corrected': corrected_map.get(idx, 0),
                'uncorrectable': uncorrectable_map.get(idx, 0),
                'total_codewords': total,
                'snr_db': snr_map.get(idx, 0) / 10 if idx in snr_map else 0
            })
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'channels': channels,
            'total_uncorrectable': sum(c['uncorrectable'] for c in channels),
            'total_corrected': sum(c['corrected'] for c in channels)
        }
    
    def _handle_pnm_pre_eq(self, params: dict) -> dict:
        """Get pre-equalization coefficients from modem."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting pre-eq coefficients for modem {modem_ip}")
        
        # DOCSIS Pre-equalization OID
        OID_PRE_EQ = '1.3.6.1.4.1.4491.2.1.20.1.2.1.5'  # docsIf3CmStatusUsEqData
        
        result = self._query_modem_via_cm_proxy(modem_ip, OID_PRE_EQ, community, walk=True)
        
        if not result.get('success'):
            return {'success': False, 'error': result.get('error', 'SNMP query failed')}
        
        coefficients = []
        for line in result.get('output', '').split('\n'):
            if '=' in line and 'Hex-STRING' in line:
                try:
                    idx = line.split('=')[0].strip().split('.')[-1]
                    hex_data = line.split('Hex-STRING:')[-1].strip()
                    coefficients.append({
                        'channel_id': int(idx),
                        'hex_data': hex_data,
                        'length': len(hex_data.replace(' ', '')) // 2
                    })
                except:
                    pass
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'coefficients': coefficients
        }
    
    def _handle_pnm_channel_info(self, params: dict) -> dict:
        """Get comprehensive channel info (DS/US power, frequency, modulation).
        
        Requires cm_proxy configuration with SSH tunnel or socat to reach modem IPs.
        Modems must be reachable via SNMP through the configured proxy.
        """
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting channel info for modem {modem_ip} via cm_proxy, community={community}")
        
        # Check if cm_proxy is configured
        if not self.config.cm_proxy_host:
            return {'success': False, 'error': 'cm_proxy not configured in agent_config.json'}
        
        self.logger.info(f"cm_proxy config: host={self.config.cm_proxy_host}, user={self.config.cm_proxy_user}")
        
        # Define all OIDs to query
        oids = {
            'ds_freq': '1.3.6.1.2.1.10.127.1.1.1.1.2',   # docsIfDownChannelFrequency
            'ds_power': '1.3.6.1.2.1.10.127.1.1.1.1.6',  # docsIfDownChannelPower
            'ds_snr': '1.3.6.1.2.1.10.127.1.1.4.1.5',    # docsIfSigQSignalNoise
            'us_power': '1.3.6.1.4.1.4491.2.1.20.1.2.1.1', # docsIf3CmStatusUsTxPower
        }
        
        self.logger.info(f"Calling _batch_query_modem for {modem_ip}")
        
        # Batch query all OIDs in single SSH command
        batch_result = self._batch_query_modem(modem_ip, oids, community)
        
        self.logger.info(f"_batch_query_modem returned: success={batch_result.get('success')}")
        
        if not batch_result.get('success'):
            return {'success': False, 'error': batch_result.get('error', 'Batch query failed')}
        
        results = batch_result.get('results', {})
        
        def parse_int_values(output_str, divisor=1):
            values = {}
            for line in output_str.split('\n'):
                if '=' in line:
                    try:
                        idx = line.split('=')[0].strip().split('.')[-1]
                        val = ''.join(c for c in line.split('=')[1] if c.isdigit() or c == '-')
                        if val:
                            values[idx] = int(val) / divisor
                    except:
                        pass
            return values
        
        ds_freq_map = parse_int_values(results.get('ds_freq', ''))
        ds_power_map = parse_int_values(results.get('ds_power', ''), 10)
        ds_snr_map = parse_int_values(results.get('ds_snr', ''), 10)
        us_power_map = parse_int_values(results.get('us_power', ''), 10)
        
        downstream = []
        for idx in ds_freq_map:
            downstream.append({
                'channel_id': int(idx),
                'frequency_mhz': ds_freq_map[idx] / 1000000,
                'power_dbmv': ds_power_map.get(idx, 0),
                'snr_db': ds_snr_map.get(idx, 0)
            })
        
        upstream = []
        for idx in us_power_map:
            upstream.append({
                'channel_id': int(idx),
                'power_dbmv': us_power_map[idx]
            })
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'downstream': sorted(downstream, key=lambda x: x['channel_id']),
            'upstream': sorted(upstream, key=lambda x: x['channel_id'])
        }
    
    def _handle_pnm_event_log(self, params: dict) -> dict:
        """Get event log from modem."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        mac_address = params.get('mac_address')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        self.logger.info(f"Getting event log for modem {modem_ip}")
        
        # DOCSIS Event Log OIDs
        OID_EVENT_TEXT = '1.3.6.1.2.1.69.1.5.8.1.7'  # docsDevEvText
        OID_EVENT_TIME = '1.3.6.1.2.1.69.1.5.8.1.6'  # docsDevEvLastTime
        OID_EVENT_LEVEL = '1.3.6.1.2.1.69.1.5.8.1.4'  # docsDevEvLevel
        
        text_result = self._query_modem_via_cm_proxy(modem_ip, OID_EVENT_TEXT, community, walk=True)
        
        events = []
        for line in text_result.get('output', '').split('\n'):
            if '=' in line and 'STRING' in line:
                try:
                    idx = line.split('=')[0].strip().split('.')[-1]
                    text = line.split('STRING:')[-1].strip().strip('"')
                    events.append({
                        'id': int(idx),
                        'text': text
                    })
                except:
                    pass
        
        return {
            'success': True,
            'mac_address': mac_address,
            'modem_ip': modem_ip,
            'timestamp': datetime.now().isoformat(),
            'events': events[-50:],  # Last 50 events
            'total_events': len(events)
        }

    def _handle_pnm_ofdm_channels(self, params: dict) -> dict:
        """Get list of OFDM channels via cm_proxy SNMP."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        if not self.config.cm_proxy_host:
            return {'success': False, 'error': 'cm_proxy not configured'}
        
        try:
            # DOCSIS 3.1 OFDM channel OIDs
            OID_OFDM_CHAN_ID = '1.3.6.1.4.1.4491.2.1.28.1.9.1.1'  # docsIf31CmDsOfdmChanChannelId
            
            self.logger.info(f"Querying OFDM channels for {modem_ip}")
            result = self._query_modem_via_cm_proxy(modem_ip, OID_OFDM_CHAN_ID, community, walk=True)
            self.logger.info(f"OFDM query result: success={result.get('success')}")
            
            if not result.get('success'):
                # Not an error - modem might be DOCSIS 3.0 only
                return {'success': True, 'channels': []}
            
            channels = []
            for line in result.get('output', '').split('\n'):
                if '=' in line and 'INTEGER' in line:
                    try:
                        parts = line.split('=')[0].strip().split('.')
                        idx = int(parts[-1])
                        chan_id = int(line.split('INTEGER:')[-1].strip())
                        channels.append({
                            "index": idx,
                            "channel_id": chan_id
                        })
                    except:
                        pass
            
            return {"success": True, "channels": channels}
        except Exception as e:
            self.logger.error(f"OFDM channels error: {e}")
            return {'success': False, 'error': str(e)}

    def _handle_pnm_ofdm_capture(self, params: dict) -> dict:
        """Trigger OFDM RxMER capture via cm_proxy SNMP SET."""
        modem_ip = params.get('modem_ip')
        ofdm_channel = params.get('ofdm_channel', 0)
        filename = params.get('filename', 'rxmer_capture')
        community = params.get('community', 'm0d3m1nf0')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        if not self.config.cm_proxy_host:
            return {'success': False, 'error': 'cm_proxy not configured'}
        
        try:
            # Correct OIDs from PyPNM compiled_oids.py
            OID_RXMER_FILENAME = f'1.3.6.1.4.1.4491.2.1.27.1.2.5.1.8.{ofdm_channel}'
            OID_RXMER_ENABLE = f'1.3.6.1.4.1.4491.2.1.27.1.2.5.1.1.{ofdm_channel}'
            
            # Set filename
            self.logger.info(f"Setting OFDM capture filename for {modem_ip} channel {ofdm_channel}")
            result = self._set_modem_via_cm_proxy(modem_ip, OID_RXMER_FILENAME, filename, 's', community)
            self.logger.info(f"Filename set result: success={result.get('success')}")
            if not result.get('success'):
                return {'success': False, 'error': f"Failed to set filename: {result.get('error')}"}
            
            # Trigger capture (enable = 1)
            self.logger.info(f"Triggering OFDM capture for {modem_ip} channel {ofdm_channel}")
            result = self._set_modem_via_cm_proxy(modem_ip, OID_RXMER_ENABLE, '1', 'i', community)
            self.logger.info(f"Trigger result: success={result.get('success')}")
            if not result.get('success'):
                return {'success': False, 'error': f"Failed to trigger capture: {result.get('error')}"}
            
            return {'success': True, 'message': 'OFDM capture triggered', 'filename': filename}
        except Exception as e:
            self.logger.error(f"OFDM capture error: {e}")
            return {'success': False, 'error': str(e)}
    def _handle_pnm_ofdm_rxmer(self, params: dict) -> dict:
        """Get OFDM RxMER data via cm_proxy SNMP walk."""
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        
        if not modem_ip:
            return {'success': False, 'error': 'modem_ip required'}
        
        if not self.config.cm_proxy_host:
            return {'success': False, 'error': 'cm_proxy not configured'}
        
        try:
            # docsPnmCmDsOfdmRxMerMean OID (MER values per subcarrier)
            OID_RXMER_MEAN = '1.3.6.1.4.1.4491.2.1.27.1.2.5.1.3'
            
            result = self._query_modem_via_cm_proxy(modem_ip, OID_RXMER_MEAN, community, walk=True)
            
            if not result.get('success'):
                return {'success': False, 'error': 'No RxMER data available'}
            
            subcarriers = []
            mer_values = []
            
            for line in result.get('output', '').split('\n'):
                if '=' in line and 'INTEGER' in line:
                    try:
                        parts = line.split('=')[0].strip().split('.')
                        subcarrier_idx = int(parts[-1])
                        mer_raw = int(line.split('INTEGER:')[-1].strip())
                        mer_db = mer_raw / 10.0  # Convert to dB
                        
                        subcarriers.append(subcarrier_idx)
                        mer_values.append(mer_db)
                    except:
                        pass
            
            if not subcarriers:
                return {'success': False, 'error': 'No RxMER data available'}
            
            return {
                'success': True,
                'data': {
                    'mac_address': params.get('mac_address'),
                    'subcarriers': subcarriers,
                    'mer_values': mer_values
                }
            }
        except Exception as e:
            self.logger.error(f"OFDM RxMER error: {e}")
            return {'success': False, 'error': str(e)}

    def _handle_cmts_get_modems(self, params: dict) -> dict:
        """
        Get list of cable modems from a CMTS via SNMP.
        Uses parallel queries for MAC, IP, Status. Supports Redis caching.
        
        DOCSIS CMTS MIBs used:
        - docsIfCmtsCmStatusMacAddress: 1.3.6.1.2.1.10.127.1.3.3.1.2
        - docsIfCmtsCmStatusIpAddress: 1.3.6.1.2.1.10.127.1.3.3.1.3
        - docsIfCmtsCmStatusValue (status): 1.3.6.1.2.1.10.127.1.3.3.1.9
        - docsIf3CmtsCmRegStatusMdIfIndex (interface): 1.3.6.1.4.1.4491.2.1.20.1.3.1.5
        """
        cmts_ip = params.get('cmts_ip')
        community = params.get('community', 'Z1gg0@LL')
        limit = params.get('limit', 10000)  # Increased limit
        use_bulk = params.get('use_bulk', True)
        use_cache = params.get('use_cache', True)
        # CMTS queries go DIRECT - don't auto-enable equalizer just because it's configured
        # Equalizer/cm_proxy is for modem enrichment, not CMTS queries
        use_equalizer = params.get('use_equalizer', False)
        
        if not cmts_ip:
            return {'success': False, 'error': 'cmts_ip required'}
        
        # Check Redis cache first
        cache_key = f"cmts_modems:{cmts_ip}"
        if use_cache and redis and self.config.redis_host:
            try:
                r = redis.Redis(host=self.config.redis_host, port=self.config.redis_port, decode_responses=True)
                cached = r.get(cache_key)
                if cached:
                    self.logger.info(f"Returning cached modems for {cmts_ip}")
                    return json.loads(cached)
            except Exception as e:
                self.logger.warning(f"Redis cache error: {e}")
        
        self.logger.info(f"Getting cable modems from CMTS {cmts_ip}")
        
        # DOCSIS 3.0 MIB OIDs - use docsIf3 table for MAC and DOCSIS version
        OID_D3_MAC = '1.3.6.1.4.1.4491.2.1.20.1.3.1.2'  # docsIf3CmtsCmRegStatusMacAddr
        
        # Old DOCSIS table for IP and Status (has different index, correlate by MAC)
        OID_OLD_MAC = '1.3.6.1.2.1.10.127.1.3.3.1.2'   # docsIfCmtsCmStatusMacAddress
        OID_OLD_IP = '1.3.6.1.2.1.10.127.1.3.3.1.3'    # docsIfCmtsCmStatusIpAddress
        OID_OLD_STATUS = '1.3.6.1.2.1.10.127.1.3.3.1.9'  # docsIfCmtsCmStatusValue
        
        # DOCSIS 3.1 MIB - MaxUsableDsFreq: if > 0, modem is DOCSIS 3.1
        OID_D31_MAX_DS_FREQ = '1.3.6.1.4.1.4491.2.1.28.1.3.1.7'  # docsIf31CmtsCmRegStatusMaxUsableDsFreq
        
        snmp_command = 'snmpbulkwalk' if use_bulk else 'snmpwalk'
        self.logger.info(f"Using {snmp_command} with community '{community}' (parallel queries)")
        
        # Function to execute SNMP query (used for parallel execution)
        # For CMTS queries, use direct SNMP (not via cm_proxy which is for modems)
        def query_oid(oid_name, oid):
            if use_equalizer and self.config.equalizer_host:
                return self._snmp_via_ssh(
                    ssh_host=self.config.equalizer_host,
                    ssh_user=self.config.equalizer_user or 'svdleer',
                    target_ip=cmts_ip,
                    oid=oid,
                    community=community,
                    command=snmp_command
                )
            else:
                # Use direct SNMP executor for CMTS (not via cm_proxy)
                return self.snmp_executor_direct.execute_snmp(
                    command=snmp_command,
                    target_ip=cmts_ip,
                    oid=oid,
                    community=community,
                    timeout=120,
                    retries=2
                )
        
        try:
            # Parallel SNMP queries
            results = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(query_oid, 'mac', OID_D3_MAC): 'mac',
                    executor.submit(query_oid, 'd31_freq', OID_D31_MAX_DS_FREQ): 'd31_freq',
                    executor.submit(query_oid, 'old_mac', OID_OLD_MAC): 'old_mac',
                    executor.submit(query_oid, 'old_ip', OID_OLD_IP): 'old_ip',
                    executor.submit(query_oid, 'old_status', OID_OLD_STATUS): 'old_status',
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        results[name] = future.result()
                    except Exception as e:
                        self.logger.error(f"Query {name} failed: {e}")
                        results[name] = {'success': False, 'error': str(e)}
            
            mac_result = results.get('mac', {})
            if not mac_result.get('success'):
                return {
                    'success': False,
                    'error': f"SNMP MAC walk failed: {mac_result.get('error')}",
                    'cmts_ip': cmts_ip
                }
            
            # Parse MAC addresses from docsIf3 table
            mac_lines = mac_result.get('output', '').strip().split('\n')
            mac_map = {}  # index -> mac
            
            for line in mac_lines[:limit]:
                if '=' in line and ('Hex-STRING' in line or 'STRING' in line):
                    try:
                        parts = line.split('=', 1)
                        oid_part = parts[0].strip()
                        value_part = parts[1].strip()
                        
                        # Extract index from OID
                        index = oid_part.split('.')[-1]
                        
                        # Extract MAC from Hex-STRING
                        if 'Hex-STRING' in value_part:
                            hex_mac = value_part.split('Hex-STRING:')[-1].strip()
                            mac_bytes = hex_mac.replace(' ', '').replace(':', '')
                            if len(mac_bytes) >= 12:
                                mac = ':'.join([mac_bytes[i:i+2] for i in range(0, 12, 2)]).lower()
                                mac_map[index] = mac
                    except Exception as e:
                        self.logger.debug(f"Failed to parse MAC line: {line} - {e}")
            
            self.logger.info(f"Parsed {len(mac_map)} MAC addresses from docsIf3 table")
            
            # Parse old table MAC -> IP mapping (for correlation)
            old_mac_result = results.get('old_mac', {})
            old_ip_result = results.get('old_ip', {})
            old_mac_map = {}  # old_index -> mac
            old_ip_map = {}   # old_index -> ip
            
            # Parse old MAC addresses
            if old_mac_result.get('success'):
                for line in old_mac_result.get('output', '').split('\n'):
                    if '=' in line and ('Hex-STRING' in line or 'STRING' in line):
                        try:
                            parts = line.split('=', 1)
                            old_index = parts[0].strip().split('.')[-1]
                            value = parts[1].strip()
                            if 'Hex-STRING' in value:
                                hex_mac = value.split('Hex-STRING:')[-1].strip()
                                mac_bytes = hex_mac.replace(' ', '').replace(':', '')
                                if len(mac_bytes) >= 12:
                                    mac = ':'.join([mac_bytes[i:i+2] for i in range(0, 12, 2)]).lower()
                                    old_mac_map[old_index] = mac
                        except:
                            pass
            
            # Parse old IP addresses
            if old_ip_result.get('success'):
                for line in old_ip_result.get('output', '').split('\n'):
                    if '=' in line and ('IpAddress' in line or 'Network Address' in line):
                        try:
                            parts = line.split('=', 1)
                            old_index = parts[0].strip().split('.')[-1]
                            ip = parts[1].strip().split(':')[-1].strip()
                            old_ip_map[old_index] = ip
                        except:
                            pass
            
            # Create MAC -> IP lookup from old table
            mac_to_ip = {}  # mac -> ip
            for old_index, mac in old_mac_map.items():
                if old_index in old_ip_map:
                    mac_to_ip[mac] = old_ip_map[old_index]
            
            self.logger.info(f"Correlated {len(mac_to_ip)} IP addresses from old table")
            
            # Parse old status values and create MAC -> status lookup
            old_status_result = results.get('old_status', {})
            old_status_map = {}  # old_index -> status
            if old_status_result.get('success'):
                for line in old_status_result.get('output', '').split('\n'):
                    if '=' in line and 'INTEGER' in line:
                        try:
                            parts = line.split('=', 1)
                            old_index = parts[0].strip().split('.')[-1]
                            status_val = parts[1].strip().split(':')[-1].strip()
                            old_status_map[old_index] = int(status_val) if status_val.isdigit() else 0
                        except:
                            pass
            
            # Create MAC -> status lookup
            mac_to_status = {}  # mac -> status_code
            for old_index, mac in old_mac_map.items():
                if old_index in old_status_map:
                    mac_to_status[mac] = old_status_map[old_index]
            
            self.logger.info(f"Correlated {len(mac_to_status)} status values from old table")
            
            # Parse DOCSIS 3.1 detection from MaxUsableDsFreq
            # If freq > 0, modem is DOCSIS 3.1, else DOCSIS 3.0
            d31_freq_result = results.get('d31_freq', {})
            d31_map = {}  # index -> is_docsis31 (bool)
            if d31_freq_result.get('success'):
                for line in d31_freq_result.get('output', '').split('\n'):
                    if '=' in line:
                        try:
                            parts = line.split('=', 1)
                            index = parts[0].strip().split('.')[-1]
                            value = parts[1].strip()
                            # Parse integer value (Unsigned32, Gauge32, INTEGER, or plain number)
                            freq = 0
                            tokens = value.replace(':', ' ').split()
                            for tok in reversed(tokens):
                                try:
                                    freq = int(tok)
                                    break
                                except ValueError:
                                    continue
                            # freq > 0 means DOCSIS 3.1
                            d31_map[index] = freq > 0
                        except:
                            pass
            
            d31_count = sum(1 for v in d31_map.values() if v)
            d30_count = sum(1 for v in d31_map.values() if not v)
            self.logger.info(f"DOCSIS version detection: {d31_count} x 3.1, {d30_count} x 3.0")
            
            # Build modem list
            modems = []
            for index, mac in mac_map.items():
                is_d31 = d31_map.get(index, False)
                docsis_version = 'DOCSIS 3.1' if is_d31 else 'DOCSIS 3.0'
                status_code = mac_to_status.get(mac, 0)
                
                modem = {
                    'mac_address': mac,
                    'ip_address': mac_to_ip.get(mac, 'N/A'),
                    'status_code': status_code,
                    'status': self._decode_cm_status(status_code),  # Use old decoder
                    'cmts_index': index,
                    'vendor': self._get_vendor_from_mac(mac),
                    'docsis_version': docsis_version,
                }
                modems.append(modem)
            
            # Optionally query modems via hop-access for sysDescr (model info)
            enrich_modems = params.get('enrich_modems', False)
            if enrich_modems and self.cm_proxy:
                self.logger.info(f"Enriching {len(modems)} modems via cm_proxy...")
                modems = self._enrich_modems_parallel(modems, params.get('modem_community', 'm0d3m1nf0'))
            
            result = {
                'success': True,
                'cmts_ip': cmts_ip,
                'count': len(modems),
                'modems': modems
            }
            
            # Cache result in Redis
            if use_cache and redis and self.config.redis_host:
                try:
                    r = redis.Redis(host=self.config.redis_host, port=self.config.redis_port, decode_responses=True)
                    r.setex(cache_key, self.config.redis_ttl, json.dumps(result))
                    self.logger.info(f"Cached {len(modems)} modems for {cmts_ip} (TTL: {self.config.redis_ttl}s)")
                except Exception as e:
                    self.logger.warning(f"Redis cache set error: {e}")
            
            return result
            
        except Exception as e:
            self.logger.exception(f"Failed to get modems from CMTS: {e}")
            return {
                'success': False,
                'error': str(e),
                'cmts_ip': cmts_ip
            }
    
    def _handle_enrich_modems(self, params: dict) -> dict:
        """
        Enrich modems with vendor/model/firmware info via cm_proxy (hop-access).
        This runs in background after initial modem list is returned.
        """
        modems = params.get('modems', [])
        modem_community = params.get('modem_community', 'm0d3m1nf0')
        
        if not self.config.cm_proxy_host:
            self.logger.error("cm_proxy_host not configured!")
            return {
                'success': False,
                'error': 'cm_proxy not configured for modem enrichment'
            }
        
        # Log some stats about incoming modems
        status_counts = {}
        for m in modems:
            s = m.get('status', 'unknown')
            status_counts[s] = status_counts.get(s, 0) + 1
        self.logger.info(f"Enrichment request: {len(modems)} modems, status breakdown: {status_counts}")
        
        try:
            enriched = self._enrich_modems_parallel(modems, modem_community, max_workers=50)
            
            # Count how many were enriched
            enriched_count = sum(1 for m in enriched if m.get('model') and m.get('model') not in ['N/A', 'Unknown'])
            self.logger.info(f"Enrichment complete: {enriched_count}/{len(enriched)} modems have model info")
            
            return {
                'success': True,
                'modems': enriched,
                'enriched_count': enriched_count,
                'total_count': len(enriched)
            }
        except Exception as e:
            self.logger.exception(f"Failed to enrich modems: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _enrich_modems_parallel(self, modems: list, modem_community: str = 'm0d3m1nf0', max_workers: int = 20) -> list:
        """
        Query each modem via cm_proxy (hop-access) to get sysDescr for model info.
        Uses batch SSH with parallel xargs for efficiency.
        """
        OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'  # sysDescr
        
        # Query modems with valid IPs (any status that indicates online)
        online_statuses = {'operational', 'registrationComplete', 'ipComplete', 'online'}
        online_modems = [m for m in modems 
                         if m.get('ip_address') and m.get('ip_address') != 'N/A' 
                         and m.get('status') in online_statuses][:200]
        
        self.logger.info(f"Enrichment: {len(online_modems)} modems with valid IP (from {len(modems)} total)")
        
        if not online_modems:
            self.logger.warning("No online modems to enrich")
            return modems
        
        if not paramiko:
            self.logger.error("paramiko not installed")
            return modems
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.config.cm_proxy_host, 
                username=self.config.cm_proxy_user or 'svdleer',
                timeout=30
            )
            self.logger.info(f"SSH connected to {self.config.cm_proxy_host} for batch modem enrichment")
            
            # Build list of IPs
            ip_list = [m.get('ip_address') for m in online_modems]
            ip_string = '\\n'.join(ip_list)
            
            # Batch query using xargs with parallel execution
            # Output format: IP|sysDescr
            batch_cmd = f'''echo -e "{ip_string}" | xargs -I{{}} -P{max_workers} sh -c 'result=$(snmpget -v2c -c {modem_community} -t 2 -r 0 {{}} {OID_SYS_DESCR} 2>/dev/null | grep STRING); [ -n "$result" ] && echo "{{}}|$result"' '''
            
            self.logger.info(f"Running batch SNMP query for {len(ip_list)} modems with {max_workers} parallel workers")
            
            stdin, stdout, stderr = ssh.exec_command(batch_cmd, timeout=120)
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            ssh.close()
            
            # Parse results
            results = {}
            for line in output.strip().split('\n'):
                if '|' in line and 'STRING:' in line:
                    parts = line.split('|', 1)
                    if len(parts) == 2:
                        ip = parts[0].strip()
                        sys_descr = parts[1].split('STRING:')[-1].strip().strip('"')
                        results[ip] = sys_descr
            
            self.logger.info(f"Batch query returned {len(results)} results")
            
            # Apply results to modems
            enriched_count = 0
            for modem in online_modems:
                ip = modem.get('ip_address')
                if ip in results:
                    model_info = self._parse_sys_descr(results[ip])
                    modem['model'] = model_info.get('model', 'Unknown')
                    modem['software_version'] = model_info.get('software', '')
                    if model_info.get('vendor'):
                        modem['vendor'] = model_info.get('vendor')
                    enriched_count += 1
            
            self.logger.info(f"Enrichment done: {enriched_count}/{len(online_modems)} modems enriched")
            
        except Exception as e:
            self.logger.exception(f"Batch enrichment failed: {e}")
        
        # Merge enriched modems back
        enriched_map = {m['mac_address']: m for m in online_modems}
        for modem in modems:
            if modem['mac_address'] in enriched_map:
                modem.update(enriched_map[modem['mac_address']])
        
        return modems
    
    def _parse_sys_descr(self, sys_descr: str) -> dict:
        """Parse sysDescr to extract vendor, model, and software version."""
        result = {}
        import re
        
        # Check for structured format: <<KEY: value; KEY: value>>
        # Example: "FAST3896 Wireless Voice Gateway <<HW_REV: 1.2; VENDOR: SAGEMCOM; SW_REV: LG-RDK_11.10.26; MODEL: F3896LG>>"
        structured_match = re.search(r'<<(.+?)>>', sys_descr)
        if structured_match:
            fields = structured_match.group(1)
            for pair in fields.split(';'):
                if ':' in pair:
                    key, value = pair.split(':', 1)
                    key = key.strip().upper()
                    value = value.strip()
                    if key == 'MODEL':
                        result['model'] = value
                    elif key == 'VENDOR':
                        result['vendor'] = value
                    elif key == 'SW_REV':
                        result['software'] = value
            if result.get('model'):
                return result
        
        # Fallback: pattern matching for non-structured sysDescr
        descr = sys_descr.lower()
        
        if 'arris' in descr or 'touchstone' in descr:
            result['vendor'] = 'ARRIS'
        elif 'technicolor' in descr:
            result['vendor'] = 'Technicolor'
        elif 'sagemcom' in descr:
            result['vendor'] = 'Sagemcom'
        elif 'hitron' in descr:
            result['vendor'] = 'Hitron'
        elif 'motorola' in descr:
            result['vendor'] = 'Motorola'
        elif 'cisco' in descr:
            result['vendor'] = 'Cisco'
        elif 'ubee' in descr:
            result['vendor'] = 'Ubee'
        
        # Model patterns
        model_match = re.search(r'(FAST\d+|F\d{4}[A-Z]*|TG\d+|TC\d+|SB\d+|DPC\d+|EPC\d+|CM\d+|SBG\d+|CGM\d+)', sys_descr, re.I)
        if model_match:
            result['model'] = model_match.group(1).upper()
        
        # Software version
        version_match = re.search(r'(\d+\.\d+\.\d+[\.\d\-a-zA-Z]*)', sys_descr)
        if version_match:
            result['software'] = version_match.group(1)
        
        return result
    
    def _decode_cm_status(self, status_code: int) -> str:
        """Decode DOCSIS CM status code to human-readable string."""
        # docsIfCmtsCmStatusValue values
        status_map = {
            1: 'other',
            2: 'ranging',
            3: 'rangingAborted',
            4: 'rangingComplete',
            5: 'ipComplete',
            6: 'registrationComplete',
            7: 'accessDenied',
            8: 'operational',  # This is the "online" state
            9: 'registeredBPIInitializing',
        }
        return status_map.get(status_code, f'unknown({status_code})')
    
    def _decode_d3_status(self, status_code: int) -> str:
        """Decode docsIf3CmtsCmRegStatusValue to human-readable string."""
        # docsIf3CmtsCmRegStatusValue values from DOCS-IF3-MIB
        status_map = {
            1: 'other',
            2: 'initialRanging',
            3: 'rangingAutoAdjComplete',
            4: 'startEae',
            5: 'startDhcpv4',
            6: 'startDhcpv6',
            7: 'dhcpv4Complete',
            8: 'dhcpv6Complete',
            9: 'startCfgFileDownload',
            10: 'cfgFileDownloadComplete',
            11: 'startRegistration',
            12: 'registrationComplete',
            13: 'operational',  # This is the "online" state
            14: 'bpiInit',
            15: 'forwardingDisabled',
            16: 'rfMuteAll',
        }
        return status_map.get(status_code, f'unknown({status_code})')
    
    def _decode_docsis_version(self, docsis_code: int) -> str:
        """Decode DOCSIS version from docsIf3CmtsCmRegStatusDocsisVersion."""
        # docsIf3CmtsCmRegStatusDocsisVersion values from DOCSIS-IF3-MIB
        version_map = {
            1: 'ATDMA',
            2: 'SCDMA', 
            3: 'DOCSIS 1.0',
            4: 'DOCSIS 1.1',
            5: 'DOCSIS 2.0',
            6: 'DOCSIS 3.0',
            7: 'DOCSIS 3.1',
            8: 'DOCSIS 4.0',
        }
        return version_map.get(docsis_code, f'Unknown({docsis_code})')
    
    def _get_vendor_from_mac(self, mac: str) -> str:
        """Get vendor name from MAC address OUI (first 3 bytes)."""
        # Common cable modem OUIs
        oui_vendors = {
            '00:00:ca': 'ARRIS',
            '00:01:5c': 'ARRIS',
            '00:15:96': 'ARRIS',
            '00:15:a2': 'ARRIS',
            '00:15:a3': 'ARRIS',
            '00:15:a4': 'ARRIS',
            '00:15:a5': 'ARRIS',
            '00:1d:ce': 'ARRIS',
            '00:1d:cf': 'ARRIS',
            '00:1d:d0': 'ARRIS',
            '00:1d:d1': 'ARRIS',
            '00:1d:d2': 'ARRIS',
            '00:1d:d3': 'ARRIS',
            '00:1d:d4': 'ARRIS',
            '00:1d:d5': 'ARRIS',
            '00:23:74': 'ARRIS',
            'e8:ed:05': 'ARRIS',
            'f8:0b:be': 'ARRIS',
            '20:3d:66': 'ARRIS',
            '84:a0:6e': 'ARRIS',
            'f0:af:85': 'ARRIS',
            'fc:51:a4': 'ARRIS',
            '00:1e:5a': 'CISCO',
            '00:1e:bd': 'CISCO',
            '00:22:6b': 'CISCO',
            '00:26:0a': 'CISCO',
            '00:30:f1': 'CISCO',
            '5c:50:15': 'CISCO',
            'c0:c5:20': 'CISCO',
            '00:11:1a': 'Motorola',
            '00:12:25': 'Motorola',
            '00:14:f8': 'Motorola',
            '00:15:9a': 'Motorola',
            '00:15:d1': 'Motorola',
            '00:17:e2': 'Motorola',
            '00:18:a4': 'Motorola',
            '00:19:47': 'Motorola',
            '00:1a:66': 'Motorola',
            '00:1a:77': 'Motorola',
            '00:1c:c1': 'Motorola',
            '00:1c:fb': 'Motorola',
            '00:1d:6b': 'Motorola',
            '00:1e:46': 'Motorola',
            '00:1e:5d': 'Motorola',
            '00:1f:6b': 'Motorola',
            '00:23:be': 'Motorola',
            '00:24:95': 'Motorola',
            '00:26:41': 'Motorola',
            '00:26:42': 'Motorola',
            '10:86:8c': 'Technicolor',
            '18:35:d1': 'Technicolor',
            '2c:39:96': 'Technicolor',
            '30:d3:2d': 'Technicolor',
            '58:23:8c': 'Technicolor',
            '70:b1:4e': 'Technicolor',
            '7c:03:4c': 'Technicolor',
            '88:f7:c7': 'Technicolor',
            '90:01:3b': 'Technicolor',
            'a0:ce:c8': 'Technicolor',
            'c8:d1:5e': 'Technicolor',
            'd4:35:1d': 'Technicolor',
            'f4:ca:e5': 'Technicolor',
            '00:1d:b5': 'Juniper',
            '00:1f:12': 'Juniper',
            '00:21:59': 'Juniper',
            '00:23:9c': 'Juniper',
            '00:26:88': 'Juniper',
            '00:14:d1': 'Ubee',
            '00:15:2c': 'Ubee',
            '28:c6:8e': 'Ubee',
            '58:6d:8f': 'Ubee',
            '5c:b0:66': 'Ubee',
            '64:0d:ce': 'Ubee',
            '68:b6:fc': 'Ubee',
            '78:96:84': 'Ubee',
            '08:95:2a': 'Sagemcom',
            '10:b3:6f': 'Sagemcom',
            '28:52:e8': 'Sagemcom',
            '30:7c:b2': 'Sagemcom',
            '44:e1:37': 'Sagemcom',
            '70:fc:8f': 'Sagemcom',
            '7c:8b:ca': 'Sagemcom',
            'a0:1b:29': 'Sagemcom',
            'a8:4e:3f': 'Sagemcom',
            'a8:70:5d': 'Sagemcom',
            'cc:33:bb': 'Sagemcom',
            'f8:08:4f': 'Sagemcom',
            '00:04:bd': 'Hitron',
            '00:26:5b': 'Hitron',
            '00:26:d8': 'Hitron',
            '68:02:b8': 'Hitron',
            'bc:14:85': 'Hitron',
            'c4:27:95': 'Hitron',
            'cc:03:fa': 'Hitron',
        }
        
        if not mac or len(mac) < 8:
            return 'Unknown'
        
        # Normalize MAC format
        mac_normalized = mac.lower().replace('-', ':')
        oui = mac_normalized[:8]
        
        return oui_vendors.get(oui, 'Unknown')
    
    def _handle_cmts_get_modem_info(self, params: dict) -> dict:
        """
        Get detailed info for a specific modem from CMTS.
        
        Can search by MAC or IP address.
        """
        cmts_ip = params.get('cmts_ip')
        mac_address = params.get('mac_address')
        modem_ip = params.get('modem_ip')
        community = params.get('community', 'private')
        
        if not cmts_ip:
            return {'success': False, 'error': 'cmts_ip required'}
        
        if not mac_address and not modem_ip:
            return {'success': False, 'error': 'mac_address or modem_ip required'}
        
        # First get all modems and find the matching one
        modems_result = self._handle_cmts_get_modems({
            'cmts_ip': cmts_ip,
            'community': community,
            'limit': 5000,  # Get more for search
            'use_bulk': True
        })
        
        if not modems_result.get('success'):
            return modems_result
        
        # Find matching modem
        for modem in modems_result.get('modems', []):
            if mac_address and modem['mac_address'].lower() == mac_address.lower():
                return {'success': True, 'modem': modem, 'cmts_ip': cmts_ip}
            if modem_ip and modem['ip_address'] == modem_ip:
                return {'success': True, 'modem': modem, 'cmts_ip': cmts_ip}
        
        return {
            'success': False,
            'error': f"Modem not found on CMTS {cmts_ip}",
            'search_mac': mac_address,
            'search_ip': modem_ip
        }
    
    def connect(self):
        """Connect to PyPNM Server."""
        self.running = True
        
        # Set up SSH tunnel if enabled
        if self.config.pypnm_ssh_tunnel_enabled:
            if not self._setup_pypnm_tunnel():
                self.logger.error("Failed to establish SSH tunnel, cannot continue")
                return
        
        ws_url = self._get_websocket_url()
        
        while self.running:
            try:
                self.logger.info(f"Connecting to {ws_url}...")
                
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                
                self.ws.run_forever(ping_interval=120, ping_timeout=60)
                
            except Exception as e:
                self.logger.error(f"Connection failed: {e}")
            
            if self.running:
                self.logger.info(f"Reconnecting in {self.config.reconnect_interval} seconds...")
                time.sleep(self.config.reconnect_interval)
    
    def stop(self):
        """Stop the agent and cleanup connections."""
        self.logger.info("Stopping agent...")
        self.running = False
        
        # Close WebSocket
        if self.ws:
            self.ws.close()
        
        # Close CM Proxy SSH connection
        if self.cm_proxy:
            self.cm_proxy.close()
        
        # Close TFTP SSH connection
        if self.tftp_ssh:
            self.tftp_ssh.close()
        
        # Stop PyPNM tunnel monitor and tunnel
        if self.pypnm_tunnel_monitor:
            self.pypnm_tunnel_monitor.stop()
        if self.pypnm_tunnel:
            self.pypnm_tunnel.stop_tunnel()
        
        self.logger.info("Agent stopped")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='PyPNM Remote Agent')
    parser.add_argument('-c', '--config', help='Path to config file')
    parser.add_argument('--url', help='PyPNM Server WebSocket URL (overrides config)')
    parser.add_argument('--token', help='Authentication token (overrides config)')
    parser.add_argument('--agent-id', help='Agent ID (overrides config)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load configuration
    if args.config:
        config = AgentConfig.from_file(args.config)
        logger.info(f"Loaded config from {args.config}")
    else:
        config = AgentConfig.from_env()
        logger.info("Loaded config from environment variables")
    
    # Override with command line args
    if args.url:
        config.pypnm_server_url = args.url
    if args.token:
        config.auth_token = args.token
    if args.agent_id:
        config.agent_id = args.agent_id
    
    # Log configuration summary
    logger.info(f"Agent ID: {config.agent_id}")
    logger.info(f"PyPNM Server: {config.pypnm_server_url}")
    logger.info(f"SSH Tunnel: {'enabled' if config.pypnm_ssh_tunnel_enabled else 'disabled'}")
    if config.pypnm_ssh_tunnel_enabled:
        logger.info(f"  SSH Host: {config.pypnm_ssh_host}")
    logger.info(f"CM Proxy: {config.cm_proxy_host or 'not configured'}")
    logger.info(f"CMTS SNMP Direct: {config.cmts_snmp_direct}")
    logger.info(f"TFTP SSH: {config.tftp_ssh_host or 'not configured'}")
    
    # Start agent
    agent = PyPNMAgent(config)
    
    try:
        agent.connect()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        agent.stop()


# OFDM Capture Handler Methods (add to PyPNMAgent class)
def _handle_pnm_ofdm_channels(self, params: dict) -> dict:
    """Get list of OFDM channels using PyPNM."""
    import sys
    sys.path.insert(0, '/home/svdleer/PyPNM')
    
    try:
        import asyncio
        from pypnm.lib.mac_address import MacAddress
        from pypnm.lib.inet import Inet
        from agent_cable_modem import AgentCableModem
        
        mac = params.get('mac_address')
        ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        
        async def get_channels():
            cm = AgentCableModem(
                mac_address=MacAddress(mac),
                inet=Inet(ip),
                backend_url='http://localhost:5050',
                write_community=community
            )
            channels_data = await cm.getDocsIf31CmDsOfdmChanEntry()
            
            channels = []
            for ch in channels_data:
                channels.append({
                    "index": ch.index,
                    "channel_id": getattr(ch.entry, 'docsIf31CmDsOfdmChanChannelId', None),
                    "subcarrier_zero_freq": getattr(ch.entry, 'docsIf31CmDsOfdmChannelSubcarrierZeroFreq', None),
                    "num_subcarriers": getattr(ch.entry, 'docsIf31CmDsOfdmChanNumActiveSubcarriers', None),
                })
            return channels
        
        channels = asyncio.run(get_channels())
        return {"success": True, "channels": channels}
        
    except Exception as e:
        logger.error(f"OFDM channels error: {e}")
        return {"success": False, "error": str(e)}


def _handle_pnm_ofdm_capture(self, params: dict) -> dict:
    """Trigger OFDM RxMER capture using PyPNM."""
    import sys
    sys.path.insert(0, '/home/svdleer/PyPNM')
    
    try:
        import asyncio
        from pypnm.lib.mac_address import MacAddress
        from pypnm.lib.inet import Inet
        from agent_cable_modem import AgentCableModem
        
        mac = params.get('mac_address')
        ip = params.get('modem_ip')
        ofdm_channel = params.get('ofdm_channel', 0)
        filename = params.get('filename', 'rxmer_capture')
        community = params.get('community', 'm0d3m1nf0')
        
        async def trigger_capture():
            cm = AgentCableModem(
                mac_address=MacAddress(mac),
                inet=Inet(ip),
                backend_url='http://localhost:5050',
                write_community=community
            )
            success = await cm.setDocsPnmCmDsOfdmRxMer(
                ofdm_idx=ofdm_channel,
                rxmer_file_name=filename,
                set_and_go=True
            )
            return success
        
        result = asyncio.run(trigger_capture())
        
        if result:
            return {
                "success": True,
                "message": "OFDM capture triggered",
                "filename": filename
            }
        else:
            return {"success": False, "error": "Failed to trigger capture"}
            
    except Exception as e:
        logger.error(f"OFDM capture error: {e}")
        return {"success": False, "error": str(e)}


def _handle_pnm_ofdm_rxmer(self, params: dict) -> dict:
    """Get OFDM RxMER data using PyPNM."""
    import sys
    sys.path.insert(0, '/home/svdleer/PyPNM')
    
    try:
        import asyncio
        from pypnm.lib.mac_address import MacAddress
        from pypnm.lib.inet import Inet
        from agent_cable_modem import AgentCableModem
        
        mac = params.get('mac_address')
        ip = params.get('modem_ip')
        community = params.get('community', 'm0d3m1nf0')
        
        async def get_rxmer():
            cm = AgentCableModem(
                mac_address=MacAddress(mac),
                inet=Inet(ip),
                backend_url='http://localhost:5050',
                write_community=community
            )
            rxmer_data = await cm.getDocsPnmCmDsOfdmRxMerEntry()
            
            if not rxmer_data:
                return None
            
            subcarriers = []
            mer_values = []
            
            for entry in rxmer_data:
                if hasattr(entry, 'index'):
                    subcarriers.append(entry.index)
                    # Extract MER value - structure may vary
                    mer = 0
                    if hasattr(entry, 'entry'):
                        mer = getattr(entry.entry, 'docsPnmCmDsOfdmRxMerMean', 0)
                    mer_values.append(mer / 10.0 if mer else 0)  # Convert to dB
            
            return {
                "mac_address": mac,
                "subcarriers": subcarriers,
                "mer_values": mer_values
            }
        
        data = asyncio.run(get_rxmer())
        
        if data:
            return {"success": True, "data": data}
        else:
            return {"success": False, "error": "No RxMER data available"}
            
    except Exception as e:
        logger.error(f"OFDM RxMER fetch error: {e}")
        return {"success": False, "error": str(e)}


def main():
    """Main entry point for the PyPNM Agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description='PyPNM Web GUI Agent')
    parser.add_argument('--config', '-c', type=str, help='Path to agent_config.json')
    parser.add_argument('--agent-id', type=str, help='Override agent ID from config')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load configuration
    if args.config:
        config = AgentConfig.from_file(args.config)
        logger.info(f"Loaded config from {args.config}")
    else:
        # Try default locations
        possible_configs = [
            'agent_config.json',
            os.path.expanduser('~/.pypnm-agent/agent_config.json'),
            os.path.expanduser('~/agent_config.json'),
            '/etc/pypnm-agent/agent_config.json',
        ]
        config = None
        for config_path in possible_configs:
            if os.path.exists(config_path):
                config = AgentConfig.from_file(config_path)
                logger.info(f"Loaded config from {config_path}")
                break
        
        if not config:
            logger.error("No configuration file found. Use --config or set environment variables.")
            return
    
    # Override agent ID if provided
    if args.agent_id:
        config.agent_id = args.agent_id
    
    # Log configuration summary
    logger.info(f"Agent ID: {config.agent_id}")
    logger.info(f"PyPNM Server: {config.pypnm_server_url}")
    logger.info(f"SSH Tunnel: {'enabled' if config.pypnm_ssh_tunnel_enabled else 'disabled'}")
    if config.pypnm_ssh_tunnel_enabled:
        logger.info(f"  SSH Host: {config.pypnm_ssh_host}")
    logger.info(f"CM Proxy: {config.cm_proxy_host or 'not configured'}")
    logger.info(f"CMTS SNMP Direct: {config.cmts_snmp_direct}")
    logger.info(f"TFTP SSH: {config.tftp_ssh_host or 'not configured'}")
    
    # Start agent
    agent = PyPNMAgent(config)
    
    try:
        agent.connect()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        agent.stop()


if __name__ == '__main__':
    main()



