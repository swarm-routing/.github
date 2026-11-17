// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command labels applies labels.json to every org repository, private ones
// included, and never deletes a label (see internal/labels).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/labels"
)

func main() {
	os.Exit(labels.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
