"""Deprecated legacy hook placeholder.

Fresh installs do not run session-start checks.  A user may invoke ``ars-watch`` explicitly
when a literature update is wanted; this path remains only for legacy cleanup recognition.
"""

from __future__ import annotations


def main() -> None:
    """Do nothing; no automatic freshness check is active."""


if __name__ == "__main__":
    main()
