# Everything runs through uv. `uv sync` once, then these.
# The dev toolchain is pinned by uv.lock, so these give the same answer as CI.

_default:
    @just --list --unsorted

# Resolve the dev toolchain from uv.lock
sync:
    uv sync

# Full suite, with pyyaml + jsonschema so structural checks run
test:
    uv run --group dev python tests/run_tests.py

# The path users actually hit: hooks must work in a bare python3 with no packages
test-bare:
    uv run --no-project python tests/run_tests.py

lint:
    uv run --group dev ruff check .claude/hooks/ scripts/ tests/ install.py src/
    uv run --group dev ruff format --check .claude/hooks/ scripts/ tests/ install.py src/

fmt:
    uv run --group dev ruff format .claude/hooks/ scripts/ tests/ install.py src/
    uv run --group dev ruff check --fix .claude/hooks/ scripts/ tests/ install.py src/

types:
    uv run --group dev basedpyright

# What CI runs. Green here means green there.
check: lint types test test-bare links

# Relative links break on a file move, and skills get installed where repo paths do not exist
links:
    #!/usr/bin/env -S uv run --group dev python
    import pathlib, re, sys
    bad = [f"{p}: dead link -> {link}"
           for p in pathlib.Path(".").rglob("*.md")
           if not ({".git", ".venv"} & set(p.parts))
           for link in re.findall(r"\]\((?!https?:|#)([^)#]+)", p.read_text())
           if not (p.parent / link).exists()]
    print("\n".join(bad) if bad else "no dead links")
    sys.exit(1 if bad else 0)

# Schema-check a survey state directory
validate dir:
    uv run --group dev python scripts/rs_validate.py {{dir}}

# Install the suite into a project
install path=".":
    uv run python install.py {{path}}

doctor path=".":
    uv run research-skills doctor {{path}}

# Build the wheel and prove it carries the assets
build:
    uv build
    unzip -l dist/*.whl | grep "research_skills/assets/.claude/skills/rs-survey/SKILL.md"
