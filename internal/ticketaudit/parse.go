// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package ticketaudit

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Boxes counts the task-list checkboxes of an issue body, outside code fences
// and <details> blocks (superseded text).
type Boxes struct {
	Total, Ticked     int // every box of the body
	AC, ACTicked      int // the boxes under an "Acceptance criteria" heading
	Unparseable       bool
	UnparseableReason string
}

// Unticked is the number of open boxes.
func (b Boxes) Unticked() int { return b.Total - b.Ticked }

// Ratio is the ticked share of every box (0 with none).
func (b Boxes) Ratio() float64 {
	if b.Total == 0 {
		return 0
	}
	return float64(b.Ticked) / float64(b.Total)
}

var (
	fenceOpen  = regexp.MustCompile("^ {0,3}(`{3,}|~{3,})")
	detailsIn  = regexp.MustCompile(`(?i)<details(?:\s[^>]*)?>`)
	detailsOut = regexp.MustCompile(`(?i)</details\s*>`)
	box        = regexp.MustCompile(`^\s*(?:>\s*)*(?:[-*+]|\d{1,9}[.)])\s+\[([ xX])\](?:\s|$)`)
	acHeading  = regexp.MustCompile(`(?i)^\s*(?:#{1,6}\s*|\*\*|__)?\s*acceptance[ -]criteria\b`)
	anyHeading = regexp.MustCompile(`^\s{0,3}#{1,6}\s|^\s*(?:\*\*|__)[^*_]+(?:\*\*|__):?\s*$`)
)

// Visible is the body without its code fences and <details> blocks, one entry
// per line kept; ok is false when a fence or a <details> block never closes
// (then nothing about the body is trusted).
func Visible(body string) (lines []string, ok bool, why string) {
	raw := strings.Split(strings.ReplaceAll(body, "\r\n", "\n"), "\n")
	// code fences first: a <details> inside a fence is text
	var unfenced []string
	fence := ""
	for _, l := range raw {
		if fence != "" {
			t := strings.TrimSpace(l)
			if strings.HasPrefix(t, fence) && strings.Trim(t, fence[:1]) == "" {
				fence = ""
			}
			continue
		}
		if m := fenceOpen.FindStringSubmatch(l); m != nil {
			fence = m[1]
			continue
		}
		unfenced = append(unfenced, l)
	}
	if fence != "" {
		return nil, false, "a code fence never closes"
	}
	depth := 0
	for _, l := range unfenced {
		opens := len(detailsIn.FindAllStringIndex(l, -1))
		closes := len(detailsOut.FindAllStringIndex(l, -1))
		inside := depth > 0 || opens > 0
		depth += opens - closes
		if depth < 0 {
			depth = 0
		}
		if !inside {
			lines = append(lines, l)
		}
	}
	if depth > 0 {
		return nil, false, "a <details> block never closes"
	}
	return lines, true, ""
}

// Count reads the checkboxes of an issue body.
func Count(body string) Boxes {
	lines, ok, why := Visible(body)
	if !ok {
		return Boxes{Unparseable: true, UnparseableReason: why}
	}
	var b Boxes
	inAC := false
	for _, l := range lines {
		if acHeading.MatchString(l) && len(strings.TrimSpace(l)) <= 80 {
			inAC = true
			continue
		}
		if inAC && anyHeading.MatchString(l) {
			inAC = false
		}
		m := box.FindStringSubmatch(l)
		if m == nil {
			continue
		}
		ticked := m[1] != " "
		b.Total++
		if ticked {
			b.Ticked++
		}
		if inAC {
			b.AC++
			if ticked {
				b.ACTicked++
			}
		}
	}
	return b
}

// Ref is one issue a text points at: the repository's bare name and the number.
type Ref struct {
	Repo string
	Num  int
}

func (r Ref) String() string { return Org + "/" + r.Repo + "#" + strconv.Itoa(r.Num) }

const refTarget = `(?:(?:https://github\.com/)?` + Org + `/([A-Za-z0-9_.-]+)(?:#|/issues/)|#)(\d{1,7})\b`

var (
	closingRef = regexp.MustCompile(`(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+` + refTarget)
	supersedes = regexp.MustCompile(`(?i)\bsupersedes\b`)
	nextRef    = regexp.MustCompile(`^(?:[\s:*_,&]|\band\b)*` + refTarget)
)

// ClosingRefs is every issue a pull request body closes with a GitHub keyword
// (close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved), in
// the PR's repository (`#N`) or another org repository (`swarm-routing/R#N`
// or its URL); text in fences and <details> blocks is left out.
func ClosingRefs(body, repo string) []Ref {
	lines, ok, _ := Visible(body)
	if !ok {
		return nil
	}
	seen := map[Ref]bool{}
	var out []Ref
	for _, m := range closingRef.FindAllStringSubmatch(strings.Join(lines, "\n"), -1) {
		r := Ref{Repo: repo}
		if m[1] != "" {
			r.Repo = m[1]
		}
		r.Num, _ = strconv.Atoi(m[2])
		if r.Num > 0 && !seen[r] {
			seen[r] = true
			out = append(out, r)
		}
	}
	return out
}

// Superseded is every issue of repo that a handoff body's "Supersedes" lines
// name (`#N`, or the full form of the same repository), sorted.
func Superseded(body, repo string) []int {
	lines, ok, _ := Visible(body)
	if !ok {
		return nil
	}
	seen := map[int]bool{}
	var out []int
	for _, l := range lines {
		loc := supersedes.FindStringIndex(l)
		if loc == nil {
			continue
		}
		// only the references right after the word, joined by commas or "and":
		// "Supersedes #648. The other work keeps #643." names #648 alone
		rest := l[loc[1]:]
		for {
			m := nextRef.FindStringSubmatchIndex(rest)
			if m == nil {
				break
			}
			other, num := "", rest[m[4]:m[5]]
			if m[2] >= 0 {
				other = rest[m[2]:m[3]]
			}
			rest = rest[m[1]:]
			if other != "" && !strings.EqualFold(other, repo) {
				continue
			}
			if n, _ := strconv.Atoi(num); n > 0 && !seen[n] {
				seen[n] = true
				out = append(out, n)
			}
		}
	}
	sort.Ints(out)
	return out
}
