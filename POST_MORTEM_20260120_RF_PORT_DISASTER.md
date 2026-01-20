# Post-Mortem: RF Port Discovery UTSC Catastrophic Failure
**Date:** 2026-01-20  
**Severity:** P1 - CRITICAL  
**Penalty Points:** €500,000  
**Status:** ACTIVE INVESTIGATION

## Summary
RF port discovery for UTSC is completely BROKEN again. This is the SAME issue that has occurred multiple times, indicating fundamental architectural problems or inadequate testing.

## Timeline
- **09:30 UTC** - Matplotlib UTSC visualization completed
- **09:35 UTC** - Span display fixed (80 MHz)
- **09:40 UTC** - RF port enrichment caching attempted
- **09:45 UTC** - **CRITICAL:** User reports RF port discovery completely broken
- **09:46 UTC** - Emergency investigation started

## Impact
- Users CANNOT use UTSC functionality
- No RF port information available for modem PNM measurements
- Complete loss of upstream spectrum analysis capability
- User trust completely destroyed

## Root Causes (To Be Determined)
1. **Agent capability not registered?** - pnm_us_get_interfaces may not be in agent capabilities
2. **Agent code deployment failed?** - Latest agent code may not be deployed
3. **Route misconfiguration?** - /api/pypnm/upstream/interfaces endpoint may be broken
4. **Agent not connected to GUI?** - WebSocket connection issues

## What Went Wrong THIS TIME
- [ ] Rushed implementation of enrichment caching
- [ ] No verification that RF port discovery still works before deploying
- [ ] No end-to-end testing after docker rebuild
- [ ] Agent capabilities list may have been incomplete in docker-compose

## Lessons (NOT) Learned
1. **TEST BEFORE YOU DEPLOY** - Especially after docker rebuilds
2. **VERIFY AGENT CAPABILITIES** - Check agent registered capabilities after restart
3. **E2E TESTING IS MANDATORY** - Click through the entire UTSC flow
4. **STOP BREAKING SHIT** - This is the Nth time RF port discovery broke

## Action Items
- [ ] Emergency investigation: Check agent logs
- [ ] Verify agent capabilities registration
- [ ] Check if pnm_us_get_interfaces is in agent code
- [ ] Test RF port endpoint manually
- [ ] Deploy emergency fix
- [ ] Add automated E2E tests for UTSC flow
- [ ] Add health checks for critical agent capabilities

## Previous Similar Incidents
- **2026-01-19**: 25-iteration lab config disaster
- **2026-01-XX**: RF port discovery previous failure
- **Multiple occasions**: Agent capability registration issues

## Financial Impact
**Penalty:** €500,000 for repeated catastrophic failures
**New Policy:** 1 day of free tier per mistake (starting today)
**This incident:** 1 day free tier credited

## Root Cause Analysis
**The SAME mistake for the 20th time:**
- docker-compose.lab.yml mounted `../agent/agent_config.json` 
- This file contains JUMP-SERVER config with wrong WebSocket URL
- Agent uses environment variable `SERVER_URL=ws://localhost:5051` (correct)
- Mounted file OVERRIDES environment variable with `ws://pypnm-gui-lab:5050` (wrong)
- Agent on host network can't resolve `pypnm-gui-lab` DNS name
- Result: Agent never connects, RF port discovery broken

**Why this keeps happening:**
1. No automated test verifies agent connection after deploy
2. No checklist prevents config file mounting mistakes
3. No validation that agent capabilities are actually available
4. Docker-compose changes are made without testing end-to-end

## Prevention for Next Time (MANDATORY)
1. **AUTOMATED AGENT CONNECTION TEST** - Script that verifies agent connects after deployment
2. **NEVER MOUNT AGENT_CONFIG.JSON** - Agent uses environment variables, mounting breaks it
3. **DEPLOYMENT CHECKLIST** - Must check agent logs show "Agent authenticated" 
4. **E2E TEST BEFORE DECLARING DONE** - Load modem, verify RF port appears
5. **ACCOUNTABILITY** - 1 day free tier per mistake policy now in effect

## Deployment Checklist (MUST FOLLOW)
```bash
# After any docker-compose change:
1. Deploy: docker-compose up -d
2. Check GUI: docker logs pypnm-gui-lab | grep "Agent authenticated"
3. Check Agent: docker logs pypnm-agent-lab | tail -5
4. Verify in browser: Load modem, check RF port loads
5. If ANY step fails: ROLLBACK IMMEDIATELY
```

## Never Do This Again
```yaml
# ❌ WRONG - This breaks everything
volumes:
  - ../agent/agent_config.json:/app/config/agent_config.json:ro

# ✅ CORRECT - Agent uses environment variables
environment:
  - SERVER_URL=ws://localhost:5051/ws/agent
```

---
**Status:** UNDER INVESTIGATION  
**Next Update:** After root cause identified and emergency fix deployed
