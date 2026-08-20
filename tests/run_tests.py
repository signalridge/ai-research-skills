#!/usr/bin/env python3
"""Stdlib regression tests for the standalone ai-research-skills toolbox.

The suite intentionally tests the public behavior that matters without importing optional
validation dependencies.  The bundled linter is also exercised through its fallback mode so
``python3`` remains enough for an installed project.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

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
    check(
        "the host registry has the six separate layouts",
        hosts.known_ids() == ("claude", "codex", "cursor", "pi", "kimi", "kimi-code"),
    )
    with tempfile.TemporaryDirectory() as raw:
        host = hosts.lookup("claude")
        assert host is not None
        desired = installer._desired_files(raw, host)
        check(
            "legacy hook source remains outside desired files",
            not any("/hooks/" in path for path in desired),
        )
        check(
            "new hedge card is in the packaged desired inventory",
            any(path.endswith("ars-survey/references/06-hedge.md") for path in desired),
        )
    recall = (ASSETS / "skills" / "ars-survey" / "references" / "01-recall.md").read_text()
    check(
        "installed recall card uses a stable setup URL",
        "https://github.com/signalridge/ai-research-skills/blob/main/docs/SETUP.md"
        in recall,
    )

    skill_root = ASSETS / "skills"
    command_root = ASSETS / "commands"

    # The structural contract lives in one stdlib-only module shared with `just skills`
    # and CI.  It replaces a per-file `"user" in text.lower()` assertion that was true of
    # essentially any English prose and so distinguished nothing.
    import check_frontmatter

    frontmatter_problems = check_frontmatter.problems()
    check(
        "skill and command frontmatter satisfies the shared contract",
        not frontmatter_problems,
        "; ".join(frontmatter_problems),
    )
    check(
        "the spec deviation stays a single documented key",
        {"disable-model-invocation"} == check_frontmatter.ARS_EXTENSIONS,
    )

    # Vocabulary from the phase-gate design removed in 0.8.  This is a regression guard
    # against that specific design returning, not a general quality signal — it cannot
    # tell a good skill from a bad one, and the structural check above is what does the
    # real work.
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
        for phrase in forbidden:
            check(f"{path.relative_to(ROOT)} omits {phrase!r}", phrase not in text.lower())
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
            "topic: partial\ncreated: 2020-08-01\nphase: 5\n"
        )
        (partial / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "paper2025x",
                    "title": "Paper",
                    "id": "doi:example/1",
                    "found_via": ["manual:user-supplied"],
                    "accessed": "2020-08-01",
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
            "% rs-provenance: key=paper id=doi:paper tool=manual date=2020-08-01\n"
        )
        rc, out = run_validator(refs_only, fallback=True)
        check(
            "refs-only subset warns instead of failing absent corpus",
            rc == 0 and "absent" in out,
            out,
        )

        bib_headers = root / "bib-headers"
        bib_headers.mkdir()
        (bib_headers / "refs.bib").write_text(
            "Plain email @example.invalid must not be an entry.\n@article{paper\n"
        )
        for fallback in (False, True):
            rc, out = run_validator(bib_headers, fallback=fallback)
            check(
                f"malformed BibTeX header is rejected ({'fallback' if fallback else 'native'})",
                rc != 0 and "invalid key/comma" in out and "never closed" in out,
                out,
            )
        (bib_headers / "refs.bib").write_text(
            "Plain email @example.invalid must not be an entry.\n"
            "@article{paper, title={A balanced {title}}}\n"
        )
        check(
            "balanced BibTeX entry and ordinary at-sign pass",
            run_validator(bib_headers, fallback=True)[0] == 0,
        )
        (bib_headers / "refs.bib").write_text("@article paper\n")
        for fallback in (False, True):
            rc, out = run_validator(bib_headers, fallback=fallback)
            check(
                f"missing BibTeX opening delimiter has one diagnostic ({'fallback' if fallback else 'native'})",
                rc != 0 and out.count("no opening") == 1,
                out,
            )
        (bib_headers / "refs.bib").write_text(
            "@comment{literal (comment)}\n"
            '@string{venue = "Journal"}\n'
            '@preamble{"\\newcommand"}\n'
            "@article(paper, title={A (study})\n"
            '@article{monitor, title={The 34" monitor}}\n'
            r'@article{escaped, title="An escaped \\"quote\\""}'
            "\n"
        )
        for fallback in (False, True):
            rc, out = run_validator(bib_headers, fallback=fallback)
            check(
                f"delimiter-aware BibTeX values pass ({'fallback' if fallback else 'native'})",
                rc == 0,
                out,
            )

        sys.path.insert(0, str(ASSETS / "scripts"))
        from rs_validate import _scan_bib_entries

        bib_scanner_cases = (
            (
                "quoted atom containing a closing parenthesis is not an outer close",
                '@article(paper, title="quoted ) value"\n',
                (
                    [],
                    [
                        "entry `paper` is never closed; the file is truncated or its delimiters are unbalanced"
                    ],
                ),
            ),
            (
                "quoted braced and bare atoms joined with hash",
                '@article{concat, title="A {"quoted")}" # {B (C)} # bare, note={ok}}\n',
                (["concat"], []),
            ),
            (
                "brace-protected quotes parentheses and comments",
                '@article{protected, title={A "quoted )" (x)}, note="A" % ) ,\n other=bare}\n',
                (["protected"], []),
            ),
            (
                "missing BibTeX opening delimiter is deduplicated",
                "@article paper\n",
                (
                    [],
                    ["entry `@article` has no opening `{` or `(` delimiter"],
                ),
            ),
            # A tab-indented entry used to vanish from the key list without a word: the
            # scanner's leading-whitespace class was written `[ \\t]`, which matches a
            # space, a backslash or a letter `t`, but never a tab.  Every cross-reference
            # to such an entry then failed against a key list it had silently left.
            (
                "a tab-indented entry is scanned like a space-indented one",
                "\t@article{tabbed,\n  title = {T},\n}\n",
                (["tabbed"], []),
            ),
            (
                "a space-indented entry is scanned",
                "  @article{spaced,\n  title = {T},\n}\n",
                (["spaced"], []),
            ),
            # The same defect ran the other way: `t` and `\` were in that class, so an
            # ordinary prose line beginning with either looked like an entry start.
            (
                "a prose line starting with t is not an entry",
                "to cite t@article{fake, use the key below\n",
                ([], []),
            ),
            (
                "a prose line starting with a backslash is not an entry",
                "\\@article{escaped, x}\n",
                ([], []),
            ),
            # `re.search(r"\\s", key)` looked for a literal backslash-s, so no key was
            # ever tested for whitespace and `@article{bad key,` was accepted.
            (
                "a key containing a space is rejected",
                "@article{bad key,\n  title = {T},\n}\n",
                ([], ["entry `@article` has an invalid key/comma header"]),
            ),
            (
                "a key containing a tab is rejected",
                "@article{bad\tkey,\n  title = {T},\n}\n",
                ([], ["entry `@article` has an invalid key/comma header"]),
            ),
            # The guard meant to stop the header at a line break compared against the
            # characters `\`, `r` and `n`, which no whitespace character can be, so it
            # never fired.  A header may not wrap, and saying so beats dropping it.
            (
                "an entry header split after the at-sign is reported",
                "@\narticle{crossed,\n  title = {T},\n}\n",
                ([], ["entry header is split across lines after `@`"]),
            ),
            (
                "an entry header split after the type is reported",
                "@article\n{split,\n  title = {T},\n}\n",
                ([], ["entry `@article` has no opening `{` or `(` delimiter"]),
            ),
            (
                "a lone at-sign on its own line is not an entry",
                "Write to me @\nand I will reply.\n",
                ([], []),
            ),
        )
        for label, source, expected_scan in bib_scanner_cases:
            check(
                f"direct BibTeX scanner exact result: {label}",
                _scan_bib_entries(source) == expected_scan,
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


def test_broken_fixture_reports_every_claimed_defect() -> None:
    """The fixture is the suite's only end-to-end check of the linter's real checks.

    "the validator rejects the broken fixture" is satisfied by *one* error, so it used to
    stay green even if every check but one silently became a no-op — which was the actual
    state: five defect classes were advertised and one was detected.  Each class is now
    asserted by name, and the count is pinned, so a check that stops firing turns red.
    """
    print("\nbroken fixture defect coverage")
    fixture = ROOT / "tests" / "fixtures" / "broken-survey"
    expected = {
        "malformed record (schema)": "schema violation at relevance",
        "malformed record (enum)": "schema violation at screen",
        "duplicate corpus key": "corpus.jsonl.key: duplicate `beta2025noreason`",
        # One paper, two records, the identifier moved between fields — the shape a
        # careless merge produces, and invisible to a per-field duplicate check.
        "identifier duplicated across fields": "duplicate identifier `openalex:W1000000001`",
        "dangling corroboration": "agrees_with references missing key",
        "dangling nearest_prior_work": "nearest_prior_work references missing key",
        "dangling revivable_by": "revivable_by references missing corpus key",
        "duplicate map coordinate": "duplicate coordinate",
        "dangling map occupant": "occupant references missing corpus key",
        "invalid gap reference": "gap_id references missing gap `G9`",
        "unterminated BibTeX entry": "is never closed",
        "attestation for a missing entry": "provenance attestation names missing entry",
        "BibTeX entry with no corpus record": "has no corpus record",
        "BibTeX entry with no attestation": "has no explicit rs-provenance attestation",
    }
    for fallback in (False, True):
        mode = "fallback" if fallback else "installed deps"
        rc, out = run_validator(fixture, fallback=fallback)
        check(f"broken fixture is rejected ({mode})", rc != 0, out)
        for label, needle in expected.items():
            check(f"broken fixture reports {label} ({mode})", needle in out, out)
        # A bare interpreter and a full one must reach the same verdict, or the linter
        # means something different depending on what the user happens to have installed.
        check(
            f"broken fixture error count is pinned ({mode})",
            "13 error(s), 2 warning(s)" in out,
            out,
        )
        check(
            f"broken fixture reports one complete entry without corpus ({mode})",
            out.count("has no corpus record") == 1,
            out,
        )
        check(
            f"broken fixture reports two complete entries without attestation ({mode})",
            out.count("has no explicit rs-provenance attestation") == 2,
            out,
        )


def test_optional_evidence_and_host_selection() -> None:
    print("\noptional evidence fields and doctor host selection")
    from ai_research_skills import hosts, installer

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

        # `check_dates` recurses, and every schema is additionalProperties: true, so a bare
        # `date` in DATE_FIELDS policed a key no schema declares.  The schema's own date
        # fields must keep failing; a user's extension key must not.
        dates = root / "extension-dates"
        dates.mkdir()
        (dates / "corpus.jsonl").write_text(
            json.dumps(
                {
                    "key": "extension-date",
                    "found_via": ["manual:test"],
                    "numbers": [{"value": "6.2 EM", "date": "August 2020"}],
                }
            )
            + "\n"
        )
        rc, out = run_validator(dates, fallback=True)
        check("user-supplied nested `date` is not policed as ISO", rc == 0, out)

        bad_accessed = root / "bad-accessed"
        bad_accessed.mkdir()
        (bad_accessed / "corpus.jsonl").write_text(
            json.dumps(
                {"key": "k", "found_via": ["manual:test"], "accessed": "August 2020"}
            )
            + "\n"
        )
        rc, out = run_validator(bad_accessed, fallback=True)
        check(
            "a declared date field is still validated", rc != 0 and "accessed" in out, out
        )

        # notes_path is the only workspace reference naming a file rather than a record key,
        # and it was the one dangling class nothing checked.
        notes = root / "notes-path"
        (notes / "notes").mkdir(parents=True)
        (notes / "notes" / "real.md").write_text("note\n")
        (notes / "corpus.jsonl").write_text(
            "\n".join(
                json.dumps(record)
                for record in (
                    {"key": "a", "found_via": ["manual:t"], "notes_path": "notes/real.md"},
                    {"key": "b", "found_via": ["manual:t"], "notes_path": "notes/gone.md"},
                    {
                        "key": "c",
                        "found_via": ["manual:t"],
                        "notes_path": "../../escape.md",
                    },
                )
            )
            + "\n"
        )
        rc, out = run_validator(notes, fallback=True)
        check(
            "notes_path: resolved is silent, missing warns, escaping errors",
            "notes/real.md" not in out
            and "missing file: `notes/gone.md`" in out
            and "must stay inside the workspace" in out
            and rc != 0,
            out,
        )

        # Spelling a path without `..` is not the same as staying inside the workspace:
        # a symlink under the survey directory can still name a file anywhere, and the
        # literal check reads it as clean.
        linked = root / "notes-symlink"
        (linked / "notes").mkdir(parents=True)
        outside = root / "outside-the-workspace.md"
        outside.write_text("not part of the workspace\n")
        symlink_supported = True
        try:
            os.symlink(outside, linked / "notes" / "leak.md")
        except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
            symlink_supported = False
        if symlink_supported:
            (linked / "corpus.jsonl").write_text(
                json.dumps(
                    {
                        "key": "leaky",
                        "found_via": ["manual:t"],
                        "notes_path": "notes/leak.md",
                    }
                )
                + "\n"
            )
            rc, out = run_validator(linked, fallback=True)
            check(
                "notes_path following a symlink out of the workspace is an error",
                rc != 0 and "resolves outside the workspace" in out,
                out,
            )

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
    # `.kimi-code` is a second on-disk layout.  Detecting it as the `kimi` host installed
    # into a freshly created `.kimi/` and left the directory the user actually had empty.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".kimi-code").mkdir()
        detected = [host.id for host in hosts.detect(str(root))]
        check(
            "a .kimi-code project detects as kimi-code",
            detected == ["kimi-code"],
            str(detected),
        )
        check(
            "install(.kimi-code) lands in .kimi-code",
            installer.install(str(root), None) == 0,
        )
        check(
            "install does not invent a sibling .kimi tree",
            (root / ".kimi-code" / "skills" / "ars-survey" / "SKILL.md").is_file()
            and not (root / ".kimi").exists(),
        )
        check(
            "uninstall removes the kimi-code install",
            installer.uninstall(str(root), None) == 0,
        )

    # os.walk on a missing directory yields nothing, so a skill renamed or mistyped in
    # SKILLS used to ship a wheel that installed a silently incomplete suite.
    claude_host = hosts.lookup("claude")
    assert claude_host is not None
    with tempfile.TemporaryDirectory() as raw:
        original = installer.SKILLS
        installer.SKILLS = (*original, "ars-not-a-real-skill")
        try:
            installer._desired_files(raw, claude_host)
        except installer.InstallerError as exc:
            failed = "ars-not-a-real-skill" in str(exc)
        else:
            failed = False
        finally:
            installer.SKILLS = original
        check("a SKILLS entry with no source directory fails loudly", failed)


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
        hook, settings_path = _manifest_with_legacy_hook(root, "claude")
        before_hook = hook.read_bytes()
        settings = json.loads(settings_path.read_text())
        handler = settings["hooks"]["PreToolUse"][0]["hooks"][0]
        handler["command"] = "python3 -O " + handler["command"]
        settings_path.write_text(json.dumps(settings))
        from ai_research_skills import hook_adapters

        manifest_before = json.loads((root / installer.MANIFEST_REL).read_text())
        _, removed, modified, missing = hook_adapters.cleanup(
            settings,
            installer.hosts.lookup("claude"),
            root=raw,
            owned_records=manifest_before["hosts"]["claude"]["handlers"],
        )
        result = installer.install(raw, "claude")
        migrated = json.loads((root / installer.MANIFEST_REL).read_text())
        record = migrated["hosts"]["claude"]
        check(
            "unclassifiable manifest handler is reported missing and protected",
            removed == []
            and modified == []
            and missing == ["bib_provenance_guard.py"]
            and result == 0
            and hook.exists()
            and hook.read_bytes() == before_hook
            and record["handlers"][0]["script"] == "bib_provenance_guard.py"
            and "python3 -O" in settings_path.read_text(),
        )

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
        cleaned, removed, modified, _missing = hook_adapters.cleanup(
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

        def fail_transaction(
            path: str,
            data: bytes,
            mode: int | None = 0o644,
            **kwargs: Any,
        ) -> None:
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("injected transaction fault")
            original_atomic(path, data, mode, **kwargs)

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

        def interrupt_after_write(
            path: str,
            data: bytes,
            mode: int | None = 0o644,
            **kwargs: Any,
        ) -> None:
            calls["count"] += 1
            original_atomic(path, data, mode, **kwargs)
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
            "hardening journal and metadata permissions are restrictive",
            stat.S_IMODE(journal.stat().st_mode) == 0o600
            and stat.S_IMODE((root / ".ai-research-skills").stat().st_mode) == 0o700,
        )
        check(
            "hardening next process recovers journal",
            installer.install(raw, "claude") == 0 and not journal.exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"after")}
        )
        target.write_text("after")
        original_atomic = installer._atomic_write
        failed_once = {"value": False}

        def fail_restore(
            path: str,
            data: bytes,
            mode: int | None = 0o644,
            **kwargs: Any,
        ) -> None:
            if not failed_once["value"]:
                failed_once["value"] = True
                raise OSError("injected restore failure")
            original_atomic(path, data, mode, **kwargs)

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

    # Every mutation here uses a digest from _capture_file as its compare-and-set token.
    # An editor saving by rename swaps the inode mid-read, so a snapshot that reported
    # the old inode's digest would authorize replacing or unlinking the file the user
    # just saved.  Forcing the rename to land inside the read keeps this deterministic.
    # Two checks guard this, and a rename trips both: the path stops naming the inode
    # that was read, and unlinking the old inode changes its ctime.  Each is therefore
    # exercised with the other disabled, so neither can rot behind the other's cover.
    old_bytes = b"old\n" * 20_000
    new_bytes = b"new\n" * 20_000

    def race_capture(
        disable: str | None, interfere: Callable[[pathlib.Path], None]
    ) -> tuple[str, bool]:
        """Run one mid-read interference and report the snapshot's honesty."""
        with tempfile.TemporaryDirectory() as raw:
            target = pathlib.Path(raw) / "settings.json"
            target.write_bytes(old_bytes)
            target.chmod(0o644)
            real_read = installer.os.read
            originals = {
                "inode": installer._inode_identity,
                "content": installer._content_identity,
            }
            fired: list[bool] = []

            def read_then_interfere(fd: int, size: int) -> bytes:
                chunk = real_read(fd, size)
                if not fired:
                    fired.append(True)
                    interfere(target)
                return chunk

            if disable == "inode":
                installer._inode_identity = lambda info: (0, 0)
            elif disable == "content":
                installer._content_identity = lambda info: (0, 0, 0)
            installer.os.read = read_then_interfere
            try:
                state, _data = installer._capture_file(str(target))
                honest = state[1] == installer._sha256(target.read_bytes())
            except installer.InstallerError:
                honest = True  # refusing is the other correct answer
            finally:
                installer.os.read = real_read
                installer._inode_identity = originals["inode"]
                installer._content_identity = originals["content"]
            return ("" if honest else "reported a stale digest"), bool(fired)

    def rename_over(target: pathlib.Path) -> None:
        replacement = target.parent / ".editor-tmp"
        replacement.write_bytes(new_bytes)
        replacement.chmod(0o644)
        os.replace(replacement, target)

    def rewrite_in_place(target: pathlib.Path) -> None:
        with open(target, "r+b") as handle:
            handle.write(new_bytes[: len(old_bytes)])

    for label, disabled, interfere in (
        ("a save by rename", None, rename_over),
        ("a save by rename, inode check alone", "content", rename_over),
        ("a save by rename, ctime check alone", "inode", rename_over),
        ("a rewrite in place", None, rewrite_in_place),
        ("a rewrite in place, ctime check alone", "inode", rewrite_in_place),
    ):
        problem, fired = race_capture(disabled, interfere)
        check(
            f"hardening a snapshot stays honest through {label}",
            problem == "" and fired,
            f"{problem}, interference fired={fired}",
        )

    # `.ai-research-skills/` holding no manifest and no journal is not ours to narrow.
    # doctor is a diagnostic; taking a shared checkout's directory to 0700 would revoke
    # other users' access as a side effect of merely looking.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        foreign = root / ".ai-research-skills"
        foreign.mkdir()
        foreign.chmod(0o755)
        (foreign / "notes.txt").write_text("another tool's data\n")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            installer.doctor(raw, "claude")
        check(
            "hardening doctor leaves a metadata directory it cannot claim alone",
            stat.S_IMODE(foreign.lstat().st_mode) == 0o755,
            oct(stat.S_IMODE(foreign.lstat().st_mode)),
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            install_rc = installer.install(raw, "claude")
        check(
            "hardening install still takes ownership of the directory it writes into",
            install_rc == 0 and stat.S_IMODE(foreign.lstat().st_mode) == 0o700,
            f"rc={install_rc}, mode={oct(stat.S_IMODE(foreign.lstat().st_mode))}",
        )
        check(
            "hardening doctor narrows the directory once it holds a manifest",
            (foreign / "manifest.json").exists() and (foreign / "notes.txt").exists(),
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
        root = pathlib.Path(raw) / "Project"
        other = pathlib.Path(raw) / "Other"
        case_other = pathlib.Path(raw) / "project"
        root.mkdir()
        other.mkdir()
        case_distinct = not case_other.exists()
        if case_distinct:
            case_other.mkdir()
        journal_root = installer._journal_unsigned(str(root), {})
        case_alias_rejected = (
            not installer._journal_root_matches(
                str(case_other), journal_root["root"], journal_root["root_path"]
            )
            if case_distinct
            else True
        )
        check(
            "journal root accepts equivalent path identity and rejects another root",
            installer._journal_root_matches(str(root), str(root / "."))
            and installer._journal_root_matches(str(root), str(root))
            and not installer._journal_root_matches(str(root), str(other))
            and case_alias_rejected,
        )
        # A relative spelling resolves against the working directory, not against
        # anything tied to the journal.  Accepting one let a journal committed to a
        # repository authorize itself on every clone, because users run from the root.
        # The check must therefore be made from inside that root, where the resolution
        # succeeds -- from anywhere else it passes for the wrong reason.
        cwd = os.getcwd()
        os.chdir(str(root))
        try:
            relative_rejected = (
                not installer._journal_root_matches(str(root), ".")
                and not installer._journal_root_matches(str(root), "")
                and not installer._journal_root_matches(
                    str(root), journal_root["root"], "."
                )
            )
            same_root_from_inside = installer._journal_root_matches(str(root), str(root))
        finally:
            os.chdir(cwd)
        check(
            "journal root rejects relative spellings that would resolve against cwd",
            relative_rejected and same_root_from_inside,
        )
        # Omitting a binding field must not be a way to skip the binding.  A format-2
        # journal that simply leaves out its root fields would otherwise fall through to
        # whichever weaker identity check remained, which is how an optional field turns
        # into a downgrade.
        downgraded = dict(journal_root)
        downgraded.pop("root_inode")
        check(
            "journal format 2 rejects a record that omits its root binding",
            not installer._journal_valid(installer._seal_journal(downgraded)),
        )
        without_path = dict(journal_root)
        without_path.pop("root_path")
        check(
            "journal format 2 rejects a record that omits its canonical root path",
            not installer._journal_valid(installer._seal_journal(without_path)),
        )
        check(
            "journal root requires the recorded inode of the root it was written for",
            installer._journal_root_matches(
                str(root),
                journal_root["root"],
                journal_root["root_path"],
                journal_root["root_inode"],
            )
            and not installer._journal_root_matches(
                str(root),
                journal_root["root"],
                journal_root["root_path"],
                "stat:0:0",
            ),
        )

    # A repository can ship `.ai-research-skills/transaction.json`.  Its seal is keyless,
    # so anyone able to write the file can re-seal it; recovery restores caller-supplied
    # bytes, and a host configuration is a file the host may later execute hooks from.
    # Running `doctor` in a fresh clone must therefore never create one.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".ai-research-skills").mkdir()
        payload = json.dumps(
            {"hooks": {"PreToolUse": [{"hooks": [{"command": "planted"}]}]}}
        ).encode()
        forged = installer._seal_journal(
            {
                "format": 2,
                "root": ".",
                "targets": {
                    ".claude/settings.json": {
                        "exists": True,
                        "mode": 0o644,
                        "data": base64.b64encode(payload).decode("ascii"),
                        "after": {"exists": False, "sha256": None, "mode": None},
                    }
                },
            }
        )
        journal = root / installer.JOURNAL_REL
        journal.write_text(json.dumps(forged))
        settings = root / ".claude" / "settings.json"
        cwd = os.getcwd()
        os.chdir(raw)  # the attacker's one assumption: the user runs from the root
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                doctor_rc = installer.doctor(raw, "claude")
        finally:
            os.chdir(cwd)
        check(
            "hardening a committed journal cannot plant a host configuration",
            not settings.exists() and doctor_rc != 0,
            f"rc={doctor_rc}, output={buffer.getvalue()!r}",
        )
        check(
            "hardening a rejected journal is retained for inspection",
            journal.exists(),
        )

    # Even with the right root, no interrupted transaction of ours ends with a shared
    # host configuration absent: this installer writes that file and never removes it.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".ai-research-skills").mkdir()
        unsigned = installer._journal_unsigned(raw, {})
        unsigned["targets"] = {
            ".claude/settings.json": {
                "exists": True,
                "mode": 0o644,
                "data": base64.b64encode(b"{}\n").decode("ascii"),
                "after": {"exists": False, "sha256": None, "mode": None},
            }
        }
        (root / installer.JOURNAL_REL).write_text(
            json.dumps(installer._seal_journal(unsigned))
        )
        settings = root / ".claude" / "settings.json"
        recovery_error = ""
        try:
            installer._recover_journal(raw)
        except installer.InstallerError as exc:
            recovery_error = str(exc)
        check(
            "hardening recovery refuses to recreate a deleted host configuration",
            not settings.exists() and "never does" in recovery_error,
            f"{recovery_error!r}",
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("windows state")
        original_name = installer.os.name
        try:
            installer.os.name = "nt"
            state, data = installer._capture_file(str(target))
            unsigned = installer._journal_unsigned(
                raw,
                {str(target): (True, data, state[2])},
                expected={str(target): installer._sha256(b"after")},
            )
            valid = installer._journal_valid(installer._seal_journal(unsigned))
        finally:
            installer.os.name = original_name
        check(
            "simulated Windows file state ignores POSIX mode constraints",
            state == ("regular", installer._sha256(b"windows state"), None)
            and unsigned["targets"][".claude/skills/ars-survey/SKILL.md"]["mode"] is None
            and valid,
        )

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
        cleaned, removed, modified, missing = hook_adapters.cleanup(
            settings,
            host,
            root=str(root),
            allow_legacy=True,
        )
        all_handlers = [
            handler
            for entries in cleaned["hooks"].values()
            for entry in entries
            for handler in entry.get("hooks", [])
        ]
        historical_handlers = [
            handler
            for handler in all_handlers
            if handler.get("command") == historical_command
        ]
        check(
            "hardening Cursor cleanup removes exact ARS and preserves modified handler",
            len(historical_handlers) == 1
            and historical_handlers[0].get("timeout") == 999
            and "absence_claim_guard.py" in modified
            and "absence_claim_guard.py" in removed,
        )
        # The old adapter wrote Claude-style groups, so an ARS handler can share a wrapper
        # with a foreign one.  Removing our child must not restructure their group: no
        # flattening to Cursor's native direct shape, no stripped `type`, no wrapper
        # metadata relocated to an invented top-level key.
        check(
            "hardening Cursor cleanup removes only the ARS child from a shared group",
            cleaned["hooks"]["preToolUse"] == settings["hooks"]["preToolUse"]
            and [
                handler
                for handler in cleaned["hooks"]["postToolUse"][0]["hooks"]
                if handler.get("command") == "foreign-post"
            ]
            == [{"type": "command", "command": "foreign-post"}],
        )
        check(
            "hardening Cursor cleanup leaves the foreign wrapper and config intact",
            cleaned["hooks"]["postToolUse"][0]["matcher"] == "Write|Edit"
            and cleaned["hooks"]["postToolUse"][0]["metadata"] == "keep"
            and cleaned["foreign_top"] == {"keep": True}
            and cleaned["version"] == 1
            and not any(key.startswith("_ars_") for key in cleaned),
        )
        settings_path.write_text(json.dumps(cleaned))
        check(
            "hardening Cursor cleanup remains safe for subsequent uninstall",
            installer.uninstall(str(root), "cursor") == 0
            and "foreign-post" in settings_path.read_text(),
        )

    claude_host = hosts.lookup("claude")
    assert claude_host is not None
    owned_cases = {
        ".claude/skills/ars-survey/SKILL.md": True,
        ".claude/skills/ars-survey/references/06-hedge.md": True,
        # A future/private name is not an ownership grant, even when it shares
        # the current ARS prefix.  The old rs spelling is also not in the published
        # v0.5 file inventory.
        ".claude/skills/ars-renamed-later/SKILL.md": False,
        ".claude/skills/rs-survey/SKILL.md": False,
        ".claude/commands/ars-lint.md": True,
        ".claude/ai-research-skills/scripts/rs_validate.py": True,
        ".claude/ai-research-skills/schemas/corpus.schema.json": True,
        ".claude/hooks/_payload.py": True,
        # Neighbours in the same shared directories, and files elsewhere in the project.
        ".claude/skills/someone-elses-skill/SKILL.md": False,
        ".claude/commands/deploy.md": False,
        ".claude/commands/ars-lint.sh": False,
        ".claude/hooks/their_hook.py": False,
        ".claude/settings.json": False,
        ".claude/skills": False,
        "README.md": False,
        ".codex/skills/ars-survey/SKILL.md": False,
        "": False,
    }
    wrong = [
        relative
        for relative, expected in owned_cases.items()
        if installer.owned_manifest_path(claude_host, relative) is not expected
    ]
    check("ownership path allowlist matches its stated boundary", not wrong, str(wrong))

    # The manifest seal proves the record was not corrupted; it is not proof that the
    # recorded paths were ever ours.  Anyone who can write the file can re-seal it, so a
    # nominated bystander file is dropped from the record rather than acted on.  It is
    # deliberately not a fatal error: this reader cannot tell a forged claim from a
    # record written by a version whose assets have since been renamed, and failing
    # closed on that would wedge install, doctor and uninstall with no way out.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        bystander = root / "README.md"
        original = "# belongs to the project, not to ARS\n"
        bystander.write_text(original)
        manifest_path = root / installer.MANIFEST_REL
        forged = json.loads(manifest_path.read_text())
        forged.pop("manifest_sha256", None)
        forged["hosts"]["claude"]["files"]["README.md"] = installer._sha256(
            bystander.read_bytes()
        )
        manifest_path.write_text(
            json.dumps(installer._seal_manifest(forged), indent=2) + "\n"
        )
        claimed = installer.retired_manifest_paths(manifest_path.read_bytes())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            install_rc = installer.install(raw, "claude")
            uninstall_rc = installer.uninstall(raw, "claude")
        reported = buffer.getvalue()
        check(
            "ownership re-sealed manifest cannot claim an ordinary project file",
            bystander.exists() and bystander.read_text() == original,
        )
        check(
            "ownership a claim on a bystander file is reported, not silently dropped",
            claimed == ["README.md"] and "README.md" in reported,
            f"claimed={claimed}, output={reported!r}",
        )
        check(
            "ownership an unrecognised claim does not wedge install or uninstall",
            install_rc == 0 and uninstall_rc == 0,
            f"install={install_rc}, uninstall={uninstall_rc}",
        )

    # A manifest that records claude says nothing about codex.  Files that merely happen
    # to be byte-identical to a current ARS asset are then somebody else's files, and the
    # manifest is positive evidence that we did not put them there.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        codex = hosts.lookup("codex")
        assert codex is not None
        planted = installer._desired_files(raw, codex)
        for path, data in planted.items():
            target = pathlib.Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        rc = installer.uninstall(raw, "codex")
        check(
            "ownership uninstall skips a host the manifest never recorded",
            rc == 0 and all(pathlib.Path(path).is_file() for path in planted),
        )

    # Host-specific config and handler records are compatibility metadata, not an
    # ownership grant.  Forging either shape must fail before any package mutation.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["hosts"]["claude"]["config"] = ".claude/other-settings.json"
        manifest.pop("manifest_sha256", None)
        manifest_path.write_text(json.dumps(installer._seal_manifest(manifest)))
        check(
            "forged host config path fails closed",
            installer.install(raw, "claude") != 0
            and not (root / ".claude" / "other-settings.json").exists(),
        )

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        manifest["hosts"]["claude"]["handlers"] = [{"event": "PreToolUse"}]
        manifest.pop("manifest_sha256", None)
        manifest_path.write_text(json.dumps(installer._seal_manifest(manifest)))
        check(
            "forged handler shape fails closed",
            installer.install(raw, "claude") != 0,
        )

    # Exact journal target inventory rejects a sealed journal that nominates a project
    # README, even though its digest and seal are internally consistent.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        metadata = root / ".ai-research-skills"
        metadata.mkdir(mode=0o700)
        bystander = root / "README.md"
        bystander.write_text("keep")
        journal = installer._journal_unsigned(
            raw,
            {str(bystander): (True, b"keep", 0o644)},
            expected={str(bystander): installer._sha256(b"changed")},
        )
        installer._atomic_json(
            str(root / installer.JOURNAL_REL), installer._seal_journal(journal), 0o600
        )
        try:
            installer._recover_journal(raw)
        except installer.InstallerError as exc:
            journal_error = str(exc)
        else:
            journal_error = ""
        check(
            "forged journal target is rejected and retained",
            "exact transaction inventory" in journal_error
            and bystander.read_text() == "keep"
            and (root / installer.JOURNAL_REL).exists(),
        )

    # Format 2 requires a complete after state.  Format 1 is more conservative: it may
    # clear only when every target still equals before, never after a post-crash edit.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"after")}
        )
        journal_path = root / installer.JOURNAL_REL
        journal_data = json.loads(journal_path.read_text())
        unsigned = {
            key: value for key, value in journal_data.items() if key != "journal_sha256"
        }
        unsigned["targets"][".claude/skills/ars-survey/SKILL.md"].pop("after")
        journal_path.write_text(json.dumps(installer._seal_journal(unsigned)))
        try:
            installer._recover_journal(raw)
        except installer.InstallerError:
            format2_missing_after = True
        else:
            format2_missing_after = False
        missing_after_retained = journal_path.exists()
        unsigned["format"] = 1
        journal_path.write_text(json.dumps(installer._seal_journal(unsigned)))
        target.write_text("edited after crash")
        try:
            installer._recover_journal(raw)
        except installer.InstallerError:
            format1_edit_refused = True
        else:
            format1_edit_refused = False
        format1_edit_retained = journal_path.exists()
        target.write_text("before")
        installer._recover_journal(raw)
        check(
            "format-2 missing after is retained",
            format2_missing_after and missing_after_retained,
        )
        check(
            "format-1 post-crash edit is retained",
            format1_edit_refused and format1_edit_retained,
        )
        check("format-1 before state clears safely", not journal_path.exists())

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"after")}
        )
        target.write_text("after")
        target.chmod(0o600)
        try:
            installer._recover_journal(raw)
        except installer.InstallerError:
            mode_conflict = True
        else:
            mode_conflict = False
        check(
            "journal recovery treats mode-only changes as conflicts",
            mode_conflict and (root / installer.JOURNAL_REL).exists(),
        )
        target.chmod(0o644)
        installer._recover_journal(raw)
        check(
            "journal recovery restores after mode is approved",
            target.read_text() == "before",
        )

    # A transaction CAS rejects an edit between plan/snapshot and mutation, and rollback
    # refuses a third state instead of overwriting it.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        transaction = installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"new")}
        )
        target.write_text("user edit")
        try:
            transaction.write(str(target), b"new")
        except installer.InstallerError:
            cas_refused = True
        else:
            cas_refused = False
        check(
            "transaction write CAS preserves concurrent edit",
            cas_refused and target.read_text() == "user edit",
        )
        target.write_text("before")
        installer._recover_journal(raw)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        transaction = installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"new")}
        )
        original_atomic = installer._atomic_write
        raced = {"value": False}

        def edit_after_temp_fsync(
            path: str,
            data: bytes,
            mode: int | None = 0o644,
            *,
            before_replace: Callable[[], None] | None = None,
        ) -> None:
            if path == str(target) and before_replace is not None:
                target.write_text("user edit during temp preparation")
                raced["value"] = True
            original_atomic(
                path,
                data,
                mode,
                before_replace=before_replace,  # type: ignore[arg-type]
            )

        installer._atomic_write = edit_after_temp_fsync  # type: ignore[assignment]
        try:
            try:
                transaction.write(str(target), b"new")
            except installer.InstallerError:
                temp_race_refused = True
            else:
                temp_race_refused = False
        finally:
            installer._atomic_write = original_atomic
        check(
            "transaction CAS runs after temp preparation",
            raced["value"]
            and temp_race_refused
            and target.read_text() == "user edit during temp preparation",
        )
        target.write_text("before")
        installer._recover_journal(raw)

    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        transaction = installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"new")}
        )
        transaction.write(str(target), b"new")
        target.write_text("third state")
        rollback_errors = transaction.rollback()
        check(
            "rollback CAS retains a third state and journal",
            bool(rollback_errors)
            and target.read_text() == "third state"
            and (root / installer.JOURNAL_REL).exists(),
        )
        target.write_text("new")
        installer._recover_journal(raw)

    # The old kimi-code alias used to operate on `.kimi` and manifest host `kimi`; it
    # must now fail with a diagnostic rather than claim that a separate layout was removed.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "kimi")
        check(
            "old kimi-code alias is not silently treated as a separate uninstall",
            installer.uninstall(raw, "kimi-code") != 0
            and (root / ".kimi" / "skills" / "ars-survey" / "SKILL.md").exists()
            and not (root / ".kimi-code").exists(),
        )

    # A journal records where a transaction started and where it meant to finish.  Any
    # third state means the file changed after the interruption, and rolling back would
    # silently destroy that change.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        target = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("before")
        installer._Transaction(
            raw, [str(target)], expected={str(target): installer._sha256(b"after")}
        )
        target.write_text("edited by the user after the crash")
        try:
            installer._recover_journal(raw)
        except installer.InstallerError as exc:
            conflict = str(exc)
        else:
            conflict = ""
        journal = root / installer.JOURNAL_REL
        check(
            "hardening recovery refuses to overwrite an edit made after the crash",
            "changed after the interruption" in conflict
            and target.read_text() == "edited by the user after the crash"
            and journal.exists(),
        )
        target.write_text("after")
        installer._recover_journal(raw)
        check(
            "hardening recovery still rolls back a genuinely interrupted write",
            target.read_text() == "before" and not journal.exists(),
        )

    # The other half of the same contract: a target the transaction never reached is
    # still at its pre-transaction bytes, and that must recover rather than fail closed.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        untouched = root / ".claude" / "skills" / "ars-survey" / "SKILL.md"
        untouched.parent.mkdir(parents=True)
        untouched.write_text("before")
        removed_target = root / ".claude" / "skills" / "ars-gap-gate" / "SKILL.md"
        removed_target.parent.mkdir(parents=True)
        removed_target.write_text("doomed")
        installer._Transaction(
            raw,
            [str(untouched), str(removed_target)],
            expected={
                str(untouched): installer._sha256(b"never written"),
                str(removed_target): None,
            },
        )
        removed_target.unlink()
        installer._recover_journal(raw)
        check(
            "hardening recovery accepts an unreached target and an applied removal",
            untouched.read_text() == "before"
            and removed_target.read_text() == "doomed"
            and not (root / installer.JOURNAL_REL).exists(),
        )

    # A plan must carry the bytes used for each decision.  Sampling `_file_state` at
    # the end of planning would silently replace that observation with a later baseline.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest_bytes = manifest_path.read_bytes()
        original_state = installer._file_state

        def forbidden_resample(_path: str) -> object:
            raise AssertionError("plan resampled a target state")

        installer._file_state = forbidden_resample  # type: ignore[assignment]
        try:
            claude = hosts.lookup("claude")
            assert claude is not None
            planned = installer._build_plan(raw, (claude,), False)
        finally:
            installer._file_state = original_state
        approved_manifest = planned["approved_before"][str(manifest_path)]
        check(
            "plan carries the manifest bytes read during verification",
            approved_manifest[1] == manifest_bytes,
        )

    # A future host record is opaque compatibility data, not a cross-host ownership grant.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "claude")
        manifest_path = root / installer.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text())
        target_relative = ".claude/skills/ars-survey/SKILL.md"
        target = root / target_relative
        target.write_text("foreign future-host bytes")
        manifest["hosts"]["claude"]["files"].pop(target_relative)
        future_record = {
            "opaque": {"future": True},
            "files": {target_relative: installer._sha256(target.read_bytes())},
            "config": "future/config.json",
            "handlers": [{"future": "shape"}],
        }
        manifest["hosts"]["future-host"] = future_record
        manifest.pop("manifest_sha256", None)
        manifest_path.write_text(json.dumps(installer._seal_manifest(manifest)))
        result = installer.install(raw, "claude")
        preserved = json.loads(manifest_path.read_text())["hosts"]["future-host"]
        check(
            "forged future-host digest cannot authorize selected-host overwrite",
            result != 0
            and target.read_text() == "foreign future-host bytes"
            and preserved == future_record,
        )

    # With both canonical Kimi layouts present and recorded, explicit kimi-code operations
    # must not trigger the old kimi alias diagnostic.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "kimi")
        (root / ".kimi-code").mkdir()
        code_target = root / ".kimi-code/skills/ars-survey/SKILL.md"
        old_target = root / ".kimi/skills/ars-survey/SKILL.md"
        installed_code = installer.install(raw, "kimi-code")
        both_records = json.loads((root / installer.MANIFEST_REL).read_text())["hosts"]
        doctor_code = installer.doctor(raw, "kimi-code")
        removed_code = installer.uninstall(raw, "kimi-code")
        check(
            "kimi and kimi-code dual layouts install, doctor, and uninstall independently",
            installed_code == 0
            and doctor_code == 0
            and removed_code == 0
            and "kimi" in both_records
            and "kimi-code" in both_records
            and not code_target.exists()
            and old_target.exists(),
        )

    def _quiet(call: Callable[[], int]) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = call()
        return code, out.getvalue() + err.getvalue()

    # Every Kimi user has a `.kimi/`.  Keying the migration diagnostic on that directory
    # rather than on evidence of an ARS installation meant the first attempt to use the
    # new `.kimi-code` layout failed for all of them, with a message whose only advice
    # was to "resolve the layouts manually".
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        (root / ".kimi").mkdir()
        code, text = _quiet(lambda: installer.install(raw, "kimi-code"))
        check(
            "an ordinary .kimi/ project can install the kimi-code layout",
            code == 0
            and (root / ".kimi-code/skills/ars-survey/SKILL.md").is_file()
            and not (root / ".kimi/skills").exists(),
            f"rc={code}: {text}",
        )

    # An explicit host name is a complete instruction, so install never refuses it; the
    # commands that name an installation which is not there still stop, because reporting
    # success would read as "the old install is gone" while it sits untouched in .kimi/.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        installer.install(raw, "kimi")
        removed, remove_text = _quiet(lambda: installer.uninstall(raw, "kimi-code"))
        check(
            "uninstall --host kimi-code still refuses to look like it removed the kimi install",
            removed != 0
            and "kimi" in remove_text
            and (root / ".kimi/skills/ars-survey/SKILL.md").exists(),
            f"rc={removed}: {remove_text}",
        )
        added, add_text = _quiet(lambda: installer.install(raw, "kimi-code"))
        check(
            "the install that first creates both Kimi layouts says so",
            added == 0 and ".kimi-code/" in add_text and "uninstall --host" in add_text,
            f"rc={added}: {add_text}",
        )

    # A pre-existing `.ai-research-skills/` this installer has not claimed keeps the mode
    # its owner chose.  Narrowing it on intent alone left a directory at 0700 that no
    # rollback restored when the run then failed.
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        metadata = root / ".ai-research-skills"
        metadata.mkdir()
        # The permissive mode is the fixture: a group-readable directory is exactly what
        # the installer must not silently narrow while it has no claim on it.
        os.chmod(metadata, 0o755)  # noqa: S103
        (root / ".claude").mkdir()
        _quiet(lambda: installer.doctor(raw))
        after_doctor = stat.S_IMODE(metadata.stat().st_mode)
        original_desired = installer._desired_files

        def _fail(*_args: Any, **_kwargs: Any) -> dict[str, bytes]:
            raise installer.InstallerError("simulated planning failure")

        installer._desired_files = _fail  # type: ignore[assignment]
        try:
            failed_code, _ = _quiet(lambda: installer.install(raw, "claude"))
        finally:
            installer._desired_files = original_desired
        after_failure = stat.S_IMODE(metadata.stat().st_mode)
        check(
            "an unclaimed metadata directory keeps its mode through doctor and a failed install",
            after_doctor == 0o755 and after_failure == 0o755 and failed_code != 0,
            f"doctor={after_doctor:o} failed-install={after_failure:o} rc={failed_code}",
        )
        succeeded, _ = _quiet(lambda: installer.install(raw, "claude"))
        check(
            "a successful install claims the metadata directory and then narrows it",
            succeeded == 0
            and stat.S_IMODE(metadata.stat().st_mode) == 0o700
            and (root / installer.MANIFEST_REL).is_file(),
        )

    # Recognition is exact, so a command this installer does not recognise is left in the
    # host's configuration on purpose.  Deleting the script behind it turned a working
    # legacy hook into one that fails to start on every invocation.
    for legacy_host in ("claude", "cursor", "codex", "pi"):
        for spelling, template in (
            ("an added interpreter flag", 'python3 -O "$CLAUDE_PROJECT_DIR/{path}"'),
            ("a wrapper command", 'sh -c "exec python3 {path}"'),
        ):
            with tempfile.TemporaryDirectory() as raw:
                root = pathlib.Path(raw)
                settings_path, fingerprint = _manifestless_legacy_fixture(root, legacy_host)
                host = hosts.lookup(legacy_host)
                assert host is not None
                adapter = hook_adapters.for_host(host)
                script_relative = f"{host.ownership_root}/hooks/bib_provenance_guard.py"
                unrecognised = template.format(path=script_relative)
                settings = json.loads(settings_path.read_text())
                container = settings if legacy_host == "codex" else settings["hooks"]
                container.setdefault(adapter.event("PreToolUse"), []).append(
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {"type": "command", "command": unrecognised, "timeout": 10}
                        ],
                    }
                )
                settings_path.write_text(json.dumps(settings))
                guard = root / script_relative
                original_loader = installer._load_legacy_fingerprint
                installer._load_legacy_fingerprint = (  # type: ignore[assignment]
                    lambda captured=fingerprint: captured
                )
                try:
                    migrated, _ = _quiet(
                        lambda target=raw, chosen=legacy_host: installer.install(
                            target, chosen
                        )
                    )
                finally:
                    installer._load_legacy_fingerprint = original_loader
                remaining = list(
                    hook_adapters.all_config_commands(json.loads(settings_path.read_text()))
                )
                still_referenced = any(
                    "bib_provenance_guard.py" in command for command in remaining
                )
                check(
                    f"legacy migration on {legacy_host} keeps a script {spelling} still names",
                    migrated == 0 and not (still_referenced and not guard.is_file()),
                    f"rc={migrated} referenced={still_referenced} exists={guard.is_file()}",
                )

    sys.path.insert(0, str(ASSETS / "scripts"))
    from _yaml_subset import safe_load as fallback_yaml

    try:
        import yaml as dev_yaml
    except ImportError:
        dev_yaml = None

    RAISES = object()

    def parse(source: str) -> object:
        try:
            return fallback_yaml(source)
        except Exception:
            return RAISES

    def reference(source: str) -> object:
        if dev_yaml is None:
            return None
        try:
            return dev_yaml.safe_load(source)
        except Exception:
            return RAISES

    # Every case states the expected value outright.  Gating the assertion on PyYAML
    # being importable made it vacuously true on a bare interpreter -- which is exactly
    # the configuration this parser exists to serve, and the only one where a regression
    # here reaches a user.  PyYAML parity is checked on top when it is available.
    #
    # Shapes a hand-written protocol.yml really contains, plus the near-misses that must
    # be rejected rather than quietly accepted with a different meaning.
    cases: tuple[tuple[str, str, object], ...] = (
        (
            "YAML 1.1 booleans",
            "truth_yes: yes\ntruth_no: NO\ntruth_on: On\ntruth_off: off\n"
            "letter_y: y\nletter_n: n\n",
            {
                "truth_yes": True,
                "truth_no": False,
                "truth_on": True,
                "truth_off": False,
                "letter_y": "y",
                "letter_n": "n",
            },
        ),
        # A block sequence may sit at its parent key's indent, not only deeper.
        (
            "a sequence at the parent key indent",
            "scope:\n  in:\n  - multi-hop QA\n  - agentic\n",
            {"scope": {"in": ["multi-hop QA", "agentic"]}},
        ),
        (
            "a sequence at column zero",
            "queries:\n- first\n- second\nnote: after\n",
            {"queries": ["first", "second"], "note": "after"},
        ),
        # Parentheses are ordinary characters in a plain scalar, not flow delimiters.
        (
            "a parenthesis in a plain scalar",
            "note: rate limited :-(\n",
            {"note": "rate limited :-("},
        ),
        (
            "parentheses inside a quoted scalar",
            'note: "has (parens) inside"\n',
            {"note": "has (parens) inside"},
        ),
        (
            "a valid literal block scalar",
            "note: |\n  first\n    deeper\n",
            {"note": "first\n  deeper\n"},
        ),
        (
            "a block scalar with a dedented content line",
            "note: |\n  first\n bad\n",
            RAISES,
        ),
        ("an unsupported anchor", "note: &base value\n", RAISES),
        ("an unsupported alias", "note: *base\n", RAISES),
        ("an unsupported tag", "note: !!str value\n", RAISES),
        # YAML requires whitespace after the sequence indicator.  Accepting `-item`
        # would make the bundled parser disagree with PyYAML about whether a workspace
        # file is valid at all, so a bare and a dev environment would reach opposite
        # verdicts on the same file.
        ("a dash without a space as a sequence entry", "in:\n-multi-hop QA\n", RAISES),
        (
            "an indented dash without a space",
            "scope:\n  in:\n  -multi-hop QA\n",
            RAISES,
        ),
        ("a bare dash as a null entry", "in:\n-\n", {"in": [None]}),
        ("a negative number as a sequence entry", "in:\n- -1\n", {"in": [-1]}),
        ("a negative number as a scalar value", "key: -1\n", {"key": -1}),
        (
            "a hexadecimal-looking scalar stays a subset string",
            "topic: 0x10\n",
            {"topic": "0x10"},
        ),
        (
            "a plain scalar may contain a bracket after its first word",
            "topic: draft [v2\n",
            {"topic": "draft [v2"},
        ),
        (
            "a structural flow sequence remains unclosed",
            "topic: [v2\n",
            RAISES,
        ),
        (
            "reserved plain scalar indicators are rejected",
            "at: @name\ntick: `name\nclose: ]name\n",
            RAISES,
        ),
        (
            "non-whitespace dash question colon forms stay strings",
            "dash: -foo\nquestion: ?foo\ncolon: :foo\n",
            {"dash": "-foo", "question": "?foo", "colon": ":foo"},
        ),
        (
            "a misaligned compact-list scalar sibling is rejected",
            "items:\n  - note: |\n      first\n     other: value\n",
            RAISES,
        ),
        (
            "a list mapping can resume after a block scalar",
            "items:\n  - note: |\n      first\n    other: value\n",
            {"items": [{"note": "first\n", "other": "value"}]},
        ),
        (
            "block scalar document markers and tags are literal content",
            "note: |\n  ---\n  ...\n  !important\nother: value\n",
            {"note": "---\n...\n!important\n", "other": "value"},
        ),
        (
            "a shallow non-structure block line is rejected",
            "note: |\n  first\n !important\n",
            RAISES,
        ),
        # `|-` and `>-` are how hand-written YAML normally spells a multi-line string.
        # They parsed only because PyYAML was installed until the bundled parser became
        # the one that decides, so every chomping and indentation indicator is pinned to
        # a value here rather than to a mere accept/reject verdict.
        (
            "a literal block scalar stripping its final newline",
            "question: |-\n  one\n  two\n",
            {"question": "one\ntwo"},
        ),
        (
            "a literal block scalar keeping its trailing newlines",
            "question: |+\n  one\n\n\nother: value\n",
            {"question": "one\n\n\n", "other": "value"},
        ),
        (
            "a folded block scalar stripping its final newline",
            "question: >-\n  one\n  two\n",
            {"question": "one two"},
        ),
        (
            "a folded block scalar clipping to one newline",
            "question: >\n  one\n  two\n",
            {"question": "one two\n"},
        ),
        (
            "an explicit block indentation indicator keeps leading space",
            "question: |2\n   indented\n",
            {"question": " indented\n"},
        ),
        (
            "an indentation indicator combines with chomping in either order",
            "a: |2-\n   x\nb: |-2\n   y\n",
            {"a": " x", "b": " y"},
        ),
        (
            "a stripped block scalar inside a compact list mapping",
            "items:\n  - note: |-\n      first\n    other: value\n",
            {"items": [{"note": "first", "other": "value"}]},
        ),
        (
            "a stripped block scalar as a bare list entry",
            "items:\n  - |-\n    first\n  - plain\n",
            {"items": ["first", "plain"]},
        ),
        (
            "a comment after a block scalar header is not content",
            "question: |- # note\n  text\n",
            {"question": "text"},
        ),
        # A blank line inside a block scalar has no indentation of its own.  Measuring it
        # against the compact `- key: |` column truncated the block one line early and
        # then tripped the sibling-alignment check, so the single most ordinary way to
        # lay out hand-written YAML -- a block scalar with a blank line after it -- was
        # rejected outright.
        (
            "a blank line after a block scalar in a compact list mapping",
            "gaps:\n  - note: |\n      first\n\nphase: 1\n",
            {"gaps": [{"note": "first\n"}], "phase": 1},
        ),
        (
            "a blank line inside a block scalar in a compact list mapping",
            "gaps:\n  - note: |\n      first\n\n      second\n",
            {"gaps": [{"note": "first\n\nsecond\n"}]},
        ),
        (
            "a blank line before a sibling field of a compact list mapping",
            "gaps:\n  - note: |\n      first\n\n    other: value\n",
            {"gaps": [{"note": "first\n", "other": "value"}]},
        ),
        (
            "a blank line before the next entry of a block sequence",
            "gaps:\n  - note: |\n      first\n\n  - plain\n",
            {"gaps": [{"note": "first\n"}, "plain"]},
        ),
        (
            "a kept block scalar keeps the blank line that follows it",
            "gaps:\n  - note: |+\n      first\n\nphase: 1\n",
            {"gaps": [{"note": "first\n\n"}], "phase": 1},
        ),
        (
            "a kept block scalar with no content at all is still its blank lines",
            "note: |+\n\nphase: 1\n",
            {"note": "\n", "phase": 1},
        ),
        # A block sequence may sit at its parent key's indent one level in, too.  The
        # outer mapping already allowed this; the compact-list-mapping branch did not,
        # and rejected `- values:` followed by its own items.
        (
            "a sequence at the parent key indent inside a list mapping",
            "axes:\n  - values:\n    - iterative\n    - hybrid\n",
            {"axes": [{"values": ["iterative", "hybrid"]}]},
        ),
        (
            "a sequence at the parent key indent followed by a sibling field",
            "axes:\n  - values:\n    - iterative\n    name: method\n",
            {"axes": [{"values": ["iterative"], "name": "method"}]},
        ),
        # Folding rules.  A break next to a more-indented line is never folded, so a
        # blank line before one contributes both its own newline and the unfolded break.
        (
            "a folded scalar opening with a blank line",
            "note: >\n\n  text\n  more\n",
            {"note": "\ntext more\n"},
        ),
        (
            "a folded scalar keeps both breaks before a more-indented line",
            "note: >-\n  text\n\n    indented\n  more\n",
            {"note": "text\n\n  indented\nmore"},
        ),
        # Fail-closed rejections.  Each one is a shape PyYAML refuses or reads as a
        # different structure; accepting it as a plain scalar made a workspace's validity
        # depend on whether PyYAML happened to be installed.
        (
            "a second mapping colon in a plain value",
            "topic: a: b\n",
            RAISES,
        ),
        (
            "a mapping colon in a plain list entry",
            "scope:\n  - a: b: c\n",
            RAISES,
        ),
        (
            "an unquoted mapping inside a flow sequence",
            "scope:\n  in: [foo: bar]\n",
            RAISES,
        ),
        (
            "a second colon in a flow mapping value",
            "scope: {a: b: c}\n",
            RAISES,
        ),
        # ...while the shapes that merely *contain* a colon stay ordinary strings.
        (
            "an identifier with an interior colon is not a mapping",
            "scope:\n  in: [W123:cites:1, 10.1038/nature12373]\n",
            {"scope": {"in": ["W123:cites:1", "10.1038/nature12373"]}},
        ),
        (
            "a quoted value may contain a mapping colon",
            'topic: "a: b"\n',
            {"topic": "a: b"},
        ),
        (
            "an explicit flow mapping inside a flow sequence is still accepted",
            "scope:\n  in: [{foo: bar}]\n",
            {"scope": {"in": [{"foo": "bar"}]}},
        ),
        # The two indentation rejections stay reachable after the blank-line fix, and
        # PyYAML refuses all three of these too.  They are pinned because they are the
        # branches most likely to turn back into false rejections of ordinary layout.
        (
            "a list mapping sibling indented past its first key",
            "gaps:\n  - note: value\n     other: x\n",
            RAISES,
        ),
        (
            "a list mapping sibling indented short of its first key",
            "gaps:\n  - note: |\n      first\n   dangling text\n",
            RAISES,
        ),
        (
            "block scalar content shallower than the column that opened it",
            "note: |\n    first\n  shallow\n",
            RAISES,
        ),
        # A byte-order mark is an encoding marker, not part of the first key.  Left in
        # place it produced a `﻿topic` key, and every check for `topic` silently
        # looked at a key that was not there.
        (
            "a leading byte-order mark is not part of the first key",
            "﻿topic: multi-hop QA\n",
            {"topic": "multi-hop QA"},
        ),
    )
    # The bundled parser produces every value ARS acts on, in both environments; PyYAML
    # is only a second opinion on what to reject.  Where the two disagree on a *value*
    # the case is named here with both sides spelled out, so a change to either one
    # fails a test instead of quietly altering what a protocol.yml means.  The cause in
    # every entry is the same: the subset does not implement YAML 1.1 implicit typing.
    typed_divergences: dict[str, tuple[object, object]] = {
        "topic: 0x10\n": ("0x10", 16),
        "topic: 1_000\n": ("1_000", 1000),
        "topic: .inf\n": (".inf", float("inf")),
        "topic: -1.5e3\n": (-1500.0, "-1.5e3"),
    }
    for label, source, expected in cases:
        actual = parse(source)
        check(
            f"hardening fallback YAML handles {label}",
            actual == expected,
            f"got {actual!r}, expected {expected!r}",
        )
        if dev_yaml is not None and expected is not RAISES:
            if source in typed_divergences:
                continue
            check(
                f"hardening fallback YAML agrees with PyYAML on {label}",
                actual == reference(source),
            )
    for source, (ours, theirs) in typed_divergences.items():
        mine = parse(source)
        check(
            f"hardening fallback YAML keeps its documented value for {source.strip()!r}",
            isinstance(mine, dict) and mine.get("topic") == ours,
            f"got {mine!r}, expected topic={ours!r}",
        )
        if dev_yaml is not None:
            other = reference(source)
            check(
                f"hardening PyYAML still differs as documented on {source.strip()!r}",
                isinstance(other, dict) and other.get("topic") == theirs,
                f"got {other!r}, expected topic={theirs!r}",
            )

    # Assembling one logical line used to re-scan the whole joined fragment after every
    # continuation, so a flow collection spread over N lines -- or one unclosed quote
    # anywhere above a large file -- cost O(N^2).  At 4000 lines that was ~19s; scanning
    # each character once it is ~0.03s.  The bound is loose enough for a slow machine and
    # still two orders of magnitude below a return to quadratic behaviour.
    import time as _time

    wide_flow = "a: [\n" + "".join(f'  "item{i}",\n' for i in range(4000)) + '  "z"\n]\n'
    started = _time.perf_counter()
    wide_value = fallback_yaml(wide_flow)
    flow_seconds = _time.perf_counter() - started
    check(
        "a flow collection spanning thousands of lines is read in linear time",
        isinstance(wide_value, dict)
        and len(wide_value.get("a", [])) == 4001
        and flow_seconds < 3.0,
        f"took {flow_seconds:.2f}s",
    )

    long_quote = 'a: "' + "\n".join("x" * 20 for _ in range(2000)) + '"\n'
    started = _time.perf_counter()
    fallback_yaml(long_quote)
    quote_seconds = _time.perf_counter() - started
    check(
        "a quoted scalar spanning thousands of lines is read in linear time",
        quote_seconds < 3.0,
        f"took {quote_seconds:.2f}s",
    )

    with tempfile.TemporaryDirectory() as raw:
        parity = pathlib.Path(raw)
        (parity / "protocol.yml").write_text("note: &base value\n")
        for fallback in (False, True):
            rc, out = run_validator(parity, fallback=fallback)
            check(
                f"load_yaml rejects anchors in {'fallback' if fallback else 'native'} mode",
                rc != 0 and "unsupported YAML anchor" in out,
                out,
            )

        parity_cases = (
            ("plain bracket text", "topic: draft [v2\n", 0),
            ("flow sequence structure", "topic: [v2\n", 1),
            ("reserved at indicator", "topic: @name\n", 1),
            ("reserved backtick indicator", "topic: `name\n", 1),
            ("allowed dash indicator", "topic: -foo\n", 0),
            ("allowed question indicator", "topic: ?foo\n", 0),
            ("allowed colon indicator", "topic: :foo\n", 0),
        )
        for label, source, expected_rc in parity_cases:
            (parity / "protocol.yml").write_text(source)
            verdicts = [
                run_validator(parity, fallback=fallback)[0] != 0
                for fallback in (False, True)
            ]
            check(
                f"forced bare/native YAML parity for {label}",
                verdicts == [bool(expected_rc), bool(expected_rc)],
            )

        (parity / "protocol.yml").write_text("topic: 0x10\n")
        parity_topic = parity / "protocol-topic.yml"
        parity_topic.write_text("topic: 0x10\n")
        verdicts = [
            run_validator(parity, fallback=fallback)[0] for fallback in (False, True)
        ]
        topic_values = []
        for fallback in (False, True):
            env = dict(os.environ)
            if fallback:
                env["ARS_FORCE_FALLBACK"] = "1"
            else:
                env.pop("ARS_FORCE_FALLBACK", None)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; sys.path.insert(0, sys.argv[1]); "
                        "from _yaml_subset import safe_load; "
                        "print(repr(safe_load('topic: 0x10\\n')));"
                    ),
                    str(ASSETS / "scripts"),
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            topic_values.append(probe.stdout.strip())
        check(
            "bundled YAML subset gives 0x10 the same verdict and value in both modes",
            verdicts == [0, 0]
            and topic_values == ["{'topic': '0x10'}", "{'topic': '0x10'}"],
        )
        block_path = parity / "protocol.yml"
        for label, source in (
            ("clipped", "items:\n  - note: |\n      first\n    other: value\n"),
            ("stripped", "question: |-\n  Does this parse?\n"),
            ("folded and stripped", "question: >-\n  Does this parse?\n"),
            ("kept", "question: |+\n  Does this parse?\n"),
        ):
            block_path.write_text(source)
            block_runs = [
                run_validator(parity, fallback=fallback) for fallback in (False, True)
            ]
            check(
                f"a {label} block scalar validates in both native and bare mode",
                [rc for rc, _out in block_runs] == [0, 0],
                "".join(out for _rc, out in block_runs),
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
    test_broken_fixture_reports_every_claimed_defect()
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
