# Code Cleanup Analysis - PyPNMGui
## Date: 2026-02-03

## 1. Files Moved to .archive/

### Clutter/Test Scripts Archived:
- ✅ `fuckup-of-the-day.md` - Temporary issue tracking
- ✅ `MOVE_WEBSOCKET_TO_PYPNM_API.md` - Completed migration doc
- ✅ `ssh-tunnel-lab.sh` - Lab SSH tunnel script
- ✅ `ssh-tunnel.sh` - Production SSH tunnel script  
- ✅ `start_utsc_freerun.sh` - Test script
- ✅ `start_with_agent.sh` - Test script
- ✅ `start.sh` - Old start script

### Already in archive/ (tracked in git):
- 30+ clusterfuck/post-mortem documents
- Old deployment scripts
- Copilot refund requests
- Integration plans
- Debug scripts

## 2. Duplicate/Unused Code Found

### HIGH PRIORITY - Can Remove:

#### `api_routes_old.py` (40KB)
**Status**: DUPLICATE - Old version of api_routes.py
**Action**: DELETE - No longer referenced
**Verification**:
```bash
grep -r "api_routes_old" backend/ --include="*.py"
# Result: No imports found
```

#### `simple_ws.py` - OLD AGENT MANAGER
**Status**: DEPRECATED - Replaced by PyPNM API agent manager
**Size**: Unknown
**Usage**: Still imported in api_routes.py but functions migrated to PyPNM API
**Action**: **KEEP FOR NOW** - Some functions still used, but marked for Phase 5 removal
**Migration Status**: 
- ✅ `pypnm_spectrum` - Migrated to PyPNM API
- ✅ `pypnm_fec` - Migrated to PyPNM API  
- ✅ `pypnm_channel_stats` - Migrated to PyPNM API
- ⚠️  `get_system_info`, `get_uptime`, etc. - Still use simple_ws
**Plan**: Complete Phase 5 migration, then remove

#### `agent_manager.py` - OLD AGENT MANAGER
**Status**: DUPLICATE of simple_ws functionality
**Action**: Review usage and consolidate or remove

### MEDIUM PRIORITY - Review:

#### `ws_routes.py` (22KB)
**Status**: WebSocket routes for GUI's agent server
**Current**: Agent now connects to PyPNM API, not GUI
**Usage**: May still be used for GUI real-time updates (non-agent WebSockets)
**Action**: **AUDIT** - Check if still needed for GUI features
**Recommendation**: If only for agent, remove. If for GUI real-time, keep and rename.

#### Duplicate PyPNM Clients:
Multiple files interact with PyPNM API:
- `pypnm_routes.py` - Main PyPNM proxy routes
- `api_routes.py` - Some PyPNM calls
- Both use `pypnm_client.py`
**Action**: Consolidate PyPNM API calls into `pypnm_routes.py`

### LOW PRIORITY - Technical Debt:

#### Backend Route Organization:
- `api_routes.py` (61KB) - Mixed PyPNM and direct operations
- `pypnm_routes.py` (75KB) - PyPNM API proxy
- `main_routes.py` (1.5KB) - Basic routes
**Recommendation**: 
- Rename `api_routes.py` → `legacy_routes.py`
- Move all PyPNM operations to `pypnm_routes.py`
- Keep `main_routes.py` for basic GUI endpoints

## 3. Copilot References Removed

### Files with Copilot Mentions (18 total):
Will remove from:
- Documentation files
- Comments
- Archive folder (kept for historical purposes)

### Action Plan:
```bash
# Remove copilot from active code/docs
grep -rl "copilot" . --include="*.py" --include="*.md" --include="*.txt" \
  --exclude-dir=.archive --exclude-dir=archive \
  | xargs sed -i '' 's/[Cc]opilot/AI Assistant/g'
```

## 4. Git History Cleanup Options

### Option A: Shallow Clone (Recommended - Simple)
**Pros**: Easy, keeps git history, remote unchanged
**Cons**: Still downloads full history initially
```bash
git clone --depth 1 <repo-url>
```

### Option B: BFG Repo-Cleaner (Remove Large Files)
**Pros**: Removes large blobs, shrinks repo
**Cons**: Rewrites history, force push required
```bash
# Install BFG
brew install bfg

# Clone bare repo
git clone --mirror https://github.com/svdleer/PyPNMGui.git

# Remove files > 10MB
bfg --strip-blobs-bigger-than 10M PyPNMGui.git

# Cleanup
cd PyPNMGui.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push (WARNING: Breaks clones)
git push --force
```

### Option C: git filter-repo (Advanced)
**Pros**: Most powerful, can remove specific paths
**Cons**: Complex, rewrites history
```bash
# Install
brew install git-filter-repo

# Remove archive folder from history
git filter-repo --path archive --invert-paths

# Force push
git push --force --all
```

### Option D: Squash and Fresh Start (Nuclear Option)
**Pros**: Clean slate, small repo
**Cons**: Lose ALL history
```bash
# Create fresh repo
git checkout --orphan fresh-start
git add -A
git commit -m "Fresh start: Clean codebase"
git branch -D main
git branch -m main
git push -f origin main
```

### **RECOMMENDED**: Option A or D
- **Option A** if you want to keep history
- **Option D** if history doesn't matter (project is young)

For this project, I'd recommend **Option D** because:
- History is mostly debugging/refactoring commits
- Archive folder has 30+ "clusterfuck" docs
- Fresh start = clean professional repo
- Keep old repo as backup

## 5. Immediate Action Items

### Phase 1: Archive & Cleanup (DONE)
- ✅ Created `.gitignore` with `.archive/` 
- ✅ Moved 7 clutter files to `.archive/`
- ✅ Archive folder already in git (30+ files)

### Phase 2: Remove Dead Code (TODO)
```bash
# 1. Delete api_routes_old.py
git rm backend/app/routes/api_routes_old.py

# 2. Remove copilot references
find . -type f \( -name "*.py" -o -name "*.md" \) \
  -not -path "./.archive/*" -not -path "./archive/*" \
  -exec sed -i '' 's/[Cc]opilot/AI Assistant/g' {} +

# 3. Commit
git add -A
git commit -m "Cleanup: Remove old files and copilot references"
```

### Phase 3: Migrate Remaining Agent Functions (TODO)
- Migrate system_info, uptime, etc. to PyPNM API
- Remove `simple_ws.py` completely
- Update `api_routes.py` to use only PyPNM API

### Phase 4: Git History (TODO - OPTIONAL)
Choose Option A (shallow) or D (fresh start) above.

## 6. File Size Summary

### Current Repository Size:
```
backend/app/routes/pypnm_routes.py:  75KB
backend/app/routes/api_routes.py:    61KB
backend/app/routes/api_routes_old.py: 40KB (DELETE)
backend/app/routes/ws_routes.py:     22KB (AUDIT)
archive/:                            ~2MB (IGNORE VIA .gitignore)
```

### After Cleanup:
- Remove `api_routes_old.py`: -40KB
- Archive `.archive/`: -2MB (from git tracking)
- Total savings: ~2MB + cleaner history

## 7. Unused Code Analysis

### Backend Modules Usage:

#### High Usage (Keep):
- ✅ `pypnm_client.py` - PyPNM API client
- ✅ `cmts_provider.py` - CMTS data provider
- ✅ `config.py` - Configuration
- ✅ Plotter modules (spectrum, constellation, utsc)

#### Review Required:
- ⚠️  `simple_ws.py` - Old agent manager (Phase 5 removal)
- ⚠️  `agent_manager.py` - May duplicate simple_ws
- ⚠️  `upstream_pnm.py` - Check if used
- ⚠️  `cmts_pnm.py` - Check if used

#### Can Likely Remove:
- ❌ `api_routes_old.py` - Old code
- ❌ `.archive/` files - Historical

### Frontend (Not Analyzed):
Frontend cleanup not performed in this analysis.

## Conclusion

**Immediate Actions**:
1. ✅ Move clutter to `.archive/` - DONE
2. 🔄 Remove `api_routes_old.py` - Ready to execute
3. 🔄 Remove copilot references - Ready to execute  
4. 📋 Document cleanup - THIS FILE

**Next Steps**:
1. Execute Phase 2 cleanup (remove dead code)
2. Complete Phase 5 migration (remove simple_ws)
3. Consider fresh git start for clean history
4. Update documentation to reflect new architecture

**Estimated Savings**:
- Disk: ~2MB
- Clarity: Significant (removes confusing old code)
- Maintenance: Easier (single source of truth)
