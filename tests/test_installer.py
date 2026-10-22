import stat
import subprocess
import sys
from pathlib import Path
from stake.installer import (
    AGENTS_START_MARKER,
    HOOK_START_MARKER,
    init_repo,
)
from tests._runner import make_suite


def test_init_repo_preserves_existing_hook_and_is_idempotent(tmp_path: Path):
    repo = tmp_path / "target"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    hooks_dir = repo / ".git" / "hooks"
    pre_commit = hooks_dir / "pre-commit"
    # Existing hook without trailing newline
    pre_commit.write_text("#!/bin/sh\necho 'running linter'")
    pre_commit.chmod(0o755)

    init_repo(str(repo), stake_bin="/usr/local/bin/stake")
    first_hook = pre_commit.read_text()
    first_agents = (repo / "AGENTS.md").read_text()

    init_repo(str(repo), stake_bin="/usr/local/bin/stake")  # second run must be byte-idempotent

    content = pre_commit.read_text()
    assert content == first_hook
    assert content.startswith("#!/bin/sh\necho 'running linter'\n")
    assert content.count(HOOK_START_MARKER) == 1
    assert "stake hook pre-commit" in content
    assert bool(pre_commit.stat().st_mode & stat.S_IXUSR)

    agents_md = (repo / "AGENTS.md").read_text()
    assert agents_md == first_agents
    assert agents_md.count(AGENTS_START_MARKER) == 1
    assert "stake claim" in agents_md


def test_init_repo_respects_custom_core_hooks_path(tmp_path: Path):
    repo = tmp_path / "custom_hooks_repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    custom_dir = repo / ".githooks"
    custom_dir.mkdir()
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True, capture_output=True)

    init_repo(str(repo), stake_bin="/usr/local/bin/stake")
    assert (custom_dir / "pre-commit").exists()
    assert (custom_dir / "pre-push").exists()


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
