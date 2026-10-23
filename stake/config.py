"""User-level Stake configuration and repository include/exclude filtering."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from stake.git_refs import _run_git, get_git_dirs

CONFIG_FILENAME: str = "config.json"
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_USER_PREFIX_RE = re.compile(r"^[^/@:]+@")
_PORT_PATH_RE = re.compile(r"^\d+(/|$)")


@dataclass
class StakeConfig:
    include: list[str] = field(default_factory=lambda: ["*"])
    exclude: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "include": list(self.include),
            "exclude": list(self.exclude),
        }

    @classmethod
    def from_dict(cls, data: object) -> StakeConfig:
        if not isinstance(data, dict):
            return cls()
        raw_inc = data.get("include", ["*"])
        raw_exc = data.get("exclude", [])
        inc = [str(x) for x in raw_inc] if isinstance(raw_inc, list) else ["*"]
        exc = [str(x) for x in raw_exc] if isinstance(raw_exc, list) else []
        return cls(include=inc, exclude=exc)


def get_home_dir(home_dir: Path | str | None = None) -> Path:
    if home_dir is not None:
        return Path(home_dir).expanduser().resolve()
    env_home = os.environ.get("STAKE_HOME_DIR")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path.home().resolve()


def get_config_dir(
    config_dir: Path | str | None = None,
    home_dir: Path | str | None = None,
) -> Path:
    if config_dir is not None:
        return Path(config_dir).expanduser().resolve()
    env_cfg = os.environ.get("STAKE_CONFIG_DIR")
    if env_cfg:
        return Path(env_cfg).expanduser().resolve()
    if home_dir is None and not os.environ.get("STAKE_HOME_DIR"):
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return (Path(xdg).expanduser() / "stake").resolve()
    return get_home_dir(home_dir) / ".config" / "stake"


def load_config(
    config_dir: Path | str | None = None,
    home_dir: Path | str | None = None,
) -> StakeConfig:
    cfg_file = get_config_dir(config_dir=config_dir, home_dir=home_dir) / CONFIG_FILENAME
    if not cfg_file.exists():
        return StakeConfig()
    try:
        raw = json.loads(cfg_file.read_text(encoding="utf-8"))
        return StakeConfig.from_dict(raw)
    except (ValueError, OSError):
        return StakeConfig()


def save_config(
    config: StakeConfig,
    config_dir: Path | str | None = None,
    home_dir: Path | str | None = None,
) -> Path:
    cfg_dir = get_config_dir(config_dir=config_dir, home_dir=home_dir)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / CONFIG_FILENAME
    cfg_file.write_text(
        json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cfg_file


def normalize_remote_url(raw_url: str) -> str:
    """Normalize a Git remote URL or path into a canonical lowercase identifier."""
    s = raw_url.strip()
    if not s:
        return ""
    s = _SCHEME_RE.sub("", s)
    s = _USER_PREFIX_RE.sub("", s)
    if ":" in s and not s.startswith("/"):
        host, rest = s.split(":", 1)
        if not _PORT_PATH_RE.match(rest):
            s = f"{host}/{rest.lstrip('/')}"
    s = s.rstrip("/")
    if s.endswith(".git"):
        s = s[:-4].rstrip("/")
    return s.lower()


def _normalize_pattern(pattern: str) -> str:
    p = pattern.strip()
    if not p:
        return ""
    if _SCHEME_RE.match(p) or _USER_PREFIX_RE.match(p) or p.endswith(".git") or p.endswith(".git/"):
        return normalize_remote_url(p)
    return p.lower()


def get_repo_identifiers(repo_path: str = ".") -> tuple[str, str]:
    """Return (normalized_origin_url, repo_root_posix) for repo_path."""
    repo_root, _, _ = get_git_dirs(repo_path)
    res = _run_git(repo_path, ["config", "--get", "remote.origin.url"], check=False)
    raw_origin = res.stdout.strip() if res.returncode == 0 else ""
    return normalize_remote_url(raw_origin), repo_root.as_posix()


def primary_repo_id(repo_path: str = ".") -> str:
    """Return normalized origin URL if configured, otherwise repo root POSIX path."""
    norm_origin, repo_root = get_repo_identifiers(repo_path)
    return norm_origin or repo_root


def _matches(pattern: str, candidates: list[str]) -> bool:
    norm_pat = _normalize_pattern(pattern)
    if not norm_pat:
        return False
    return any(fnmatch.fnmatchcase(c.lower(), norm_pat) for c in candidates)


def is_repo_allowed(
    repo_path: str = ".",
    config_dir: Path | str | None = None,
    home_dir: Path | str | None = None,
) -> bool:
    """Evaluate include/exclude patterns (exclude wins over include)."""
    config = load_config(config_dir=config_dir, home_dir=home_dir)
    norm_origin, repo_root = get_repo_identifiers(repo_path)
    candidates = [c for c in (norm_origin, repo_root) if c]
    if not candidates:
        return False

    for exc in config.exclude:
        if _matches(exc, candidates):
            return False

    for inc in config.include:
        if _matches(inc, candidates):
            return True

    return False
