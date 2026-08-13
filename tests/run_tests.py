#!/usr/bin/env python3
"""Stdlib regression tests for the standalone ai-research-skills toolbox.

The suite intentionally tests the public behavior that matters without importing optional
validation dependencies.  The bundled linter is also exercised through its fallback mode so
``python3`` remains enough for an installed project.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASSETS = SRC / "ai_research_skills" / "assets"
INSTALL = ROOT / "install.py"
VALIDATE = ASSETS / "scripts" / "rs_validate.py"
EXAMPLE = (
    ROOT
    / "examples"
    / "worked-survey"
    / ".research"
    / "survey"
    / "retrieval-augmented-agents"
)

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


def run_validator(
    directory: pathlib.Path,
    *,
    fallback: bool = False,
    strict: bool = False,
    profile: str | None = None,
) -> tuple[int, str]:
    env = dict(os.environ)
    if fallback:
        env["ARS_FORCE_FALLBACK"] = "1"
    command = [sys.executable, str(VALIDATE)]
    if strict:
        command.append("--strict")
    if profile:
        command += ["--profile", profile]
    command.append(str(directory))
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    return result.returncode, result.stdout + result.stderr


def test_version_and_assets() -> None:
    print("\nversion and asset contract")
    from ai_research_skills import __version__, hosts, installer

    check("release version is 0.8.0", __version__ == "0.8.0")
    check("installer version is 0.8.0", installer.__version__ == "0.8.0")
    check(
        "all registered hosts are skills-only", all(not host.hooks for host in hosts.HOSTS)
    )
    with tempfile.TemporaryDirectory() as raw:
        host = hosts.lookup("claude")
        assert host is not None
        desired = installer._desired_files(raw, host)
        check(
            "legacy hook source remains outside desired files",
            not any("/hooks/" in path for path in desired),
        )

    skill_root = ASSETS / "skills"
    command_root = ASSETS / "commands"
    forbidden = (
        "disallowed-tools",
        "cannot advance",
        "read-only projection",
        "only skill permitted",
        "mandatory recall",
        "readiness floor",
    )
    for path in sorted(skill_root.glob("*/SKILL.md")) + sorted(command_root.glob("*.md")):
        text = path.read_text()
        check(f"{path.relative_to(ROOT)} is user-invoked", "user" in text.lower())
        for phrase in forbidden:
            check(f"{path.relative_to(ROOT)} omits {phrase!r}", phrase not in text.lower())
        check(
            f"{path.relative_to(ROOT)} disables model auto-invocation",
            "disable-model-invocation: true" in text,
        )
    for path in (
        ROOT / "README.md",
        ROOT / "docs" / "DESIGN.md",
        ROOT / "docs" / "SETUP.md",
    ):
        text = path.read_text().lower()
        for phrase in forbidden:
            check(f"{path.relative_to(ROOT)} omits {phrase!r}", phrase not in text)
    check("lint command is packaged", (command_root / "ars-lint.md").is_file())


def test_linter_scope() -> None:
    print("\nscoped optional linter")
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        empty = root / "empty"
        empty.mkdir()
        rc, out = run_validator(empty, fallback=True)
        check("empty optional workspace passes", rc == 0 and "none" in out, out)

        sparse = root / "sparse"
        sparse.mkdir()
        (sparse / "protocol.yml").write_text("topic: small\nphase: 0\n")
        rc, out = run_validator(sparse, fallback=True)
        check("protocol-only legacy phase is accepted", rc == 0, out)

        empty_protocol = root / "empty-protocol"
        empty_protocol.mkdir()
        (empty_protocol / "protocol.yml").write_text("\n")
        rc, out = run_validator(empty_protocol, fallback=True)
        check(
            "present empty protocol fails instead of looking absent",
            rc != 0 and "empty/null" in out,
            out,
        )

        sparse_corpus = root / "sparse-corpus"
        sparse_corpus.mkdir()
        (sparse_corpus / "corpus.jsonl").write_text(
            json.dumps({"key": "paper-without-provenance"}) + "\n"
        )
        rc, out = run_validator(sparse_corpus, fallback=True)
        strict_rc, _strict_out = run_validator(sparse_corpus, fallback=True, strict=True)
        check(
            "missing corpus found_via is a warning",
            rc == 0 and strict_rc != 0 and "WARN" in out and "found_via" in out,
            out,
        )
        (sparse_corpus / "corpus.jsonl").write_text(
            json.dumps({"key": "bad-provenance", "found_via": None}) + "\n"
        )
        check(
            "malformed supplied corpus provenance is an error",
            run_validator(sparse_corpus, fallback=True)[0] != 0,
        )
        rc, out = run_validator(sparse, fallback=True, profile="decision-brief")
        check(
            "deprecated profile adds no prerequisite",
            rc == 0 and "prerequisite" in out.lower(),
            out,
        )

        partial = root / "partial"
        partial.mkdir()
        (partial / "protocol.yml").write_text(
            "topic: partial\ncreated: 2026-08-01\nphase: 5\n"
        )
        (partial / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "paper2025x",
                    "title": "Paper",
                    "id": "doi:example/1",
                    "found_via": ["manual:user-supplied"],
                    "accessed": "2026-08-01",
                }
            )
            + "\n"
        )
        rc, out = run_validator(partial, fallback=True)
        check("partial corpus does not need future artifacts", rc == 0, out)

        broken = root / "broken"
        broken.mkdir()
        (broken / "corpus.jsonl").write_text(
            json.dumps({"key": "same", "id": "doi:one", "found_via": ["manual:x"]})
            + "\n"
            + json.dumps(
                {
                    "key": "same",
                    "id": "doi:one",
                    "found_via": ["manual:y"],
                    "corroboration": {"agrees_with": ["missing"]},
                }
            )
            + "\n"
        )
        rc, out = run_validator(broken, fallback=True)
        check(
            "duplicate keys and dangling references fail",
            rc != 0 and "duplicate" in out and "missing" in out,
            out,
        )

        refs = root / "refs"
        refs.mkdir()
        (refs / "corpus.jsonl").write_text(
            json.dumps(
                {"key": "paper2025x", "id": "doi:example/1", "found_via": ["manual:x"]}
            )
            + "\n"
        )
        (refs / "refs.bib").write_text("@article{paper2025x, title={Paper}}\n")
        rc, out = run_validator(refs, fallback=True)
        strict_rc, _strict_out = run_validator(refs, fallback=True, strict=True)
        check(
            "missing BibTeX provenance is a visible warning",
            rc == 0 and "provenance" in out,
            out,
        )
        check("strict mode can elevate the warning", strict_rc != 0)

        coverage_only = root / "coverage-only"
        coverage_only.mkdir()
        (coverage_only / "coverage.yml").write_text(
            "cells:\n  - occupants: [missing-paper]\n    gap_id: missing-gap\n"
        )
        rc, out = run_validator(coverage_only, fallback=True)
        check(
            "coverage-only subset warns instead of failing unresolved companions",
            rc == 0 and "absent" in out,
            out,
        )

        gaps_only = root / "gaps-only"
        gaps_only.mkdir()
        (gaps_only / "gaps.yml").write_text(
            "gaps:\n  - id: gap-one\n    closes_if_met:\n      key: missing-paper\n"
        )
        rc, out = run_validator(gaps_only, fallback=True)
        check(
            "gaps-only subset warns instead of failing absent corpus",
            rc == 0 and "absent" in out,
            out,
        )

        refs_only = root / "refs-only"
        refs_only.mkdir()
        (refs_only / "refs.bib").write_text(
            "@article{paper, title={Paper}}\n"
            "% rs-provenance: key=paper id=doi:paper tool=manual date=2026-08-01\n"
        )
        rc, out = run_validator(refs_only, fallback=True)
        check(
            "refs-only subset warns instead of failing absent corpus",
            rc == 0 and "absent" in out,
            out,
        )

        malformed_subset = root / "malformed-subset"
        malformed_subset.mkdir()
        (malformed_subset / "coverage.yml").write_text("cells: not-a-list\n")
        check(
            "malformed present optional artifact still fails",
            run_validator(malformed_subset, fallback=True)[0] != 0,
        )

    check(
        "worked example passes fallback linter",
        run_validator(EXAMPLE, fallback=True)[0] == 0,
    )


def test_optional_evidence_and_host_selection() -> None:
    print("\noptional evidence fields and doctor host selection")
    from ai_research_skills import installer

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)

        legacy = root / "legacy-corpus"
        legacy.mkdir()
        (legacy / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "legacy-number",
                    "found_via": ["manual:test"],
                    "numbers": [
                        {"value": "6.2 EM", "source": "Table 3, p.7", "looked_at": True}
                    ],
                }
            )
            + "\n"
        )
        rc, out = run_validator(legacy, fallback=True)
        check("legacy corpus and number fields still pass", rc == 0, out)

        valid_locator = root / "valid-locator"
        valid_locator.mkdir()
        (valid_locator / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "located",
                    "found_via": ["manual:test"],
                    "claim": "A located claim",
                    "claim_locator": {
                        "kind": "section",
                        "value": "4.1",
                        "detail": "methods",
                        "extension": "kept",
                    },
                    "numbers": [
                        {
                            "value": "6.2 EM",
                            "source": "Table 3",
                            "looked_at": True,
                            "locator": {"kind": "table", "value": "3", "detail": "p.7"},
                        }
                    ],
                }
            )
            + "\n"
        )
        rc, out = run_validator(valid_locator, fallback=True)
        check("valid claim and number locators pass", rc == 0, out)
        (valid_locator / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "bad-locator",
                    "found_via": ["manual:test"],
                    "claim_locator": {"kind": "page", "value": ""},
                }
            )
            + "\n"
        )
        rc, out = run_validator(valid_locator, fallback=True)
        check(
            "empty supplied locator value fails clearly",
            rc != 0 and "claim_locator" in out,
            out,
        )
        (valid_locator / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "bad-number-locator",
                    "found_via": ["manual:test"],
                    "numbers": [{"value": "1", "locator": {"kind": "table"}}],
                }
            )
            + "\n"
        )
        rc, out = run_validator(valid_locator, fallback=True)
        check(
            "number locator missing value fails clearly",
            rc != 0 and "numbers/0/locator" in out,
            out,
        )

        status = root / "search-status"
        status.mkdir()
        (status / "protocol.yml").write_text(
            "search:\n"
            "  status: success_no_hits\n"
            "  backend: test-backend\n"
            "  queries: [first query, second query]\n"
            "  note: completed without matches\n"
        )
        rc, out = run_validator(status, fallback=True)
        check("valid optional search status passes", rc == 0, out)
        (status / "protocol.yml").write_text("search:\n  status: not-a-search-state\n")
        rc, out = run_validator(status, fallback=True)
        check(
            "invalid optional search status fails", rc != 0 and "search/status" in out, out
        )

        refs = root / "both-identifiers"
        refs.mkdir()
        (refs / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "both-ids",
                    "id": "doi:example/1",
                    "openalex_id": "W123",
                    "found_via": ["manual:test"],
                }
            )
            + "\n"
        )
        refs_path = refs / "refs.bib"
        refs_path.write_text(
            "@article{both-ids, title={Both identifiers}}\n"
            "% rs-provenance: key=both-ids id=W123 tool=manual date=2025-01-01\n"
        )
        rc, out = run_validator(refs, fallback=True)
        check("OpenAlex provenance identifier is accepted", rc == 0, out)
        refs_path.write_text(refs_path.read_text().replace("id=W123", "id=doi:example/1"))
        rc, out = run_validator(refs, fallback=True)
        check("DOI provenance identifier is also accepted", rc == 0, out)
        refs_path.write_text(refs_path.read_text().replace("id=doi:example/1", "id=other"))
        rc, out = run_validator(refs, fallback=True)
        check(
            "unmatched provenance identifier still fails",
            rc != 0 and "does not match" in out,
            out,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        selected_calls: list[tuple[str, ...]] = []
        real_selected = installer._selected
        real_recover = installer._recover_journal

        def record_selected(
            path: str, requested: str | None
        ) -> tuple[tuple[object, ...], int]:
            chosen, rc = real_selected(path, requested)
            selected_calls.append(tuple(host.id for host in chosen))
            return chosen, rc

        def replace_detected_host(path: str) -> None:
            (pathlib.Path(path) / ".claude").rename(pathlib.Path(path) / ".cursor")

        installer._selected = record_selected  # type: ignore[assignment]
        installer._recover_journal = replace_detected_host  # type: ignore[assignment]
        try:
            result = installer.doctor(raw)
        finally:
            installer._selected = real_selected
            installer._recover_journal = real_recover
        check(
            "doctor resolves auto host after recovery state changes",
            result != 0 and selected_calls == [("cursor",)],
            f"result={result}, calls={selected_calls}",
        )


def _manifest_with_legacy_hook(
    root: pathlib.Path, host_id: str, *, timeout: int = 10, modified_file: bool = False
) -> tuple[pathlib.Path, pathlib.Path]:
    from ai_research_skills import hook_adapters, hosts, installer

    host = hosts.lookup(host_id)
    assert host is not None
    script = "bib_provenance_guard.py"
    hook = root / host.ownership_root / "hooks" / script
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("legacy hook")
    command = hook_adapters.command_for(host, script, str(root))
    settings_path = root / host.ownership_root / host.hooks_file
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "foreign_top": {"keep": True},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Write|Edit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command,
                                    "timeout": timeout,
                                },
                                {"type": "command", "command": "foreign", "timeout": 1},
                            ],
                        }
                    ]
                },
            }
        )
    )
    manifest_path = root / installer.MANIFEST_REL
    manifest = json.loads(manifest_path.read_text())
    record = manifest["hosts"][host.id]
    record["config"] = f"{host.ownership_root}/{host.hooks_file}"
    record["files"][f"{host.ownership_root}/hooks/{script}"] = installer._sha256(
        hook.read_bytes()
    )
    record["handlers"] = [
        {
            "event": "PreToolUse",
            "script": script,
            "command": command,
            "matcher": "Write|Edit",
            "timeout": 10,
            "definition": {"type": "command", "command": command, "timeout": 10},
        }
    ]
    manifest_path.write_text(
        json.dumps(
            installer._seal_manifest(
                {key: value for key, value in manifest.items() if key != "manifest_sha256"}
            )
        )
    )
    if modified_file:
        hook.write_text("user-edited legacy hook")
    return hook, settings_path


def test_install_and_legacy_cleanup() -> None:
    print("\nstandalone install and legacy cleanup")
    from ai_research_skills import installer

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        foreign_settings = root / ".claude" / "settings.json"
        foreign_settings.parent.mkdir(parents=True)
        foreign_settings.write_text(json.dumps({"foreign": True, "hooks": {"Other": []}}))
        before_settings = foreign_settings.read_bytes()
        result = installer.install(raw, "claude")
        check("fresh install succeeds", result == 0)
        check(
            "fresh install leaves foreign hook settings byte-identical",
            foreign_settings.read_bytes() == before_settings,
        )
        check(
            "fresh install creates no settings through absence",
            not (root / ".claude" / "hooks").exists(),
        )
        check(
            "fresh install has no hook directory", not (root / ".claude" / "hooks").exists()
        )
        manifest = json.loads((root / installer.MANIFEST_REL).read_text())
        check(
            "fresh manifest has no hook handlers",
            manifest["hosts"]["claude"]["handlers"] == [],
        )
        check(
            "fresh manifest does not own hook config",
            manifest["hosts"]["claude"]["config"] is None,
        )
        check(
            "lint alias installed",
            (root / ".claude" / "commands" / "ars-lint.md").is_file(),
        )
        check(
            "verify alias installed without hooks",
            (root / ".claude" / "commands" / "ars-verify.md").is_file()
            and not (root / ".claude" / "hooks").exists(),
        )
        check("doctor does not execute linter", installer.doctor(raw, "claude") == 0)
        check(
            "fresh manifest uses downgrade-safe format 2",
            manifest["format"] == installer.MANIFEST_FORMAT == 2,
        )
        check(
            "simulated format-1 reader rejects format-2 manifest",
            manifest.get("format") != 1,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        settings_path = root / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{not valid json")
        before = settings_path.read_bytes()
        result = installer.install(raw, "claude")
        check(
            "fresh install ignores malformed foreign settings",
            result == 0 and settings_path.read_bytes() == before,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        missing_skill = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        missing_skill.unlink()
        before_manifest = (root / installer.MANIFEST_REL).read_bytes()
        result = installer.doctor(raw, "claude")
        check(
            "doctor reports missing skill without repairing it",
            result != 0
            and not missing_skill.exists()
            and (root / installer.MANIFEST_REL).read_bytes() == before_manifest,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["format"] = 1
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        result = installer.install(raw, "claude")
        migrated = json.loads(manifest_path.read_text())
        check(
            "install migrates legacy format-1 manifest to format 2",
            result == 0 and migrated["format"] == 2,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["format"] = 1
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        result = installer.doctor(raw, "claude")
        migrated = json.loads(manifest_path.read_text())
        check(
            "doctor migrates a clean legacy manifest without repairing files",
            result == 0 and migrated["format"] == 2,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        hook, _settings_path = _manifest_with_legacy_hook(root, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["format"] = 1
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        missing_skill = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        missing_skill.unlink()
        result = installer.doctor(raw, "claude")
        migrated = json.loads(manifest_path.read_text())
        check(
            "doctor migrates format-1 only while cleaning legacy hooks",
            result != 0
            and not hook.exists()
            and not missing_skill.exists()
            and migrated["format"] == 2,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        from ai_research_skills import hook_adapters, hosts

        installer.install(raw, "claude")
        exact_hook, settings_path = _manifest_with_legacy_hook(root, "claude")
        host = hosts.lookup("claude")
        assert host is not None
        modified_script = "absence_claim_guard.py"
        modified_hook = root / host.ownership_root / "hooks" / modified_script
        modified_hook.write_text("legacy absence hook")
        modified_digest = installer._sha256(modified_hook.read_bytes())
        modified_command = hook_adapters.command_for(host, modified_script, str(root))
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["PostToolUse"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": modified_command,
                        "timeout": 999,
                    }
                ]
            }
        ]
        settings_path.write_text(json.dumps(settings))
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        record = manifest["hosts"][host.id]
        modified_relative = f"{host.ownership_root}/hooks/{modified_script}"
        exact_relative = f"{host.ownership_root}/hooks/bib_provenance_guard.py"
        record["files"][modified_relative] = modified_digest
        record["handlers"].append(
            {
                "event": "PostToolUse",
                "script": modified_script,
                "command": modified_command,
                "matcher": None,
                "timeout": 10,
                "definition": {
                    "type": "command",
                    "command": modified_command,
                    "timeout": 10,
                },
            }
        )
        manifest["format"] = 1
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        result = installer.doctor(raw, "claude")
        migrated = json.loads(manifest_path.read_text())
        migrated_record = migrated["hosts"][host.id]
        migrated_handlers = migrated_record["handlers"]
        check(
            "format-1 doctor preserves only the modified handler and hook",
            result != 0
            and not exact_hook.exists()
            and modified_hook.exists()
            and migrated["format"] == 2
            and migrated_record["config"] == f"{host.ownership_root}/{host.hooks_file}"
            and [item["script"] for item in migrated_handlers] == [modified_script],
        )
        check(
            "format-1 doctor preserves modified script digest only",
            migrated_record["files"].get(modified_relative) == modified_digest
            and exact_relative not in migrated_record["files"],
        )
        cleaned = json.loads(settings_path.read_text())
        check(
            "format-1 doctor removes exact sibling and retains modified handler",
            "bib_provenance_guard.py" not in json.dumps(cleaned)
            and modified_script in json.dumps(cleaned),
        )
        before_settings = settings_path.read_bytes()
        before_hook = modified_hook.read_bytes()
        repeat = installer.doctor(raw, "claude")
        repeated_manifest = json.loads(manifest_path.read_text())
        check(
            "repeated doctor still reports and preserves modified ownership",
            repeat != 0
            and settings_path.read_bytes() == before_settings
            and modified_hook.read_bytes() == before_hook
            and [item["script"] for item in repeated_manifest["hosts"][host.id]["handlers"]]
            == [modified_script],
        )
        install_result = installer.install(raw, "claude")
        check(
            "install after migrated doctor keeps the modified handler usable",
            install_result == 0
            and modified_hook.exists()
            and modified_script in settings_path.read_text()
            and [
                item["script"]
                for item in json.loads(manifest_path.read_text())["hosts"][host.id][
                    "handlers"
                ]
            ]
            == [modified_script],
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        hook, settings_path = _manifest_with_legacy_hook(root, "claude")
        original = json.loads(settings_path.read_text())
        result = installer.install(raw, "claude")
        cleaned = json.loads(settings_path.read_text())
        check("upgrade removes exact legacy hook file", result == 0 and not hook.exists())
        check(
            "upgrade removes exact legacy handler",
            "bib_provenance_guard.py" not in settings_path.read_text(),
        )
        check(
            "upgrade preserves foreign config",
            cleaned.get("foreign_top") == original["foreign_top"]
            and "foreign" in settings_path.read_text(),
        )
        new_manifest = json.loads((root / installer.MANIFEST_REL).read_text())
        check(
            "upgrade records no desired handlers",
            new_manifest["hosts"]["claude"]["handlers"] == [],
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        hook, settings_path = _manifest_with_legacy_hook(
            root, "claude", timeout=999, modified_file=True
        )
        before_hook = hook.read_bytes()
        before_settings = settings_path.read_bytes()
        result = installer.install(raw, "claude")
        check("modified legacy leftovers do not block upgrade", result == 0)
        check(
            "modified legacy hook file is preserved",
            hook.exists() and hook.read_bytes() == before_hook,
        )
        check(
            "modified legacy handler is preserved",
            settings_path.read_bytes() == before_settings,
        )
        check("doctor reports modified leftovers", installer.doctor(raw, "claude") != 0)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        hook, settings_path = _manifest_with_legacy_hook(
            root, "claude", timeout=999, modified_file=False
        )
        result = installer.install(raw, "claude")

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        from ai_research_skills import hook_adapters, hosts

        installer.install(raw, "claude")
        host = hosts.lookup("claude")
        assert host is not None
        payload = root / host.ownership_root / "hooks" / "_payload.py"
        modified_hook = root / host.ownership_root / "hooks" / "absence_claim_guard.py"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(
            (pathlib.Path(installer.ASSETS) / "hooks" / "_payload.py").read_bytes()
        )
        modified_hook.write_text("legacy payload-dependent hook")
        command = hook_adapters.command_for(host, "absence_claim_guard.py", str(root))
        settings_path = root / host.ownership_root / host.hooks_file
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PostToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": command,
                                        "timeout": 999,
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        record = manifest["hosts"][host.id]
        payload_relative = f"{host.ownership_root}/hooks/_payload.py"
        modified_relative = f"{host.ownership_root}/hooks/absence_claim_guard.py"
        record["config"] = f"{host.ownership_root}/{host.hooks_file}"
        record["files"][payload_relative] = installer._sha256(payload.read_bytes())
        record["files"][modified_relative] = installer._sha256(modified_hook.read_bytes())
        record["handlers"] = [
            {
                "event": "PostToolUse",
                "script": "absence_claim_guard.py",
                "command": command,
                "matcher": None,
                "timeout": 10,
                "definition": {
                    "type": "command",
                    "command": command,
                    "timeout": 10,
                },
            }
        ]
        record["format"] = 1
        manifest["format"] = 1
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        modified_hook.write_text("user-edited payload-dependent hook")
        check(
            "legacy modified handler protects its owned payload dependency",
            installer.uninstall(raw, "claude") == 0
            and modified_hook.exists()
            and payload.exists()
            and not (root / installer.MANIFEST_REL).exists()
            and settings_path.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original = installer._atomic_write
        calls = {"count": 0}

        def fail_after_three(path: str, data: bytes, mode: int = 0o644) -> None:
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("injected transaction fault")
            original(path, data, mode)

        installer._atomic_write = fail_after_three
        try:
            result = installer.install(raw, "claude")
        finally:
            installer._atomic_write = original
        check("transaction fault returns nonzero", result != 0)
        check(
            "transaction rollback removes package output",
            not (root / ".ai-research-skills" / "manifest.json").exists(),
        )
        check(
            "transaction rollback leaves no hook directory",
            not (root / ".claude" / "hooks").exists(),
        )


def _manifestless_legacy_fixture(
    root: pathlib.Path, host_id: str
) -> tuple[pathlib.Path, dict[str, object]]:
    from ai_research_skills import hook_adapters, hosts, installer

    host = hosts.lookup(host_id)
    assert host is not None
    adapter = hook_adapters.for_host(host)
    timeout_by_script = {
        script: timeout for _event, _matcher, script, timeout in hook_adapters._BASE_SPECS
    }
    settings: dict[str, object]
    if host_id == "codex":
        settings = {"foreign_top": True}
        container = settings
    else:
        settings = {"version": 1, "foreign_top": True, "hooks": {}}
        container = settings["hooks"]
    assert isinstance(container, dict)
    files: dict[str, str] = {}
    commands: list[str] = []
    for canonical_event, _matcher, script, _timeout in hook_adapters._BASE_SPECS:
        event = adapter.event(canonical_event)
        command = hook_adapters.historical_command_forms(host, script)[0]
        commands.append(command)
        hook = root / host.ownership_root / "hooks" / script
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(f"legacy {script}")
        files[installer._relative(str(root), str(hook))] = installer._sha256(
            hook.read_bytes()
        )
        handler = {
            "type": "command",
            "command": command,
            "timeout": timeout_by_script[script],
        }
        if script in {"bib_provenance_guard.py", "absence_claim_guard.py"}:
            matcher = {
                "codex": "apply_patch|Write|Edit",
                "pi": "write|edit",
            }.get(host_id, "Write|Edit")
            group = {"matcher": matcher, "hooks": [handler]}
        else:
            group = {"hooks": [handler]}
        entries = container.setdefault(event, [])
        assert isinstance(entries, list)
        entries.append(group)

    # A foreign group in an ARS event must survive migration in both historical layouts.
    absence_event = adapter.event("PostToolUse")
    entries = container.setdefault(absence_event, [])
    assert isinstance(entries, list)
    entries.append(
        {
            "matcher": "Other",
            "foreign_group": True,
            "hooks": [{"type": "command", "command": "foreign", "timeout": 1}],
        }
    )
    settings_path = root / host.ownership_root / host.hooks_file
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings))
    fingerprint = {
        "format": 1,
        "package": "ai-research-skills",
        "version": "0.5.0",
        "hosts": {host_id: {"files": files, "handler_commands": commands}},
    }
    return settings_path, fingerprint


def test_migration_safety_regressions() -> None:
    print("\nmigration and installer safety regressions")
    from ai_research_skills import hook_adapters, hosts, installer

    for host_id in ("codex", "cursor", "pi"):
        host = hosts.lookup(host_id)
        assert host is not None
        command = (
            hook_adapters.historical_command_forms(host, "survey_staleness.py")[0]
            + " --custom"
        )
        check(
            f"{host_id} historical command suffix is classified, not exact",
            hook_adapters.script_for_command(command, host) == "survey_staleness.py"
            and hook_adapters.exact_script(command, host) is None,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        host = hosts.lookup("pi")
        assert host is not None
        script = "bib_provenance_guard.py"
        command = hook_adapters.historical_command_forms(host, script)[0] + " --custom"
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "write|edit",
                        "hooks": [{"type": "command", "command": command, "timeout": 10}],
                    }
                ]
            }
        }
        cleaned, removed, modified = hook_adapters.cleanup(
            settings, host, root=str(root), allow_legacy=True
        )
        foreign = command.replace(f"{script}", f"{script}.bak")
        check(
            "historical relative command suffix is retained as modified",
            removed == []
            and modified == [script]
            and script in json.dumps(cleaned)
            and hook_adapters.script_for_command(foreign, host) is None,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(str(root), "pi")
        host = hosts.lookup("pi")
        assert host is not None
        script = "bib_provenance_guard.py"
        hook = root / host.ownership_root / "hooks" / script
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("shared legacy hook")
        exact_command = hook_adapters.historical_command_forms(host, script)[0]
        modified_command = exact_command + " --custom"
        settings_path = root / host.ownership_root / host.hooks_file
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "write|edit",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": exact_command,
                                        "timeout": 10,
                                    },
                                    {
                                        "type": "command",
                                        "command": modified_command,
                                        "timeout": 10,
                                    },
                                ],
                            }
                        ]
                    }
                }
            )
        )
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        record = manifest["hosts"][host.id]
        relative = f"{host.ownership_root}/hooks/{script}"
        record["config"] = f"{host.ownership_root}/{host.hooks_file}"
        record["files"][relative] = installer._sha256(hook.read_bytes())
        record["handlers"] = [
            {
                "event": "PreToolUse",
                "script": script,
                "command": exact_command,
                "matcher": "write|edit",
                "timeout": 10,
                "definition": {
                    "type": "command",
                    "command": exact_command,
                    "timeout": 10,
                },
            }
        ]
        manifest_path.write_text(
            json.dumps(
                installer._seal_manifest(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    }
                )
            )
        )
        result = installer.install(str(root), "pi")
        cleaned = json.loads(settings_path.read_text())
        migrated = json.loads(manifest_path.read_text())
        commands = [
            handler["command"]
            for group in cleaned["hooks"]["PreToolUse"]
            for handler in group["hooks"]
        ]
        check(
            "historical suffix keeps a shared legacy script after exact cleanup",
            result == 0
            and hook.exists()
            and commands == [modified_command]
            and relative in migrated["hosts"][host.id]["files"]
            and [item["script"] for item in migrated["hosts"][host.id]["handlers"]]
            == [script],
        )
    for host_id in ("codex", "pi", "cursor"):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            settings_path, fingerprint = _manifestless_legacy_fixture(root, host_id)
            old_loader = installer._load_legacy_fingerprint
            installer._load_legacy_fingerprint = lambda fingerprint=fingerprint: fingerprint
            try:
                result = installer.install(str(root), host_id)
            finally:
                installer._load_legacy_fingerprint = old_loader
            migrated = json.loads(settings_path.read_text())
            check(
                f"manifestless {host_id} v0.5 migration succeeds",
                result == 0,
            )
            check(
                f"manifestless {host_id} removes obsolete hook files",
                not (root / f".{host_id}" / "hooks").exists()
                or not any((root / f".{host_id}" / "hooks").iterdir()),
            )
            check(
                f"manifestless {host_id} preserves foreign hook entries",
                "foreign" in json.dumps(migrated) and migrated.get("foreign_top") is True,
            )
            check(
                f"manifestless {host_id} removes ARS commands only",
                not any(
                    script in json.dumps(migrated) for script in hook_adapters.HOOK_SCRIPTS
                )
                and "foreign" in json.dumps(migrated),
            )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        host = hosts.lookup("kimi")
        assert host is not None
        desired = installer._desired_files(str(root), host)
        files: dict[str, str] = {}
        for path, data in desired.items():
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_bytes(data)
            files[installer._relative(str(root), path)] = installer._sha256(data)
        settings_path = root / ".kimi" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"foreign": True, "hooks": {"Other": []}}))
        before_settings = settings_path.read_bytes()
        published = installer._load_legacy_fingerprint()
        kimi_record = dict(published["hosts"]["kimi"])
        kimi_record["files"] = files
        fingerprint = {
            "format": published["format"],
            "hosts": {"kimi": kimi_record},
        }
        old_loader = installer._load_legacy_fingerprint
        installer._load_legacy_fingerprint = lambda fingerprint=fingerprint: fingerprint
        try:
            result = installer.install(str(root), "kimi")
        finally:
            installer._load_legacy_fingerprint = old_loader
        check(
            "Kimi legacy ordinary files adopt without hook proof",
            result == 0 and settings_path.read_bytes() == before_settings,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        host = hosts.lookup("claude")
        assert host is not None
        settings_path = root / ".claude" / host.hooks_file
        settings_path.parent.mkdir(parents=True)
        command = hook_adapters.historical_command_forms(host, "bib_provenance_guard.py")[0]
        settings_path.write_text(
            json.dumps(
                {
                    "foreign_top": True,
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write|Edit",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": command,
                                        "timeout": 10,
                                    }
                                ],
                            }
                        ]
                    },
                }
            )
        )
        before = settings_path.read_bytes()
        result = installer.install(str(root), "claude")
        check(
            "partial manifestless legacy handler is preserved",
            result == 0 and settings_path.read_bytes() == before,
        )
        check(
            "partial manifestless handler is still present",
            any(
                handler.get("command") == command
                for group in json.loads(settings_path.read_text())["hooks"]["PreToolUse"]
                for handler in group.get("hooks", [])
            ),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(str(root), "claude")
        _hook, settings_path = _manifest_with_legacy_hook(root, "claude")
        settings = json.loads(settings_path.read_text())
        settings["hooks"]["PreToolUse"][0]["matcher"] = "Other"
        settings_path.write_text(json.dumps(settings))
        result = installer.install(str(root), "claude")
        retained = json.loads(settings_path.read_text())
        check(
            "modified manifest group matcher does not remove handler",
            result == 0
            and retained["hooks"]["PreToolUse"][0]["matcher"] == "Other"
            and any(
                handler.get("command")
                == hook_adapters.command_for(
                    hosts.lookup("claude"), "bib_provenance_guard.py", str(root)
                )
                for group in retained["hooks"]["PreToolUse"]
                for handler in group.get("hooks", [])
            ),
        )
        check(
            "modified matcher test still has a foreign sibling",
            "foreign" in settings_path.read_text(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".claude").mkdir()
        marker = root / ".claude" / "foreign.txt"
        marker.write_text("keep")
        result = installer.doctor(str(root), "claude")
        check(
            "doctor with no manifest is diagnostic-only",
            result != 0
            and marker.read_text() == "keep"
            and not (root / installer.MANIFEST_REL).exists()
            and not (root / ".claude" / "skills").exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        settings_path, fingerprint = _manifestless_legacy_fixture(root, "cursor")
        old_loader = installer._load_legacy_fingerprint
        installer._load_legacy_fingerprint = lambda fingerprint=fingerprint: fingerprint
        try:
            result = installer.doctor(str(root), "cursor")
        finally:
            installer._load_legacy_fingerprint = old_loader
        check(
            "doctor cleans a complete legacy install without installing a suite",
            result == 0
            and not (root / installer.MANIFEST_REL).exists()
            and (
                not (root / ".cursor" / "hooks").exists()
                or not any((root / ".cursor" / "hooks").iterdir())
            )
            and "foreign" in settings_path.read_text(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        real = root / "real"
        real.mkdir()
        symlink_root = root / "project"
        symlink_root.symlink_to(real, target_is_directory=True)
        check(
            "symlink project root is rejected without writes",
            installer.install(str(symlink_root), "claude") != 0
            and not (real / installer.MANIFEST_REL).exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(str(root), "claude")
        foreign = root / ".claude" / "foreign-owned.txt"
        foreign.write_text("keep")
        check(
            "uninstall preserves unowned host file",
            installer.uninstall(str(root), "claude") == 0 and foreign.read_text() == "keep",
        )


def test_installer_hardening_regressions() -> None:
    """Focused hardening checks for the skills-only installer transaction boundary."""
    print("\ninstaller hardening regressions")
    from ai_research_skills import hook_adapters, hosts, installer

    def files_snapshot(root: pathlib.Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        conflict = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("foreign")
        before = files_snapshot(root)
        result = installer.install(raw, "claude")
        check(
            "hardening same-name conflict is zero-write",
            result != 0
            and files_snapshot(root) == before
            and not (root / installer.MANIFEST_REL).exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["hosts"]["claude"]["files"]["tampered"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        before = files_snapshot(root)
        check(
            "hardening manifest tamper rejects with zero-write",
            installer.install(raw, "claude") != 0
            and installer.uninstall(raw, "claude") != 0
            and files_snapshot(root) == before,
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        settings_path = root / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{bad")
        before = files_snapshot(root)
        check(
            "hardening invalid foreign JSON is untouched",
            installer.install(raw, "claude") == 0
            and files_snapshot(root) != before
            and settings_path.read_bytes() == b"{bad",
            "fresh skills-only install must not parse or rewrite foreign settings",
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        real = root / "real"
        real.mkdir()
        symlink_root = root / "project"
        symlink_root.symlink_to(real, target_is_directory=True)
        ancestor = root / "ancestor"
        ancestor.mkdir()
        (ancestor / ".claude").symlink_to(real, target_is_directory=True)
        check(
            "hardening symlink root and ancestor reject",
            installer.install(str(symlink_root), "claude") != 0
            and installer.install(str(ancestor), "claude") != 0
            and not (real / installer.MANIFEST_REL).exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original_atomic = installer._atomic_write
        calls = {"count": 0}

        def fail_transaction(path: str, data: bytes, mode: int = 0o644) -> None:
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("injected transaction fault")
            original_atomic(path, data, mode)

        installer._atomic_write = fail_transaction
        try:
            result = installer.install(raw, "claude")
        finally:
            installer._atomic_write = original_atomic
        check(
            "hardening transaction fault rolls back package output",
            result != 0 and not (root / installer.MANIFEST_REL).exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original_atomic = installer._atomic_write
        calls = {"count": 0}

        def interrupt_after_write(path: str, data: bytes, mode: int = 0o644) -> None:
            calls["count"] += 1
            original_atomic(path, data, mode)
            if calls["count"] == 3:
                raise KeyboardInterrupt("simulated process interruption")

        installer._atomic_write = interrupt_after_write
        interrupted = False
        try:
            installer.install(raw, "claude")
        except KeyboardInterrupt:
            interrupted = True
        finally:
            installer._atomic_write = original_atomic
        journal = root / installer.JOURNAL_REL
        check(
            "hardening interrupted transaction leaves journal",
            interrupted and journal.exists(),
        )
        check(
            "hardening next process recovers journal",
            installer.install(raw, "claude") == 0 and not journal.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / "snapshot.txt"
        target.write_text("before")
        installer._Transaction(raw, [str(target)])
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
                installer._recover_journal(raw)
            except installer.InstallerError as exc:
                recovery_error = str(exc)
            else:
                recovery_error = ""
        finally:
            installer._atomic_write = original_atomic
        journal = root / installer.JOURNAL_REL
        check(
            "hardening failed snapshot recovery retains sealed journal",
            "sealed journal retained" in recovery_error and journal.exists(),
        )
        installer._recover_journal(raw)
        check(
            "hardening later snapshot recovery completes",
            target.read_text() == "before" and not journal.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        original_stat = installer.os.stat
        fake_stat = type("FakeStat", (), {"st_dev": 7, "st_ino": 11})()
        installer.os.stat = lambda _path: fake_stat
        try:
            one = installer._ProjectLock(str(root / "Project"))
            two = installer._ProjectLock(str(root / "project"))
        finally:
            installer.os.stat = original_stat
        check("hardening lock identity is stable across aliases", one.path == two.path)

    with tempfile.TemporaryDirectory() as raw:
        missing = pathlib.Path(raw) / "missing-uninstall"
        check(
            "hardening missing-root uninstall is a no-op without creation",
            installer.uninstall(str(missing), "claude") == 0 and not missing.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        hooks = root / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        check(
            "hardening foreign empty hooks directory survives uninstall",
            installer.install(raw, "claude") == 0
            and installer.uninstall(raw, "claude") == 0
            and hooks.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        host = hosts.lookup("cursor")
        assert host is not None
        historical_command = hook_adapters.historical_command_forms(
            host, "absence_claim_guard.py"
        )[0]
        settings = {
            "version": 1,
            "foreign_top": {"keep": True},
            "hooks": {
                "preToolUse": [
                    {
                        "matcher": "Other",
                        "foreign_group": True,
                        "hooks": [{"type": "command", "command": "foreign-pre"}],
                    }
                ],
                "postToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "metadata": "keep",
                        "hooks": [
                            {
                                "type": "command",
                                "command": historical_command,
                                "timeout": 10,
                            },
                            {
                                "type": "command",
                                "command": historical_command,
                                "timeout": 999,
                            },
                            {"type": "command", "command": "foreign-post"},
                        ],
                    }
                ],
            },
        }
        settings_path = root / ".cursor" / "hooks.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(settings))
        cleaned, removed, modified = hook_adapters.cleanup(
            settings,
            host,
            root=str(root),
            allow_legacy=True,
        )
        all_entries = [entry for entries in cleaned["hooks"].values() for entry in entries]
        historical_entries = [
            entry for entry in all_entries if entry.get("command") == historical_command
        ]
        check(
            "hardening Cursor cleanup removes exact ARS and preserves modified handler",
            len(historical_entries) == 1
            and historical_entries[0].get("timeout") == 999
            and "absence_claim_guard.py" in modified
            and "absence_claim_guard.py" not in removed,
        )
        check(
            "hardening Cursor legacy cleanup directifies every sibling",
            all("hooks" not in entry and "type" not in entry for entry in all_entries)
            and any(entry.get("command") == "foreign-pre" for entry in all_entries)
            and any(entry.get("command") == "foreign-post" for entry in all_entries),
        )
        check(
            "hardening Cursor cleanup retains matcher metadata and foreign config",
            any(
                entry.get("command") == "foreign-post"
                and entry.get("matcher") == "Write|Edit"
                for entry in all_entries
            )
            and cleaned["foreign_top"] == {"keep": True}
            and "_ars_legacy_cursor_group_metadata" in cleaned,
        )
        settings_path.write_text(json.dumps(cleaned))
        check(
            "hardening Cursor cleanup remains safe for subsequent uninstall",
            installer.uninstall(str(root), "cursor") == 0
            and "foreign-post" in settings_path.read_text(),
        )

    sys.path.insert(0, str(ASSETS / "scripts"))
    from _yaml_subset import safe_load as fallback_yaml

    fixture = "truth_yes: yes\ntruth_no: NO\ntruth_on: On\ntruth_off: off\nletter_y: y\nletter_n: n\n"
    fallback_value = fallback_yaml(fixture)
    try:
        import yaml as dev_yaml
    except ImportError:
        dev_yaml = None
    check(
        "hardening fallback YAML 1.1 booleans match PyYAML",
        dev_yaml is None or fallback_value == dev_yaml.safe_load(fixture),
    )


def test_legacy_workspace_and_bare_runtime() -> None:
    print("\nlegacy workspace and bare runtime")
    protocol = (EXAMPLE / "protocol.yml").read_text()
    check("legacy phase field remains in example", "phase:" in protocol)
    check("legacy corpus remains readable", (EXAMPLE / "corpus.jsonl").is_file())
    check("legacy coverage remains readable", (EXAMPLE / "coverage.yml").is_file())
    bare = subprocess.run(
        [sys.executable, "-I", "-S", str(VALIDATE), "--self-test"],
        text=True,
        capture_output=True,
        env={"ARS_FORCE_FALLBACK": "1", "PATH": os.environ.get("PATH", "")},
    )
    check(
        "bare interpreter linter self-test passes",
        bare.returncode == 0,
        bare.stdout + bare.stderr,
    )


def main() -> int:
    test_version_and_assets()
    test_linter_scope()
    test_optional_evidence_and_host_selection()
    test_install_and_legacy_cleanup()
    test_migration_safety_regressions()
    test_installer_hardening_regressions()
    test_legacy_workspace_and_bare_runtime()
    print(f"\n{passed} passed, {len(failed)} failed")
    if failed:
        print("Failed checks:")
        for name in failed:
            print(f"- {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
