#!/usr/bin/env python3
"""
Test PyPNM integration via agent
"""
import asyncio
import logging
import sys
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet

# Add parent directory to path
sys.path.insert(0, '/Users/silvester/PythonDev/Git/PyPNMGui')

from pypnm_integration.agent_cable_modem import AgentCableModem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_agent_pypnm():
    """Test PyPNM with agent transport."""
    
    # Test modem
    mac = MacAddress("20:b8:2b:53:c5:e8")
    ip = Inet("10.214.157.17")
    
    logger.info(f"Testing PyPNM via agent for modem {mac} @ {ip}")
    
    # Create CableModem with agent transport
    cm = AgentCableModem(
        mac_address=mac,
        inet=ip,
        backend_url="http://localhost:5050",
        write_community="m0d3m1nf0"
    )
    
    logger.info("Testing SNMP GET (sysDescr)...")
    sys_descr = await cm.getSysDescr()
    logger.info(f"✅ sysDescr: {sys_descr}")
    
    logger.info("\nTesting PNM bulk configuration check...")
    bulk_config = await cm.getDocsPnmBulkDataGroup()
    logger.info(f"✅ PNM Bulk Config:")
    logger.info(f"  - IP Address Type: {bulk_config.docsPnmBulkDestIpAddrType}")
    logger.info(f"  - IP Address: {bulk_config.docsPnmBulkDestIpAddr}")
    logger.info(f"  - Path: {bulk_config.docsPnmBulkDestPath}")
    logger.info(f"  - Upload Control: {bulk_config.docsPnmBulkUploadControl}")
    
    logger.info("\nTesting setDocsPnmBulk...")
    success = await cm.setDocsPnmBulk(
        tftp_server="172.22.170.30",
        tftp_path="/opt/images/access/upload/"
    )
    if success:
        logger.info("✅ PNM bulk TFTP configured successfully!")
    else:
        logger.warning("⚠️  PNM bulk TFTP configuration failed (may be read-only)")
    
    logger.info("\nTesting downstream channel info...")
    ds_channels = await cm.getDocsIf3CmStatusUsOfdmaChanEntry()
    logger.info(f"✅ Found {len(ds_channels)} downstream channels")
    
    logger.info("\n🎉 Agent PyPNM integration test complete!")
    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_agent_pypnm())
        sys.exit(0 if result else 1)
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        sys.exit(1)
