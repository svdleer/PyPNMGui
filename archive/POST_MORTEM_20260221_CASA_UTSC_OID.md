# POST-MORTEM: Casa UTSC Bulk Data Control Wrong OID
## Date: 21 February 2026
## Duration: ~45 minutes wasted
## Impact: UTSC bulk data control not being configured on Casa CCAP
## Root Cause: AI assistant used fabricated Casa vendor OID instead of using provided SNMP walk data

---

## EXECUTIVE SUMMARY

The Casa CCAP UTSC bulk data control table was configured with the wrong OID (`1.3.6.1.4.1.4998.1.1.115.1.3.1` - a non-existent Casa enterprise OID), causing the `is_casa` detection to always return `False` and the TFTP destination IP to never be set for UTSC file uploads.

**The correct OID** (`1.3.6.1.4.1.4491.2.1.27.1.1.1` - standard DOCS-PNM-MIB `docsPnmCcapBulkDataControl`) **was clearly visible in the user-provided SNMP walk output**, but the AI assistant ignored it and instead walked incorrect OIDs, wasting time.

---

## TIMELINE

### ~06:45 - User asked to check what is provisioned in the MIBs
- AI walked `1.3.6.1.4.1.4491.2.1.27.1.3.10.2` (UTSC config table) - correct, showed active rows
- AI walked `1.3.6.1.4.1.4998.1.1.115.1.3.1` (fabricated Casa vendor OID) - returned "No Such Object"
- AI walked `1.3.6.1.4.1.4491.2.1.27.1.3.11` - returned "No Such Object"
- AI walked `1.3.6.1.4.1.4491.2.1.27.1.3` with grep for bulk/dest/upload - no results
- AI walked `1.3.6.1.4.1.4491.2.1.27.1.3.10.1` (capabilities) - unrelated

### ~07:00 - User provided the correct OID
- User stated: `docsPnmBulkData 1.3.6.1.4.1.4491.2.1.27.1.1 is perfectly there`
- Walk confirmed: `docsPnmCcapBulkDataControlDestIpAddr.1 = Hex-STRING: AC 1D 0A 44` (172.29.10.68 - wrong IP)
- Walk confirmed: `docsPnmCcapBulkDataControlUploadControl.1 = INTEGER: autoUpload(3)`
- Walk confirmed: `docsPnmCcapBulkDataControlPnmTestSelector.1 = BITS: 00 80 usTriggeredSpectrumCapture(8)`

### ~07:10 - OID fixed and committed
- Changed `OID_BULK_DATA_CTRL_TABLE` from `1.3.6.1.4.1.4998.1.1.115.1.3.1` to `1.3.6.1.4.1.4491.2.1.27.1.1.1`
- Fixed column indexes (.4 = UploadControl, .5 = PnmTestSelector) to match actual MIB structure

---

## ROOT CAUSE

1. **Wrong OID**: Code used `1.3.6.1.4.1.4998.1.1.115.1.3.1` (Casa enterprise namespace) which does not exist on this CCAP
2. **Correct OID**: `1.3.6.1.4.1.4491.2.1.27.1.1.1` (standard DOCS-PNM-MIB `docsPnmCcapBulkDataControl`)
3. **Wrong column indexes**: UploadControl was `.5` (should be `.4`), PnmTestSelector was `.6` (should be `.5`)

## AI FAILURE MODE

- **Ignored user-provided data**: The SNMP walk output clearly showed the correct OID path, but the AI did not use it
- **Fabricated OID**: The Casa vendor OID `4998.1.1.115.1.3.1` was never verified against actual CMTS output
- **Multiple unnecessary SNMP walks**: Instead of asking the user or using the provided data, the AI ran 5+ incorrect walks
- **Assumption over evidence**: AI assumed a Casa-specific enterprise MIB existed rather than checking the standard DOCS-PNM-MIB

## ADDITIONAL ISSUES FOUND IN THIS SESSION

| Issue | Description | Fix |
|-------|-------------|-----|
| OFDMA vs Physical port | GUI auto-selected OFDMA logical ifIndex (16M) instead of physical RF port (4M) | Added Casa mapping in `UtscRfPortDiscoveryService.discover()` |
| TFTP dest IP | Bulk data control hardcoded to `172.29.10.68` instead of Casa backbone `172.22.147.18` | Changed `dest_ip` in `configure_bulk_data_control()` |
| Ethernet in port list | UTSC port list showed ethernet/mgmt interfaces | Added `exclude_patterns` filter |
| OFDMA in port list | UTSC port list showed OFDMA logical channels | Removed OFDMA pattern from `us_patterns` |

## COMMITS

| Commit | Description |
|--------|-------------|
| `69fa1f4` | fix(utsc): exclude ethernet/mgmt interfaces, use strict Casa patterns |
| `f431daa` | fix(utsc): Casa - only show physical ports for UTSC, exclude OFDMA logical channels |
| `2030c9e` | fix(utsc): Casa 100G - map OFDMA logical ifIndex to physical RF port in discovery |
| `b56068f` | fix(utsc): Casa bulk data TFTP dest_ip to 172.22.147.18 (backbone interface) |
| `ce20d9d` | fix(utsc): correct bulk data control OID to standard DOCS-PNM-MIB |

## LESSONS LEARNED

1. **ALWAYS use SNMP walk output provided by the user** - do not fabricate or assume OIDs
2. **Verify OIDs against actual CMTS output** before writing code that depends on them
3. **Standard MIBs first** - check `DOCS-PNM-MIB` (4491.2.1.27) before assuming vendor-specific OIDs
4. **Copy-paste > assumption** - when the user provides exact data, use it verbatim
