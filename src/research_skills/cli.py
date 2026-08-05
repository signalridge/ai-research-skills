"""research-skills command line interface.

    research-skills install [path]      copy the suite into <path>/.claude/
    research-skills uninstall [path]    remove it, keeping foreign hooks
    research-skills doctor [path]       check an installation item by item

The repo-root install.py shim lands here too: dispatched on argv[0], it keeps
its pre-packaging interface (`python3 install.py [path] [--uninstall]`).
"""

from __future__ import annotations

import argparse
import os
import sys

from research_skills import __version__, hosts, installer


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="research-skills",
        description="Install the research-skills suite into a project's .claude/.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    for name, summary in (
        ("install", "copy the suite into <path>/.claude/ and merge its hooks"),
        ("uninstall", "remove the suite from <path>, keeping foreign hooks"),
        ("doctor", "check an installation: files, hook entries, backend env"),
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
    return ap


def main() -> int:
    if os.path.basename(sys.argv[0]) == "install.py":
        return installer.legacy_main(sys.argv[1:])

    args = build_parser().parse_args()
    root = os.path.abspath(args.root)
    if args.command == "install":
        return installer.install(root, args.host)
    if args.command == "uninstall":
        return installer.uninstall(root, args.host)
    return installer.doctor(root, args.host)


if __name__ == "__main__":
    sys.exit(main())
