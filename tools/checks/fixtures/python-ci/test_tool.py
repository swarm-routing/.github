# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""Runs tool.py only as `python3 -I tool.py`, from another directory, as a user
would; never imports it. reusable-python-ci.yml counts tool.py's lines only if
it measures child processes (python-ci-selftest.yml, #480)."""

import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "tool.py"

with tempfile.TemporaryDirectory() as cwd:
    for args, want in ((["a", "b"], "b a"), ([], "nothing")):
        out = subprocess.run(
            [sys.executable, "-I", str(TOOL), *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert out == want, (args, out)
print("test_tool: ok")
