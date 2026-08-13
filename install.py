#!/usr/bin/env python3
"""Checkout shim: ``python3 install.py [path] [--uninstall]``.

The real installer is the ai_research_skills package under ``src/``. From an installed copy,
use ``ai-research-skills install|uninstall|doctor|lint``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from ai_research_skills.cli import main

sys.exit(main())
