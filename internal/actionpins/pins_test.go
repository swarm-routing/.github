// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package actionpins

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const (
	oldSHA = "aebdcf6156ab6691adf63218240e476564a1ed4c"
	newSHA = "1111111111111111111111111111111111111111"
	coSHA  = "3d3c42e5aac5ba805825da76410c181273ba90b1"
	orgSHA = "29c9ad419e5c90de4c13051720f1b33e8f6bbb14"
)

func wf(harden, version string) string {
	return "jobs:\n  a:\n    steps:\n" +
		"      - uses: step-security/harden-runner@" + harden + " # " + version + "\n" +
		"      - uses: actions/checkout@" + coSHA + " # v7.0.1\n" +
		"      - uses: swarm-routing/.github/.github/actions/bot-token@" + orgSHA + "\n"
}

func tpl(harden, version string) string {
	return ManagedMarker + ": edit templates/workflows/x.yml there.\njobs:\n  a:\n    steps:\n" +
		"      - name: Harden\n        uses: step-security/harden-runner@" + harden + " # " + version + "\n" +
		"        with:\n          egress-policy: audit\n" +
		"      - uses: swarm-routing/.github/.github/actions/bot-token@main\n"
}

func TestSyncMovesTemplatePins(t *testing.T) {
	files := map[string]string{
		".github/workflows/ci.yml":             wf(newSHA, "v2.24.0"),
		".github/actions/bot-token/action.yml": "runs:\n  steps:\n    - uses: step-security/harden-runner@" + newSHA + " # v2.24.0\n",
		"templates/workflows/x.yml":            tpl(oldSHA, "v2.23.0"),
		"templates/workflows/y.yml":            tpl(newSHA, "v2.24.0"),
		"docs/other.yml":                       "uses: step-security/harden-runner@" + oldSHA + " # v1\n",
	}
	changed, found, err := Sync(files)
	if err != nil {
		t.Fatal(err)
	}
	if len(changed) != 1 || changed["templates/workflows/x.yml"] != tpl(newSHA, "v2.24.0") {
		t.Fatalf("changed = %#v", changed)
	}
	if len(found) != 1 || found[0].Line != 6 || found[0].Action != "step-security/harden-runner" {
		t.Fatalf("found = %#v", found)
	}
	want := "drift     templates/workflows/x.yml:6: step-security/harden-runner at aebdcf6156ab (v2.23.0), .github/workflows at 111111111111 (v2.24.0)"
	if found[0].String() != want {
		t.Fatalf("finding %q, want %q", found[0], want)
	}
}

func TestSyncSubpathAndMissingComment(t *testing.T) {
	files := map[string]string{
		".github/workflows/a.yml":    "    - uses: github/codeql-action/upload-sarif@" + newSHA + " # v4.40.0\n",
		"templates/quality/q.yml.in": "    - uses: github/codeql-action/analyze@" + oldSHA + "\n",
	}
	changed, _, err := Sync(files)
	if err != nil {
		t.Fatal(err)
	}
	if got := changed["templates/quality/q.yml.in"]; got != "    - uses: github/codeql-action/analyze@"+newSHA+" # v4.40.0\n" {
		t.Fatalf("got %q", got)
	}
}

func TestSyncTemplateOnlyActionIsAnError(t *testing.T) {
	files := map[string]string{
		".github/workflows/a.yml":   wf(newSHA, "v2.24.0"),
		"templates/workflows/x.yml": "      - uses: acme/only-here@" + oldSHA + " # v1\n",
	}
	changed, found, err := Sync(files)
	if err != nil || len(changed) != 0 || len(found) != 1 || !strings.Contains(found[0].Err, "pinned only in templates/") {
		t.Fatalf("changed %v found %#v err %v", changed, found, err)
	}
}

func TestPinsDisagree(t *testing.T) {
	files := map[string]string{
		".github/workflows/a.yml": wf(newSHA, "v2.24.0"),
		".github/workflows/b.yml": wf(oldSHA, "v2.23.0"),
	}
	_, err := Pins(files)
	if err == nil || !strings.Contains(err.Error(), "step-security/harden-runner has 2 pins") {
		t.Fatalf("err = %v", err)
	}
}

func TestSourceAndTemplatePaths(t *testing.T) {
	for p, want := range map[string]bool{
		".github/workflows/ci.yml":             true,
		".github/workflows/x.yaml":             true,
		".github/workflows/sub/ci.yml":         false,
		".github/actions/bot-token/action.yml": true,
		".github/actions/bot-token/other.yml":  false,
		".github/actions/a/b/action.yml":       false,
		"templates/workflows/x.yml":            false,
	} {
		if Source(p) != want {
			t.Errorf("Source(%q) = %v", p, !want)
		}
	}
}

func write(t *testing.T, dir string, files map[string]string) {
	t.Helper()
	for p, text := range files {
		full := filepath.Join(dir, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestLocalCheckThenWrite(t *testing.T) {
	dir := t.TempDir()
	write(t, dir, map[string]string{
		".github/workflows/ci.yml":  wf(newSHA, "v2.24.0"),
		"templates/workflows/x.yml": tpl(oldSHA, "v2.23.0"),
	})
	var out bytes.Buffer
	if rc := Main([]string{dir}, nil, nil, "", &out, &out); rc != 1 || !strings.Contains(out.String(), "run: "+Fix) {
		t.Fatalf("check rc %d:\n%s", rc, out.String())
	}
	out.Reset()
	if rc := Main([]string{"--write", dir}, nil, nil, "", &out, &out); rc != 0 || !strings.Contains(out.String(), "update    templates/workflows/x.yml") {
		t.Fatalf("write rc %d:\n%s", rc, out.String())
	}
	got, _ := os.ReadFile(filepath.Join(dir, "templates/workflows/x.yml"))
	if string(got) != tpl(newSHA, "v2.24.0") {
		t.Fatalf("written %q", got)
	}
	out.Reset()
	if rc := Main([]string{dir}, nil, nil, "", &out, &out); rc != 0 || out.String() != "action-pins: 1 template files at the pins of .github/workflows\n" {
		t.Fatalf("recheck rc %d:\n%s", rc, out.String())
	}
}

func TestLocalTemplateOnlyFails(t *testing.T) {
	dir := t.TempDir()
	write(t, dir, map[string]string{"templates/workflows/x.yml": tpl(oldSHA, "v2.23.0")})
	var out bytes.Buffer
	if rc := Local(dir, true, &out); rc != 1 || !strings.Contains(out.String(), "1 template pins no workflow here uses") {
		t.Fatalf("rc %d:\n%s", rc, out.String())
	}
}
