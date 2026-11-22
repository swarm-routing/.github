// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package actionpins keeps the third-party action pins of templates/ at the
// pins this repository's own workflows use (swarm-routing/.github#773).
//
// Dependabot scans .github/workflows/ and .github/actions/*/ here, never
// templates/, so the pins org-sync renders into every repository would never
// move at the source. The rule: every `uses: <owner>/<repo>[/<path>]@<sha> #
// <version>` under templates/ names the commit and the version comment that
// .github/workflows/ and .github/actions/ use for the same owner/repo. Sync
// checks it (CI, `action-pins`) and writes it (`action-pins --write`, and the
// sweep, which commits it onto Dependabot's pull requests here). An action
// pinned only in templates/ is an error: nothing would ever bump it.
// swarm-routing/.github's own workflows and actions are not this rule's: they
// follow .github/org-sync.lock (ADR-0004).
package actionpins

import (
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// usesLine is one `uses: owner/repo[/path]@<40-hex sha>` with an optional
// `# <version>` comment: 1 the text before the action, 2 owner/repo,
// 3 /path, 4 the sha, 5 the comment with its leading space, 6 the version.
var usesLine = regexp.MustCompile(`(?m)^(\s*(?:-\s+)?uses:\s*)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)((?:/[A-Za-z0-9_.-]+)*)@([0-9a-f]{40})([ \t]*#[ \t]*(\S+))?`)

// Pin is one action's commit and its version comment ("" when none).
type Pin struct {
	SHA     string
	Version string
}

func (p Pin) String() string {
	if p.Version == "" {
		return p.SHA[:12]
	}
	return p.SHA[:12] + " (" + p.Version + ")"
}

// Source says whether a path is one Dependabot moves here: a workflow, or a
// composite action's action.yml.
func Source(path string) bool {
	if strings.HasPrefix(path, ".github/workflows/") && !strings.Contains(path[len(".github/workflows/"):], "/") {
		return strings.HasSuffix(path, ".yml") || strings.HasSuffix(path, ".yaml")
	}
	if strings.HasPrefix(path, ".github/actions/") {
		parts := strings.Split(path, "/")
		return len(parts) == 4 && (parts[3] == "action.yml" || parts[3] == "action.yaml")
	}
	return false
}

// Template says whether a path is one org-sync renders from: anything under templates/.
func Template(path string) bool { return strings.HasPrefix(path, "templates/") }

// own is swarm-routing/.github itself, pinned by org-sync.lock instead.
func own(repo string) bool { return strings.EqualFold(repo, "swarm-routing/.github") }

// Finding is one template pin that is not the source's, or cannot be.
type Finding struct {
	Path   string
	Line   int
	Action string
	Have   Pin
	Want   Pin    // zero when Err is set
	Err    string // the pin cannot be synced: why
}

func (f Finding) String() string {
	if f.Err != "" {
		return fmt.Sprintf("error     %s:%d: %s: %s", f.Path, f.Line, f.Action, f.Err)
	}
	return fmt.Sprintf("drift     %s:%d: %s at %s, .github/workflows at %s", f.Path, f.Line, f.Action, f.Have, f.Want)
}

// Pins reads the source pins of files (path -> text): one Pin per
// owner/repo, or an error when the sources disagree (a bump half applied).
func Pins(files map[string]string) (map[string]Pin, error) {
	seen := map[string]map[Pin][]string{}
	for _, path := range sorted(files) {
		if !Source(path) {
			continue
		}
		for _, m := range usesLine.FindAllStringSubmatch(files[path], -1) {
			if own(m[2]) {
				continue
			}
			p := Pin{m[4], m[6]}
			if seen[m[2]] == nil {
				seen[m[2]] = map[Pin][]string{}
			}
			seen[m[2]][p] = append(seen[m[2]][p], path)
		}
	}
	out := map[string]Pin{}
	var bad []string
	for repo, pins := range seen {
		if len(pins) > 1 {
			var all []string
			for p, paths := range pins {
				all = append(all, fmt.Sprintf("%s in %s", p, strings.Join(dedup(paths), ", ")))
			}
			sort.Strings(all)
			bad = append(bad, fmt.Sprintf("%s has %d pins: %s", repo, len(pins), strings.Join(all, "; ")))
			continue
		}
		for p := range pins {
			out[repo] = p
		}
	}
	if len(bad) > 0 {
		sort.Strings(bad)
		return nil, fmt.Errorf("the workflows here disagree, so no template pin can follow them:\n  %s", strings.Join(bad, "\n  "))
	}
	return out, nil
}

// Sync returns the template files whose pins it changed (path -> new text)
// and every finding, in path and line order.
func Sync(files map[string]string) (map[string]string, []Finding, error) {
	pins, err := Pins(files)
	if err != nil {
		return nil, nil, err
	}
	changed := map[string]string{}
	var found []Finding
	for _, path := range sorted(files) {
		if !Template(path) {
			continue
		}
		text := files[path]
		var b strings.Builder
		last := 0
		for _, ix := range usesLine.FindAllStringSubmatchIndex(text, -1) {
			g := func(i int) string {
				if ix[2*i] < 0 {
					return ""
				}
				return text[ix[2*i]:ix[2*i+1]]
			}
			repo := g(2)
			if own(repo) {
				continue
			}
			have := Pin{g(4), g(6)}
			line := 1 + strings.Count(text[:ix[0]], "\n")
			want, ok := pins[repo]
			if !ok {
				found = append(found, Finding{Path: path, Line: line, Action: repo + g(3), Have: have,
					Err: "pinned only in templates/: no workflow here uses it, so Dependabot never bumps it; use it in one, or drop it"})
				continue
			}
			if want == have {
				continue
			}
			found = append(found, Finding{Path: path, Line: line, Action: repo + g(3), Have: have, Want: want})
			comment := ""
			if want.Version != "" {
				comment = " # " + want.Version
			}
			b.WriteString(text[last:ix[0]])
			b.WriteString(g(1) + repo + g(3) + "@" + want.SHA + comment)
			last = ix[1]
		}
		if last > 0 {
			b.WriteString(text[last:])
			changed[path] = b.String()
		}
	}
	return changed, found, nil
}

func sorted(files map[string]string) []string {
	keys := make([]string, 0, len(files))
	for k := range files {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func dedup(xs []string) []string {
	var out []string
	for i, x := range xs {
		if i == 0 || xs[i-1] != x {
			out = append(out, x)
		}
	}
	return out
}

// Read is every source and template file under dir (slash paths).
func Read(dir string) (map[string]string, error) {
	files := map[string]string{}
	for _, root := range []string{".github/workflows", ".github/actions", "templates"} {
		err := filepath.WalkDir(filepath.Join(dir, root), func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				if os.IsNotExist(err) && p == filepath.Join(dir, root) {
					return fs.SkipDir
				}
				return err
			}
			if d.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(dir, p)
			if err != nil {
				return err
			}
			rel = filepath.ToSlash(rel)
			if !Source(rel) && !Template(rel) {
				return nil
			}
			data, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			files[rel] = string(data)
			return nil
		})
		if err != nil {
			return nil, err
		}
	}
	return files, nil
}

// Fix is the command a failed check prints.
const Fix = "go run ./cmd/action-pins --write ."

// Local checks (write false) or writes the template pins of the checkout at
// dir; it returns the exit code: 0 in step, 1 drift or an unsyncable pin, 2
// an error.
func Local(dir string, write bool, out io.Writer) int {
	files, err := Read(dir)
	if err != nil {
		fmt.Fprintln(out, "action-pins:", err)
		return 2
	}
	changed, found, err := Sync(files)
	if err != nil {
		fmt.Fprintln(out, "action-pins:", err)
		return 1
	}
	drift, bad := 0, 0
	for _, f := range found {
		fmt.Fprintln(out, f)
		if f.Err != "" {
			bad++
		} else {
			drift++
		}
	}
	if write {
		for _, path := range sorted(changed) {
			fi, err := os.Stat(filepath.Join(dir, path))
			if err != nil {
				fmt.Fprintln(out, "action-pins:", err)
				return 2
			}
			if err := os.WriteFile(filepath.Join(dir, path), []byte(changed[path]), fi.Mode().Perm()); err != nil {
				fmt.Fprintln(out, "action-pins:", err)
				return 2
			}
			fmt.Fprintf(out, "update    %s\n", path)
		}
	}
	switch {
	case bad > 0:
		fmt.Fprintf(out, "action-pins: %d template pins no workflow here uses\n", bad)
		return 1
	case drift > 0 && !write:
		fmt.Fprintf(out, "action-pins: %d template pins are not the pins of .github/workflows; run: %s\n", drift, Fix)
		return 1
	case drift > 0:
		fmt.Fprintf(out, "action-pins: %d template pins moved to the pins of .github/workflows\n", drift)
	default:
		fmt.Fprintf(out, "action-pins: %d template files at the pins of .github/workflows\n", countTemplates(files))
	}
	return 0
}

func countTemplates(files map[string]string) int {
	n := 0
	for p, text := range files {
		if Template(p) && usesLine.MatchString(text) {
			n++
		}
	}
	return n
}
