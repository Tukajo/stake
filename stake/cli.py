"""Command-line interface for Stake."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from stake import __version__
from stake.config import (
    get_repo_identifiers,
    is_repo_allowed,
    load_config,
    normalize_pattern,
    primary_repo_id,
    save_config,
)
from stake.git_refs import (
    REF_PREFIX,
    _run_git,
    delete_local_claim_ref,
    get_repo_identity,
    load_local_state,
    read_local_claim_refs,
    save_local_state,
    sync_claims_with_remote,
)
from stake.installer import setup_user
from stake.matcher import (
    find_overlaps,
    format_active_claims_for_agent,
    format_collision_brief,
    has_module_drift,
    modules_overlap,
)
from stake.models import ClaimRecord, LocalState, derive_modules, make_claim_id


def _parse_files_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _staged_files(repo_path: str) -> list[str]:
    res = _run_git(repo_path, ["diff", "--cached", "--name-only"], check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _short_head(repo_path: str) -> str | None:
    res = _run_git(repo_path, ["rev-parse", "--short", "HEAD"], check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return None
    return res.stdout.strip()


def cmd_setup(args: argparse.Namespace) -> int:
    info = setup_user(stake_bin=os.environ.get("STAKE_BIN"))
    print("Stake configured globally for current user:")
    print(f"  config.json : {info['config_file']}")
    print(f"  pre-commit  : {info['pre_commit']}")
    print(f"  pre-push    : {info['pre_push']}")
    print(f"  husky init  : {info['husky_init']}")
    print(f"  CLAUDE.md   : {info['claude_md']}")
    print(f"  GEMINI.md   : {info['gemini_md']}")
    print(f"  SKILL.md    : {info['skill_md']}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    repo_id = primary_repo_id(args.repo)
    cfg = load_config()
    if repo_id not in cfg.exclude:
        cfg.exclude.append(repo_id)
    if repo_id in cfg.include and repo_id != "*":
        cfg.include = [item for item in cfg.include if item != repo_id]
    save_config(cfg)
    print(f"Stake disabled for '{repo_id}'.")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    norm_origin, repo_root = get_repo_identifiers(args.repo)
    repo_id = norm_origin or repo_root
    remove_set = {x.lower() for x in (repo_id, norm_origin, repo_root) if x}
    cfg = load_config()
    cfg.exclude = [
        item
        for item in cfg.exclude
        if item.strip().lower() not in remove_set and normalize_pattern(item) not in remove_set
    ]
    save_config(cfg)
    if not is_repo_allowed(args.repo):
        cfg.include.append(repo_id)
        save_config(cfg)
    print(f"Stake enabled for '{repo_id}'.")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    repo_path = args.repo
    if not is_repo_allowed(repo_path):
        sys.stdout.write(
            f"Stake: repository '{primary_repo_id(repo_path)}' is disabled in config; skipping claim.\n"
        )
        return 0

    owner_email, owner_name, branch, detected_base = get_repo_identity(repo_path)
    base_branch = args.base or detected_base
    files = _parse_files_csv(args.files)

    state = load_local_state(repo_path)
    if state.branch != branch:
        state = LocalState(branch=branch)

    claim_id = make_claim_id(owner_email, branch)
    existing = {c.claim_id: c for c in read_local_claim_refs(repo_path)}.get(claim_id)

    my_claim = ClaimRecord.create(
        owner_email=owner_email,
        owner_name=owner_name,
        branch=branch,
        base_branch=base_branch,
        symptom=args.symptom,
        diagnosis_and_fix=args.fix,
        files=files,
        stage="planned",
        ticket=args.ticket or (existing.ticket if existing else None),
        last_commit_sha=_short_head(repo_path),
        created_at=existing.created_at if existing else None,
    )

    active_claims, remote_ok = sync_claims_with_remote(repo_path, push_claim=my_claim)
    if not remote_ok:
        sys.stderr.write("stake: remote unreachable, continuing offline\n")

    drifted_files = set(my_claim.files) - set(state.declared_files)
    drifted_modules = set(my_claim.modules) - set(state.declared_modules)
    effective_seen = set(state.seen_claims)
    if drifted_files or drifted_modules:
        for c in active_claims:
            if drifted_files.intersection(c.files) or modules_overlap(drifted_modules, c.modules):
                effective_seen.discard(c.claim_id)
                effective_seen.discard(c.receipt_key())

    matches = find_overlaps(my_claim, active_claims, seen_claims=sorted(effective_seen))
    sys.stdout.write(format_active_claims_for_agent(my_claim, active_claims))
    if matches:
        sys.stdout.write("\n" + format_collision_brief(my_claim, matches))

    seen_set = {k for k in state.seen_claims if "@" in k}
    for c in active_claims:
        if c.claim_id != my_claim.claim_id:
            seen_set.add(c.receipt_key())

    new_state = LocalState(
        claim_id=my_claim.claim_id,
        branch=branch,
        declared_modules=my_claim.modules,
        declared_files=my_claim.files,
        symptom=my_claim.symptom,
        diagnosis_and_fix=my_claim.diagnosis_and_fix,
        seen_claims=sorted(seen_set),
    )
    save_local_state(repo_path, new_state)
    return 0


def cmd_hook_pre_commit(args: argparse.Namespace) -> int:
    if os.environ.get("STAKE_SKIP") == "1":
        return 0

    repo_path = args.repo
    if not is_repo_allowed(repo_path):
        return 0

    staged = _staged_files(repo_path)
    if not staged:
        return 0

    owner_email, owner_name, branch, base_branch = get_repo_identity(repo_path)
    state = load_local_state(repo_path)
    if state.branch != branch:
        state = LocalState(branch=branch)

    claim_id = make_claim_id(owner_email, branch)
    existing = {c.claim_id: c for c in read_local_claim_refs(repo_path)}.get(claim_id)

    drifted = bool(
        state.claim_id
        and has_module_drift(staged, state.declared_modules, state.declared_files)
    )
    drifted_modules = set(derive_modules(staged)) - set(state.declared_modules) if drifted else set()

    combined_files = sorted(set(state.declared_files) | set(staged))
    drifted_files = set(combined_files) - set(state.declared_files) if drifted else set()
    symptom = (existing.symptom if existing else state.symptom) or f"Changes on branch {branch}"
    fix = (existing.diagnosis_and_fix if existing else state.diagnosis_and_fix) or f"Modifying {', '.join(staged[:5])}"

    my_claim = ClaimRecord.create(
        owner_email=owner_email,
        owner_name=owner_name,
        branch=branch,
        base_branch=existing.base_branch if existing else base_branch,
        symptom=symptom,
        diagnosis_and_fix=fix,
        files=combined_files,
        stage="committed",
        ticket=existing.ticket if existing else None,
        last_commit_sha=_short_head(repo_path),
        created_at=existing.created_at if existing else None,
    )

    active_claims, remote_ok = sync_claims_with_remote(repo_path, push_claim=my_claim)
    if not remote_ok:
        sys.stderr.write("stake: remote unreachable, continuing offline\n")
        state.claim_id = my_claim.claim_id
        state.branch = branch
        state.declared_modules = my_claim.modules
        state.declared_files = my_claim.files
        state.symptom = symptom
        state.diagnosis_and_fix = fix
        save_local_state(repo_path, state)
        return 0

    effective_seen = set(state.seen_claims)
    drifted_ids: set[str] = set()
    if drifted_modules or drifted_files:
        for c in active_claims:
            if modules_overlap(drifted_modules, c.modules) or drifted_files.intersection(c.files):
                drifted_ids.add(c.claim_id)
                effective_seen.discard(c.claim_id)
                effective_seen.discard(c.receipt_key())

    matches = find_overlaps(my_claim, active_claims, seen_claims=sorted(effective_seen))
    matched_ids = {m.claim.claim_id for m in matches}
    seen_set = {k for k in state.seen_claims if "@" in k} | {m.claim.receipt_key() for m in matches}
    for c in active_claims:
        if c.claim_id in state.seen_claims and c.claim_id not in matched_ids and c.claim_id not in drifted_ids:
            seen_set.add(c.receipt_key())

    new_state = LocalState(
        claim_id=my_claim.claim_id,
        branch=branch,
        declared_modules=my_claim.modules,
        declared_files=my_claim.files,
        symptom=symptom,
        diagnosis_and_fix=fix,
        seen_claims=sorted(seen_set),
    )
    save_local_state(repo_path, new_state)

    if matches:
        sys.stderr.write(format_collision_brief(my_claim, matches))
        return 1
    return 0


def cmd_hook_pre_push(args: argparse.Namespace) -> int:
    if os.environ.get("STAKE_SKIP") == "1":
        return 0

    repo_path = args.repo
    if not is_repo_allowed(repo_path):
        return 0

    owner_email, owner_name, branch, base_branch = get_repo_identity(repo_path)
    state = load_local_state(repo_path)
    if state.branch != branch:
        state = LocalState(branch=branch)
    claim_id = make_claim_id(owner_email, branch)
    existing = {c.claim_id: c for c in read_local_claim_refs(repo_path)}.get(claim_id)

    files = existing.files if existing else state.declared_files
    symptom = (existing.symptom if existing else state.symptom) or f"Branch {branch}"
    fix = (existing.diagnosis_and_fix if existing else state.diagnosis_and_fix) or f"Pushed branch {branch}"

    my_claim = ClaimRecord.create(
        owner_email=owner_email,
        owner_name=owner_name,
        branch=branch,
        base_branch=existing.base_branch if existing else base_branch,
        symptom=symptom,
        diagnosis_and_fix=fix,
        files=files,
        stage="landed",
        ticket=existing.ticket if existing else None,
        last_commit_sha=_short_head(repo_path),
        created_at=existing.created_at if existing else None,
    )
    _, remote_ok = sync_claims_with_remote(repo_path, push_claim=my_claim)
    if not remote_ok:
        sys.stderr.write("stake: remote unreachable, continuing offline\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo_path = args.repo
    active_claims, remote_ok = sync_claims_with_remote(repo_path, push_claim=None)
    if not remote_ok:
        sys.stderr.write("stake: remote unreachable, continuing offline\n")

    if args.json:
        print(json.dumps([c.to_dict() for c in active_claims], indent=2, sort_keys=True))
        return 0

    if not active_claims:
        print("No active claims in the 72h window.")
        return 0

    print(f"Active claims ({len(active_claims)}):")
    for c in active_claims:
        ticket_str = f" [{c.ticket}]" if c.ticket else ""
        print(f"- {c.claim_id}: {c.owner_name} <{c.owner_email}> | branch={c.branch} (base={c.base_branch}) | stage={c.stage}{ticket_str}")
        print(f"    symptom : {c.symptom}")
        print(f"    fix     : {c.diagnosis_and_fix}")
        print(f"    files   : {', '.join(c.files) or '(none)'}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    repo_path = args.repo
    owner_email, _, branch, _ = get_repo_identity(repo_path)
    claim_id = make_claim_id(owner_email, branch)
    delete_local_claim_ref(repo_path, claim_id)
    try:
        _run_git(
            repo_path,
            ["push", "--no-verify", "origin", "--delete", f"{REF_PREFIX}{claim_id}"],
            timeout=3.0,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        pass
    save_local_state(repo_path, LocalState())
    print(f"Cleared claim '{claim_id}'.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stake",
        description="Serverless Git-ref duplicate-work radar for multi-agent teams.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Configure global Git hooks, ~/.config/stake/config.json, and user-level agent instructions")
    p_setup.set_defaults(func=cmd_setup)

    p_disable = sub.add_parser("disable", help="Disable Stake for a repository in ~/.config/stake/config.json")
    p_disable.add_argument("--repo", default=".", help="Target git repository path")
    p_disable.set_defaults(func=cmd_disable)

    p_enable = sub.add_parser("enable", help="Re-enable Stake for a repository in ~/.config/stake/config.json")
    p_enable.add_argument("--repo", default=".", help="Target git repository path")
    p_enable.set_defaults(func=cmd_enable)

    p_claim = sub.add_parser("claim", help="Declare diagnosis and planned fix at planning time")
    p_claim.add_argument("--symptom", required=True, help="1-sentence description of the symptom or issue")
    p_claim.add_argument("--fix", required=True, help="1-2 sentence root cause diagnosis and proposed fix")
    p_claim.add_argument("--files", default="", help="Comma-separated repo-relative file paths to be modified")
    p_claim.add_argument("--ticket", default=None, help="Optional issue tracker ticket key (e.g. PROJ-412)")
    p_claim.add_argument("--base", default=None, help="Optional target base branch override (e.g. development, release/stg)")
    p_claim.add_argument("--repo", default=".", help="Target git repository path")
    p_claim.set_defaults(func=cmd_claim)

    p_status = sub.add_parser("status", help="List active claims in the repository")
    p_status.add_argument("--json", action="store_true", help="Emit JSON output")
    p_status.add_argument("--repo", default=".", help="Target git repository path")
    p_status.set_defaults(func=cmd_status)

    p_hook = sub.add_parser("hook", help="Internal git hook entry point")
    p_hook.add_argument("hook_name", choices=["pre-commit", "pre-push"])
    p_hook.add_argument("--repo", default=".", help="Target git repository path")

    p_clear = sub.add_parser("clear", help="Remove the active claim for the current branch")
    p_clear.add_argument("--repo", default=".", help="Target git repository path")
    p_clear.set_defaults(func=cmd_clear)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "hook":
        if args.hook_name == "pre-commit":
            return cmd_hook_pre_commit(args)
        return cmd_hook_pre_push(args)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
