# Stake

**Serverless Git-Ref Duplicate-Work Radar for Multi-Agent Teams.**

`stake` prevents developers and coding agents from unknowingly spending time implementing the same underlying fix—including when starting from **two different tickets describing different symptoms** or working across different target branches (`development` vs. `release/stg`).

It requires **zero servers, zero databases, zero background daemons, and zero third-party dependencies**, storing tiny self-cleaning claims directly on your Git remote under `refs/stake/claims/*`.

---

## Agent Playbook

For comprehensive instructions on configuring and operating `stake` across AI coding agents (Claude Code, Cursor, Antigravity, OpenCode, Devin, etc.), see the dedicated operational playbook:

📖 **[Stake Agent Playbook](docs/playbook.md)** (also packaged as an agent skill in [`skills/stake/SKILL.md`](skills/stake/SKILL.md))

### Quick Setup

```bash
# 1. Ensure stake is on PATH
mkdir -p ~/.local/bin
ln -sf /path/to/stake/bin/stake ~/.local/bin/stake
chmod +x ~/.local/bin/stake

# 2. Initialize target repository
stake init --repo "<TARGET_REPO>"

# 3. Verify status
stake status --repo "<TARGET_REPO>"
```

---

## How `stake` Works in Daily Use

### 1. At Diagnosis / Plan Time (`stake claim`)
Once an agent finishes root-cause investigation and knows its proposed fix and target files (before writing code):
```bash
stake claim \
  --symptom "Admin dashboard 504 timeout on enterprise accounts" \
  --fix "Batch and memoize N+1 org permission lookups in resolver" \
  --files "src/permissions/resolver.ts"
```
- Writes a parentless commit (`depth = 1`, ~400 bytes) to `refs/stake/claims/<owner>--<branch>` with a **4-hour TTL**.
- Fetches all live claims across the repo (regardless of base branch: `development`, `release/stg`, `main`).
- Prints active teammate claims so the agent can evaluate semantic or module-neighborhood overlap right at the plan checkpoint.
- Records all surfaced `claim_id`s in `.git/stake-state.json` (`seen_claims`).

### 2. At Commit Time (`pre-commit` Unskippable Backstop)
- **Happy Path (100% Silent):** If `stake claim` was run and staged files stay inside the declared module neighborhood with no new colliding claims, `pre-commit` silently upgrades the claim to `stage: "committed"` (**72-hour sliding TTL**) and exits `0`.
- **Skipped Plan or Module Drift:** If an agent/IDE skipped `stake claim`, or edits drifted into an undeclared module, `pre-commit` auto-registers the claim from the staged diff. If an unseen overlap exists, it prints a side-by-side brief once, marks the claim seen, and exits `1`.
- **Zero-Ceremony Override:** Because `stake` is a **show-once radar** (not a lock), simply re-running `git commit` (or setting `STAKE_SKIP=1`) goes straight through on the second attempt—even if it *is* the exact same work.

### 3. Self-Cleaning Git Plumbing
- **Zero Push Contention:** Each `(developer, branch)` writes only to its own ref under `refs/stake/claims/*`.
- **Zero History Growth:** Every update uses `git commit-tree` with **no `-p` parent**, overwriting the single ~400-byte blob in place.
- **Automatic Remote Pruning:** Every `stake` fetch deletes expired refs (>4h `planned`, >72h `committed`/`landed`) from `origin` via `git push origin --delete`, and standard `git gc` purges unreachable blobs to 0 bytes.
- **Hidden from Branch UIs:** Because `refs/stake/*` is outside `refs/heads/*`, claims never clutter `git branch` or Gitea/GitHub branch dropdowns.
