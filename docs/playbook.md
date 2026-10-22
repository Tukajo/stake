---
name: stake-playbook
description: Instructions and operational playbook for AI coding agents (Claude Code, Cursor, Antigravity, OpenCode, Devin, etc.) using Stake duplicate-work radar.
---

# Stake Agent Playbook

> A standardized operational playbook for AI coding agents to configure and operate the `stake` serverless duplicate-work radar.

`stake` enables autonomous coding agents and human developers to prevent accidental duplicate effort across branches (`development`, `release/stg`, `main`) with **zero background daemons, zero external servers, and zero database dependencies**.

---

## 1. Onboarding a Target Repository

When asked by a user to onboard or set up `stake` on any Git repository `<TARGET_REPO>`:

### Step 1: Ensure `stake` is on `PATH`
If `stake` is not already installed on your system or environment `PATH`:

```bash
mkdir -p ~/.local/bin
ln -sf /path/to/stake/bin/stake ~/.local/bin/stake
chmod +x ~/.local/bin/stake
```

Confirm availability:
```bash
stake --version
```

### Step 2: Initialize the Target Repository
Run `stake init` targeting the repository:

```bash
stake init --repo "<TARGET_REPO>"
```

What `stake init` does non-destructively:
1. **Chains Git Hooks Safely:** Inspects `core.hooksPath` (or `.git/hooks`) and injects an idempotent `# --- stake-hook-start ---` block into `pre-commit` and `pre-push`. Pre-existing hooks (e.g. linters, formatters, Husky) are preserved and chained intact.
2. **Updates `AGENTS.md` (and `CLAUDE.md` if present):** Inserts an idempotent `<!-- stake:start -->` instruction block instructing all coding harnesses to run `stake claim` at the conclusion of root-cause investigation.

### Step 3: Verify Configuration
```bash
stake status --repo "<TARGET_REPO>"
```
Verify that hooks and instructions are reported as active.

---

## 2. Daily Workflow for Coding Agents

### Phase 1: At Root-Cause Diagnosis / Plan Checkpoint
Do **not** run `stake claim` at the very beginning of a session when the root cause is unknown. Instead, explore the codebase, reproduce the bug, or plan the feature first.

Once you have identified the exact root cause, proposed fix, and intended target files (write-set only):

```bash
stake claim \
  --symptom "<1-sentence summary of the observed issue or ticket>" \
  --fix "<1-2 sentence description of root cause & proposed solution>" \
  --files "<comma-separated repo-relative file paths>"
```

**Example:**
```bash
stake claim \
  --symptom "Admin dashboard 504 timeout on enterprise accounts" \
  --fix "Batch and memoize N+1 org permission lookups in resolver" \
  --files "src/permissions/resolver.ts"
```

#### What Happens Under the Hood:
- Writes a parentless lightweight Git commit (~400 bytes) to `refs/stake/claims/<owner>--<branch>`.
- Claims have a **4-hour TTL** for `stage: "planned"`.
- Fetches all live remote claims across all base branches (`development`, `release/stg`, `main`).
- Outputs any active overlapping claims from teammates.

---

### Phase 2: Evaluating Teammate Claims
When `stake claim` outputs active claims:

1. **Check for Overlap:**
   - **Semantic Overlap:** Does another developer's fix address the exact same root cause, even if their symptom description or ticket ID was different?
   - **Neighborhood Overlap:** Are they modifying the same files or files in the immediate same module directory?
2. **Communicate with the Human Partner:**
   - If an overlap exists, present a concise side-by-side comparison to the user before proceeding to write code.
   - Example format:
     > "Notice: Teammate `<owner>` has an active claim on branch `<branch>`:
     > - **Their Fix:** Batching permission queries in `resolver.ts`.
     > - **Our Plan:** Memoizing permission lookups in `resolver.ts`.
     > Would you like to coordinate with them, or continue with this approach?"

---

### Phase 3: Committing Code (`pre-commit` Backstop)
When implementation is complete and you run `git commit`:

1. **Happy Path (100% Silent):**
   - If you previously declared `stake claim` and your staged changes match the declared module neighborhood without colliding with any newly arrived claims, `pre-commit` silently upgrades your claim to `stage: "committed"` (**72-hour sliding TTL**) and exits `0`.
2. **Skipped Plan or Module Drift:**
   - If `stake claim` was skipped, or edits drifted into an undeclared module, `pre-commit` auto-registers your claim from the staged diff.
   - If an unseen overlap exists, `pre-commit` displays a side-by-side brief and exits `1`.
3. **Show-Once Override (Zero Ceremony):**
   - Because `stake` is a **radar, not a lock**, simply re-running `git commit` (or setting `STAKE_SKIP=1`) immediately proceeds. `stake` records surfaced claims in `.git/stake-state.json` (`seen_claims`) and never blocks on the same claim twice.

---

### Phase 4: Landing & Pruning (`pre-push`)
When pushing your branch (`git push`):

1. `pre-push` tags the claim with `stage: "landed"`.
2. `stake` automatically removes expired claims from the remote using `git push origin --delete refs/stake/claims/<owner>--<branch>`.
3. Standard Git garbage collection (`git gc`) purges unreferenced blobs to 0 bytes.

---

## 3. Best Practices for Coding Agents

- **Write-Set Only:** Only pass files you plan to create or modify to `--files`. Never include read-only exploration files or logs.
- **Concise Summaries:** Keep `--symptom` and `--fix` focused on the technical root cause and solution mechanism so the matching engine can accurately detect semantic duplication.
- **Never Force Lockouts:** Do not attempt to kill another teammate's claim. `stake` is designed for situational awareness; the human developer or tech lead has final authority.
- **Offline Resilient:** If network connectivity is unavailable, `stake` logs a warning and proceeds locally without failing your commit or build.
