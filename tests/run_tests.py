#!/usr/bin/env python3
"""Test suite for research-skills. Standard library only.

    python3 tests/run_tests.py
    uv run --with pyyaml --with jsonschema python3 tests/run_tests.py  # + structural

Covers the three things that can silently rot:

  1. Hooks behave correctly AND fail open. A guard that crashes on a malformed payload and
     blocks real work is worse than no guard, so that case is tested explicitly.
  2. rs_validate catches every defect planted in tests/fixtures/broken-survey.
  3. The worked example in examples/ still passes its own validator — so the documentation
     cannot drift away from the schemas.

Exit 0 all green, 1 on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "hooks")
VALIDATE = os.path.join(ROOT, "scripts", "rs_validate.py")
BROKEN = os.path.join(ROOT, "tests", "fixtures", "broken-survey")
EXAMPLE = os.path.join(
    ROOT,
    "examples",
    "worked-survey",
    ".research",
    "survey",
    "retrieval-augmented-agents",
)

passed = 0
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}" + (f"\n         {detail}" if detail else ""))


def run_hook(script: str, payload) -> tuple[int, str, str]:
    p = subprocess.run(
        [sys.executable, os.path.join(HOOKS, script)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def outcome(stdout: str) -> str:
    """Classify a hook's decision from its stdout."""
    if not stdout:
        return "silent"
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        return "malformed-output"
    hso = d.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return "deny"
    if d.get("decision") == "block":
        return "block"
    if d.get("systemMessage"):
        return "warn-user"
    if hso.get("additionalContext"):
        return "context"
    return "other"


# ---------------------------------------------------------------- hook tests


def test_hooks(tmp: str) -> None:
    print("\nhooks")

    survey = os.path.join(tmp, ".research", "survey", "demo")
    os.makedirs(os.path.join(survey, "notes"), exist_ok=True)

    bib = os.path.join(tmp, "refs.bib")
    entry = "@inproceedings{alpha2025x,\n  title={X}\n}"

    cases = [
        (
            "bib_provenance_guard.py",
            "bib: entries without provenance -> deny",
            {
                "cwd": tmp,
                "tool_name": "Write",
                "tool_input": {"file_path": bib, "content": entry},
            },
            "deny",
        ),
        (
            "bib_provenance_guard.py",
            "bib: entries with provenance -> allow",
            {
                "cwd": tmp,
                "tool_name": "Write",
                "tool_input": {
                    "file_path": bib,
                    "content": "% rs-provenance: tool=x date=2026-08-03\n" + entry,
                },
            },
            "silent",
        ),
        (
            "bib_provenance_guard.py",
            "bib: Edit adding an entry -> deny",
            {
                "cwd": tmp,
                "tool_name": "Edit",
                "tool_input": {"file_path": bib, "old_string": "", "new_string": entry},
            },
            "deny",
        ),
        (
            "bib_provenance_guard.py",
            "bib: non-.bib path -> allow",
            {
                "cwd": tmp,
                "tool_name": "Write",
                "tool_input": {
                    "file_path": os.path.join(tmp, "n.md"),
                    "content": entry,
                },
            },
            "silent",
        ),
    ]
    for script, name, payload, want in cases:
        rc, out, err = run_hook(script, payload)
        check(
            name,
            rc == 0 and outcome(out) == want,
            f"rc={rc} outcome={outcome(out)} want={want} stderr={err[:120]}",
        )

    # Absence guard. Prose asserting an absence, in a project that has a survey.
    prose = {
        "cwd": tmp,
        "tool_name": "Write",
        "tool_input": {
            "file_path": os.path.join(tmp, "related_work.md"),
            "content": "To the best of our knowledge, no prior work "
            "evaluates this setting.\n",
        },
    }

    rc, out, _ = run_hook("absence_claim_guard.py", prose)
    check(
        "absence: no gaps.yml -> block",
        rc == 0 and outcome(out) == "block",
        f"outcome={outcome(out)}",
    )

    with open(os.path.join(survey, "gaps.yml"), "w", encoding="utf-8") as fh:
        fh.write(
            "gaps:\n  - id: G1\n    evidence_of_absence:\n      queries_run:\n"
            "        - 'a'\n        - 'b'\n        - 'c'\n"
        )
    rc, out, _ = run_hook("absence_claim_guard.py", prose)
    check(
        "absence: backed by gaps.yml -> allow",
        rc == 0 and outcome(out) == "silent",
        f"outcome={outcome(out)}",
    )

    outside = dict(prose, cwd=tempfile.mkdtemp())
    rc, out, _ = run_hook("absence_claim_guard.py", outside)
    check(
        "absence: outside a survey project -> silent",
        rc == 0 and outcome(out) == "silent",
        f"outcome={outcome(out)}",
    )

    # Staleness.
    proto = os.path.join(survey, "protocol.yml")
    with open(proto, "w", encoding="utf-8") as fh:
        fh.write(
            "topic: demo\nlast_searched_at: 2020-01-01\nphase: 5\n"
            "counts:\n  deduped: 240\n  adjudicated: 150\n"
        )
    rc, out, _ = run_hook("survey_staleness.py", {"cwd": tmp, "source": "startup"})
    check(
        "staleness: old protocol -> context",
        rc == 0 and outcome(out) == "context",
        f"outcome={outcome(out)}",
    )

    import datetime

    with open(proto, "w", encoding="utf-8") as fh:
        fh.write(f"topic: demo\nlast_searched_at: {datetime.date.today().isoformat()}\n")
    rc, out, _ = run_hook("survey_staleness.py", {"cwd": tmp, "source": "startup"})
    check(
        "staleness: fresh protocol -> silent",
        rc == 0 and outcome(out) == "silent",
        f"outcome={outcome(out)}",
    )

    # Stop-hook audit: 7/10 abstract-only, all from one recall mode.
    recs = [
        {
            "key": f"alpha2025a{i}",
            "title": f"P{i}",
            "found_via": ["keyword:r1"],
            "relevance": 7,
            "screen": "include",
            "evidence_read": "abstract",
            "accessed": "2026-08-03",
        }
        for i in range(7)
    ]
    recs += [
        {
            "key": f"beta2025b{i}",
            "title": f"D{i}",
            "found_via": ["keyword:r1"],
            "relevance": 9,
            "screen": "include",
            "evidence_read": "full",
            "accessed": "2026-08-03",
        }
        for i in range(3)
    ]
    with open(os.path.join(survey, "corpus.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in recs))

    rc, out, _ = run_hook("stop_survey_peer.py", {"cwd": tmp, "hook_event_name": "Stop"})
    ok = rc == 0 and outcome(out) == "warn-user"
    msg = json.loads(out)["systemMessage"] if ok else ""
    check("stop: abstract-heavy corpus -> warn", ok, f"outcome={outcome(out)}")
    check("stop: names the depth problem", "abstract-only" in msg, msg[:160])
    check("stop: names single-mode recall", "no other mode" in msg, msg[:160])

    rc, out, _ = run_hook("stop_survey_peer.py", {"cwd": tempfile.mkdtemp()})
    check(
        "stop: no survey dir -> silent",
        rc == 0 and outcome(out) == "silent",
        f"outcome={outcome(out)}",
    )

    # Fail-open: every hook must survive garbage without blocking.
    print("\nhooks fail open")
    for script in (
        "bib_provenance_guard.py",
        "absence_claim_guard.py",
        "survey_staleness.py",
        "stop_survey_peer.py",
    ):
        for label, payload in (
            ("malformed json", "{not json at all"),
            ("empty stdin", ""),
            ("unexpected shape", {"wat": True}),
        ):
            rc, out, _ = run_hook(script, payload)
            check(
                f"{script.replace('.py', '')}: {label} -> exit 0, no block",
                rc == 0 and outcome(out) in ("silent", "other"),
                f"rc={rc} outcome={outcome(out)}",
            )


# ------------------------------------------------------------ validator tests


def run_validate(path: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, VALIDATE, path], capture_output=True, text=True)
    return p.returncode, p.stdout


def test_validator() -> None:
    print("\nvalidator")

    rc, out = run_validate(BROKEN)
    check("broken fixture exits nonzero", rc == 1, f"rc={rc}")

    # Each planted defect must be named. Keyed to tests/fixtures/broken-survey/README.md.
    expected = [
        ("1  non-interrogative question", "not interrogative"),
        ("2  empty citation_chain mode", "citation_chain"),
        ("3  low adjudication coverage", "adjudicated"),
        ("4  include without claim", "missing `claim`"),
        ("5  exclude without reason", "exclude_reason"),
        ("6  coverage axes drift", "axes differ from protocol"),
        ("7  unexplored without trend evidence", "trend_evidence"),
        ("8  high confidence on thin evidence", "confidence `high` but missing"),
        ("9  bib without provenance", "no tool-provenance header"),
        ("10 single-mode recall", "no other mode"),
    ]
    for label, needle in expected:
        check(f"catches defect {label}", needle in out, f"missing {needle!r}")

    rc, out = run_validate(EXAMPLE)
    check(
        "worked example passes clean",
        rc == 0 and "0 error(s)" in out,
        f"rc={rc}\n{out}",
    )


# ------------------------------------------------------------------- plugin


def test_plugin_shape() -> None:
    print("\nplugin shape")

    import re

    skills = sorted(os.listdir(os.path.join(ROOT, "skills")))
    check("all seven skills present", len(skills) == 7, str(skills))

    may_search = {"survey", "watch", "red-team"}
    for s in skills:
        p = os.path.join(ROOT, "skills", s, "SKILL.md")
        head = re.match(r"^---\n(.*?)\n---", open(p, encoding="utf-8").read(), re.DOTALL)
        check(f"{s}: has frontmatter", head is not None)
        if not head:
            continue
        fm = head.group(1)
        check(
            f"{s}: declares a name", re.search(r"^name:\s*\S", fm, re.MULTILINE) is not None
        )
        restricted = "disallowed-tools" in fm
        # The invariant: only survey, watch and red-team may reach for search tools.
        check(
            f"{s}: search restriction is {'absent' if s in may_search else 'present'}",
            restricted == (s not in may_search),
            f"disallowed-tools present={restricted}",
        )

    for name in ("hooks/hooks.json", ".claude-plugin/plugin.json"):
        try:
            json.load(open(os.path.join(ROOT, name), encoding="utf-8"))
            check(f"{name} parses", True)
        except Exception as exc:
            check(f"{name} parses", False, str(exc))


def main() -> int:
    print(f"research-skills tests  (python {sys.version.split()[0]})")
    try:
        import jsonschema  # noqa: F401

        print("structural checks: enabled")
    except ImportError:
        print("structural checks: SKIPPED (no jsonschema) — semantic checks still run")

    with tempfile.TemporaryDirectory() as tmp:
        test_hooks(tmp)
    test_validator()
    test_plugin_shape()

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
