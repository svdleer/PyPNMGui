# Repetitive Deployment Failures

## Critical Issue: Docker Cache Persistence Despite --no-cache Flag

### Problem Description
Docker builds frequently use **cached layers even when explicitly instructed with `--no-cache` flag**, causing deployment of outdated code and wasting significant time and credits.

### Symptoms
- Code changes committed and pushed to git successfully
- Git pull on server confirms latest code
- Docker rebuild with `--no-cache` flag executes
- **Container still contains old code/files from previous builds**
- Multiple rebuild attempts required before changes take effect

### Root Cause
Docker build context caching and layer caching persist even with `--no-cache`:
1. Build context is cached at Docker daemon level
2. Some Dockerfile layers (especially COPY operations) may reuse cached content
3. File timestamps in git don't trigger Docker to invalidate cache

### Documented Occurrences
**Session: 2026-01-21 - SciChart CDN URL Update**
- Changed SciChart URL from v3 to v4 in `frontend/templates/index.html`
- Committed, pushed, pulled - confirmed correct in repo
- Rebuilt 4+ times with `--no-cache` flag
- Container kept using old v3 URL from cache
- Required adding comment change to "bust cache" before it finally updated
- **Wasted ~30 minutes and significant token credits**

### Mandatory Solution Protocol

**ALWAYS follow this exact sequence for ANY code deployment:**

```bash
# 1. Commit and push locally
cd /path/to/local/repo
git add -A
git commit -m "Description of changes"
git push origin main

# 2. On server: Remove old container first
ssh server 'docker rm -f container-name'

# 3. Pull latest code
ssh server 'cd /opt/repo && git pull'

# 4. Verify git changes took effect
ssh server 'grep "some-unique-string" /opt/repo/path/to/changed/file'

# 5. Build with --no-cache AND prune build cache
ssh server 'docker builder prune -f && cd /opt/repo && docker-compose build --no-cache service-name'

# 6. Start container
ssh server 'cd /opt/repo && docker-compose up -d service-name'

# 7. CRITICAL: Verify change in running container
ssh server 'docker exec container-name grep "some-unique-string" /app/path/to/file'
```

### Cache Busting Techniques When --no-cache Fails

If `--no-cache` still uses cached files:

1. **Add a cache-busting layer** to Dockerfile:
   ```dockerfile
   RUN echo "Cache bust: $(date +%s)"
   ```

2. **Modify a comment** in the changed file:
   ```html
   <!-- Updated: 2026-01-21 v2 -->
   ```

3. **Prune build cache** before building:
   ```bash
   docker builder prune -a -f
   ```

4. **Check file timestamps in git**:
   ```bash
   git ls-files -z | xargs -0 touch
   git commit --amend --no-edit
   ```

### Prevention Guidelines

- **NEVER assume** `--no-cache` alone is sufficient
- **ALWAYS verify** changes in running container after deployment
- **ALWAYS remove** old container before rebuilding
- **Always prune** build cache: `docker builder prune -f`
- **Consider** adding build timestamp to Dockerfile for automatic cache invalidation

### Financial Impact
Each failed deployment cycle costs:
- ~5-10 minutes of time
- ~5000-10000 tokens in context
- Multiple rebuild attempts
- **Estimated cost per incident: $0.50-2.00**

### Action Items
- [ ] Update deployment scripts to include verification steps
- [ ] Add automated cache pruning to deployment pipeline
- [ ] Create deployment checklist for manual deployments
- [ ] Monitor for cache-related issues in future sessions

---
**Last Updated:** 2026-01-21  
**Severity:** 🔴 CRITICAL - Causes significant time/cost waste
