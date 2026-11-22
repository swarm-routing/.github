// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command ticket-audit closes the org's finished issues and keeps the
// "[tickets] audit" summary (see internal/ticketaudit).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/ticketaudit"
)

func main() {
	os.Exit(ticketaudit.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
