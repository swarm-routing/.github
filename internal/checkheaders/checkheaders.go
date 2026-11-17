// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package checkheaders is the licence-header gate for swarm-routing repos
// (AntHocNet's rules, ADR-0028), the Go port of the former tools/checks/check-headers.py
// (#531), byte for byte: the same findings, output and exit codes for the
// same arguments and tree. The rules are in help.txt (the Python tool's
// docstring, which its --help prints).
package checkheaders

import (
	"regexp"
	"strings"
)

// SPDX is the tag every covered file carries in its first lines.
const SPDX = "SPDX-License-Identifier"

// DualSPDX is the exact line a file under a dual root carries.
const DualSPDX = SPDX + ": MIT OR GPL-2.0-only"

// HeadLines is the header window, not counting a contributor's extra
// copyright lines.
const HeadLines = 5

// OrgCopyright is the org's copyright line.
const OrgCopyright = "Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)"

// Exts are the covered source types; CXX are the C++ ones the include rule reads.
var (
	Exts = []string{".h", ".hpp", ".cc", ".cpp", ".go", ".py", ".sh"}
	CXX  = []string{".h", ".hpp", ".cc", ".cpp"}
)

const (
	sp  = `[` + pySpaceClass + `]`
	nsp = `[^` + pySpaceClass + `]`
	dig = `\p{Nd}`
)

var (
	copyrightRE    = regexp.MustCompile(`^` + sp + `*(?://|#)` + sp + `*Copyright \(c\) ` + dig + `{4}(?:-` + dig + `{4})? ` + nsp)
	orgCopyrightRE = regexp.MustCompile(`^` + sp + `*(?://|#)` + sp + `*Copyright \(c\) ` + dig + `{4}(?:-` + dig + `{4})? ` +
		`Daniel Joppi \(https://github\.com/swarm-routing\)` + sp + `*$`)
)

// StdHeaders are the C++ standard-library headers a core may include with <...>.
var StdHeaders = func() map[string]bool {
	m := map[string]bool{}
	for _, h := range strings.Fields(`
algorithm any array atomic bit bitset cassert cctype cerrno cfloat charconv chrono
cinttypes climits clocale cmath compare complex concepts condition_variable csignal
cstdarg cstddef cstdint cstdio cstdlib cstring ctime cwchar deque exception expected
format forward_list fstream functional initializer_list iomanip ios iosfwd iostream
istream iterator limits list locale map memory mutex new numbers numeric optional
ostream queue random ranges ratio regex set shared_mutex source_location span sstream
stack stdexcept streambuf string string_view system_error thread tuple type_traits
typeindex typeinfo unordered_map unordered_set utility valarray variant vector version
`) {
		m[h] = true
	}
	return m
}()

func hasSuffix(s string, exts []string) bool {
	for _, e := range exts {
		if strings.HasSuffix(s, e) {
			return true
		}
	}
	return false
}

func hasPrefix(s string, roots []string) bool {
	for _, r := range roots {
		if strings.HasPrefix(s, r) {
			return true
		}
	}
	return false
}

// Head is the header window: the first HeadLines lines, plus every copyright
// line after the first met on the way (a contributor's line never pushes the
// SPDX line out; a header with one copyright line keeps the plain window).
func Head(text string) []string {
	var out []string
	counted, holders := 0, 0
	for _, line := range strings.Split(text, "\n") {
		if counted >= HeadLines {
			break
		}
		out = append(out, line)
		if copyrightRE.MatchString(line) {
			holders++
			if holders == 1 {
				counted++
			}
		} else {
			counted++
		}
	}
	return out
}

// HeadHas reports whether a line of the header window contains needle.
func HeadHas(text, needle string) bool {
	for _, line := range Head(text) {
		if strings.Contains(line, needle) {
			return true
		}
	}
	return false
}

func copyrightFindings(rel, text, expr string) []string {
	lines := Head(text)
	var holders []string
	for _, line := range lines {
		if copyrightRE.MatchString(line) {
			holders = append(holders, line)
		}
	}
	if len(holders) < 2 {
		return nil
	}
	var out []string
	if !orgCopyrightRE.MatchString(holders[0]) {
		out = append(out, rel+":1: a contributor's copyright line goes beneath the org line '"+
			OrgCopyright+"', which must come first")
	}
	exact := false
	for _, line := range lines {
		if !strings.Contains(line, SPDX) {
			continue
		}
		after := line
		if i := strings.Index(line, SPDX+":"); i >= 0 {
			after = line[i+len(SPDX)+1:]
		}
		if pyStrip(after) == expr {
			exact = true
		}
	}
	if !exact {
		out = append(out, rel+":1: with more than one copyright line the header must say exactly '"+
			SPDX+": "+expr+"'")
	}
	return out
}

// Rules are a scan's roots: the dual-licensed roots, the core roots and the
// files under a dual root that stay GPL.
type Rules struct {
	Dual    []string
	Core    []string
	GPLOnly map[string]bool
}

// CheckFile returns the findings for one file. exists says whether a path
// relative to the scan root is a file; depOK whether an include name resolves
// to a dual-licensed file of a --core-dep (either may be nil: never).
func CheckFile(rel, text string, r Rules, exists func(string) bool, depOK func(string) bool) []string {
	if exists == nil {
		exists = func(string) bool { return false }
	}
	if depOK == nil {
		depOK = func(string) bool { return false }
	}
	dual := hasPrefix(rel, r.Dual) && !r.GPLOnly[rel]
	expr := "GPL-2.0-only"
	if dual {
		expr = "MIT OR GPL-2.0-only"
	}
	if !HeadHas(text, SPDX) {
		return []string{rel + ":1: no " + SPDX + " in the first 5 lines — add\n" +
			"    // Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)\n" +
			"    // " + SPDX + ": " + expr + "\n  ('#' comments for Python/shell, after any shebang)"}
	}
	var out []string
	if dual && !HeadHas(text, DualSPDX) {
		out = append(out, rel+":1: this root is dual-licensed — the header must say exactly '"+
			DualSPDX+"' (or list the file with --gpl-only)")
	}
	out = append(out, copyrightFindings(rel, text, expr)...)
	for _, c := range r.Core {
		if strings.HasPrefix(rel, c) {
			// the first core root that matches; an empty one checks nothing
			if c != "" && hasSuffix(rel, CXX) {
				out = append(out, includeFindings(rel, text, c, exists, depOK)...)
			}
			break
		}
	}
	return out
}

func includeFindings(rel, text, root string, exists, depOK func(string) bool) []string {
	var out []string
	here := pyParent(rel)
	for n, line := range strings.Split(text, "\n") {
		s := pyStrip(line)
		if !strings.HasPrefix(s, "#include") {
			continue
		}
		target := pyStrip(s[len("#include"):])
		switch {
		case strings.HasPrefix(target, "<"):
			name := target[1:]
			if i := strings.IndexByte(target, '>'); i >= 0 {
				name = pySlice(target, 1, i)
			}
			if !StdHeaders[name] {
				out = append(out, rel+":"+itoa(n+1)+": "+root+
					" may include only the C++ standard library with <...>, not <"+name+">")
			}
		case strings.HasPrefix(target, `"`):
			end := strings.IndexByte(target[1:], '"')
			if end >= 0 {
				end++
			}
			name := pySlice(target, 1, end)
			cands := []string{
				Norm(here + "/" + name),
				Norm(root + "include/" + name),
				Norm(strings.TrimRight(root, "/") + "/" + name),
			}
			found := false
			for _, c := range cands {
				if strings.HasPrefix(c, root) && exists(c) {
					found = true
					break
				}
			}
			if !found && !depOK(name) {
				out = append(out, rel+":"+itoa(n+1)+`: "`+name+`" does not resolve to a file under `+root+
					" or to a dual-licensed file of a --core-dep — "+root+" includes nothing from outside it")
			}
		}
	}
	return out
}

// pySlice is s[i:j] of a Python str for byte indices of ASCII delimiters,
// with Python's meaning of a negative j (counted from the end).
func pySlice(s string, i, j int) string {
	if j < 0 {
		j += len(s)
	}
	if j < i {
		return ""
	}
	return s[i:j]
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

// pyParts is PurePosixPath(p).parts: the root ("/" or, for exactly two
// leading slashes, "//"), then the components without empty ones and ".".
func pyParts(p string) []string {
	var parts []string
	rest := p
	switch {
	case strings.HasPrefix(p, "//") && !strings.HasPrefix(p, "///"):
		parts = append(parts, "//")
		rest = p[2:]
	case strings.HasPrefix(p, "/"):
		parts = append(parts, "/")
		rest = strings.TrimLeft(p, "/")
	}
	for _, c := range strings.Split(rest, "/") {
		if c != "" && c != "." {
			parts = append(parts, c)
		}
	}
	return parts
}

// pyParent is str(PurePosixPath(rel).parent) for a relative path.
func pyParent(rel string) string {
	parts := pyParts(rel)
	if len(parts) <= 1 {
		if len(parts) == 1 && (parts[0] == "/" || parts[0] == "//") {
			return parts[0]
		}
		return "."
	}
	parent := parts[:len(parts)-1]
	if parent[0] == "/" || parent[0] == "//" {
		return parent[0] + strings.Join(parent[1:], "/")
	}
	return strings.Join(parent, "/")
}

// Norm resolves ".." lexically, as the Python tool's norm() did.
func Norm(rel string) string {
	var parts []string
	for _, p := range pyParts(rel) {
		if p == ".." {
			if len(parts) > 0 {
				parts = parts[:len(parts)-1]
			}
		} else {
			parts = append(parts, p)
		}
	}
	return strings.Join(parts, "/")
}

// DepResolver returns depOK for CheckFile: name is a file inside one of the
// --core-dep directories (never above it) whose first lines carry the dual
// SPDX. Directories are resolved as pathlib's resolve() does, relative to the
// working directory.
func DepResolver(deps []string) func(string) bool {
	dirs := make([]string, len(deps))
	for i, d := range deps {
		dirs[i] = realpath(d)
	}
	return func(name string) bool {
		for _, d := range dirs {
			var p string
			if strings.HasPrefix(name, "/") {
				p = realpath(name)
			} else {
				p = realpath(d + "/" + name)
			}
			if isRelativeTo(p, d) && isFile(p) {
				text, err := readText(p)
				if err == nil && HeadHas(text, DualSPDX) {
					return true
				}
			}
		}
		return false
	}
}

// isRelativeTo is PurePosixPath(p).is_relative_to(d) for absolute paths.
func isRelativeTo(p, d string) bool {
	pp, dp := pyParts(p), pyParts(d)
	if len(dp) > len(pp) {
		return false
	}
	for i := range dp {
		if pp[i] != dp[i] {
			return false
		}
	}
	return true
}
