#!/usr/bin/env python3
"""cmb:audit — persist findings to .cmb/audit/ and diff against the prior run.

This is the *optional* happy path for the JSON output described in
references/output-schema.md. It exists because two things are easy to get subtly
wrong by hand and must be byte-for-byte consistent across runs: the stable
finding id (a sha256 over identity fields, excluding the line number) and the
diff that classifies findings as resolved / new / open. If no shell or Python is
available, write the same files by hand following output-schema.md.

Usage:
    # assemble the audit as JSON (see PAYLOAD below) and pipe it in:
    python cmb_audit_store.py write --root /path/to/audited/repo < payload.json
    # ...or read the payload from a file:
    python cmb_audit_store.py write --root . --payload payload.json

    # compute a single id (handy when writing files by hand):
    python cmb_audit_store.py id --dimension security --file app.py --rule sql-injection

    # verify the tool itself:
    python cmb_audit_store.py --self-test

`write` reads any existing .cmb/audit/ under --root, writes the new manifest +
per-dimension files (overwriting state), and prints the diff summary JSON to
stdout for the caller to fold into the chat summary and the markdown report.

PAYLOAD shape (ids/status/first_seen are filled in for you):
{
  "scope": "services/payments",
  "stack": ["python", "flask"],
  "commit": "41d0863",                 // or null
  "dimensions": {
    "security": {
      "ran": true, "score": 3, "headline": "...",
      "findings": [
        {"severity": "critical", "rule": "sql-injection", "title": "...",
         "file": "services/payments/charge.py", "line": 42,
         "evidence": "...", "recommendation": "...", "locator": ""}
      ]
    },
    "accessibility": {"ran": false, "reason": "no frontend code in scope"}
  }
}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

SCHEMA_VERSION = 1
SEVERITIES = ("critical", "high", "medium", "low")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def finding_id(dimension: str, file: str, rule: str, locator: str = "") -> str:
    """Stable id for 'the same underlying issue'. Excludes line number and title
    on purpose so a finding that moves or is reworded still matches across runs.
    Must match the rule in references/output-schema.md exactly."""
    key = f"{dimension}|{file or ''}|{rule}|{locator or ''}".lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    base = os.path.basename(file) if file else ""
    return f"{dimension}:{base}:{rule}:{digest}"


def _audit_dir(root: str) -> str:
    return os.path.join(root, ".cmb/audit")


def _atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path)
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


def load_prior(root: str) -> dict:
    """Map id -> prior finding (carrying first_seen), from any *.json except the
    manifest, plus the set of dimensions that actually ran last time (so 'new'
    findings in a dimension that wasn't assessed before can be told apart from
    genuine regressions). Returns empty structures when there's no prior run."""
    adir = _audit_dir(root)
    prior: dict = {}
    prior_generated_at = None
    ran_dims: set = set()
    if not os.path.isdir(adir):
        return {"findings": prior, "generated_at": None, "ran_dims": ran_dims}
    manifest_path = os.path.join(adir, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            man = json.load(open(manifest_path, encoding="utf-8"))
            prior_generated_at = man.get("generated_at")
            ran_dims = {d for d, info in man.get("dimensions", {}).items() if info.get("ran")}
        except (ValueError, OSError):
            prior_generated_at = None
    for name in sorted(os.listdir(adir)):
        if not name.endswith(".json") or name == "manifest.json":
            continue
        try:
            data = json.load(open(os.path.join(adir, name), encoding="utf-8"))
        except (ValueError, OSError):
            continue
        dim = data.get("dimension")
        if dim:
            ran_dims.add(dim)  # presence of a findings file also means it ran
        for f in data.get("findings", []):
            fid = f.get("id")
            if fid:
                prior[fid] = f
    return {"findings": prior, "generated_at": prior_generated_at, "ran_dims": ran_dims}


def build(payload: dict, prior: dict, generated_at: str) -> dict:
    """Compute ids, statuses, counts, scores, and the diff. Pure: no I/O."""
    prior_findings = prior["findings"]
    dimensions_in = payload.get("dimensions", {})

    current_ids: set = set()
    dim_files: dict = {}            # dimension -> file object to write
    manifest_dims: dict = {}
    scores = []

    for dim, info in dimensions_in.items():
        if not info.get("ran", False):
            manifest_dims[dim] = {"ran": False, "reason": info.get("reason", "not applicable")}
            continue
        score = info.get("score")
        if isinstance(score, (int, float)):
            scores.append(score)
        counts = {s: 0 for s in SEVERITIES}
        out_findings = []
        for f in info.get("findings", []):
            fid = finding_id(dim, f.get("file", ""), f.get("rule", "unknown"), f.get("locator", ""))
            current_ids.add(fid)
            sev = f.get("severity", "low")
            if sev in counts:
                counts[sev] += 1
            if fid in prior_findings:
                status = "open"
                first_seen = prior_findings[fid].get("first_seen", generated_at)
            else:
                status = "new"
                first_seen = generated_at
            out_findings.append({
                "id": fid,
                "severity": sev,
                "rule": f.get("rule", "unknown"),
                "title": f.get("title", ""),
                "file": f.get("file"),
                "line": f.get("line"),
                "evidence": f.get("evidence", ""),
                "recommendation": f.get("recommendation", ""),
                "status": status,
                "first_seen": first_seen,
            })
        dim_files[dim] = {
            "schema_version": SCHEMA_VERSION,
            "dimension": dim,
            "generated_at": generated_at,
            "scope": payload.get("scope"),
            "score": score,
            "headline": info.get("headline", ""),
            "findings": out_findings,
        }
        manifest_dims[dim] = {
            "ran": True,
            "score": score,
            "headline": info.get("headline", ""),
            "findings_file": f"{dim}.json",
            "counts": counts,
        }

    overall = round(sum(scores) / len(scores), 1) if scores else None
    critical_present = any(
        f["severity"] == "critical" for df in dim_files.values() for f in df["findings"]
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "tool": "cmb:audit",
        "generated_at": generated_at,
        "scope": payload.get("scope"),
        "stack": payload.get("stack", []),
        "commit": payload.get("commit"),
        "overall_score": overall,
        "critical_present": critical_present,
        "dimensions": manifest_dims,
    }

    # diff
    def brief(f):
        return {"id": f["id"], "dimension": f["id"].split(":", 1)[0],
                "severity": f["severity"], "title": f["title"]}

    current_by_id = {f["id"]: f for df in dim_files.values() for f in df["findings"]}
    had_prior = bool(prior_findings) or prior["generated_at"] is not None
    prior_ran = prior.get("ran_dims", set())
    resolved = [
        {"id": fid, "dimension": fid.split(":", 1)[0],
         "severity": pf.get("severity", "low"), "title": pf.get("title", "")}
        for fid, pf in prior_findings.items() if fid not in current_ids
    ]
    # A "new" finding in a dimension that wasn't assessed last time isn't a
    # regression — it's newly-assessed surface. Only split this way when we have a
    # prior run AND we actually know which dimensions ran (prior_ran non-empty).
    new, newly_assessed = [], []
    for f in current_by_id.values():
        if f["status"] != "new":
            continue
        dim = f["id"].split(":", 1)[0]
        if had_prior and prior_ran and dim not in prior_ran:
            newly_assessed.append(brief(f))
        else:
            new.append(brief(f))
    open_ = [dict(brief(f), first_seen=f["first_seen"])
             for f in current_by_id.values() if f["status"] == "open"]
    diff = {
        "had_prior": had_prior,
        "prior_generated_at": prior["generated_at"],
        "resolved": resolved,
        "new": new,
        "newly_assessed": newly_assessed,
        "open": open_,
        "counts": {"resolved": len(resolved), "new": len(new),
                   "newly_assessed": len(newly_assessed), "open": len(open_)},
    }
    return {"manifest": manifest, "dim_files": dim_files, "diff": diff}


def write_state(root: str, built: dict) -> None:
    adir = _audit_dir(root)
    os.makedirs(adir, exist_ok=True)
    # overwrite state: clear existing *.json in the dir (tool owns this dir)
    for name in os.listdir(adir):
        if name.endswith(".json"):
            os.remove(os.path.join(adir, name))
    _atomic_write(os.path.join(adir, "manifest.json"), _dump(built["manifest"]))
    for dim, obj in built["dim_files"].items():
        _atomic_write(os.path.join(adir, f"{dim}.json"), _dump(obj))


def cmd_write(args) -> int:
    raw = open(args.payload, encoding="utf-8").read() if args.payload and args.payload != "-" else sys.stdin.read()
    payload = json.loads(raw)
    generated_at = args.now or now_iso()
    prior = load_prior(args.root)
    built = build(payload, prior, generated_at)
    write_state(args.root, built)
    sys.stdout.write(_dump(built["diff"]))
    return 0


def cmd_id(args) -> int:
    sys.stdout.write(finding_id(args.dimension, args.file, args.rule, args.locator) + "\n")
    return 0


def self_test() -> int:
    import shutil
    tmp = tempfile.mkdtemp(prefix="cmb-audit-selftest-")
    try:
        # id is stable and line-independent
        a = finding_id("security", "app.py", "sql-injection", "")
        b = finding_id("security", "app.py", "sql-injection", "")
        assert a == b, "id not stable"

        run1 = {
            "scope": ".", "stack": ["python"], "commit": None,
            "dimensions": {
                "security": {"ran": True, "score": 3, "headline": "h", "findings": [
                    {"severity": "critical", "rule": "sql-injection", "title": "SQLi", "file": "app.py", "line": 10},
                    {"severity": "high", "rule": "hardcoded-secret", "title": "secret", "file": "app.py", "line": 5},
                ]},
                "accessibility": {"ran": False, "reason": "no frontend"},
            },
        }
        b1 = build(run1, load_prior(tmp), "2026-01-01T00:00:00Z")
        write_state(tmp, b1)
        assert b1["diff"]["counts"] == {"resolved": 0, "new": 2, "newly_assessed": 0, "open": 0}, b1["diff"]["counts"]
        assert b1["manifest"]["overall_score"] == 3
        assert b1["manifest"]["critical_present"] is True
        assert os.path.exists(os.path.join(tmp, ".cmb/audit", "security.json"))
        assert not os.path.exists(os.path.join(tmp, ".cmb/audit", "accessibility.json"))

        # run 2: secret fixed (removed); sqli persists at a NEW line; a genuine new
        # security finding (security ran last time); and a performance finding in a
        # dimension that did NOT run last time (should be newly_assessed, not new).
        run2 = {
            "scope": ".", "stack": ["python"], "commit": None,
            "dimensions": {
                "security": {"ran": True, "score": 5, "headline": "h", "findings": [
                    {"severity": "critical", "rule": "sql-injection", "title": "SQLi (reworded)", "file": "app.py", "line": 99},
                    {"severity": "medium", "rule": "weak-hash", "title": "MD5 used", "file": "app.py", "line": 12},
                ]},
                "performance": {"ran": True, "score": 8, "headline": "h", "findings": [
                    {"severity": "medium", "rule": "n-plus-1", "title": "N+1", "file": "app.py", "line": 20},
                ]},
            },
        }
        b2 = build(run2, load_prior(tmp), "2026-02-01T00:00:00Z")
        c = b2["diff"]["counts"]
        assert c == {"resolved": 1, "new": 1, "newly_assessed": 1, "open": 1}, c
        assert b2["diff"]["new"][0]["title"] == "MD5 used"               # security ran before -> regression
        assert b2["diff"]["newly_assessed"][0]["title"] == "N+1"         # performance is new surface
        # sqli carried over: first_seen preserved from run 1 despite the line move
        sec = b2["dim_files"]["security"]["findings"][0]
        assert sec["status"] == "open" and sec["first_seen"] == "2026-01-01T00:00:00Z", sec
        assert b2["diff"]["resolved"][0]["title"] == "secret"
        write_state(tmp, b2)
        # overwrite cleared the now-empty-of-findings dims correctly
        assert not os.path.exists(os.path.join(tmp, ".cmb/audit", "accessibility.json"))
        print("self-test OK")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Persist cmb:audit findings to .cmb/audit/ and diff against the prior run.")
    p.add_argument("--self-test", action="store_true", help="run internal checks and exit")
    sub = p.add_subparsers(dest="cmd")

    pw = sub.add_parser("write", help="write .cmb/audit/ from a payload and print the diff")
    pw.add_argument("--root", default=".", help="root of the audited repo (default: cwd)")
    pw.add_argument("--payload", default="-", help="payload JSON file, or - for stdin (default)")
    pw.add_argument("--now", default=None, help="override timestamp (ISO8601, for testing)")
    pw.set_defaults(func=cmd_write)

    pi = sub.add_parser("id", help="print the stable id for one finding")
    pi.add_argument("--dimension", required=True)
    pi.add_argument("--file", required=True)
    pi.add_argument("--rule", required=True)
    pi.add_argument("--locator", default="")
    pi.set_defaults(func=cmd_id)

    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
