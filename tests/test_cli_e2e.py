import subprocess
import sys
from pathlib import Path
from stake.cli import main
from tests._runner import make_suite


def _setup_two_devs(tmp_path: Path, stake_bin: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(remote), str(seed)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.email", "seed@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.name", "Seed"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "checkout", "-b", "development"], check=True, capture_output=True)
    (seed / "src" / "permissions").mkdir(parents=True)
    (seed / "src" / "permissions" / "org_loader.ts").write_text("export const load = () => {};\n")
    (seed / "src" / "permissions" / "resolver.ts").write_text("export const resolve = () => {};\n")
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-m", "initial"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "push", "-u", "origin", "development"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "checkout", "-b", "release/stg"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "push", "-u", "origin", "release/stg"], check=True, capture_output=True)

    alice = tmp_path / "alice"
    bob = tmp_path / "bob"
    subprocess.run(["git", "clone", "-b", "development", str(remote), str(alice)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(alice), "config", "user.email", "alice@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(alice), "config", "user.name", "Alice"], check=True, capture_output=True)

    subprocess.run(["git", "clone", "-b", "release/stg", str(remote), str(bob)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(bob), "config", "user.email", "bob@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(bob), "config", "user.name", "Bob"], check=True, capture_output=True)

    assert main(["init", "--repo", str(alice)]) == 0
    assert main(["init", "--repo", str(bob)]) == 0
    return remote, alice, bob


def test_e2e_plan_checkin_and_silent_commit(tmp_path: Path):
    stake_bin = Path("/home/tjfrisch/Code/stake/bin/stake")
    _, alice, bob = _setup_two_devs(tmp_path, stake_bin)

    subprocess.run(["git", "-C", str(alice), "checkout", "-b", "fix/PROJ-412-csv"], check=True, capture_output=True)
    assert main([
        "claim", "--repo", str(alice),
        "--symptom", "CSV export hangs",
        "--fix", "Batch N+1 org permission queries",
        "--files", "src/permissions/org_loader.ts",
    ]) == 0

    # Alice commits within her declared module -> pre-commit is 100% silent and exits 0
    (alice / "src" / "permissions" / "org_loader.ts").write_text("export const load = () => 'batched';\n")
    subprocess.run(["git", "-C", str(alice), "add", "."], check=True, capture_output=True)
    res = subprocess.run(["git", "-C", str(alice), "commit", "-m", "fix: batch loader"], capture_output=True, text=True)
    assert res.returncode == 0


def test_e2e_skipped_plan_stops_once_at_precommit_then_bypasses_on_retry(tmp_path: Path):
    stake_bin = Path("/home/tjfrisch/Code/stake/bin/stake")
    _, alice, bob = _setup_two_devs(tmp_path, stake_bin)

    # Alice declares on development
    subprocess.run(["git", "-C", str(alice), "checkout", "-b", "fix/PROJ-412-csv"], check=True, capture_output=True)
    assert main([
        "claim", "--repo", str(alice),
        "--symptom", "CSV export hangs",
        "--fix", "Batch N+1 org permission queries",
        "--files", "src/permissions/org_loader.ts",
    ]) == 0

    # Bob hotfixes release/stg in adjacent file WITHOUT running `stake claim`
    subprocess.run(["git", "-C", str(bob), "checkout", "-b", "hotfix/OPS-88-504"], check=True, capture_output=True)
    (bob / "src" / "permissions" / "resolver.ts").write_text("export const resolve = () => 'cached';\n")
    subprocess.run(["git", "-C", str(bob), "add", "."], check=True, capture_output=True)

    # First commit attempt warns once about Alice's cross-branch overlap and exits non-zero
    c1 = subprocess.run(["git", "-C", str(bob), "commit", "-m", "fix: cache resolver"], capture_output=True, text=True)
    assert c1.returncode != 0
    assert "alice@example.com" in c1.stderr
    assert "CROSS-BRANCH" in c1.stderr

    # Second commit attempt immediately succeeds (show-once semantics)
    c2 = subprocess.run(["git", "-C", str(bob), "commit", "-m", "fix: cache resolver"], capture_output=True, text=True)
    assert c2.returncode == 0


def test_e2e_cli_offline_remote_logs_warning_and_exits_zero(tmp_path: Path):
    repo = tmp_path / "offline_cli"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "dev@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Dev"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "/nonexistent/origin.git"], check=True, capture_output=True)

    assert main(["init", "--repo", str(repo)]) == 0
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.py"], check=True, capture_output=True)
    commit_res = subprocess.run(["git", "-C", str(repo), "commit", "-m", "offline commit"], capture_output=True, text=True)
    assert commit_res.returncode == 0
    assert "stake: remote unreachable, continuing offline" in commit_res.stderr


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
