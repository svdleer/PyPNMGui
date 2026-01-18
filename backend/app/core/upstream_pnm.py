# Upstream PNM Module
# SPDX-License-Identifier: Apache-2.0
#
# Implements Upstream Triggered Spectrum Capture (UTSC) and Upstream RxMER
# Based on DOCSIS PNM MIBs and CommScope E6000 implementation

"""
Upstream PNM Module for DOCSIS 3.1 CCAP/CMTS

This module provides:
1. UTSC (Upstream Triggered Spectrum Capture) - Wideband/narrowband spectrum at CMTS
2. US RxMER (Upstream OFDMA RxMER) - Per-subcarrier MER on OFDMA channels

Key OIDs (from DOCS-PNM-MIB):
- docsPnmCmtsUtscCfgTable: 1.3.6.1.4.1.4491.2.1.27.1.3.1
- docsPnmCmtsUtscCtrlTable: 1.3.6.1.4.1.4491.2.1.27.1.3.2  
- docsPnmCmtsUtscStatusTable: 1.3.6.1.4.1.4491.2.1.27.1.3.3
- docsPnmCmtsUsOfdmaRxMerTable: 1.3.6.1.4.1.4491.2.1.27.1.3.8
- docsPnmCmtsUsOfdmaAQProbeTable: 1.3.6.1.4.1.4491.2.1.27.1.3.6

Results are stored on CMTS in /pnm/ directory and can be retrieved via TFTP.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import IntEnum

logger = logging.getLogger(__name__)


# ============== UTSC Constants ==============

class UtscTriggerMode(IntEnum):
    """UTSC Trigger Modes (docsPnmCmtsUtscCfgTriggerMode)"""
    OTHER = 1
    FREE_RUNNING = 2
    MINI_SLOT = 3
    SID = 4
    IDLE_SID = 5
    CM_MAC = 6


class UtscOutputFormat(IntEnum):
    """UTSC Output Formats (docsPnmCmtsUtscCfgOutputFormat)"""
    TIME_IQ = 1
    FFT_POWER = 2
    FFT_COMPLEX = 3
    FFT_IQ = 4
    FFT_AMPLITUDE = 5


class UtscWindow(IntEnum):
    """UTSC Window Types (docsPnmCmtsUtscCfgWindow)"""
    OTHER = 1
    RECTANGULAR = 2
    HANN = 3
    BLACKMAN_HARRIS = 4
    HAMMING = 5


class MeasStatusType(IntEnum):
    """Measurement Status (docsPnmCmtsUtscStatusMeasStatus)"""
    OTHER = 1
    INACTIVE = 2
    BUSY = 3
    SAMPLE_READY = 4
    ERROR = 5
    RESOURCE_UNAVAILABLE = 6
    SAMPLE_TRUNCATED = 7


# ============== OID Definitions ==============

class UpstreamPnmOids:
    """DOCSIS PNM MIB OIDs for Upstream Tests"""
    
    # Base OID for docsPnmCmtsMib
    DOCS_PNM_CMTS_MIB = "1.3.6.1.4.1.4491.2.1.27.1"
    
    # UTSC Configuration Table (docsPnmCmtsUtscCfgTable)
    UTSC_CFG_TABLE = f"{DOCS_PNM_CMTS_MIB}.3.1.1"
    UTSC_CFG_INDEX = f"{UTSC_CFG_TABLE}.1"  # Key
    UTSC_CFG_LOGICAL_CH_IFINDEX = f"{UTSC_CFG_TABLE}.2"
    UTSC_CFG_TRIGGER_MODE = f"{UTSC_CFG_TABLE}.3"
    UTSC_CFG_CM_MAC_ADDR = f"{UTSC_CFG_TABLE}.6"
    UTSC_CFG_CENTER_FREQ = f"{UTSC_CFG_TABLE}.8"
    UTSC_CFG_SPAN = f"{UTSC_CFG_TABLE}.9"
    UTSC_CFG_NUM_BINS = f"{UTSC_CFG_TABLE}.10"
    UTSC_CFG_FILENAME = f"{UTSC_CFG_TABLE}.13"
    UTSC_CFG_WINDOW = f"{UTSC_CFG_TABLE}.16"
    UTSC_CFG_OUTPUT_FORMAT = f"{UTSC_CFG_TABLE}.17"
    UTSC_CFG_REPEAT_PERIOD = f"{UTSC_CFG_TABLE}.18"
    UTSC_CFG_FREERUN_DURATION = f"{UTSC_CFG_TABLE}.19"
    UTSC_CFG_TRIGGER_COUNT = f"{UTSC_CFG_TABLE}.20"
    
    # UTSC Control Table (docsPnmCmtsUtscCtrlTable)
    UTSC_CTRL_TABLE = f"{DOCS_PNM_CMTS_MIB}.3.2.1"
    UTSC_CTRL_INITIATE_TEST = f"{UTSC_CTRL_TABLE}.1"
    
    # UTSC Status Table (docsPnmCmtsUtscStatusTable)
    UTSC_STATUS_TABLE = f"{DOCS_PNM_CMTS_MIB}.3.3.1"
    UTSC_STATUS_MEAS_STATUS = f"{UTSC_STATUS_TABLE}.1"
    
    # US OFDMA RxMER Table (docsPnmCmtsUsOfdmaRxMerTable)
    US_RXMER_TABLE = f"{DOCS_PNM_CMTS_MIB}.3.8.1"
    US_RXMER_ENABLE = f"{US_RXMER_TABLE}.1"
    US_RXMER_PRE_EQ = f"{US_RXMER_TABLE}.2"
    US_RXMER_NUM_AVGS = f"{US_RXMER_TABLE}.3"
    US_RXMER_MEAS_STATUS = f"{US_RXMER_TABLE}.4"
    US_RXMER_FILENAME = f"{US_RXMER_TABLE}.5"
    US_RXMER_CM_MAC = f"{US_RXMER_TABLE}.6"
    
    # US OFDMA Active/Quiet Probe Table (docsPnmCmtsUsOfdmaAQProbeTable)
    US_AQPROBE_TABLE = f"{DOCS_PNM_CMTS_MIB}.3.6.1"
    US_AQPROBE_ENABLE = f"{US_AQPROBE_TABLE}.1"
    US_AQPROBE_PRE_EQ_ON = f"{US_AQPROBE_TABLE}.2"
    US_AQPROBE_USE_IDLE_SID = f"{US_AQPROBE_TABLE}.3"
    US_AQPROBE_NUM_SYM = f"{US_AQPROBE_TABLE}.4"
    US_AQPROBE_FREQ_DOMAIN = f"{US_AQPROBE_TABLE}.5"
    US_AQPROBE_MEAS_STATUS = f"{US_AQPROBE_TABLE}.6"
    US_AQPROBE_FILENAME = f"{US_AQPROBE_TABLE}.7"
    US_AQPROBE_CM_MAC = f"{US_AQPROBE_TABLE}.8"


# ============== Data Classes ==============

@dataclass
class UtscConfig:
    """Configuration for UTSC test"""
    rf_port_ifindex: int  # ifIndex of the upstream RF port
    trigger_mode: UtscTriggerMode = UtscTriggerMode.FREE_RUNNING
    cm_mac_address: Optional[str] = None  # For CM_MAC trigger mode
    logical_ch_ifindex: Optional[int] = None  # For IdleSID/CM_MAC modes
    center_freq_hz: int = 30000000  # 30 MHz default
    span_hz: int = 80000000  # 80 MHz span
    num_bins: int = 800
    output_format: UtscOutputFormat = UtscOutputFormat.FFT_POWER
    window: UtscWindow = UtscWindow.HANN
    filename: str = "utsc_capture"
    repeat_period_ms: int = 0  # 0 = single capture
    freerun_duration_ms: int = 1000  # 1 second
    trigger_count: int = 1  # For IdleSID/CM_MAC modes


@dataclass
class UsRxMerConfig:
    """Configuration for Upstream OFDMA RxMER test"""
    ofdma_ifindex: int  # ifIndex of the OFDMA channel
    cm_mac_address: str  # MAC address of the CM
    filename: str = "us_rxmer_capture"
    pre_eq: bool = True  # Enable pre-equalization


@dataclass
class UsAQProbeConfig:
    """Configuration for Upstream Active/Quiet Probe test"""
    ofdma_ifindex: int  # ifIndex of the OFDMA channel
    cm_mac_address: Optional[str] = None  # For active probe
    filename: str = "aqprobe_capture"
    use_idle_sid: bool = True  # True=quiet, False=active
    pre_eq_on: bool = True
    num_symbols: int = 8
    freq_domain: bool = True  # True=frequency domain, False=time domain


# ============== Upstream PNM Client ==============

class UpstreamPnmClient:
    """
    Client for Upstream PNM operations via agent.
    
    Upstream PNM tests run on the CMTS/CCAP, not on the cable modem.
    The agent needs SNMP access to the CMTS to trigger tests.
    """
    
    def __init__(self, agent_manager=None):
        """
        Initialize upstream PNM client.
        
        Args:
            agent_manager: AgentManager instance for agent communication
        """
        self.agent_manager = agent_manager
    
    def _send_agent_request(self, action: str, params: dict) -> dict:
        """Send request to agent via agent manager."""
        if not self.agent_manager:
            raise RuntimeError("AgentManager not configured")
        
        # Format request for agent
        request = {
            "action": action,
            "params": params
        }
        
        return self.agent_manager.send_request(request)
    
    # ============== UTSC Operations ==============
    
    def configure_utsc(
        self,
        cmts_ip: str,
        config: UtscConfig,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Configure UTSC test parameters on CMTS.
        
        Args:
            cmts_ip: CMTS IP address
            config: UTSC configuration
            community: SNMP community string
            
        Returns:
            dict with success status
        """
        params = {
            "cmts_ip": cmts_ip,
            "community": community,
            "rf_port_ifindex": config.rf_port_ifindex,
            "trigger_mode": int(config.trigger_mode),
            "center_freq_hz": config.center_freq_hz,
            "span_hz": config.span_hz,
            "num_bins": config.num_bins,
            "output_format": int(config.output_format),
            "window": int(config.window),
            "filename": config.filename,
            "repeat_period_ms": config.repeat_period_ms,
            "freerun_duration_ms": config.freerun_duration_ms,
            "trigger_count": config.trigger_count,
        }
        
        if config.cm_mac_address:
            params["cm_mac_address"] = config.cm_mac_address
        if config.logical_ch_ifindex:
            params["logical_ch_ifindex"] = config.logical_ch_ifindex
            
        return self._send_agent_request("pnm_utsc_configure", params)
    
    def start_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Start UTSC test (set InitiateTest to true).
        
        Args:
            cmts_ip: CMTS IP address
            rf_port_ifindex: ifIndex of the upstream RF port
            community: SNMP community string
            
        Returns:
            dict with success status
        """
        return self._send_agent_request("pnm_utsc_start", {
            "cmts_ip": cmts_ip,
            "rf_port_ifindex": rf_port_ifindex,
            "community": community,
        })
    
    def stop_utsc(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Stop UTSC test (set InitiateTest to false).
        """
        return self._send_agent_request("pnm_utsc_stop", {
            "cmts_ip": cmts_ip,
            "rf_port_ifindex": rf_port_ifindex,
            "community": community,
        })
    
    def get_utsc_status(
        self,
        cmts_ip: str,
        rf_port_ifindex: int,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Get UTSC test status.
        
        Returns:
            dict with status, meas_status (MeasStatusType value)
        """
        return self._send_agent_request("pnm_utsc_status", {
            "cmts_ip": cmts_ip,
            "rf_port_ifindex": rf_port_ifindex,
            "community": community,
        })
    
    # ============== Upstream RxMER Operations ==============
    
    def start_us_rxmer(
        self,
        cmts_ip: str,
        config: UsRxMerConfig,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement.
        
        Args:
            cmts_ip: CMTS IP address
            config: US RxMER configuration
            community: SNMP community string
            
        Returns:
            dict with success status
        """
        return self._send_agent_request("pnm_us_rxmer_start", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": config.ofdma_ifindex,
            "cm_mac_address": config.cm_mac_address,
            "filename": config.filename,
            "pre_eq": config.pre_eq,
            "community": community,
        })
    
    def get_us_rxmer_status(
        self,
        cmts_ip: str,
        ofdma_ifindex: int,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Get Upstream RxMER measurement status.
        """
        return self._send_agent_request("pnm_us_rxmer_status", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "community": community,
        })
    
    # ============== Active/Quiet Probe Operations ==============
    
    def start_aq_probe(
        self,
        cmts_ip: str,
        config: UsAQProbeConfig,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Start Active or Quiet Probe measurement.
        
        Args:
            cmts_ip: CMTS IP address
            config: AQ Probe configuration
            community: SNMP community string
            
        Returns:
            dict with success status
        """
        return self._send_agent_request("pnm_aq_probe_start", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": config.ofdma_ifindex,
            "cm_mac_address": config.cm_mac_address,
            "filename": config.filename,
            "use_idle_sid": config.use_idle_sid,
            "pre_eq_on": config.pre_eq_on,
            "num_symbols": config.num_symbols,
            "freq_domain": config.freq_domain,
            "community": community,
        })
    
    def get_aq_probe_status(
        self,
        cmts_ip: str,
        ofdma_ifindex: int,
        community: str = "private"
    ) -> Dict[str, Any]:
        """
        Get Active/Quiet Probe measurement status.
        """
        return self._send_agent_request("pnm_aq_probe_status", {
            "cmts_ip": cmts_ip,
            "ofdma_ifindex": ofdma_ifindex,
            "community": community,
        })
    
    # ============== File Retrieval ==============
    
    def fetch_pnm_file(
        self,
        cmts_ip: str,
        filename: str,
        directory: str = "/pnm/utsc"
    ) -> Dict[str, Any]:
        """
        Fetch PNM results file from CMTS via TFTP.
        
        Args:
            cmts_ip: CMTS IP address
            filename: Name of the file (without timestamp)
            directory: Directory on CMTS (/pnm/utsc, /pnm/mer, /pnm/aqprobe)
            
        Returns:
            dict with file contents (binary or parsed)
        """
        return self._send_agent_request("pnm_fetch_file", {
            "cmts_ip": cmts_ip,
            "filename": filename,
            "directory": directory,
        })


# ============== Helper Functions ==============

def mac_to_hex_string(mac_address: str) -> str:
    """Convert MAC address to hex string for SNMP SET."""
    # Remove separators and convert to hex
    mac = mac_address.replace(":", "").replace("-", "").replace(".", "").upper()
    return mac


def parse_utsc_file(data: bytes) -> Dict[str, Any]:
    """
    Parse UTSC binary file format.
    
    File format (per DOCSIS OSSIv4.0):
    - Header: 328 bytes
    - Sample data: up to 16384 bytes
    """
    if len(data) < 328:
        return {"error": "File too small for valid UTSC data"}
    
    # Parse header (simplified - full parsing requires struct unpacking)
    result = {
        "header_size": 328,
        "data_size": len(data) - 328,
        "raw_data": data[328:].hex() if len(data) > 328 else None,
    }
    
    # TODO: Full header parsing based on DOCSIS spec
    
    return result


def parse_us_rxmer_file(data: bytes) -> Dict[str, Any]:
    """
    Parse Upstream RxMER binary file format.
    
    File format (per DOCSIS OSSIv4.0):
    - Header: 297 bytes
    - RxMER data: up to 1900 bytes (50kHz) or 3800 bytes (25kHz)
    """
    if len(data) < 297:
        return {"error": "File too small for valid US RxMER data"}
    
    # Parse header (simplified)
    result = {
        "header_size": 297,
        "data_size": len(data) - 297,
    }
    
    # TODO: Full parsing with subcarrier MER values
    
    return result
