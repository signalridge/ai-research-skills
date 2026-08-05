#!/usr/bin/env python3
"""Test suite for research-skills. Standard library only.

    python3 tests/run_tests.py
    uv run --with pyyaml --with jsonschema python3 tests/run_tests.py  # + structural

Covers the four things that can silently rot:

  1. Hooks behave correctly AND fail open. A guard that crashes on a malformed payload and
     blocks real work is worse than no guard, so that case is tested explicitly.
  2. rs_validate catches every defect planted in tests/fixtures/broken-survey.
  3. The worked example in examples/ still passes its own validator — so the documentation
     cannot drift away from the schemas.
  4. install.py lands every asset, merges hooks into settings.json idempotently, and
     uninstalls without touching foreign hooks — and doctor reads the result back,
     failing on an empty project and passing on an installed one.

Exit 0 all green, 1 on any failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".claude", "hooks")
SKILLS = os.path.join(ROOT, ".claude", "skills")
INSTALL = os.path.join(ROOT, "install.py")
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

    # Zero-corroboration: 12 includes read past the abstract, not one link between them.
    recs = [
        {
            "key": f"gamma2025c{i}",
            "title": f"C{i}",
            "found_via": ["keyword:r1"] if i % 2 else ["citation_chain:W1:cites"],
            "relevance": 8,
            "screen": "include",
            "evidence_read": "intro+method+results",
            "accessed": "2026-08-03",
        }
        for i in range(12)
    ]
    with open(os.path.join(survey, "corpus.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in recs))
    rc, out, _ = run_hook("stop_survey_peer.py", {"cwd": tmp, "hook_event_name": "Stop"})
    ok = rc == 0 and outcome(out) == "warn-user"
    msg = json.loads(out)["systemMessage"] if ok else ""
    check("stop: zero corroboration -> warn", ok, f"outcome={outcome(out)}")
    check(
        "stop: names both readings of zero corroboration",
        "genuinely uncontested" in msg and "stopped at the surface" in msg,
        msg[:160],
    )

    recs[0]["corroboration"] = {"agrees_with": ["gamma2025c1"]}
    with open(os.path.join(survey, "corpus.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in recs))
    rc, out, _ = run_hook("stop_survey_peer.py", {"cwd": tmp, "hook_event_name": "Stop"})
    msg = json.loads(out)["systemMessage"] if out else ""
    check(
        "stop: one corroboration link -> corroboration warning gone",
        "uncontested" not in msg,
        msg[:160],
    )

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
        ("2b missing contrarian mode", "recall mode `contrarian` is empty"),
        ("3  low adjudication coverage", "adjudicated"),
        ("4  include without claim", "missing `claim`"),
        ("5  exclude without reason", "exclude_reason"),
        ("6  coverage axes drift", "axes differ from protocol"),
        ("7  unexplored without trend evidence", "trend_evidence"),
        ("8  high confidence on thin evidence", "confidence `high` but missing"),
        ("9  bib without provenance", "no tool-provenance header"),
        ("10 single-mode recall", "no other mode"),
        ("12 abandoned cell promoted to a gap", "marked `abandoned` but promoted"),
        ("13 revivable_by names a non-corpus key", "not a corpus.jsonl key"),
    ]
    for label, needle in expected:
        check(f"catches defect {label}", needle in out, f"missing {needle!r}")

    try:
        import jsonschema  # noqa: F401

        # iter_errors surfaces every violation; validate() would stop at the first and
        # hide this one behind the queries_run error earlier in the same document.
        check(
            "catches defect 11 nearest_prior_work without differing_axis",
            "'differing_axis' is a required property" in out,
            "missing differing_axis violation",
        )
        check(
            "reports more than one schema error per document",
            out.count("schema violation") > 1,
            f"only {out.count('schema violation')} schema violations reported",
        )
    except ImportError:
        pass

    rc, out = run_validate(EXAMPLE)
    check(
        "worked example passes clean",
        rc == 0 and "0 error(s)" in out,
        f"rc={rc}\n{out}",
    )


# ------------------------------------------------------------------- layout


def test_layout() -> None:
    print("\nlayout")

    import re

    skills = sorted(os.listdir(SKILLS))
    check("all seven skills present", len(skills) == 7, str(skills))

    may_search = {"rs-survey", "rs-watch", "rs-red-team"}
    for s in skills:
        p = os.path.join(SKILLS, s, "SKILL.md")
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

    # Handoffs closure: every skill declares one, and every skill it names exists.
    # The contract is prose for the agent, but the edge set is machine-checkable.
    for s in skills:
        text = open(os.path.join(SKILLS, s, "SKILL.md"), encoding="utf-8").read()
        m = re.search(r"^## Handoffs\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        check(f"{s}: declares handoffs", m is not None)
        if not m:
            continue
        for ref in sorted(set(re.findall(r"rs-[a-z-]+", m.group(1))) - {s}):
            check(f"{s}: handoff target {ref} exists", ref in skills, f"{ref} not a skill")

    # Progressive disclosure: every `references/*.md` link in a SKILL.md resolves to a
    # real file, and reference files never link further down — one level, or the
    # disclosure graph rots where nothing checks it.
    ref_link = re.compile(r"references/[\w.-]+\.md")
    for s in skills:
        text = open(os.path.join(SKILLS, s, "SKILL.md"), encoding="utf-8").read()
        for rel in sorted(set(ref_link.findall(text))):
            check(
                f"{s}: {rel} resolves",
                os.path.isfile(os.path.join(SKILLS, s, rel)),
                f"{s}/{rel} missing",
            )
    refs_dir = os.path.join(SKILLS, "rs-survey", "references")
    for f in sorted(os.listdir(refs_dir)):
        if not f.endswith(".md"):
            continue
        text = open(os.path.join(refs_dir, f), encoding="utf-8").read()
        check(f"references/{f}: no nested references/ link", ref_link.search(text) is None)

    commands = sorted(
        f
        for f in os.listdir(os.path.join(ROOT, ".claude", "commands"))
        if f.startswith("rs-") and f.endswith(".md")
    )
    check("all seven commands present", len(commands) == 7, str(commands))
    check("install.py present", os.path.isfile(INSTALL))


# ------------------------------------------------------------------ install


def test_install(tmp: str) -> None:
    print("\ninstall")

    target = os.path.join(tmp, "proj")
    os.makedirs(target)

    def run(*argv: str) -> tuple[int, str]:
        p = subprocess.run(
            [sys.executable, INSTALL, *argv, target], capture_output=True, text=True
        )
        return p.returncode, p.stdout + p.stderr

    def read_settings() -> dict:
        with open(os.path.join(target, ".claude", "settings.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def our_hook_entries(settings: dict) -> int:
        n = 0
        for entries in (settings.get("hooks") or {}).values():
            for entry in entries:
                for h in entry.get("hooks", []):
                    if ".claude/hooks/" in h.get("command", ""):
                        n += 1
        return n

    rc, out = run()
    check("install exits 0", rc == 0, out[-200:])
    landed = [
        os.path.join(target, ".claude", "commands", "rs-survey.md"),
        os.path.join(target, ".claude", "skills", "rs-survey", "SKILL.md"),
        os.path.join(target, ".claude", "hooks", "bib_provenance_guard.py"),
        os.path.join(target, ".claude", "research-skills", "scripts", "rs_validate.py"),
        os.path.join(target, ".claude", "research-skills", "schemas", "corpus.schema.json"),
    ]
    for path in landed:
        check(f"lands {os.path.relpath(path, target)}", os.path.isfile(path))

    settings = read_settings()
    check("settings has 4 hook entries", our_hook_entries(settings) == 4)
    check(
        "hook command uses $CLAUDE_PROJECT_DIR",
        "$CLAUDE_PROJECT_DIR/.claude/hooks/bib_provenance_guard.py"
        in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
    )

    rc, out = run()
    settings = read_settings()
    check(
        "re-install is idempotent",
        rc == 0 and our_hook_entries(settings) == 4,
        f"rc={rc} entries={our_hook_entries(settings)}",
    )

    # A user's own hook in the same event must survive both directions.
    settings["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "python3 mine.py"}]}
    )
    settings_path = os.path.join(target, ".claude", "settings.json")
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh)
    rc, _ = run("--uninstall")
    check("uninstall exits 0", rc == 0)
    gone = [p for p in landed if os.path.exists(p)]
    check("uninstall removes files", not gone, str(gone))
    settings = read_settings()
    check(
        "uninstall keeps foreign hooks",
        our_hook_entries(settings) == 0
        and settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "python3 mine.py",
        json.dumps(settings.get("hooks")),
    )


# ------------------------------------------------------------------- doctor


def test_doctor(tmp: str) -> None:
    print("\ndoctor")

    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))

    def run_doctor(target: str) -> tuple[int, str]:
        p = subprocess.run(
            [sys.executable, "-m", "research_skills", "doctor", target],
            capture_output=True,
            text=True,
            env=env,
        )
        return p.returncode, p.stdout + p.stderr

    target = os.path.join(tmp, "proj")
    os.makedirs(target)

    rc, out = run_doctor(target)
    check("doctor: empty project exits 1", rc == 1, f"rc={rc}")
    # An empty project is "not installed", not "installed and broken". Listing every
    # absent file for every known host was 60 lines of noise; the actionable thing is
    # the command that fixes it.
    check(
        "doctor: empty project says not installed",
        "not installed" in out,
        out[-300:],
    )
    check(
        "doctor: empty project names the fix",
        "research-skills install" in out,
        out[-300:],
    )

    p = subprocess.run([sys.executable, INSTALL, target], capture_output=True, text=True)
    rc, out = run_doctor(target)
    check(
        "doctor: installed project exits 0",
        p.returncode == 0 and rc == 0,
        f"install rc={p.returncode} doctor rc={rc}  {out[-160:]}",
    )


# -------------------------------------------------------------------- hosts


def test_hosts(tmp: str) -> None:
    """The registry is the multi-agent contract: detection, scoping, and honesty about
    which hosts can actually run the guardrails."""
    print("\nhosts")
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from research_skills import hosts

    ids = hosts.known_ids()
    check(
        "registry covers the eleven agents",
        set(ids)
        >= {
            "claude",
            "codex",
            "cursor",
            "pi",
            "kimi",
            "qwen",
            "opencode",
            "windsurf",
            "kilo",
            "kiro",
            "copilot",
        },
        str(ids),
    )
    # A stub that points at a path the installer never writes is a silent dead end.
    for host in hosts.HOSTS:
        if host.invocation_dir:
            check(
                f"{host.id}: include syntax carries the path",
                "{path}" in host.include,
                host.include,
            )
    kimi = hosts.lookup("kimi-code")
    check("kimi-code resolves to kimi", kimi is not None and kimi.id == "kimi")
    check("unknown host resolves to None", hosts.lookup("nonesuch") is None)

    # Only Claude Code fires an event carrying a file path before the write, so it is
    # the only host where the two write-time guards can attach. Every other host must
    # say so out loud — a user who believes they are protected and is not is worse off
    # than one who knows they are not.
    guarded = [h.id for h in hosts.HOSTS if h.hooks]
    check("exactly one host claims guardrails", guarded == ["claude"], str(guarded))
    unguarded = [h for h in hosts.HOSTS if not h.hooks]
    check(
        "every unguarded host carries a caveat",
        all(h.caveat for h in unguarded),
        str([h.id for h in unguarded if not h.caveat]),
    )
    check(
        "ownership roots are distinct",
        len({h.ownership_root for h in hosts.HOSTS}) == len(hosts.HOSTS),
    )

    proj = os.path.join(tmp, "detect")
    os.makedirs(os.path.join(proj, ".codex"), exist_ok=True)
    os.makedirs(os.path.join(proj, ".cursor"), exist_ok=True)
    detected, _ = hosts.resolve(proj, None)
    check(
        "detection finds the hosts a project uses",
        {h.id for h in detected} == {"codex", "cursor"},
        str([h.id for h in detected]),
    )
    check(
        "bare project falls back to claude",
        [h.id for h in hosts.resolve(os.path.join(tmp, "bare"), None)[0]] == ["claude"],
    )
    chosen, unknown = hosts.resolve(proj, "pi, kimi-code , nonesuch")
    check(
        "explicit selection overrides detection",
        [h.id for h in chosen] == ["pi", "kimi"],
    )
    check("unknown ids are reported, not silently dropped", unknown == ["nonesuch"])


def main() -> int:
    print(f"research-skills tests  (python {sys.version.split()[0]})")
    try:
        import jsonschema  # noqa: F401

        print("structural checks: enabled")
    except ImportError:
        print("structural checks: SKIPPED (no jsonschema) — semantic checks still run")

    with tempfile.TemporaryDirectory() as tmp:
        test_hooks(tmp)
        test_hosts(tmp)
    test_validator()
    test_layout()
    with tempfile.TemporaryDirectory() as tmp:
        test_install(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        test_doctor(tmp)

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
