"""Overlap detection, cross-branch comparison, and terminal brief formatting."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from stake.models import ClaimRecord, _TOP_LEVEL_CONTAINERS, _normalize_repo_path, derive_modules

_CAMEL_RE_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_WORD_RE = re.compile(r"[a-z0-9_]{4,}")
_SUB_WORD_RE = re.compile(r"[a-z0-9]{4,}")

_STOPWORDS: frozenset[str] = frozenset({
    "this", "that", "with", "from", "into", "when", "where", "which", "while",
    "have", "will", "should", "could", "would", "make", "made", "only", "also",
    "code", "file", "files", "change", "changes", "update", "updated", "fix",
    "fixed", "fixing", "issue", "issues", "bug", "bugs", "task", "work",
    "branch", "commit", "some", "more", "over", "under", "after", "before",
    "modifying", "modified", "modify", "pushed", "feat", "feature",
    "hotfix", "bugfix", "chore", "refactor", "release", "main", "master",
    "development", "staging", "index", "types", "utils", "common", "helper",
    "helpers", "test", "tests", "spec",
})

_SYNTHETIC_PATTERNS = (
    re.compile(r"^Changes on branch \S+$"),
    re.compile(r"^Branch \S+$"),
    re.compile(r"^Modifying [^\s,]+(?:, [^\s,]+)*$"),
    re.compile(r"^Pushed branch \S+$"),
)


def _extract_keywords(text: str) -> set[str]:
    if not text:
        return set()
    s = _CAMEL_RE_1.sub(r"\1 \2", text)
    s = _CAMEL_RE_2.sub(r"\1 \2", s).lower()
    keywords: set[str] = set()
    for tok in _WORD_RE.findall(s):
        if tok not in _STOPWORDS:
            keywords.add(tok)
        if "_" in tok:
            for sub in _SUB_WORD_RE.findall(tok):
                if sub not in _STOPWORDS:
                    keywords.add(sub)
    return keywords


def _is_synthetic(text: str) -> bool:
    stripped = text.strip()
    return any(p.match(stripped) for p in _SYNTHETIC_PATTERNS)


def _claim_keywords(claim: ClaimRecord) -> set[str]:
    parts: list[str] = []
    if claim.symptom and not _is_synthetic(claim.symptom):
        parts.append(claim.symptom)
    if claim.diagnosis_and_fix and not _is_synthetic(claim.diagnosis_and_fix):
        parts.append(claim.diagnosis_and_fix)
    if not parts:
        return set()
    return _extract_keywords(" ".join(parts))


def modules_overlap(
    mods_a: Iterable[str],
    mods_b: Iterable[str],
) -> list[str]:
    """Return sorted overlapping module paths excluding top-level containers.

    Matches identical or parent/child module paths (m1 == m2 or m1/m2 is a nested
    child of the other), returning the shared parent module path.
    """
    valid_a = {m for m in mods_a if m and m not in _TOP_LEVEL_CONTAINERS}
    valid_b = {m for m in mods_b if m and m not in _TOP_LEVEL_CONTAINERS}
    shared: set[str] = set()
    for m1 in valid_a:
        for m2 in valid_b:
            if m1 == m2:
                shared.add(m1)
            elif m1.startswith(m2 + "/"):
                shared.add(m2)
            elif m2.startswith(m1 + "/"):
                shared.add(m1)
    return sorted(shared)


@dataclass
class OverlapMatch:
    claim: ClaimRecord
    shared_files: list[str]
    shared_modules: list[str]
    shared_keywords: list[str]
    cross_branch: bool


def find_overlaps(
    my_claim: ClaimRecord,
    all_claims: list[ClaimRecord],
    seen_claims: list[str] | None = None,
) -> list[OverlapMatch]:
    """Return active foreign claims that overlap in files, modules, or fix keywords."""
    seen = set(seen_claims or [])
    my_files = set(my_claim.files)
    my_keywords = _claim_keywords(my_claim)

    matches: list[OverlapMatch] = []
    for other in all_claims:
        if other.claim_id == my_claim.claim_id or other.branch == my_claim.branch:
            continue
        if other.claim_id in seen or other.receipt_key() in seen:
            continue

        shared_files = sorted(my_files.intersection(other.files))
        shared_modules = modules_overlap(my_claim.modules, other.modules)
        other_keywords = _claim_keywords(other)
        shared_keywords = sorted(my_keywords.intersection(other_keywords))

        if shared_files or shared_modules or len(shared_keywords) >= 2:
            matches.append(
                OverlapMatch(
                    claim=other,
                    shared_files=shared_files,
                    shared_modules=shared_modules,
                    shared_keywords=shared_keywords,
                    cross_branch=(my_claim.base_branch != other.base_branch),
                )
            )
    return matches


def has_module_drift(
    staged_files: list[str],
    declared_modules: list[str],
    declared_files: list[str],
) -> bool:
    """Return True if staged_files touch a module or root file not declared at plan time."""
    norm_files = [p for p in (_normalize_repo_path(f) for f in staged_files) if p]
    decl_mods = set(declared_modules)
    decl_files = set(declared_files)

    for f in norm_files:
        if f in decl_files:
            continue
        mods = derive_modules([f])
        if not mods:
            # Root-level file that was not explicitly declared
            return True
        if not set(mods).issubset(decl_mods):
            return True
    return False


def format_collision_brief(my_claim: ClaimRecord, matches: list[OverlapMatch]) -> str:
    """Render a concise side-by-side collision radar brief."""
    lines: list[str] = [
        "========================================================================",
        f"STAKE RADAR: {len(matches)} overlapping claim(s) detected (show-once notice)",
        "========================================================================",
        f"Your work ({my_claim.branch}, base: {my_claim.base_branch}"
        + (f", ticket: {my_claim.ticket}" if my_claim.ticket else "")
        + "):",
        f"  Symptom : {my_claim.symptom or '(unspecified)'}",
        f"  Fix     : {my_claim.diagnosis_and_fix or '(unspecified)'}",
        f"  Files   : {', '.join(my_claim.files) if my_claim.files else '(none)'}",
        "------------------------------------------------------------------------",
    ]
    for m in matches:
        c = m.claim
        cross = (
            f" [CROSS-BRANCH: theirs targets {c.base_branch}, yours targets {my_claim.base_branch}]"
            if m.cross_branch
            else ""
        )
        lines.append(
            f"* {c.owner_name} <{c.owner_email}> on branch '{c.branch}' "
            f"(base: {c.base_branch}, stage: {c.stage}"
            + (f", ticket: {c.ticket}" if c.ticket else "")
            + f"){cross}"
        )
        lines.append(f"  Symptom : {c.symptom or '(unspecified)'}")
        lines.append(f"  Fix     : {c.diagnosis_and_fix or '(unspecified)'}")
        lines.append(f"  Files   : {', '.join(c.files) if c.files else '(none)'}")
        reasons: list[str] = []
        if m.shared_files:
            reasons.append(f"files={', '.join(m.shared_files)}")
        if m.shared_modules:
            reasons.append(f"modules={', '.join(m.shared_modules)}")
        if m.shared_keywords:
            reasons.append(f"keywords={', '.join(m.shared_keywords)}")
        lines.append(f"  Overlap : {'; '.join(reasons)}")
        lines.append("------------------------------------------------------------------------")

    lines.append(
        "Bypass: This claim pair is now marked seen. Re-run `git commit` (or set STAKE_SKIP=1) to proceed."
    )
    return "\n".join(lines) + "\n"


def format_active_claims_for_agent(my_claim: ClaimRecord, all_claims: list[ClaimRecord]) -> str:
    """Format active foreign claims for an agent to evaluate during planning."""
    my_files = set(my_claim.files)
    my_keywords = _claim_keywords(my_claim)
    foreign = [
        c for c in all_claims
        if c.claim_id != my_claim.claim_id and c.branch != my_claim.branch
    ]
    foreign.sort(
        key=lambda c: (
            -len(my_files.intersection(c.files)),
            -len(modules_overlap(my_claim.modules, c.modules)),
            -len(my_keywords.intersection(_claim_keywords(c))),
            c.claim_id,
        )
    )
    if not foreign:
        return f"Stake registered claim '{my_claim.claim_id}'. No active teammate claims in the 72h window.\n"

    lines = [
        f"Stake registered claim '{my_claim.claim_id}'. Active teammate claims ({len(foreign)}):",
    ]
    for c in foreign:
        cross = (
            f" [CROSS-BRANCH: targets {c.base_branch} vs your {my_claim.base_branch}]"
            if c.base_branch != my_claim.base_branch
            else ""
        )
        lines.append(
            f"- [{c.claim_id}] {c.owner_name} <{c.owner_email}> | branch={c.branch} "
            f"| base={c.base_branch} | stage={c.stage}"
            + (f" | ticket={c.ticket}" if c.ticket else "")
            + cross
        )
        lines.append(f"    symptom: {c.symptom}")
        lines.append(f"    fix:     {c.diagnosis_and_fix}")
        lines.append(f"    modules: {', '.join(c.modules) or '(root)'} | files: {', '.join(c.files)}")
    return "\n".join(lines) + "\n"
