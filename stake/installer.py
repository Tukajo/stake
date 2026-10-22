"""Non-destructive Git hook and AGENTS.md onboarding installer for Stake."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stake.git_refs import get_git_dirs

HOOK_START_MARKER: str = "# --- stake-hook-start ---"
HOOK_END_MARKER: str = "# --- stake-hook-end ---"
AGENTS_START_MARKER: str = "<!-- stake:start -->"
AGENTS_END_MARKER: str = "<!-- stake:end -->"


def _default_stake_bin() -> str:
    if shutil.which("stake"):
        return "stake"
    return str(Path(__file__).resolve().parent.parent / "bin" / "stake")


def _upsert_fenced_block(existing: str, start_marker: str, end_marker: str, block: str) -> str:
    if start_marker in existing and end_marker in existing:
        before, rest = existing.split(start_marker, 1)
        _, after = rest.split(end_marker, 1)
        before_clean = before.rstrip("\r\n")
        after_clean = after.lstrip("\r\n")
        prefix = f"{before_clean}\n\n" if before_clean else ""
        suffix = f"\n{after_clean}" if after_clean else ""
        return f"{prefix}{block.strip()}\n{suffix}"
    before_clean = existing.rstrip("\r\n")
    if not before_clean:
        return block.strip() + "\n"
    return f"{before_clean}\n\n{block.strip()}\n"


def _resolve_hooks_dir(repo_root: Path, git_common_dir: Path) -> Path:
    res = subprocess.run(
        ["git", "-C", str(repo_root), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    custom = res.stdout.strip()
    if custom:
        p = Path(custom).expanduser()
        resolved = p if p.is_absolute() else (repo_root / p)
        # Husky v9 sets core.hooksPath to .husky/_, but user-editable and
        # version-controlled hooks reside in .husky. Writing into _ is wiped
        # by husky prepare scripts and gitignored.
        if resolved.name == "_" and (resolved.parent / "_").is_dir():
            return resolved.parent
        return resolved
    return git_common_dir / "hooks"


def _install_hook_file(hook_path: Path, subcommand: str, stake_bin: str, allow_fail: bool = False) -> None:
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    existing = hook_path.read_text(encoding="utf-8") if hook_path.exists() else "#!/usr/bin/env sh\n"
    suffix = " || true" if allow_fail else ""
    block = "\n".join([
        HOOK_START_MARKER,
        f'STAKE_BIN="${{STAKE_BIN:-{stake_bin}}}"',
        'if command -v "$STAKE_BIN" >/dev/null 2>&1; then',
        f'  "$STAKE_BIN" hook {subcommand}{suffix}',
        'elif [ -x "$STAKE_BIN" ]; then',
        f'  "$STAKE_BIN" hook {subcommand}{suffix}',
        'elif command -v stake >/dev/null 2>&1; then',
        f'  stake hook {subcommand}{suffix}',
        "fi",
        HOOK_END_MARKER,
    ])
    updated = _upsert_fenced_block(existing, HOOK_START_MARKER, HOOK_END_MARKER, block)
    hook_path.write_text(updated, encoding="utf-8")
    current_mode = hook_path.stat().st_mode if hook_path.exists() else 0o755
    hook_path.chmod(current_mode | 0o755)


def _agents_md_block(stake_bin: str) -> str:
    cmd_name = "stake" if shutil.which("stake") or stake_bin == "stake" else stake_bin
    return f"""{AGENTS_START_MARKER}
## Workflow Coordination (`stake`)

This repository uses **Stake** (`refs/stake/claims/*`) as a serverless show-once radar to surface duplicate or overlapping work across teammates and branches (`development`, `release/stg`, etc.) before code is written.

1. **One-time clone bootstrap:** If `.git/hooks/pre-commit` does not yet contain `{HOOK_START_MARKER}`, run:
   ```bash
   {cmd_name} init
   ```
2. **At Diagnosis / Plan Time (before writing code):** Once you have investigated the symptom and know your root cause, proposed fix, and target files, declare your claim:
   ```bash
   {cmd_name} claim --symptom "<1-sentence issue>" --fix "<1-2 sentence root cause & proposed change>" --files "<comma-separated repo-relative files>"
   ```
3. **Evaluate & surface once:** Read the active teammate claims printed by `{cmd_name} claim`. If another developer's in-flight or recently landed claim solves the same root cause or touches the same/adjacent files in the same module (including across `release/stg` vs. `development`), present a brief side-by-side comparison to the user. If the user chooses to proceed anyway (or re-runs `git commit`), `stake` records the claim as seen and never blocks flow twice.
{AGENTS_END_MARKER}"""


def init_repo(repo_path: str = ".", stake_bin: str | None = None) -> dict[str, str]:
    """Install non-destructive Git hooks and AGENTS.md instructions into repo_path."""
    repo_root, _, git_common_dir = get_git_dirs(repo_path)
    resolved_bin = stake_bin or _default_stake_bin()
    hooks_dir = _resolve_hooks_dir(repo_root, git_common_dir)

    pre_commit = hooks_dir / "pre-commit"
    pre_push = hooks_dir / "pre-push"
    _install_hook_file(pre_commit, "pre-commit", resolved_bin, allow_fail=False)
    _install_hook_file(pre_push, "pre-push", resolved_bin, allow_fail=True)

    block = _agents_md_block(resolved_bin)
    agents_file = repo_root / "AGENTS.md"
    existing_agents = agents_file.read_text(encoding="utf-8") if agents_file.exists() else "# Agent Instructions\n"
    agents_file.write_text(
        _upsert_fenced_block(existing_agents, AGENTS_START_MARKER, AGENTS_END_MARKER, block),
        encoding="utf-8",
    )

    claude_file = repo_root / "CLAUDE.md"
    if claude_file.exists() and not claude_file.is_symlink():
        existing_claude = claude_file.read_text(encoding="utf-8")
        claude_file.write_text(
            _upsert_fenced_block(existing_claude, AGENTS_START_MARKER, AGENTS_END_MARKER, block),
            encoding="utf-8",
        )

    return {
        "repo_root": str(repo_root),
        "pre_commit": str(pre_commit),
        "pre_push": str(pre_push),
        "agents_md": str(agents_file),
    }
