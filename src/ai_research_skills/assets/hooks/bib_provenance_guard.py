"""Deprecated legacy hook placeholder.

Citation provenance is checked only when the user explicitly invokes a research skill or the
optional linter.  This old write-time hook is not installed in ARS 0.8 and remains only as a
recognizable legacy path for safe cleanup.
"""

from __future__ import annotations


def main() -> None:
    """Do nothing; no write-time governance is active."""


if __name__ == "__main__":
    main()
