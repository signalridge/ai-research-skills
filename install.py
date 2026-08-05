#!/usr/bin/env python3
"""Thin shim so a checkout keeps working: python3 install.py [path] [--uninstall].

The real installer is the research_skills package in src/; run from an
installed copy prefer `research-skills install|uninstall|doctor` instead.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from research_skills.cli import main

sys.exit(main())
