#!/usr/bin/env python3
"""Comprehensive PNM Data Test"""
import asyncio
import sys
sys.path.insert(0, '/home/svdleer/PyPNM')
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

async def test_comprehensive_pnm():
    cm = AgentCableModem(
        mac_address=MacAddress('20:b8:2b:53:c5:e8'),
        inet=Inet('10.214.157.17'),
        backend_url='http://localhost:5050',
        write_community='m0d3m1nf0'
    )
    
    print('=== Comprehensive PNM Data Test ===\n')
    
    # System Info
    print('1. System Information:')
    sys_descr = await cm.getSysDescr()
    print(f'   Vendor: {sys_descr.vendor}')
    print(f'   Model: {sys_descr.model}')
    print(f'   SW Version: {sys_descr.sw_rev}')
    print(f'   HW Version: {sys_descr.hw_rev}')
    
    # DOCSIS 3.0 Downstream Channels
    print('\n2. DOCSIS 3.0 Downstream Channels (SC-QAM):')
    try:
        ds_channels = await cm.getDocsIfDownstreamChannel()
        print(f'   Found {len(ds_channels)} channels')
        for i, ch in enumerate(ds_channels[:5]):
            freq = ch.entry.docsIfDownChannelFrequency / 1e6
            power = ch.entry.docsIfDownChannelPower
            print(f'   CH{ch.channel_id}: {freq:.1f} MHz, {power:.1f} dBmV')
    except Exception as e:
        print(f'   Error: {e}')
    
    # DOCSIS 3.0 Upstream Channels
    print('\n3. DOCSIS 3.0 Upstream Channels (SC-QAM):')
    try:
        us_channels = await cm.getDocsIfUpstreamChannelEntry()
        if us_channels and len(us_channels) > 0:
            print(f'   Found {len(us_channels)} channels')
            for i, ch in enumerate(us_channels[:3]):
                freq = ch.docsIfUpChannelFrequency / 1e6 if ch.docsIfUpChannelFrequency else 0
                width = ch.docsIfUpChannelWidth / 1000 if ch.docsIfUpChannelWidth else 0  
                print(f'   CH{i+1}: {freq:.1f} MHz, Width: {width} kHz')
        else:
            print('   No upstream channels found')
    except Exception as e:
        print(f'   Error: {e}')
    
    # DOCSIS 3.1 OFDM Downstream
    print('\n4. DOCSIS 3.1 Downstream OFDM Channels:')
    try:
        ofdm_ds = await cm.getDocsIf31CmDsOfdmChanEntry()
        if ofdm_ds and len(ofdm_ds) > 0:
            print(f'   Found {len(ofdm_ds)} OFDM channels')
            for ch in ofdm_ds[:3]:
                print(f'   OFDM: {ch}')
        else:
            print('   No OFDM channels (modem is DOCSIS 3.0)')
    except Exception as e:
        print(f'   OFDM not available: {e}')
    
    # DOCSIS 3.1 OFDMA Upstream  
    print('\n5. DOCSIS 3.1 Upstream OFDMA Channels:')
    try:
        ofdma_us = await cm.getDocsIf31CmUsOfdmaChanEntry()
        if ofdma_us and len(ofdma_us) > 0:
            print(f'   Found {len(ofdma_us)} OFDMA channels')
        else:
            print('   No OFDMA channels (modem is DOCSIS 3.0)')
    except Exception as e:
        print(f'   OFDMA not available: {e}')
    
    # Signal Quality
    print('\n6. Signal Quality / Error Stats:')
    try:
        sig_quality = await cm.getDocsIfSignalQuality()
        if sig_quality and len(sig_quality) > 0:
            print(f'   Found {len(sig_quality)} measurements')
            for i, sq in enumerate(sig_quality[:5]):
                idx = sq.index
                unerr = sq.docsIfSigQUnerroreds or 0
                corr = sq.docsIfSigQCorrecteds or 0
                uncorr = sq.docsIfSigQUncorrectables or 0
                print(f'   Index {idx}: Unerr={unerr}, Corr={corr}, Uncorr={uncorr}')
        else:
            print('   No signal quality data')
    except Exception as e:
        print(f'   Error: {e}')
    
    print('\n✅ Test Complete!')
    print('   Architecture: PyPNM → Agent Transport → Backend → Agent → cm_proxy → Modem')

asyncio.run(test_comprehensive_pnm())
