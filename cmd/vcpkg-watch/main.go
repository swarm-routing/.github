// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command vcpkg-watch keeps a ticket open for a release whose vcpkg port bump
// is missing (see internal/vcpkgwatch).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/vcpkgwatch"
)

func main() {
	os.Exit(vcpkgwatch.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
