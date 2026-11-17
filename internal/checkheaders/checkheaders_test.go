// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// TestSelfTestCases carries the Python --self-test's cases, one subtest each.
func TestSelfTestCases(t *testing.T) {
	known := func(p string) bool { return SelfTestKnown[p] }
	for _, c := range SelfTestCases {
		t.Run(c.Label, func(t *testing.T) {
			got := CheckFile(c.Rel, c.Text, SelfTestRules, known, nil)
			if (len(got) > 0) != c.Fire {
				t.Errorf("fire = %v, want %v: %q", len(got) > 0, c.Fire, got)
			}
		})
	}
	for _, name := range []string{"cmd/x/main.go", "core/a.cc", "tools/x.py", "tools/x.sh"} {
		if !hasSuffix(name, Exts) {
			t.Errorf("%s is not scanned", name)
		}
	}
}

// TestCoreDep carries the Python self-test's --core-dep cases.
func TestCoreDep(t *testing.T) {
	dep, err := MakeDepFixture(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	depOK := DepResolver([]string{dep})
	for _, c := range SelfTestDepCases {
		text := DepCaseText(c.Name)
		if got := CheckFile("core/a.cc", text, DepRules, nil, depOK); (len(got) > 0) != c.Fire {
			t.Errorf("--core-dep %s: %q, want fire %v", c.Name, got, c.Fire)
		}
		if without := CheckFile("core/a.cc", text, DepRules, nil, nil); len(without) == 0 {
			t.Errorf("%s resolved without --core-dep", c.Name)
		}
	}
}

func TestSelfTestCommand(t *testing.T) {
	var out bytes.Buffer
	if rc := SelfTest(&out); rc != 0 || out.String() != "self-test: PASS\n" {
		t.Fatalf("rc %d, %q", rc, out.String())
	}
	var o, e bytes.Buffer
	if rc := Main([]string{"--self-test"}, &o, &e); rc != 0 || o.String() != "self-test: PASS\n" || e.Len() != 0 {
		t.Fatalf("Main --self-test: rc %d, %q, %q", rc, o.String(), e.String())
	}
}

func TestDecodeText(t *testing.T) {
	for in, want := range map[string]string{
		"a\r\nb\rc\n":      "a\nb\nc\n",
		"\xe9x":            "\ufffdx",
		"\xe2\x82":         "\ufffd",             // one maximal subpart
		"\xe2\x82x":        "\ufffdx",            // ... then the byte that broke it
		"\xf0\x80\x80":     "\ufffd\ufffd\ufffd", // F0 needs 90..BF next
		"\xed\xa0\x80":     "\ufffd\ufffd\ufffd", // no surrogates
		"\xf4\x90\x80\x80": "\ufffd\ufffd\ufffd\ufffd",
		"\xc0\xaf":         "\ufffd\ufffd",
		"ok é\U0001f600\r": "ok é\U0001f600\n",
	} {
		if got := decodeText([]byte(in)); got != want {
			t.Errorf("decodeText(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestPyRepr(t *testing.T) {
	for in, want := range map[string]string{
		"x":            `'x'`,
		"a'b":          `"a'b"`,
		`a"b'c`:        `'a"b\'c'`,
		"\\\t\n\r":     `'\\\t\n\r'`,
		"\x00\x7f":     `'\x00\x7f'`,
		"é":            "'é'",
		"\u200b\u00a0": "'\\u200b\\xa0'",
		"\U000e0001":   `'\U000e0001'`,
	} {
		if got := pyRepr(in); got != want {
			t.Errorf("pyRepr(%q) = %s, want %s", in, got, want)
		}
	}
}

func TestQuotePath(t *testing.T) {
	for in, want := range map[string]string{
		"a/b.py":   "a/b.py",
		"a b.py":   "a b.py",
		"é.py":     `"\303\251.py"`,
		"q\"t\\x":  `"q\"t\\x"`,
		"t\tn\x01": `"t\tn\001"`,
		"d\x7f":    `"d\177"`,
	} {
		if got := quotePath(in); got != want {
			t.Errorf("quotePath(%q) = %s, want %s", in, got, want)
		}
	}
}

func TestNorm(t *testing.T) {
	for in, want := range map[string]string{
		"core/src/../a.h":  "core/a.h",
		"./a.h":            "a.h",
		"core//x/./y":      "core/x/y",
		"../../x":          "x",
		"core/x//abs":      "core/x/abs",
		"/abs":             "//abs",
		"//two":            "///two",
		"/..":              "",
		"core/include/a.h": "core/include/a.h",
		"coreinclude/../a": "a",
	} {
		if got := Norm(in); got != want {
			t.Errorf("Norm(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestRealpath(t *testing.T) {
	d, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	must := func(err error) {
		if err != nil {
			t.Fatal(err)
		}
	}
	must(os.MkdirAll(filepath.Join(d, "a", "b"), 0o755))
	must(os.Symlink("a/b", filepath.Join(d, "lb")))
	must(os.Symlink("loop2", filepath.Join(d, "loop1")))
	must(os.Symlink("loop1", filepath.Join(d, "loop2")))
	must(os.Symlink("/", filepath.Join(d, "toroot")))
	for in, want := range map[string]string{
		d + "/lb":              d + "/a/b",
		d + "/lb/..":           d + "/a",
		d + "/missing/../a":    d + "/a",
		d + "/a/./b//":         d + "/a/b",
		d + "/loop1/x":         d + "/loop1/x",
		d + "/toroot/..":       "/",
		d + "/lb/missing/../c": d + "/a/b/c",
	} {
		if got := realpath(in); got != want {
			t.Errorf("realpath(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestParseIndexRejects(t *testing.T) {
	for _, b := range [][]byte{nil, []byte("DIRC"), []byte("XXXX\x00\x00\x00\x02\x00\x00\x00\x00" + string(make([]byte, 20)))} {
		if _, err := parseIndex(b, 20); err == nil {
			t.Errorf("parseIndex(%q) accepted", b)
		}
	}
	if v, n := varint([]byte{0x80, 0x00}); v != 128 || n != 2 {
		t.Errorf("varint = %d, %d", v, n)
	}
}

func TestLsFilesOutsideARepository(t *testing.T) {
	d := t.TempDir()
	if _, err := LsFiles(d); err == nil {
		t.Skip("the temporary directory is inside a repository")
	}
	var o, e bytes.Buffer
	if rc := Scan(d, Rules{}, "", nil, &o, &e); rc != 1 || o.Len() != 0 || e.Len() == 0 {
		t.Errorf("rc %d, stdout %q, stderr %q", rc, o.String(), e.String())
	}
}
