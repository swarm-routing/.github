// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package dispatch is the ci-tools image's entrypoint logic: `ci-tools <tool>
// [args...]` runs /usr/local/bin/<tool> in place of itself. The runtime image
// is distroless (no shell), so this is the one way into it besides naming a
// tool's path as the entrypoint.
package dispatch

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
)

// Self is the dispatcher's own name; it is never a tool.
const Self = "ci-tools"

// maxTools bounds a listing (golden rule 7): the image holds a handful.
const maxTools = 256

var toolName = regexp.MustCompile(`^[a-z][a-z0-9-]{0,63}$`)

// ExecFunc replaces the process with path (syscall.Exec in main).
type ExecFunc func(path string, argv []string, env []string) error

// Resolve returns the path of tool name in dir: a plain name (lowercase,
// digits, dashes), never the dispatcher, a regular executable file.
func Resolve(dir, name string) (string, error) {
	if !toolName.MatchString(name) || name == Self {
		return "", fmt.Errorf("%q is not a tool name", name)
	}
	p := filepath.Join(dir, name)
	fi, err := os.Stat(p)
	if err != nil {
		return "", fmt.Errorf("no tool %q", name)
	}
	if !fi.Mode().IsRegular() || fi.Mode().Perm()&0o111 == 0 {
		return "", fmt.Errorf("%q is not an executable file", name)
	}
	return p, nil
}

// List returns the tools in dir, sorted.
func List(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range entries {
		if _, err := Resolve(dir, e.Name()); err == nil {
			out = append(out, e.Name())
		}
		if len(out) == maxTools {
			return nil, errors.New("too many tools")
		}
	}
	sort.Strings(out)
	return out, nil
}

// Main runs the dispatcher on args (os.Args[1:]) and returns the exit code
// when it does not exec: 0 for `list`, 2 for a usage error.
func Main(args []string, dir string, env []string, stdout, stderr io.Writer, exec ExecFunc) int {
	if len(args) == 0 || args[0] == "list" || args[0] == "-h" || args[0] == "--help" {
		tools, err := List(dir)
		if err != nil {
			fmt.Fprintf(stderr, "%s: %v\n", Self, err)
			return 1
		}
		w := stdout
		if len(args) == 0 {
			w = stderr
			fmt.Fprintf(w, "usage: %s <tool> [args...]   (%s list: the tools)\n", Self, Self)
		}
		for _, t := range tools {
			fmt.Fprintln(w, t)
		}
		if len(args) == 0 {
			return 2
		}
		return 0
	}
	p, err := Resolve(dir, args[0])
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v (%s list: the tools)\n", Self, err, Self)
		return 2
	}
	if err := exec(p, args, env); err != nil {
		fmt.Fprintf(stderr, "%s: %s: %v\n", Self, args[0], err)
		return 1
	}
	return 0
}
