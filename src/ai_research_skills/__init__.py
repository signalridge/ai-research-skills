"""ai-research-skills: a survey-first research suite for AI/ML."""

from importlib.metadata import distributions
from pathlib import Path

_FALLBACK_VERSION = "0.6.0"
_PACKAGE_INIT = Path("ai_research_skills") / "__init__.py"


def _metadata_version() -> str | None:
    """Use metadata only when it names the package currently being imported."""
    imported_path = Path(__file__).resolve()
    versions: set[str] = set()
    for distribution in distributions():
        try:
            name = distribution.metadata["Name"]
        except (KeyError, TypeError, AttributeError):
            continue
        if not isinstance(name, str) or name.casefold() != "ai-research-skills":
            continue
        try:
            package_path = Path(str(distribution.locate_file(str(_PACKAGE_INIT)))).resolve()
            version = distribution.version
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if package_path == imported_path and isinstance(version, str):
            versions.add(version)
    return versions.pop() if len(versions) == 1 else None


__version__ = _metadata_version() or _FALLBACK_VERSION

__all__ = ["__version__"]
