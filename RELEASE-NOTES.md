# Stake Release Notes

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
