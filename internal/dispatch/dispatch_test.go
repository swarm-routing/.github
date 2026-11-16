// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package dispatch

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func bin(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	for name, mode := range map[string]os.FileMode{
		"fixture": 0o755, "org-bot": 0o755, Self: 0o755, "notes.txt": 0o644, "Bad_Name": 0o755,
	} {
		if err := os.WriteFile(filepath.Join(dir, name), nil, mode); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(dir, "subdir"), 0o755); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestList(t *testing.T) {
	got, err := List(bin(t))
	if err != nil || !reflect.DeepEqual(got, []string{"fixture", "org-bot"}) {
		t.Fatalf("List = %v, %v", got, err)
	}
	if _, err := List(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("List of a missing directory must fail")
	}
}

func TestResolve(t *testing.T) {
	dir := bin(t)
	if p, err := Resolve(dir, "fixture"); err != nil || p != filepath.Join(dir, "fixture") {
		t.Fatalf("Resolve(fixture) = %q, %v", p, err)
	}
	for _, name := range []string{"", Self, "../fixture", "/bin/sh", "Bad_Name", "notes.txt", "subdir", "absent"} {
		if _, err := Resolve(dir, name); err == nil {
			t.Errorf("Resolve(%q) must fail", name)
		}
	}
}

func TestMain_(t *testing.T) {
	dir := bin(t)
	var gotPath string
	var gotArgv []string
	ok := func(p string, argv, env []string) error { gotPath, gotArgv = p, argv; return nil }
	cases := []struct {
		args        []string
		exec        ExecFunc
		code        int
		out, errOut string
	}{
		{nil, ok, 2, "", "usage: ci-tools <tool> [args...]   (ci-tools list: the tools)\nfixture\norg-bot\n"},
		{[]string{"list"}, ok, 0, "fixture\norg-bot\n", ""},
		{[]string{"--help"}, ok, 0, "fixture\norg-bot\n", ""},
		{[]string{"nope"}, ok, 2, "", "ci-tools: no tool \"nope\" (ci-tools list: the tools)\n"},
		{[]string{"fixture", "a"}, func(string, []string, []string) error { return errors.New("boom") }, 1, "", "ci-tools: fixture: boom\n"},
		{[]string{"fixture", "go.mod"}, ok, 0, "", ""},
	}
	for _, c := range cases {
		var out, errOut bytes.Buffer
		if code := Main(c.args, dir, nil, &out, &errOut, c.exec); code != c.code || out.String() != c.out || errOut.String() != c.errOut {
			t.Errorf("Main(%q) = %d, %q, %q; want %d, %q, %q", c.args, code, out.String(), errOut.String(), c.code, c.out, c.errOut)
		}
	}
	if gotPath != filepath.Join(dir, "fixture") || !reflect.DeepEqual(gotArgv, []string{"fixture", "go.mod"}) {
		t.Errorf("exec(%q, %q)", gotPath, gotArgv)
	}
	var out, errOut bytes.Buffer
	if code := Main([]string{"list"}, filepath.Join(dir, "missing"), nil, &out, &errOut, ok); code != 1 {
		t.Errorf("list of a missing directory: code %d", code)
	}
}
