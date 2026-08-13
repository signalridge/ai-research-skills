"""Deprecated hook compatibility placeholder.

ARS 0.8 does not install or dispatch runtime governance hooks.  The filename remains only
so a legacy path can be recognized and removed safely by the installer.
"""

from __future__ import annotations


def main() -> None:
    """Do nothing; legacy hook payload parsing is no longer active."""


if __name__ == "__main__":
    main()
