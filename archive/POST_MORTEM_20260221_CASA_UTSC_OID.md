# POST-MORTEM: Casa UTSC Bulk Data Control - Repeated Wrong OIDs
## Date: 21 February 2026
## Duration: ~2 hours wasted (3 wrong OID attempts, 1 wrong SNMP community)
## Impact: UTSC bulk data control not being configured on Casa CCAP
## Root Cause: AI assistant repeatedly fabricated OIDs instead of using snmptranslate or user-provided data

---

## EXECUTIVE SUMMARY

The Casa CCAP UTSC bulk data control table was configured with the wrong OID **three times in a row**, each time requiring the user to correct the AI. The AI also used the read community (`Z1gg0@LL`) for an SNMP SET operation, despite write communities being available in `.env` files that the AI should have checked first.

---

## INCIDENT 1: Fabricated Casa vendor OID

**Wrong OID**: `1.3.6.1.4.1.4998.1.1.115.1.3.1` (non-existent Casa enterprise OID)
**Result**: `No Such Object` — `is_casa` detection always returned `False`, bulk data control never configured
**User fix**: Told the AI `docsPnmBulkData 1.3.6.1.4.1.4491.2.1.27.1.1 is perfectly there`
**AI failure**: Instead of using the user's OID, the AI walked 5+ wrong OIDs before user intervened

## INCIDENT 2: Wrong table base (used parent instead of entry OID)

**Wrong OID**: `1.3.6.1.4.1.4491.2.1.27.1.1.1` (parent node, not the entry)
**Correct OID**: `1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1` (actual entry — `docsPnmCcapBulkDataControlEntry`)
**Result**: `noCreation` error — SET targeted `docsPnmBulkDestIpAddr` (a different table) instead of `docsPnmCcapBulkDataControlDestIpAddr`
**User fix**: User said "you used the wrongggggg"  
**AI failure**: The `snmptranslate` output clearly showed `.1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1.3.1` but the AI set the table base to `...1.1.1` with columns `.1`-`.5` instead of `...1.1.1.5.1` with columns `.2`-`.6`

## INCIDENT 3: Used read community for SNMP SET

**Wrong community**: `Z1gg0@LL` (read-only)
**Correct community**: `Z1gg0Sp3c1@l` (write, from `SNMP_WRITE_COMMUNITY_CASA` in `/opt/pypnm-gui-lab/docker/.env`)
**Result**: `noAccess` error
**AI failure**: Did not check `.env` files for write communities before attempting SET. Communities were rebuilt to use `.env` files — the AI should have known this from the workspace configuration.

---

## TIMELINE

### ~06:45 - User asked to check what is provisioned in the MIBs
- AI walked UTSC config table — correct, showed active rows on physical ports
- AI walked `4998.1.1.115.1.3.1` (fabricated vendor OID) — No Such Object
- AI walked 4 more wrong OIDs — all failed

### ~07:00 - User provided correct OID (INCIDENT 1 resolved)
- User stated: `docsPnmBulkData 1.3.6.1.4.1.4491.2.1.27.1.1 is perfectly there`
- Walk confirmed existing config with wrong IP (`AC 1D 0A 44` = 172.29.10.68)
- AI set OID to `1.3.6.1.4.1.4491.2.1.27.1.1.1` — **still wrong** (parent, not entry)

### ~07:20 - AI tried SNMP SET with wrong community (INCIDENT 3)
- Used `Z1gg0@LL` (read) → `noAccess`
- Found `Z1gg0Sp3c1@l` in deployed `.env`

### ~07:25 - AI tried SET with correct community but wrong OID (INCIDENT 2)  
- SET to `...1.1.1.2.1` → `noCreation` (wrong table: `docsPnmBulkDestIpAddr`)
- AI ran `snmptranslate` showing correct OIDs at `...1.1.1.5.1.{2-6}`
- **AI still didn't use the translate output correctly** — user had to point it out

### ~08:30 - Finally correct OID and community
- Table base: `1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1`, columns `.2`-`.6`
- Manual SET with write community succeeded: `AC 16 93 12` (172.22.147.18)
- Code fixed, committed (`3bc018c`), deployed, verified

---

## ROOT CAUSE ANALYSIS

| # | What went wrong | Why |
|---|----------------|-----|
| 1 | Used fabricated Casa vendor OID `4998.1.1.115.1.3.1` | AI assumed vendor-specific MIB without verification |
| 2 | Used parent OID `...1.1.1` instead of entry `...1.1.1.5.1` | AI guessed column structure instead of using `snmptranslate` output |
| 3 | Used read community for SET | AI didn't check `.env` files for write communities |
| 4 | Ignored user-provided data multiple times | AI ran own SNMP walks instead of using data already on screen |

## ALL COMMITS THIS SESSION

| Commit | Description |
|--------|-------------|
| `69fa1f4` | fix(utsc): exclude ethernet/mgmt interfaces, use strict Casa patterns |
| `f431daa` | fix(utsc): Casa - only show physical ports, exclude OFDMA logical channels |
| `2030c9e` | fix(utsc): Casa 100G - map OFDMA logical ifIndex to physical RF port |
| `b56068f` | fix(utsc): Casa bulk data TFTP dest_ip to 172.22.147.18 (backbone) |
| `ce20d9d` | fix(utsc): OID attempt 2 — `4491.2.1.27.1.1.1` (still wrong) |
| `3bc018c` | fix(utsc): OID attempt 3 — `4491.2.1.27.1.1.1.5.1` (correct, verified via snmptranslate) |

## LESSONS LEARNED

1. **ALWAYS run `snmptranslate -On`** to get numeric OIDs — never guess MIB structure
2. **Use the user's data verbatim** — do not re-walk OIDs that have already been provided
3. **Check `.env` for communities** before any SNMP SET — read != write
4. **Standard DOCS-PNM-MIB first** — vendor OIDs under `4998.*` should never be assumed
5. **Verify OID = entry, not parent** — `snmpwalk` resolves names but the numeric OID includes the entry node
