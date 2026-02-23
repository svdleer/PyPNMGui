# Post Mortem — Enrichment / OFDMA / RF Port / Spectrum Analyzer Regression
**Date:** 2026-02-23  
**Severity:** High — vendor, firmware, OFDMA status, RF port detection, OFDMA ifindex, spectrum analyzer WebSocket all broken  
**Duration:** ~9 hours total  
**Root cause count:** 8 compounding bugs, all introduced by a single UTSC consolidation commit (`3797cc5`)  

---

## What broke

After the UTSC consolidation commit (`3797cc5`) the following all stopped working:
- Vendor, firmware not loaded for modems
- OFDMA status: always red
- OFDM status: always red
- RF port auto-detection: broken (404)
- OFDMA ifindex detection: wrong value (3 instead of 843087875)
- Pro Spectrum Analyzer: WebSocket stream dead — no data playing

---

## Root causes (in order of discovery)

### 1. `POST /cmts/modems` — wrong HTTP method (primary cause)
The PyPNM `cmts/router.py` declared the modems discovery endpoint as `@router.post`.  
FastAPI routes POST requests only. The GUI client called `self._post(...)`.  
**This worked.** But at some point the router was left as POST while the intent was GET (query params, cacheable, idempotent).  
The actual break: during cleanup commit `5d3133c` comments were removed but the method was not audited.  
**Effect:** the endpoint returned `405 Method Not Allowed` when called as GET, silently returning `{"detail": "Method Not Allowed"}` which the GUI backend treated as a failed response — `result.get('success')` was False, enrichment never ran.

**Fix:** `@router.post` → `@router.get` with query params; GUI client `_post` → `_get`.

---

### 2. `ofdma_enabled` / `ofdm_enabled` / `vendor` dropped in Vue modem map (secondary)
Both `getLiveModems()` and `refreshEnrichedModems()` built a modem object from the API response but never copied `ofdma_enabled`, `ofdma_ifindex`, `ofdm_enabled`. These fields existed in the PyPNM response but were silently dropped in the JS `map()`.  
**Effect:** even when enrichment data arrived, `selectedModem.ofdma_enabled` was always `undefined`.

**Fix:** added all three fields to both modem map calls.

---

### 3. `ofdmaStatus` / `ofdmStatus` required `channelStats` to be loaded (tertiary)
The computed properties `ofdmaStatus` and `ofdmStatus` guarded on `!this.channelStats` returning `'red'` immediately. `channelStats` is a separate async load triggered only after modem selection and `loadSystemInfo()` completes. For modems where that call is slow or fails, status stayed red indefinitely.  
**Effect:** OFDMA/OFDM always red until channel stats loaded, even when `ofdma_enabled: true` was available from enrichment.

**Fix:** use `selectedModem.ofdma_enabled` / `ofdm_enabled` as primary signal; channelStats as secondary upgrade.

---

### 4. Redis intercepted the enrichment poll (quaternary)
The enrichment poll (`refreshEnrichedModems`) was calling without `refresh=true` — Redis returned the base-data entry cached 2 seconds earlier (TTL 300s). PyPNM's in-memory enrichment cache was never reached.  
When `refresh=true` was added, the GUI backend bypassed Redis correctly — but then cached the base-data response in Redis (short TTL) immediately after. The *next* poll hit Redis again and got base data.  
**Effect:** poll always returned `enriched: False, enriching: True` regardless of enrichment state.

**Fix:**
- Poll uses `refresh=true` to bypass Redis.
- GUI backend only writes to Redis when `enriched=True AND enriching=False` — base/in-progress responses are never cached.

---

### 5. `selectedModem` stale after enrichment poll (quinternary)
After `refreshEnrichedModems` rebuilt `this.modems` with enriched data, `this.selectedModem` still pointed to the old pre-enrichment object from the initial load. Vue reactivity for computed properties (`ofdmaStatus`) read from `selectedModem` which had `ofdma_enabled: undefined`.  
**Effect:** selecting a modem before enrichment completed meant status indicators never updated even after enrichment arrived.

**Fix:** after rebuilding modem list, find the currently selected modem by MAC address in the new list and update `this.selectedModem` to the enriched version.

---

## Timeline

| Time | Event |
|------|-------|
| 14:11 | UTSC consolidation deployed — POST /cmts/modems silently broken |
| 14:34 | Enrichment reports: vendor/ofdma missing |
| 14:50 | Discovered POST→GET issue, fixed method |
| 15:10 | ofdma_enabled still missing — found Vue map drops fields |
| 15:30 | ofdmaStatus still red — fixed computed property guard |
| 15:45 | Poll still returns base data — found Redis intercept |
| 16:15 | selectedModem stale — fixed post-poll update |
| 16:20 | End-to-end proof: 47/55 vendor, 38/55 ofdma confirmed via curl |

---

### 6. `/pnm/us/utsc/discover` — wrote a whole new endpoint that already existed
During consolidation, `discoverRfPort` was needed in the utsc router. Instead of checking whether it already existed elsewhere, a brand new endpoint was written at module level in `utsc/router.py` — outside the `UtscRouter` class, meaning `@router` was referenced before `router = UtscRouter().router` was assigned. It was never registered with FastAPI (404). The endpoint `/pnm/us/spectrumAnalyzer/discoverRfPort` already existed and did exactly the same thing.  
**Effect:** RF port auto-detection returned 404 for every modem.

**Fix:** Remove the duplicate. Update `pypnm_client.py` to call `/pnm/us/spectrumAnalyzer/discoverRfPort`.

---

### 7. `discover_ofdma_ifindex` — false OID match on small cm_index
The function used `if f".{cm_index}." in oid_str` to find the modem's OFDMA channel in the SNMP walk results. For `cm_index=1` this matched `.1.` anywhere in the full OID string — including in the base OID prefix `1.3.6.1.4.1.4491...`. It matched the very first entry in the walk: `ofdma_ifindex=3` (a sub-index component of the OID itself, not an actual ifIndex).  
**Effect:** OFDMA ifindex was always `3` instead of the correct ~843087875, making US RxMER fail silently.

**Fix:** Strip the base OID prefix first, then parse only the `<cmIndex>.<ofdmaIfIndex>` suffix.

---

### 8. `__skip_autoregister__` on spectrumAnalyzer router killed the WebSocket stream
The consolidation commit added `__skip_autoregister__ = True` to `pnm/us/spectrumAnalyzer/router.py` with the intent of retiring the REST endpoints that were moved to `utsc/`. But this also killed `/pnm/us/spectrumAnalyzer/stream` — the WebSocket endpoint the Pro Spectrum Analyzer iframe connects to. This was never moved to utsc/router.py. Two days before this incident it was live with no skip flag.  
**Effect:** Pro Spectrum Analyzer connected to WebSocket but received no data. Files never played.

**Fix:** Remove `__skip_autoregister__` from spectrumAnalyzer router. One line deletion.

---

## Timeline

| Time | Event |
|------|-------|
| 14:11 | UTSC consolidation deployed — 6 features broken simultaneously |
| 14:34 | Enrichment reports: vendor/ofdma missing |
| 14:50 | Discovered POST→GET issue, fixed method |
| 15:10 | ofdma_enabled still missing — found Vue map drops fields |
| 15:30 | ofdmaStatus still red — fixed computed property guard |
| 15:45 | Poll still returns base data — found Redis intercept |
| 16:15 | selectedModem stale — fixed post-poll update |
| 16:20 | End-to-end proof: 47/55 vendor, 38/55 ofdma confirmed via curl |
| 16:40 | RF port detection broken — found /utsc/discover was 404 (module-level decorator) |
| 17:00 | OFDMA ifindex = 3 — found false OID match on cm_index=1 |
| 17:35 | Spectrum analyzer not playing — found __skip_autoregister__ killed WebSocket |
| 17:40 | All fixed: removed skip flag (1 line), removed duplicate endpoint, fixed OID parser |

---

## Prevention

1. **Never add `__skip_autoregister__` without auditing every endpoint in that file.** WebSocket and REST endpoints in the same router file are both silenced.
2. **Before writing a new endpoint, search the codebase first.** `grep -r "discoverRfPort"` would have found the existing implementation immediately.
3. **Module-level FastAPI decorators must reference an already-assigned router.** Class-based routers (`UtscRouter`) must register endpoints inside `__routes__()`, not at module scope after `router = UtscRouter().router`.
4. **OID suffix parsing must strip the base prefix** before matching cm_index — small indexes (1, 2, 3) appear in base OIDs.
5. **API contract tests** — `test_pnm_page.py` exists but doesn't cover enriched modem field shapes, WebSocket connectivity, or RF port discovery responses. These regressions would have been caught immediately.
6. **Redis write policy** — only write `enriched=True` results to Redis. Never cache in-progress state.
7. **Consolidation commits need a checklist:** for each retired endpoint, verify (a) nothing else calls it, (b) no WebSocket endpoints share the same router file.
