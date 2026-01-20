# UTSC Issue Summary - 20 January 2026

## Problem Statement
UTSC (Upstream Triggered Spectrum Capture) stops displaying after a few images instead of capturing continuously over time.

## What Was Fixed
1. ✅ **PyPNM API** - Added configurable timing parameters (`repeat_period_ms`, `freerun_duration_ms`, `trigger_count`)
2. ✅ **Frontend Config** - Set proper defaults (3s intervals, 60s duration, 20 captures max)
3. ✅ **Frontend Request** - Now sends timing parameters to backend
4. ✅ **GUI Display Limits** - Increased from 10 to 50 historical plots
5. ✅ **WebSocket Rate Limit** - Reduced from 100ms to 10ms to show more captures
6. ✅ **Trigger Mode** - Changed from CM_MAC (6) to FreeRunning (2) for timed captures

## What Actually Works
- ✅ GUI sends correct parameters: `repeat_period_ms: 3000`, `freerun_duration_ms: 60000`, `trigger_count: 20`
- ✅ PyPNM API receives and processes parameters correctly
- ✅ PyPNM sets SNMP OIDs on CMTS:
  - `docsPnmCmtsUtscCfgRepeatPeriod` = 3,000,000 microseconds (3 seconds)
  - `docsPnmCmtsUtscCfgFreeRunDuration` = 60,000 milliseconds (60 seconds)
  - `docsPnmCmtsUtscCfgTriggerCount` = 20

## Root Cause: CMTS Firmware Limitation
**The Casa E6000 CMTS ignores the RepeatPeriod setting.**

Evidence:
```bash
# Files created every 20ms instead of every 3000ms:
-rw-rw-rw- 1 tftp tftp 3528 Jan 20 15:02 utsc_e45740f03a14_2026-01-20_15.02.57.954
-rw-rw-rw- 1 tftp tftp 3528 Jan 20 15:02 utsc_e45740f03a14_2026-01-20_15.02.57.934
-rw-rw-rw- 1 tftp tftp 3528 Jan 20 15:02 utsc_e45740f03a14_2026-01-20_15.02.57.914
# Timestamps: .954 → .934 → .914 = 20ms intervals, NOT 3000ms!
```

The CMTS captures as fast as possible (~20ms per capture) and stops after ~10 captures, regardless of:
- RepeatPeriod setting
- TriggerCount setting  
- FreeRunDuration setting
- Trigger mode (tested both FreeRunning and CM_MAC)

## Tested Configurations
| Configuration | Result |
|--------------|--------|
| trigger_mode=6 (CM_MAC), repeat_period=3000ms | 10 captures @ 20ms intervals |
| trigger_mode=2 (FreeRunning), repeat_period=3000ms | 10 captures @ 20ms intervals |
| freerun_duration=60000ms | Ignored - stops after ~200ms |
| trigger_count=20 | Ignored - stops after ~10 captures |

## CMTS Behavior
The Casa E6000 CMTS appears to have a hardcoded behavior:
1. Captures as fast as hardware allows (~20ms per capture)
2. Stops after an internal limit (~10 captures or ~200ms total duration)
3. **Completely ignores** the DOCSIS PNM MIB timing parameters

## Potential Solutions

### Option 1: Accept Current Behavior (Easiest)
- You get 10-15 rapid captures per UTSC run
- View them in the GUI history (now shows up to 50)
- Good enough for quick spectrum analysis

### Option 2: Application-Level Rate Limiting (Medium)
Modify backend to:
```python
for i in range(20):  # 20 captures
    trigger_utsc()
    wait_for_completion()
    time.sleep(3)  # 3 second delay
```
This would give you timed captures but through repeated UTSC starts instead of one continuous session.

### Option 3: Contact Casa Systems (Hard)
Report the bug:
- CMTS: Casa E6000
- Firmware: Release 13.0
- Issue: `docsPnmCmtsUtscCfgRepeatPeriod` OID not respected
- MIB: DOCS-PNM-MIB (DOCSIS 3.1 spec)

## Git Commits Made
1. `28d58a5` - PyPNM: Add configurable UTSC timing parameters
2. `b2dfec9` - PyPNMGui: Fix UTSC stopping after 5 images
3. `5e72909` - PyPNMGui: Add timing parameters to start endpoint
4. `dd1c3ac` - PyPNMGui: Set proper default timing values
5. `da0c5aa` - PyPNMGui: Use FreeRunning trigger mode
6. `b517a89` - PyPNMGui: Increase display limits and reduce rate limit

## Current State
- ✅ Code is correct and properly configured
- ✅ All parameters are sent to CMTS via SNMP
- ❌ CMTS firmware doesn't honor the parameters
- ✅ GUI now displays up to 50 captures
- ✅ GUI has faster refresh rate (10ms vs 100ms)

## Bottom Line
**This is a CMTS firmware issue, not a software bug.** The code is working correctly - the hardware just doesn't do what the DOCSIS spec says it should do.

The current implementation will show you 10-15 rapid captures, which may be sufficient for spectrum analysis purposes. If you need time-spaced captures, you'll need either a firmware fix from Casa or application-level workarounds.

---
*End of technical summary. Code changes are committed to both PyPNM and PyPNMGui repositories.*
