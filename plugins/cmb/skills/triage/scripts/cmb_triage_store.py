#!/usr/bin/env python3
"""cmb:triage — read/write/apply per-finding decisions in .cmb/decisions.json.

This is the canonical helper for the decisions file. Like cmb_audit_store.py,
the format is also hand-writable (see references/decisions-schema.md), so the
schema is enforced here in code AND documented there in prose.

Two things must be byte-for-byte consistent with cmb_audit_store.py:
- the finding `id` format — decisions are keyed by it
- the severity vocabulary — `critical | high | medium | low`

Usage:
    # read .cmb/decisions.json (returns {} on missing)
    python cmb_triage_store.py read --root /path/to/repo

    # write a payload to .cmb/decisions.json (atomic)
    python cmb_triage_store.py write --root . --payload decisions-payload.json
    # ...or piped:
    cat decisions-payload.json | python cmb_triage_store.py write --root .

    # given the current manifest + decisions, classify each finding for the audit
    python cmb_triage_store.py apply --root . --manifest .cmb/audit/manifest.json

    # rename a decision id (slug-drift carry-over)
    python cmb_triage_store.py relink --root . --from <old-id> --to <new-id>

    # verify the tool itself
    python cmb_triage_store.py --self-test

PAYLOAD shape for `write` (ids are the key; decided_at defaults to now if
missing; severity_at_decision/title_at_decision must be provided):
{
  "decisions": {
    "<finding-id>": {
      "verb": "plan" | "accept-risk" | "dismiss",
      "justification": "...",
      "severity_at_decision": "critical" | "high" | "medium" | "low",
      "title_at_decision": "...",
      "decided_by": "...",              // optional
      "plan_file": "audit-reports/...", // optional, only for plan
      "expires_at": "...Z"              // optional, only for accept-risk
    }
  }
}

APPLY return shape (printed to stdout, consumed by the audit orchestrator):
{
  "counts": {
    "open": N, "new": N, "resolved": N, "newly_assessed": N,
    "suppressed": N, "planned": N, "dismissed": N,
    "escalated": N, "expired": N, "orphans": N
  },
  "applied": [
    {"id": "...", "verb": "accept-risk", "state": "suppressed",
     "severity_now": "high", "severity_at_decision": "high",
     "title": "...", "dimension": "security"},
    {"id": "...", "verb": "accept-risk", "state": "escalated",
     "severity_now": "critical", "severity_at_decision": "high", ...},
    {"id": "...", "verb": "plan", "state": "planned",
     "plan_file": "audit-reports/...", ...},
    {"id": "...", "verb": "dismiss", "state": "dismissed", ...}
  ],
  "orphans": [
    {"id": "...", "verb": "...", "title_at_decision": "...",
     "reason": "no longer present in current audit (resolved or out of scope)"}
  ]
}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

SCHEMA_VERSION = 1
VERBS = ("plan", "accept-risk", "dismiss")
SEVERITIES = ("critical", "high", "medium", "low")
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITIES))}  # low=0 .. critical=3


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmb_dir(root: str) -> str:
    return os.path.join(root, ".cmb")


def _decisions_path(root: str) -> str:
    return os.path.join(_cmb_dir(root), "decisions.json")


def _atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def empty_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "tool": "cmb:triage", "decisions": {}}


def read(root: str) -> dict:
    """Load .cmb/decisions.json. Returns empty_state() if missing.
    Validates every decision and raises ValueError on malformed entries."""
    path = _decisions_path(root)
    if not os.path.exists(path):
        return empty_state()
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON: {e}") from e
    _validate(data, path)
    return data


def _validate(data: dict, path_hint: str = "<payload>") -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{path_hint}: top-level must be an object")
    if data.get("schema_version") != SCHEMA_VERSION:
        # Future versions: bump here. For now: tolerate missing/old to allow
        # easy hand-edits, but warn-shape on stderr.
        if "schema_version" in data:
            print(
                f"warning: {path_hint} schema_version={data.get('schema_version')!r} "
                f"(expected {SCHEMA_VERSION})", file=sys.stderr,
            )
    decisions = data.get("decisions") or {}
    if not isinstance(decisions, dict):
        raise ValueError(f"{path_hint}: 'decisions' must be an object keyed by finding id")
    for fid, dec in decisions.items():
        _validate_decision(fid, dec, path_hint)


def _validate_decision(fid: str, dec: dict, path_hint: str) -> None:
    if not isinstance(dec, dict):
        raise ValueError(f"{path_hint}: decisions[{fid!r}] must be an object")
    verb = dec.get("verb")
    if verb not in VERBS:
        raise ValueError(
            f"{path_hint}: decisions[{fid!r}].verb must be one of {VERBS}, got {verb!r}"
        )
    sev = dec.get("severity_at_decision")
    if sev not in SEVERITIES:
        raise ValueError(
            f"{path_hint}: decisions[{fid!r}].severity_at_decision must be one of "
            f"{SEVERITIES}, got {sev!r}"
        )
    if not dec.get("title_at_decision"):
        raise ValueError(f"{path_hint}: decisions[{fid!r}].title_at_decision is required")
    if not dec.get("decided_at"):
        raise ValueError(f"{path_hint}: decisions[{fid!r}].decided_at is required")
    if verb in ("accept-risk", "dismiss") and not dec.get("justification"):
        raise ValueError(
            f"{path_hint}: decisions[{fid!r}] uses verb {verb!r}; justification is required"
        )


def write(root: str, payload: dict) -> dict:
    """Replace .cmb/decisions.json with the given payload (after validation).
    Fills in defaults for missing optional fields. Returns the written state."""
    if "decisions" not in payload:
        raise ValueError("payload must contain a 'decisions' object")
    decisions_in = payload["decisions"] or {}
    decisions_out: dict = {}
    now = now_iso()
    for fid, dec in decisions_in.items():
        if not isinstance(dec, dict):
            raise ValueError(f"decisions[{fid!r}] must be an object")
        out = dict(dec)
        out.setdefault("decided_at", now)
        # Validate after defaults applied
        _validate_decision(fid, out, "<write payload>")
        decisions_out[fid] = out
    state = {
        "schema_version": SCHEMA_VERSION,
        "tool": "cmb:triage",
        "decisions": decisions_out,
    }
    _atomic_write(_decisions_path(root), _dump(state))
    return state


def upsert(root: str, finding_id: str, decision: dict) -> dict:
    """Add or replace a single decision; returns the written state."""
    state = read(root)
    state["decisions"][finding_id] = decision
    return write(root, state)


def remove(root: str, finding_id: str) -> dict:
    """Remove a single decision if present; returns the written state."""
    state = read(root)
    state["decisions"].pop(finding_id, None)
    return write(root, state)


def relink(root: str, old_id: str, new_id: str) -> dict:
    """Carry a decision across a slug-drift rename. Errors if old_id is absent or
    new_id already exists (no silent clobber)."""
    state = read(root)
    decisions = state["decisions"]
    if old_id not in decisions:
        raise ValueError(f"no decision found for old id {old_id!r}")
    if new_id in decisions and new_id != old_id:
        raise ValueError(f"new id {new_id!r} already has a decision (refusing to clobber)")
    decisions[new_id] = decisions.pop(old_id)
    return write(root, state)


# --- apply -----------------------------------------------------------------

def _current_findings_from_manifest(root: str, manifest: dict) -> dict:
    """Return {finding_id: {dimension, severity, title}} from the per-dimension
    files referenced by the manifest."""
    out: dict = {}
    cmb_audit = os.path.join(_cmb_dir(root), "audit")
    for dim, info in (manifest.get("dimensions") or {}).items():
        if not info.get("ran"):
            continue
        ff = info.get("findings_file")
        if not ff:
            continue
        path = os.path.join(cmb_audit, ff)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for f in data.get("findings", []):
            fid = f.get("id")
            if not fid:
                continue
            out[fid] = {
                "dimension": dim,
                "severity": f.get("severity"),
                "title": f.get("title"),
            }
    return out


def apply(root: str, manifest: dict, now: str | None = None) -> dict:
    """Classify every decision against current findings.

    Returns the applied/orphans/counts payload documented in the module docstring."""
    now = now or now_iso()
    state = read(root)
    decisions = state["decisions"]
    current = _current_findings_from_manifest(root, manifest)

    applied: list = []
    orphans: list = []
    counts = {
        "suppressed": 0, "planned": 0, "dismissed": 0,
        "escalated": 0, "expired": 0, "orphans": 0,
    }

    for fid, dec in decisions.items():
        f = current.get(fid)
        if f is None:
            orphans.append({
                "id": fid,
                "verb": dec["verb"],
                "title_at_decision": dec["title_at_decision"],
                "severity_at_decision": dec["severity_at_decision"],
                "reason": "no longer present in current audit (resolved or out of scope)",
            })
            counts["orphans"] += 1
            continue
        # Determine state:
        # 1. Escalation check (only for accept-risk and dismiss — both suppress;
        #    plan never suppresses so escalation doesn't void it)
        sev_now = f["severity"]
        sev_decided = dec["severity_at_decision"]
        escalated = (
            dec["verb"] in ("accept-risk", "dismiss")
            and SEVERITY_RANK.get(sev_now, -1) > SEVERITY_RANK.get(sev_decided, -1)
        )
        # 2. Expiry check (only for accept-risk; plan and dismiss don't expire)
        expired = (
            dec["verb"] == "accept-risk"
            and dec.get("expires_at") is not None
            and dec["expires_at"] < now
        )
        if escalated:
            state_label = "escalated"
            counts["escalated"] += 1
        elif expired:
            state_label = "expired"
            counts["expired"] += 1
        elif dec["verb"] == "plan":
            state_label = "planned"
            counts["planned"] += 1
        elif dec["verb"] == "accept-risk":
            state_label = "suppressed"
            counts["suppressed"] += 1
        else:  # dismiss
            state_label = "dismissed"
            counts["dismissed"] += 1
        applied.append({
            "id": fid,
            "verb": dec["verb"],
            "state": state_label,
            "dimension": f["dimension"],
            "title": f["title"],
            "severity_now": sev_now,
            "severity_at_decision": sev_decided,
            "plan_file": dec.get("plan_file"),
            "expires_at": dec.get("expires_at"),
        })
    return {"counts": counts, "applied": applied, "orphans": orphans}


# --- self-test -------------------------------------------------------------

def _self_test() -> None:
    """Verify read/write/upsert/relink and apply's escalation/expiry/orphan logic."""
    import shutil
    with tempfile.TemporaryDirectory() as root:
        # read on missing -> empty
        s0 = read(root)
        assert s0["decisions"] == {}, "missing file should return empty decisions"

        # write a payload with one of each verb
        decided = "2026-05-26T20:00:00Z"
        sample = {
            "decisions": {
                "security:main.py:hardcoded-secret:aaaa1111": {
                    "verb": "accept-risk",
                    "decided_at": decided,
                    "severity_at_decision": "high",
                    "title_at_decision": "Old finding title",
                    "justification": "Dev-only.",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
                "performance:doc.py:n-plus-one:bbbb2222": {
                    "verb": "plan",
                    "decided_at": decided,
                    "severity_at_decision": "high",
                    "title_at_decision": "N+1",
                    "justification": "Q3.",
                    "plan_file": "audit-reports/perf.md",
                },
                "documentation:README.md:doc-drift:cccc3333": {
                    "verb": "dismiss",
                    "decided_at": decided,
                    "severity_at_decision": "medium",
                    "title_at_decision": "Drift",
                    "justification": "FP.",
                },
                # this one will be an orphan (no current finding matches)
                "test-coverage:foo.py:bare:dddd4444": {
                    "verb": "accept-risk",
                    "decided_at": decided,
                    "severity_at_decision": "low",
                    "title_at_decision": "Orphan",
                    "justification": "old.",
                },
            }
        }
        s1 = write(root, sample)
        assert len(s1["decisions"]) == 4
        assert os.path.exists(_decisions_path(root))

        # roundtrip
        s2 = read(root)
        assert s2["decisions"] == s1["decisions"]

        # required-field validation
        try:
            write(root, {"decisions": {"x:y:z:1": {"verb": "accept-risk"}}})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for missing required fields")

        # bad verb
        try:
            write(root, {"decisions": {"x:y:z:1": {
                "verb": "wat", "decided_at": decided,
                "severity_at_decision": "low", "title_at_decision": "x",
            }}})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for unknown verb")

        # upsert + remove
        upsert(root, "x:y:z:9", {
            "verb": "plan", "decided_at": decided,
            "severity_at_decision": "low", "title_at_decision": "added",
        })
        assert "x:y:z:9" in read(root)["decisions"]
        remove(root, "x:y:z:9")
        assert "x:y:z:9" not in read(root)["decisions"]

        # relink
        relink(root, "performance:doc.py:n-plus-one:bbbb2222",
               "performance:doc.py:n-plus-1:eeee5555")
        d_after = read(root)["decisions"]
        assert "performance:doc.py:n-plus-1:eeee5555" in d_after
        assert "performance:doc.py:n-plus-one:bbbb2222" not in d_after

        # apply — manufacture a manifest + per-dim files reflecting current state
        cmb_audit = os.path.join(_cmb_dir(root), "audit")
        os.makedirs(cmb_audit, exist_ok=True)
        # security: same id but ESCALATED to critical (was high at decision)
        # performance: same NEW id (after relink) at high
        # documentation: drop the dismissed one entirely (resolved)
        # The orphan (test-coverage:foo.py:bare:dddd4444) stays as orphan
        with open(os.path.join(cmb_audit, "security.json"), "w") as fh:
            json.dump({"findings": [{
                "id": "security:main.py:hardcoded-secret:aaaa1111",
                "severity": "critical", "title": "Now critical",
            }]}, fh)
        with open(os.path.join(cmb_audit, "performance.json"), "w") as fh:
            json.dump({"findings": [{
                "id": "performance:doc.py:n-plus-1:eeee5555",
                "severity": "high", "title": "N+1 (renamed)",
            }]}, fh)
        manifest = {"dimensions": {
            "security": {"ran": True, "findings_file": "security.json"},
            "performance": {"ran": True, "findings_file": "performance.json"},
            "documentation": {"ran": True, "findings_file": "documentation.json"},
        }}
        result = apply(root, manifest, now="2026-05-26T21:00:00Z")
        states = {a["id"]: a["state"] for a in result["applied"]}
        assert states["security:main.py:hardcoded-secret:aaaa1111"] == "escalated", states
        assert states["performance:doc.py:n-plus-1:eeee5555"] == "planned", states
        # dismissed one was resolved -> orphan
        orphan_ids = {o["id"] for o in result["orphans"]}
        assert "documentation:README.md:doc-drift:cccc3333" in orphan_ids
        assert "test-coverage:foo.py:bare:dddd4444" in orphan_ids
        assert result["counts"]["escalated"] == 1, result["counts"]
        assert result["counts"]["planned"] == 1
        assert result["counts"]["orphans"] == 2

        # expiry path
        upsert(root, "security:x.py:y:ffff6666", {
            "verb": "accept-risk", "decided_at": decided,
            "severity_at_decision": "high",
            "title_at_decision": "Expiring",
            "justification": "until Q3",
            "expires_at": "2026-01-01T00:00:00Z",  # in the past
        })
        with open(os.path.join(cmb_audit, "security.json"), "w") as fh:
            json.dump({"findings": [
                {"id": "security:main.py:hardcoded-secret:aaaa1111",
                 "severity": "high", "title": "Back to high"},
                {"id": "security:x.py:y:ffff6666",
                 "severity": "high", "title": "Expiring"},
            ]}, fh)
        result = apply(root, manifest, now="2026-05-26T21:00:00Z")
        states = {a["id"]: a["state"] for a in result["applied"]}
        assert states["security:x.py:y:ffff6666"] == "expired", states
        assert states["security:main.py:hardcoded-secret:aaaa1111"] == "suppressed", states

    print("self-test OK")


# --- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="cmb:triage decisions store helper")
    p.add_argument("--self-test", action="store_true", help="run internal tests")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("read", help="print .cmb/decisions.json (empty state if missing)")
    pr.add_argument("--root", required=True)

    pw = sub.add_parser("write", help="overwrite .cmb/decisions.json with a payload")
    pw.add_argument("--root", required=True)
    pw.add_argument("--payload", help="path to payload JSON; default reads stdin")

    pa = sub.add_parser("apply", help="classify decisions vs the current manifest, print applied/orphans JSON")
    pa.add_argument("--root", required=True)
    pa.add_argument("--manifest", help="path to manifest.json (default .cmb/audit/manifest.json)")

    pl = sub.add_parser("relink", help="rename a decision id (slug-drift)")
    pl.add_argument("--root", required=True)
    pl.add_argument("--from", dest="old", required=True)
    pl.add_argument("--to", dest="new", required=True)

    args = p.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0

    if args.cmd == "read":
        print(_dump(read(args.root)), end="")
        return 0

    if args.cmd == "write":
        if args.payload:
            with open(args.payload, encoding="utf-8") as fh:
                payload = json.load(fh)
        else:
            payload = json.load(sys.stdin)
        state = write(args.root, payload)
        print(_dump(state), end="")
        return 0

    if args.cmd == "apply":
        manifest_path = args.manifest or os.path.join(
            _cmb_dir(args.root), "audit", "manifest.json"
        )
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        result = apply(args.root, manifest)
        print(_dump(result), end="")
        return 0

    if args.cmd == "relink":
        state = relink(args.root, args.old, args.new)
        print(_dump(state), end="")
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
