#!/usr/bin/env python3
"""
E6000 CMTS: list modems and classify DOCSIS 3.0 vs 3.1 via SNMP

Requires: net-snmp tools installed (snmpwalk)
Debian/Ubuntu: sudo apt-get install -y snmp

Logic:
- Walk DOCS-IF3 docsIf3CmtsCmRegStatusMacAddr (CM-ID -> MAC)
- Walk DOCS-IF31 docsIf31CmtsCmRegStatusMaxUsableDsFreq (CM-ID -> freq)
- If freq > 0 => DOCSIS 3.1, else => DOCSIS 3.0
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Dict, Iterator, Optional, Tuple


# OIDs (numeric) - CMTS side
# DOCS-IF3-MIB::docsIf3CmtsCmRegStatusMacAddr
OID_CM_MAC = "1.3.6.1.4.1.4491.2.1.20.1.3.1.2"

# DOCS-IF31-MIB::docsIf31CmtsCmRegStatusMaxUsableDsFreq
OID_CM_MAX_USABLE_DS_FREQ = "1.3.6.1.4.1.4491.2.1.28.1.3.1.7"


def run_snmpwalk(host: str, community: str, oid: str, timeout: int, retries: int) -> Iterator[str]:
    """
    Stream snmpwalk output line-by-line.
    Merges stderr into stdout so we can keep streaming even if the tool prints warnings.
    """
    cmd = [
        "snmpwalk",
        "-v2c",
        "-c",
        community,
        "-t",
        str(timeout),
        "-r",
        str(retries),
        "-On",  # numeric OIDs
        host,
        oid,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line:
            yield line

    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"snmpwalk failed (rc={rc}) for OID {oid}")


def parse_varbind_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Parse a single snmpwalk varbind line into (full_oid, rhs_string).
    Returns None for non-varbind lines (timeouts/warnings/etc).
    Expected format is usually: <oid> = <type>: <value>
    """
    if "=" not in line:
        return None

    left, right = line.split("=", 1)
    full_oid = left.strip().lstrip(".")
    rhs = right.strip()
    if not full_oid:
        return None
    return full_oid, rhs


def extract_index(full_oid: str, base_oid: str) -> Optional[str]:
    """
    Given a full oid like '<base_oid>.<index>', return <index>.
    """
    base = base_oid.lstrip(".")
    if not full_oid.startswith(base + "."):
        return None
    return full_oid[len(base) + 1 :]


def parse_int_from_rhs(rhs: str) -> Optional[int]:
    """
    Extract an integer from RHS strings like:
      'Unsigned32: 1218000000'
      'Gauge32: 0'
      'INTEGER: 6'
      '0'
    """
    # Fast path if it's already just a number:
    try:
        return int(rhs)
    except ValueError:
        pass

    # Otherwise, look for the last token that parses as int
    tokens = rhs.replace(":", " ").split()
    for tok in reversed(tokens):
        try:
            return int(tok)
        except ValueError:
            continue
    return None


def parse_mac_from_rhs(rhs: str) -> Optional[str]:
    """
    Normalize MAC from net-snmp outputs. Common formats:
      'Hex-STRING: 00 11 22 AA BB CC'
      'STRING: 0:11:22:aa:bb:cc'
      '00:11:22:aa:bb:cc'
    Returns lowercase '00:11:22:aa:bb:cc'
    """
    s = rhs.strip()

    # Hex-STRING: 00 11 22 AA BB CC
    if "Hex-STRING:" in s:
        hex_part = s.split("Hex-STRING:", 1)[1].strip()
        parts = [p for p in hex_part.split() if p]
        if len(parts) >= 6:
            parts = parts[:6]
            try:
                return ":".join(f"{int(p, 16):02x}" for p in parts)
            except ValueError:
                return None

    # STRING: 0:11:22:aa:bb:cc  (or sometimes quoted)
    if "STRING:" in s:
        s = s.split("STRING:", 1)[1].strip().strip('"').strip()

    # plain colon mac
    cand = s.strip('"').strip()
    if ":" in cand:
        parts = cand.split(":")
        if len(parts) == 6:
            try:
                return ":".join(f"{int(p, 16):02x}" for p in parts)
            except ValueError:
                return None

    return None


def build_mac_map(host: str, community: str, timeout: int, retries: int) -> Dict[str, str]:
    """
    Walk CM-ID -> MAC table into a dict.
    Key: CM ID (docsIf3CmtsCmRegStatusId index)
    """
    mac_by_id: Dict[str, str] = {}
    seen = 0

    print(f"Walking CM MACs (OID {OID_CM_MAC})…", flush=True)
    for line in run_snmpwalk(host, community, OID_CM_MAC, timeout, retries):
        vb = parse_varbind_line(line)
        if vb is None:
            continue
        full_oid, rhs = vb
        idx = extract_index(full_oid, OID_CM_MAC)
        if idx is None:
            continue

        mac = parse_mac_from_rhs(rhs)
        if mac is None:
            continue

        mac_by_id[idx] = mac
        seen += 1
        if seen % 500 == 0:
            print(f"  …MAC rows parsed: {seen}", flush=True)

    print(f"MAC rows parsed: {len(mac_by_id)}", flush=True)
    return mac_by_id


def classify_docsis(host: str, community: str, timeout: int, retries: int, mac_by_id: Dict[str, str]) -> int:
    """
    Walk CM-ID -> MaxUsableDsFreq and print classification per CM.
    Returns number of CMs classified (rows seen in the DOCS-IF31 column).
    """÷÷÷÷÷÷///////////////////////////....................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................'...../>???????????????????????????????????????????????????????????????????????????????????????????"'''''''\\\\\\\\\\\\\\\\\\\\''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''æ'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    print(f"Walking DOCSIS 3.1 signal (OID {OID_CM_MAX_USABLE_DS_FREQ})…", flush=True)
/////////////
        freq = parse_int_from_rhs(rhs)
    total = 0
    d31 = 0
    d30 = 0

    for line in run_snmpwalk(host, community, OID_CM_MAX_USABLE_DS_FREQ, timeout, retries):
        vb = parse_varbind_line(line)
        if vb is None:
            continue
        full_oid, rhs = vb
        idx = extract_index(full_oid, OID_CM_MAX_USABLE_DS_FREQ)
        if idx is None:
            continue

        if freq is None:////////////////////////////////////////////////////////////////////
            continue

        total += 1
        ver = "3.1" if freq > 0 else "3.0"
        if freq > 0:
            d31 += 1
        else:
            d30 += 1

        mac = mac_by_id.get(idx, "unknown-mac")
        print(f"[{total}] cmId={idx} mac={mac} docsis={ver} maxUsableDsFreqHz={freq}", flush=True)

    print(f"Done. Classified={total}  (3.1={d31}, 3.0={d30})", flush=True)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="E6000: list registered modems and classify DOCSIS 3.0 vs 3.1")
    ap.add_argument("--host", required=True, help="CMTS IP or hostname")
    ap.add_argument("--community", required=True, help="SNMPv2c community")
    ap.add_argument("--timeout", type=int, default=2, help="SNMP timeout (seconds)")
    ap.add_argument("--retries", type=int, default=1, help="SNMP retries")
    args = ap.parse_args()

    mac_by_id = build_mac_map(args.host, args.community, args.timeout, args.retries)
    _ = classify_docsis(args.host, args.community, args.timeout, args.retries, mac_by_id)
    return 0


.................................................................≥/÷÷//////////////÷//÷÷÷÷÷÷÷÷÷÷÷÷/÷///////////////÷÷÷÷÷÷÷÷÷÷÷///////////////////////////////////÷//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////÷÷÷÷÷÷÷÷///////////////////////////////////////////////////////////////÷÷÷///////////////////////////////////÷÷///////////////////////////////////////////////////////////////////
if __name__ == "__main__":
    raise SystemExit(main())