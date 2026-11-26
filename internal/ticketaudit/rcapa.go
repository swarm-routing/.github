// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package ticketaudit

import (
	"fmt"
	"regexp"
	"strings"
	"time"
)

// The RCAPA pass (#952). An issue opened through the API gets none of its
// form's labels, so an open issue whose title starts `[rcapa]` but lacks
// `rcapa` gets the form's labels added (ISSUE_TEMPLATE/rcapa.yml for an
// NS3-NNN, rcapa-regression.yml otherwise). An RCAPA ticket older than
// RCAPAGrace with no `<!-- rcapa-step: ... -->` comment (tools/rcapa/rcapa.py
// log) and no pull request that references it is listed in the report, never
// changed.

const (
	// MaxLabels bounds the issues one run labels (golden rule 7).
	MaxLabels = 20
	// RCAPAGrace is how long a new RCAPA ticket may go without a logged step.
	RCAPAGrace = 48 * time.Hour
)

var (
	rcapaTitle = regexp.MustCompile(`(?i)^\s*\[rcapa\]`)
	ns3ID      = regexp.MustCompile(`\bNS3-\d+\b`)
	stepMarker = regexp.MustCompile(`<!--\s*rcapa-step:\s*[a-z-]+\s*-->`)
	ns3Labels  = []string{"rcapa", "ns3-upstream", "verification", "ns3"}
	regrLabels = []string{"rcapa", "bug"}
)

// rcapaLabels is what the form would have set and the issue lacks, or nil
// for an issue that is not an unlabelled RCAPA ticket.
func rcapaLabels(i Issue) []string {
	if !rcapaTitle.MatchString(i.Title) || i.has("rcapa") {
		return nil
	}
	want := regrLabels
	if ns3ID.MatchString(i.Title) {
		want = ns3Labels
	}
	var out []string
	for _, l := range want {
		if !i.has(l) {
			out = append(out, l)
		}
	}
	return out
}

type comment struct {
	Body string `json:"body"`
}

type timelineEvent struct {
	Event  string `json:"event"`
	Source struct {
		Issue struct {
			PR *struct{} `json:"pull_request"`
		} `json:"issue"`
	} `json:"source"`
}

// recorded says whether an RCAPA ticket carries its investigation: a logged
// step, or a pull request that references it. An unreadable answer counts as
// recorded: the report flags only what it saw.
func (a *auditor) recorded(r Repo, n int) bool {
	cs, err := list[comment](a.g, fmt.Sprintf("repos/%s/issues/%d/comments?", r.FullName, n))
	if err != nil {
		return true
	}
	for _, c := range cs {
		if stepMarker.MatchString(c.Body) {
			return true
		}
	}
	evs, err := list[timelineEvent](a.g, fmt.Sprintf("repos/%s/issues/%d/timeline?", r.FullName, n))
	if err != nil {
		return true
	}
	for _, e := range evs {
		if e.Event == "cross-referenced" && e.Source.Issue.PR != nil {
			return true
		}
	}
	return false
}

// rcapa runs the pass on one repository's open issues, before decide: a
// label it adds is on the issue for the keep rule too.
func (a *auditor) rcapa(r Repo, open []Issue, res *Result) {
	for k := range open {
		i := &open[k]
		if add := rcapaLabels(*i); add != nil {
			name := a.label(r)
			if !r.private() {
				name = fmt.Sprintf("%s/%s#%d", Org, r.Name, i.Number)
			}
			line := fmt.Sprintf("- %s: added %s", name, "`"+strings.Join(add, "`, `")+"`")
			switch {
			case res.labelBudget() <= 0:
				fmt.Fprintf(a.out, "%s: an [rcapa] ticket without rcapa; deferred (%d a run)\n", name, MaxLabels)
				continue
			case a.dry:
				fmt.Fprintf(a.out, "%s: dry run: would add %s\n", name, strings.Join(add, ", "))
				line = fmt.Sprintf("- %s: would add %s", name, "`"+strings.Join(add, "`, `")+"`")
			default:
				if _, err := a.g.do("POST", fmt.Sprintf("repos/%s/issues/%d/labels", r.FullName, i.Number),
					map[string]any{"labels": add}); err != nil {
					fmt.Fprintf(a.out, "%s: labelling failed: %v\n", name, a.mask.Error(err))
					res.Failed++
					continue
				}
				fmt.Fprintf(a.out, "%s: added %s\n", name, strings.Join(add, ", "))
			}
			res.Labelled = append(res.Labelled, line)
			for _, l := range add {
				i.Labels = append(i.Labels, label{Name: l})
			}
		}
		if !i.has("rcapa") || a.now.Sub(i.CreatedAt) < RCAPAGrace || a.recorded(r, i.Number) {
			continue
		}
		if r.private() {
			res.UnrecordedPrivate++
			continue
		}
		days := int(a.now.Sub(i.CreatedAt).Hours() / 24)
		res.Unrecorded = append(res.Unrecorded, fmt.Sprintf("- %s/%s#%d: opened %d days ago, no logged step and no linked PR",
			Org, r.Name, i.Number, days))
		fmt.Fprintf(a.out, "unrecorded rcapa: %s/%s#%d\n", Org, r.Name, i.Number)
	}
}

func (res *Result) labelBudget() int { return MaxLabels - len(res.Labelled) }
