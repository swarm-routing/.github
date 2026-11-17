// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Case is one self-test case: the findings for text at rel fire or not.
type Case struct {
	Rel, Text string
	Fire      bool
	Label     string
}

// SelfTestRules are the roots the self-test cases run under.
var SelfTestRules = Rules{
	Dual:    []string{"core/", "tools/"},
	Core:    []string{"core/"},
	GPLOnly: map[string]bool{"tools/gpl_glue.py": true},
}

// SelfTestKnown are the files that exist for the self-test's include cases.
var SelfTestKnown = map[string]bool{"core/include/x/a.h": true, "core/src/b.h": true}

// SelfTestCases are the Python tool's self-test cases, in its order.
var SelfTestCases = func() []Case {
	const h = "// Copyright (c) 2026 X\n"
	org := OrgCopyright
	return []Case{
		{"ns3/model/a.cc", "#include <map>\n", true, "no header"},
		{"ns3/model/a.cc", strings.Repeat("\n", 5) + "// SPDX-License-Identifier: GPL-2.0-only\n", true, "header too low"},
		{"ns3/model/a.cc", h + "// SPDX-License-Identifier: GPL-2.0-only\n", false, "GPL module"},
		{"tools/x.py", "#!/usr/bin/env python3\n# SPDX-License-Identifier: GPL-2.0-only\n", true, "GPL in dual root"},
		{"tools/x.py", "#!/usr/bin/env python3\n# SPDX-License-Identifier: MIT\n", true, "MIT-only in dual root"},
		{"tools/x.sh", "#!/bin/sh\n# SPDX-License-Identifier: MIT OR GPL-2.0-only\n", false, "dual tool"},
		{"tools/cmd/x/main.go", "// " + org + "\n// SPDX-License-Identifier: MIT OR GPL-2.0-only\n\npackage main\n", false, "dual Go tool"},
		{"tools/cmd/x/main.go", "// " + org + "\n// SPDX-License-Identifier: GPL-2.0-only\n\npackage main\n", true, "GPL Go file in dual root"},
		{"cmd/x/main.go", "package main\n", true, "Go file without a header"},
		{"cmd/x/main.go", "//go:build linux\n\n// " + org + "\n// SPDX-License-Identifier: GPL-2.0-only\n\npackage main\n", false, "Go header after a build constraint"},
		{"tools/gpl_glue.py", "# SPDX-License-Identifier: GPL-2.0-only\n", false, "listed gpl-only"},
		{"core/src/b.cc", h + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n" + "#include \"x/a.h\"\n#include \"b.h\"\n#include <span>\n", false, "clean core"},
		{"core/src/b.cc", h + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include <ns3/node.h>\n", true, "ns-3 angle include"},
		{"core/src/b.cc", h + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include \"ns3/node.h\"\n", true, "ns-3 quote include"},
		{"core/src/b.cc", h + "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include \"../../ns3/model/a.h\"\n", true, "escape by .."},
		{"core/src/b.cc", "// " + org + "\n// Copyright (c) 2027 Ada Lovelace\n" +
			"// Copyright (c) 2027 Alan Turing\n// Copyright (c) 2027 Grace Hopper\n" +
			"// Copyright (c) 2027 Edsger Dijkstra\n" +
			"// SPDX-License-Identifier: MIT OR GPL-2.0-only\n", false, "contributors beneath the org line"},
		{"tools/x.py", "#!/usr/bin/env python3\n# " + org + "\n# Copyright (c) 2027 Ada Lovelace\n" +
			"# SPDX-License-Identifier: MIT OR GPL-2.0-only\n", false, "contributor in a script"},
		{"ns3/model/a.cc", "// Copyright (c) 2027 Ada Lovelace\n// SPDX-License-Identifier: GPL-2.0-only\n" +
			"// Copyright (c) 2027 Alan Turing\n", true, "contributors without the org line"},
		{"ns3/model/a.cc", "// Copyright (c) 2027 Ada Lovelace\n// " + org + "\n" +
			"// SPDX-License-Identifier: GPL-2.0-only\n", true, "contributor above the org line"},
		{"ns3/model/a.cc", "// " + org + "\n// Copyright (c) 2027 Ada Lovelace\n" +
			"// SPDX-License-Identifier: GPL-2.0-or-later\n", true, "contributor with an inexact SPDX"},
		{"ns3/model/a.cc", strings.Repeat("\n", 4) +
			"// Copyright (c) 2027 Ada Lovelace\n// SPDX-License-Identifier: GPL-2.0-only\n", true, "one copyright line keeps the five-line window"},
	}
}()

// DepCase is a --core-dep self-test case: an include of Name fires or not.
type DepCase struct {
	Name string
	Fire bool
}

// SelfTestDepCases are the Python tool's --core-dep cases: a dual-licensed
// header of the dependency resolves; a GPL one, a missing one and an escape
// above the directory do not.
var SelfTestDepCases = []DepCase{{"dual.h", false}, {"gpl.h", true}, {"nope.h", true}, {"../above.h", true}}

// MakeDepFixture writes the --core-dep fixture under tmp and returns the
// dependency's core directory.
func MakeDepFixture(tmp string) (string, error) {
	dep := filepath.Join(tmp, "dep", "core")
	if err := os.MkdirAll(dep, 0o755); err != nil {
		return "", err
	}
	for p, text := range map[string]string{
		filepath.Join(dep, "dual.h"):         "// x\n// SPDX-License-Identifier: MIT OR GPL-2.0-only\n",
		filepath.Join(dep, "gpl.h"):          "// x\n// SPDX-License-Identifier: GPL-2.0-only\n",
		filepath.Join(tmp, "dep", "above.h"): "// SPDX-License-Identifier: MIT OR GPL-2.0-only\n",
	} {
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			return "", err
		}
	}
	return dep, nil
}

// DepCaseText is the core file each --core-dep case checks.
func DepCaseText(name string) string {
	return "// x\n// SPDX-License-Identifier: MIT OR GPL-2.0-only\n#include \"" + name + "\"\n"
}

// DepRules are the roots of the --core-dep cases.
var DepRules = Rules{Dual: []string{"core/"}, Core: []string{"core/"}}

// SelfTest is --self-test: every case, a line per failure, then the verdict.
func SelfTest(w io.Writer) int {
	fails := 0
	known := func(p string) bool { return SelfTestKnown[p] }
	for _, c := range SelfTestCases {
		got := CheckFile(c.Rel, c.Text, SelfTestRules, known, nil)
		if (len(got) > 0) != c.Fire {
			fails++
			want := "silence"
			if c.Fire {
				want = "a finding"
			}
			fmt.Fprintf(w, "SELF-TEST FAIL (%s): expected %s, got %s\n", c.Label, want, pyList(got))
		}
	}
	for _, name := range []string{"cmd/x/main.go", "core/a.cc", "tools/x.py", "tools/x.sh"} {
		if !hasSuffix(name, Exts) {
			fails++
			fmt.Fprintf(w, "SELF-TEST FAIL: %s is not scanned\n", name)
		}
	}
	fails += selfTestCoreDep(w)
	if fails == 0 {
		fmt.Fprintln(w, "self-test: PASS")
		return 0
	}
	fmt.Fprintf(w, "self-test: %d FAILURE(S)\n", fails)
	return 1
}

func selfTestCoreDep(w io.Writer) int {
	tmp, err := os.MkdirTemp("", "check-headers-")
	if err != nil {
		fmt.Fprintf(w, "SELF-TEST FAIL (--core-dep): %v\n", err)
		return 1
	}
	defer os.RemoveAll(tmp)
	dep, err := MakeDepFixture(tmp)
	if err != nil {
		fmt.Fprintf(w, "SELF-TEST FAIL (--core-dep): %v\n", err)
		return 1
	}
	depOK := DepResolver([]string{dep})
	fails := 0
	for _, c := range SelfTestDepCases {
		text := DepCaseText(c.Name)
		got := CheckFile("core/a.cc", text, DepRules, nil, depOK)
		without := CheckFile("core/a.cc", text, DepRules, nil, nil)
		if (len(got) > 0) != c.Fire || len(without) == 0 {
			fails++
			fmt.Fprintf(w, "SELF-TEST FAIL (--core-dep %s): got %s\n", c.Name, pyList(got))
		}
	}
	return fails
}

// pyList is repr() of a list of str.
func pyList(items []string) string {
	parts := make([]string, len(items))
	for i, s := range items {
		parts[i] = pyRepr(s)
	}
	return "[" + strings.Join(parts, ", ") + "]"
}
