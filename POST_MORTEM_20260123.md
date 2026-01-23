# Post-Mortem: 23 January 2026

## Summary
Successful day overall - fixed MIB issues and implemented pysnmp v7 throughout the stack. However, ~30 credits wasted on over-engineering.

## What Went Well ✅

### 1. PyPNM API MIB Configuration
- **Problem**: MIB loading errors in PyPNM container
- **Solution**: Added `PYSNMP_MIB_DIRS` environment variable pointing to pysnmp-mibs package location
- **Result**: All MIBs load perfectly, no more "Cannot find module" errors
- **Files Changed**: 
  - `docker/docker-compose.lab.yml` - Added PYSNMP_MIB_DIRS env var
  - `Dockerfile` (PyPNM repo) - Removed unnecessary net-snmp CLI tools

### 2. Clean Architecture Implementation  
- **Final Flow**: GUI → Agent → PyPNM (pysnmp) → CMTS
- **Result**: All SNMP operations use pysnmp library (Python), no subprocess calls needed
- **Benefit**: Smaller Docker images, faster builds, cleaner code

### 3. Agent PySnmp v7 Implementation
- **Solution**: Proper async implementation using `pysnmp.hlapi.v1arch.asyncio`
- **Key Code**: Used `asyncio.run()` to wrap async calls in sync context
- **Result**: Agent now uses pysnmp v7 async API successfully
- **Files Changed**: `agent/agent.py`, `agent/requirements.txt`

### 4. UTSC SNMP Control via Agent
- **Refactored**: GUI stop/start UTSC now calls agent's snmp_set capability
- **Benefit**: Centralized SNMP operations, proper error handling
- **Files Changed**: `backend/app/routes/ws_routes.py`

### 5. TFTP Support Added
- **Added**: tftpy to GUI backend requirements  
- **Result**: TFTP file cleanup now works
- **Files Changed**: `backend/requirements.txt`

## What Went Wrong ❌

### 1. Over-Engineering Waste (~30 Credits)
**Timeline of mistakes:**

1. **First Attempt**: Tried to make GUI call PyPNM API directly for SNMP
   - Wrong architecture - GUI should call agent, not PyPNM
   - Wasted: ~5 credits

2. **Second Attempt**: Tried to implement pysnmp.hlapi (old v5/v6 API)
   - Wrong API - pysnmp v7 doesn't have hlapi module structure
   - Multiple failed import attempts
   - Wasted: ~10 credits

3. **Third Attempt**: Complex pysnmp v7 implementation attempts
   - Got lost in async/sync conversion issues
   - Multiple debugging cycles
   - Wasted: ~10 credits

4. **Fourth Attempt**: Subprocess with -On flag
   - This worked! Simple solution that took 1 commit
   - But then was asked to replace with pysnmp anyway
   - Wasted: ~5 credits

**Root Cause**: Didn't ask for clarification before diving into implementation. Should have presented options:
- Option A: Subprocess + `-On` flag (simple, works)
- Option B: Implement pysnmp v7 (complex, needs research)  
- Option C: Call agent for SNMP (architectural change)

**Lesson**: Always present options and get user input before complex implementations.

## Technical Details

### PySnmp v7 Changes
- Old: `from pysnmp.hlapi import *` (deprecated)
- New: `from pysnmp.hlapi.v1arch.asyncio import get_cmd, set_cmd`
- Key: All operations are now async, need `await` or `asyncio.run()`

### Agent Implementation Pattern
```python
def execute_snmp_set(self, ...):
    result = asyncio.run(self._async_snmp_set(...))
    return result

async def _async_snmp_set(self, ...):
    snmpDispatcher = SnmpDispatcher()
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(...)
        # Process results
    finally:
        snmpDispatcher.transport_dispatcher.close_dispatcher()
```

### Environment Variables
```yaml
environment:
  - PYSNMP_MIB_DIRS=/usr/local/lib/python3.12/dist-packages/pysnmp_mibs
```

## Metrics
- **Commits**: ~15 commits
- **Credits Used**: ~60 total (~30 wasted on over-engineering)
- **Build Time**: ~5 minutes per container rebuild
- **Files Modified**: 8 files across 2 repos

## Action Items
1. ✅ Pysnmp v7 working in agent
2. ⚠️ Agent authentication token needs fixing (config issue, not code)
3. ✅ MIB warnings eliminated
4. ✅ TFTP cleanup working
5. 🔄 Test UTSC end-to-end (pending)

## Future Improvements
1. **Communication**: Always ask before complex implementations
2. **Options**: Present 2-3 options with pros/cons
3. **Check-ins**: Pause and validate approach after first attempt
4. **Architecture**: Listen to user's architectural guidance ("all SNMP via agent")

## Credits Breakdown
- Successful work: ~30 credits ✅
- Wasted on over-engineering: ~30 credits ❌
- **Total**: ~60 credits

---
**Status**: MIBs fixed ✅ | Pysnmp implemented ✅ | ~30 credits wasted ❌
