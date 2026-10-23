# Stake Release Notes

## v0.2.0 (2026-10-22)

Stake v0.2.0 delivers precision improvements across claim receipt tracking, module boundary detection, parallel worktree support, and hook installation resilience.

### Highlights

- **Claim Receipt Fingerprinting & Re-Surfacing:** Suppressed claims now track a content receipt key (combining claim ID, target files, target modules, symptom, and diagnosis). When a teammate modifies their active claim on an existing branch, or local edits drift into new files or modules, the radar automatically invalidates suppression cache entries and alerts once before allowing commit retry.
- **Top-Level Container Exclusion:** Common top-level container directories (`src`, `lib`, `packages`, `apps`, `tests`) are no longer treated as root modules, eliminating false-positive overlaps across unrelated features.
- **Hierarchical Submodule Matching:** Overlap matching now recognizes hierarchical parent/child modules (e.g. `src/permissions` and `src/permissions/loaders`), matching across nested module boundaries.
- **Same-User Parallel Worktree Detection:** Parallel worktree workflows by the same developer identity across divergent branches (e.g. `development` vs `release/stg`) now detect collision overlaps across worktree checkouts.
- **Compound Keyword Tokenization:** Symptom and diagnosis keyword extraction splits snake_case and CamelCase compound tokens into distinct search keywords for richer semantic matching.
- **Batched Remote Push:** Ref deletion and claim publication are batched into a single `git push` invocation, drastically reducing network round-trip overhead during sync and pruning.
- **Resilient Hook Chaining:** The `stake init` installer places its managed hook block ahead of any trailing exit statements in existing hooks, ensuring previous hook steps do not prevent Stake from running.
- **CLI Versioning:** Added `--version` CLI flag to report the running Stake version (`stake 0.2.0`).

## v0.1.0 (2026-10-22)

Stake is an **Agentic Git Coordination Framework** that prevents AI coding agents and human developers from unknowingly duplicating effort across branches—even when tickets describe different symptoms or engineers target different branches (`development` vs. `release/stg`).

Stake requires **zero servers, zero background daemons, and zero third-party dependencies**. It writes lightweight, parentless Git commits directly to your repository's remote under `refs/stake/claims/*`.

### Highlights

- **Serverless Git-Ref Coordination:** Stores claims on `refs/stake/claims/<owner>--<branch>` using parentless Git commit objects (~400 bytes). Zero branch noise in GitHub/Gitea branch dropdowns.
- **Cross-Branch Duplicate Detection:** Surfaces overlapping work regardless of base branch (`development`, `release/stg`, `main`).
- **Show-Once Backstop Radar:** Intercepts potential duplicate work at `pre-commit` and `stake claim`. As a non-blocking radar, repeating the commit immediately bypasses the notice without friction.
- **Automatic TTL & Remote Lazy Pruning:** Expired claims (>4h for `planned`, >72h for `committed`/`landed`) are cleaned automatically from the remote during fetch operations. Unreachable objects are swept away by standard `git gc`.
- **Non-Destructive Hook Chaining:** `stake init` chains idempotently into existing `pre-commit` and `pre-push` hooks (supporting Husky, custom hooks, and `core.hooksPath`), and updates `AGENTS.md` to establish autonomous agent coordination.
- **Dedicated Agent Playbook:** Comprehensive documentation in `docs/playbook.md` and packaged skill in `skills/stake/SKILL.md` for seamless integration into agentic workflows (Claude Code, Cursor, Antigravity, OpenCode, Devin).
