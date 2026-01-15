#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/home/svdleer/PyPNM')
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

async def test_pnm_data():
    cm = AgentCableModem(
        mac_address=MacAddress('20:b8:2b:53:c5:e8'),
        inet=Inet('10.214.157.17'),
        backend_url='http://localhost:5050',
        write_community='m0d3m1nf0'
    )
    
    print('=== PyPNM SNMP Data Retrieval Test ===')
    
    print('\n1. System Info:')
    sys_descr = await cm.getSysDescr()
    print(f'   sysDescr: {sys_descr}')
    
    print('\n2. Downstream OFDM Channels:')
    ds_ofdm = await cm.getDocsIf31CmDsOfdmChanEntry()
    print(f'   Total DS OFDM channels: {len(ds_ofdm)}')
    if ds_ofdm:
        print(f'   First channel ID: {ds_ofdm[0].docsIf31CmDsOfdmChannelId}')
    
    print('\n3. PNM Bulk Config:')
    bulk_group = await cm.getDocsPnmBulkDataGroup()
    print(f'   TFTP Server: {bulk_group.docsPnmBulkDestIpAddr}')
    print(f'   TFTP Path: {bulk_group.docsPnmBulkDestPath}')
    
    print('\n✅ PyPNM SNMP integration working!')
    return True

if __name__ == '__main__':
    asyncio.run(test_pnm_data())
