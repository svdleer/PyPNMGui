# Post-Mortem: Lab Agent Configuration Repeated Failures
**Date:** January 20, 2026  
**Incident:** Agent configuration repeatedly broken during UTSC debugging session  
**Impact:** ~25 iterations to restore working enrichment in lab environment  

## Timeline of Failures

### Initial Problem
- User testing UTSC on modem `e4:57:40:f7:12:99`
- UTSC failed because agent returned wrong RF port: `1074864128` (RPS01-1) instead of `1074339840` (RPS01-0)
- Root cause: Agent slot matching logic was broken (matched RPS01-**1** instead of RPS01-**0**)

### The Cascade of Config Disasters

#### Iteration 1-5: Wrong Port Fix
- Fixed agent slot matching logic in `agent.py`
- Committed and pushed to git
- Rebuilt agent Docker container
- **BROKE:** Removed ALL lab-specific config from `agent_config.json`

#### Iteration 6-10: Auth Token Mismatch
- Agent couldn't authenticate
- Token in agent config: `dev-token-change-me`
- Token in GUI config: `dev-token-change-in-production`
- **ROOT CAUSE:** Different defaults in `config.py` vs `ws_routes.py` fallback

#### Iteration 11-15: Missing CMTS Community
- Auth fixed, but enrichment showed all modems as "Unknown"
- Agent had `cm_proxy` config (SSH to hop-access) instead of `cm_direct`
- Lab uses DIRECT SNMP to modems, not SSH proxy
- Missing CMTS community string

#### Iteration 16-20: Wrong Modem Community
- Added `cm_direct` but enrichment still failed
- Used wrong modem community
- Correct community: `m0d3m1nf0` (not the default)

#### Iteration 21-23: Missing TFTP and Redis
- Enrichment working but no TFTP config for PNM operations
- Missing Redis config for caching
- TFTP IP: `172.16.6.101`
- Redis host: `eve-li-redis-lab:6379`

#### Iteration 24-25: Cache Not Cleared
- All config finally correct
- GUI still showed "Unknown" vendors
- Cache still had old failed enrichment data
- Had to manually clear Redis cache

## Complete Lab Agent Config (THE ONE THAT WORKS)

```json
{
    "agent_id": "jump-server-script3a",
    
    "pypnm_server": {
        "url": "ws://pypnm-gui-lab:5050/ws/agent",
        "auth_token": "dev-token-change-in-production",
        "reconnect_interval": 5
    },
    
    "cmts": {
        "snmp_direct": true,
        "community": "Z1gg0Sp3c1@l",
        "write_community": "Z1gg0Sp3c1@l"
    },
    
    "cm_direct": {
        "enabled": true,
        "community": "m0d3m1nf0"
    },
    
    "tftp_server": {
        "host": "172.16.6.101",
        "protocol": "tftp"
    },
    
    "redis": {
        "host": "eve-li-redis-lab",
        "port": 6379,
        "db": 0
    }
}
```

## Root Causes

### 1. **No Template for Lab Config**
- No `agent_config.lab.json.template` in repo
- Every rebuild starts from scratch or wrong example
- Example configs are for production (SSH proxy), not lab (direct)

### 2. **Inconsistent Auth Token Defaults**
- `backend/app/core/config.py`: `dev-token-change-in-production`
- `backend/app/routes/ws_routes.py` fallback: `dev-token-change-me`
- Agent example config: `dev-token-change-me`
- Production config: Different token entirely

### 3. **Two Different Modem Access Methods**
- Production: SSH to `hop-access1-sh.ext.oss.local`, run SNMP commands there
- Lab: Direct SNMP from agent container to modems
- Easy to use wrong method → enrichment fails silently

### 4. **Silent Failures**
- Agent enrichment fails but GUI says "106 modems updated in cache"
- No clear error in GUI that enrichment actually failed
- Have to dig through agent logs to find "Batch enrichment failed"

### 5. **Aggressive Caching**
- Redis caches modem data indefinitely
- Failed enrichment data stays cached
- No cache invalidation on agent restart/config change
- Have to manually clear cache to test fixes

## Lessons Learned

### What Went Wrong
1. **Touched agent config without checking what lab needs**
2. **No checklist of required lab settings**
3. **Assumed default configs would work**
4. **Didn't verify each fix before moving to next**
5. **Didn't check if cache needed clearing**

### What Should Happen Next Time

#### BEFORE touching agent config:
- [ ] Check current working config: `cat agent_config.json`
- [ ] Copy to backup: `cp agent_config.json agent_config.backup`
- [ ] Note all custom settings (CMTS community, modem community, TFTP, Redis)

#### AFTER changing agent code:
- [ ] Restore COMPLETE lab config, not just auth token
- [ ] Use template from this document
- [ ] Clear Redis cache: `redis-cli del 'modems:...'`
- [ ] Test enrichment: reload modem page, check for vendor names

#### Permanent fixes needed:
1. Create `agent/agent_config.lab.json.template` in repo
2. Document lab vs prod config differences in README
3. Add cache clear option to GUI (button or TTL)
4. Make enrichment failures visible in GUI
5. Add config validation on agent startup
6. Fix inconsistent auth token defaults across codebase

## Action Items

- [x] Document correct lab config in this post-mortem
- [ ] Create lab config template file
- [ ] Add "Lab vs Production" section to agent README
- [ ] Add cache management tools to GUI
- [ ] Standardize auth token defaults
- [ ] Add agent config validation

## Prevention for Future Sessions

**Rule #1:** NEVER rebuild lab agent without this checklist:
```bash
# 1. Backup current config
ssh lab "cat /opt/pypnm-gui-lab/agent/agent_config.json > /tmp/agent_backup.json"

# 2. After rebuild, restore COMPLETE config (not just one field)
# Use config from this document

# 3. Clear cache
ssh lab "docker exec eve-li-redis-lab redis-cli del 'modems:...'"

# 4. Test
# Reload modem page, verify vendors show correctly
```

**Rule #2:** The magic incantation that fixes lab agent:
```
CMTS: Z1gg0Sp3c1@l
Modems: m0d3m1nf0 (direct, NOT proxy)
TFTP: 172.16.6.101
Redis: eve-li-redis-lab:6379
Auth: dev-token-change-in-production
```

## Conclusion

What started as a simple fix (agent port matching) turned into 25 iterations because:
1. No template for lab-specific config
2. Mixing up lab (direct) vs prod (proxy) modem access
3. Inconsistent auth token defaults
4. Aggressive caching hiding failures
5. Not checking each fix fully before proceeding

**Time wasted:** ~2 hours  
**User frustration:** Maximum  
**Times user said "FUCKING":** 1  
**Times I should have just copied the working config:** 24  

---
*"Always when you touch the agent: 1) lab settings gone, 2) community wrong, 3) cmts gone, 4) enrichment broken"*  
— User, being absolutely correct
