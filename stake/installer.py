"""User-level Git hook, Husky init, and global agent instructions installer for Stake."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from stake.config import (
    CONFIG_FILENAME,
    StakeConfig,
    get_config_dir,
    get_home_dir,
    save_config,
)

HOOK_START_MARKER: str = "# --- stake-hook-start ---"
HOOK_END_MARKER: str = "# --- stake-hook-end ---"
AGENTS_START_MARKER: str = "<!-- stake:start -->"
AGENTS_END_MARKER: str = "<!-- stake:end -->"
_TRAILING_EXIT_RE = re.compile(r"(?:^|\r?\n)([ \t]*exit(?:\s+\$?0|\s+\$\?)?[ \t]*)\s*\Z")


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
    if start_marker == HOOK_START_MARKER:
        match = _TRAILING_EXIT_RE.search(before_clean)
        if match:
            before_exit = before_clean[:match.start()].rstrip("\r\n")
            exit_line = match.group(1)
            prefix = f"{before_exit}\n\n" if before_exit else ""
            return f"{prefix}{block.strip()}\n\n{exit_line}\n"
    return f"{before_clean}\n\n{block.strip()}\n"


def _global_hook_script(
    subcommand: str,
    stake_bin: str,
    prev_hooks_file: Path,
    allow_fail: bool = False,
) -> str:
    suffix = " || true" if allow_fail else " || exit $?"
    return "\n".join([
        "#!/usr/bin/env sh",
        HOOK_START_MARKER,
        f'HOOK_NAME="{subcommand}"',
        'SELF_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"',
        f'PREV_HOOKS_FILE="{prev_hooks_file}"',
        'if [ "${STAKE_HOOK_CHAINED:-0}" != "1" ]; then',
        '  if [ -f "$PREV_HOOKS_FILE" ]; then',
        '    PREV_DIR="$(cat "$PREV_HOOKS_FILE" 2>/dev/null)"',
        '    if [ -n "$PREV_DIR" ] && [ -x "$PREV_DIR/$HOOK_NAME" ]; then',
        '      PREV_HOOK="$(cd "$PREV_DIR" 2>/dev/null && pwd)/$HOOK_NAME"',
        '      if [ "$PREV_HOOK" != "$SELF_PATH" ]; then',
        '        STAKE_HOOK_CHAINED=1 "$PREV_HOOK" "$@" || exit $?',
        '      fi',
        '    fi',
        '  fi',
        '  GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null)"',
        '  if [ -n "$GIT_COMMON" ] && [ -x "$GIT_COMMON/hooks/$HOOK_NAME" ]; then',
        '    LOCAL_HOOK="$(cd "$GIT_COMMON/hooks" 2>/dev/null && pwd)/$HOOK_NAME"',
        '    if [ "$LOCAL_HOOK" != "$SELF_PATH" ] && ! grep -q "# --- stake-hook-start ---" "$LOCAL_HOOK" 2>/dev/null; then',
        '      STAKE_HOOK_CHAINED=1 "$LOCAL_HOOK" "$@" || exit $?',
        '    fi',
        '  fi',
        'fi',
        f'STAKE_BIN="${{STAKE_BIN:-{stake_bin}}}"',
        'if command -v "$STAKE_BIN" >/dev/null 2>&1; then',
        f'  "$STAKE_BIN" hook {subcommand}{suffix}',
        'elif [ -x "$STAKE_BIN" ]; then',
        f'  "$STAKE_BIN" hook {subcommand}{suffix}',
        'elif command -v stake >/dev/null 2>&1; then',
        f'  stake hook {subcommand}{suffix}',
        "fi",
        HOOK_END_MARKER,
        "",
    ])


def _husky_init_block(stake_bin: str) -> str:
    return "\n".join([
        HOOK_START_MARKER,
        f'STAKE_BIN="${{STAKE_BIN:-{stake_bin}}}"',
        'STAKE_HUSKY_HOOK="$(basename "$0" 2>/dev/null)"',
        'if [ "$STAKE_HUSKY_HOOK" = "pre-commit" ] || [ "$STAKE_HUSKY_HOOK" = "pre-push" ]; then',
        '  if command -v "$STAKE_BIN" >/dev/null 2>&1; then',
        '    if [ "$STAKE_HUSKY_HOOK" = "pre-commit" ]; then "$STAKE_BIN" hook pre-commit || exit $?; else "$STAKE_BIN" hook pre-push || true; fi',
        '  elif [ -x "$STAKE_BIN" ]; then',
        '    if [ "$STAKE_HUSKY_HOOK" = "pre-commit" ]; then "$STAKE_BIN" hook pre-commit || exit $?; else "$STAKE_BIN" hook pre-push || true; fi',
        '  elif command -v stake >/dev/null 2>&1; then',
        '    if [ "$STAKE_HUSKY_HOOK" = "pre-commit" ]; then stake hook pre-commit || exit $?; else stake hook pre-push || true; fi',
        '  fi',
        'fi',
        HOOK_END_MARKER,
    ])


def _agents_md_block(stake_bin: str) -> str:
    cmd_name = "stake" if shutil.which("stake") or stake_bin == "stake" else stake_bin
    return f"""{AGENTS_START_MARKER}
## Workflow Coordination (`stake`)

**Stake** (`refs/stake/claims/*`) is installed globally at the user level as a serverless show-once radar to surface duplicate or overlapping work across teammates and branches (`development`, `release/stg`, `main`) before code is written.

1. **At Diagnosis / Plan Time (before writing code):** Once you have investigated the symptom in any Git repository and know your root cause, proposed fix, and target files, declare your claim:
   ```bash
   {cmd_name} claim --symptom "<1-sentence issue>" --fix "<1-2 sentence root cause & proposed change>" --files "<comma-separated repo-relative files>"
   ```
2. **Evaluate & surface once:** Read the active teammate claims printed by `{cmd_name} claim`. If another developer's in-flight or recently landed claim solves the same root cause or touches the same/adjacent files in the same module (including across `release/stg` vs. `development`), present a brief side-by-side comparison to the user. If the user chooses to proceed anyway (or re-runs `git commit`), `stake` records the claim as seen and never blocks flow twice.
3. **Repository Opt-Out / Opt-In:** Use `{cmd_name} disable` or `{cmd_name} enable` (configured in `~/.config/stake/config.json`) to exclude or include specific repositories.
{AGENTS_END_MARKER}"""


def _skill_md_content(stake_bin: str) -> str:
    cmd_name = "stake" if shutil.which("stake") or stake_bin == "stake" else stake_bin
    return f"""---
name: stake
description: Use when declaring a root-cause diagnosis and proposed fix before writing code in any Git repository, or when managing Stake user-level setup and repository filtering.
---

# Stake: Serverless Git-Ref Duplicate-Work Radar

## User-Level Setup (One-Time)

Configure global Git hooks, repository filtering (`~/.config/stake/config.json`), and user-level agent instructions:

```bash
{cmd_name} setup
```

To exclude or re-enable a specific repository:

```bash
{cmd_name} disable --repo "<REPO_PATH>"
{cmd_name} enable --repo "<REPO_PATH>"
```

## Using `stake` During Feature / Bugfix Work

1. **Declare at Diagnosis / Plan Time (Not Session Start):**
   Wait until you have investigated the symptom and identified the root cause, proposed fix, and target files (write-set only, never files merely read during exploration):
   ```bash
   {cmd_name} claim \\
     --symptom "<1-sentence symptom>" \\
     --fix "<1-2 sentence root cause and proposed fix>" \\
     --files "<comma-separated repo-relative file paths>"
   ```
2. **Evaluate Returned Claims:**
   Inspect the active teammate claims printed by `{cmd_name} claim`. If another developer's claim solves the same underlying root cause or modifies the same/adjacent files in the same module (including across `release/stg` vs. `development`), show the user a concise side-by-side comparison.
3. **Show-Once Bypass:**
   If the user wants to proceed anyway (or if `pre-commit` surfaces a new overlap once), simply continue or re-run `git commit` (`stake` records seen claims in `.git/stake-state.json` and never blocks twice).
"""


def setup_user(
    home_dir: Path | str | None = None,
    config_dir: Path | str | None = None,
    stake_bin: str | None = None,
) -> dict[str, str]:
    """Install user-level Git hooks, Husky init, config.json, and global agent instructions."""
    resolved_home = get_home_dir(home_dir)
    resolved_cfg = get_config_dir(config_dir=config_dir, home_dir=resolved_home)
    resolved_bin = stake_bin or _default_stake_bin()

    resolved_cfg.mkdir(parents=True, exist_ok=True)
    config_file = resolved_cfg / CONFIG_FILENAME
    if not config_file.exists():
        save_config(StakeConfig(), config_dir=resolved_cfg, home_dir=resolved_home)

    hooks_dir = resolved_cfg / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    prev_hooks_file = resolved_cfg / "previous_hooks_path"

    gitconfig_path = resolved_home / ".gitconfig"
    existing_hooks_res = subprocess.run(
        ["git", "config", "--file", str(gitconfig_path), "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    existing_hooks_raw = existing_hooks_res.stdout.strip() if existing_hooks_res.returncode == 0 else ""
    if existing_hooks_raw:
        existing_hooks_path = Path(existing_hooks_raw).expanduser().resolve()
        if existing_hooks_path != hooks_dir.resolve():
            prev_hooks_file.write_text(str(existing_hooks_path) + "\n", encoding="utf-8")

    subprocess.run(
        ["git", "config", "--file", str(gitconfig_path), "core.hooksPath", str(hooks_dir)],
        capture_output=True,
        text=True,
        check=True,
    )

    pre_commit = hooks_dir / "pre-commit"
    pre_push = hooks_dir / "pre-push"
    pre_commit.write_text(
        _global_hook_script("pre-commit", resolved_bin, prev_hooks_file, allow_fail=False),
        encoding="utf-8",
    )
    pre_commit.chmod(0o755)

    pre_push.write_text(
        _global_hook_script("pre-push", resolved_bin, prev_hooks_file, allow_fail=True),
        encoding="utf-8",
    )
    pre_push.chmod(0o755)

    husky_init = resolved_home / ".config" / "husky" / "init.sh"
    husky_init.parent.mkdir(parents=True, exist_ok=True)
    existing_husky = husky_init.read_text(encoding="utf-8") if husky_init.exists() else "#!/usr/bin/env sh\n"
    husky_init.write_text(
        _upsert_fenced_block(existing_husky, HOOK_START_MARKER, HOOK_END_MARKER, _husky_init_block(resolved_bin)),
        encoding="utf-8",
    )

    agent_block = _agents_md_block(resolved_bin)
    claude_md = resolved_home / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    existing_claude = claude_md.read_text(encoding="utf-8") if claude_md.exists() else "# User Instructions\n"
    claude_md.write_text(
        _upsert_fenced_block(existing_claude, AGENTS_START_MARKER, AGENTS_END_MARKER, agent_block),
        encoding="utf-8",
    )

    gemini_md = resolved_home / ".gemini" / "GEMINI.md"
    gemini_md.parent.mkdir(parents=True, exist_ok=True)
    existing_gemini = gemini_md.read_text(encoding="utf-8") if gemini_md.exists() else "# User Instructions\n"
    gemini_md.write_text(
        _upsert_fenced_block(existing_gemini, AGENTS_START_MARKER, AGENTS_END_MARKER, agent_block),
        encoding="utf-8",
    )

    skill_md = resolved_home / ".agents" / "skills" / "stake" / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(_skill_md_content(resolved_bin), encoding="utf-8")

    return {
        "config_file": str(config_file),
        "hooks_dir": str(hooks_dir),
        "pre_commit": str(pre_commit),
        "pre_push": str(pre_push),
        "husky_init": str(husky_init),
        "claude_md": str(claude_md),
        "gemini_md": str(gemini_md),
        "skill_md": str(skill_md),
    }
