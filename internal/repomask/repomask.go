// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package repomask names repositories in a tool's output, which a public
// workflow log holds: a public repository by the name the tool chooses, a
// private one as "private repository N" (N counts the private repositories in
// the order the tool first names them), and Scrub takes a private
// repository's name out of any other text, an error message for one
// (swarm-routing/.github#622). Every org tool that prints repository names
// goes through a Masker.
package repomask

import (
	"fmt"
	"sort"
	"strings"
)

// Hidden replaces a private repository's name inside other text.
const Hidden = "<private>"

// Masker remembers the private repositories it has named. The zero value is
// ready to use.
type Masker struct {
	labels  map[string]string // the first secret of a private repository -> its label
	secrets []string          // every secret seen, longest first
}

// Repo returns how to name a repository in the output: shown for a public
// one, "private repository N" for a private one. secrets are the strings
// that name the repository (its full name, its bare name); the first one
// identifies it, so naming it again returns the same label, and Scrub takes
// every one of them out of other text.
func (m *Masker) Repo(shown string, private bool, secrets ...string) string {
	if !private {
		return shown
	}
	if len(secrets) == 0 {
		secrets = []string{shown}
	}
	if m.labels == nil {
		m.labels = map[string]string{}
	}
	if l, ok := m.labels[secrets[0]]; ok {
		return l
	}
	l := fmt.Sprintf("private repository %d", len(m.labels)+1)
	m.labels[secrets[0]] = l
	for _, s := range secrets {
		if s != "" {
			m.secrets = append(m.secrets, s)
		}
	}
	// longest first, so a full name goes before the bare name inside it
	sort.SliceStable(m.secrets, func(i, j int) bool { return len(m.secrets[i]) > len(m.secrets[j]) })
	return l
}

// Scrub replaces every secret of every private repository named so far with
// Hidden.
func (m *Masker) Scrub(s string) string {
	for _, x := range m.secrets {
		s = strings.ReplaceAll(s, x, Hidden)
	}
	return s
}

// Error is Scrub on an error's message (nil stays nil).
func (m *Masker) Error(err error) error {
	if err == nil {
		return nil
	}
	return scrubbed{err, m.Scrub(err.Error())}
}

// scrubbed keeps the original error for errors.Is and errors.As.
type scrubbed struct {
	err error
	msg string
}

func (e scrubbed) Error() string { return e.msg }
func (e scrubbed) Unwrap() error { return e.err }
