// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package fixture

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// sha256sum of "a\nb\n"
const abSum = "911169ddaaf146aff539f58c26c489af3b892dff0fe283c1c264c65ae5aa59a2"

type failing struct{}

func (failing) Read([]byte) (int, error) { return 0, errors.New("read error") }

func TestDescribe(t *testing.T) {
	if lines, sum, err := Describe(strings.NewReader("a\nb\n")); err != nil || lines != 2 || sum != abSum {
		t.Fatalf("Describe = %d, %q, %v", lines, sum, err)
	}
	if _, _, err := Describe(failing{}); err == nil {
		t.Fatal("a read error must be returned")
	}
}

func TestRun(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "in.txt")
	if err := os.WriteFile(p, []byte("a\nb\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if code := Run(nil, &out, &errOut); code != 2 || errOut.String() != "usage: fixture FILE...\n" {
		t.Fatalf("no path: %d %q", code, errOut.String())
	}
	out.Reset()
	errOut.Reset()
	// a missing file and a directory (opens, fails to read) are reported, the rest still runs
	code := Run([]string{filepath.Join(dir, "missing"), dir, p}, &out, &errOut)
	if want := p + " 2 " + abSum + "\n"; code != 1 || out.String() != want || strings.Count(errOut.String(), "\n") != 2 {
		t.Fatalf("Run = %d, %q, %q; want 1, %q and two errors", code, out.String(), errOut.String(), want)
	}
}
