# CASA C100G UTSC HARD CONSTRAINTS
## Confirmed by syslog: 24 February 2026
## Source: Casa C100G syslog (smm7: snmpd) — these are firmware-enforced limits

> **WARNING: DO NOT CHANGE THESE VALUES WITHOUT DIRECT SYSLOG PROOF FROM A CASA DEVICE**
> These are not guesses. They come from `utsc_freerun_param_check()` and
> `is_freerun_trigger_valid()` in Casa's SNMP agent. Wrong values → commitFailed
> on InitiateTest with NO useful error in the API response.

---

## Timing Constraints

| Parameter | Min | Max | Default | Source |
|---|---|---|---|---|
| `repeat_period_ms` | **100ms** | 60,000ms | 400ms | syslog: `RepeatPeriod >= 100ms` |
| `freerun_duration_ms` | **120,000ms (120s)** | **300,000ms (300s)** | 120,000ms | syslog: `freerun trigger delay < 120` + `freerun_duration > 300000` |
| files per run | 1 | **300** | — | syslog: `FreeRunDuration / RepeatPeriod <= 300` |

## Code Locations

- `PyPNMGui/backend/app/core/utsc_validation.py` — `UtscLimits` dataclass
- `PyPNM/src/pypnm/api/routes/pnm/us/utsc/service.py` — Casa clamp block (`if is_casa:`)

## Current Values (as of 24 Feb 2026)

```python
# utsc_validation.py — UtscLimits (Casa vendor)
MIN_REPEAT_PERIOD_MS     = 100        # Casa minimum: 100ms
MAX_REPEAT_PERIOD_MS     = 60_000     # 60s max
DEFAULT_REPEAT_PERIOD_MS = 400        # 400ms: satisfies 120s/300files rule

MIN_FREERUN_DURATION_MS  = 120_000    # Casa minimum: 120s
MAX_FREERUN_DURATION_MS  = 300_000    # Casa HARD MAX: 300s  ← confirmed syslog 24 Feb 2026
DEFAULT_FREERUN_DURATION = 120_000    # 120s (at minimum)
MAX_CAPTURE_FILE_COUNT   = 300        # FreeRun / Repeat <= 300
```

```python
# service.py — Casa clamp block
CASA_MAX_FREERUN_MS = 300000   # absolute hard cap BEFORE files<=300 check
```

## Syslog Messages That Confirm These Values

```
# freerun > 300s:
utsc_freerun_param_check() freerun_duration:600000 is greater than 300000

# freerun < 120s:
is_freerun_trigger_valid() freerun trigger delay is less than 120, ifindex:4000048
k_docsPnmCmtsUtscCtrlEntry_set(), is_freerun_trigger_valid failed for ifIndex:4000048, cfg_index:3
```

## How RowStatus Revert Works on Casa

Casa validates ALL row parameters when RowStatus transitions `createAndWait(5) → active(1)`.
If ANY parameter is out of range, Casa:
1. Echoes `active(1)` in the SNMP SET response (looks like success)
2. Immediately reverts the row back to `createAndWait(5)`
3. Returns `commitFailed` when InitiateTest is attempted

**This means:** RowStatus reverting = parameter validation failure. Check syslog, not SNMP logic.

## How to Check Casa Syslog

```bash
ssh access-engineering.nl "tail -50 /path/to/casa/syslog"
# The relevant lines contain: utsc_freerun_param_check, is_freerun_trigger_valid,
# k_docsPnmCmtsUtscCtrlEntry_set
```

## Active UTSC Ports on Lab Casa C100G (172.16.6.201)

| ifIndex | Description | cfg_index | TriggerMode |
|---|---|---|---|
| 4000048 | Upstream Physical Interface 0/6.0 | 3 | 2 (freeRunning) |

Only one port has modems and a pre-provisioned UTSC ctrl entry.
Casa will return `No Such Instance` for any other ifIndex on the ctrl table.
