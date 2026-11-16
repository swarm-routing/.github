// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package fixture is the ci-tools image's fixture tool: it proves the image
// runs a tool on the workspace a workflow mounts, with output a test can
// compute independently (wc -l and sha256sum).
package fixture

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
)

// Describe returns the number of newlines in r and its SHA-256, in hex.
func Describe(r io.Reader) (int, string, error) {
	h := sha256.New()
	lines := 0
	buf := make([]byte, 32*1024)
	for {
		n, err := r.Read(buf)
		for _, b := range buf[:n] {
			if b == '\n' {
				lines++
			}
		}
		h.Write(buf[:n])
		if err == io.EOF {
			return lines, hex.EncodeToString(h.Sum(nil)), nil
		}
		if err != nil {
			return 0, "", err
		}
	}
}

// Run prints one line per path, "<path> <lines> <sha256>", and returns 1 if
// a path could not be read (after the others), 2 when no path is given.
func Run(paths []string, stdout, stderr io.Writer) int {
	if len(paths) == 0 {
		fmt.Fprintln(stderr, "usage: fixture FILE...")
		return 2
	}
	code := 0
	for _, p := range paths {
		f, err := os.Open(p)
		if err != nil {
			fmt.Fprintf(stderr, "fixture: %v\n", err)
			code = 1
			continue
		}
		lines, sum, err := Describe(f)
		f.Close()
		if err != nil {
			fmt.Fprintf(stderr, "fixture: %s: %v\n", p, err)
			code = 1
			continue
		}
		fmt.Fprintf(stdout, "%s %d %s\n", p, lines, sum)
	}
	return code
}
