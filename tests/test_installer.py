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


def test_init_repo_supports_husky_hooks_path(tmp_path: Path):
    repo = tmp_path / "husky_repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    husky_dir = repo / ".husky"
    husky_internal = husky_dir / "_"
    husky_internal.mkdir(parents=True)
    (husky_internal / ".gitignore").write_text("*")
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".husky/_"], check=True, capture_output=True)

    init_repo(str(repo), stake_bin="/usr/local/bin/stake")
    assert (husky_dir / "pre-commit").exists()
    assert (husky_dir / "pre-push").exists()
    assert not (husky_internal / "pre-push").exists()


def test_init_repo_inserts_hook_before_trailing_exit_and_stays_idempotent(tmp_path: Path):
    repo = tmp_path / "exit_hook_repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    hooks_dir = repo / ".git" / "hooks"
    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text("#!/bin/sh\necho 'custom check'\nexit 0\n")
    pre_commit.chmod(0o755)

    dummy_stake = tmp_path / "dummy_stake"
    dummy_stake.write_text("#!/bin/sh\nexit 1\n")
    dummy_stake.chmod(0o755)

    init_repo(str(repo), stake_bin=str(dummy_stake))
    first = pre_commit.read_text()
    init_repo(str(repo), stake_bin=str(dummy_stake))
    second = pre_commit.read_text()

    assert first == second
    assert first.count(HOOK_START_MARKER) == 1
    assert first.index("echo 'custom check'") < first.index(HOOK_START_MARKER) < first.rindex("exit 0")

    run_res = subprocess.run([str(pre_commit)], capture_output=True)
    assert run_res.returncode != 0


def test_upsert_fenced_block_handles_exit_variants():
    from stake.installer import (
        HOOK_START_MARKER,
        HOOK_END_MARKER,
        AGENTS_START_MARKER,
        AGENTS_END_MARKER,
        _upsert_fenced_block,
    )

    block = f"{HOOK_START_MARKER}\necho 'stake'\n{HOOK_END_MARKER}"

    # Test variants: exit, exit $0, exit $?
    for exit_stmt in ("exit", "exit 0", "exit $0", "exit $?", "  exit 0  "):
        script = f"#!/bin/sh\nrun_something\n{exit_stmt}\n"
        first = _upsert_fenced_block(script, HOOK_START_MARKER, HOOK_END_MARKER, block)
        second = _upsert_fenced_block(first, HOOK_START_MARKER, HOOK_END_MARKER, block)
        assert first == second
        assert first.index("run_something") < first.index(HOOK_START_MARKER) < first.rindex(exit_stmt.strip())
        assert first.endswith(f"\n\n{exit_stmt}\n")

    # Exit 1 should not match trailing clean exit; block should append after exit 1
    err_script = "#!/bin/sh\nexit 1\n"
    res = _upsert_fenced_block(err_script, HOOK_START_MARKER, HOOK_END_MARKER, block)
    assert res.index("exit 1") < res.index(HOOK_START_MARKER)

    # AGENTS marker should ignore trailing exit statements in markdown
    agents_block = f"{AGENTS_START_MARKER}\ncontent\n{AGENTS_END_MARKER}"
    md_content = "# Doc\nexit 0\n"
    res_md = _upsert_fenced_block(md_content, AGENTS_START_MARKER, AGENTS_END_MARKER, agents_block)
    assert res_md.index("exit 0") < res_md.index(AGENTS_START_MARKER)


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
