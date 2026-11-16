# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""A tool the self-test only ever runs as a child process (python-ci-selftest.yml, #480)."""

import sys


def answer(words: list[str]) -> str:
    if words:
        return " ".join(reversed(words))
    return "nothing"


if __name__ == "__main__":
    print(answer(sys.argv[1:]))
