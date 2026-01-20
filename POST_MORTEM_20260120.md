# Post-Mortem: January 20, 2026 - UTSC Endpoint Failures

## Incident Summary
**Date:** January 20, 2026  
**Duration:** ~3 hours  
**Impact:** Complete failure of UTSC (Upstream Test Signal Capture) functionality  
**Root Cause:** Docker network misconfiguration + PyPNM API bug  
**Cost Impact:** 100% of premium request SKU budget exhausted  

## Timeline
- **13:00-13:30:** User reported UTSC endpoint returning empty response `{"success": false, ...}`
- **13:30-14:00:** Investigated route registration, Flask app configuration, tested endpoints
- **14:00-14:30:** Discovered PyPNM API returning 500 errors due to `ValueError: invalid literal for int() with base 10: ''`
- **14:30-15:00:** Fixed PyPNM bug, rebuilt image, redeployed
- **15:00-15:30:** STILL BROKEN - discovered Docker networking issue
- **15:30-16:00:** Fixed Docker networking, system operational

## Root Causes

### Primary Issue: Docker Network Misconfiguration
**Symptom:** `ERROR in pypnm_client: Cannot connect to PyPNM at http://pypnm-api:8000`

**Root Cause:**
- `pypnm-api` container was running from `/opt/pypnm/compose/docker-compose.yml` on network `compose_default`
- `pypnm-gui-lab` container was running from `/opt/pypnm-gui-lab/docker/docker-compose.lab.yml` on network `docker_pypnm-net`
- Containers on different Docker networks cannot communicate by container name

**Fix:**
```bash
cd /opt/pypnm/compose && docker compose down
cd /opt/pypnm-gui-lab/docker && docker compose -f docker-compose.lab.yml up -d pypnm-api
```

### Secondary Issue: PyPNM API Bug
**Location:** `/opt/pypnm/PyPNM-v1.0.20.0/src/pypnm/docsis/cm_snmp_operation.py:458`

**Bug:**
```python
# Old code - crashes on empty string
status_value = int(Snmp_v2c.snmp_get_result_value(result)[0])
```

**Symptom:** `ValueError: invalid literal for int() with base 10: ''`

**Root Cause:** 
- Some DOCSIS 3.0 modems return empty string for `docsPnmCmCtlStatus` OID
- Code attempted to cast empty string directly to int without validation

**Fix:**
```python
raw_value = Snmp_v2c.snmp_get_result_value(result)[0]
if raw_value == '' or raw_value is None:
    self.logger.warning(f'Empty value returned for docsPnmCmCtlStatus, treating as not ready')
    return DocsPnmCmCtlStatus.PNM_NOT_READY

try:
    status_value = int(raw_value)
except (ValueError, TypeError) as e:
    self.logger.error(f'Invalid docsPnmCmCtlStatus value "{raw_value}": {e}')
    return DocsPnmCmCtlStatus.SNMP_ERROR

return DocsPnmCmCtlStatus(status_value)
```

## What Went Wrong

### 1. Debugging Approach Was Inefficient
❌ **Spent 2+ hours debugging symptoms before checking network connectivity**
- Should have immediately checked: "Can the containers talk to each other?"
- Basic `docker network inspect` would have revealed the issue in 30 seconds

### 2. Assumed Infrastructure Was Correct
❌ **Assumed containers were on same network because docker-compose.lab.yml defined it**
- Failed to verify that pypnm-api was actually started from the GUI docker-compose
- Didn't check which compose file was used to start pypnm-api

### 3. Fixed Secondary Issue Before Primary
❌ **Fixed PyPNM bug first, which wasn't causing the main failure**
- While the PyPNM bug was real, it wasn't the reason for "Cannot connect"
- Wasted time rebuilding images when network was the real issue

### 4. Over-Reliance on Application Logs
❌ **Focused on application-level errors instead of infrastructure**
- Logs showed "Cannot connect" but didn't immediately check network config
- Should have verified infrastructure (networks, DNS resolution) first

### 5. No Deployment Documentation
❌ **No clear documentation on which docker-compose controls which services**
- Two separate docker-compose files managing overlapping services
- No documentation on startup order or dependencies

## Lessons Learned

### DO: Debug Infrastructure First
1. **Always check network connectivity FIRST**
   ```bash
   docker network inspect <network-name>
   docker exec <container> ping <other-container>
   docker exec <container> curl <service-url>
   ```

2. **Verify container placement**
   ```bash
   docker inspect <container> | grep NetworkMode
   docker ps --format '{{.Names}}\t{{.Networks}}'
   ```

### DO: Follow OSI Model for Debugging
1. **Layer 1-3:** Can containers reach each other? (Network/DNS)
2. **Layer 4:** Are ports open? Is service listening?
3. **Layer 7:** Application-level errors (only after 1-4 work)

### DO: Maintain Deployment State Documentation
Create `/opt/pypnm-gui-lab/DEPLOYMENT_STATE.md`:
```markdown
# Current Deployment State

## Services
- pypnm-api: Started from `/opt/pypnm-gui-lab/docker/docker-compose.lab.yml`
- pypnm-gui-lab: Started from `/opt/pypnm-gui-lab/docker/docker-compose.lab.yml`
- redis-lab: Started from `/opt/pypnm-gui-lab/docker/docker-compose.lab.yml`

## Networks
All services MUST be on: `docker_pypnm-net`

## Startup
```bash
cd /opt/pypnm-gui-lab/docker
docker compose -f docker-compose.lab.yml up -d
```
```

### DO: Add Health Checks Early
Add endpoint that reports:
```json
{
  "status": "healthy",
  "dependencies": {
    "pypnm-api": "reachable",
    "redis": "reachable",
    "agent": "connected"
  }
}
```

### DON'T: Assume Anything About Infrastructure
- ❌ Don't assume docker-compose was used to start services
- ❌ Don't assume services are on the same network
- ❌ Don't assume DNS resolution works
- ✅ Verify everything

### DON'T: Debug Application Before Infrastructure
- ❌ Don't read application logs when "Cannot connect" appears
- ✅ Check networks first, application second

## Prevention Measures

### 1. Add Startup Script
Create `/opt/pypnm-gui-lab/scripts/start-all.sh`:
```bash
#!/bin/bash
set -e

echo "Starting PyPNM GUI Lab environment..."

# Ensure old pypnm-api is stopped
cd /opt/pypnm/compose && docker compose down || true

# Start all services from GUI compose
cd /opt/pypnm-gui-lab/docker
docker compose -f docker-compose.lab.yml down
docker compose -f docker-compose.lab.yml up -d

# Wait and verify
echo "Waiting for services to be healthy..."
sleep 5

# Verify network
echo "Verifying network configuration..."
docker network inspect docker_pypnm-net --format '{{range .Containers}}{{.Name}} {{end}}'

echo "All services started successfully"
```

### 2. Add Pre-flight Checks to Flask App
```python
def check_pypnm_connectivity():
    """Check if PyPNM API is reachable before starting"""
    try:
        response = requests.get(f"{PYPNM_BASE_URL}/health", timeout=2)
        if response.status_code == 200:
            logger.info(f"✅ PyPNM API reachable at {PYPNM_BASE_URL}")
            return True
    except Exception as e:
        logger.error(f"❌ PyPNM API NOT reachable at {PYPNM_BASE_URL}: {e}")
        logger.error("Check: docker network inspect docker_pypnm-net")
        return False
```

### 3. Update Docker Compose with Depends On
```yaml
gui-server-lab:
  depends_on:
    pypnm-api:
      condition: service_healthy
```

### 4. Add Network Verification to Health Check
```python
@app.route('/api/health/full')
def health_full():
    return {
        "status": "healthy",
        "network": {
            "pypnm_api": check_service("http://pypnm-api:8000/docs"),
            "redis": check_service("redis://eve-li-redis-lab:6379")
        }
    }
```

## Cost Impact Analysis

### Budget Exhaustion Factors
1. **Inefficient debugging:** 3 hours of token-heavy operations
2. **Repeated failed attempts:** Testing same thing multiple ways
3. **Large log outputs:** Reading 100+ line logs repeatedly
4. **Context switching:** Jumping between files without systematic approach

### How to Prevent Budget Exhaustion
1. **Front-load verification:** Check infrastructure first (cheap)
2. **Targeted debugging:** Read specific log lines, not full logs
3. **Document as you go:** Save findings to reduce re-reading
4. **Use streaming logs:** `tail -f` instead of `docker logs | tail -100`

## Action Items

- [ ] Create `/opt/pypnm-gui-lab/scripts/start-all.sh`
- [ ] Add pre-flight connectivity checks to Flask app
- [ ] Update docker-compose with proper health checks and depends_on
- [ ] Document current deployment state in `/opt/pypnm-gui-lab/DEPLOYMENT_STATE.md`
- [ ] Add network verification endpoint
- [ ] Update deployment documentation in README
- [ ] Submit PyPNM bug fix as PR to upstream repo
- [ ] Create troubleshooting guide with network verification steps

## References
- Previous incident: `POST_MORTEM_20260115.md`
- PyPNM fix commit: `3461fbf` (Fix ValueError when docsPnmCmCtlStatus returns empty string)
- Docker compose: `/opt/pypnm-gui-lab/docker/docker-compose.lab.yml`

## Sign-off
**Incident closed:** January 20, 2026, 16:00  
**System status:** Operational  
**Follow-up:** Required - implement prevention measures
