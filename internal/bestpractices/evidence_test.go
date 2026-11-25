// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// #559: a justification cites what a CI workflow runs, never a word in one.

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// repoOf writes files into a fresh directory and derives its answers.
func repoOf(t *testing.T, name string, files map[string]string) Answers {
	t.Helper()
	d := filepath.Join(t.TempDir(), name)
	for rel, text := range files {
		p := filepath.Join(d, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	a, err := Derive(d, Org+"/"+name, "2026-11-16")
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func wantStatus(t *testing.T, a Answers, want string, cs ...string) {
	t.Helper()
	for _, c := range cs {
		if got := status(a, c); got != want {
			t.Errorf("%s: want %s, got %s (%s)", c, want, got, why(a, c))
		}
	}
}

// metadata is .github's repo-metadata.yml in small: a manual workflow whose
// description strings name sanitizers, fuzzing and assertions.
const metadata = `name: repo metadata
on:
  workflow_dispatch:
jobs:
  apply:
    runs-on: ubuntu-24.04
    steps:
      - run: |
          apply sim-containers "debug, sanitized and optimized images" ci sanitizers fuzz assert codeql sonar
`

// Swarm-routing/.github#559 as it was found: a Python repository whose only
// mention of sanitizers is a topic in a manual workflow.
func TestWordsAreNotEvidencePython(t *testing.T) {
	a := repoOf(t, "Py", map[string]string{
		"README.md":                           "x\n",
		"tools/x.py":                          "x = 1\n",
		".github/workflows/repo-metadata.yml": metadata,
		".github/workflows/ci.yml": `on:
  pull_request:
jobs:
  lint:
    steps:
      # the tests run under sanitizers and a fuzzer, with --self-test: not here
      - run: ruff check tools
      - run: trivy=$(sed -n 's/^TRIVY=//p' test/run.sh)
`,
	})
	wantStatus(t, a, "?", "dynamic_analysis", "dynamic_analysis_fixed", "dynamic_analysis_enable_assertions",
		"test_continuous_integration", "static_analysis_common_vulnerabilities")
	for _, x := range a {
		if strings.Contains(x.Why, "repo-metadata.yml") {
			t.Errorf("%s cites repo-metadata.yml: %s", x.Criterion, x.Why)
		}
	}
}

// Every word an old matcher took for evidence, in a C++ repository: in
// comments, step names, a SARIF upload, a disabled input, a profile that is
// not run, a reusable workflow nothing here calls, a file name.
func TestWordsAreNotEvidenceCxx(t *testing.T) {
	a := repoOf(t, "Cxx", map[string]string{
		"README.md":                           "x\n",
		"CMakeLists.txt":                      "add_compile_options(-Wall)\n",
		"src/a.cc":                            "int a;\n",
		".github/workflows/repo-metadata.yml": metadata,
		".github/workflows/ci.yml": `on:
  pull_request:
  push:
jobs:
  scan:
    name: codeql, sanitizers and fuzz
    steps:
      - run: echo build  # -fsanitize=address -DX_SANITIZE=ON CMAKE_BUILD_TYPE=Debug ctest
      - uses: github/codeql-action/upload-sarif@0000000000000000000000000000000000000000 # v4
      - run: trivy=$(sed -n 's/^TRIVY=//p' test/run.sh)
  ns3:
    uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main
    with:
      profiles: '["optimized"]'
      sonar: false
`,
		".github/workflows/reusable-x.yml": `on:
  workflow_call:
jobs:
  san:
    steps:
      - run: cmake -DCMAKE_CXX_FLAGS=-fsanitize=address -DCMAKE_BUILD_TYPE=Debug && ctest
      - uses: github/codeql-action/analyze@0000000000000000000000000000000000000000 # v4
`,
		".github/workflows/fuzz.yml": "on: [pull_request]\njobs:\n  fuzz: {}\n",
	})
	wantStatus(t, a, "?", "dynamic_analysis", "dynamic_analysis_fixed", "dynamic_analysis_unsafe",
		"dynamic_analysis_enable_assertions", "static_analysis", "static_analysis_common_vulnerabilities",
		"static_analysis_often")
}

// What does count: steps that run, reusable workflows called with the input
// that turns the tool on, and a workflow this repository calls itself.
func TestRealEvidence(t *testing.T) {
	ns3 := repoOf(t, "Ns3", map[string]string{
		"README.md":  "x\n",
		"model/a.cc": "int a;\n",
		".github/workflows/ns3.yml": `on:
  pull_request:
jobs:
  ci:
    uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main
    with:
      strict-warnings: true
      sonar: ${{ inputs.ns3-versions == '' }}
`,
	})
	wantStatus(t, ns3, "Met", "dynamic_analysis", "dynamic_analysis_fixed", "dynamic_analysis_unsafe",
		"dynamic_analysis_enable_assertions", "static_analysis", "static_analysis_common_vulnerabilities",
		"test_continuous_integration", "warnings_strict")
	if !strings.Contains(why(ns3, "static_analysis_common_vulnerabilities"), "SonarQube Cloud") {
		t.Error("sonar on: SonarQube Cloud")
	}

	local := repoOf(t, "Local", map[string]string{
		"README.md":      "x\n",
		"core/a.cc":      "int a;\n",
		"core/test/t.cc": "int t;\n",
		".github/workflows/ci.yml": `on:
  pull_request:
jobs:
  core:
    uses: ./.github/workflows/ci-core.yml
`,
		".github/workflows/ci-core.yml": `on:
  workflow_call:
jobs:
  san:
    steps:
      - run: |
          cmake -S core -B b -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined"
          ctest --test-dir b
`,
	})
	wantStatus(t, local, "Met", "dynamic_analysis", "dynamic_analysis_fixed", "dynamic_analysis_unsafe",
		"dynamic_analysis_enable_assertions", "test_continuous_integration")
	if !strings.Contains(why(local, "dynamic_analysis"), "ci-core.yml") {
		t.Error("the called workflow is the evidence")
	}

	goRace := repoOf(t, "Go", map[string]string{
		"README.md": "x\n",
		"main.go":   "package main\n",
		".github/workflows/ci.yml": `on: [pull_request, push]
jobs:
  go:
    uses: swarm-routing/.github/.github/workflows/reusable-go-ci.yml@main
`,
	})
	wantStatus(t, goRace, "Met", "dynamic_analysis", "dynamic_analysis_fixed")
	if !strings.Contains(why(goRace, "dynamic_analysis"), "race detector") {
		t.Error("reusable-go-ci runs go test -race by default")
	}
	noRace := repoOf(t, "Go", map[string]string{
		"README.md": "x\n",
		".github/workflows/ci.yml": `on: [pull_request]
jobs:
  go:
    uses: swarm-routing/.github/.github/workflows/reusable-go-ci.yml@main
    with:
      race: false
`,
	})
	wantStatus(t, noRace, "?", "dynamic_analysis")

	nightly := repoOf(t, "Nightly", map[string]string{
		"README.md":                  "x\n",
		"core/a.cc":                  "int a;\n",
		".github/workflows/fuzz.yml": "on:\n  schedule:\n    - cron: '0 3 * * *'\njobs:\n  f:\n    steps:\n      - run: b/fuzz -max_total_time=600\n",
	})
	wantStatus(t, nightly, "Met", "dynamic_analysis")
	wantStatus(t, nightly, "?", "dynamic_analysis_fixed")
}

func TestStripCommentsAndTriggers(t *testing.T) {
	code := stripComments("# all comment\nrun: a # b\nrun: 'x # y' # z\nrun: ${#v}\n")
	if code != "\nrun: a \nrun: 'x # y' \nrun: ${#v}\n" {
		t.Errorf("stripComments: %q", code)
	}
	on, filtered := triggersOf("on:\n  pull_request:\n    paths:\n      - go.mod\n  push:\n    branches: [main]\njobs:\n")
	if !reflect.DeepEqual(on, map[string]bool{"pull_request": true, "push": true}) || !filtered {
		t.Errorf("block on: %v %v", on, filtered)
	}
	on, filtered = triggersOf("on: [push, pull_request]\n")
	if !on["push"] || !on["pull_request"] || filtered {
		t.Errorf("inline on: %v", on)
	}
}

// A justification already saved on the site from the old matcher is drift.
func TestStaleEvidenceIsDrift(t *testing.T) {
	wf := "https://github.com/" + Org + "/.github/blob/main/.github/workflows/"
	site := map[string]any{
		"dynamic_analysis_status":                   "Met",
		"dynamic_analysis_justification":            "Dynamic analysis (sanitizers) in CI: " + wf + "repo-metadata.yml.",
		"dynamic_analysis_enable_assertions_status": "Met",
		"dynamic_analysis_enable_assertions_justification": "Python's assertions are on in every test run: " +
			wf + "repo-metadata.yml.",
		"test_most_status":        "Met",
		"test_most_justification": "The owner's own reading of the coverage report.",
		"build_status":            "Met",
		"build_justification":     "Hand-written, citing no workflow.",
	}
	file := map[string]any{
		"dynamic_analysis_status":                   "?",
		"dynamic_analysis_justification":            "No fuzzing, sanitizer or race-detector run found in CI.",
		"dynamic_analysis_enable_assertions_status": "Met",
		"dynamic_analysis_enable_assertions_justification": "The Python tests run with assertions on " +
			"(no -O, no PYTHONOPTIMIZE): " + wf + "ci.yml.",
		"test_most_status":        "?",
		"test_most_justification": "The owner answers from the coverage report.",
		"build_status":            "Met",
		"build_justification":     "Built with make.",
	}
	tree := map[string]bool{".github/workflows/repo-metadata.yml": true, ".github/workflows/ci.yml": true}
	rep := Findings(".github", site, file, tree)
	want := []string{
		"dynamic_analysis: the site says Met, .bestpractices.json finds no evidence for it on main",
		"dynamic_analysis_enable_assertions: the site's justification cites .github/workflows/repo-metadata.yml, " +
			".bestpractices.json no longer does",
	}
	if !reflect.DeepEqual(rep.Items, want) {
		t.Errorf("items: %q", rep.Items)
	}
	if !rep.Propose["dynamic_analysis_enable_assertions"] || rep.Propose["dynamic_analysis"] || rep.Propose["build"] {
		t.Errorf("propose: %v", rep.Propose)
	}
}
