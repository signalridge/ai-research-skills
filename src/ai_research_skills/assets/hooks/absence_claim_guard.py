"""Deprecated legacy hook placeholder.

Fresh ARS installs do not configure hooks.  Absence claims are handled as an explicit,
human-visible literature-integrity guideline by the invoked skills; this file exists only so
an older installed path can be identified during cleanup.
"""

from __future__ import annotations


def main() -> None:
    """Do nothing; no write-time governance is active."""


if __name__ == "__main__":
    main()
