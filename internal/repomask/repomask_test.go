// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package repomask

import (
	"errors"
	"io/fs"
	"strings"
	"testing"
)

func TestRepo(t *testing.T) {
	var m Masker
	if got := m.Repo("swarm-routing/open", false, "swarm-routing/open", "open"); got != "swarm-routing/open" {
		t.Errorf("a public repository keeps its name: %q", got)
	}
	a := m.Repo("swarm-routing/secret-lib", true, "swarm-routing/secret-lib", "secret-lib")
	b := m.Repo("hidden-two", true)
	again := m.Repo("anything", true, "swarm-routing/secret-lib")
	if a != "private repository 1" || b != "private repository 2" || again != a {
		t.Errorf("labels: %q %q %q", a, b, again)
	}
	if m.Scrub("open") != "open" {
		t.Error("a public name is never scrubbed")
	}
}

func TestScrub(t *testing.T) {
	var m Masker
	if m.Scrub("repos/swarm-routing/secret-lib") != "repos/swarm-routing/secret-lib" {
		t.Error("nothing is scrubbed before a private repository is named")
	}
	m.Repo("x", true, "swarm-routing/secret-lib", "secret-lib")
	got := m.Scrub("GET repos/swarm-routing/secret-lib/pulls: secret-lib not found")
	if got != "GET repos/<private>/pulls: <private> not found" {
		t.Errorf("scrub: %q", got)
	}
	err := m.Error(&fs.PathError{Op: "open", Path: "secret-lib", Err: fs.ErrNotExist})
	if strings.Contains(err.Error(), "secret-lib") || !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("an error is scrubbed and keeps its cause: %v", err)
	}
	if m.Error(nil) != nil {
		t.Error("nil stays nil")
	}
}
