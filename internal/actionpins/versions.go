// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package actionpins

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// VersionsEnv is the file of the dev tool versions CI runs (#647);
// reusable-python-ci.yml fails when it and the requirements lock differ.
const VersionsEnv = "tools/versions.env"

// Requirement says whether a path is one of tools/requirements/*.in, the pip
// inputs Dependabot bumps.
func Requirement(path string) bool {
	rest, ok := strings.CutPrefix(path, "tools/requirements/")
	return ok && !strings.Contains(rest, "/") && strings.HasSuffix(rest, ".in")
}

var (
	// pinLine is one `name==version` requirement: 1 the name, 2 the version.
	pinLine = regexp.MustCompile(`^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._-]+)\s*(?:#.*)?$`)
	// envLine is one KEY=VALUE line of versions.env: 1 the key, 2 the value.
	envLine = regexp.MustCompile(`^([A-Z][A-Z0-9_]*)=(.*)$`)
)

// envKey is the versions.env key a package's pin sets: ruff -> RUFF_VERSION,
// shellcheck-py -> SHELLCHECK_PY_VERSION.
func envKey(name string) string {
	return strings.ToUpper(strings.NewReplacer("-", "_", ".", "_").Replace(name)) + "_VERSION"
}

// SyncVersions sets every versions.env key that names a package pinned in the
// requirements inputs (path -> text) to that pin (swarm-routing/.github#809).
// Only the value of an existing key changes; a pin with no key, and every other
// line, is left as it is. It returns the new text and one line per change, or
// an error when two inputs pin one package differently.
func SyncVersions(env string, reqs map[string]string) (string, []string, error) {
	want, from := map[string]string{}, map[string]string{}
	paths := make([]string, 0, len(reqs))
	for p := range reqs {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	for _, p := range paths {
		for _, line := range strings.Split(reqs[p], "\n") {
			m := pinLine.FindStringSubmatch(strings.TrimSpace(line))
			if m == nil {
				continue
			}
			key := envKey(m[1])
			if v, ok := want[key]; ok && v != m[2] {
				return "", nil, fmt.Errorf("%s pins %s==%s but %s pins %s", p, m[1], m[2], from[key], v)
			}
			want[key], from[key] = m[2], p
		}
	}
	lines := strings.Split(env, "\n")
	var changes []string
	for i, line := range lines {
		m := envLine.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if v, ok := want[m[1]]; ok && v != m[2] {
			lines[i] = m[1] + "=" + v
			changes = append(changes, fmt.Sprintf("%s: %s %s -> %s (%s)", VersionsEnv, m[1], m[2], v, from[m[1]]))
		}
	}
	return strings.Join(lines, "\n"), changes, nil
}
