// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command security-autofix is the deterministic half of the security alert
// pipeline (see internal/securityautofix).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/securityautofix"
)

func main() {
	os.Exit(securityautofix.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.ReadFile, os.Stdout, os.Stderr))
}
