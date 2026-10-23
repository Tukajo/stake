import sys
from datetime import datetime, timezone
from stake.models import ClaimRecord
from stake.matcher import (
    _claim_keywords,
    find_overlaps,
    format_active_claims_for_agent,
    format_collision_brief,
    has_module_drift,
    modules_overlap,
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


def test_same_email_different_branch_surfaces_while_same_claim_and_seen_receipts_filter():
    bob_wt1 = _claim("bob@example.com", "fix/PROJ-412", "development", "bug", "fix perm", ["src/permissions/a.ts"])
    bob_wt2 = _claim("bob@example.com", "hotfix/OPS-88", "release/stg", "bug", "fix perm", ["src/permissions/a.ts"])

    # Exact same branch/claim_id never matches itself
    assert find_overlaps(bob_wt1, [bob_wt1]) == []
    # Same developer email on a parallel branch/worktree DOES surface
    matches = find_overlaps(bob_wt1, [bob_wt2])
    assert len(matches) == 1
    assert matches[0].claim.claim_id == bob_wt2.claim_id

    # Suppressed by either bare claim_id (backward-compat) or receipt_key()
    assert find_overlaps(bob_wt1, [bob_wt2], seen_claims=[bob_wt2.claim_id]) == []
    assert find_overlaps(bob_wt1, [bob_wt2], seen_claims=[bob_wt2.receipt_key()]) == []

    # If bob_wt2 mutates files, the old receipt_key no longer suppresses it
    bob_wt2_mutated = _claim("bob@example.com", "hotfix/OPS-88", "release/stg", "bug", "fix perm", ["src/permissions/a.ts", "src/permissions/b.ts"])
    assert len(find_overlaps(bob_wt1, [bob_wt2_mutated], seen_claims=[bob_wt2.receipt_key()])) == 1


def test_compound_identifiers_and_synthetic_boilerplate_filtering():
    c1 = _claim(
        "alice@example.com", "fix/a", "development",
        "Slow PermissionResolver lookup",
        "Refactor org_permission_loader query",
        ["src/auth/handler.ts"],
    )
    c2 = _claim(
        "bob@example.com", "fix/b", "development",
        "Admin timeout",
        "Cache permission resolver in loader",
        ["src/billing/invoice.ts"],
    )
    matches = find_overlaps(c1, [c2])
    assert len(matches) == 1
    assert {"loader", "permission", "resolver"}.issubset(set(matches[0].shared_keywords))

    # Two unplanned auto-commits sharing synthetic boilerplate and branch tokens must NOT collide
    auto1 = _claim(
        "alice@example.com", "feat/billing-export", "development",
        "Changes on branch feat/billing-export",
        "Modifying src/billing/index.ts, src/billing/types.ts",
        ["src/billing/index.ts", "src/billing/types.ts"],
    )
    auto2 = _claim(
        "bob@example.com", "feat/email-export", "development",
        "Changes on branch feat/email-export",
        "Modifying src/email/index.ts, src/email/types.ts",
        ["src/email/index.ts", "src/email/types.ts"],
    )
    assert find_overlaps(auto1, [auto2]) == []

    # Legitimate manual claim starting with 'Modifying ' still extracts keywords
    manual = _claim(
        "alice@example.com", "fix/perm", "development",
        "",
        "Modifying permission resolver query in loader",
        ["src/permissions/resolver.ts"],
    )
    assert _claim_keywords(manual) == {"permission", "resolver", "query", "loader"}


def test_nested_submodule_overlap_and_shallow_container_isolation():
    parent_claim = _claim(
        "alice@example.com", "fix/parent", "development",
        "Update auth", "Fix check", ["src/permissions/resolver.ts"],
    )
    child_claim = _claim(
        "bob@example.com", "fix/child", "development",
        "Tweak role", "Adjust rule", ["src/permissions/rbac/policy.ts"],
    )
    matches = find_overlaps(parent_claim, [child_claim])
    assert len(matches) == 1
    assert matches[0].shared_modules == ["src/permissions"]

    shallow_a = _claim("alice@example.com", "fix/s1", "development", "A", "B", ["src/index.ts"])
    shallow_b = _claim("bob@example.com", "fix/s2", "development", "C", "D", ["src/config.ts"])
    assert find_overlaps(shallow_a, [shallow_b]) == []


def test_format_active_claims_sorts_by_keyword_overlap_and_includes_same_email():
    mine = _claim(
        "me@example.com", "fix/mine", "development",
        "PermissionResolver timeout", "Batch permission loader queries", ["src/a/one.ts"],
    )
    unrel = _claim("aaa@example.com", "fix/unrel", "development", "Invoice pdf", "Fix margin", ["src/b/two.ts"])
    kw_match = _claim(
        "me@example.com", "fix/other-wt", "development",
        "Slow export", "Optimize permission resolver loader", ["src/c/three.ts"],
    )
    out = format_active_claims_for_agent(mine, [unrel, kw_match])
    assert kw_match.claim_id in out
    assert out.index(kw_match.claim_id) < out.index(unrel.claim_id)


def test_modules_overlap_direct():
    assert modules_overlap(["src/permissions"], ["src/permissions/rbac"]) == ["src/permissions"]
    assert modules_overlap(["src/permissions/rbac"], ["src/permissions"]) == ["src/permissions"]
    assert modules_overlap({"src/permissions"}, {"src/permissions"}) == ["src/permissions"]
    assert modules_overlap(["src", "lib"], ["src", "app"]) == []
    assert modules_overlap(["src/permissions/a"], ["src/permissions/b"]) == []
    assert modules_overlap([], ["src/permissions"]) == []


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
