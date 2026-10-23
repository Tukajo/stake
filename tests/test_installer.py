import stat
import subprocess
import sys
from pathlib import Path
from stake.installer import (
    AGENTS_END_MARKER,
    AGENTS_START_MARKER,
    HOOK_END_MARKER,
    HOOK_START_MARKER,
    _upsert_fenced_block,
    setup_user,
)
from tests._runner import make_suite


def test_setup_user_creates_global_files_and_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    cfg = home / ".config" / "stake"

    info1 = setup_user(home_dir=home, config_dir=cfg, stake_bin="/usr/local/bin/stake")
    pre_commit = Path(info1["pre_commit"])
    pre_push = Path(info1["pre_push"])
    claude_md = Path(info1["claude_md"])
    gemini_md = Path(info1["gemini_md"])
    skill_md = Path(info1["skill_md"])
    husky_init = Path(info1["husky_init"])
    config_file = Path(info1["config_file"])

    assert pre_commit.exists() and bool(pre_commit.stat().st_mode & stat.S_IXUSR)
    assert pre_push.exists() and bool(pre_push.stat().st_mode & stat.S_IXUSR)
    assert claude_md.exists() and claude_md.read_text().count(AGENTS_START_MARKER) == 1
    assert gemini_md.exists() and gemini_md.read_text().count(AGENTS_START_MARKER) == 1
    assert skill_md.exists() and "stake claim" in skill_md.read_text()
    assert "stake init" not in claude_md.read_text()
    assert "stake init" not in skill_md.read_text()
    assert husky_init.exists() and husky_init.read_text().count(HOOK_START_MARKER) == 1
    assert config_file.exists()

    snap = {p: p.read_text() for p in (pre_commit, pre_push, claude_md, gemini_md, skill_md, husky_init, config_file)}
    setup_user(home_dir=home, config_dir=cfg, stake_bin="/usr/local/bin/stake")
    for p, before in snap.items():
        assert p.read_text() == before

    res = subprocess.run(
        ["git", "config", "--file", str(home / ".gitconfig"), "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert Path(res.stdout.strip()) == cfg / "hooks"


def test_global_pre_commit_chains_repo_local_hook_and_respects_failure(tmp_path: Path):
    home = tmp_path / "home"
    cfg = home / ".config" / "stake"
    dummy_stake = tmp_path / "dummy_stake"
    marker = tmp_path / "stake_ran"
    dummy_stake.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    dummy_stake.chmod(0o755)

    info = setup_user(home_dir=home, config_dir=cfg, stake_bin=str(dummy_stake))
    global_pre_commit = Path(info["pre_commit"])

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    local_hook = repo / ".git" / "hooks" / "pre-commit"

    # 1. Failing local hook must abort before stake runs
    local_hook.write_text("#!/bin/sh\necho 'linter failed' >&2\nexit 1\n")
    local_hook.chmod(0o755)
    r1 = subprocess.run([str(global_pre_commit)], cwd=str(repo), capture_output=True, text=True)
    assert r1.returncode == 1
    assert "linter failed" in r1.stderr
    assert not marker.exists()

    # 2. Passing local hook chains into stake
    local_marker = tmp_path / "local_ran"
    local_hook.write_text(f"#!/bin/sh\ntouch '{local_marker}'\nexit 0\n")
    r2 = subprocess.run([str(global_pre_commit)], cwd=str(repo), capture_output=True, text=True)
    assert r2.returncode == 0
    assert local_marker.exists()
    assert marker.exists()


def test_global_pre_commit_chains_in_linked_worktree(tmp_path: Path):
    home = tmp_path / "home"
    cfg = home / ".config" / "stake"
    dummy_stake = tmp_path / "dummy_stake"
    dummy_stake.write_text("#!/bin/sh\nexit 0\n")
    dummy_stake.chmod(0o755)
    info = setup_user(home_dir=home, config_dir=cfg, stake_bin=str(dummy_stake))

    repo = tmp_path / "main_repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "a@b.c"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "A"], check=True)
    (repo / "f.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "wt-branch", str(wt)], check=True, capture_output=True)

    local_marker = tmp_path / "wt_local_hook_ran"
    local_hook = repo / ".git" / "hooks" / "pre-commit"
    local_hook.write_text(f"#!/bin/sh\ntouch '{local_marker}'\nexit 0\n")
    local_hook.chmod(0o755)

    res = subprocess.run([info["pre_commit"]], cwd=str(wt), capture_output=True, text=True)
    assert res.returncode == 0
    assert local_marker.exists()


def test_setup_user_preserves_and_chains_previous_global_hooks_path(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    prev_hooks = tmp_path / "prev_global_hooks"
    prev_hooks.mkdir(parents=True)
    prev_marker = tmp_path / "prev_ran"
    prev_pre_commit = prev_hooks / "pre-commit"
    prev_pre_commit.write_text(f"#!/bin/sh\ntouch '{prev_marker}'\nexit 0\n")
    prev_pre_commit.chmod(0o755)

    subprocess.run(
        ["git", "config", "--file", str(home / ".gitconfig"), "core.hooksPath", str(prev_hooks)],
        check=True,
    )

    cfg = home / ".config" / "stake"
    dummy_stake = tmp_path / "dummy_stake"
    dummy_stake.write_text("#!/bin/sh\nexit 0\n")
    dummy_stake.chmod(0o755)

    info = setup_user(home_dir=home, config_dir=cfg, stake_bin=str(dummy_stake))
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)

    res = subprocess.run([info["pre_commit"]], cwd=str(repo), capture_output=True, text=True)
    assert res.returncode == 0
    assert prev_marker.exists()


def test_upsert_fenced_block_handles_exit_variants():
    block = f"{HOOK_START_MARKER}\necho 'stake'\n{HOOK_END_MARKER}"

    for exit_stmt in ("exit", "exit 0", "exit $0", "exit $?", "  exit 0  "):
        script = f"#!/bin/sh\nrun_something\n{exit_stmt}\n"
        first = _upsert_fenced_block(script, HOOK_START_MARKER, HOOK_END_MARKER, block)
        second = _upsert_fenced_block(first, HOOK_START_MARKER, HOOK_END_MARKER, block)
        assert first == second
        assert first.index("run_something") < first.index(HOOK_START_MARKER) < first.rindex(exit_stmt.strip())
        assert first.endswith(f"\n\n{exit_stmt}\n")

    err_script = "#!/bin/sh\nexit 1\n"
    res = _upsert_fenced_block(err_script, HOOK_START_MARKER, HOOK_END_MARKER, block)
    assert res.index("exit 1") < res.index(HOOK_START_MARKER)

    agents_block = f"{AGENTS_START_MARKER}\ncontent\n{AGENTS_END_MARKER}"
    md_content = "# Doc\nexit 0\n"
    res_md = _upsert_fenced_block(md_content, AGENTS_START_MARKER, AGENTS_END_MARKER, agents_block)
    assert res_md.index("exit 0") < res_md.index(AGENTS_START_MARKER)


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
