import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from stake.cli import main
from stake.git_refs import (
    is_git_repo,
    write_local_claim_ref,
)
from stake.models import ClaimRecord
from tests._runner import make_suite


def _setup_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "STAKE_SKIP": "1"}
    subprocess.run(["git", "-C", str(repo), "init"], env=env, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "alice@example.com"], env=env, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Alice"], env=env, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], env=env, check=True, capture_output=True)
    (repo / "README.md").write_text("# Hello\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], env=env, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], env=env, check=True, capture_output=True)
    return repo


def test_is_git_repo_true_for_git_repo(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    assert is_git_repo(str(repo)) is True


def test_is_git_repo_false_for_non_git_dir(tmp_path: Path):
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    assert is_git_repo(str(non_git)) is False


def test_non_git_repo_returns_clean_error(tmp_path: Path):
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()

    stderr_buf = io.StringIO()
    stdout_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf), patch("sys.stdout", stdout_buf):
        rc = main(["list", "--repo", str(non_git)])

    assert rc == 1
    err = stderr_buf.getvalue()
    assert "stake: not a git repository" in err


def test_list_claims_empty(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    stdout_buf = io.StringIO()
    with patch("sys.stdout", stdout_buf):
        rc = main(["list", "--repo", str(repo)])
    assert rc == 0
    assert "No active claims found." in stdout_buf.getvalue()


def test_list_claims_subcommand_syntax(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    now = datetime.now(timezone.utc)
    c = ClaimRecord.create(
        owner_email="alice@example.com",
        owner_name="Alice",
        branch="feat/test",
        base_branch="main",
        symptom="Missing feature",
        diagnosis_and_fix="Implement feature",
        files=["stake/cli.py"],
        now=now,
    )
    write_local_claim_ref(str(repo), c)

    buf1 = io.StringIO()
    with patch("sys.stdout", buf1):
        rc1 = main(["list", "--repo", str(repo)])
    assert rc1 == 0

    buf2 = io.StringIO()
    with patch("sys.stdout", buf2):
        rc2 = main(["list", "claims", "--repo", str(repo)])
    assert rc2 == 0

    assert buf1.getvalue() == buf2.getvalue()
    assert "feat/test" in buf1.getvalue()


def test_list_claims_formatting_and_ordering(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    base_time = datetime.now(timezone.utc)

    # Older claim
    c1 = ClaimRecord.create(
        owner_email="bob@example.com",
        owner_name="Bob",
        branch="feat/older",
        base_branch="main",
        symptom="Old bug",
        diagnosis_and_fix="Fix old bug",
        files=["old.py"],
        now=base_time - timedelta(hours=1),
    )
    # Newer claim
    c2 = ClaimRecord.create(
        owner_email="alice@example.com",
        owner_name="Alice",
        branch="feat/newer",
        base_branch="main",
        symptom="New bug",
        diagnosis_and_fix="Fix new bug",
        files=["new.py"],
        ticket="PROJ-999",
        now=base_time - timedelta(minutes=5),
    )
    write_local_claim_ref(str(repo), c1)
    write_local_claim_ref(str(repo), c2)

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = main(["list", "--repo", str(repo)])
    assert rc == 0
    out = buf.getvalue()
    assert "Active claims (2):" in out
    assert "[PROJ-999]" in out
    # Newer claim should appear before older claim
    idx_newer = out.find("feat/newer")
    idx_older = out.find("feat/older")
    assert idx_newer != -1 and idx_older != -1
    assert idx_newer < idx_older


def test_list_claims_truncation_default_limit(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    base_time = datetime.now(timezone.utc)

    # Create 12 claims
    for i in range(12):
        c = ClaimRecord.create(
            owner_email=f"dev{i}@example.com",
            owner_name=f"Dev{i}",
            branch=f"feat/branch-{i}",
            base_branch="main",
            symptom=f"Issue {i}",
            diagnosis_and_fix=f"Fix {i}",
            files=[f"file_{i}.py"],
            now=base_time - timedelta(minutes=i),
        )
        write_local_claim_ref(str(repo), c)

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = main(["list", "--repo", str(repo)])
    assert rc == 0
    out = buf.getvalue()
    assert "Active claims (12):" in out
    assert "Showing 10 of 12 active claims. Use --all to view all." in out


def test_list_claims_all_flag(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    base_time = datetime.now(timezone.utc)

    for i in range(12):
        c = ClaimRecord.create(
            owner_email=f"dev{i}@example.com",
            owner_name=f"Dev{i}",
            branch=f"feat/branch-{i}",
            base_branch="main",
            symptom=f"Issue {i}",
            diagnosis_and_fix=f"Fix {i}",
            files=[f"file_{i}.py"],
            now=base_time - timedelta(minutes=i),
        )
        write_local_claim_ref(str(repo), c)

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = main(["list", "--all", "--repo", str(repo)])
    assert rc == 0
    out = buf.getvalue()
    assert "Active claims (12):" in out
    assert "Showing 10 of 12 active claims" not in out
    for i in range(12):
        assert f"feat/branch-{i}" in out


def test_list_claims_custom_limit(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    base_time = datetime.now(timezone.utc)

    for i in range(5):
        c = ClaimRecord.create(
            owner_email=f"dev{i}@example.com",
            owner_name=f"Dev{i}",
            branch=f"feat/branch-{i}",
            base_branch="main",
            symptom=f"Issue {i}",
            diagnosis_and_fix=f"Fix {i}",
            files=[f"file_{i}.py"],
            now=base_time - timedelta(minutes=i),
        )
        write_local_claim_ref(str(repo), c)

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = main(["list", "--limit", "2", "--repo", str(repo)])
    assert rc == 0
    out = buf.getvalue()
    assert "Active claims (5):" in out
    assert "Showing 2 of 5 active claims. Use --all to view all." in out


def test_list_claims_json(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    base_time = datetime.now(timezone.utc)
    c = ClaimRecord.create(
        owner_email="alice@example.com",
        owner_name="Alice",
        branch="feat/json-test",
        base_branch="main",
        symptom="Issue json",
        diagnosis_and_fix="Fix json",
        files=["json_file.py"],
        now=base_time,
    )
    write_local_claim_ref(str(repo), c)

    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rc = main(["list", "--json", "--repo", str(repo)])
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["branch"] == "feat/json-test"


def test_list_claims_invalid_target(tmp_path: Path):
    repo = _setup_git_repo(tmp_path)
    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf):
        try:
            rc = main(["list", "invalid_target", "--repo", str(repo)])
        except SystemExit as exc:
            rc = exc.code
    assert rc != 0


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
