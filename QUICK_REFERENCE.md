# Quick Reference Guide - Deployment & Testing

## Deployment Script (`./deploy.sh`)

### Common Commands

```bash
# View all options
./deploy.sh --help

# Remote deployment (quick)
./deploy.sh remote-deploy

# Remote full rebuild
./deploy.sh remote-rebuild

# Check remote status
./deploy.sh remote-status

# View remote logs
./deploy.sh remote-logs

# Local docker with rebuild
./deploy.sh local-docker --no-cache

# Remote build without cache
./deploy.sh remote-build --no-cache

# SSH to remote server
./deploy.sh ssh

# Cleanup local docker
./deploy.sh cleanup

# Create backup
./deploy.sh backup
```

### Advanced Usage

```bash
# Custom remote host
./deploy.sh -h myserver.com -u admin remote-deploy

# Different environment
./deploy.sh -e prod remote-deploy

# Custom docker compose file
./deploy.sh -f docker/docker-compose.prod.yml local-docker
```

## API Test Script (`./test_api.py`)

### Run Tests

```bash
# Run all tests (requires GUI and PyPNM API running)
./test_api.py

# Results saved to: test_results_TIMESTAMP.json
```

### What It Tests

1. **Health Endpoints**
   - GUI health check
   - PyPNM API health
   - API documentation access

2. **CMTS Management**
   - List all CMTS
   - CMTS summary

3. **Modem Endpoints**
   - List modems
   - Get specific modem
   - System info (requires real modem)

4. **PyPNM Proxy Endpoints**
   - Spectrum analyzer
   - FEC summary
   - Channel statistics
   
5. **PyPNM API Direct**
   - Agent status
   - OpenAPI spec

### Test Output

- ✓ **GREEN** = Passed
- ✗ **RED** = Failed
- ⚠ **YELLOW** = Skipped (requires real hardware)

## Testing After Coffee ☕

1. **Start services**:
   ```bash
   ./deploy.sh remote-status    # Check if running
   ./deploy.sh remote-logs      # View logs if needed
   ```

2. **Run tests**:
   ```bash
   ./test_api.py
   ```

3. **Check results**:
   - Console output shows pass/fail
   - JSON file has detailed results
   - Failed tests show error messages

4. **Manual testing**:
   - GUI: http://localhost:5050 (or remote via SSH tunnel)
   - PyPNM API: http://localhost:8000/docs
   - Test with real cable modems if available

## Workflow Examples

### Deploy to Remote Lab
```bash
./deploy.sh remote-deploy
./deploy.sh remote-status
./deploy.sh remote-logs
```

### Full Remote Rebuild
```bash
./deploy.sh remote-stop
./deploy.sh remote-rebuild
./deploy.sh remote-status
```

### Local Testing
```bash
./deploy.sh local-docker
./test_api.py
```

### Troubleshooting
```bash
./deploy.sh remote-logs          # View logs
./deploy.sh remote-status        # Check status
./deploy.sh ssh                  # SSH to debug
./deploy.sh remote-restart       # Restart services
```

## Quick Deployment Reference

| Task | Command |
|------|---------|
| Deploy changes | `./deploy.sh remote-deploy` |
| Full rebuild | `./deploy.sh remote-rebuild` |
| Check status | `./deploy.sh remote-status` |
| View logs | `./deploy.sh remote-logs` |
| Restart | `./deploy.sh remote-restart` |
| Test APIs | `./test_api.py` |

## After Your Coffee ☕

Run this sequence:
```bash
# 1. Check remote status
./deploy.sh remote-status

# 2. View recent logs
./deploy.sh remote-logs | head -50

# 3. Test all API endpoints
./test_api.py

# 4. Check test results
cat test_results_*.json | jq '.summary'
```

Enjoy your coffee! The scripts are ready to test everything when you return. 🚀
