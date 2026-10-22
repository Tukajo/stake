"""Git plumbing for reading, writing, syncing, and pruning refs/stake/claims/*."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from stake.models import ClaimRecord, LocalState

REF_PREFIX: str = "refs/stake/claims/"
STATE_FILENAME: str = "stake-state.json"

_CANDIDATE_BASE_BRANCHES: tuple[str, ...] = (
    "development",
    "dev",
    "release/stg",
    "release",
    "stg",
    "staging",
    "main",
    "master",
)


def _git_timeout() -> float:
    try:
        return float(os.environ.get("STAKE_GIT_TIMEOUT_SEC", "3"))
    except ValueError:
        return 3.0


def _run_git(
    repo_path: str,
    args: list[str],
    input_text: str | None = None,
    timeout: float | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def get_git_dirs(repo_path: str = ".") -> tuple[Path, Path, Path]:
    """Return resolved (repo_root, git_dir, git_common_dir) supporting linked worktrees."""
    base = Path(repo_path).resolve()
    res = _run_git(
        str(base),
        ["rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir"],
    )
    lines = res.stdout.strip().splitlines()
    repo_root = Path(lines[0]).resolve()
    raw_git_dir = Path(lines[1])
    raw_common_dir = Path(lines[2])
    git_dir = (raw_git_dir if raw_git_dir.is_absolute() else (base / raw_git_dir)).resolve()
    git_common_dir = (raw_common_dir if raw_common_dir.is_absolute() else (base / raw_common_dir)).resolve()
    return repo_root, git_dir, git_common_dir


def _detect_base_branch(repo_path: str, current_branch: str) -> str:
    if current_branch in _CANDIDATE_BASE_BRANCHES:
        return current_branch

    best_branch: str | None = None
    best_distance: int | None = None

    for candidate in _CANDIDATE_BASE_BRANCHES:
        for ref_prefix in ("refs/remotes/origin/", "refs/heads/"):
            ref = f"{ref_prefix}{candidate}"
            Verify = _run_git(repo_path, ["rev-parse", "--verify", "--quiet", ref], check=False)
            if Verify.returncode != 0:
                continue
            mb = _run_git(repo_path, ["merge-base", "HEAD", ref], check=False)
            if mb.returncode != 0 or not mb.stdout.strip():
                continue
            base_sha = mb.stdout.strip()
            dist_res = _run_git(repo_path, ["rev-list", "--count", f"{base_sha}..HEAD"], check=False)
            if dist_res.returncode == 0 and dist_res.stdout.strip().isdigit():
                dist = int(dist_res.stdout.strip())
                if best_distance is None or dist < best_distance:
                    best_distance = dist
                    best_branch = candidate
    return best_branch or current_branch or "main"


def get_repo_identity(repo_path: str = ".") -> tuple[str, str, str, str]:
    """Return (owner_email, owner_name, branch, base_branch) for the repository."""
    email_res = _run_git(repo_path, ["config", "--get", "user.email"], check=False)
    name_res = _run_git(repo_path, ["config", "--get", "user.name"], check=False)
    owner_email = email_res.stdout.strip() or os.environ.get("USER", "unknown") + "@localhost"
    owner_name = name_res.stdout.strip() or owner_email.split("@")[0]

    branch_res = _run_git(repo_path, ["branch", "--show-current"], check=False)
    branch = branch_res.stdout.strip()
    if not branch:
        sha_res = _run_git(repo_path, ["rev-parse", "--short", "HEAD"], check=False)
        short_sha = sha_res.stdout.strip() or "unborn"
        branch = f"detached-{short_sha}"

    base_branch = _detect_base_branch(repo_path, branch)
    return owner_email, owner_name, branch, base_branch


def write_local_claim_ref(repo_path: str, claim: ClaimRecord) -> str:
    """Write claim as a parentless commit (depth = 1) at refs/stake/claims/<claim_id>."""
    blob_sha = _run_git(
        repo_path,
        ["hash-object", "-w", "--stdin"],
        input_text=claim.to_json(),
    ).stdout.strip()

    tree_line = f"100644 blob {blob_sha}\tclaim.json\n"
    tree_sha = _run_git(
        repo_path,
        ["mktree"],
        input_text=tree_line,
    ).stdout.strip()

    commit_sha = _run_git(
        repo_path,
        ["commit-tree", tree_sha, "-m", f"stake claim {claim.claim_id}"],
    ).stdout.strip()

    ref_name = f"{REF_PREFIX}{claim.claim_id}"
    _run_git(repo_path, ["update-ref", ref_name, commit_sha])
    return commit_sha


def read_local_claim_refs(repo_path: str) -> list[ClaimRecord]:
    """Read all local refs/stake/claims/* records."""
    res = _run_git(
        repo_path,
        ["for-each-ref", "--format=%(refname)", REF_PREFIX],
        check=False,
    )
    if res.returncode != 0 or not res.stdout.strip():
        return []

    claims: list[ClaimRecord] = []
    for ref in res.stdout.strip().splitlines():
        ref = ref.strip()
        if not ref:
            continue
        blob_res = _run_git(repo_path, ["show", f"{ref}:claim.json"], check=False)
        if blob_res.returncode != 0 or not blob_res.stdout.strip():
            continue
        try:
            claims.append(ClaimRecord.from_json(blob_res.stdout))
        except (ValueError, KeyError):
            continue
    return sorted(claims, key=lambda c: c.claim_id)


def delete_local_claim_ref(repo_path: str, claim_id: str) -> None:
    ref_name = f"{REF_PREFIX}{claim_id}"
    _run_git(repo_path, ["update-ref", "-d", ref_name], check=False)


def sync_claims_with_remote(
    repo_path: str,
    push_claim: ClaimRecord | None = None,
    now: datetime | None = None,
) -> tuple[list[ClaimRecord], bool]:
    """Fetch remote claims, write push_claim, prune expired refs, and push.

    Fails open (returns (local_active_claims, False)) if origin is missing or unreachable.
    """
    current_time = now or datetime.now(timezone.utc)
    timeout = _git_timeout()
    remote_ok = True

    try:
        fetch_res = _run_git(
            repo_path,
            ["fetch", "--prune", "--no-tags", "origin", f"+{REF_PREFIX}*:{REF_PREFIX}*"],
            timeout=timeout,
            check=False,
        )
        if fetch_res.returncode != 0:
            remote_ok = False
    except (subprocess.SubprocessError, OSError):
        remote_ok = False

    if push_claim is not None:
        write_local_claim_ref(repo_path, push_claim)

    all_local = read_local_claim_refs(repo_path)
    active: list[ClaimRecord] = []
    expired_ids: list[str] = []

    for claim in all_local:
        if claim.is_expired(current_time):
            expired_ids.append(claim.claim_id)
            delete_local_claim_ref(repo_path, claim.claim_id)
        else:
            active.append(claim)

    if remote_ok:
        for exp_id in expired_ids:
            try:
                _run_git(
                    repo_path,
                    ["push", "origin", "--delete", f"{REF_PREFIX}{exp_id}"],
                    timeout=timeout,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError):
                pass

        if push_claim is not None and not push_claim.is_expired(current_time):
            ref = f"{REF_PREFIX}{push_claim.claim_id}"
            try:
                push_res = _run_git(
                    repo_path,
                    ["push", "--force", "origin", f"{ref}:{ref}"],
                    timeout=timeout,
                    check=False,
                )
                if push_res.returncode != 0:
                    remote_ok = False
            except (subprocess.SubprocessError, OSError):
                remote_ok = False

    return active, remote_ok


def load_local_state(repo_path: str = ".") -> LocalState:
    """Load per-worktree stake-state.json receipt from git_dir."""
    _, git_dir, _ = get_git_dirs(repo_path)
    state_file = git_dir / STATE_FILENAME
    if not state_file.exists():
        return LocalState()
    try:
        return LocalState.from_dict(json.loads(state_file.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return LocalState()


def save_local_state(repo_path: str, state: LocalState) -> None:
    """Persist per-worktree stake-state.json receipt inside git_dir."""
    _, git_dir, _ = get_git_dirs(repo_path)
    state_file = git_dir / STATE_FILENAME
    state_file.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
