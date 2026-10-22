from datetime import datetime, timezone, timedelta
from stake.models import (
    PLAN_TTL_SECONDS,
    COMMIT_TTL_SECONDS,
    ClaimRecord,
    LocalState,
    derive_modules,
    extract_ticket,
    make_claim_id,
    slugify,
)


def test_slugify_and_make_claim_id():
    assert slugify("Alice.Smith@Example.com") == "alice-smith-example-com"
    assert make_claim_id("Alice@Example.com", "fix/csv_export#12") == "alice-example-com--fix-csv-export-12"


def test_derive_modules_ignores_repo_root_files():
    files = ["README.md", "./Makefile", "src/permissions/org_loader.ts", "src/permissions/resolver.ts", "pkg/api/v1/handler.go"]
    assert derive_modules(files) == ["pkg/api/v1", "src/permissions"]


def test_extract_ticket_finds_jira_style_key():
    assert extract_ticket("fix/PROJ-412-csv-hang", "fixing export") == "PROJ-412"
    assert extract_ticket("hotfix/stg-timeout", "Addresses OPS-99 in loader") == "OPS-99"
    assert extract_ticket("chore/cleanup", "no ticket here") is None


def test_claim_record_roundtrip_and_expiry():
    now = datetime(2026, 10, 22, 16, 0, 0, tzinfo=timezone.utc)
    claim = ClaimRecord.create(
        owner_email="alice@example.com",
        owner_name="Alice",
        branch="fix/csv-hang",
        base_branch="development",
        symptom="CSV export hangs",
        diagnosis_and_fix="Batch org permission queries",
        files=["src/permissions/org_loader.ts"],
        stage="planned",
        now=now,
    )
    assert claim.expires_at == "2026-10-22T20:00:00Z"
    assert not claim.is_expired(now + timedelta(seconds=PLAN_TTL_SECONDS - 1))
    assert claim.is_expired(now + timedelta(seconds=PLAN_TTL_SECONDS + 1))

    restored = ClaimRecord.from_json(claim.to_json())
    assert restored == claim


import sys
from tests._runner import make_suite


def load_tests(loader, tests, pattern):
    return make_suite(sys.modules[__name__])
