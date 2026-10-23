import subprocess
import sys
from pathlib import Path
from stake.config import (
    StakeConfig,
    get_config_dir,
    get_home_dir,
    get_repo_identifiers,
    is_repo_allowed,
    load_config,
    normalize_remote_url,
    primary_repo_id,
    save_config,
)
from tests._runner import make_suite


def test_normalize_remote_url_variants():
    assert normalize_remote_url("git@github.com:Tukajo/stake.git") == "github.com/tukajo/stake"
    assert normalize_remote_url("https://github.com/Tukajo/stake.git/") == "github.com/tukajo/stake"
    assert normalize_remote_url("https://oauth2:ghp_secret123@github.com/Tukajo/stake.git") == "github.com/tukajo/stake"
    assert normalize_remote_url("http://192.168.1.220:3000/Tukajo/stake.git") == "192.168.1.220:3000/tukajo/stake"
    assert normalize_remote_url("ssh://git@192.168.1.220:2222/Tukajo/stake.git") == "192.168.1.220:2222/tukajo/stake"
    assert normalize_remote_url("/tmp/SomeRepo/origin.git") == "/tmp/somerepo/origin"
    assert normalize_remote_url("   ") == ""


def test_load_and_save_config_with_corrupt_fallback(tmp_path: Path):
    cfg_dir = tmp_path / "stake_cfg"
    # Missing file returns defaults
    default_cfg = load_config(config_dir=cfg_dir)
    assert default_cfg.include == ["*"]
    assert default_cfg.exclude == []

    # Corrupt file returns defaults without raising
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
    assert load_config(config_dir=cfg_dir) == StakeConfig(include=["*"], exclude=[])

    # Valid save & reload
    custom = StakeConfig(include=["github.com/myorg/*"], exclude=["github.com/myorg/secret"])
    saved_path = save_config(custom, config_dir=cfg_dir)
    assert saved_path == cfg_dir / "config.json"
    assert load_config(config_dir=cfg_dir) == custom


def test_is_repo_allowed_matching_and_precedence(tmp_path: Path):
    cfg_dir = tmp_path / "cfg"
    repo = tmp_path / "work_repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:Tukajo/stake.git"],
        check=True,
        capture_output=True,
    )

    # Default allows all
    assert is_repo_allowed(str(repo), config_dir=cfg_dir) is True
    assert primary_repo_id(str(repo)) == "github.com/tukajo/stake"

    # Exclude overrides wildcard include (even when user provides raw URL in exclude)
    save_config(
        StakeConfig(include=["*"], exclude=["https://github.com/Tukajo/stake.git"]),
        config_dir=cfg_dir,
    )
    assert is_repo_allowed(str(repo), config_dir=cfg_dir) is False

    # Org wildcard include
    save_config(
        StakeConfig(include=["github.com/tukajo/*"], exclude=[]),
        config_dir=cfg_dir,
    )
    assert is_repo_allowed(str(repo), config_dir=cfg_dir) is True

    # Non-matching include disallows
    save_config(
        StakeConfig(include=["192.168.1.220:3000/*"], exclude=[]),
        config_dir=cfg_dir,
    )
    assert is_repo_allowed(str(repo), config_dir=cfg_dir) is False


def test_repo_without_origin_falls_back_to_local_path(tmp_path: Path):
    cfg_dir = tmp_path / "cfg"
    local_only = tmp_path / "local_only"
    subprocess.run(["git", "init", str(local_only)], check=True, capture_output=True)

    norm_origin, repo_root = get_repo_identifiers(str(local_only))
    assert norm_origin == ""
    assert primary_repo_id(str(local_only)) == repo_root

    save_config(StakeConfig(include=["*"], exclude=[repo_root]), config_dir=cfg_dir)
    assert is_repo_allowed(str(local_only), config_dir=cfg_dir) is False


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
