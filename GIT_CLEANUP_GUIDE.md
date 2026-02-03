# Git History Cleanup Guide

## Current Situation
Your PyPNMGui repository has grown with debug commits, temporary files, and refactoring history. The archive folder alone contains 30+ "clusterfuck" documents.

## Cleanup Options

### ⭐ RECOMMENDED: Option 1 - Fresh Start (Clean Slate)
**Best for**: Projects where history isn't critical
**Pros**: Clean professional repo, small size, fast clones
**Cons**: Lose commit history (but you can keep old repo as backup)

```bash
# 1. Backup current repo
cd /Users/silvester/PythonDev/Git
mv PyPNMGui PyPNMGui-backup

# 2. Clone fresh
git clone https://github.com/svdleer/PyPNMGui.git
cd PyPNMGui

# 3. Create fresh commit history
git checkout --orphan fresh-start
git add -A
git commit -m "Initial commit: Production-ready PyPNM GUI

Architecture:
- Flask backend with PyPNM API integration
- React frontend
- WebSocket agent support via PyPNM API
- Multi-agent deployment ready
- Docker containerized

Features:
- DOCSIS 3.0/3.1 PNM monitoring
- Spectrum analyzer
- OFDM/OFDMA RxMER
- Channel statistics
- CMTS integration
- Real-time agent management"

# 4. Replace main branch
git branch -D main
git branch -m main

# 5. Force push (WARNING: This rewrites history!)
git push -f origin main

# 6. Cleanup
git gc --prune=now --aggressive

# Result: Small, clean repo with professional commit history
```

### Option 2 - Remove Large/Sensitive Files (BFG)
**Best for**: Keeping history but removing specific large files
**Pros**: Keeps git history, removes bloat
**Cons**: Rewrites history, requires force push

```bash
# Install BFG Repo-Cleaner
brew install bfg

# Clone mirror
cd /Users/silvester/PythonDev/Git
git clone --mirror https://github.com/svdleer/PyPNMGui.git PyPNMGui-cleanup.git
cd PyPNMGui-cleanup.git

# Remove files > 5MB from history
bfg --strip-blobs-bigger-than 5M

# Remove archive folder from history
bfg --delete-folders archive
bfg --delete-folders .archive

# Cleanup
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push
git push --force --all

# Update local repo
cd /Users/silvester/PythonDev/Git/PyPNMGui
git fetch origin
git reset --hard origin/main
```

### Option 3 - Filter Specific Paths (git filter-repo)
**Best for**: Surgical removal of specific files/folders
**Pros**: Most powerful, precise control
**Cons**: Complex, requires careful planning

```bash
# Install git-filter-repo
brew install git-filter-repo

# Fresh clone
cd /Users/silvester/PythonDev/Git
git clone https://github.com/svdleer/PyPNMGui.git PyPNMGui-filtered
cd PyPNMGui-filtered

# Remove archive folder from ALL history
git filter-repo --path archive --invert-paths --force

# Remove specific files from history
git filter-repo --path 'fuckup-of-the-day.md' --invert-paths --force
git filter-repo --path 'CLUSTERFUCK_*.md' --invert-paths --force

# Force push
git remote add origin https://github.com/svdleer/PyPNMGui.git
git push --force --all origin
git push --force --tags origin
```

### Option 4 - Shallow Clone Only (No History Rewrite)
**Best for**: Working locally without changing remote
**Pros**: Easy, no force push needed
**Cons**: Still downloads full history initially, doesn't reduce remote size

```bash
# Clone with only recent history
git clone --depth 50 https://github.com/svdleer/PyPNMGui.git PyPNMGui-shallow

# Or convert existing clone
cd /Users/silvester/PythonDev/Git/PyPNMGui
git fetch --depth 50
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

## My Recommendation: Option 1 (Fresh Start)

**Why?**
1. Your project is actively developed, history is mostly debugging
2. Archive has 30+ "clusterfuck" documents - not professional for public repo
3. Recent architecture changes make old history less relevant
4. Clean slate = professional appearance
5. Easy to execute, no complex commands

**Before You Do It:**
```bash
# 1. Create backup tag
git tag -a backup-before-cleanup -m "Backup before history cleanup - 2026-02-03"
git push origin backup-before-cleanup

# 2. Export important commits
git log --oneline > git-history-backup.txt
git log --all --pretty=format:"%h %an %ad %s" > detailed-history.txt

# 3. Keep old repo as backup
cd /Users/silvester/PythonDev/Git
tar -czf PyPNMGui-full-backup-2026-02-03.tar.gz PyPNMGui
```

**After Fresh Start:**
- Old history preserved in backup tag
- Can always restore from backup
- New clones are fast and small
- Professional commit history going forward

## Comparison Table

| Method | Keeps History | Remote Size | Complexity | Force Push |
|--------|--------------|-------------|------------|------------|
| Fresh Start | ❌ | Smallest | Easy | Yes |
| BFG | ✅ | Medium | Medium | Yes |
| filter-repo | ✅ | Medium | Hard | Yes |
| Shallow | ✅ | No change | Easy | No |

## Post-Cleanup: Protect Future

Add to `.gitignore`:
```gitignore
# Already added ✅
.archive/
archive/

# Add these:
*.bak
*.tmp
*backup*
*debug*
*test*
```

Create commit message template:
```bash
cat > ~/.gitmessage << 'EOF'
# Type: [feat|fix|docs|style|refactor|test|chore]
# 
# Summary (50 chars or less)
#
# Detailed description (wrap at 72 chars)
#
# Refs: #issue_number
EOF

git config --global commit.template ~/.gitmessage
```

## Execute Fresh Start Now

Ready? Here's the complete script:

```bash
#!/bin/bash
set -e

echo "🔄 Starting git history cleanup..."

# Backup
cd /Users/silvester/PythonDev/Git
echo "📦 Creating backup..."
tar -czf PyPNMGui-backup-$(date +%Y%m%d).tar.gz PyPNMGui

cd PyPNMGui

# Create backup tag
echo "🏷️  Creating backup tag..."
git tag -a backup-2026-02-03 -m "Backup before fresh start"
git push origin backup-2026-02-03

# Export history
echo "📝 Exporting history..."
git log --oneline > ../git-history-backup.txt

# Fresh start
echo "🆕 Creating fresh branch..."
git checkout --orphan fresh-start
git add -A
git commit -m "Initial commit: Production-ready PyPNM GUI

Complete DOCSIS PNM monitoring solution with multi-agent architecture"

echo "🔄 Replacing main branch..."
git branch -D main
git branch -m main

echo "⚠️  About to force push. Press Ctrl+C to cancel, Enter to continue..."
read

echo "⬆️  Force pushing..."
git push -f origin main

echo "🧹 Cleaning up..."
git gc --prune=now --aggressive

echo "✅ Done! Your repo is now clean."
echo "📊 Old history preserved in: ../git-history-backup.txt"
echo "💾 Full backup at: ../PyPNMGui-backup-$(date +%Y%m%d).tar.gz"
echo "🏷️  Old repo tagged: backup-2026-02-03"
```

Save as `cleanup-git-history.sh`, make executable, and run:
```bash
chmod +x cleanup-git-history.sh
./cleanup-git-history.sh
```

## Questions?

**Q: Can I undo this?**
A: Yes! You have:
1. Backup tarball of entire repo
2. Git tag `backup-2026-02-03` on remote
3. Backup text files of commit history

**Q: Will this break other clones?**
A: Yes. Other team members need to:
```bash
git fetch origin
git reset --hard origin/main
```

**Q: What about open PRs?**
A: They'll need to be recreated against new history

**Q: Is there a safer option?**
A: Yes - Option 4 (shallow clone) doesn't change remote
