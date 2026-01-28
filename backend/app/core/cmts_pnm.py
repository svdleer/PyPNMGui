# CMTS PNM Operations using PyPNM pysnmp
# SPDX-License-Identifier: Apache-2.0
#
# Implements CMTS-side PNM operations (US OFDMA RxMER, UTSC)
# Uses PyPNM's Snmp_v2c class for async SNMP operations

"""
CMTS PNM Module for Upstream OFDMA RxMER

This module provides CMTS-side PNM operations using PyPNM's pysnmp wrapper.
Key features:
- Discover modem's OFDMA channel ifIndex on CMTS
- Trigger US OFDMA RxMER measurement
- Poll measurement status
- Retrieve results from TFTP

OIDs used (from DOCS-PNM-MIB):
- docsIf3CmtsCmRegStatusMacAddr: 1.3.6.1.4.1.4491.2.1.20.1.3.1.2
- docsIf31CmtsCmUsOfdmaChannelStatus: 1.3.6.1.4.1.4491.2.1.28.1.5.1.1  
- docsPnmCmtsUsOfdmaRxMerTable: 1.3.6.1.4.1.4491.2.1.27.1.3.8
"""

import asyncio
import logging
import re
from typing import Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import IntEnum

from pysnmp.proto.rfc1902 import Integer32, OctetString

# Import PyPNM's SNMP module
try:
    from pypnm.snmp.snmp_v2c import Snmp_v2c
    from pypnm.lib.inet import Inet
    PYPNM_AVAILABLE = True
except ImportError:
    PYPNM_AVAILABLE = False
    Snmp_v2c = None  # type: ignore
    Inet = None  # type: ignore

if TYPE_CHECKING:
    from pypnm.snmp.snmp_v2c import Snmp_v2c
    from pypnm.lib.inet import Inet

logger = logging.getLogger(__name__)


class MeasStatus(IntEnum):
    """Measurement Status (docsPnmCmtsUsOfdmaRxMerMeasStatus)"""
    OTHER = 1
    INACTIVE = 2
    BUSY = 3
    SAMPLE_READY = 4
    ERROR = 5
    RESOURCE_UNAVAILABLE = 6


@dataclass
class UsOfdmaRxMerConfig:
    """Configuration for US OFDMA RxMER measurement"""
    cmts_ip: str
    ofdma_ifindex: int
    cm_mac_address: str
    community: str = "private"
    filename: str = "us_rxmer"
    pre_eq: bool = True
    num_averages: int = 1


class CmtsPnmClient:
    """
    CMTS PNM client using PyPNM's pysnmp wrapper.
    
    Provides async methods for:
    - Discovering modem's OFDMA channel ifIndex
    - Starting/monitoring US OFDMA RxMER measurements
    - Retrieving measurement results
    """
    
    # OID definitions
    OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
    OID_CM_REG_MAC = "1.3.6.1.4.1.4491.2.1.20.1.3.1.2"  # docsIf3CmtsCmRegStatusMacAddr
    OID_CM_OFDMA_STATUS = "1.3.6.1.4.1.4491.2.1.28.1.5.1.1"  # docsIf31CmtsCmUsOfdmaChannelStatusTable
    
    # US OFDMA RxMER Table (docsPnmCmtsUsOfdmaRxMerTable)
    OID_US_RXMER_TABLE = "1.3.6.1.4.1.4491.2.1.27.1.3.8.1"
    OID_US_RXMER_ENABLE = f"{OID_US_RXMER_TABLE}.1"
    OID_US_RXMER_PRE_EQ = f"{OID_US_RXMER_TABLE}.2"
    OID_US_RXMER_NUM_AVGS = f"{OID_US_RXMER_TABLE}.3"
    OID_US_RXMER_MEAS_STATUS = f"{OID_US_RXMER_TABLE}.4"
    OID_US_RXMER_FILENAME = f"{OID_US_RXMER_TABLE}.5"
    OID_US_RXMER_CM_MAC = f"{OID_US_RXMER_TABLE}.6"
    
    def __init__(self, cmts_ip: str, community: str = "private", write_community: Optional[str] = None):
        """
        Initialize CMTS PNM client.
        
        Args:
            cmts_ip: CMTS IP address
            community: SNMP read community
            write_community: SNMP write community (defaults to community)
        """
        if not PYPNM_AVAILABLE:
            raise RuntimeError("PyPNM not available. Install pypnm package.")
        
        self.cmts_ip = cmts_ip
        self.community = community
        self.write_community = write_community or community
        self._snmp: Optional[Snmp_v2c] = None
    
    def _get_snmp(self) -> Snmp_v2c:
        """Get or create SNMP client instance."""
        if self._snmp is None:
            self._snmp = Snmp_v2c(
                Inet(self.cmts_ip),
                read_community=self.community,
                write_community=self.write_community,
                timeout=10,
                retries=2
            )
        return self._snmp
    
    def close(self):
        """Close SNMP connection."""
        if self._snmp:
            self._snmp.close()
            self._snmp = None
    
    @staticmethod
    def mac_to_hex_octets(mac_address: str) -> str:
        """Convert MAC address to hex octets string for SNMP SET."""
        mac = mac_address.lower().replace(":", "").replace("-", "").replace(".", "")
        return bytes.fromhex(mac).decode('latin-1')
    
    @staticmethod
    def normalize_mac(mac_address: str) -> str:
        """Normalize MAC address to lowercase colon-separated format."""
        mac = mac_address.lower().replace("-", ":").replace(".", "")
        if ":" not in mac:
            mac = ":".join([mac[i:i+2] for i in range(0, 12, 2)])
        return mac
    
    async def discover_cm_index(self, cm_mac: str) -> Optional[int]:
        """
        Find CM index on CMTS from MAC address.
        
        Args:
            cm_mac: Cable modem MAC address
            
        Returns:
            CM index (docsIf3CmtsCmRegStatusIndex) or None
        """
        snmp = self._get_snmp()
        mac_normalized = self.normalize_mac(cm_mac)
        
        logger.info(f"Looking for CM MAC {mac_normalized} on CMTS {self.cmts_ip}")
        
        try:
            results = await snmp.bulk_walk(self.OID_CM_REG_MAC, max_repetitions=50)
            
            if not results:
                logger.warning("No CM registration entries found")
                return None
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                value = var_bind[1]
                
                # Convert SNMP OctetString to MAC format
                if hasattr(value, 'prettyPrint'):
                    mac_hex = value.prettyPrint()
                    # Handle "0x001122334455" format
                    if mac_hex.startswith("0x"):
                        mac_hex = mac_hex[2:]
                    # Convert to colon format
                    if len(mac_hex) == 12:
                        found_mac = ":".join([mac_hex[i:i+2].lower() for i in range(0, 12, 2)])
                        if found_mac == mac_normalized:
                            # Extract CM index from OID suffix
                            cm_index = int(oid_str.split(".")[-1])
                            logger.info(f"Found CM index: {cm_index}")
                            return cm_index
            
            logger.warning(f"CM MAC {mac_normalized} not found on CMTS")
            return None
            
        except Exception as e:
            logger.error(f"Error discovering CM index: {e}")
            return None
    
    async def discover_ofdma_ifindex(self, cm_index: int) -> Optional[int]:
        """
        Find OFDMA channel ifIndex for a cable modem.
        
        Args:
            cm_index: CM registration index
            
        Returns:
            OFDMA channel ifIndex or None
        """
        snmp = self._get_snmp()
        
        logger.info(f"Looking for OFDMA channel for CM index {cm_index}")
        
        try:
            results = await snmp.bulk_walk(self.OID_CM_OFDMA_STATUS, max_repetitions=50)
            
            if not results:
                logger.warning("No OFDMA status entries found")
                return None
            
            for var_bind in results:
                oid_str = str(var_bind[0])
                
                # OID format: .1.3.6.1.4.1.4491.2.1.28.1.5.1.1.<cmIndex>.<ofdmaIfIndex>
                if f".{cm_index}." in oid_str:
                    parts = oid_str.split(".")
                    for i, part in enumerate(parts):
                        if part == str(cm_index) and i + 1 < len(parts):
                            ofdma_ifindex = int(parts[i + 1])
                            # OFDMA ifindexes are typically in the 843087xxx range
                            if ofdma_ifindex >= 843087000:
                                logger.info(f"Found OFDMA ifIndex: {ofdma_ifindex}")
                                return ofdma_ifindex
            
            logger.warning(f"No OFDMA channel found for CM index {cm_index}")
            return None
            
        except Exception as e:
            logger.error(f"Error discovering OFDMA ifIndex: {e}")
            return None
    
    async def discover_modem_ofdma(self, cm_mac: str) -> dict[str, Any]:
        """
        Discover modem's OFDMA channel information.
        
        Args:
            cm_mac: Cable modem MAC address
            
        Returns:
            Dict with cm_index, ofdma_ifindex, and success status
        """
        cm_index = await self.discover_cm_index(cm_mac)
        if not cm_index:
            return {"success": False, "error": "CM not found on CMTS"}
        
        ofdma_ifindex = await self.discover_ofdma_ifindex(cm_index)
        if not ofdma_ifindex:
            return {"success": False, "error": "No OFDMA channel for this modem", "cm_index": cm_index}
        
        # Get OFDMA channel description
        snmp = self._get_snmp()
        description = None
        try:
            result = await snmp.get(f"{self.OID_IF_DESCR}.{ofdma_ifindex}")
            if result:
                description = str(result[0][1])
        except:
            pass
        
        return {
            "success": True,
            "cm_index": cm_index,
            "ofdma_ifindex": ofdma_ifindex,
            "ofdma_description": description
        }
    
    async def start_us_rxmer(self, config: UsOfdmaRxMerConfig) -> dict[str, Any]:
        """
        Start Upstream OFDMA RxMER measurement.
        
        Args:
            config: US RxMER configuration
            
        Returns:
            Dict with success status and details
        """
        snmp = self._get_snmp()
        idx = f".{config.ofdma_ifindex}"
        
        logger.info(f"Starting US RxMER for OFDMA ifIndex {config.ofdma_ifindex}, CM MAC {config.cm_mac_address}")
        
        try:
            # 1. Set filename
            await snmp.set(
                f"{self.OID_US_RXMER_FILENAME}{idx}",
                config.filename,
                OctetString
            )
            
            # 2. Set CM MAC address
            mac_octets = self.mac_to_hex_octets(config.cm_mac_address)
            await snmp.set(
                f"{self.OID_US_RXMER_CM_MAC}{idx}",
                mac_octets,
                OctetString
            )
            
            # 3. Set pre-equalization (1=true, 2=false)
            pre_eq_val = 1 if config.pre_eq else 2
            await snmp.set(
                f"{self.OID_US_RXMER_PRE_EQ}{idx}",
                pre_eq_val,
                Integer32
            )
            
            # 4. Set number of averages
            await snmp.set(
                f"{self.OID_US_RXMER_NUM_AVGS}{idx}",
                config.num_averages,
                Integer32
            )
            
            # 5. Enable measurement (1=true)
            await snmp.set(
                f"{self.OID_US_RXMER_ENABLE}{idx}",
                1,
                Integer32
            )
            
            return {
                "success": True,
                "message": "US OFDMA RxMER measurement started",
                "ofdma_ifindex": config.ofdma_ifindex,
                "cm_mac": config.cm_mac_address,
                "filename": config.filename
            }
            
        except Exception as e:
            logger.error(f"Failed to start US RxMER: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_us_rxmer_status(self, ofdma_ifindex: int) -> dict[str, Any]:
        """
        Get US OFDMA RxMER measurement status.
        
        Args:
            ofdma_ifindex: OFDMA channel ifIndex
            
        Returns:
            Dict with measurement status
        """
        snmp = self._get_snmp()
        
        try:
            result = await snmp.get(f"{self.OID_US_RXMER_MEAS_STATUS}.{ofdma_ifindex}")
            
            if not result:
                return {"success": False, "error": "No response from CMTS"}
            
            status_value = int(result[0][1])
            status_name = MeasStatus(status_value).name if status_value in [e.value for e in MeasStatus] else "unknown"
            
            return {
                "success": True,
                "ofdma_ifindex": ofdma_ifindex,
                "meas_status": status_value,
                "meas_status_name": status_name,
                "is_ready": status_value == MeasStatus.SAMPLE_READY,
                "is_busy": status_value == MeasStatus.BUSY,
                "is_error": status_value == MeasStatus.ERROR
            }
            
        except Exception as e:
            logger.error(f"Failed to get US RxMER status: {e}")
            return {"success": False, "error": str(e)}


# Async wrapper functions for use in Flask routes

def run_async(coro):
    """Run async coroutine in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def discover_modem_ofdma_sync(cmts_ip: str, cm_mac: str, community: str = "private") -> dict[str, Any]:
    """
    Synchronous wrapper for OFDMA discovery.
    
    Args:
        cmts_ip: CMTS IP address
        cm_mac: Cable modem MAC address
        community: SNMP community
        
    Returns:
        Discovery result dict
    """
    client = CmtsPnmClient(cmts_ip, community)
    try:
        return run_async(client.discover_modem_ofdma(cm_mac))
    finally:
        client.close()


def start_us_rxmer_sync(config: UsOfdmaRxMerConfig) -> dict[str, Any]:
    """
    Synchronous wrapper for starting US RxMER measurement.
    """
    client = CmtsPnmClient(config.cmts_ip, config.community)
    try:
        return run_async(client.start_us_rxmer(config))
    finally:
        client.close()


def get_us_rxmer_status_sync(cmts_ip: str, ofdma_ifindex: int, community: str = "private") -> dict[str, Any]:
    """
    Synchronous wrapper for getting US RxMER status.
    """
    client = CmtsPnmClient(cmts_ip, community)
    try:
        return run_async(client.get_us_rxmer_status(ofdma_ifindex))
    finally:
        client.close()
