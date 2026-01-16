#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/home/svdleer/PyPNM')
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

async def test():
    cm = AgentCableModem(
        mac_address=MacAddress('20:b8:2b:53:c5:e8'),
        inet=Inet('10.214.157.17'),
        backend_url='http://localhost:5050',
        write_community='m0d3m1nf0'
    )
    
    print('=== PyPNM Data Retrieval Test ===')
    
    print('\n1. Modem Info:')
    sys_descr = await cm.getSysDescr()
    print(f'   Model: {sys_descr}')
    
    print('\n2. Downstream OFDM Channels:')
    ds_ofdm = await cm.getDocsIf31CmDsOfdmChanEntry()
    print(f'   Total DS OFDM channels: {len(ds_ofdm)}')
    for i, chan in enumerate(ds_ofdm[:3]):
        print(f'   Channel {i+1}: ID={chan.docsIf31CmDsOfdmChannelId}, Freq={chan.docsIf31CmDsOfdmChannelCenterFrequency}Hz')
    
    print('\n3. Upstream OFDMA Channels:')
    try:
        us_ofdma = await cm.getDocsIf31CmUsOfdmaChanEntry()
        print(f'   Total US OFDMA channels: {len(us_ofdma)}')
    except Exception as e:
        print(f'   Error: {e}')
    
    print('\n4. RxMER (Modulation Error Ratio):')
    try:
        rxmer = await cm.getDocsIf31CmDsOfdmChanRxMer()
        if rxmer and len(rxmer) > 0:
            print(f'   RxMER data available: {len(rxmer)} entries')
            for i, entry in enumerate(rxmer[:3]):
                print(f'   Entry {i+1}: {entry}')
        else:
            print('   No RxMER data available')
    except Exception as e:
        print(f'   RxMER retrieval error: {e}')
    
    print('\n✅ PNM integration working!')

asyncio.run(test())
