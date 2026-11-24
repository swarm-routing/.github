// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package ns3bugs renders the "Known simulator bugs" table of the org's
// install guide (templates/install/known-bugs.md, the org-sync section
// `known-bugs` of each C++ repository's docs/install.md) from
// swarm-routing/sim-tools docs/ns3-bugs.md, the ns-3 bug register, so the
// table is generated, never typed (swarm-routing/.github#881, #884).
//
// It reads two tables of the register by their header cells: the index (ID,
// Title, ns-3 versions, Status, Workaround in our repositories, RCAPA) and
// "Fixed upstream before we recorded them" (Bug, ns-3, Fixed in, Workaround
// in our repositories). A register that lost one of those columns is an
// error, never a silently shorter table. Relative links in a cell point into
// the register's directory, so they are rewritten to absolute URLs under
// --base.
package ns3bugs

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
)

// Base is where the register's relative links resolve: sim-tools' docs/ on main.
const Base = "https://github.com/swarm-routing/sim-tools/blob/main/docs/"

// Bug is one row of the register's index (an NS3-NNN).
type Bug struct {
	ID, Title, Versions, Status, Workaround, RCAPA string
}

// Fixed is one row of "Fixed upstream before we recorded them".
type Fixed struct {
	Bug, Versions, FixedIn, Workaround string
}

var (
	idRe   = regexp.MustCompile(`^NS3-\d+$`)
	linkRe = regexp.MustCompile(`\]\(([^)\s]+)\)`)
	sepRe  = regexp.MustCompile(`^\|?\s*:?-{3,}`)
)

// cells splits one Markdown table row; `\|` stays inside its cell.
func cells(line string) []string {
	line = strings.TrimSpace(line)
	line = strings.TrimPrefix(line, "|")
	line = strings.TrimSuffix(line, "|")
	var out []string
	var cur strings.Builder
	for i := 0; i < len(line); i++ {
		if line[i] == '\\' && i+1 < len(line) && line[i+1] == '|' {
			cur.WriteString(`\|`)
			i++
			continue
		}
		if line[i] == '|' {
			out = append(out, strings.TrimSpace(cur.String()))
			cur.Reset()
			continue
		}
		cur.WriteByte(line[i])
	}
	return append(out, strings.TrimSpace(cur.String()))
}

// table is one Markdown table: its header cells and its rows, each a map.
type table struct {
	header []string
	rows   []map[string]string
}

func tables(text string) []table {
	lines := strings.Split(text, "\n")
	var out []table
	for i := 0; i+1 < len(lines); i++ {
		if !strings.HasPrefix(strings.TrimSpace(lines[i]), "|") || !sepRe.MatchString(strings.TrimSpace(lines[i+1])) {
			continue
		}
		t := table{header: cells(lines[i])}
		k := i + 2
		for ; k < len(lines) && strings.HasPrefix(strings.TrimSpace(lines[k]), "|"); k++ {
			row := map[string]string{}
			for j, c := range cells(lines[k]) {
				if j < len(t.header) {
					row[t.header[j]] = c
				}
			}
			t.rows = append(t.rows, row)
		}
		out = append(out, t)
		i = k - 1
	}
	return out
}

func (t table) has(cols ...string) bool {
	for _, c := range cols {
		found := false
		for _, h := range t.header {
			if h == c {
				found = true
			}
		}
		if !found {
			return false
		}
	}
	return true
}

var (
	indexCols = []string{"ID", "Title", "ns-3 versions", "Status", "Workaround in our repositories", "RCAPA"}
	fixedCols = []string{"Bug", "ns-3", "Fixed in", "Workaround in our repositories"}
)

// Parse reads the register's index and its fixed-upstream table.
func Parse(text string) ([]Bug, []Fixed, error) {
	var bugs []Bug
	var fixed []Fixed
	var index, done bool
	for _, t := range tables(text) {
		switch {
		case t.has("ID", "ns-3 versions"):
			if !t.has(indexCols...) {
				return nil, nil, fmt.Errorf("the index table lacks a column: want %q, have %q", indexCols, t.header)
			}
			index = true
			for _, r := range t.rows {
				if !idRe.MatchString(r["ID"]) {
					return nil, nil, fmt.Errorf("index row with ID %q, not NS3-NNN", r["ID"])
				}
				bugs = append(bugs, Bug{r["ID"], r["Title"], r["ns-3 versions"], r["Status"], r["Workaround in our repositories"], r["RCAPA"]})
			}
		case t.has("Bug", "Fixed in"):
			if !t.has(fixedCols...) {
				return nil, nil, fmt.Errorf("the fixed-upstream table lacks a column: want %q, have %q", fixedCols, t.header)
			}
			done = true
			for _, r := range t.rows {
				fixed = append(fixed, Fixed{r["Bug"], r["ns-3"], r["Fixed in"], r["Workaround in our repositories"]})
			}
		}
	}
	if !index {
		return nil, nil, errors.New("no index table (a header with ID and ns-3 versions)")
	}
	if !done {
		return nil, nil, errors.New("no fixed-upstream table (a header with Bug and Fixed in)")
	}
	if len(bugs) == 0 {
		return nil, nil, errors.New("the index table has no row")
	}
	return bugs, fixed, nil
}

// absolute rewrites the relative links of a cell to URLs under base (the
// register's directory); an anchor alone points into the register itself.
func absolute(cell, base string) string {
	return linkRe.ReplaceAllStringFunc(cell, func(m string) string {
		href := linkRe.FindStringSubmatch(m)[1]
		switch {
		case strings.Contains(href, "://"), strings.HasPrefix(href, "mailto:"):
			return m
		case strings.HasPrefix(href, "#"):
			return "](" + base + "ns3-bugs.md" + href + ")"
		default:
			return "](" + base + strings.TrimPrefix(href, "./") + ")"
		}
	})
}

// firstHref is the first link target of a cell, or "".
func firstHref(cell string) string {
	if m := linkRe.FindStringSubmatch(cell); m != nil {
		return m[1]
	}
	return ""
}

// Render is the section's body: the comment saying where it comes from, the
// open bugs and the ones fixed upstream, every link absolute.
func Render(bugs []Bug, fixed []Fixed, base string) string {
	if !strings.HasSuffix(base, "/") {
		base += "/"
	}
	reg := base + "ns3-bugs.md"
	var b strings.Builder
	b.WriteString("<!-- Generated from swarm-routing/sim-tools docs/ns3-bugs.md by swarm-routing/.github\n")
	b.WriteString("     cmd/ns3-bugs (swarm-routing/.github#884); never edit by hand: a change goes to the register. -->\n")
	fmt.Fprintf(&b, "Upstream ns-3 defects our repositories meet, from the org's [ns-3 bug register](%s).\n", reg)
	b.WriteString("Each ID links its RCAPA (the reproduction, the root cause, the upstream report).\n\n")
	b.WriteString("| ID | What breaks | ns-3 versions | Status | Our fix or workaround |\n")
	b.WriteString("|----|-------------|---------------|--------|-----------------------|\n")
	for _, x := range bugs {
		id := x.ID
		if h := firstHref(absolute(x.RCAPA, base)); h != "" {
			id = fmt.Sprintf("[%s](%s)", x.ID, h)
		}
		fmt.Fprintf(&b, "| %s | %s | %s | %s | %s |\n", id, absolute(x.Title, base),
			absolute(x.Versions, base), absolute(x.Status, base), absolute(x.Workaround, base))
	}
	if len(fixed) > 0 {
		b.WriteString("\nFixed upstream, but present in an older ns-3 release you may still pin:\n\n")
		b.WriteString("| What breaks | ns-3 versions | Fixed in | Our fix or workaround |\n")
		b.WriteString("|-------------|---------------|----------|-----------------------|\n")
		for _, x := range fixed {
			fmt.Fprintf(&b, "| %s | %s | %s | %s |\n", absolute(x.Bug, base), absolute(x.Versions, base),
				absolute(x.FixedIn, base), absolute(x.Workaround, base))
		}
	}
	return b.String()
}

const usage = "usage: ns3-bugs REGISTER.md [--base URL] [--write FILE | --check FILE]"

// Main runs the tool: the table on stdout, or written to FILE, or FILE
// compared (exit 1 when it differs). Exit 2 on a usage or register error.
func Main(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("ns3-bugs", flag.ContinueOnError)
	fs.SetOutput(stderr)
	base := fs.String("base", Base, "where the register's relative links resolve")
	write := fs.String("write", "", "write the table to this file")
	check := fs.String("check", "", "compare this file with the table; exit 1 when it differs")
	// the register first, the options after it, as the usage line shows
	var reg string
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		reg, args = args[0], args[1:]
	}
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if reg == "" && fs.NArg() == 1 {
		reg = fs.Arg(0)
	} else if fs.NArg() != 0 {
		reg = ""
	}
	if reg == "" || (*write != "" && *check != "") {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	text, err := os.ReadFile(reg)
	if err != nil {
		fmt.Fprintf(stderr, "ns3-bugs: %v\n", err)
		return 2
	}
	bugs, fixed, err := Parse(string(text))
	if err != nil {
		fmt.Fprintf(stderr, "ns3-bugs: %s: %v\n", reg, err)
		return 2
	}
	out := Render(bugs, fixed, *base)
	switch {
	case *write != "":
		if err := os.WriteFile(*write, []byte(out), 0o644); err != nil {
			fmt.Fprintf(stderr, "ns3-bugs: %v\n", err)
			return 2
		}
		fmt.Fprintf(stdout, "ns3-bugs: wrote %s: %d bug(s), %d fixed upstream\n", *write, len(bugs), len(fixed))
	case *check != "":
		have, err := os.ReadFile(*check)
		if err != nil {
			fmt.Fprintf(stderr, "ns3-bugs: %v\n", err)
			return 2
		}
		if string(have) != out {
			fmt.Fprintf(stdout, "ns3-bugs: %s differs from the register (%d bug(s), %d fixed upstream): run ns3-bugs %s --write %s\n",
				*check, len(bugs), len(fixed), reg, *check)
			return 1
		}
		fmt.Fprintf(stdout, "ns3-bugs: %s matches the register: %d bug(s), %d fixed upstream\n", *check, len(bugs), len(fixed))
	default:
		io.WriteString(stdout, out)
	}
	return 0
}
