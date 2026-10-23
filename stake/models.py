"""Data models and pure helpers for Stake claims and local receipt state."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

PLAN_TTL_SECONDS: int = 14400      # 4 hours for uncommitted planned claims
COMMIT_TTL_SECONDS: int = 259200   # 72 hours for committed / landed claims

_TOP_LEVEL_CONTAINERS: frozenset[str] = frozenset(
    {"src", "lib", "app", "pkg", "packages", "internal", "cmd", "test", "tests", "docs"}
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")


def slugify(value: str) -> str:
    """Convert an arbitrary identifier into a lowercase alphanumeric hyphen slug."""
    cleaned = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return cleaned or "unknown"


def make_claim_id(owner_email: str, branch: str) -> str:
    """Deterministic per-(owner, branch) claim identifier."""
    return f"{slugify(owner_email)}--{slugify(branch)}"


def _normalize_repo_path(path: str) -> str:
    norm = posixpath.normpath(path.strip().replace("\\", "/"))
    while norm.startswith("./"):
        norm = norm[2:]
    return "" if norm in ("", ".") else norm


def derive_modules(files: list[str]) -> list[str]:
    """Derive sorted unique parent directory paths from repo-relative file paths.

    Root-level files (e.g. 'README.md') have no parent module directory and are
    excluded so root file edits do not collide on a synthetic root module.
    Single-segment generic container directories (e.g. 'src', 'lib') are also
    excluded.
    """
    modules: set[str] = set()
    for raw in files:
        norm = _normalize_repo_path(raw)
        if not norm:
            continue
        parent = posixpath.dirname(norm)
        if parent and parent != "." and parent not in _TOP_LEVEL_CONTAINERS:
            modules.add(parent)
    return sorted(modules)


def extract_ticket(*texts: str) -> str | None:
    """Extract the first Jira-style ticket key (e.g. PROJ-412) from any input text."""
    for text in texts:
        if not text:
            continue
        match = _TICKET_RE.search(text)
        if match:
            return match.group(1)
    return None


def format_iso_utc(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with trailing 'Z'."""
    utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z")


def parse_iso_utc(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime."""
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class ClaimRecord:
    claim_id: str
    owner_email: str
    owner_name: str
    branch: str
    base_branch: str
    ticket: str | None
    stage: str
    created_at: str
    updated_at: str
    expires_at: str
    symptom: str
    diagnosis_and_fix: str
    modules: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    last_commit_sha: str | None = None

    @classmethod
    def create(
        cls,
        owner_email: str,
        owner_name: str,
        branch: str,
        base_branch: str,
        symptom: str,
        diagnosis_and_fix: str,
        files: list[str],
        stage: str = "planned",
        ticket: str | None = None,
        last_commit_sha: str | None = None,
        created_at: str | None = None,
        now: datetime | None = None,
    ) -> ClaimRecord:
        current = now or datetime.now(timezone.utc)
        ttl_sec = PLAN_TTL_SECONDS if stage == "planned" else COMMIT_TTL_SECONDS
        norm_files = sorted({p for p in (_normalize_repo_path(f) for f in files) if p})
        resolved_ticket = ticket or extract_ticket(branch, symptom, diagnosis_and_fix)
        now_iso = format_iso_utc(current)
        exp_iso = format_iso_utc(current + timedelta(seconds=ttl_sec))
        return cls(
            claim_id=make_claim_id(owner_email, branch),
            owner_email=owner_email.strip(),
            owner_name=owner_name.strip(),
            branch=branch.strip(),
            base_branch=base_branch.strip() or "main",
            ticket=resolved_ticket,
            stage=stage,
            created_at=created_at or now_iso,
            updated_at=now_iso,
            expires_at=exp_iso,
            symptom=symptom.strip(),
            diagnosis_and_fix=diagnosis_and_fix.strip(),
            modules=derive_modules(norm_files),
            files=norm_files,
            last_commit_sha=last_commit_sha,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        try:
            return current >= parse_iso_utc(self.expires_at)
        except ValueError:
            return True

    def receipt_key(self) -> str:
        """Deterministic content fingerprint receipt key over collision-relevant fields."""
        payload = json.dumps(
            {
                "claim_id": self.claim_id,
                "diagnosis_and_fix": self.diagnosis_and_fix.strip(),
                "files": sorted(self.files),
                "modules": sorted(self.modules),
                "symptom": self.symptom.strip(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{self.claim_id}@{digest}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimRecord:
        return cls(
            claim_id=str(data["claim_id"]),
            owner_email=str(data["owner_email"]),
            owner_name=str(data.get("owner_name", "")),
            branch=str(data["branch"]),
            base_branch=str(data.get("base_branch", "main")),
            ticket=data.get("ticket"),
            stage=str(data.get("stage", "planned")),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            expires_at=str(data["expires_at"]),
            symptom=str(data.get("symptom", "")),
            diagnosis_and_fix=str(data.get("diagnosis_and_fix", "")),
            modules=list(data.get("modules", [])),
            files=list(data.get("files", [])),
            last_commit_sha=data.get("last_commit_sha"),
        )

    @classmethod
    def from_json(cls, raw: str) -> ClaimRecord:
        return cls.from_dict(json.loads(raw))


@dataclass
class LocalState:
    claim_id: str | None = None
    branch: str | None = None
    declared_modules: list[str] = field(default_factory=list)
    declared_files: list[str] = field(default_factory=list)
    symptom: str = ""
    diagnosis_and_fix: str = ""
    seen_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalState:
        return cls(
            claim_id=data.get("claim_id"),
            branch=data.get("branch"),
            declared_modules=list(data.get("declared_modules", [])),
            declared_files=list(data.get("declared_files", [])),
            symptom=str(data.get("symptom", "")),
            diagnosis_and_fix=str(data.get("diagnosis_and_fix", "")),
            seen_claims=list(data.get("seen_claims", [])),
        )
