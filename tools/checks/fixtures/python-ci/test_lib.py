# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Imports lib.py from the second `source` directory (python-ci-lib), so the
report holds it only if every `source` item is measured (#530)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python-ci-lib"))

import lib  # noqa: E402

assert lib.double(21) == 42
print("test_lib: ok")
