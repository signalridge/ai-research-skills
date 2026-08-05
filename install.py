#!/usr/bin/env python3
"""Thin shim so a checkout keeps working: python3 install.py [path] [--uninstall].

The real installer is the ai_research_skills package under src/; from an installed
copy prefer `ai-research-skills install|uninstall|doctor` instead.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from ai_research_skills.cli import main

sys.exit(main())
