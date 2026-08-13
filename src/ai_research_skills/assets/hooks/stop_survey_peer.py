"""Deprecated legacy hook placeholder.

ARS 0.8 performs no automatic end-of-turn audit or peer check.  The filename remains only so
an older installed path can be recognized and removed safely.
"""

from __future__ import annotations


def main() -> None:
    """Do nothing; no automatic audit is active."""


if __name__ == "__main__":
    main()
