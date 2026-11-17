// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command release-sync-watch dispatches the site's release-sync.yml for a release
// the site missed (see internal/releasesync).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/releasesync"
)

func main() {
	os.Exit(releasesync.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
