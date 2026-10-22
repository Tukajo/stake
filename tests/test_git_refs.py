import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from stake.models import ClaimRecord, LocalState
from stake.git_refs import (
    get_git_dirs,
    get_repo_identity,
    load_local_state,
    read_local_claim_refs,
    save_local_state,
    sync_claims_with_remote,
    write_local_claim_ref,
)
from tests._runner import make_suite


def _init_clone(tmp_path: Path, name: str, bare_remote: Path, email: str, user: str) -> Path:
    clone = tmp_path / name
    subprocess.run(["git", "clone", str(bare_remote), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", email], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", user], check=True, capture_output=True)
    return clone


def test_write_claim_ref_has_zero_parents_and_overwrites_in_place(tmp_path: Path):
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    alice = _init_clone(tmp_path, "alice", remote, "alice@example.com", "Alice")
    subprocess.run(["git", "-C", str(alice), "checkout", "-b", "development"], check=True, capture_output=True)
    (alice / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(alice), "add", "app.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(alice), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(alice), "push", "-u", "origin", "development"], check=True, capture_output=True)

    now = datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc)
    c1 = ClaimRecord.create("alice@example.com", "Alice", "fix/a", "development", "s1", "f1", ["app.py"], "planned", now=now)
    sha1 = write_local_claim_ref(str(alice), c1)
    c2 = ClaimRecord.create("alice@example.com", "Alice", "fix/a", "development", "s1", "f2", ["app.py"], "committed", now=now)
    sha2 = write_local_claim_ref(str(alice), c2)

    assert sha1 != sha2
    parents = subprocess.run(
        ["git", "-C", str(alice), "rev-list", "--parents", "-n", "1", sha2],
        check=True, capture_output=True, text=True
    ).stdout.strip().split()
    assert len(parents) == 1  # parentless orphan commit (depth = 1)


def test_sync_claims_fetches_across_clones_and_prunes_expired(tmp_path: Path):
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    alice = _init_clone(tmp_path, "alice", remote, "alice@example.com", "Alice")
    bob = _init_clone(tmp_path, "bob", remote, "bob@example.com", "Bob")

    t0 = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
    stale = ClaimRecord.create("alice@example.com", "Alice", "fix/old", "development", "old", "old fix", ["a.py"], "planned", now=t0)
    sync_claims_with_remote(str(alice), push_claim=stale, now=t0)

    # 5 hours later (> 4h planned TTL), Bob syncs his own claim and prunes Alice's expired ref
    t1 = t0 + timedelta(hours=5)
    bob_claim = ClaimRecord.create("bob@example.com", "Bob", "fix/new", "release/stg", "new", "new fix", ["b.py"], "planned", now=t1)
    active, remote_ok = sync_claims_with_remote(str(bob), push_claim=bob_claim, now=t1)
    assert remote_ok is True
    assert [c.claim_id for c in active] == [bob_claim.claim_id]

    remote_refs = subprocess.run(
        ["git", "--git-dir", str(remote), "for-each-ref", "--format=%(refname)", "refs/stake/claims/"],
        check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert remote_refs == [f"refs/stake/claims/{bob_claim.claim_id}"]


def test_current_branch_detached_head_fallback_and_worktree_support(tmp_path: Path):
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = _init_clone(tmp_path, "repo", remote, "dev@example.com", "Dev")
    (repo / "f.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "--detach", "HEAD"], check=True, capture_output=True)

    email, name, branch, base = get_repo_identity(str(repo))
    assert branch.startswith("detached-")

    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "feat/wt", str(wt)], check=True, capture_output=True)
    root, git_dir, common_dir = get_git_dirs(str(wt))
    assert git_dir != common_dir
    save_local_state(str(wt), LocalState(claim_id="c1", branch="feat/wt", declared_modules=[], declared_files=[], symptom="s", diagnosis_and_fix="f", seen_claims=["x"]))
    assert load_local_state(str(wt)).seen_claims == ["x"]


def test_offline_remote_fails_open_with_zero_exit(tmp_path: Path):
    repo = tmp_path / "offline"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "/nonexistent/path/repo.git"], check=True, capture_output=True)
    now = datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc)
    c = ClaimRecord.create("a@b.com", "A", "main", "main", "s", "f", ["x.py"], "planned", now=now)
    active, remote_ok = sync_claims_with_remote(str(repo), push_claim=c, now=now)
    assert remote_ok is False
    assert [x.claim_id for x in active] == [c.claim_id]


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
