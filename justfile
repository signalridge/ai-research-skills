# Everything runs through uv. `uv sync` once, then these.
# The dev toolchain is pinned by uv.lock, so these give the same answer as CI.

_default:
    @just --list --unsorted

# Resolve the dev toolchain from uv.lock, then dogfood the suite into this checkout.
# The assets live in src/ai_research_skills/assets/; .claude/ is install output and is gitignored,
# so a fresh clone has no skills active until this runs.
sync:
    uv sync
    uv run python install.py .

# Full suite, with pyyaml + jsonschema for the optional scoped linter
test:
    uv run --group dev python tests/run_tests.py

# The path users actually hit: hooks must work in a bare python3 with no packages.
#
# Run from elsewhere on purpose. `uv run --no-project` still discovers ./.venv when the
# cwd is the project, so this recipe used to reuse the dev toolchain and pass locally
# while the same command failed in CI, where no venv exists. `--python 3.13` pins an
# interpreter the project venv cannot satisfy, so uv has to provision a clean one.
test-bare:
    cd "$(mktemp -d)" && uv run --no-project --python 3.13 python {{justfile_directory()}}/tests/run_tests.py

lint:
    uv run --group dev ruff check src/ tests/ install.py
    uv run --group dev ruff format --check src/ tests/ install.py

fmt:
    uv run --group dev ruff format src/ tests/ install.py
    uv run --group dev ruff check --fix src/ tests/ install.py

types:
    uv run --group dev basedpyright

# Parse every shipped/configured JSON and YAML file, matching the CI lint job.
data:
    #!/usr/bin/env -S uv run --group dev python
    import json, pathlib, sys, yaml
    bad = []
    skip = {".git", ".venv", "node_modules", "__pycache__", ".claude", "dist"}
    for pattern, load in (("*.json", json.loads), ("*.yml", yaml.safe_load),
                          ("*.yaml", yaml.safe_load)):
        for path in pathlib.Path(".").rglob(pattern):
            if skip & set(path.parts):
                continue
            try:
                load(path.read_text())
            except Exception as exc:
                bad.append(f"{path}: {exc}")
    print("\n".join(bad) if bad else "json/yaml parse: ok")
    sys.exit(1 if bad else 0)

# Validate the frontmatter contract consumed by host skill listings.
skills:
    #!/usr/bin/env -S uv run --group dev python
    import pathlib, re, sys, yaml
    bad = []
    paths = sorted(pathlib.Path("src/ai_research_skills/assets/skills").glob("*/SKILL.md"))
    for path in paths:
        match = re.match(r"^---\n(.*?)\n---", path.read_text(), re.S)
        if not match:
            bad.append(f"{path}: no frontmatter")
            continue
        frontmatter = yaml.safe_load(match.group(1))
        if not frontmatter.get("name"):
            bad.append(f"{path}: no name")
        if not frontmatter.get("description"):
            bad.append(f"{path}: no description")
        length = len(" ".join(str(frontmatter.get("description", "")).split()))
        if length > 1536:
            bad.append(f"{path}: description {length} chars, over the 1536 cap")
    print("\n".join(bad) if bad else f"skill frontmatter: ok ({len(paths)} skills)")
    sys.exit(1 if bad else 0)

# What CI runs. Green here means green there.
check: lint types data skills test test-bare links

# Relative links break on a file move, and skills get installed where repo paths do not exist
links:
    #!/usr/bin/env -S uv run --group dev python
    import pathlib, re, sys
    bad = [f"{p}: dead link -> {link}"
           for p in pathlib.Path(".").rglob("*.md")
           if not ({".git", ".venv", ".claude", "dist"} & set(p.parts))
           for link in re.findall(r"\]\((?!https?:|#)([^)#]+)", p.read_text())
           if not (p.parent / link).exists()]
    print("\n".join(bad) if bad else "no dead links")
    sys.exit(1 if bad else 0)

# Explicitly lint the present artifacts in a research directory
validate dir:
    uv run --group dev python src/ai_research_skills/assets/scripts/rs_validate.py {{dir}}

# Install the suite into a project
install path=".":
    uv run python install.py {{path}}

doctor path=".":
    uv run ai-research-skills doctor {{path}}

# Build the wheel and prove it carries the assets. dist/ is cleared first: `unzip -l`
# takes one archive, so a stale wheel from an older version would be the one inspected.
build:
    rm -rf dist
    uv build
    unzip -l dist/*.whl | grep "ai_research_skills/assets/skills/ars-survey/SKILL.md"
