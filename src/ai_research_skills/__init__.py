"""ai-research-skills: a survey-first research suite for AI/ML."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: pyproject.toml. A hardcoded copy here drifts the moment
    # one of the two is bumped and the other is not.
    __version__ = version("ai-research-skills")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0+unknown"

__all__ = ["__version__"]
