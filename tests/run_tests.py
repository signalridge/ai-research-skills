#!/usr/bin/env python3
"""Stdlib regression suite for ai-research-skills.

The tests exercise the host adapters, payload parser, ownership transaction and the
phase-aware validator.  The validator is deliberately run once with its development
libraries and once through the bundled fallback profile.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASSETS = SRC / "ai_research_skills" / "assets"
HOOKS = ASSETS / "hooks"
VALIDATE = ASSETS / "scripts" / "rs_validate.py"
INSTALL = ROOT / "install.py"
EXAMPLE = (
    ROOT
    / "examples"
    / "worked-survey"
    / ".research"
    / "survey"
    / "retrieval-augmented-agents"
)
BROKEN = ROOT / "tests" / "fixtures" / "broken-survey"

sys.path.insert(0, str(SRC))

passed = 0
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


def run_hook(
    name: str, payload: object, *, host: str | None = None
) -> tuple[int, str, str]:
    value = payload if isinstance(payload, str) else json.dumps(payload)
    command = [sys.executable, str(HOOKS / name)]
    if host:
        command += ["--host", host]
    result = subprocess.run(
        command,
        input=value,
        text=True,
        capture_output=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def decision(stdout: str) -> str:
    if not stdout:
        return "silent"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return "malformed"
    if (data.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny":
        return "deny"
    if data.get("permission") == "deny":
        return "deny"
    if data.get("decision") == "block":
        return "block"
    if data.get("systemMessage"):
        return "warn"
    return "other"


def run_validator(
    directory: pathlib.Path,
    *,
    fallback: bool = False,
    isolated: bool = False,
    strict: bool = False,
) -> tuple[int, str]:
    env = dict(os.environ)
    if fallback:
        env["ARS_FORCE_FALLBACK"] = "1"
    command = [sys.executable]
    if isolated:
        command += ["-I", "-S"]
    command += [str(VALIDATE)]
    if strict:
        command.append("--strict")
    command.append(str(directory))
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    return result.returncode, result.stdout + result.stderr


# --------------------------------------------------------------------------- hooks


def test_payload_and_hooks() -> None:
    print("\nhooks and payloads")
    sys.path.insert(0, str(HOOKS))
    import _payload

    pi_write = {"path": "notes/a.md", "content": "hello"}
    pi_edit = {"path": "notes/a.md", "edits": [{"newText": "one"}, {"newText": "two"}]}
    check("Pi path/content payload", _payload.operations(pi_write)[0].text == "hello")
    check("Pi edit newText payload", _payload.operations(pi_edit)[0].text == "one\ntwo")
    check(
        "Claude file_path/new_string remain supported",
        _payload.targets({"file_path": "a.md", "new_string": "x"}) == ["a.md"],
    )

    patch = """*** Begin Patch
*** Add File: first.bib
+@article{first2025x, title={First}}
*** Update File: second.md
+no prior work has done this.
*** Update File: old.md
+@article{not-a-bib-entry, title={No}}
*** Move to: moved.md
*** End Patch"""
    operations = _payload.operations({"command": patch})
    check(
        "apply_patch parses Add/Update/Move operations",
        [op.path for op in operations] == ["first.bib", "second.md", "moved.md"],
    )
    check(
        "multi-file patch text is isolated",
        operations[0].text.startswith("@article")
        and "no prior" not in operations[0].text
        and operations[1].text.startswith("no prior"),
    )
    check(
        "Move keeps source for comparison",
        operations[-1].old_path == "old.md" and operations[-1].text.startswith("@article"),
    )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        survey = root / ".research" / "survey" / "demo"
        survey.mkdir(parents=True)
        (survey / "gaps.yml").write_text(
            "gaps:\n  - id: G1\n    evidence_of_absence:\n      queries_run:\n        - a\n"
        )
        payload = {
            "cwd": raw,
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: safe.py\n+ok\n*** Update File: claim.md\n+No prior work exists here.\n*** End Patch"
            },
        }
        rc, out, _err = run_hook("absence_claim_guard.py", payload)
        check(
            "guard visits every patch operation",
            rc == 0 and decision(out) in ("block", "deny"),
        )
        gap_path = survey / "gaps.yml"
        claim = {
            "cwd": raw,
            "tool_input": {"path": "claim.md", "content": "No prior work exists here."},
        }
        gap_path.write_text(
            "gaps:\n"
            "  - id: G1\n"
            "    evidence_of_absence:\n"
            "      queries_run:\n"
            '        - "Same query"\n'
            "        - same   query\n"
            "        - SAME QUERY\n"
        )
        rc, out, _err = run_hook("absence_claim_guard.py", claim)
        check(
            "absence guard denies three duplicated normalized queries",
            rc == 0 and decision(out) in ("block", "deny"),
        )
        gap_path.write_text(
            "gaps:\n"
            "  - id: G1\n"
            "    evidence_of_absence:\n"
            "      queries_run:\n"
            "        - first phrasing\n"
            "        - second phrasing\n"
            "        - third phrasing\n"
        )
        rc, out, _err = run_hook("absence_claim_guard.py", claim)
        check("absence guard accepts three distinct queries", rc == 0 and not out)
        gap_path.write_text(
            "gaps:\n  - id: G1\n    evidence_of_absence:\n      queries_run:\n        - a\n"
        )

        bib = survey / "refs.bib"
        corpus = survey / "corpus.jsonl"
        corpus.write_text(
            json.dumps({"key": "first2025x", "id": "arXiv:2500.00001"}) + "\n"
        )
        strict = "% rs-provenance: key=first2025x id=arXiv:2500.00001 tool=arxiv.export_citations date=2026-08-03\n@article{first2025x, title={First}}\n"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": strict}},
        )
        check("strict per-entry BibTeX attestation passes", rc == 0 and not out)
        directives = (
            "@STRING{venue = {Example}}\n"
            '@Preamble("generated")\n'
            "@COMMENT{directive is not a citation}\n"
            "% rs-provenance: key=first2025x id=arXiv:2500.00001 tool=t date=2026-08-03\n"
            "@ARTICLE(first2025x, title={First})\n"
        )
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": directives}},
        )
        check(
            "BibTeX directives are ignored case-insensitively by guard",
            rc == 0 and not out,
        )
        parenthesized = "@article(first2025x, title={Unattested})\n"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": parenthesized}},
        )
        check(
            "parenthesized BibTeX entry still requires attestation",
            rc == 0 and decision(out) == "deny",
        )
        legacy = "% rs-provenance: tool=old date=2026-08-03\n@article{first2025x, title={First}}\n@article{new2025x, title={New}}\n"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": legacy}},
        )
        check(
            "legacy file header cannot authorise append",
            rc == 0 and decision(out) == "deny",
        )

        # Host stdout is a contract, not a union of permissive-looking fields.  Codex
        # fixtures reject every Cursor top-level key; Cursor rejects hookSpecificOutput.
        bad_bib = {
            "cwd": raw,
            "tool_input": {"path": str(bib), "content": "@article{new2025x, title={New}}"},
        }
        for profile, expected in (
            ("claude", {"hookSpecificOutput"}),
            ("pi", {"hookSpecificOutput"}),
            ("codex", {"hookSpecificOutput"}),
            ("cursor", {"permission", "user_message", "agent_message"}),
        ):
            rc, out, _err = run_hook("bib_provenance_guard.py", bad_bib, host=profile)
            data = json.loads(out)
            check(
                f"{profile} deny stdout uses exact profile schema",
                rc == 0 and set(data) == expected,
            )
            if profile == "codex":
                check(
                    "Codex deny fixture contains no Cursor fields",
                    not ({"permission", "user_message", "agent_message"} & set(data)),
                )

        claim_payload = {
            "cwd": raw,
            "tool_input": {"path": "draft.md", "content": "No prior work exists here."},
        }
        for profile, expected in (
            ("claude", {"decision", "reason"}),
            ("pi", {"decision", "reason"}),
            ("codex", {"hookSpecificOutput"}),
            ("cursor", {"permission", "user_message", "agent_message"}),
        ):
            rc, out, _err = run_hook("absence_claim_guard.py", claim_payload, host=profile)
            check(
                f"{profile} absence response is host-valid",
                rc == 0 and set(json.loads(out)) == expected,
            )

        (survey / "protocol.yml").write_text("topic: demo\nlast_searched_at: 2000-01-01\n")
        for profile, expected in (
            ("claude", {"hookSpecificOutput"}),
            ("pi", {"hookSpecificOutput"}),
            ("codex", {"hookSpecificOutput"}),
            ("cursor", {"additional_context"}),
        ):
            rc, out, _err = run_hook("survey_staleness.py", {"cwd": raw}, host=profile)
            check(
                f"{profile} SessionStart response uses actual schema",
                rc == 0 and set(json.loads(out)) == expected,
            )

        # A corpus belongs to the refs.bib directory.  A key in a different survey must
        # not authorize this one, and a duplicate local key is not resolved by last-write.
        other = root / ".research" / "survey" / "other"
        other.mkdir(parents=True)
        (other / "corpus.jsonl").write_text(
            json.dumps({"key": "foreign2025x", "id": "arXiv:2500.00002"}) + "\n"
        )
        cross = "% rs-provenance: key=foreign2025x id=arXiv:2500.00002 tool=t date=2026-08-03\n@article{foreign2025x, title={Foreign}}\n"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": cross}},
        )
        check(
            "foreign survey corpus cannot authorize refs",
            rc == 0 and decision(out) == "deny",
        )
        corpus.write_text(
            json.dumps({"key": "first2025x", "id": "one"})
            + "\n"
            + json.dumps({"key": "first2025x", "id": "two"})
            + "\n"
        )
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": strict}},
        )
        check(
            "duplicate corpus key cannot authorize refs",
            rc == 0 and decision(out) == "deny",
        )

        old_bib = root / "old.bib"
        old_bib.write_text("@article{move2025x, title={Old}}\n")
        partial_move = "*** Begin Patch\n*** Update File: old.bib\n@@\n- title={Old}\n+ title={New}\n*** Move to: moved.bib\n*** End Patch"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py", {"cwd": raw, "tool_input": {"command": partial_move}}
        )
        check(
            "partial BibTeX move is conservatively denied",
            rc == 0 and decision(out) == "deny",
        )
        full_move = "*** Begin Patch\n*** Update File: old.bib\n+% rs-provenance: key=move2025x id=arXiv:2500.00003 tool=t date=2026-08-03\n+@article{move2025x, title={New}}\n*** Move to: moved.bib\n*** End Patch"
        (root / ".research" / "survey" / "demo" / "corpus.jsonl").write_text(
            json.dumps({"key": "move2025x", "id": "arXiv:2500.00003"}) + "\n"
        )
        rc, out, _err = run_hook(
            "bib_provenance_guard.py", {"cwd": raw, "tool_input": {"command": full_move}}
        )
        check("complete BibTeX move can be attested", rc == 0 and not out)
        duplicate_bib = "% rs-provenance: key=first2025x id=arXiv:2500.00001 tool=t date=2026-08-03\n@article{first2025x, title={One}}\n@article{first2025x, title={Two}}\n"
        rc, out, _err = run_hook(
            "bib_provenance_guard.py",
            {"cwd": raw, "tool_input": {"path": str(bib), "content": duplicate_bib}},
        )
        check(
            "two BibTeX entries with one attestation fail",
            rc == 0 and decision(out) == "deny",
        )

    for name in (
        "bib_provenance_guard.py",
        "absence_claim_guard.py",
        "survey_staleness.py",
        "stop_survey_peer.py",
    ):
        rc, out, _err = run_hook(name, "{not json")
        check(
            f"{name} fails open on malformed input", rc == 0 and decision(out) == "silent"
        )


# --------------------------------------------------------------------------- installer and host adapters


def test_installer() -> None:
    print("\ninstaller and host adapters")
    from ai_research_skills import hook_adapters, hosts, installer

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".codex").mkdir()
        (root / ".cursor").mkdir()
        (root / ".codex" / "hooks.json").write_text(
            json.dumps(
                {
                    "description": "foreign description",
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Other",
                                "hooks": [
                                    {"type": "command", "command": "mine.py", "timeout": 1}
                                ],
                                "foreign_key": "keep",
                            }
                        ]
                    },
                }
            )
        )
        result = subprocess.run(
            [sys.executable, str(INSTALL), str(root), "--host", "codex,cursor"],
            text=True,
            capture_output=True,
        )
        check(
            "multi-host install succeeds",
            result.returncode == 0,
            result.stdout + result.stderr,
        )
        codex = json.loads((root / ".codex" / "hooks.json").read_text())
        check(
            "Codex has official top-level hooks object",
            isinstance(codex.get("hooks"), dict)
            and "PreToolUse" not in codex
            and codex.get("description") == "foreign description",
        )
        check(
            "Codex preserves foreign group and unknown key",
            codex["hooks"]["PreToolUse"][0]["foreign_key"] == "keep"
            and codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "mine.py",
        )
        codex_commands = [
            handler["command"]
            for entries in codex["hooks"].values()
            for group in entries
            for handler in group.get("hooks", [])
        ]
        check(
            "non-Claude hook command is absolute and profiles host",
            bool(codex_commands)
            and all(
                str(root) in command and "--host codex" in command
                for command in codex_commands
                if any(script in command for script in installer.HOOK_SCRIPTS)
            ),
        )
        check(
            "Codex absence guard is PreToolUse only",
            any("absence_claim_guard.py" in command for command in codex_commands)
            and not any(
                "absence_claim_guard.py" in handler.get("command", "")
                for handler in codex["hooks"].get("PostToolUse", [])
            ),
        )
        cursor = json.loads((root / ".cursor" / "hooks.json").read_text())
        check(
            "Cursor has version and camelCase preToolUse",
            cursor.get("version") == 1 and "preToolUse" in cursor["hooks"],
        )
        check(
            "Cursor uses direct native entries",
            all(
                "hooks" not in entry
                and set(entry).issubset({"command", "matcher", "timeout"})
                for entry in cursor["hooks"]["preToolUse"]
            ),
        )
        check(
            "Cursor hook commands are absolute and profile-selected",
            all(
                str(root) in entry.get("command", "")
                and "--host cursor" in entry.get("command", "")
                for entries in cursor["hooks"].values()
                for entry in entries
                if any(
                    script in entry.get("command", "") for script in installer.HOOK_SCRIPTS
                )
            ),
        )
        check(
            "Cursor absence guard is preToolUse",
            any(
                "absence_claim_guard.py" in entry["command"]
                for entry in cursor["hooks"]["preToolUse"]
            ),
        )
        check(
            "Cursor stop advisory is explicitly omitted",
            not any(
                "stop_survey_peer.py" in json.dumps(entry)
                for entries in cursor["hooks"].values()
                for entry in entries
            )
            and not (root / ".cursor" / "hooks" / "stop_survey_peer.py").exists(),
        )
        check(
            "adapter validates actual host shape",
            not hook_adapters.validate_config(cursor, hosts.lookup("cursor")),
        )
        cursor_without_version = dict(cursor)
        cursor_without_version.pop("version", None)
        check(
            "Cursor missing version uses default 1",
            not hook_adapters.validate_config(
                cursor_without_version, hosts.lookup("cursor")
            ),
        )

        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        (root / ".claude" / "skills" / "ars-survey").mkdir(parents=True)
        conflict = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        conflict.write_text("foreign")
        before_conflict = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        result = subprocess.run(
            [sys.executable, str(INSTALL), str(root), "--host", "claude"],
            text=True,
            capture_output=True,
        )
        after_conflict = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        check("same-name conflict fails", result.returncode != 0)
        check("same-name conflict is zero-write", before_conflict == after_conflict)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        settings = {
            "description": "keep",
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {"type": "command", "command": "mine.py", "timeout": 1},
                            {
                                "type": "command",
                                "command": "python3 .claude/hooks/bib_provenance_guard.py",
                                "timeout": 10,
                            },
                            {
                                "type": "command",
                                "command": hook_adapters.command_for(
                                    hosts.lookup("claude"),
                                    "bib_provenance_guard.py",
                                    str(root),
                                ),
                                "timeout": 999,
                            },
                            {
                                "type": "command",
                                "command": "echo survey_staleness.py",
                                "timeout": 1,
                            },
                            {
                                "type": "command",
                                "command": "python3 /enterprise/survey_staleness.py.backup",
                                "timeout": 1,
                            },
                            {
                                "type": "command",
                                "command": "python3 /enterprise/survey_staleness.py",
                                "timeout": 1,
                            },
                        ],
                    }
                ]
            },
        }
        (root / ".claude" / "settings.json").write_text(json.dumps(settings))
        result = subprocess.run(
            [sys.executable, str(INSTALL), str(root), "--host", "claude"],
            text=True,
            capture_output=True,
        )
        merged = json.loads((root / ".claude" / "settings.json").read_text())
        handlers = merged["hooks"]["PreToolUse"][0]["hooks"]
        check("mixed foreign group install succeeds", result.returncode == 0)
        check(
            "mixed group keeps foreign handler and matcher",
            any(h.get("command") == "mine.py" for h in handlers)
            and merged["description"] == "keep",
        )
        all_commands = json.dumps(merged)
        check(
            "foreign script-name commands are not owned by basename",
            all(
                token in all_commands
                for token in (
                    "echo survey_staleness.py",
                    "/enterprise/survey_staleness.py.backup",
                    "/enterprise/survey_staleness.py",
                )
            ),
        )
        all_handlers = [
            h
            for entries in merged["hooks"].values()
            for entry in entries
            for h in (entry.get("hooks", []) if isinstance(entry, dict) else [])
        ]
        check(
            "matching command with foreign definition is not owned",
            any(
                h.get("command")
                == hook_adapters.command_for(
                    hosts.lookup("claude"), "bib_provenance_guard.py", str(root)
                )
                and h.get("timeout") == 999
                for h in all_handlers
            ),
        )
        check(
            "mixed group replaces only our handler",
            # The exact historical command in this incomplete no-manifest
            # config is foreign until the full legacy fingerprint is proven;
            # the new handlers are added beside it rather than claimed.
            sum("bib_provenance_guard.py" in h.get("command", "") for h in all_handlers)
            == len(installer.HOOK_SPEC[0][4]) + 2,
        )
        check(
            "reinstall is idempotent",
            subprocess.run(
                [sys.executable, str(INSTALL), str(root), "--host", "claude"],
                capture_output=True,
            ).returncode
            == 0,
        )
        manifest = root / ".ai-research-skills" / "manifest.json"
        data = json.loads(manifest.read_text())
        data["hosts"]["claude"]["files"]["tampered"] = "0" * 64
        manifest.write_text(json.dumps(data))
        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        check(
            "modified manifest rejects upgrade", installer.install(str(root), "claude") != 0
        )
        check(
            "modified manifest rejects uninstall",
            installer.uninstall(str(root), "claude") != 0,
        )
        after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        check("manifest rejection preserves files", before == after)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text("{bad")
        before = (root / ".claude" / "settings.json").read_bytes()
        check("invalid JSON install rejects", installer.install(str(root), "claude") != 0)
        check(
            "invalid JSON is zero-write",
            (root / ".claude" / "settings.json").read_bytes() == before
            and not (root / ".ai-research-skills").exists(),
        )

        real = root / "real"
        real.mkdir()
        symlink_root = root / "symlink-project"
        symlink_root.symlink_to(real, target_is_directory=True)
        check(
            "symlink target root rejects",
            installer.install(str(symlink_root), "claude") != 0,
        )
        root2 = root / "ancestor"
        root2.mkdir()
        (root2 / ".claude").symlink_to(real, target_is_directory=True)
        check("symlink ancestor rejects", installer.install(str(root2), "claude") != 0)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        legacy = root / ".claude" / "skills" / "rs-survey"
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text("unknown user asset")
        check(
            "unknown legacy asset blocks mutation with migration guidance",
            installer.install(str(root), "claude") != 0,
        )
        check(
            "unknown legacy asset is preserved",
            (legacy / "SKILL.md").read_text() == "unknown user asset"
            and not (root / ".claude" / "skills" / "ars-survey").exists(),
        )
        legacy.rename(root / ".claude" / "skills" / "legacy-survey-user")
        check(
            "uninstall remains safe after legacy refusal",
            installer.uninstall(str(root), "claude") == 0
            and installer.uninstall(str(root), "claude") == 0,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original = installer._atomic_write
        calls = {"n": 0}

        def fail_after_two(path: str, data: bytes, mode: int = 0o644) -> None:
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("injected replace fault")
            original(path, data, mode)

        installer._atomic_write = fail_after_two
        try:
            result = installer.install(str(root), "claude")
        finally:
            installer._atomic_write = original
        suite_files = list(
            (root / ".claude").rglob("*") if (root / ".claude").exists() else []
        )
        check("fault injection returns nonzero", result != 0)
        check(
            "fault injection rolls back suite and manifest",
            not suite_files
            and not (root / ".ai-research-skills" / "manifest.json").exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        check(
            "baseline install for source-byte upgrade",
            installer.install(str(root), "claude") == 0,
        )
        original_desired = installer._desired_files

        def changed_source(target_root: str, host: Any) -> dict[str, bytes]:
            desired = original_desired(target_root, host)
            key = str(pathlib.Path(target_root) / ".claude/skills/ars-survey/SKILL.md")
            desired[key] += b"\n# package source changed\n"
            return desired

        installer._desired_files = changed_source
        try:
            upgraded = installer.install(str(root), "claude")
        finally:
            installer._desired_files = original_desired
        changed_file = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        check(
            "manifest old hash permits source-byte upgrade",
            upgraded == 0
            and changed_file.read_bytes().endswith(b"# package source changed\n"),
        )

        stale = root / ".claude" / "obsolete-from-previous-package.txt"
        stale.write_text("old package")
        data = json.loads((root / ".ai-research-skills" / "manifest.json").read_text())
        data["hosts"]["claude"]["files"][".claude/obsolete-from-previous-package.txt"] = (
            installer._sha256(stale.read_bytes())
        )
        (root / ".ai-research-skills" / "manifest.json").write_text(
            json.dumps(
                installer._seal_manifest(
                    {k: v for k, v in data.items() if k != "manifest_sha256"}
                )
            )
        )
        check(
            "upgrade removes unmodified stale manifest file",
            installer.install(str(root), "claude") == 0 and not stale.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        check(
            "multi-host install for selective uninstall",
            installer.install(str(root), "claude,pi") == 0,
        )
        claude_file = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        pi_file = root / ".pi" / "skills" / "ars-survey" / "SKILL.md"
        claude_file.write_text("user claude edit")
        pi_file.write_text("user pi edit")
        check(
            "uninstall keeps modified selected host files",
            installer.uninstall(str(root), "claude") == 0
            and claude_file.read_text() == "user claude edit",
        )
        check(
            "unselected modified host does not block uninstall",
            pi_file.read_text() == "user pi edit"
            and (root / ".ai-research-skills" / "manifest.json").exists(),
        )
        check(
            "uninstall keeps modified other-host file",
            installer.uninstall(str(root), "pi") == 0
            and pi_file.read_text() == "user pi edit",
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(str(root), "claude")
        settings_path = root / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] += " --user-edit"
        settings_path.write_text(json.dumps(settings))
        check(
            "uninstall keeps modified handler and removes exact remainder",
            installer.uninstall(str(root), "claude") == 0
            and "--user-edit" in settings_path.read_text(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original_atomic = installer._atomic_write
        calls = {"n": 0}

        def interrupt_after_write(path: str, data: bytes, mode: int = 0o644) -> None:
            calls["n"] += 1
            original_atomic(path, data, mode)
            if calls["n"] == 3:
                raise KeyboardInterrupt("simulated process interruption")

        installer._atomic_write = interrupt_after_write
        interrupted = False
        try:
            installer.install(str(root), "claude")
        except KeyboardInterrupt:
            interrupted = True
        finally:
            installer._atomic_write = original_atomic
        journal = root / ".ai-research-skills" / "transaction.json"
        check(
            "interrupted transaction leaves persistent journal",
            interrupted and journal.exists(),
        )
        check(
            "new installer instance recovers journal",
            installer.install(str(root), "claude") == 0 and not journal.exists(),
        )


def test_hardening_regressions() -> None:
    """Focused adversarial cases for migration, transactions, and locking."""
    print("\nhardening regressions")
    from ai_research_skills import hook_adapters, hosts, installer

    check("release version is 0.6.0", installer.__version__ == "0.6.0")

    with tempfile.TemporaryDirectory() as raw:
        fake_root = pathlib.Path(raw)
        dist_info = fake_root / "ai_research_skills-0.5.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: ai-research-skills\nVersion: 0.5.0\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((str(fake_root), str(SRC)))
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ai_research_skills; print(ai_research_skills.__version__)",
            ],
            env=env,
            text=True,
            capture_output=True,
        )
        check(
            "source checkout ignores same-name stale distribution metadata",
            result.returncode == 0 and result.stdout.strip() == "0.6.0",
            result.stderr,
        )

    with tempfile.TemporaryDirectory() as raw:
        fake_root = pathlib.Path(raw)
        package = fake_root / "ai_research_skills"
        package.mkdir()
        (package / "__init__.py").write_text(
            (SRC / "ai_research_skills" / "__init__.py").read_text()
        )
        for version in ("0.5.0", "0.6.0"):
            dist_info = fake_root / f"ai_research_skills-{version}.dist-info"
            dist_info.mkdir()
            (dist_info / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: ai-research-skills\nVersion: {version}\n"
            )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(fake_root)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ai_research_skills; print(ai_research_skills.__version__)",
            ],
            env=env,
            text=True,
            capture_output=True,
        )
        check(
            "same-directory conflicting metadata falls back safely",
            result.returncode == 0 and result.stdout.strip() == "0.6.0",
            result.stderr,
        )

    import ai_research_skills as package_module

    bad_name_distribution = type("BadNameDistribution", (), {"metadata": {"Name": None}})()
    original_distributions = package_module.distributions
    package_module.distributions = lambda: [bad_name_distribution]
    try:
        bad_name_version = package_module._metadata_version()
    finally:
        package_module.distributions = original_distributions
    check("non-string distribution name is safe", bad_name_version is None)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".cursor").mkdir()
        settings_path = root / ".cursor" / "hooks.json"
        settings_path.write_text(json.dumps({"version": True}))
        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        install_result = installer.install(str(root), "cursor")
        after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        check(
            "Cursor boolean version rejects install with zero writes",
            install_result != 0
            and before == after
            and not (root / ".ai-research-skills").exists(),
        )
        check(
            "Cursor boolean version fails adapter validation",
            bool(hook_adapters.validate_config({"version": True}, hosts.lookup("cursor"))),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        check(
            "valid Cursor install for doctor version fixture",
            installer.install(str(root), "cursor") == 0,
        )
        settings_path = root / ".cursor" / "hooks.json"
        settings = json.loads(settings_path.read_text())
        settings["version"] = True
        settings_path.write_text(json.dumps(settings))
        check(
            "Cursor boolean version fails doctor",
            installer.doctor(str(root), "cursor") != 0,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        settings_path = root / ".claude" / "settings.json"
        foreign = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'python3 ".claude/hooks/bib_provenance_guard.py"',
                                "timeout": 10,
                            }
                        ],
                        "foreign_key": "leave-me",
                    }
                ]
            },
            "description": "foreign",
        }
        settings_path.write_text(json.dumps(foreign, separators=(",", ":")))
        before = settings_path.read_bytes()
        check(
            "incomplete no-manifest historical command is uninstall no-op",
            installer.uninstall(str(root), "claude") == 0
            and settings_path.read_bytes() == before,
        )
        check(
            "incomplete no-manifest install preserves exact foreign handler",
            installer.install(str(root), "claude") == 0
            and any(
                handler.get("command") == 'python3 ".claude/hooks/bib_provenance_guard.py"'
                for group in json.loads(settings_path.read_text())["hooks"]["PreToolUse"]
                for handler in group.get("hooks", [])
            ),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        command = hook_adapters.command_for(
            hosts.lookup("claude"), "bib_provenance_guard.py", str(root)
        )
        settings_path = root / ".claude" / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write|Edit",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": command,
                                        "timeout": 999,
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )
        check(
            "same-command foreign handler initial install survives",
            installer.install(str(root), "claude") == 0,
        )
        manifest = json.loads((root / ".ai-research-skills" / "manifest.json").read_text())
        owned = manifest["hosts"]["claude"]["handlers"]
        check(
            "same-command foreign handler is not manifest-owned",
            not any(record.get("timeout") == 999 for record in owned),
        )
        check(
            "same-command foreign handler survives reinstall",
            installer.install(str(root), "claude") == 0
            and any(
                handler.get("command") == command and handler.get("timeout") == 999
                for group in json.loads(settings_path.read_text())["hooks"]["PreToolUse"]
                for handler in group.get("hooks", [])
            ),
        )
        check(
            "same-command foreign handler survives uninstall",
            installer.uninstall(str(root), "claude") == 0
            and any(
                handler.get("command") == command and handler.get("timeout") == 999
                for group in json.loads(settings_path.read_text())["hooks"]["PreToolUse"]
                for handler in group.get("hooks", [])
            ),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        host = hosts.lookup("cursor")
        assert host is not None
        desired = installer._desired_files(str(root), host)
        for path, data in desired.items():
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_bytes(data)
        stale = root / ".cursor" / "hooks" / "stop_survey_peer.py"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes((pathlib.Path(installer.SRC_HOOKS) / stale.name).read_bytes())
        legacy_files = {
            installer._relative(str(root), path): installer._sha256(data)
            for path, data in desired.items()
        }
        legacy_files[".cursor/hooks/stop_survey_peer.py"] = installer._sha256(
            stale.read_bytes()
        )

        def old_handler(script: str, timeout: int) -> dict[str, Any]:
            return {
                "type": "command",
                "command": f'python3 ".cursor/hooks/{script}"',
                "timeout": timeout,
            }

        settings = {
            "version": 1,
            "hooks": {
                "preToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [old_handler("bib_provenance_guard.py", 10)],
                        "unknown_group": "preserve",
                    }
                ],
                "postToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            old_handler("absence_claim_guard.py", 10),
                            {"type": "command", "command": "foreign.py", "timeout": 1},
                        ],
                    }
                ],
                "sessionStart": [{"hooks": [old_handler("survey_staleness.py", 10)]}],
                "stop": [{"hooks": [old_handler("stop_survey_peer.py", 15)]}],
            },
            "foreign_top": True,
        }
        settings_path = root / ".cursor" / "hooks.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings))
        fingerprint = {
            "format": 1,
            "package": "ai-research-skills",
            "version": "0.5.0",
            "hosts": {
                "cursor": {
                    "files": legacy_files,
                    "handler_commands": [
                        f'python3 ".cursor/hooks/{script}"'
                        for script in (
                            "bib_provenance_guard.py",
                            "absence_claim_guard.py",
                            "survey_staleness.py",
                            "stop_survey_peer.py",
                        )
                    ],
                }
            },
        }
        old_loader = installer._load_legacy_fingerprint
        installer._load_legacy_fingerprint = lambda: fingerprint
        try:
            check(
                "complete Cursor v0.5 fingerprint/layout is adopted",
                installer._legacy_adoption(str(root), host, settings)[0],
            )
            upgraded = installer.install(str(root), "cursor")
            migrated = json.loads(settings_path.read_text())
            event_entries = [
                entry
                for event, entries in migrated["hooks"].items()
                if event in {"preToolUse", "postToolUse", "sessionStart"}
                for entry in entries
            ]
            manifest = json.loads(
                (root / ".ai-research-skills" / "manifest.json").read_text()
            )
            manifest_files = manifest["hosts"]["cursor"]["files"]
            check(
                "Cursor migration writes native direct entries and removes old Stop",
                upgraded == 0
                and all("hooks" not in entry for entry in event_entries)
                and not stale.exists()
                and not any(
                    "stop_survey_peer.py" in json.dumps(entry)
                    for entry in migrated["hooks"].get("stop", [])
                ),
            )
            check(
                "Cursor migration retains foreign handler/unknown keys",
                "foreign.py" in json.dumps(migrated)
                and migrated.get("foreign_top") is True
                and "unknown_group" in json.dumps(migrated),
            )
            check(
                "Cursor manifest retains all desired assets without stale Stop",
                all(
                    path in manifest_files
                    for path in legacy_files
                    if path != stale.relative_to(root).as_posix()
                )
                and stale.relative_to(root).as_posix() not in manifest_files,
            )
            check(
                "migrated Cursor install passes doctor",
                installer.doctor(str(root), "cursor") == 0,
            )
            check(
                "migrated Cursor uninstall preserves foreign config",
                installer.uninstall(str(root), "cursor") == 0
                and "foreign.py" in settings_path.read_text(),
            )
        finally:
            installer._load_legacy_fingerprint = old_loader

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / "snapshot.txt"
        target.write_text("before")
        _ = installer._Transaction(str(root), [str(target)])
        target.write_text("after")
        original_atomic = installer._atomic_write
        failed_once = {"value": False}

        def fail_restore(path: str, data: bytes, mode: int = 0o644) -> None:
            if not failed_once["value"]:
                failed_once["value"] = True
                raise OSError("injected restore failure")
            original_atomic(path, data, mode)

        installer._atomic_write = fail_restore
        try:
            try:
                installer._recover_journal(str(root))
            except installer.InstallerError as exc:
                first_recovery_error = str(exc)
            else:
                first_recovery_error = ""
        finally:
            installer._atomic_write = original_atomic
        journal = root / ".ai-research-skills" / "transaction.json"
        check(
            "failed snapshot recovery reports error and retains journal",
            bool(first_recovery_error)
            and "sealed journal retained" in first_recovery_error
            and journal.exists(),
        )
        installer._recover_journal(str(root))
        check(
            "next recovery restores snapshot and seals completion",
            target.read_text() == "before" and not journal.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / "atomic.txt"
        original_open = installer.os.open
        original_fsync = installer.os.fsync

        def unsupported_open(path: str | bytes, flags: int, mode: int = 0o777) -> int:
            if os.path.isdir(path):
                raise OSError("directory open unsupported")
            return original_open(path, flags, mode)

        def unsupported_fsync(fd: int) -> None:
            if installer.stat.S_ISDIR(installer.os.fstat(fd).st_mode):
                raise OSError("directory fsync unsupported")
            original_fsync(fd)

        try:
            for kind in ("open", "fsync"):
                target.write_bytes(b"before")
                installer.os.open = unsupported_open if kind == "open" else original_open
                installer.os.fsync = (
                    unsupported_fsync if kind == "fsync" else original_fsync
                )
                try:
                    installer._atomic_write(str(target), b"after")
                    installer._Transaction(str(root), [str(root / "transaction-target")])
                    installer._recover_journal(str(root))
                    durable_result = (
                        target.read_bytes() == b"after"
                        and not (root / ".ai-research-skills" / "transaction.json").exists()
                    )
                except Exception:
                    durable_result = False
                check(
                    f"directory {kind} sync failure does not wedge transaction",
                    durable_result,
                )
        finally:
            installer.os.open = original_open
            installer.os.fsync = original_fsync

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original_stat = installer.os.stat
        fake_stat = type("FakeStat", (), {"st_dev": 7, "st_ino": 11})()
        installer.os.stat = lambda _path: fake_stat
        try:
            existing_one = installer._project_root_identity(str(root / "Project"))
            existing_two = installer._project_root_identity(str(root / "project"))
            lock_one = installer._ProjectLock(str(root / "Project")).path
            lock_two = installer._ProjectLock(str(root / "project")).path
        finally:
            installer.os.stat = original_stat
        check(
            "existing case aliases share filesystem project lock identity",
            existing_one == existing_two and lock_one == lock_two,
        )

        installer.os.stat = lambda _path: (_ for _ in ()).throw(FileNotFoundError())
        try:
            missing_one = installer._project_path_identity(str(root / "MissingProject"))
            missing_two = installer._project_path_identity(str(root / "missingproject"))
            missing_lock_one = installer._project_path_lock(
                str(root / "MissingProject")
            ).path
            missing_lock_two = installer._project_path_lock(
                str(root / "missingproject")
            ).path
        finally:
            installer.os.stat = original_stat
        check(
            "missing case aliases share conservative path lock identity",
            missing_one == missing_two
            and missing_lock_one == missing_lock_two
            and missing_one.startswith("path:"),
        )

        lock_code = (
            "import sys\n"
            f"sys.path.insert(0, {str(SRC)!r})\n"
            "from ai_research_skills import installer\n"
            f"print(installer._ProjectLock({str(root / 'process-project')!r}).path)\n"
        )
        if os.name == "nt":
            check("POSIX lock path ignores per-process TMPDIR", True)
        else:
            with (
                tempfile.TemporaryDirectory() as tmp_one,
                tempfile.TemporaryDirectory() as tmp_two,
            ):
                lock_outputs: list[str] = []
                lock_smoke_ok = True
                for tmpdir in (tmp_one, tmp_two):
                    lock_env = dict(os.environ)
                    lock_env["TMPDIR"] = tmpdir
                    lock_env["PYTHONPATH"] = str(SRC)
                    lock_process = subprocess.run(
                        [sys.executable, "-c", lock_code],
                        env=lock_env,
                        capture_output=True,
                        text=True,
                    )
                    lock_smoke_ok = lock_smoke_ok and lock_process.returncode == 0
                    lock_outputs.append(lock_process.stdout.strip())
                check(
                    "different TMPDIR processes share one stable lock path",
                    lock_smoke_ok
                    and len(lock_outputs) == 2
                    and lock_outputs[0] == lock_outputs[1],
                )

        stable_root = root / "StableProject"
        path_before = installer._project_path_lock(str(stable_root))
        stable_root.mkdir()
        path_after = installer._project_path_lock(str(stable_root))
        inode_lock = installer._project_lock(str(stable_root))
        check(
            "stable path lock survives root creation before inode lock",
            path_before.identity == path_after.identity
            and path_before.path == path_after.path
            and path_before.identity.startswith("path:")
            and inode_lock.identity.startswith("stat:"),
        )

    with tempfile.TemporaryDirectory() as raw:
        # Start with a genuinely absent root.  One waiter constructs the path lock
        # before creation; a second operation constructs the inode lock after creation.
        root = pathlib.Path(raw) / "missing-project"
        ensuring = threading.Event()
        allow_create = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        calls: list[str] = []
        results: list[int] = []
        original_ensure = installer._ensure_install_root
        original_recover = installer._recover_journal
        original_project_lock = installer._project_lock
        original_project_path_lock = installer._project_path_lock
        stale_constructed = threading.Event()
        stale_identities: list[str] = []
        path_attempted = threading.Event()
        inode_attempted = threading.Event()

        def blocked_ensure(project_root: str) -> bool:
            ensuring.set()
            allow_create.wait(2)
            return original_ensure(project_root)

        def blocked_recover(project_root: str) -> None:
            calls.append(project_root)
            if len(calls) == 1:
                entered.set()
                release.wait(2)

        class ObservedLock:
            def __init__(self, lock: Any, on_enter: Any) -> None:
                self.lock = lock
                self.identity = lock.identity
                self.on_enter = on_enter

            def __enter__(self) -> Any:
                self.on_enter()
                return self.lock.__enter__()

            def __exit__(self, *args: Any) -> Any:
                return self.lock.__exit__(*args)

        def tracked_project_path_lock(project_root: str) -> Any:
            lock = original_project_path_lock(project_root)
            name = threading.current_thread().name
            if name == "stale-waiter":
                stale_identities.append(lock.identity)
                stale_constructed.set()
            if name == "inode-waiter":
                return ObservedLock(lock, path_attempted.set)
            return lock

        def tracked_project_lock(project_root: str) -> Any:
            lock = original_project_lock(project_root)
            if threading.current_thread().name == "inode-waiter":
                return ObservedLock(lock, inode_attempted.set)
            return lock

        def run_install(host: str) -> None:
            results.append(installer.install(str(root), host))

        installer._ensure_install_root = blocked_ensure
        installer._recover_journal = blocked_recover
        installer._project_path_lock = tracked_project_path_lock
        installer._project_lock = tracked_project_lock
        try:
            first = threading.Thread(target=run_install, args=("claude",), name="creator")
            stale_waiter = threading.Thread(
                target=run_install, args=("pi",), name="stale-waiter"
            )
            first.start()
            check(
                "missing-root first operation reaches root creation",
                ensuring.wait(1),
            )
            stale_waiter.start()
            check(
                "stale waiter constructs path identity before root creation",
                stale_constructed.wait(1)
                and bool(stale_identities)
                and stale_identities[0].startswith("path:")
                and not root.exists(),
            )
            allow_create.set()
            check(
                "missing-root first operation enters critical section",
                entered.wait(2),
            )
            second = threading.Thread(
                target=run_install, args=("cursor",), name="inode-waiter"
            )
            second.start()
            check(
                "path-lock waiter attempts lock during first critical section",
                path_attempted.wait(1) and len(calls) == 1,
            )
            release.set()
            first.join(10)
            stale_waiter.join(10)
            second.join(10)
            check(
                "path-lock waiter acquires inode lock after promotion",
                inode_attempted.is_set(),
            )
        finally:
            release.set()
            allow_create.set()
            installer._ensure_install_root = original_ensure
            installer._recover_journal = original_recover
            installer._project_path_lock = original_project_path_lock
            installer._project_lock = original_project_lock
        check(
            "missing-root concurrent installs retain every manifest record",
            len(results) == 3
            and all(result == 0 for result in results)
            and set(
                json.loads((root / ".ai-research-skills" / "manifest.json").read_text())[
                    "hosts"
                ]
            )
            == {"claude", "pi", "cursor"},
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw) / "exception-project"
        creator_ensuring = threading.Event()
        allow_create = threading.Event()
        failure_entered = threading.Event()
        release_failure = threading.Event()
        waiter_constructed = threading.Event()
        waiter_checked = threading.Event()
        waiter_saw_missing: list[bool] = []
        waiter_identities: list[str] = []
        exception_results: dict[str, int] = {}
        original_ensure = installer._ensure_install_root
        original_build = installer._build_plan
        original_project_path_lock = installer._project_path_lock

        def blocked_ensure(project_root: str) -> bool:
            name = threading.current_thread().name
            if name == "exception-creator":
                creator_ensuring.set()
                allow_create.wait(2)
            if name == "exception-waiter":
                waiter_saw_missing.append(not os.path.lexists(project_root))
                waiter_checked.set()
            return original_ensure(project_root)

        def failing_build(
            project_root: str, selected: tuple[Any, ...], uninstall: bool
        ) -> dict[str, Any]:
            if threading.current_thread().name == "exception-creator":
                failure_entered.set()
                release_failure.wait(2)
                raise installer.InstallerError("injected planning failure")
            return original_build(project_root, selected, uninstall)

        def tracked_project_path_lock(project_root: str) -> Any:
            lock = original_project_path_lock(project_root)
            if threading.current_thread().name == "exception-waiter":
                waiter_identities.append(lock.identity)
                waiter_constructed.set()
            return lock

        def run_creator() -> None:
            exception_results["creator"] = installer.install(str(root), "claude")

        def run_waiter() -> None:
            exception_results["waiter"] = installer.install(str(root), "pi")

        installer._ensure_install_root = blocked_ensure
        installer._build_plan = failing_build
        installer._project_path_lock = tracked_project_path_lock
        try:
            creator = threading.Thread(target=run_creator, name="exception-creator")
            waiter = threading.Thread(target=run_waiter, name="exception-waiter")
            creator.start()
            check("exception creator reaches root creation", creator_ensuring.wait(1))
            waiter.start()
            check(
                "exception waiter constructs path identity before creation",
                waiter_constructed.wait(1)
                and bool(waiter_identities)
                and waiter_identities[0].startswith("path:")
                and not root.exists(),
            )
            allow_create.set()
            check("exception creator reaches injected failure", failure_entered.wait(2))
            release_failure.set()
            creator.join(10)
            waiter.join(10)
        finally:
            allow_create.set()
            release_failure.set()
            installer._ensure_install_root = original_ensure
            installer._build_plan = original_build
            installer._project_path_lock = original_project_path_lock
        check(
            "exception cleanup happens before waiter creates root",
            exception_results.get("creator") == 1
            and exception_results.get("waiter") == 0
            and waiter_checked.is_set()
            and waiter_saw_missing == [True]
            and (root / ".ai-research-skills" / "manifest.json").exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw) / "three-thread-project"
        host = hosts.lookup("claude")
        if host is None:
            raise AssertionError("claude host is unavailable")
        thread_host = host
        creator_ensuring = threading.Event()
        allow_create = threading.Event()
        root_created = threading.Event()
        failure_entered = threading.Event()
        release_failure = threading.Event()
        remover_constructed = threading.Event()
        remover_entered = threading.Event()
        writer_constructed = threading.Event()
        writer_attempted = threading.Event()
        cleanup_done = threading.Event()
        remover_cleanup_at_entry: list[bool] = []
        remover_root_at_entry: list[bool] = []
        thread_results: dict[str, Any] = {}
        original_ensure = installer._ensure_install_root
        original_build = installer._build_plan
        original_path_lock = installer._project_path_lock
        original_rmdir = installer.os.rmdir

        class ObservedPathLock:
            def __init__(self, lock: Any, *, before: Any = None, after: Any = None) -> None:
                self.lock = lock
                self.identity = lock.identity
                self.before = before
                self.after = after

            def __enter__(self) -> Any:
                if self.before is not None:
                    self.before()
                entered = self.lock.__enter__()
                if self.after is not None:
                    self.after()
                return entered

            def __exit__(self, *args: Any) -> Any:
                return self.lock.__exit__(*args)

        def blocked_ensure(project_root: str) -> bool:
            if threading.current_thread().name == "three-thread-creator":
                creator_ensuring.set()
                allow_create.wait(2)
            created = original_ensure(project_root)
            if threading.current_thread().name == "three-thread-creator" and created:
                root_created.set()
            return created

        def failing_build(
            project_root: str, selected: tuple[Any, ...], uninstall: bool
        ) -> dict[str, Any]:
            if threading.current_thread().name == "three-thread-creator":
                failure_entered.set()
                release_failure.wait(2)
                raise installer.InstallerError("injected three-thread planning failure")
            return original_build(project_root, selected, uninstall)

        def tracked_path_lock(project_root: str) -> Any:
            lock = original_path_lock(project_root)
            name = threading.current_thread().name
            if name == "three-thread-remover":
                remover_constructed.set()
                return ObservedPathLock(
                    lock,
                    after=lambda: (
                        remover_cleanup_at_entry.append(cleanup_done.is_set()),
                        remover_root_at_entry.append(os.path.lexists(project_root)),
                        remover_entered.set(),
                    ),
                )
            if name == "three-thread-writer":
                writer_constructed.set()
                return ObservedPathLock(lock, before=writer_attempted.set)
            return lock

        def tracked_rmdir(path: str) -> None:
            original_rmdir(path)
            if os.path.abspath(path) == os.path.abspath(root):
                cleanup_done.set()

        def run_creator() -> None:
            thread_results["creator"] = installer.install(str(root), "claude")

        def run_writer() -> None:
            try:
                thread_results["writer"] = installer.install_files(str(root), thread_host)
            except BaseException as exc:
                thread_results["writer_error"] = repr(exc)

        def run_remover() -> None:
            try:
                installer.remove_files(str(root), thread_host)
                thread_results["remover"] = None
            except BaseException as exc:
                thread_results["remover_error"] = repr(exc)

        creator = threading.Thread(target=run_creator, name="three-thread-creator")
        remover = threading.Thread(target=run_remover, name="three-thread-remover")
        writer = threading.Thread(target=run_writer, name="three-thread-writer")
        installer._ensure_install_root = blocked_ensure
        installer._build_plan = failing_build
        installer._project_path_lock = tracked_path_lock
        installer.os.rmdir = tracked_rmdir
        try:
            creator.start()
            check(
                "three-thread creator reaches pre-create ensure",
                creator_ensuring.wait(1),
            )
            remover.start()
            check(
                "stale remove_files constructs stable path lock before creation",
                remover_constructed.wait(1) and not root.exists(),
            )
            allow_create.set()
            check("three-thread creator creates root", root_created.wait(2))
            writer.start()
            check(
                "post-create install_files attempts stable path lock",
                writer_constructed.wait(1) and writer_attempted.wait(1),
            )
            check(
                "remover cannot enter while creator body is blocked",
                failure_entered.wait(2) and not remover_entered.is_set(),
            )
            release_failure.set()
            creator.join(10)
            writer.join(10)
            remover.join(10)
            check(
                "remover entered only after creator cleanup",
                remover_entered.wait(2)
                and cleanup_done.is_set()
                and remover_cleanup_at_entry == [True],
            )
        finally:
            allow_create.set()
            release_failure.set()
            creator.join(10)
            writer.join(10)
            remover.join(10)
            installer._ensure_install_root = original_ensure
            installer._build_plan = original_build
            installer._project_path_lock = original_path_lock
            installer.os.rmdir = original_rmdir
        check(
            "three-thread lock protocol preserves creator/writer/remover outcomes",
            thread_results.get("creator") == 1
            and thread_results.get("writer_error") is None
            and thread_results.get("remover_error") is None
            and cleanup_done.is_set()
            and len(remover_root_at_entry) == 1,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw) / "compatibility-project"
        host = hosts.lookup("claude")
        if host is None:
            raise AssertionError("claude host is unavailable")
        thread_host = host
        creator_ensuring = threading.Event()
        allow_create = threading.Event()
        helper_constructed = threading.Event()
        helper_path_identities: list[str] = []
        helper_inode_identities: list[str] = []
        creator_result: list[int] = []
        helper_result: list[list[str]] = []
        original_ensure = installer._ensure_install_root
        original_project_path_lock = installer._project_path_lock
        original_project_lock = installer._project_lock

        def blocked_ensure(project_root: str) -> bool:
            if threading.current_thread().name == "compatibility-creator":
                creator_ensuring.set()
                allow_create.wait(2)
            return original_ensure(project_root)

        def tracked_project_path_lock(project_root: str) -> Any:
            lock = original_project_path_lock(project_root)
            if threading.current_thread().name == "compatibility-helper":
                helper_path_identities.append(lock.identity)
                helper_constructed.set()
            return lock

        def tracked_project_lock(project_root: str) -> Any:
            lock = original_project_lock(project_root)
            if threading.current_thread().name == "compatibility-helper":
                helper_inode_identities.append(lock.identity)
            return lock

        def run_creator() -> None:
            creator_result.append(installer.install(str(root), "claude"))

        def run_helper() -> None:
            helper_result.append(installer.install_files(str(root), thread_host))

        installer._ensure_install_root = blocked_ensure
        installer._project_path_lock = tracked_project_path_lock
        installer._project_lock = tracked_project_lock
        try:
            creator = threading.Thread(target=run_creator, name="compatibility-creator")
            helper = threading.Thread(target=run_helper, name="compatibility-helper")
            creator.start()
            check("compatibility creator reaches root creation", creator_ensuring.wait(1))
            helper.start()
            check(
                "compatibility helper constructs path identity before creation",
                helper_constructed.wait(1)
                and bool(helper_path_identities)
                and helper_path_identities[0].startswith("path:")
                and not root.exists(),
            )
            allow_create.set()
            creator.join(10)
            helper.join(10)
        finally:
            allow_create.set()
            installer._ensure_install_root = original_ensure
            installer._project_path_lock = original_project_path_lock
            installer._project_lock = original_project_lock
        check(
            "compatibility helper holds path then inode locks",
            creator_result == [0]
            and bool(helper_result)
            and bool(helper_result[0])
            and bool(helper_path_identities)
            and any(identity.startswith("stat:") for identity in helper_inode_identities),
        )
        missing = pathlib.Path(raw) / "missing-uninstall"
        check(
            "uninstall missing root does not create it",
            installer.uninstall(str(missing), "claude") == 0 and not missing.exists(),
        )
        installer.remove_files(str(missing), thread_host)
        check("remove_files missing root does not create it", not missing.exists())


def test_doctor() -> None:
    print("\ndoctor")
    from ai_research_skills import hosts, installer

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        check("doctor empty project is nonzero", installer.doctor(str(root), "claude") == 1)
        check(
            "doctor sees clean install",
            installer.install(str(root), "claude,pi") == 0
            and installer.doctor(str(root), "claude,pi") == 0,
        )
        settings_path = root / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] += " --tampered"
        settings_path.write_text(json.dumps(settings))
        check(
            "doctor detects modified managed handler",
            installer.doctor(str(root), "claude") != 0,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        marker = root / "doctor-ran-marker"
        skill = root / ".claude" / "skills" / "ars-survey"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("marker skill")
        fake = root / ".claude" / "ai-research-skills" / "scripts" / "rs_validate.py"
        fake.parent.mkdir(parents=True)
        fake.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        )
        check(
            "doctor never executes fake validator without manifest",
            installer.doctor(str(root), "claude") != 0 and not marker.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        marker = root / "doctor-ran-marker"
        check(
            "clean install remains doctor-valid",
            installer.install(str(root), "claude") == 0,
        )
        host = hosts.lookup("claude")
        assert host is not None
        malicious = root / "malicious-python"
        malicious.mkdir()
        (malicious / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        )
        saved_python_env = {
            name: os.environ.get(name)
            for name in (
                "PYTHONPATH",
                "PYTHONHOME",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
            )
        }
        try:
            os.environ["PYTHONPATH"] = str(malicious)
            os.environ["PYTHONHOME"] = str(malicious)
            os.environ["PYTHONSTARTUP"] = str(malicious / "startup.py")
            os.environ["PYTHONUSERBASE"] = str(malicious)
            trusted_ok = installer._verify_installed_validator(str(root), host)
        finally:
            for name, value in saved_python_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        check(
            "doctor trusted fallback ignores PYTHONPATH and sitecustomize",
            trusted_ok and not marker.exists(),
        )
        fake_python = root / "fake-python"
        fake_python.write_text(f"#!/bin/sh\nprintf ran > {str(marker)!r}\nexit 0\n")
        fake_python.chmod(0o755)
        original_executable = installer.sys.executable
        try:
            installer.sys.executable = str(fake_python)
            polluted_executable_ok = installer._verify_installed_validator(str(root), host)
        finally:
            installer.sys.executable = original_executable
        check(
            "doctor ignores PYTHONEXECUTABLE-polluted sys.executable",
            polluted_executable_ok and not marker.exists(),
        )
        sys_module: Any = installer.sys
        original_base_executable = getattr(sys_module, "_base_executable", None)
        had_base_executable = hasattr(sys_module, "_base_executable")

        def verify_with_base(candidate: str) -> bool:
            try:
                sys_module._base_executable = candidate
                return installer._verify_installed_validator(str(root), host)
            finally:
                if had_base_executable:
                    sys_module._base_executable = original_base_executable
                else:
                    delattr(sys_module, "_base_executable")

        echo_candidate = installer._trusted_executable("/bin/echo")
        echo_base_ok = verify_with_base("/bin/echo")
        check(
            "doctor rejects /bin/echo as an untrusted base executable",
            echo_candidate is None and echo_base_ok is False and not marker.exists(),
        )
        fake_candidate = installer._trusted_executable(str(fake_python))
        fake_base_ok = verify_with_base(str(fake_python))
        check(
            "doctor rejects a project fake executable without running it",
            fake_candidate is None and fake_base_ok is False and not marker.exists(),
        )
        no_trusted_executable_ok = verify_with_base(str(root / "missing-base-python"))
        check(
            "doctor fails closed without a trusted interpreter",
            no_trusted_executable_ok is False and not marker.exists(),
        )

        trusted_python = installer._trusted_python_executable()
        check(
            "real base interpreter passes static trust proof",
            trusted_python is not None
            and installer._trusted_executable(trusted_python) == trusted_python,
        )
        smoke_env = dict(os.environ)
        smoke_env["PYTHONEXECUTABLE"] = str(fake_python)
        smoke_env["PYTHONPATH"] = str(SRC)
        smoke_code = (
            "from ai_research_skills import hosts, installer\n"
            f"raise SystemExit(0 if installer._verify_installed_validator({str(root)!r}, "
            "hosts.lookup('claude')) else 1)\n"
        )
        smoke = (
            subprocess.run(
                [trusted_python, "-c", smoke_code],
                env=smoke_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if trusted_python is not None
            else None
        )
        check(
            "doctor subprocess smoke survives PYTHONEXECUTABLE",
            smoke is not None and smoke.returncode == 0 and not marker.exists(),
            "" if smoke is None else smoke.stdout + smoke.stderr,
        )
        validator = root / ".claude" / "ai-research-skills" / "scripts" / "rs_validate.py"
        validator.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        )
        check(
            "doctor does not execute tampered installed validator",
            installer.doctor(str(root), "claude") != 0 and not marker.exists(),
        )


# --------------------------------------------------------------------------- phase-aware validator fixtures


def _base_protocol(phase: int) -> str:
    lines = [
        "topic: demo-topic",
        'question: "Which method improves multi-hop retrieval under a fixed budget?"',
        "created: 2026-01-01",
        f"phase: {phase}",
        "scope:",
        "  in: [multi-hop QA]",
        "  out: [single-hop QA]",
        "axes:",
        "  - name: method",
        "    values: [iterative, long-context]",
        "  - name: control",
        "    values: [none, fixed recall]",
        "  - name: evaluation",
        "    values: [2-hop, 3+-hop]",
    ]
    if phase >= 1:
        lines += [
            "recall_modes:",
            "  keyword: [{tool: search, q: one}]",
            "  citation_chain: [{tool: graph, seed: W1}]",
            "  venue_author: [{tool: sweep, venue: ICLR}]",
            "  contrarian: [{tool: search, q: opposing}]",
        ]
    if phase >= 2:
        lines += [
            "screen:",
            "  include: [relevant]",
            "  exclude: [irrelevant]",
            "  relevance_threshold: 6",
        ]
    if phase >= 5:
        lines += [
            "last_searched_at: 2026-01-02",
            "saturation:",
            "  rounds: 1",
            "  new_on_topic_last_round: 0",
            "  stop_rule: no new records",
        ]
    return "\n".join(lines) + "\n"


def _write_phase(directory: pathlib.Path, phase: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "protocol.yml").write_text(_base_protocol(phase))
    if phase == 0:
        return
    record: dict[str, Any] = {
        "key": "alpha2025x",
        "id": "arXiv:2500.00001",
        "title": "A paper",
        "found_via": ["keyword:r1"],
        "relevance": 8,
        "screen": "include",
        "accessed": "2026-01-02",
    }
    if phase >= 2:
        record["contextual_summary"] = "A summary against the question."
    if phase >= 3:
        record.update(
            {
                "claim": "The method improves the benchmark under the stated control.",
                "evidence_read": "full",
                "axes": {"method": "iterative", "control": "none", "evaluation": "2-hop"},
                "code": {"status": "none"},
            }
        )
    (directory / "corpus.jsonl").write_text(json.dumps(record) + "\n")
    (directory / "log.md").write_text("keyword citation_chain venue_author contrarian\n")
    if phase >= 1:
        counts = ["counts:", "  retrieved: 1", "  deduped: 1"]
        if phase >= 2:
            counts += [
                "  adjudicated: 1",
                "  scored_at_or_above_threshold: 1",
                "  unsure: 0",
            ]
        if phase >= 3:
            counts += ["  fulltext_kept: 1"]
        with (directory / "protocol.yml").open("a") as fh:
            fh.write("\n" + "\n".join(counts) + "\n")
    if phase >= 3:
        (directory / "refs.bib").write_text(
            "% rs-provenance: key=alpha2025x id=arXiv:2500.00001 tool=arxiv.export_citations date=2026-01-02\n"
            "@article{alpha2025x, title={A paper}}\n"
        )
    if phase >= 4:
        cells: list[str] = []
        values = [
            ("iterative", "none"),
            ("iterative", "fixed recall"),
            ("long-context", "none"),
            ("long-context", "fixed recall"),
        ]
        for method, control in values:
            for evaluation in ("2-hop", "3+-hop"):
                occupied = (
                    method == "iterative" and control == "none" and evaluation == "2-hop"
                )
                gap = (
                    method == "iterative"
                    and control == "fixed recall"
                    and evaluation == "2-hop"
                )
                cells += [
                    f"  - coords: {{method: {method}, control: {control}, evaluation: {evaluation}}}",
                    f"    occupants: [{'alpha2025x' if occupied else ''}]",
                    f"    state: {'occupied' if occupied else ('unexplored' if gap else 'undecided')}",
                ]
                if gap:
                    cells.append("    trend_evidence: live neighbour")
                    cells.append("    gap_id: G1")
        (directory / "coverage.yml").write_text(
            "axes:\n  - name: method\n    values: [iterative, long-context]\n  - name: control\n    values: [none, fixed recall]\n  - name: evaluation\n    values: [2-hop, 3+-hop]\n"
            "cells:\n"
            + "\n".join(cells)
            + "\nrecall_diagnostic:\n  includes_by_mode: {keyword: 1, citation_chain: 0, venue_author: 0, contrarian: 0}\n"
        )
        (directory / "gaps.yml").write_text(
            "gaps:\n  - id: G1\n    statement: A testable missing comparison in the synthetic state.\n    type: unvalidated-comparison\n    evidence_of_absence:\n      queries_run: [one phrasing, two phrasing, three phrasing]\n      venues_swept: [ICLR@2025, ACL@2025, NeurIPS@2025]\n      nearest_prior_work:\n        - key: alpha2025x\n          why_not_it: It controls a different variable.\n          differing_axis: problem-setting\n      last_checked: 2026-01-02\n    confidence: medium\n    closes_if: A paper matches the missing controlled comparison.\n"
        )


def test_validator() -> None:
    print("\nphase-aware validator")
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        for phase in range(6):
            directory = root / f"phase{phase}"
            _write_phase(directory, phase)
            rc, out = run_validator(directory, fallback=True)
            check(f"phase {phase} minimal state is valid", rc == 0, out)
        minimal = root / "phase1-minimal"
        _write_phase(minimal, 1)
        minimal_record = json.loads((minimal / "corpus.jsonl").read_text())
        minimal_record.pop("relevance")
        minimal_record.pop("screen")
        (minimal / "corpus.jsonl").write_text(json.dumps(minimal_record) + "\n")
        rc, out = run_validator(minimal, fallback=True)
        check("Phase 1 minimal corpus contract omits Phase 2 fields", rc == 0, out)

        for label, refs in (
            ("empty", ""),
            ("directives", "@comment{note}\n% comment only\n"),
        ):
            missing_refs = root / f"phase3-missing-{label}"
            _write_phase(missing_refs, 3)
            (missing_refs / "refs.bib").write_text(refs)
            rc, out = run_validator(missing_refs, fallback=True)
            strict_rc, strict_out = run_validator(missing_refs, fallback=True, strict=True)
            check(
                f"Phase 3 {label} refs warns for missing include",
                rc == 0 and "has no BibTeX entry" in out,
                out,
            )
            check(
                f"Phase 3 {label} refs is strict-nonzero",
                strict_rc != 0 and "has no BibTeX entry" in strict_out,
                strict_out,
            )

        no_include = root / "phase3-no-include"
        _write_phase(no_include, 3)
        no_include_record = json.loads((no_include / "corpus.jsonl").read_text())
        no_include_record["screen"] = "exclude"
        no_include_record["exclude_reason"] = "synthetic control"
        (no_include / "corpus.jsonl").write_text(json.dumps(no_include_record) + "\n")
        (no_include / "protocol.yml").write_text(
            (no_include / "protocol.yml")
            .read_text()
            .replace("fulltext_kept: 1", "fulltext_kept: 0")
        )
        (no_include / "refs.bib").write_text("")
        rc, out = run_validator(no_include, fallback=True, strict=True)
        check(
            "Phase 3 refs with no includes stays clean under strict",
            rc == 0 and "has no BibTeX entry" not in out,
            out,
        )

        from ai_research_skills.assets.scripts import _yaml_subset

        quoted_yaml = "topic: 'bad''slug'\n"
        fallback_value = _yaml_subset.safe_load(quoted_yaml)
        check(
            "fallback decodes YAML doubled single quote",
            fallback_value == {"topic": "bad'slug"},
        )
        try:
            import yaml as reference_yaml
        except ImportError:
            reference_yaml = None
        if reference_yaml is not None:
            check(
                "fallback matches PyYAML doubled single quote",
                fallback_value == reference_yaml.safe_load(quoted_yaml),
            )
        malformed_quote = False
        try:
            _yaml_subset.safe_load("topic: 'bad'slug'\n")
        except _yaml_subset.YAMLSubsetError:
            malformed_quote = True
        check("fallback rejects unpaired YAML single quote", malformed_quote)

        fragment_yaml = (
            'quoted: "first # kept\n'
            '  second # kept"\n'
            "empty: ''\n"
            'flow: [one, "two, # kept", three#kept] # outside\n'
        )
        fallback_fragments = _yaml_subset.safe_load(fragment_yaml)
        check(
            "fallback keeps quoted continuation hashes and flow punctuation",
            fallback_fragments
            == {
                "quoted": "first # kept second # kept",
                "empty": "",
                "flow": ["one", "two, # kept", "three#kept"],
            },
        )
        if reference_yaml is not None:
            check(
                "fallback matches PyYAML quoted and flow fragments",
                fallback_fragments == reference_yaml.safe_load(fragment_yaml),
            )

        block_yaml = (
            "literal: |\n"
            "  first # literal\n"
            "\n"
            "  # literal content\n"
            "    nested\n"
            "folded: >\n"
            "  first # folded\n"
            "\n"
            "  # folded content\n"
            "  second\n"
        )
        fallback_blocks = _yaml_subset.safe_load(block_yaml)
        check(
            "fallback preserves literal/folded hashes, blanks, and indent",
            fallback_blocks
            == {
                "literal": "first # literal\n\n# literal content\n  nested\n",
                "folded": "first # folded\n# folded content second\n",
            },
        )
        if reference_yaml is not None:
            check(
                "fallback matches PyYAML block scalar profile",
                fallback_blocks == reference_yaml.safe_load(block_yaml),
            )
        check(
            "fallback preserves single-quoted backslash and empty scalar",
            _yaml_subset.safe_load("empty: ''\nvalue: 'a\\b # stays'\n")
            == {"empty": "", "value": "a\\b # stays"},
        )
        unclosed_double = False
        try:
            _yaml_subset.safe_load('value: "unterminated\n')
        except _yaml_subset.YAMLSubsetError:
            unclosed_double = True
        check("fallback rejects unclosed double quote", unclosed_double)

        bad_topic = root / "phase0-bad-single-quote"
        _write_phase(bad_topic, 0)
        (bad_topic / "protocol.yml").write_text(
            (bad_topic / "protocol.yml")
            .read_text()
            .replace("topic: demo-topic", "topic: 'bad''slug'")
        )
        rc, out = run_validator(bad_topic, fallback=True)
        check(
            "decoded single-quoted topic is rejected by schema",
            rc != 0 and "does not match" in out,
            out,
        )

        mismatch = root / "phase2"
        protocol = (
            (mismatch / "protocol.yml").read_text().replace("deduped: 1", "deduped: 0")
        )
        (mismatch / "protocol.yml").write_text(protocol)
        rc, out = run_validator(mismatch, fallback=True)
        check("counts mismatch is nonzero", rc != 0 and "deduped" in out)

        phase4 = root / "phase4"
        coverage = (phase4 / "coverage.yml").read_text()
        (phase4 / "coverage.yml").write_text(
            coverage.replace(
                "method: long-context, control: fixed recall, evaluation: 3+-hop",
                "method: iterative, control: none, evaluation: 2-hop",
                1,
            )
        )
        rc, out = run_validator(phase4, fallback=True)
        check(
            "coverage duplicate/missing cell is caught",
            rc != 0 and ("duplicate grid cell" in out or "missing" in out),
        )
        wrong_occupant = root / "phase4-wrong-occupant"
        _write_phase(wrong_occupant, 4)
        wrong_text = (
            (wrong_occupant / "coverage.yml")
            .read_text()
            .replace("occupants: [alpha2025x]", "occupants: [ghost2025x]", 1)
        )
        (wrong_occupant / "coverage.yml").write_text(wrong_text)
        rc, out = run_validator(wrong_occupant, fallback=True)
        check("coverage wrong occupant is caught", rc != 0 and "not an include" in out)

        abstract_only = root / "phase4-abstract-occupant"
        _write_phase(abstract_only, 4)
        abstract_record = json.loads((abstract_only / "corpus.jsonl").read_text())
        abstract_record["evidence_read"] = "abstract"
        (abstract_only / "corpus.jsonl").write_text(json.dumps(abstract_record) + "\n")
        (abstract_only / "protocol.yml").write_text(
            (abstract_only / "protocol.yml")
            .read_text()
            .replace("fulltext_kept: 1", "fulltext_kept: 0")
        )
        rc, out = run_validator(abstract_only, fallback=True)
        check(
            "abstract-only include cannot occupy coverage cell",
            rc != 0 and "abstract-only" in out and "cannot establish coverage" in out,
        )

        duplicate_queries = root / "phase4-duplicate-query-phrasings"
        _write_phase(duplicate_queries, 4)
        duplicate_query_text = (
            (duplicate_queries / "gaps.yml")
            .read_text()
            .replace(
                "[one phrasing, two phrasing, three phrasing]",
                "[Same query, same   query, SAME QUERY]",
            )
        )
        (duplicate_queries / "gaps.yml").write_text(duplicate_query_text)
        rc, out = run_validator(duplicate_queries, fallback=True)
        check(
            "validator rejects duplicate normalized query phrasings",
            rc != 0 and "only 1 distinct query" in out,
        )

        legal = root / "phase4-closure"
        _write_phase(legal, 4)
        legal_gaps = (
            (legal / "gaps.yml")
            .read_text()
            .replace(
                "    confidence: medium",
                "    closes_if_met:\n      key: alpha2025x\n      date: 2026-01-02\n      rationale: synthetic closure record\n    threats:\n      - key: alpha2025x\n        date: 2026-01-02\n        unmet_clause: control is not matched\n    confidence: medium",
            )
        )
        (legal / "gaps.yml").write_text(legal_gaps)
        (legal / "protocol.yml").write_text(
            (legal / "protocol.yml").read_text() + "last_searched_at: 2026-01-02\n"
        )
        rc, out = run_validator(legal, fallback=True)
        check("legal watch closure and threat references pass", rc == 0, out)

        revived = root / "phase4-revivable"
        _write_phase(revived, 4)
        revived_text = (
            (revived / "coverage.yml")
            .read_text()
            .replace(
                "    state: unexplored\n    trend_evidence: live neighbour\n    gap_id: G1",
                "    state: abandoned\n    trend_evidence: live neighbour\n    gap_id: G1",
                1,
            )
        )
        (revived / "coverage.yml").write_text(revived_text)
        rc, out = run_validator(revived, fallback=True)
        check(
            "abandoned promoted cell without successor is rejected",
            rc != 0 and "revivable_by" in out,
        )
        (revived / "coverage.yml").write_text(
            revived_text.replace(
                "    gap_id: G1", "    gap_id: G1\n    revivable_by: alpha2025x", 1
            )
        )
        rc, out = run_validator(revived, fallback=True)
        check("abandoned promoted cell with included successor passes", rc == 0, out)

        duplicate_modes = root / "phase4-duplicate-modes"
        _write_phase(duplicate_modes, 4)
        record = json.loads((duplicate_modes / "corpus.jsonl").read_text())
        record["found_via"].append("keyword:second-query")
        (duplicate_modes / "corpus.jsonl").write_text(json.dumps(record) + "\n")
        rc, out = run_validator(duplicate_modes, fallback=True)
        check("recall diagnostic counts each paper-mode once", rc == 0, out)

        invalid_dates = root / "invalid-dates"
        _write_phase(invalid_dates, 4)
        protocol_text = (
            (invalid_dates / "protocol.yml")
            .read_text()
            .replace("created: 2026-01-01", "created: 2026-02-31")
        )
        (invalid_dates / "protocol.yml").write_text(protocol_text)
        record = json.loads((invalid_dates / "corpus.jsonl").read_text())
        record["accessed"] = "2026-02-31"
        (invalid_dates / "corpus.jsonl").write_text(json.dumps(record) + "\n")
        invalid_gaps = (
            (invalid_dates / "gaps.yml")
            .read_text()
            .replace("last_checked: 2026-01-02", "last_checked: 2026-02-31")
        )
        (invalid_dates / "gaps.yml").write_text(invalid_gaps)
        rc_fallback, out_fallback = run_validator(invalid_dates, fallback=True)
        rc_dev, out_dev = run_validator(invalid_dates)
        check(
            "invalid calendar dates fail in fallback and development",
            rc_fallback != 0
            and rc_dev != 0
            and "traceback" not in (out_fallback + out_dev).lower(),
            out_dev,
        )

        orphan_gap = root / "phase4-orphan-gap"
        _write_phase(orphan_gap, 4)
        (orphan_gap / "coverage.yml").write_text(
            (orphan_gap / "coverage.yml").read_text().replace("    gap_id: G1\n", "", 1)
        )
        rc, out = run_validator(orphan_gap, fallback=True)
        check(
            "orphan gap is rejected",
            rc != 0 and "no legal empty promotable cell" in out,
        )

        occupied_gap = root / "phase4-occupied-gap"
        _write_phase(occupied_gap, 4)
        occupied_text = (
            (occupied_gap / "coverage.yml")
            .read_text()
            .replace(
                "    state: unexplored\n    trend_evidence: live neighbour\n    gap_id: G1",
                "    occupants: [alpha2025x]\n    state: occupied\n    gap_id: G1",
                1,
            )
        )
        (occupied_gap / "coverage.yml").write_text(occupied_text)
        rc, out = run_validator(occupied_gap, fallback=True)
        check(
            "occupied gap_id cell is rejected",
            rc != 0 and "gap_id" in out and "promotable" in out,
        )

        multi_gap = root / "phase4-multi-gap-cell"
        _write_phase(multi_gap, 4)
        multi_text = (
            (multi_gap / "coverage.yml")
            .read_text()
            .replace(
                "    state: undecided",
                "    state: unexplored\n    trend_evidence: second legal cell\n    gap_id: G1",
                1,
            )
        )
        (multi_gap / "coverage.yml").write_text(multi_text)
        rc, out = run_validator(multi_gap, fallback=True)
        check("one gap may reference multiple legal cells", rc == 0, out)

        low_include = root / "phase2-low-include"
        _write_phase(low_include, 2)
        low_record = json.loads((low_include / "corpus.jsonl").read_text())
        low_record["relevance"] = 5
        (low_include / "corpus.jsonl").write_text(json.dumps(low_record) + "\n")
        (low_include / "protocol.yml").write_text(
            (low_include / "protocol.yml")
            .read_text()
            .replace("scored_at_or_above_threshold: 1", "scored_at_or_above_threshold: 0")
        )
        rc, out = run_validator(low_include, fallback=True)
        check(
            "low relevance include is rejected",
            rc != 0 and "screen=include relevance" in out,
        )

        high_exclude = root / "phase2-high-exclude"
        _write_phase(high_exclude, 2)
        high_record = json.loads((high_exclude / "corpus.jsonl").read_text())
        high_record.update(
            {"relevance": 10, "screen": "exclude", "exclude_reason": "out of scope"}
        )
        (high_exclude / "corpus.jsonl").write_text(json.dumps(high_record) + "\n")
        rc, out = run_validator(high_exclude, fallback=True)
        check("high relevance exclude remains allowed", rc == 0, out)

        future_dates = root / "phase5-future-dates"
        _write_phase(future_dates, 5)
        (future_dates / "protocol.yml").write_text(
            (future_dates / "protocol.yml")
            .read_text()
            .replace("created: 2026-01-01", "created: 2099-01-01")
            .replace("last_searched_at: 2026-01-02", "last_searched_at: 2099-01-02")
        )
        future_record = json.loads((future_dates / "corpus.jsonl").read_text())
        future_record["accessed"] = "2099-01-02"
        (future_dates / "corpus.jsonl").write_text(json.dumps(future_record) + "\n")
        future_gap = (
            (future_dates / "gaps.yml")
            .read_text()
            .replace("last_checked: 2026-01-02", "last_checked: 2099-01-03")
        )
        (future_dates / "gaps.yml").write_text(future_gap)
        rc, out = run_validator(future_dates, fallback=True)
        check(
            "future and out-of-order protocol/corpus/gap dates fail",
            rc != 0
            and "cannot be in the future" in out
            and "accessed cannot be in the future" in out,
        )

        watch_order = root / "phase5-watch-date-order"
        _write_phase(watch_order, 5)
        watch_gap = (
            (watch_order / "gaps.yml")
            .read_text()
            .replace(
                "    confidence: medium",
                "    closes_if_met:\n      key: alpha2025x\n      date: 2026-01-02\n      rationale: closure\n    threats:\n      - key: alpha2025x\n        date: 2026-01-02\n        unmet_clause: still open\n    confidence: medium",
            )
        )
        (watch_order / "gaps.yml").write_text(watch_gap)
        (watch_order / "protocol.yml").write_text(
            (watch_order / "protocol.yml")
            .read_text()
            .replace("last_searched_at: 2026-01-02", "last_searched_at: 2026-01-01")
        )
        rc, out = run_validator(watch_order, fallback=True)
        check(
            "watch closure/threat dates cannot outrun last search",
            rc != 0 and "after protocol.last_searched_at" in out,
        )

        duplicate_refs = root / "phase3-duplicate-refs"
        _write_phase(duplicate_refs, 3)
        (duplicate_refs / "refs.bib").write_text(
            "% rs-provenance: key=alpha2025x id=arXiv:2500.00001 tool=t date=2026-01-02\n"
            "@article{alpha2025x, title={A}}\n@article{alpha2025x, title={B}}\n"
        )
        rc, out = run_validator(duplicate_refs, fallback=True)
        check(
            "validator rejects duplicate BibTeX key with one attestation",
            rc != 0 and "duplicate citation key" in out,
        )

        parenthesized_refs = root / "phase3-parenthesized-refs"
        _write_phase(parenthesized_refs, 3)
        (parenthesized_refs / "refs.bib").write_text(
            "@article(alpha2025x, title={Unattested})\n"
        )
        rc, out = run_validator(parenthesized_refs, fallback=True)
        check(
            "validator recognizes parenthesized BibTeX entries",
            rc != 0 and "lacks a strict per-entry" in out,
        )

        directives_refs = root / "phase3-directives-refs"
        _write_phase(directives_refs, 3)
        (directives_refs / "refs.bib").write_text(
            "@STRING{venue = {Example}}\n"
            '@PREAMBLE("generated")\n'
            "@COMMENT{directive is not a citation}\n"
            "% rs-provenance: key=alpha2025x id=arXiv:2500.00001 tool=t date=2026-01-02\n"
            "@ARTICLE(alpha2025x, title={A paper})\n"
        )
        rc, out = run_validator(directives_refs, fallback=True)
        check(
            "validator ignores BibTeX directives case-insensitively",
            rc == 0,
            out,
        )

        from ai_research_skills.assets.scripts import _schema_subset, _yaml_subset

        try:
            _schema_subset.iter_errors({}, {"type": "object", "unknown_keyword": True})
            unknown_schema = False
        except _schema_subset.SchemaSubsetError:
            unknown_schema = True
        check("schema fallback rejects unknown keywords", unknown_schema)
        map_text = (
            ASSETS / "skills" / "ars-survey" / "references" / "04-map.md"
        ).read_text()
        yaml_block = map_text.split("```yaml\n", 3)[3].split("```", 1)[0]
        fallback_map = _yaml_subset.safe_load(yaml_block)
        check(
            "fallback parses documented multiline flow YAML",
            isinstance(fallback_map, dict)
            and fallback_map.get("gaps", [{}])[0]
            .get("evidence_of_absence", {})
            .get("nearest_prior_work"),
        )
        try:
            import yaml as dev_yaml
        except ImportError:
            dev_yaml = None
        if dev_yaml is not None:
            dev_map = dev_yaml.safe_load(yaml_block)
            check(
                "fallback and PyYAML agree on documented map shape",
                fallback_map["gaps"][0]["statement"] == dev_map["gaps"][0]["statement"]
                and len(fallback_map["gaps"][0]["evidence_of_absence"]["queries_run"])
                == len(dev_map["gaps"][0]["evidence_of_absence"]["queries_run"]),
            )
        colon_scalar = (
            "citation_chains:\n  - W123:cites:1\n  - https://example.test/work:detail\n"
        )
        fallback_colons = _yaml_subset.safe_load(colon_scalar)
        check(
            "fallback keeps colon-bearing block-list scalars as strings",
            fallback_colons
            == {"citation_chains": ["W123:cites:1", "https://example.test/work:detail"]},
        )
        if dev_yaml is not None:
            check(
                "fallback and PyYAML agree on colon-bearing scalars",
                fallback_colons == dev_yaml.safe_load(colon_scalar),
            )
        bad = legal_gaps.replace(
            "closes_if_met:\n      key: alpha2025x",
            "closes_if_met:\n      key: ghost2025x",
            1,
        )
        (legal / "gaps.yml").write_text(bad)
        rc, out = run_validator(legal, fallback=True)
        check("invalid closure reference is caught", rc != 0 and "closes_if_met.key" in out)

    check(
        "worked example has a complete 12-cell grid",
        EXAMPLE.joinpath("coverage.yml").read_text().count("  - coords:") == 12,
    )
    rc_dev, out_dev = run_validator(EXAMPLE)
    rc, out = run_validator(EXAMPLE, fallback=True)
    check("worked example is clean", rc == 0 and "0 error(s)" in out, out)
    check("development and fallback validators agree", rc_dev == rc == 0, out_dev)
    rc_broken_dev, _out = run_validator(BROKEN)
    rc_broken_fallback, _out = run_validator(BROKEN, fallback=True)
    check(
        "development and fallback reject broken state",
        rc_broken_dev != 0 and rc_broken_fallback != 0,
    )
    rc, _out = run_validator(BROKEN, fallback=True)
    check("broken fixture is nonzero under fallback", rc != 0)
    rc, _out = run_validator(EXAMPLE, isolated=True)
    check("clean isolated interpreter validates worked example", rc == 0)
    rc, _out = run_validator(BROKEN, isolated=True)
    check("clean isolated interpreter rejects broken example", rc != 0)


def main() -> int:
    print(f"ai-research-skills tests (python {sys.version.split()[0]})")
    test_payload_and_hooks()
    test_installer()
    test_hardening_regressions()
    test_doctor()
    test_validator()
    print(f"\n{passed} passed, {len(failed)} failed")
    for name in failed:
        print(f"  - {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
