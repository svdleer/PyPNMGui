#!/usr/bin/env python3
"""
Test script for SNMP table walks - channel stats optimization.

Tests walking these MIB tables instead of individual GETs:
- docsIfDownChannelTable (DS channel config)
- docsIfSigQTable (DS signal quality)
- docsIfSigQExtTable (DS extended signal quality)
- docsIf3SignalQualityExtTable (DS RxMER)
- docsIfUpChannelTable (US channel config)
- docsIf3CmStatusUsTable (US status/power)

Usage:
    python test_channel_tables.py [modem_ip] [community]
"""

import asyncio
import json
import sys
import time
import websockets

# Configuration
AGENT_WS_URL = "ws://localhost:8000/api/agents/ws"  # Via SSH tunnel
MODEM_IP = "10.206.234.83"
COMMUNITY = "z1gg0m0n1t0r1ng"

# Table OIDs
TABLES = {
    "docsIfDownChannelTable": "1.3.6.1.2.1.10.127.1.1.1",
    "docsIfSigQTable": "1.3.6.1.2.1.10.127.1.1.4",
    "docsIfSigQExtTable": "1.3.6.1.2.1.10.127.1.3.3",
    "docsIf3SignalQualityExtTable": "1.3.6.1.4.1.4491.2.1.20.1.24",
    "docsIfUpChannelTable": "1.3.6.1.2.1.10.127.1.1.2",
    "docsIf3CmStatusUsTable": "1.3.6.1.4.1.4491.2.1.20.1.2",
}

# OID name mappings for readable output
OID_NAMES = {
    # docsIfDownChannelTable columns
    "1.3.6.1.2.1.10.127.1.1.1.1.1": "docsIfDownChannelId",
    "1.3.6.1.2.1.10.127.1.1.1.1.2": "docsIfDownChannelFrequency",
    "1.3.6.1.2.1.10.127.1.1.1.1.3": "docsIfDownChannelWidth",
    "1.3.6.1.2.1.10.127.1.1.1.1.4": "docsIfDownChannelModulation",
    "1.3.6.1.2.1.10.127.1.1.1.1.5": "docsIfDownChannelInterleave",
    "1.3.6.1.2.1.10.127.1.1.1.1.6": "docsIfDownChannelPower",
    # docsIfSigQTable columns
    "1.3.6.1.2.1.10.127.1.1.4.1.1": "docsIfSigQIncludesContention",
    "1.3.6.1.2.1.10.127.1.1.4.1.2": "docsIfSigQUnerroreds",
    "1.3.6.1.2.1.10.127.1.1.4.1.3": "docsIfSigQCorrecteds",
    "1.3.6.1.2.1.10.127.1.1.4.1.4": "docsIfSigQUncorrectables",
    "1.3.6.1.2.1.10.127.1.1.4.1.5": "docsIfSigQSignalNoise",
    "1.3.6.1.2.1.10.127.1.1.4.1.6": "docsIfSigQMicroreflections",
    # docsIfSigQExtTable columns
    "1.3.6.1.2.1.10.127.1.3.3.1.1": "docsIfSigQExtExpectedMcsBits",
    "1.3.6.1.2.1.10.127.1.3.3.1.2": "docsIfSigQExtUnerroreds",
    "1.3.6.1.2.1.10.127.1.3.3.1.3": "docsIfSigQExtCorrecteds",
    "1.3.6.1.2.1.10.127.1.3.3.1.4": "docsIfSigQExtUncorrectables",
    # docsIf3SignalQualityExtTable columns
    "1.3.6.1.4.1.4491.2.1.20.1.24.1.1": "docsIf3SignalQualityExtRxMER",
    "1.3.6.1.4.1.4491.2.1.20.1.24.1.2": "docsIf3SignalQualityExtRxMerSamples",
    # docsIfUpChannelTable columns
    "1.3.6.1.2.1.10.127.1.1.2.1.1": "docsIfUpChannelId",
    "1.3.6.1.2.1.10.127.1.1.2.1.2": "docsIfUpChannelFrequency",
    "1.3.6.1.2.1.10.127.1.1.2.1.3": "docsIfUpChannelWidth",
    "1.3.6.1.2.1.10.127.1.1.2.1.4": "docsIfUpChannelModulationProfile",
    "1.3.6.1.2.1.10.127.1.1.2.1.5": "docsIfUpChannelSlotSize",
    "1.3.6.1.2.1.10.127.1.1.2.1.6": "docsIfUpChannelTxTimingOffset",
    "1.3.6.1.2.1.10.127.1.1.2.1.7": "docsIfUpChannelRangingBackoffStart",
    "1.3.6.1.2.1.10.127.1.1.2.1.8": "docsIfUpChannelRangingBackoffEnd",
    "1.3.6.1.2.1.10.127.1.1.2.1.9": "docsIfUpChannelTxBackoffStart",
    "1.3.6.1.2.1.10.127.1.1.2.1.10": "docsIfUpChannelTxBackoffEnd",
    "1.3.6.1.2.1.10.127.1.1.2.1.15": "docsIfUpChannelType",
    # docsIf3CmStatusUsTable columns
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.1": "docsIf3CmStatusUsTxPower",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.2": "docsIf3CmStatusUsT3Timeouts",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.3": "docsIf3CmStatusUsT4Timeouts",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.4": "docsIf3CmStatusUsRangingAborteds",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.5": "docsIf3CmStatusUsModulationType",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.6": "docsIf3CmStatusUsEqData",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.7": "docsIf3CmStatusUsT3Exceededs",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.8": "docsIf3CmStatusUsIsMuted",
    "1.3.6.1.4.1.4491.2.1.20.1.2.1.9": "docsIf3CmStatusUsRangingStatus",
}


def get_oid_name(oid: str) -> str:
    """Get human-readable name for OID."""
    # Try exact match first
    if oid in OID_NAMES:
        return OID_NAMES[oid]
    # Try prefix match (strip index)
    parts = oid.rsplit('.', 1)
    if len(parts) == 2:
        base_oid = parts[0]
        if base_oid in OID_NAMES:
            return f"{OID_NAMES[base_oid]}.{parts[1]}"
    return oid


async def snmp_walk_via_api(modem_ip: str, oid: str, community: str) -> dict:
    """Walk an SNMP table via PyPNM API."""
    import aiohttp
    
    url = "http://localhost:8000/snmp/walk"
    payload = {
        "cable_modem": {
            "mac_address": "test",
            "ip_address": modem_ip,
            "snmp": {
                "snmpV2C": {
                    "community": community
                }
            }
        },
        "oid": oid
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=30) as resp:
            return await resp.json()


async def snmp_walk_direct(modem_ip: str, oid: str, community: str) -> list:
    """Walk SNMP table using pysnmp directly (for local testing)."""
    try:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData, ContextData, ObjectIdentity, ObjectType,
            SnmpEngine, UdpTransportTarget, bulk_walk_cmd
        )
    except ImportError:
        print("pysnmp not installed, skipping direct test")
        return []
    
    results = []
    engine = SnmpEngine()
    
    async for (errorIndication, errorStatus, errorIndex, varBinds) in bulk_walk_cmd(
        engine,
        CommunityData(community),
        await UdpTransportTarget.create((modem_ip, 161), timeout=5, retries=2),
        ContextData(),
        0, 25,  # nonRepeaters, maxRepetitions
        ObjectType(ObjectIdentity(oid)),
        lexicographicMode=False
    ):
        if errorIndication:
            print(f"  Error: {errorIndication}")
            break
        elif errorStatus:
            print(f"  Error: {errorStatus.prettyPrint()}")
            break
        else:
            for varBind in varBinds:
                oid_str = str(varBind[0])
                value = varBind[1].prettyPrint()
                results.append((oid_str, value))
    
    return results


def parse_table_results(results: list, table_name: str) -> dict:
    """Parse walk results into a dict keyed by ifIndex."""
    channels = {}
    
    for oid, value in results:
        # Extract column and index from OID
        # OID format: base.column.index
        parts = oid.split('.')
        if len(parts) < 2:
            continue
        
        index = parts[-1]
        col_oid = '.'.join(parts[:-1])
        col_name = get_oid_name(col_oid)
        
        if index not in channels:
            channels[index] = {'ifIndex': int(index)}
        
        # Convert value
        try:
            if value.isdigit():
                channels[index][col_name] = int(value)
            else:
                try:
                    channels[index][col_name] = float(value)
                except ValueError:
                    channels[index][col_name] = value
        except:
            channels[index][col_name] = value
    
    return channels


async def test_table_walks(modem_ip: str, community: str):
    """Test walking all channel tables."""
    print(f"\n{'='*60}")
    print(f"Testing SNMP Table Walks for Channel Stats")
    print(f"Modem: {modem_ip}")
    print(f"Community: {community}")
    print(f"{'='*60}\n")
    
    all_results = {}
    total_time = 0
    
    for table_name, table_oid in TABLES.items():
        print(f"\n--- {table_name} ({table_oid}) ---")
        
        start = time.time()
        try:
            results = await snmp_walk_direct(modem_ip, table_oid, community)
            elapsed = time.time() - start
            total_time += elapsed
            
            print(f"  Time: {elapsed:.2f}s")
            print(f"  Entries: {len(results)}")
            
            if results:
                channels = parse_table_results(results, table_name)
                all_results[table_name] = channels
                
                # Show sample
                print(f"  Channels found: {list(channels.keys())}")
                if channels:
                    sample_idx = list(channels.keys())[0]
                    print(f"  Sample (index {sample_idx}):")
                    for k, v in list(channels[sample_idx].items())[:5]:
                        print(f"    {k}: {v}")
            else:
                print("  No results")
                
        except Exception as e:
            print(f"  Error: {e}")
    
    print(f"\n{'='*60}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Tables walked: {len(TABLES)}")
    print(f"{'='*60}")
    
    # Merge results by ifIndex for downstream
    print("\n\n--- MERGED DOWNSTREAM CHANNELS ---")
    ds_channels = merge_downstream_channels(all_results)
    for idx, ch in sorted(ds_channels.items()):
        print(f"\nChannel {idx}:")
        print(f"  Frequency: {ch.get('docsIfDownChannelFrequency', 'N/A')} Hz")
        print(f"  Power: {ch.get('docsIfDownChannelPower', 'N/A')} (tenths dBmV)")
        print(f"  RxMER: {ch.get('docsIf3SignalQualityExtRxMER', 'N/A')} (tenths dB)")
        print(f"  Modulation: {ch.get('docsIfDownChannelModulation', 'N/A')}")
    
    # Merge results for upstream
    print("\n\n--- MERGED UPSTREAM CHANNELS ---")
    us_channels = merge_upstream_channels(all_results)
    for idx, ch in sorted(us_channels.items()):
        print(f"\nChannel {idx}:")
        print(f"  Frequency: {ch.get('docsIfUpChannelFrequency', 'N/A')} Hz")
        print(f"  TX Power: {ch.get('docsIf3CmStatusUsTxPower', 'N/A')} (tenths dBmV)")
        print(f"  Type: {ch.get('docsIfUpChannelType', 'N/A')}")
        print(f"  T3 Timeouts: {ch.get('docsIf3CmStatusUsT3Timeouts', 'N/A')}")
    
    return all_results


def merge_downstream_channels(all_results: dict) -> dict:
    """Merge DS table results by ifIndex."""
    merged = {}
    
    # Tables that have DS channel data
    ds_tables = [
        "docsIfDownChannelTable",
        "docsIfSigQTable", 
        "docsIfSigQExtTable",
        "docsIf3SignalQualityExtTable"
    ]
    
    for table_name in ds_tables:
        if table_name not in all_results:
            continue
        for idx, data in all_results[table_name].items():
            if idx not in merged:
                merged[idx] = {}
            merged[idx].update(data)
    
    return merged


def merge_upstream_channels(all_results: dict) -> dict:
    """Merge US table results by ifIndex."""
    merged = {}
    
    us_tables = [
        "docsIfUpChannelTable",
        "docsIf3CmStatusUsTable"
    ]
    
    for table_name in us_tables:
        if table_name not in all_results:
            continue
        for idx, data in all_results[table_name].items():
            if idx not in merged:
                merged[idx] = {}
            merged[idx].update(data)
    
    return merged


if __name__ == "__main__":
    # Allow command line overrides
    modem_ip = sys.argv[1] if len(sys.argv) > 1 else MODEM_IP
    community = sys.argv[2] if len(sys.argv) > 2 else COMMUNITY
    
    asyncio.run(test_table_walks(modem_ip, community))
