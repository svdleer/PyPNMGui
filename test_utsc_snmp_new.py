#!/usr/bin/env python3
"""
E6000 UTSC BulkPNM Spectrum Streamer (2 minutes @ 0.5 s)
------------------------------------------------------

This script controls UTSC on a CommScope E6000 using SNMP, receives PNM files
via Bulk File Transfer (BulkPNM), parses FFT power frames, and streams them
as JSON frames over WebSocket to a spectrum analyser.

Design (E6000‑correct):
- FreeRunning UTSC
- RepeatPeriod = 500 ms
- FreeRunDuration = 10000 ms (10 s window)
- Each run => 10 files via BulkPNM
- Loop 12 runs => 2 minutes total

Assumptions:
- BulkPNM destination already configured on the E6000 (TFTP/FTP/SFTP)
- Files appear in a local directory on this machine (PNM_INBOX)
- OutputFormat = fftPower

Requirements:
  pip install pysnmp websockets numpy

(Paramiko not required because files arrive via BulkPNM automatically)
"""

import time
import os
import struct
import asyncio
import json
import numpy as np
from pysnmp.hlapi import *
import websockets

# ===================== CONFIG =====================

CMTS_IP    = "10.10.10.1"
COMMUNITY  = "private"

IFINDEX = 1078534144

CENTER_FREQ = 65000000      # Hz
SPAN        = 51200000      # Hz
NUM_BINS    = 1024

REFRESH_SEC   = 0.5         # analyser refresh
TOTAL_TIME    = 120         # seconds (2 minutes)
RUN_WINDOW    = 10          # UTSC run window (seconds)

# Directory where BulkPNM delivers UTSC files
PNM_INBOX = "/data/pnm/utsc"      # CHANGE to your real BulkPNM path

# WebSocket analyser endpoint
WS_URL = "ws://127.0.0.1:9000/spectrum"

# ===================== OIDs (E6000 UTSC) =====================
# Config table: 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1
# Control table: 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1
# Status table: 1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1

OID_TRIGGERMODE  = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.3.{IFINDEX}.1"
OID_CENTERFREQ   = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.8.{IFINDEX}.1"
OID_SPAN         = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.9.{IFINDEX}.1"
OID_NUMBINS      = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.10.{IFINDEX}.1"
OID_FILENAME     = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.12.{IFINDEX}.1"
OID_OUTPUTFORMAT = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.17.{IFINDEX}.1"
OID_REPEATPERIOD = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.18.{IFINDEX}.1"
OID_FREERUNDUR   = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.19.{IFINDEX}.1"
OID_INITIATE     = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{IFINDEX}.1"
OID_STATUS       = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1.{IFINDEX}.1"

# ===================== SNMP HELPERS =====================

def snmp_set(oid, value, t="i"):
    if t == "i": val = Integer(value)
    elif t == "u": val = Gauge32(value)
    else: val = OctetString(value)

    errorIndication, errorStatus, _, _ = next(
        setCmd(
            SnmpEngine(),
            CommunityData(COMMUNITY, mpModel=1),
            UdpTransportTarget((CMTS_IP, 161), timeout=2, retries=2),
            ContextData(),
            ObjectType(ObjectIdentity(oid), val)
        )
    )

    if errorIndication or errorStatus:
        raise RuntimeError(f"SNMP SET failed on {oid}")


def snmp_get(oid):
    for (_, _, _, varBinds) in getCmd(
        SnmpEngine(),
        CommunityData(COMMUNITY, mpModel=1),
        UdpTransportTarget((CMTS_IP, 161), timeout=2, retries=2),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    ):
        for varBind in varBinds:
            return int(varBind[1])

# ===================== UTSC CONTROL =====================

def start_utsc(run_id):
    filename = f"stream_{run_id}"

    # Static configuration
    snmp_set(OID_CENTERFREQ, CENTER_FREQ, "u")
    snmp_set(OID_SPAN, SPAN, "u")
    snmp_set(OID_NUMBINS, NUM_BINS, "u")

    snmp_set(OID_OUTPUTFORMAT, 5, "i")     # fftAmplitude (better visualization)
    snmp_set(OID_FILENAME, filename, "s")
    snmp_set(OID_TRIGGERMODE, 2, "i")      # FreeRunning
    snmp_set(OID_REPEATPERIOD, 500000, "u")   # 500ms in microseconds
    snmp_set(OID_FREERUNDUR, 10000, "u")   # 10 sec in milliseconds

    # Start test
    snmp_set(OID_INITIATE, 1, "i")

    # Wait until sampleReady (status values: 1=other, 2=inactive, 3=busy, 4=sampleReady, 5=error)
    timeout = 15
    start = time.time()
    while time.time() - start < timeout:
        status = snmp_get(OID_STATUS)
        if status == 4:   # sampleReady
            break
        if status == 5:   # error
            raise RuntimeError("UTSC test failed (status=error)")
        time.sleep(0.2)
    
    if time.time() - start >= timeout:
        raise RuntimeError("Timeout waiting for UTSC completion")

# ===================== FILE HANDLING =====================

def wait_for_new_files(prefix, timeout=15):
    """Wait until 10 new UTSC files with given prefix appear in inbox."""
    start = time.time()
    collected = []

    while time.time() - start < timeout:
        files = [f for f in os.listdir(PNM_INBOX) if f.startswith(prefix)]
        if len(files) >= 10:
            collected = sorted(files)
            break
        time.sleep(0.2)

    if len(collected) < 10:
        raise RuntimeError("Timeout waiting for BulkPNM UTSC files")

    return [os.path.join(PNM_INBOX, f) for f in collected]

# ===================== PARSER =====================

def parse_utsc_fft(path):
    with open(path, "rb") as f:
        data = f.read()

    header = data[:328]
    payload = data[328:]

    # fftPower = signed int16, big endian
    bins = struct.unpack(f">{NUM_BINS}h", payload[:NUM_BINS*2])

    # Convert to dB
    spectrum = [b / 10.0 for b in bins]

    return spectrum

# ===================== WEBSOCKET STREAM =====================

async def send_frame(ws, spectrum):
    frame = {
        "timestamp": time.time(),
        "ifIndex": IFINDEX,
        "center_freq": CENTER_FREQ,
        "span": SPAN,
        "num_bins": NUM_BINS,
        "rbw": SPAN / NUM_BINS,
        "power": spectrum
    }

    await ws.send(json.dumps(frame))

# ===================== MAIN LOOP =====================

async def main():
    runs_needed = int(TOTAL_TIME / RUN_WINDOW)   # 12 runs

    async with websockets.connect(WS_URL) as ws:

        for run in range(runs_needed):

            prefix = f"stream_{run}"

            # Start UTSC run
            start_utsc(run)

            # Wait for BulkPNM delivery
            files = wait_for_new_files(prefix)

            # Stream frames to analyser
            for f in files:
                spectrum = parse_utsc_fft(f)
                await send_frame(ws, spectrum)
                await asyncio.sleep(REFRESH_SEC)

        print("Streaming finished (2 minutes)")

# ===================== ENTRY =====================

if __name__ == "__main__":
    asyncio.run(main())
