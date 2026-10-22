import sys
from datetime import datetime, timezone
from stake.models import ClaimRecord
from stake.matcher import (
    find_overlaps,
    format_active_claims_for_agent,
    format_collision_brief,
    has_module_drift,
)
from tests._runner import make_suite


def _claim(owner: str, branch: str, base: str, symptom: str, fix: str, files: list[str]) -> ClaimRecord:
    now = datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc)
    return ClaimRecord.create(owner, owner.split("@")[0], branch, base, symptom, fix, files, "committed", now=now)


def test_find_overlaps_catches_adjacent_files_and_flags_cross_branch():
    mine = _claim(
        "alice@example.com", "fix/dev-timeout", "development",
        "Admin dashboard 504 timeout",
        "Batch and cache org permission lookups",
        ["src/permissions/resolver.ts"],
    )
    bobs = _claim(
        "bob@example.com", "hotfix/stg-csv", "release/stg",
        "CSV export hangs on large orgs",
        "Memoize org permission query N+1 in loader",
        ["src/permissions/org_loader.ts"],
    )
    matches = find_overlaps(mine, [mine, bobs])
    assert len(matches) == 1
    assert matches[0].claim.claim_id == bobs.claim_id
    assert matches[0].shared_modules == ["src/permissions"]
    assert matches[0].cross_branch is True

    brief = format_collision_brief(mine, matches)
    assert "CROSS-BRANCH" in brief
    assert "release/stg" in brief
    assert "development" in brief


def test_self_match_and_seen_claims_are_filtered_out():
    bob_stg = _claim("bob@example.com", "hotfix/stg", "release/stg", "bug", "fix perm", ["src/permissions/a.ts"])
    bob_backfill = _claim("bob@example.com", "backfill/dev", "development", "bug", "fix perm", ["src/permissions/a.ts"])
    carol = _claim("carol@example.com", "fix/other", "development", "bug", "fix perm", ["src/permissions/b.ts"])

    # Bob's backfill never triggers against Bob's own hotfix
    assert find_overlaps(bob_backfill, [bob_stg]) == []
    # Carol seen once is suppressed on subsequent checks
    assert find_overlaps(bob_backfill, [carol], seen_claims=[carol.claim_id]) == []


def test_has_module_drift_detects_undeclared_directory():
    assert not has_module_drift(["src/permissions/b.ts"], ["src/permissions"], ["src/permissions/a.ts"])
    assert has_module_drift(["src/billing/invoice.ts"], ["src/permissions"], ["src/permissions/a.ts"])


def test_format_active_claims_orders_overlapping_first():
    mine = _claim("me@example.com", "fix/mine", "development", "s", "f", ["src/permissions/resolver.ts"])
    unrelated_aaa = _claim("aaa@example.com", "fix/unrel", "development", "s", "f", ["src/billing/inv.ts"])
    overlapping_zzz = _claim("zzz@example.com", "fix/perm", "development", "s", "f", ["src/permissions/org_loader.ts"])

    out = format_active_claims_for_agent(mine, [unrelated_aaa, overlapping_zzz])
    assert out.index(overlapping_zzz.claim_id) < out.index(unrelated_aaa.claim_id)


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
