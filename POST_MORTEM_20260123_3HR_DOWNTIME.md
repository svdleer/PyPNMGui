# POST-MORTEM: 3 Hour Downtime - Lab Environment
## Date: 23 January 2026
## Duration: ~3 hours (16:00-19:00 CET)
## Impact: Complete lab environment unavailable
## Root Cause: Configuration file corruption + missing agent configuration

---

## EXECUTIVE SUMMARY

The lab environment experienced 3 hours of downtime due to multiple configuration issues that compounded:

1. **Critical**: `docker-compose.lab.yml` file corruption with invalid YAML characters
2. **Critical**: Agent configuration had wrong connection URL (couldn't reach GUI)
3. **Critical**: Agent configuration missing SNMP community
4. **Major**: Agent configuration had wrong agent_id causing auth failures

**Contributing Factor**: AI assistant made incorrect architecture assumptions and wasted 24+ hours prior to this incident, leaving environment in unstable state.

---

## TIMELINE

### 16:00 - Initial Issue
- User provided "corrected" docker-compose.lab.yml file
- File contained invalid characters: `,,,,,,,,,,,,,,,,,,,,,,,,,,,.?version: '3.8'`
- User requested building container on remote server

### 16:15 - First Build Failure
- YAML parsing error due to corrupted first line
- Error: `expected the node content, but found ','`
- Quick fix: Removed invalid characters from line 1

### 16:20 - Build Started Successfully
- Container built without issues
- Docker images created correctly
- Services started

### 16:25 - Agent Authentication Failure Discovered
- Agent connecting but auth failing: "invalid token"
- Agent repeatedly reconnecting every 5 seconds
- Logs showed: `WARNING in simple_ws: Auth failed for lab-agent-local: invalid token`

### 16:30-17:30 - Wrong Diagnosis #1
- Initially thought token mismatch between agent and GUI
- Checked agent config location
- Found config at `/opt/pypnm-gui-lab/agent/agent_config.json`
- Agent was using token: `dev-token-change-in-production`

### 17:30 - First Config Update (INCORRECT)
- Updated agent config with:
  - `agent_id: lab-agent-local` ✅
  - `url: ws://pypnm-gui-lab:5050/ws/agent` ❌ (WRONG - agent on host network)
  - `auth_token: dev-token-change-in-production` ✅

### 17:35 - Agent Still Failing
- Auth failures continued
- Agent couldn't connect at all now
- Realized: Agent on `host` network can't resolve `pypnm-gui-lab` hostname

### 18:00 - User Intervention
- User asked: "are the correct communities configured?"
- User asked: "are the dockers on the correct network (host)?"
- Investigation revealed multiple issues

### 18:15 - Network Analysis
- **Discovered**: Agent is on `network_mode: host` (correct for CMTS access)
- **Discovered**: GUI is on bridge network `pypnm-net`
- **Problem**: Agent URL pointed to bridge network hostname
- **Problem**: No SNMP community configured in agent config

### 18:30 - Second Config Update (CORRECT)
- Fixed agent config:
  - `url: ws://localhost:5051/ws/agent` ✅ (host network uses localhost)
  - Added `default_community: Z1gg0Sp3c1@l` ✅
  - Added TFTP server config with FTP credentials ✅
  - Port corrected to 5051 (host port mapping)

### 19:00 - System Restored
- Agent authenticated successfully
- All capabilities available
- System operational

---

## ROOT CAUSES

### 1. Docker-Compose File Corruption
**What Happened**: File started with invalid characters `,,,,,,,,,,,,,,,,,,,,,,,,,,,.?version:`

**Why It Happened**: 
- Unknown - possibly copy/paste error, editor corruption, or file system issue
- File was provided by user as "correct" version

**Impact**: 
- Initial build completely failed
- Delayed diagnosis of actual problems by 15 minutes

**Why Not Caught Earlier**:
- File was accepted without validation
- No pre-build YAML syntax check

### 2. Agent Configuration - Wrong Network URL
**What Happened**: Agent config had `ws://pypnm-gui-lab:5050/ws/agent`

**Why It Was Wrong**:
- Agent runs on `host` network mode (for direct CMTS access)
- `pypnm-gui-lab` is a bridge network hostname
- Host network containers can't resolve bridge network hostnames
- Should have been `ws://localhost:5051/ws/agent`

**Impact**:
- Agent couldn't connect to GUI at all
- Complete loss of agent functionality
- ~2 hours troubleshooting

**Why Not Caught Earlier**:
- Agent config not reviewed during deployment
- No network topology validation
- Previous working config had different network setup

### 3. Missing SNMP Community Configuration
**What Happened**: Agent config had no `default_community` setting

**Why Critical**:
- Agent can't communicate with CMTS without SNMP community string
- All UTSC operations would fail silently
- PyPNM API calls would fail

**Impact**:
- Even after fixing network, UTSC wouldn't work
- Would have required additional debugging session

**Why Not Caught Earlier**:
- No configuration validation against requirements
- Template agent config didn't include CMTS-specific settings

### 4. Wrong Agent ID Initially
**What Happened**: Config had `agent_id: docker-agent-01` instead of `lab-agent-local`

**Impact**:
- Auth failures even with correct token
- GUI expects specific agent ID format

---

## CONTRIBUTING FACTORS

### Prior Context Loss (24+ hours)
**From Previous Session**:
- AI assistant lost context about architecture multiple times
- Made wrong assumptions about data flow (Frontend → PyPNM → Agent instead of Frontend → PyPNM → CMTS)
- Suggested removing working code
- Multiple rollbacks required

**Impact on This Incident**:
- Environment left in unstable state
- Configuration files not properly validated
- No clear documentation of correct setup
- Increased complexity making diagnosis harder

### Lack of Configuration Validation
**What Was Missing**:
- No pre-deployment config validation
- No YAML syntax checking before git commit
- No agent config schema validation
- No network topology verification

### No Staging/Testing Environment
**Problem**:
- Changes deployed directly to lab environment
- No ability to test configuration before applying
- Build takes 5+ minutes, making iteration slow

### Poor Documentation
**What Was Missing**:
- No network topology diagram
- No agent configuration requirements document
- No deployment checklist
- No rollback procedure

---

## WHAT WENT WRONG (Technical Details)

### 1. YAML File Corruption
```yaml
# WRONG (corrupt file):
,,,,,,,,,,,,,,,,,,,,,,,,,,,.?version: '3.8'

# CORRECT:
version: '3.8'
```

**Error Message**:
```
yaml.parser.ParserError: while parsing a block node
expected the node content, but found ','
  in "./docker-compose.lab.yml", line 1, column 1
```

### 2. Network Configuration Mismatch
```yaml
# Agent runs on host network:
agent-lab:
  network_mode: host  # Can access 172.16.6.x directly

# GUI runs on bridge network:
gui-server-lab:
  networks:
    - pypnm-net  # Isolated bridge network
```

**Agent Config - WRONG**:
```json
{
  "pypnm_server": {
    "url": "ws://pypnm-gui-lab:5050/ws/agent"  // Can't resolve from host network!
  }
}
```

**Agent Config - CORRECT**:
```json
{
  "pypnm_server": {
    "url": "ws://localhost:5051/ws/agent"  // Host network uses localhost + host port
  }
}
```

### 3. Missing SNMP Configuration
```json
// WRONG (missing):
"cmts_access": {
  "snmp_direct": true
  // No community string!
}

// CORRECT:
"cmts_access": {
  "snmp_direct": true,
  "default_community": "Z1gg0Sp3c1@l"
}
```

---

## IMPACT ASSESSMENT

### Availability Impact
- **Lab Environment**: 100% unavailable for 3 hours
- **UTSC Testing**: Completely blocked
- **Development Work**: Halted

### Time Lost
- **Downtime**: 3 hours
- **Prior Issues**: 24+ hours wasted on wrong assumptions
- **Total Time Lost**: ~27 hours

### User Frustration
- **Level**: Maximum
- **Confidence in AI**: Destroyed
- **Trust**: None remaining

---

## LESSONS LEARNED

### 1. ALWAYS Validate Configuration Files
**Before Deployment**:
- ✅ Run YAML syntax validation
- ✅ Check for non-ASCII characters
- ✅ Validate against schema if available
- ✅ Review network configuration matches deployment target

### 2. NEVER Trust "Corrected" Files Blindly
**Problem**: User provided file assumed to be correct
**Solution**: Always validate, even user-provided files

### 3. Understand Network Topology FIRST
**Problem**: Didn't verify agent network mode before configuration
**Solution**: 
- Document network topology
- Verify network mode matches config
- Test connectivity before declaring success

### 4. Configuration Must Match Network Mode
**Rule**: 
- `network_mode: host` → use `localhost` + host-mapped ports
- `networks: [bridge]` → use container names + internal ports

### 5. Include ALL Required Config Fields
**Problem**: Template config missing critical fields
**Solution**:
- Maintain complete config template with all required fields
- Document which fields are mandatory for each deployment type
- Validate config completeness before deployment

### 6. Stop Making Assumptions
**From Prior Sessions**:
- Don't assume architecture without verification
- Don't remove code without understanding purpose
- Don't suggest major changes during debugging
- ASK questions before acting

---

## CORRECTIVE ACTIONS

### Immediate (Done)
- ✅ Fixed docker-compose.lab.yml corruption
- ✅ Corrected agent network URL to `localhost:5051`
- ✅ Added SNMP community configuration
- ✅ Added TFTP server configuration
- ✅ Verified agent authentication successful

### Short Term (Should Do)
- [ ] Create configuration validation script
- [ ] Document network topology with diagram
- [ ] Create agent config template with all required fields
- [ ] Add pre-deployment checklist
- [ ] Document rollback procedures

### Long Term (Must Do)
- [ ] Implement configuration schema validation
- [ ] Create staging environment for testing
- [ ] Automated configuration testing
- [ ] Network topology as code
- [ ] CI/CD pipeline with validation gates

---

## PREVENTIVE MEASURES

### 1. Pre-Deployment Validation
```bash
# Add to deployment script:
# 1. Validate YAML syntax
yamllint docker-compose.lab.yml

# 2. Check for corruption
file docker-compose.lab.yml | grep "ASCII text"

# 3. Validate agent config
python -m json.tool agent_config.json > /dev/null

# 4. Check network configuration
docker-compose config | grep network_mode
```

### 2. Configuration Checklist
**Before Deploying Agent**:
- [ ] Agent ID matches environment (lab-agent-local)
- [ ] URL matches network mode (host → localhost, bridge → container name)
- [ ] Port matches host mapping (5051 for lab)
- [ ] Auth token matches GUI configuration
- [ ] SNMP community configured
- [ ] TFTP server configured with credentials

### 3. Testing Procedure
**After Deployment**:
1. Check container status: `docker ps`
2. Check agent logs: `docker logs pypnm-agent-lab`
3. Verify authentication: `grep "Agent authenticated" logs`
4. Test agent capabilities available
5. Test SNMP connectivity to CMTS
6. Test TFTP connectivity

---

## CONCLUSION

**Root Cause**: Multiple configuration errors compounding:
1. File corruption (YAML)
2. Network configuration mismatch
3. Missing SNMP community
4. Wrong agent ID

**Primary Failure**: No configuration validation before deployment

**Secondary Failure**: Prior 24 hours of wrong assumptions left environment unstable

**Cost**: 3 hours downtime + 24 hours wasted effort = 27 hours total loss

**Prevention**: Implement configuration validation, network topology documentation, and testing procedures before deployment

---

## APPENDIX A: Correct Configuration

### docker-compose.lab.yml (Network Section)
```yaml
agent-lab:
  network_mode: host  # For direct CMTS access
  
gui-server-lab:
  networks:
    - pypnm-net  # Bridge network
  ports:
    - "5051:5050"  # Host:Container
```

### agent_config.json (Critical Fields)
```json
{
  "agent_id": "lab-agent-local",
  "pypnm_server": {
    "url": "ws://localhost:5051/ws/agent",
    "auth_token": "dev-token-change-in-production"
  },
  "cmts_access": {
    "snmp_direct": true,
    "default_community": "Z1gg0Sp3c1@l"
  },
  "tftp_server": {
    "host": "172.16.6.212",
    "username": "ftpaccess",
    "password": "ftpaccessftp"
  }
}
```

---

*Document prepared: 23 January 2026, 19:15 CET*
*Total downtime: 3 hours*
*Total time wasted (including prior issues): 27 hours*
