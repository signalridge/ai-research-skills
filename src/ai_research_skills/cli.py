"""ai-research-skills command line interface.

    ai-research-skills install [path]      configure the suite for selected host(s)
    ai-research-skills uninstall [path]    remove manifest-owned files/handlers only
    ai-research-skills doctor [path]       check an installation item by item

The repo-root install.py shim lands here too: dispatched on argv[0], it keeps
its pre-packaging interface (`python3 install.py [path] [--uninstall]`).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from ai_research_skills import __version__, hosts, installer


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ai-research-skills",
        description="Safely configure ai-research-skills in a project host.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    for name, summary in (
        ("install", "install standalone skills and optional command aliases into <path>"),
        ("uninstall", "remove manifest-owned skills and command aliases from <path>"),
        ("doctor", "inspect an installation and clean exact legacy governance state"),
    ):
        p = sub.add_parser(name, help=summary)
        p.add_argument(
            "root", nargs="?", default=".", help="target project root (default: cwd)"
        )
        p.add_argument(
            "--host",
            metavar="IDS",
            help="comma-separated hosts (default: whichever the project already uses, "
            "else claude). Known: " + ", ".join(hosts.known_ids()),
        )
    lint = sub.add_parser(
        "lint", help="explicitly lint selected/present research artifacts"
    )
    lint.add_argument("survey_dir", nargs="?", default=".", help="artifact directory")
    lint.add_argument(
        "--strict", action="store_true", help="treat linter warnings as errors"
    )
    return ap


def main() -> int:
    if os.path.basename(sys.argv[0]) == "install.py":
        return installer.legacy_main(sys.argv[1:])

    args = build_parser().parse_args()
    if args.command == "lint":
        validator = Path(installer.SRC_SCRIPTS) / "rs_validate.py"
        command = [sys.executable, str(validator)]
        if args.strict:
            command.append("--strict")
        command.append(os.path.abspath(args.survey_dir))
        return subprocess.run(command, check=False).returncode
    root = os.path.abspath(args.root)
    if args.command == "install":
        return installer.install(root, args.host)
    if args.command == "uninstall":
        return installer.uninstall(root, args.host)
    if args.command == "doctor":
        return installer.doctor(root, args.host)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
