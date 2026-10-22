---
name: stake
description: Use when onboarding a repository to the Stake duplicate-work radar (~/Code/stake) or when declaring a root-cause diagnosis and proposed fix before writing code.
---

# Stake: Serverless Git-Ref Duplicate-Work Radar

## Onboarding a Target Repository

When asked to set up or install `stake` for any Git repository `<REPO_PATH>`:

1. Ensure the CLI symlink is installed:
   ```bash
   mkdir -p ~/.local/bin
   ln -sf /home/tjfrisch/Code/stake/bin/stake ~/.local/bin/stake
   ```
2. Run the non-destructive initializer:
   ```bash
   /home/tjfrisch/Code/stake/bin/stake init --repo "<REPO_PATH>"
   ```
3. Commit the updated `AGENTS.md` (if the user wants it tracked in the target repo) and verify with:
   ```bash
   /home/tjfrisch/Code/stake/bin/stake status --repo "<REPO_PATH>"
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
