#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

mkdir -p .local_backups
force_restore=false
if [[ "${1:-}" == "--force-restore" || "${EC2_SYNC_FORCE_RESTORE:-}" == "1" ]]; then
  force_restore=true
fi

tracked_status="$(git status --porcelain --untracked-files=no)"
if [[ -n "$tracked_status" ]]; then
  ts="$(date +%Y%m%d_%H%M%S)"
  patch_path=".local_backups/ec2_tracked_changes_${ts}.patch"
  {
    git diff --binary
    git diff --cached --binary
  } > "$patch_path" || true

  echo "[ec2_sync] tracked local changes found; saved patch to ${patch_path}"
  if [[ "$force_restore" != true ]]; then
    echo "[ec2_sync] refusing to overwrite tracked local changes without --force-restore"
    echo "[ec2_sync] review the patch or rerun: bash scripts/ec2_sync.sh --force-restore"
    exit 2
  fi
  echo "[ec2_sync] restoring tracked files to GitHub source of truth"
  git restore --staged .
  git restore .
fi

git pull --ff-only origin main
