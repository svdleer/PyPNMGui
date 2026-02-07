#!/usr/bin/env python3
"""
Test script for channel stats using SNMP table walks.
Gets same data as channel-stats endpoint but using efficient table walks.

Run on remote server: python3 test_channel_stats_tables.py
"""

import subprocess
import re
import json
import time
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration - can be overridden by command line args
MODEM_IP = sys.argv[1] if len(sys.argv) > 1 else "10.206.234.92"
CM_COMMUNITY = sys.argv[2] if len(sys.argv) > 2 else "z1gg0m0n1t0r1ng"
TIMEOUT = 5
RETRIES = 1
MAX_REPETITIONS = 25  # For bulk walk - how many OIDs to fetch per request

# OID definitions for CM tables
TABLES = {
    # Downstream SC-QAM channel table
    "docsIfDownChannelTable": {
        "oid": "1.3.6.1.2.1.10.127.1.1.1",
        "columns": {
            1: "docsIfDownChannelId",
            2: "docsIfDownChannelFrequency", 
            3: "docsIfDownChannelWidth",
            4: "docsIfDownChannelModulation",
            5: "docsIfDownChannelInterleave",
            6: "docsIfDownChannelPower",  # TenthsdBmV
        }
    },
    # Signal quality table (SC-QAM)
    "docsIfSigQTable": {
        "oid": "1.3.6.1.2.1.10.127.1.1.4",
        "columns": {
            1: "docsIfSigQIncludesContention",
            2: "docsIfSigQUnerroreds",
            3: "docsIfSigQCorrecteds",
            4: "docsIfSigQUncorrectables",
            5: "docsIfSigQSignalNoise",  # TenthdB - SNR
            6: "docsIfSigQMicroreflections",
            7: "docsIfSigQEqualizationData",
        }
    },
    # DOCSIS 3.0+ signal quality extension - RxMER
    "docsIf3SignalQualityExtTable": {
        "oid": "1.3.6.1.4.1.4491.2.1.20.1.24",
        "columns": {
            1: "docsIf3SignalQualityExtRxMER",  # TenthdB
        }
    },
    # DOCSIS 3.1 Downstream OFDM Channel Table
    "docsIf31CmDsOfdmChanTable": {
        "oid": "1.3.6.1.4.1.4491.2.1.28.1.1",
        "columns": {
            1: "docsIf31CmDsOfdmChanChannelId",
            2: "docsIf31CmDsOfdmChanIndicator",  # 1=primary, 0=non-primary
            3: "docsIf31CmDsOfdmChanSubcarrierZeroFreq",
            4: "docsIf31CmDsOfdmChanFirstActiveSubcarrierNum",
            5: "docsIf31CmDsOfdmChanLastActiveSubcarrierNum",
            6: "docsIf31CmDsOfdmChanNumActiveSubcarriers",
            7: "docsIf31CmDsOfdmChanSubcarrierSpacing",  # 1=25kHz, 2=50kHz
            8: "docsIf31CmDsOfdmChanCyclicPrefix",
            9: "docsIf31CmDsOfdmChanRollOffPeriod",
            10: "docsIf31CmDsOfdmChanPlcFreq",
            11: "docsIf31CmDsOfdmChanNumPilots",
            12: "docsIf31CmDsOfdmChanTimeInterleaverDepth",
            13: "docsIf31CmDsOfdmChanPlcTotalCodewords",
            14: "docsIf31CmDsOfdmChanPlcUnreliableCodewords",
            15: "docsIf31CmDsOfdmChanNcpTotalFields",
            16: "docsIf31CmDsOfdmChanNcpFieldCrcFailures",
            17: "docsIf31CmDsOfdmChannelPower",  # TenthdBmV
            18: "docsIf31CmDsOfdmChanMer",  # TenthdB - MER
        }
    },
    # DOCSIS 3.1 Upstream OFDMA Channel Table  
    "docsIf31CmUsOfdmaChanTable": {
        "oid": "1.3.6.1.4.1.4491.2.1.28.1.6",
        "columns": {
            1: "docsIf31CmUsOfdmaChanChannelId",
            2: "docsIf31CmUsOfdmaChanConfigChangeCt",
            3: "docsIf31CmUsOfdmaChanSubcarrierZeroFreq",
            4: "docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum",
            5: "docsIf31CmUsOfdmaChanLastActiveSubcarrierNum",
            6: "docsIf31CmUsOfdmaChanNumActiveSubcarriers",
            7: "docsIf31CmUsOfdmaChanSubcarrierSpacing",
            8: "docsIf31CmUsOfdmaChanCyclicPrefix",
            9: "docsIf31CmUsOfdmaChanRollOffPeriod",
            10: "docsIf31CmUsOfdmaChanNumSymbolsPerFrame",
            11: "docsIf31CmUsOfdmaChanTxPower",  # TenthdBmV
        }
    },
    # Upstream SC-QAM/ATDMA channel table
    "docsIfUpChannelTable": {
        "oid": "1.3.6.1.2.1.10.127.1.1.2",
        "columns": {
            1: "docsIfUpChannelId",
            2: "docsIfUpChannelFrequency",
            3: "docsIfUpChannelWidth",
            4: "docsIfUpChannelModulationProfile",
            5: "docsIfUpChannelSlotSize",
            15: "docsIfUpChannelType",  # 1=tdma, 2=atdma, 3=scdma
        }
    },
    # CM upstream status table - TX power, timeouts (ATDMA)
    "docsIf3CmStatusUsTable": {
        "oid": "1.3.6.1.4.1.4491.2.1.20.1.2",
        "columns": {
            1: "docsIf3CmStatusUsTxPower",  # TenthdBmV
            2: "docsIf3CmStatusUsT3Timeouts",
            3: "docsIf3CmStatusUsT4Timeouts",
            4: "docsIf3CmStatusUsRangingAborteds",
            5: "docsIf3CmStatusUsModulationType",
            6: "docsIf3CmStatusUsEqData",
            7: "docsIf3CmStatusUsT3Exceededs",
            8: "docsIf3CmStatusUsIsMuted",
            9: "docsIf3CmStatusUsRangingStatus",
        }
    },
}


def snmp_walk(host: str, community: str, oid: str, use_bulk: bool = True) -> dict:
    """Walk an SNMP table and return results as dict[oid] = value.
    
    Args:
        host: Target IP address
        community: SNMP community string
        oid: Base OID to walk
        use_bulk: Use snmpbulkwalk (faster) instead of snmpwalk
    """
    if use_bulk:
        cmd = [
            "snmpbulkwalk", "-v2c", "-c", community,
            "-t", str(TIMEOUT), "-r", str(RETRIES),
            "-Cr" + str(MAX_REPETITIONS),  # Max repetitions per request
            "-On",  # Numeric OIDs
            "-Oq",  # Quick output (no type info)
            host, oid
        ]
    else:
        cmd = [
            "snmpwalk", "-v2c", "-c", community,
            "-t", str(TIMEOUT), "-r", str(RETRIES),
            "-On",  # Numeric OIDs
            "-Oq",  # Quick output (no type info)
            host, oid
        ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT walking {oid}")
        return {}
    except Exception as e:
        print(f"  ERROR walking {oid}: {e}")
        return {}
    
    data = {}
    for line in output.split('\n'):
        if not line or 'No Such' in line or 'No more' in line:
            continue
        parts = line.split(' ', 1)
        if len(parts) == 2:
            oid_str, value = parts
            # Clean up value
            value = value.strip().strip('"')
            data[oid_str] = value
    
    return data


def walk_table(table_name: str, table_def: dict, host: str, community: str) -> tuple:
    """Walk a single table and return (table_name, raw_data, elapsed_time)."""
    start = time.time()
    raw_data = snmp_walk(host, community, table_def["oid"], use_bulk=True)
    elapsed = time.time() - start
    parsed = parse_table(table_name, raw_data, table_def)
    return (table_name, raw_data, parsed, elapsed)


def parse_table(table_name: str, raw_data: dict, table_def: dict) -> dict:
    """Parse raw SNMP walk data into structured per-index data."""
    base_oid = table_def["oid"]
    columns = table_def["columns"]
    
    # Result: {index: {field_name: value}}
    result = defaultdict(dict)
    
    for oid, value in raw_data.items():
        # OID format: base.1.column.index (table entry OID structure)
        # e.g., .1.3.6.1.2.1.10.127.1.1.1.1.1.3 = docsIfDownChannelId.3
        
        # Extract column and index from OID
        suffix = oid.replace(base_oid + ".", "").lstrip(".")
        parts = suffix.split(".")
        
        if len(parts) >= 2:
            # Format is typically 1.column.index for table entries
            try:
                if parts[0] == "1":  # Entry row
                    col = int(parts[1])
                    idx = int(parts[2]) if len(parts) > 2 else int(parts[1])
                else:
                    col = int(parts[0])
                    idx = int(parts[1]) if len(parts) > 1 else 0
            except ValueError:
                continue
            
            if col in columns:
                field_name = columns[col]
                result[idx][field_name] = value
    
    return dict(result)


def parse_value(value: str, field_name: str) -> any:
    """Parse SNMP value to appropriate Python type."""
    if value is None or value == "":
        return None
    
    value_str = str(value)
    
    # Check if snmpwalk already displayed with unit suffix
    # "TenthdB", "TenthdBmV" = already converted to display value
    # "dB", "dBmV" = also already converted (e.g., "6.8 dBmV")
    already_converted = any(unit in value_str for unit in ["TenthdB", "TenthdBmV", " dB", " dBmV"])
    
    # TenthdB/TenthdBmV fields - divide by 10 ONLY if not already converted
    tenth_fields = [
        "docsIfDownChannelPower",
        "docsIfSigQSignalNoise", 
        "docsIf3SignalQualityExtRxMER",
        "docsIf3CmStatusUsTxPower",
        "docsIf31CmDsOfdmChannelPower",
        "docsIf31CmDsOfdmChanMer",
        "docsIf31CmUsOfdmaChanTxPower",
    ]
    
    try:
        # Extract numeric value
        num_match = re.search(r'[-+]?\d+\.?\d*', value_str)
        if num_match:
            num = float(num_match.group())
            
            # Only divide by 10 if it's a tenth field AND not already converted by snmpwalk
            if field_name in tenth_fields and not already_converted:
                return num / 10.0
            
            if num == int(num):
                return int(num)
            return num
    except:
        pass
    
    return value


def build_channel_stats(tables_data: dict) -> dict:
    """Build channel stats structure from parsed table data."""
    
    # Downstream SC-QAM channels
    ds_scqam_channels = []
    ds_down = tables_data.get("docsIfDownChannelTable", {})
    ds_sigq = tables_data.get("docsIfSigQTable", {})
    ds_rxmer = tables_data.get("docsIf3SignalQualityExtTable", {})
    
    for idx in sorted(ds_down.keys()):
        down_data = ds_down.get(idx, {})
        sigq_data = ds_sigq.get(idx, {})
        rxmer_data = ds_rxmer.get(idx, {})
        
        channel_id = parse_value(down_data.get("docsIfDownChannelId"), "docsIfDownChannelId")
        if not channel_id:
            continue
            
        freq = parse_value(down_data.get("docsIfDownChannelFrequency"), "docsIfDownChannelFrequency")
        power = parse_value(down_data.get("docsIfDownChannelPower"), "docsIfDownChannelPower")
        modulation = parse_value(down_data.get("docsIfDownChannelModulation"), "docsIfDownChannelModulation")
        snr = parse_value(sigq_data.get("docsIfSigQSignalNoise"), "docsIfSigQSignalNoise")
        rxmer = parse_value(rxmer_data.get("docsIf3SignalQualityExtRxMER"), "docsIf3SignalQualityExtRxMER")
        
        ds_scqam_channels.append({
            "index": idx,
            "channel_id": channel_id,
            "frequency": freq,
            "frequency_mhz": freq / 1_000_000 if freq else None,
            "power": power,
            "modulation": modulation,
            "snr": snr,
            "rxmer": rxmer,
            "type": "SC-QAM",
        })
    
    # Downstream OFDM channels (DOCSIS 3.1)
    ds_ofdm_channels = []
    ds_ofdm = tables_data.get("docsIf31CmDsOfdmChanTable", {})
    
    for idx in sorted(ds_ofdm.keys()):
        ofdm_data = ds_ofdm.get(idx, {})
        
        channel_id = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanChannelId"), "docsIf31CmDsOfdmChanChannelId")
        if not channel_id:
            continue
        
        plc_freq = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanPlcFreq"), "docsIf31CmDsOfdmChanPlcFreq")
        power = parse_value(ofdm_data.get("docsIf31CmDsOfdmChannelPower"), "docsIf31CmDsOfdmChannelPower")
        mer = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanMer"), "docsIf31CmDsOfdmChanMer")
        num_subcarriers = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanNumActiveSubcarriers"), "docsIf31CmDsOfdmChanNumActiveSubcarriers")
        subcarrier_spacing = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanSubcarrierSpacing"), "docsIf31CmDsOfdmChanSubcarrierSpacing")
        first_sc = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanFirstActiveSubcarrierNum"), "docsIf31CmDsOfdmChanFirstActiveSubcarrierNum")
        last_sc = parse_value(ofdm_data.get("docsIf31CmDsOfdmChanLastActiveSubcarrierNum"), "docsIf31CmDsOfdmChanLastActiveSubcarrierNum")
        
        # Subcarrier spacing: 1=25kHz, 2=50kHz
        sc_spacing_hz = 25000 if subcarrier_spacing == 1 else 50000
        bandwidth = (num_subcarriers or 0) * sc_spacing_hz
        
        ds_ofdm_channels.append({
            "index": idx,
            "channel_id": channel_id,
            "plc_freq": plc_freq,
            "plc_freq_mhz": plc_freq / 1_000_000 if plc_freq else None,
            "power": power,
            "mer": mer,
            "num_subcarriers": num_subcarriers,
            "first_subcarrier": first_sc,
            "last_subcarrier": last_sc,
            "subcarrier_spacing": subcarrier_spacing,
            "subcarrier_spacing_khz": sc_spacing_hz / 1000,
            "bandwidth": bandwidth,
            "bandwidth_mhz": bandwidth / 1_000_000 if bandwidth else None,
            "type": "OFDM",
        })
    
    # Upstream ATDMA channels
    us_atdma_channels = []
    us_up = tables_data.get("docsIfUpChannelTable", {})
    us_status = tables_data.get("docsIf3CmStatusUsTable", {})
    
    for idx in sorted(us_up.keys()):
        up_data = us_up.get(idx, {})
        status_data = us_status.get(idx, {})
        
        channel_id = parse_value(up_data.get("docsIfUpChannelId"), "docsIfUpChannelId")
        if not channel_id:
            continue
        
        freq = parse_value(up_data.get("docsIfUpChannelFrequency"), "docsIfUpChannelFrequency")
        width = parse_value(up_data.get("docsIfUpChannelWidth"), "docsIfUpChannelWidth")
        ch_type = parse_value(up_data.get("docsIfUpChannelType"), "docsIfUpChannelType")
        tx_power = parse_value(status_data.get("docsIf3CmStatusUsTxPower"), "docsIf3CmStatusUsTxPower")
        t3_timeouts = parse_value(status_data.get("docsIf3CmStatusUsT3Timeouts"), "docsIf3CmStatusUsT3Timeouts")
        
        # Skip inactive channels (freq=0)
        if not freq or freq == 0:
            continue
        
        # Channel type: 1=tdma, 2=atdma, 3=scdma
        type_name = {1: "TDMA", 2: "ATDMA", 3: "SCDMA"}.get(ch_type, str(ch_type))
        
        us_atdma_channels.append({
            "index": idx,
            "channel_id": channel_id,
            "frequency": freq,
            "frequency_mhz": freq / 1_000_000 if freq else None,
            "width": width,
            "width_mhz": width / 1_000_000 if width else None,
            "type": type_name,
            "tx_power": tx_power,
            "t3_timeouts": t3_timeouts,
        })
    
    # Upstream OFDMA channels (DOCSIS 3.1)
    us_ofdma_channels = []
    us_ofdma = tables_data.get("docsIf31CmUsOfdmaChanTable", {})
    
    for idx in sorted(us_ofdma.keys()):
        ofdma_data = us_ofdma.get(idx, {})
        
        channel_id = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanChannelId"), "docsIf31CmUsOfdmaChanChannelId")
        if not channel_id:
            continue
        
        zero_freq = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanSubcarrierZeroFreq"), "docsIf31CmUsOfdmaChanSubcarrierZeroFreq")
        tx_power = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanTxPower"), "docsIf31CmUsOfdmaChanTxPower")
        num_subcarriers = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanNumActiveSubcarriers"), "docsIf31CmUsOfdmaChanNumActiveSubcarriers")
        subcarrier_spacing = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanSubcarrierSpacing"), "docsIf31CmUsOfdmaChanSubcarrierSpacing")
        first_sc = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum"), "docsIf31CmUsOfdmaChanFirstActiveSubcarrierNum")
        last_sc = parse_value(ofdma_data.get("docsIf31CmUsOfdmaChanLastActiveSubcarrierNum"), "docsIf31CmUsOfdmaChanLastActiveSubcarrierNum")
        
        # Subcarrier spacing: 1=25kHz, 2=50kHz
        sc_spacing_hz = 25000 if subcarrier_spacing == 1 else 50000
        bandwidth = (num_subcarriers or 0) * sc_spacing_hz
        
        us_ofdma_channels.append({
            "index": idx,
            "channel_id": channel_id,
            "zero_freq": zero_freq,
            "zero_freq_mhz": zero_freq / 1_000_000 if zero_freq else None,
            "tx_power": tx_power,
            "num_subcarriers": num_subcarriers,
            "first_subcarrier": first_sc,
            "last_subcarrier": last_sc,
            "subcarrier_spacing_khz": sc_spacing_hz / 1000,
            "bandwidth": bandwidth,
            "bandwidth_mhz": bandwidth / 1_000_000 if bandwidth else None,
            "type": "OFDMA",
        })
    
    return {
        "downstream": {
            "scqam": {
                "channels": ds_scqam_channels,
                "count": len(ds_scqam_channels),
            },
            "ofdm": {
                "channels": ds_ofdm_channels,
                "count": len(ds_ofdm_channels),
            },
        },
        "upstream": {
            "atdma": {
                "channels": us_atdma_channels,
                "count": len(us_atdma_channels),
            },
            "ofdma": {
                "channels": us_ofdma_channels,
                "count": len(us_ofdma_channels),
            },
        }
    }


def main():
    print("=" * 60)
    print("Channel Stats via Parallel Bulk Walks")
    print("=" * 60)
    print(f"Modem IP: {MODEM_IP}")
    print(f"Community: {CM_COMMUNITY}")
    print(f"Max repetitions: {MAX_REPETITIONS}")
    print()
    
    total_start = time.time()
    tables_data = {}
    
    # Walk all tables in parallel using ThreadPoolExecutor
    print("Walking all tables in parallel...")
    with ThreadPoolExecutor(max_workers=len(TABLES)) as executor:
        futures = {
            executor.submit(walk_table, name, defn, MODEM_IP, CM_COMMUNITY): name 
            for name, defn in TABLES.items()
        }
        
        for future in as_completed(futures):
            table_name = futures[future]
            try:
                name, raw_data, parsed, elapsed = future.result()
                tables_data[name] = parsed
                print(f"  {name}: {len(raw_data)} OIDs, {len(parsed)} indices, {elapsed:.2f}s")
            except Exception as e:
                print(f"  {table_name}: ERROR - {e}")
    
    total_elapsed = time.time() - total_start
    print()
    print(f"Total time (parallel): {total_elapsed:.2f}s")
    print()
    
    # Build channel stats
    print("Building channel stats...")
    channel_stats = build_channel_stats(tables_data)
    
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print()
    
    ds_scqam = channel_stats["downstream"]["scqam"]
    ds_ofdm = channel_stats["downstream"]["ofdm"]
    us_atdma = channel_stats["upstream"]["atdma"]
    us_ofdma = channel_stats["upstream"]["ofdma"]
    
    print(f"Downstream SC-QAM: {ds_scqam['count']} channels")
    print("-" * 50)
    if ds_scqam["channels"]:
        print(f"{'Ch':>3} {'Freq (MHz)':>12} {'Power':>8} {'SNR':>6} {'RxMER':>6} {'Mod':>4}")
        for ch in ds_scqam["channels"][:10]:  # First 10
            print(f"{ch['channel_id']:>3} {ch['frequency_mhz'] or 0:>12.1f} {ch['power'] or 0:>8.1f} {ch['snr'] or 0:>6.1f} {ch['rxmer'] or 0:>6.1f} {ch['modulation'] or '':>4}")
        if len(ds_scqam["channels"]) > 10:
            print(f"  ... and {len(ds_scqam['channels']) - 10} more")
    print()
    
    print(f"Downstream OFDM: {ds_ofdm['count']} channels")
    print("-" * 50)
    if ds_ofdm["channels"]:
        print(f"{'Ch':>3} {'PLC (MHz)':>12} {'BW (MHz)':>10} {'Power':>8} {'MER':>6} {'Subcarriers':>12}")
        for ch in ds_ofdm["channels"]:
            print(f"{ch['channel_id']:>3} {ch['plc_freq_mhz'] or 0:>12.1f} {ch['bandwidth_mhz'] or 0:>10.1f} {ch['power'] or 0:>8.1f} {ch['mer'] or 0:>6.1f} {ch['num_subcarriers'] or 0:>12}")
    print()
    
    print(f"Upstream ATDMA: {us_atdma['count']} channels")
    print("-" * 50)
    if us_atdma["channels"]:
        print(f"{'Ch':>3} {'Freq (MHz)':>12} {'Width':>8} {'TxPwr':>8} {'Type':>10} {'T3':>4}")
        for ch in us_atdma["channels"]:
            print(f"{ch['channel_id']:>3} {ch['frequency_mhz'] or 0:>12.2f} {ch['width_mhz'] or 0:>8.2f} {ch['tx_power'] or 0:>8.1f} {ch['type']:>10} {ch['t3_timeouts'] or 0:>4}")
    print()
    
    print(f"Upstream OFDMA: {us_ofdma['count']} channels")
    print("-" * 50)
    if us_ofdma["channels"]:
        print(f"{'Ch':>3} {'Zero (MHz)':>12} {'BW (MHz)':>10} {'TxPwr':>8} {'Subcarriers':>12}")
        for ch in us_ofdma["channels"]:
            print(f"{ch['channel_id']:>3} {ch['zero_freq_mhz'] or 0:>12.1f} {ch['bandwidth_mhz'] or 0:>10.1f} {ch['tx_power'] or 0:>8.1f} {ch['num_subcarriers'] or 0:>12}")
    print()
    
    # Output JSON summary
    print("=" * 60)
    print("SUMMARY:")
    print("=" * 60)
    print(f"DS SC-QAM: {ds_scqam['count']}, DS OFDM: {ds_ofdm['count']}")
    print(f"US ATDMA: {us_atdma['count']}, US OFDMA: {us_ofdma['count']}")


if __name__ == "__main__":
    main()
