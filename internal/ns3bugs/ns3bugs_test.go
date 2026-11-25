// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package ns3bugs

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func run(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var out, errb bytes.Buffer
	code := Main(args, &out, &errb)
	return code, out.String(), errb.String()
}

func readFile(t *testing.T, p string) string {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// The fixture's table, byte for byte: relative links and anchors made
// absolute, an escaped pipe kept in its cell, the candidates and the PROC
// table left out, the ID linked to its RCAPA only when it has one.
func TestGolden(t *testing.T) {
	code, out, errs := run(t, "testdata/register.md")
	if code != 0 || errs != "" {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	if want := readFile(t, "testdata/want.md"); out != want {
		t.Fatalf("output differs from testdata/want.md:\n%s", out)
	}
	for _, not := range []string{"PROC-001", "delay shift", "](ns3-rcapa/", "](#"} {
		if strings.Contains(out, not) {
			t.Errorf("output has %q", not)
		}
	}
}

func TestWriteAndCheck(t *testing.T) {
	f := filepath.Join(t.TempDir(), "known-bugs.md")
	if code, out, _ := run(t, "testdata/register.md", "--write", f); code != 0 || !strings.Contains(out, "2 bug(s), 1 fixed upstream") {
		t.Fatalf("--write: exit %d, %q", code, out)
	}
	if readFile(t, f) != readFile(t, "testdata/want.md") {
		t.Fatal("--write wrote something else than the table")
	}
	if code, out, _ := run(t, "testdata/register.md", "--check", f); code != 0 || !strings.Contains(out, "matches") {
		t.Fatalf("--check on the written file: exit %d, %q", code, out)
	}
	if err := os.WriteFile(f, []byte("typed by hand\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if code, out, _ := run(t, "testdata/register.md", "--check", f); code != 1 || !strings.Contains(out, "differs") {
		t.Fatalf("--check on a hand edit: exit %d, %q", code, out)
	}
}

// GFM rows need no leading or trailing pipe: such a row is kept, never the end of the table.
func TestRowsWithoutOuterPipes(t *testing.T) {
	reg := strings.Replace(readFile(t, "testdata/register.md"), "| NS3-002 |", "NS3-002 |", 1)
	p := filepath.Join(t.TempDir(), "register.md")
	if err := os.WriteFile(p, []byte(reg), 0o644); err != nil {
		t.Fatal(err)
	}
	if code, out, errs := run(t, p); code != 0 || out != readFile(t, "testdata/want.md") {
		t.Fatalf("exit %d, stderr %q; output differs from testdata/want.md:\n%s", code, errs, out)
	}
}

// The repair a --check mismatch names keeps the --base it was checked with.
func TestCheckRepairKeepsBase(t *testing.T) {
	f := filepath.Join(t.TempDir(), "known-bugs.md")
	const base = "https://example.org/docs/"
	if err := os.WriteFile(f, []byte("stale\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, _ := run(t, "testdata/register.md", "--base", base, "--check", f)
	want := "run ns3-bugs testdata/register.md --base " + base + " --write " + f
	if code != 1 || !strings.Contains(out, want) {
		t.Fatalf("--check with --base: exit %d, %q, want %q", code, out, want)
	}
	if code, _, _ := run(t, "testdata/register.md", "--base", base, "--write", f); code != 0 {
		t.Fatalf("the named repair: exit %d", code)
	}
	if code, out, _ := run(t, "testdata/register.md", "--base", base, "--check", f); code != 0 {
		t.Fatalf("the same check after the repair: exit %d, %q", code, out)
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, errors.New("stdout closed") }

func TestStdoutError(t *testing.T) {
	var errb bytes.Buffer
	if code := Main([]string{"testdata/register.md"}, failingWriter{}, &errb); code != 2 || !strings.Contains(errb.String(), "stdout closed") {
		t.Fatalf("a failing stdout: exit %d, stderr %q", code, errb.String())
	}
}

func TestBase(t *testing.T) {
	_, out, _ := run(t, "testdata/register.md", "--base", "https://example.org/docs")
	if !strings.Contains(out, "[NS3-001](https://example.org/docs/ns3-rcapa/ns3-rcapa-aodv-icmp-livelock.md)") {
		t.Fatalf("--base without a slash: %s", out)
	}
}

func TestRegisterErrors(t *testing.T) {
	reg := readFile(t, "testdata/register.md")
	for name, text := range map[string]string{
		"a lost index column":   strings.Replace(reg, "| Workaround in our repositories | Upstream |", "| Fix | Upstream |", 1),
		"no index table":        strings.Replace(reg, "ns-3 versions", "versions", 1),
		"a lost fixed column":   strings.Replace(reg, "| Fixed in |", "| Since |", 1),
		"a non-NS3 index ID":    strings.Replace(reg, "| NS3-002 |", "| NS3-two |", 1),
		"an empty index":        strings.Split(reg, "| NS3-001")[0] + "\n## Fixed upstream\n\n| Bug | ns-3 | Fixed in | Workaround in our repositories |\n|---|---|---|---|\n",
		"no fixed-upstream one": strings.Split(reg, "## Fixed upstream")[0],
	} {
		p := filepath.Join(t.TempDir(), "register.md")
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
		if code, _, errs := run(t, p); code != 2 || !strings.HasPrefix(errs, "ns3-bugs: ") {
			t.Errorf("%s: exit %d, stderr %q", name, code, errs)
		}
	}
}

func TestUsage(t *testing.T) {
	for _, args := range [][]string{
		nil,
		{"--write", "x"},
		{"testdata/register.md", "--write", "a", "--check", "b"},
		{"testdata/register.md", "extra"},
		{"--nope"},
	} {
		if code, _, _ := run(t, args...); code != 2 {
			t.Errorf("%q: exit %d, want 2", args, code)
		}
	}
	if code, _, _ := run(t, "testdata/missing.md"); code != 2 {
		t.Errorf("a missing register: exit %d, want 2", code)
	}
}
