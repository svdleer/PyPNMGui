"""
PyPNM OFDM Capture Integration
Handles DOCSIS 3.1 OFDM downstream spectrum captures
"""
import asyncio
import logging
from typing import Optional, Dict, List
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

logger = logging.getLogger(__name__)


class OfdmCaptureManager:
    """Manages OFDM spectrum captures using PyPNM."""
    
    def __init__(self, backend_url: str = "http://localhost:5050"):
        self.backend_url = backend_url
        self._captures = {}  # Active captures by MAC address
    
    async def get_ofdm_channels(self, mac_address: str, modem_ip: str, community: str = "m0d3m1nf0") -> List[Dict]:
        """
        Get list of available OFDM channels on the modem.
        
        Returns:
            List of OFDM channel info dicts with index, frequency, etc.
        """
        try:
            cm = AgentCableModem(
                mac_address=MacAddress(mac_address),
                inet=Inet(modem_ip),
                backend_url=self.backend_url,
                write_community=community
            )
            
            # Get OFDM channel entries
            ofdm_channels = await cm.getDocsIf31CmDsOfdmChanEntry()
            
            channels = []
            for ch in ofdm_channels:
                channels.append({
                    "index": ch.index,
                    "channel_id": ch.entry.docsIf31CmDsOfdmChanChannelId if hasattr(ch.entry, 'docsIf31CmDsOfdmChanChannelId') else None,
                    "subcarrier_zero_freq": ch.entry.docsIf31CmDsOfdmChannelSubcarrierZeroFreq if hasattr(ch.entry, 'docsIf31CmDsOfdmChannelSubcarrierZeroFreq') else None,
                    "num_subcarriers": ch.entry.docsIf31CmDsOfdmChanNumActiveSubcarriers if hasattr(ch.entry, 'docsIf31CmDsOfdmChanNumActiveSubcarriers') else None,
                })
            
            return channels
        except Exception as e:
            logger.error(f"Error getting OFDM channels: {e}")
            return []
    
    async def trigger_rxmer_capture(
        self,
        mac_address: str,
        modem_ip: str,
        ofdm_channel: int = 0,
        filename: str = "rxmer_capture",
        community: str = "m0d3m1nf0"
    ) -> Dict:
        """
        Trigger RxMER (Receive Modulation Error Ratio) capture.
        
        Args:
            mac_address: Modem MAC address
            modem_ip: Modem IP address
            ofdm_channel: OFDM channel index (0-based)
            filename: Filename for capture data on TFTP server
            community: SNMP community string
            
        Returns:
            Dict with success status and capture ID
        """
        try:
            cm = AgentCableModem(
                mac_address=MacAddress(mac_address),
                inet=Inet(modem_ip),
                backend_url=self.backend_url,
                write_community=community
            )
            
            # Trigger the capture
            success = await cm.setDocsPnmCmDsOfdmRxMer(
                ofdm_idx=ofdm_channel,
                rxmer_file_name=filename,
                set_and_go=True
            )
            
            if success:
                capture_id = f"{mac_address}_{ofdm_channel}_{filename}"
                self._captures[capture_id] = {
                    "mac_address": mac_address,
                    "modem_ip": modem_ip,
                    "ofdm_channel": ofdm_channel,
                    "filename": filename,
                    "status": "triggered"
                }
                
                return {
                    "success": True,
                    "capture_id": capture_id,
                    "message": "RxMER capture triggered successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to trigger capture"
                }
                
        except Exception as e:
            logger.error(f"Error triggering RxMER capture: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_rxmer_data(
        self,
        mac_address: str,
        modem_ip: str,
        ofdm_channel: int = 0,
        community: str = "m0d3m1nf0"
    ) -> Optional[Dict]:
        """
        Retrieve RxMER spectrum data after capture completes.
        
        Returns:
            Dict with spectrum data including frequencies and MER values
        """
        try:
            cm = AgentCableModem(
                mac_address=MacAddress(mac_address),
                inet=Inet(modem_ip),
                backend_url=self.backend_url,
                write_community=community
            )
            
            # Get RxMER data
            rxmer_data = await cm.getDocsPnmCmDsOfdmRxMerEntry()
            
            if not rxmer_data:
                return None
            
            # Parse and format the data for graphing
            spectrum_data = {
                "mac_address": mac_address,
                "ofdm_channel": ofdm_channel,
                "subcarriers": [],
                "mer_values": []
            }
            
            for entry in rxmer_data:
                if hasattr(entry, 'index') and hasattr(entry, 'entry'):
                    spectrum_data["subcarriers"].append(entry.index)
                    # MER value extraction depends on PyPNM data structure
                    mer = getattr(entry.entry, 'mer_value', 0) if hasattr(entry, 'entry') else 0
                    spectrum_data["mer_values"].append(mer)
            
            return spectrum_data
            
        except Exception as e:
            logger.error(f"Error getting RxMER data: {e}")
            return None


# Singleton instance
_ofdm_manager = None

def get_ofdm_manager(backend_url: str = "http://localhost:5050") -> OfdmCaptureManager:
    """Get or create OfdmCaptureManager singleton."""
    global _ofdm_manager
    if _ofdm_manager is None:
        _ofdm_manager = OfdmCaptureManager(backend_url)
    return _ofdm_manager
