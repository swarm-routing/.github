// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package projectsync

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// Issue is the part of an issue the sync reads (REST).
type Issue struct {
	NodeID      string  `json:"node_id"`
	Number      int     `json:"number"`
	State       string  `json:"state"`
	StateReason *string `json:"state_reason"`
	Labels      []struct {
		Name string `json:"name"`
	} `json:"labels"`
	PullRequest *struct{} `json:"pull_request"`
	SubIssues   *struct {
		Total     int `json:"total"`
		Completed int `json:"completed"`
	} `json:"sub_issues_summary"`
	Repo string `json:"-"` // the repository's name, set by the reader
}

func (i Issue) has(label string) bool {
	for _, l := range i.Labels {
		if l.Name == label {
			return true
		}
	}
	return false
}

func (i Issue) withPrefix(p string) []string {
	var out []string
	for _, l := range i.Labels {
		if strings.HasPrefix(l.Name, p) && len(l.Name) > len(p) {
			out = append(out, l.Name[len(p):])
		}
	}
	return out
}

// Key names an issue in the output: <repo>#<number>.
func (i Issue) Key() string { return fmt.Sprintf("%s#%d", i.Repo, i.Number) }

// Matches says whether an add rule takes the issue.
func (d *Definition) Matches(i Issue) bool {
	for _, r := range d.Add {
		if i.State != "open" && !r.Closed {
			continue
		}
		if (r.Label != "" && i.has(r.Label)) || (r.LabelPrefix != "" && len(i.withPrefix(r.LabelPrefix)) > 0) {
			return true
		}
	}
	return false
}

// Value derives a field's value for an issue; "" leaves the field empty.
func (f Field) Value(i Issue) string {
	switch f.From {
	case "status":
		switch {
		case i.State == "closed" && (i.StateReason == nil || *i.StateReason == "completed"):
			return StatusDone
		case i.State == "closed":
			return StatusDropped
		case i.SubIssues != nil && i.SubIssues.Completed > 0:
			return StatusInProgress
		}
		return StatusOpen
	case "label_prefix":
		v := i.withPrefix(f.Prefix)
		if len(v) == 0 {
			return ""
		}
		SortVersions(v)
		return v[len(v)-1]
	case "labels":
		for _, o := range f.Options {
			if (o.Label != "" && i.has(o.Label)) || (o.LabelPrefix != "" && len(i.withPrefix(o.LabelPrefix)) > 0) {
				return o.Name
			}
		}
		return ""
	case "sub_issues":
		if i.SubIssues == nil || i.SubIssues.Total == 0 {
			return ""
		}
		return fmt.Sprintf("%d/%d", i.SubIssues.Completed, i.SubIssues.Total)
	}
	return ""
}

// WantedOptions is a single-select field's options: the listed ones, or for
// a field derived from a label prefix the values the issues carry, in
// version order.
func (f Field) WantedOptions(issues []Issue) []Option {
	if f.From != "label_prefix" {
		return f.Options
	}
	seen := map[string]bool{}
	var vals []string
	for _, i := range issues {
		if v := f.Value(i); v != "" && !seen[v] {
			seen[v] = true
			vals = append(vals, v)
		}
	}
	SortVersions(vals)
	out := make([]Option, 0, len(vals))
	for _, v := range vals {
		out = append(out, Option{Name: v, Color: f.Color})
	}
	return out
}

// SortVersions orders vX.Y.Z numerically, then anything else by text.
func SortVersions(v []string) {
	key := func(s string) ([3]int, bool) {
		var k [3]int
		p := strings.Split(strings.TrimPrefix(s, "v"), ".")
		if len(p) != 3 {
			return k, false
		}
		for j, x := range p {
			n, err := strconv.Atoi(x)
			if err != nil || n < 0 {
				return k, false
			}
			k[j] = n
		}
		return k, true
	}
	sort.SliceStable(v, func(a, b int) bool {
		ka, oka := key(v[a])
		kb, okb := key(v[b])
		if oka != okb {
			return oka
		}
		if oka && ka != kb {
			return ka[0] < kb[0] || (ka[0] == kb[0] && (ka[1] < kb[1] || (ka[1] == kb[1] && ka[2] < kb[2])))
		}
		return v[a] < v[b]
	})
}
