#!/usr/bin/env bash
# email_sync.sh — Gmail-to-website sync pipeline for Drew's Move dashboard.
# Designed to run every 30 minutes via cron.
#
# Crontab entry:
#   */30 * * * * /home/openclaw/drew-shipping/email_sync.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/sync.log"
PACKAGES_FILE="$SCRIPT_DIR/packages.json"
PROMPT_FILE="$SCRIPT_DIR/email_prompt.txt"
TEMP_DIR=$(mktemp -d)

# Cleanup temp files on exit
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# Logging helper — writes to log file and stdout
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========== Email sync started =========="

# --- Step 1: Call Claude CLI to scan Gmail and extract package data ---
log "Step 1: Scanning Gmail via Claude CLI..."

NEW_PACKAGES_FILE="$TEMP_DIR/new_packages.json"
CLAUDE_STDERR="$TEMP_DIR/claude_stderr.log"

PROMPT=$(cat "$PROMPT_FILE")

if claude -p "$PROMPT" \
    --allowedTools "mcp__claude_ai_Gmail__gmail_search_messages,mcp__claude_ai_Gmail__gmail_read_message,mcp__claude_ai_Gmail__gmail_read_thread" \
    --output-format text \
    > "$NEW_PACKAGES_FILE" \
    2> "$CLAUDE_STDERR"; then
    log "Claude CLI completed successfully."
else
    CLAUDE_EXIT=$?
    log "ERROR: Claude CLI failed with exit code $CLAUDE_EXIT"
    if [ -f "$CLAUDE_STDERR" ]; then
        log "Claude stderr: $(cat "$CLAUDE_STDERR")"
    fi
    exit 1
fi

# Validate that output is valid JSON
if ! python3 -c "import json, sys; json.load(open(sys.argv[1]))" "$NEW_PACKAGES_FILE" 2>/dev/null; then
    log "WARNING: Claude output is not valid JSON. Attempting to extract JSON array..."
    # Try to extract a JSON array from the output (Claude sometimes wraps in markdown)
    if python3 -c "
import json, re, sys
content = open(sys.argv[1]).read()
# Strip markdown code fences if present
content = re.sub(r'\`\`\`json?\s*', '', content)
content = re.sub(r'\`\`\`\s*$', '', content.strip())
# Find the JSON array
match = re.search(r'\[.*\]', content, re.DOTALL)
if match:
    data = json.loads(match.group())
    with open(sys.argv[1], 'w') as f:
        json.dump(data, f)
    sys.exit(0)
sys.exit(1)
" "$NEW_PACKAGES_FILE" 2>/dev/null; then
        log "Successfully extracted JSON array from Claude output."
    else
        log "ERROR: Could not extract valid JSON from Claude output."
        log "Raw output: $(head -20 "$NEW_PACKAGES_FILE")"
        exit 1
    fi
fi

# Check if we got any packages
PACKAGE_COUNT=$(python3 -c "import json, sys; print(len(json.load(open(sys.argv[1]))))" "$NEW_PACKAGES_FILE")
log "Found $PACKAGE_COUNT package(s) from email scan."

if [ "$PACKAGE_COUNT" -eq 0 ]; then
    log "No new packages found. Nothing to do."
    log "========== Email sync finished (no changes) =========="
    exit 0
fi

# --- Step 2: Merge new data with existing packages.json ---
log "Step 2: Merging new packages into existing data..."

MERGE_OUTPUT=$(python3 "$SCRIPT_DIR/merge_packages.py" "$PACKAGES_FILE" "$NEW_PACKAGES_FILE" 2>&1) || {
    log "ERROR: Merge failed: $MERGE_OUTPUT"
    exit 1
}
log "$MERGE_OUTPUT"

# --- Step 3: Run sync.py to inject into index.html ---
log "Step 3: Syncing packages.json into index.html..."

SYNC_OUTPUT=$(python3 "$SCRIPT_DIR/sync.py" "$PACKAGES_FILE" 2>&1) || {
    log "ERROR: sync.py failed: $SYNC_OUTPUT"
    exit 1
}
log "$SYNC_OUTPUT"

# --- Step 4: Git commit and push if there are changes ---
log "Step 4: Checking for git changes..."
cd "$SCRIPT_DIR"

if git diff --quiet index.html packages.json 2>/dev/null; then
    log "No changes detected in index.html or packages.json. Skipping git push."
else
    log "Changes detected. Committing and pushing..."

    git add index.html packages.json
    git commit -m "Automated sync: update package tracking data

Synced $PACKAGE_COUNT package(s) from email scan at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    if git push 2>&1 | tee -a "$LOG_FILE"; then
        log "Successfully pushed to GitHub."
    else
        log "ERROR: git push failed."
        exit 1
    fi
fi

log "========== Email sync finished =========="
