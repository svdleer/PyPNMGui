#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/home/svdleer/PyPNM')
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

async def show_data():
    cm = AgentCableModem(
        mac_address=MacAddress('20:b8:2b:53:c5:e8'),
        inet=Inet('10.214.157.17'),
        backend_url='http://localhost:5050',
        write_community='m0d3m1nf0'
    )
    
    print('=' * 60)
    print('PyPNM Data Retrieved from Modem 10.214.157.17')
    print('=' * 60)
    
    print('\n1. SYSTEM INFORMATION:')
    sys_descr = await cm.getSysDescr()
    print(f'   Vendor:     {sys_descr.vendor}')
    print(f'   Model:      {sys_descr.model}')
    print(f'   HW Rev:     {sys_descr.hw_rev}')
    print(f'   SW Rev:     {sys_descr.sw_rev}')
    print(f'   Boot Rev:   {sys_descr.boot_rev}')
    
    print('\n2. DOWNSTREAM CHANNELS (DOCSIS 3.0):')
    ds = await cm.getDocsIfDownstreamChannel()
    print(f'   Total Channels: {len(ds)}')
    print('   ---')
    for i, ch in enumerate(ds[:5]):
        freq_mhz = ch.entry.docsIfDownChannelFrequency / 1e6
        power_dbmv = ch.entry.docsIfDownChannelPower
        width_mhz = ch.entry.docsIfDownChannelWidth / 1e6
        mod = ch.entry.docsIfDownChannelModulation
        print(f'   CH {ch.channel_id:2d}: {freq_mhz:6.1f} MHz | Power: {power_dbmv:5.1f} dBmV | Width: {width_mhz:.1f} MHz | Mod: {mod}')
    if len(ds) > 5:
        print(f'   ... and {len(ds) - 5} more channels')
    
    print('\n3. SIGNAL QUALITY (Error Counters):')
    sig = await cm.getDocsIfSignalQuality()
    print(f'   Total Measurements: {len(sig)}')
    print('   ---')
    for i, sq in enumerate(sig[:5]):
        idx = sq.index if hasattr(sq, 'index') else i+1
        unerr = sq.docsIfSigQUnerroreds or 0
        corr = sq.docsIfSigQCorrecteds or 0
        uncorr = sq.docsIfSigQUncorrectables or 0
        micro = sq.docsIfSigQMicroreflections or 0
        print(f'   IF {idx:2d}: Unerr={unerr:10d} | Corr={corr:8d} | Uncorr={uncorr:6d} | Micro={micro}')
    if len(sig) > 5:
        print(f'   ... and {len(sig) - 5} more measurements')
    
    print('\n' + '=' * 60)
    print('PyPNM Integration: FULLY OPERATIONAL')
    print('=' * 60)

asyncio.run(show_data())
