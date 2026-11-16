// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// Evidence a justification may cite (#559). A word in a workflow is not
// evidence: a comment, a step name or a description string that says
// "sanitizers" runs nothing. A workflow counts only when it runs in CI (on
// push, pull_request, merge_group or schedule, itself or through the
// workflow that calls it), and only for what its code (comments removed)
// does: a sanitizer flag, a fuzzer, a CodeQL analysis step, a reusable
// workflow called with the input that turns the tool on.

import (
	"regexp"
	"strings"
)

// ciEvents are the triggers that make a workflow CI: it runs on changes, or
// on a schedule, without anyone dispatching it.
var ciEvents = []string{"push", "pull_request", "merge_group", "schedule"}

// prEvents are the triggers that run a workflow before a change merges.
var prEvents = []string{"pull_request", "merge_group"}

func (w workflow) onAny(events []string) bool {
	for _, e := range events {
		if w.on[e] {
			return true
		}
	}
	return false
}

// stripComments removes YAML and shell comments: whole comment lines, and a
// trailing ` #...` outside quotes.
func stripComments(text string) string {
	lines := strings.Split(text, "\n")
	for i, l := range lines {
		if strings.HasPrefix(strings.TrimLeft(l, " \t"), "#") {
			lines[i] = ""
			continue
		}
		inS, inD := false, false
		for j := 0; j < len(l); j++ {
			switch c := l[j]; {
			case c == '\'' && !inD:
				inS = !inS
			case c == '"' && !inS:
				inD = !inD
			case c == '#' && !inS && !inD && j > 0 && (l[j-1] == ' ' || l[j-1] == '\t'):
				lines[i] = l[:j]
				j = len(l)
			}
		}
	}
	return strings.Join(lines, "\n")
}

var (
	onLine  = regexp.MustCompile(`^(?:on|"on"|'on'):\s*(.*)$`)
	onWord  = regexp.MustCompile(`[a-z_]+`)
	onKey   = regexp.MustCompile(`^\s*-?\s*([a-z_]+)`)
	localWF = regexp.MustCompile(`(?m)^\s*uses:\s*\./\.github/workflows/([^\s@]+)`)
)

var pathsKey = regexp.MustCompile(`^\s+paths(-ignore)?:`)

// triggersOf is the set of events in a workflow's top-level `on:`, and
// whether a paths filter limits them.
func triggersOf(code string) (map[string]bool, bool) {
	out := map[string]bool{}
	filtered := false
	lines := strings.Split(code, "\n")
	for i, l := range lines {
		m := onLine.FindStringSubmatch(l)
		if m == nil {
			continue
		}
		if rest := strings.TrimSpace(m[1]); rest != "" {
			for _, k := range onWord.FindAllString(rest, -1) {
				out[k] = true
			}
			return out, false
		}
		indent := -1
		for _, l2 := range lines[i+1:] {
			if strings.TrimSpace(l2) == "" {
				continue
			}
			ind := len(l2) - len(strings.TrimLeft(l2, " "))
			if ind == 0 {
				break
			}
			if indent < 0 {
				indent = ind
			}
			if ind == indent {
				if k := onKey.FindStringSubmatch(l2); k != nil {
					out[k[1]] = true
				}
			} else if pathsKey.MatchString(l2) {
				filtered = true
			}
		}
		return out, filtered
	}
	return out, false
}

// resolveTriggers gives a workflow this repository calls itself
// (`uses: ./.github/workflows/X`) the triggers of its callers. A reusable-*
// workflow is the org's contract for other repositories: its steps depend
// on inputs, and here it may run on fixtures, so it inherits nothing.
func resolveTriggers(ws []workflow) {
	byFile := map[string]int{}
	for i, w := range ws {
		byFile[strings.TrimPrefix(w.file, ".github/workflows/")] = i
	}
	for changed := true; changed; {
		changed = false
		for _, w := range ws {
			for _, m := range localWF.FindAllStringSubmatch(w.code, -1) {
				j, ok := byFile[m[1]]
				if !ok || strings.HasPrefix(m[1], "reusable-") {
					continue
				}
				for e := range w.on {
					if e != "workflow_call" && !ws[j].on[e] {
						ws[j].on[e] = true
						changed = true
					}
				}
			}
		}
	}
}

// callBlock is the job block that calls the org's reusable workflow name
// (`uses: .../<name>@...`): the uses line and the deeper lines after it,
// else "".
func callBlock(code, name string) string {
	rx := regexp.MustCompile(`^\s*uses:\s*\S*/` + regexp.QuoteMeta(name) + `(@\S*)?\s*$`)
	lines := strings.Split(code, "\n")
	for i, l := range lines {
		if !rx.MatchString(l) {
			continue
		}
		ind := len(l) - len(strings.TrimLeft(l, " "))
		block := []string{l}
		for _, l2 := range lines[i+1:] {
			if strings.TrimSpace(l2) != "" && len(l2)-len(strings.TrimLeft(l2, " ")) < ind {
				break
			}
			block = append(block, l2)
		}
		return strings.Join(block, "\n")
	}
	return ""
}

// input is the value a call block gives input key, and whether it gives one.
func input(block, key string) (string, bool) {
	m := regexp.MustCompile(`(?m)^\s+` + regexp.QuoteMeta(key) + `:[ \t]*(\S.*)$`).FindStringSubmatch(block)
	if m == nil {
		return "", false
	}
	return strings.TrimSpace(m[1]), true
}

// on is whether the input turns its tool on: given and not `false`, or, when
// not given, the reusable workflow's default.
func on(block, key string, dflt bool) bool {
	v, ok := input(block, key)
	if !ok {
		return dflt
	}
	return strings.Trim(v, `'"`) != "false"
}

// ns3Profile: the job calling reusable-ns3-ci.yml runs the profile (its
// default profiles are debug and sanitized).
func ns3Profile(code, profile string) bool {
	b := callBlock(code, "reusable-ns3-ci.yml")
	if b == "" {
		return false
	}
	v, ok := input(b, "profiles")
	return !ok || strings.Contains(v, profile)
}

// ciMatch is the URL of the first CI workflow on which match is true, else
// "": one that runs on every change before one a paths filter limits.
func (r *Repo) ciMatch(match func(workflow) bool, events []string) string {
	for _, filtered := range []bool{false, true} {
		for _, w := range r.workflows {
			if w.filtered == filtered && w.onAny(events) && match(w) {
				return r.url(w.file)
			}
		}
	}
	return ""
}

// ciURL is the first CI workflow whose code (comments removed) matches.
func (r *Repo) ciURL(pattern string) string {
	rx := regexp.MustCompile("(?im)" + pattern)
	return r.ciMatch(func(w workflow) bool { return rx.MatchString(w.code) }, ciEvents)
}

// prURL is ciURL for workflows that run on pull requests (or the merge queue).
func (r *Repo) prURL(pattern string) string {
	rx := regexp.MustCompile("(?im)" + pattern)
	return r.ciMatch(func(w workflow) bool { return rx.MatchString(w.code) }, prEvents)
}

func (r *Repo) runsOnPR(url string) bool {
	for _, w := range r.workflows {
		if r.url(w.file) == url {
			return w.onAny(prEvents)
		}
	}
	return false
}

// dockerProfile: a Dockerfile whose code (comments removed) matches pattern,
// built per profile (BUILD_PROFILE) by a CI workflow; the workflow's URL.
func (r *Repo) dockerProfile(pattern string) string {
	rx := regexp.MustCompile("(?m)" + pattern)
	found := false
	for _, f := range r.sorted {
		if (f == "Dockerfile" || strings.HasSuffix(f, "/Dockerfile")) && rx.MatchString(stripComments(r.text(f))) {
			found = true
			break
		}
	}
	if !found {
		return ""
	}
	return r.ciURL(`\bBUILD_PROFILE\b`)
}

// Patterns of real evidence, matched against workflow code.
const (
	// AddressSanitizer: every pattern here builds with it.
	sanRx = `-fsanitize=[\w,-]*address|\b\w+_SANITIZE=ON\b|--enable-sanitizers|ns3-dev:[^\s'"]*sanitized`
	// a fuzzer that runs
	fuzzRx = `-fsanitize=[\w,-]*fuzzer|\b\w+_FUZZ=ON\b|-max_total_time|\bgo\s+test\b[^\n]*\s-fuzz\b|\batheris\b|\bcifuzz\b`
	// assertions on: a debug build
	debugRx = `CMAKE_BUILD_TYPE=Debug\b|--enable-asserts|(^|[\s"'=])-d\s+debug\b|ns3-dev:[^\s'"]*debug`
	// a test run on Python code
	pyTestRx = `python3?\s[^\n]*(--self-test|\btest_\w*\.py)|-m\s+(unittest|pytest)\b|\bpytest\b|reusable-python-ci\.yml`
	// Python with assertions off
	pyOptRx = `python3?\s+-\w*O|PYTHONOPTIMIZE`
	// a test suite run
	testRunRx = `\bctest\b|--self-test|\bpytest\b|-m\s+unittest\b|\bgo\s+test\b|reusable-(ns3|python|go)-ci\.yml|` +
		`\bmake\s+(test|check)\b|\btest\.py\b|ns3-build-contrib\b[^\n]*--test|^\s*(\./)?test/run\.sh\b|` +
		`\bnode\s+\S*(test|smoke)\S*\.m?js|\bnpm\s+(run\s+)?test\b|\btest_\w*\.py\b`
	codeqlRx = `github/codeql-action/(init|analyze)@`
	sonarRx  = `SonarSource/\S+@|\bsonar-scanner\b`
	tidyRx   = `\b(run-)?clang-tidy\b`
	// linters of the repository's shell, Dockerfiles and workflows
	lintRx     = `hadolint/hadolint-action@|^\s*(hadolint|shellcheck|actionlint)\s|/actionlint"?\s`
	ruffRx     = `\bruff\s+(check|format)\b|reusable-python-ci\.yml`
	coverageRx = `codecov/codecov-action@|reusable-codecov\.yml|\bgcovr\b|--coverage\b|\bcoverage\s+run\b|` +
		`pytest-cov|-coverprofile|reusable-(python|go)-ci\.yml`
	strictRx = `--strict-warnings\b|-Werror\b`
)

// ns3CI: the workflow calls reusable-ns3-ci.yml with input key on.
func ns3CI(key string) func(workflow) bool {
	return func(w workflow) bool {
		b := callBlock(w.code, "reusable-ns3-ci.yml")
		return b != "" && on(b, key, false)
	}
}

// matches is a workflow test: its code matches pattern, or extra says so.
func matches(pattern string, extra ...func(workflow) bool) func(workflow) bool {
	rx := regexp.MustCompile("(?im)" + pattern)
	return func(w workflow) bool {
		if rx.MatchString(w.code) {
			return true
		}
		for _, f := range extra {
			if f(w) {
				return true
			}
		}
		return false
	}
}

func raceCI(w workflow) bool {
	if regexp.MustCompile(`\bgo\s+test\b[^\n]*\s-race\b`).MatchString(w.code) {
		return true
	}
	b := callBlock(w.code, "reusable-go-ci.yml")
	return b != "" && on(b, "race", true)
}

func sanCI(w workflow) bool   { return ns3Profile(w.code, "sanitized") }
func debugCI(w workflow) bool { return ns3Profile(w.code, "debug") }
