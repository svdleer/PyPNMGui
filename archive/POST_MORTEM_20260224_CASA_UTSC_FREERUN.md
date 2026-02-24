# POST-MORTEM: Casa UTSC - Wrong freerun_duration Hard Cap (600s vs 300s)
## Date: 24 February 2026
## Duration: ~3 hours (same root cause discovered in CMTS syslog after extended debugging)
## Impact: Casa UTSC InitiateTest always returned `commitFailed` — UTSC never started
## Root Cause: `MAX_FREERUN_DURATION_MS` set to 600,000ms; Casa hard cap is 300,000ms

---

## EXECUTIVE SUMMARY

Casa C100G CCAP UTSC always returned `commitFailed` on InitiateTest. The AI chased
RowStatus transitions, TriggerMode probe logic, cfg_index resolution, and atomic SNMP
PDUs for 3+ hours. The actual cause was a single wrong constant: `MAX_FREERUN_DURATION_MS = 600_000`
when Casa's hard maximum is **300,000ms (5 minutes)**. This was visible in the CMTS syslog
the entire time. The syslog was not checked until the user explicitly pasted it.

---

## CASA SYSLOG ERRORS (what should have been checked first)

```
utsc_freerun_param_check() freerun_duration:600000 is greater than 300000
k_docsPnmCmtsUtscCtrlEntry_set(), is_freerun_trigger_valid failed for ifIndex:4000048, cfg_index:3
is_freerun_trigger_valid() freerun trigger delay is less than 120, ifindex:4000048
```

These errors were present from the **first test at 22:55 on 23 Feb**. Had the syslog been
checked before any code changes, the fix would have been 1 line, 5 minutes.

---

## WHAT WENT WRONG

### Wrong constant in utsc_validation.py (commit 768cff2, 22 Feb 2026)
```python
# WRONG — set in commit 768cff2:
MAX_FREERUN_DURATION_MS: int = 600_000   # "10 minutes max" — WRONG

# CORRECT — fixed in this incident:
MAX_FREERUN_DURATION_MS: int = 300_000   # Casa hard max 300s (confirmed by syslog)
```

### Why RowStatus kept reverting to createAndWait(5)
Casa validates ALL row parameters when transitioning RowStatus to active(1).
If freerun_duration > 300000ms, Casa silently accepts the SET echo but reverts the row.
This looked like a RowStatus bug — it was actually the freerun validation rejecting the row.

### Wrong commit 768cff2 also set DEFAULT_FREERUN_DURATION_MS = 120_000
The default was correct (120s minimum). The MAX was wrong (600s instead of 300s).
The GUI was sending freerun_duration_ms=600000 from the live spectrum default.

---

## INCORRECT CHANGES MADE DURING THIS INCIDENT

The following changes were made before the root cause was found and should be reviewed:

1. `start()` now probes by TriggerMode instead of RowStatus — **CORRECT, keep**
   - Casa pre-provisions rows with fixed TriggerModes; RowStatus probe picked wrong cfg_index
   - commit: `fix: start() auto-probe by TriggerMode (cfg_index=0)`

2. `UtscStartRequest.cfg_index` default changed to 0 — **CORRECT, keep**

3. RowStatus readback loop added to `start()` — **REMOVE, unnecessary**
   - Was added to debug the revert; now that freerun is fixed, RowStatus will stick
   - The readback + notInService(2) retry path adds latency and complexity for no benefit

---

## THE FIX

**PyPNM service.py** — added Casa absolute hard cap before files≤300 check:
```python
CASA_MAX_FREERUN_MS = 300000
if freerun_duration_ms > CASA_MAX_FREERUN_MS:
    clamp_warnings.append(...)
    freerun_duration_ms = CASA_MAX_FREERUN_MS
```

**utsc_validation.py**:
```python
MAX_FREERUN_DURATION_MS: int = 300_000   # Casa hard max: 300s
```

---

## RULE: ALWAYS CHECK CMTS SYSLOG FIRST

Before any code change for a Casa SNMP `commitFailed`:

```bash
ssh access-engineering.nl "tail -50 /var/log/casa-syslog"   # or equivalent
# OR check CMTS syslog via SSH to lab server
```

The syslog will tell you **exactly** which parameter validation failed.
`commitFailed` on Casa = parameter validation error, **not** a code/OID problem.

---

## CASA C100G UTSC HARD CONSTRAINTS (DO NOT CHANGE WITHOUT SYSLOG PROOF)

See: `CASA_UTSC_CONSTRAINTS.md` in this archive directory.

These values are confirmed by Casa C100G syslog errors and must not be changed
without direct evidence from `utsc_freerun_param_check()` or similar Casa syslog output.

---

## TIMELINE

| Time (CET) | Event |
|---|---|
| 22:52 Mon 23 Feb | Quick deploy with TriggerMode probe fix — configure+start succeeded at 00:22 |
| 00:22 Tue 24 Feb | First successful start logged (freerun was 600s from earlier test, happened to work once) |
| 01:02 | Start fails again — RowStatus readback shows revert to createAndWait(5) |
| 01:15 | Casa syslog shows `is_freerun_trigger_valid failed` and `freerun_duration > 300000` |
| ~01:30 | User pastes Casa syslog — root cause immediately obvious |
| 01:50 | Fix deployed: cap 300000ms, remove 600000 |

---

## LESSONS

1. **Check the CMTS syslog before writing any code for commitFailed errors**
2. **The constant 600_000 was wrong on the day it was committed (768cff2)**
3. **RowStatus reverting = parameter validation failure, not a RowStatus bug**
4. **Do not chase symptoms (RowStatus, cfg_index, atomic PDU) without reading device logs**

---

## INCIDENT 2 (same day): Cisco cBR-8 UTSC commitFailed — missing write_community in frontend

**Score: 4 out of 4 UTSC endpoints broken. All from copy-paste errors in the same PR.**

### Root Cause
`app.js` sent `community: this.snmpCommunityRW` but **no `write_community`** in the
configure, start, and live-spectrum-start UTSC request bodies. The route fell back to
`get_cmts_write_community()` (env default), which is the Casa write community — wrong for
Cisco cBR-8. Cisco's InitiateTest SET returned `commitFailed` due to noAccess.

### Pattern
This is **identical to POST_MORTEM_20260221 Incident 3** (used read community for SET).
The fix was applied to the backend but the frontend was never updated to pass write_community.

### Fix
Added `write_community: this.snmpCommunityRW` to all three UTSC call sites in `app.js`:
- `utsc/configure`
- `utsc/start` (normal)
- `utsc/start` (live spectrum)

Commit: `fix: send write_community in all UTSC configure+start calls`

### Rule Added
**Every SNMP SET from the frontend must explicitly send both `community` AND `write_community`.**
The backend `get_cmts_write_community()` fallback is CMTS-agnostic and will be wrong for
any vendor that isn't the default in `.env`.
