// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command bestpractices is the OpenSSF Best Practices pipeline (see
// internal/bestpractices): `answers`, `register` and `check`.
package main

import (
	"os"

	"github.com/swarm-routing/.github/internal/bestpractices"
)

func main() {
	os.Exit(bestpractices.Main(os.Args[1:], bestpractices.Env{}, os.Stdout, os.Stderr))
}
