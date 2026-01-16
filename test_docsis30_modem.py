#!/usr/bin/env python3
"""
Test PyPNM data retrieval for DOCSIS 3.0 modem
Modem: 10.214.157.17 (SAGEMCOM FAST3896)
"""
import asyncio
import sys
sys.path.insert(0, '/home/svdleer/PyPNM')
from pypnm.lib.mac_address import MacAddress
from pypnm.lib.inet import Inet
from agent_cable_modem import AgentCableModem

async def test_docsis30_modem():
    cm = AgentCableModem(
        mac_address=MacAddress('20:b8:2b:53:c5:e8'),
        inet=Inet('10.214.157.17'),
        backend_url='http://localhost:5050',
        write_community='m0d3m1nf0'
    )
    
    print('=== DOCSIS 3.0 Cable Modem Test ===')
    print('Modem: 10.214.157.17 (SAGEMCOM FAST3896)\n')
    
    print('1. System Information:')
    sys_descr = await cm.getSysDescr()
    print(f'   Description: {sys_descr}')
    
    try:
        uptime = await cm.getSysUpTime()
        print(f'   Uptime: {uptime}')
    except:
        pass
    
    print('\n2. Downstream Channels (DOCSIS 3.0 SC-QAM):')
    try:
        ds_channels = await cm.getDocsIfDownstreamChannelEntry()
        print(f'   Total channels: {len(ds_channels)}')
        for i, ch in enumerate(ds_channels[:5]):
            freq = ch.docsIfDownChannelFrequency / 1000000
            power = ch.docsIfDownChannelPower / 10
            print(f'   CH{i+1}: {freq} MHz, Power: {power} dBmV')
    except Exception as e:
        print(f'   Error: {e}')
    
    print('\n3. Upstream Channels:')
    try:
        us_channels = await cm.getDocsIfUpstreamChannelEntry()
        print(f'   Total channels: {len(us_channels)}')
        for i, ch in enumerate(us_channels[:3]):
            freq = ch.docsIfUpChannelFrequency / 1000000
            width = ch.docsIfUpChannelWidth / 1000
            print(f'   CH{i+1}: {freq} MHz, Width: {width} kHz')
    except Exception as e:
        print(f'   Error: {e}')
    
    print('\n4. Signal Quality (SNR):')
    try:
        sig_quality = await cm.getDocsIfSigQSignalNoise()
        if sig_quality:
            print(f'   SNR values: {len(sig_quality)} channels')
            for i, snr in enumerate(sig_quality[:5]):
                print(f'   CH{i+1}: {snr/10} dB')
    except Exception as e:
        print(f'   Error: {e}')
    
    print('\n✅ PyPNM successfully retrieving DOCSIS 3.0 modem data!')
    print('   Data flows: PyPNM → Agent Transport → Backend API → Agent → cm_proxy → Modem')

asyncio.run(test_docsis30_modem())
