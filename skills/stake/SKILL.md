---
name: stake
description: Use when declaring a root-cause diagnosis and proposed fix before writing code in any Git repository, or when managing Stake user-level setup and repository filtering.
---

# Stake: Serverless Git-Ref Duplicate-Work Radar

See the full [Stake Agent Playbook](../../docs/playbook.md) for comprehensive operational guidelines.

## One-Time User-Level Setup

When asked to set up or install `stake`:

1. Ensure the `stake` executable is on `PATH` or symlinked to `~/.local/bin/stake`:
   ```bash
   mkdir -p ~/.local/bin
   ln -sf /path/to/stake/bin/stake ~/.local/bin/stake
   ```
2. Run the user-level setup (zero tracked files modified in any repository):
   ```bash
   stake setup
   ```
3. Optional repository filtering (`~/.config/stake/config.json`):
   ```bash
   stake disable --repo "<REPO_PATH>"
   stake enable --repo "<REPO_PATH>"
   ```

## Using `stake` During Feature / Bugfix Work

1. **Declare at Diagnosis / Plan Time (Not Session Start):**
   Wait until you have investigated the symptom and identified the root cause, proposed fix, and target files (write-set only, never files merely read during exploration):
   ```bash
   stake claim \
     --symptom "<1-sentence symptom>" \
     --fix "<1-2 sentence root cause and proposed fix>" \
     --files "<comma-separated repo-relative file paths>"
   ```
2. **Evaluate Returned Claims:**
   Inspect the active teammate claims printed by `stake claim`. If another developer's claim solves the same underlying root cause or modifies the same/adjacent files in the same module (including across `release/stg` vs. `development`), show the user a concise side-by-side comparison.
3. **Show-Once Bypass:**
   If the user wants to proceed anyway (or if `pre-commit` surfaces a new overlap once), simply continue or re-run `git commit` (`stake` records seen claims in `.git/stake-state.json` and never blocks twice).
4. **Inspect Active Claims:**
   List all active claims in the current repository (auto-detects git repo):
   ```bash
   stake list
   # Or explicitly:
   stake list claims [--limit N] [--all] [--json]
   ```
