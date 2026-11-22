// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package securityalerts

// Policy findings (Scorecard) are repository policy, not vulnerabilities
// (maintainer decision 2026-11-22, #629): one ticket per Scorecard check
// across the org, in swarm-routing/.github, listing every affected
// repository and its alert; labels security and chore, P2, P1 once any of
// its alerts is past the SLA.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/repomask"
	"github.com/swarm-routing/.github/internal/securityautofix"
)

// PolicyRepo is the repository the policy tickets live in.
const PolicyRepo = ".github"

// PolicyMarker ties a ticket to its Scorecard check.
func PolicyMarker(rule string) string { return "<!-- security-policy: " + rule + " -->" }

var policyRe = regexp.MustCompile(`<!-- security-policy: (\S+) -->`)

// policyAlert is one repository's alert of a check.
type policyAlert struct {
	Repo  Repo
	Alert Alert
}

// Group is one Scorecard check's alerts across the org.
type Group struct {
	Rule   string
	What   string // the check's description (data, quoted)
	Alerts []policyAlert
}

// Key is the group's entry in a Budget.
func (g Group) Key() string { return "policy:" + g.Rule }

// Oldest is the group's oldest alert's creation.
func (g Group) Oldest() time.Time {
	var t time.Time
	for _, a := range g.Alerts {
		if t.IsZero() || a.Alert.Created.Before(t) {
			t = a.Alert.Created
		}
	}
	return t
}

// Priority: P1 once any alert of the check is past its SLA, else P2.
func (g Group) Priority(now time.Time) string {
	for _, a := range g.Alerts {
		if a.Alert.PastSLA(now) {
			return "P1"
		}
	}
	return "P2"
}

// Groups gathers the policy findings of every repository by check.
func Groups(results []Result) []Group {
	by := map[string]*Group{}
	for _, r := range results {
		for _, a := range r.Policy {
			rule := a.What
			if i := strings.Index(rule, ":"); i > 0 {
				rule = rule[:i]
			}
			if rule == "" {
				rule = "unknown"
			}
			g, ok := by[rule]
			if !ok {
				g = &Group{Rule: rule, What: strings.TrimSpace(strings.TrimPrefix(a.What, rule+":"))}
				by[rule] = g
			}
			g.Alerts = append(g.Alerts, policyAlert{r.Repo, a})
		}
	}
	var out []Group
	for _, g := range by {
		sort.Slice(g.Alerts, func(i, j int) bool {
			if g.Alerts[i].Repo.Name != g.Alerts[j].Repo.Name {
				return g.Alerts[i].Repo.Name < g.Alerts[j].Repo.Name
			}
			return g.Alerts[i].Alert.Number < g.Alerts[j].Alert.Number
		})
		out = append(out, *g)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Rule < out[j].Rule })
	return out
}

// PolicyTitle of a check's ticket.
func PolicyTitle(g Group) string {
	return fmt.Sprintf("[security] Scorecard %s: %d repositories", clip(g.Rule, 60), len(repoSet(g)))
}

func repoSet(g Group) map[string]bool {
	s := map[string]bool{}
	for _, a := range g.Alerts {
		s[a.Repo.Name] = true
	}
	return s
}

// PolicyBody of a check's ticket; a private repository is named through m
// and never linked (this ticket is public).
func PolicyBody(g Group, m *repomask.Masker, now time.Time) string {
	lines := []string{PolicyMarker(g.Rule), "## Context", "",
		fmt.Sprintf("OpenSSF Scorecard's `%s` check fails in %d repositories. It is a repository policy finding, "+
			"not a vulnerability: one ticket for the check across the org (#629).", clip(g.Rule, 60), len(repoSet(g)))}
	if g.What != "" {
		lines = append(lines, "", "> "+clip(g.What, 300))
	}
	lines = append(lines, "", "| Repository | Alert | Open since |", "|---|---|---|")
	for _, a := range g.Alerts {
		name := m.Repo(a.Repo.Name, a.Repo.Private, Org+"/"+a.Repo.Name, a.Repo.Name)
		link := fmt.Sprintf("[#%d](%s)", a.Alert.Number, a.Alert.URL)
		if a.Repo.Private {
			link = fmt.Sprintf("#%d", a.Alert.Number)
		}
		since := a.Alert.Created.UTC().Format("2006-01-02")
		if a.Alert.PastSLA(now) {
			since += " (past its SLA)"
		}
		lines = append(lines, fmt.Sprintf("| %s | %s | %s |", name, link, since))
	}
	lines = append(lines, "", "## Proposal", "")
	if fix, ok := securityautofix.SettingsFix(g.Rule); ok {
		lines = append(lines, "A settings-as-code change fixes it: "+fix+". That PR is the maintainer's call: it changes "+
			"how the repositories are governed. Or dismiss the alerts with the reason, where the policy is set on purpose.")
	} else {
		lines = append(lines, "Dismiss the alerts with the reason (the policy is set on purpose, or does not apply), or "+
			"change the policy through `[settings]` in each repository's `.github/org-sync.toml`.")
	}
	lines = append(lines, "", "Dismissing an alert is the maintainer's decision: no agent or task dismisses one.", "",
		"## Acceptance criteria", "",
		"- [ ] Every alert above is fixed by a settings change, or dismissed by the maintainer with its reason.", "",
		"Kept by the hourly `security-alerts` task (swarm-routing/.github `cmd/security-alerts`): updated in place, "+
			"closed when no repository has the check's alert open.")
	return strings.Join(lines, "\n") + Footer
}

// PolicyLabels of a check's ticket.
func PolicyLabels(g Group, now time.Time) []string {
	return []string{Label, "chore", "ci", "model:haiku-5.5", "priority:" + g.Priority(now)}
}

// policyTickets are the open policy tickets in PolicyRepo, by check.
func policyTickets(g GitHub) (map[string]Issue, error) {
	issues, err := list[Issue](g, "repos/"+Org+"/"+PolicyRepo+"/issues?state=open&labels="+Label)
	if err != nil {
		return nil, err
	}
	out := map[string]Issue{}
	for _, i := range issues {
		if m := policyRe.FindStringSubmatch(i.Body); m != nil && i.PR == nil {
			out[m[1]] = i
		}
	}
	return out, nil
}

// SyncPolicy keeps one ticket per Scorecard check; mayClose is false when a
// code-scanning listing could not be read, so a check is never closed on
// missing data.
func SyncPolicy(g GitHub, groups []Group, tickets map[string]Issue, b *Budget, m *repomask.Masker, now time.Time,
	dry, mayClose bool) (opened, updated, closed, deferred int, msgs []string, err error) {
	full := Org + "/" + PolicyRepo
	seen := map[string]bool{}
	for _, grp := range groups {
		seen[grp.Rule] = true
		title, body, labels := PolicyTitle(grp), PolicyBody(grp, m, now), PolicyLabels(grp, now)
		t, ok := tickets[grp.Rule]
		if !ok {
			if b != nil && !b.Allow[grp.Key()] {
				deferred++
				continue
			}
			opened++
			msg := fmt.Sprintf("Scorecard %s: open a ticket (%d repositories, priority:%s)", grp.Rule, len(repoSet(grp)), grp.Priority(now))
			if !dry {
				data, e := g.do("POST", "repos/"+full+"/issues", map[string]any{"title": title, "body": body, "labels": labels})
				if e != nil {
					return opened, updated, closed, deferred, msgs, e
				}
				var got Issue
				_ = json.Unmarshal(data, &got)
				msg = fmt.Sprintf("Scorecard %s: opened #%d (%d repositories, priority:%s)", grp.Rule, got.Number, len(repoSet(grp)), grp.Priority(now))
			}
			msgs = append(msgs, msg)
			continue
		}
		want := mergeLabels(t.labelNames(), labels)
		if t.Title == title && t.Body == body && sameSet(t.labelNames(), want) {
			continue
		}
		updated++
		msgs = append(msgs, fmt.Sprintf("Scorecard %s: update #%d", grp.Rule, t.Number))
		if !dry {
			if _, e := g.do("PATCH", fmt.Sprintf("repos/%s/issues/%d", full, t.Number),
				map[string]any{"title": title, "body": body, "labels": want}); e != nil {
				return opened, updated, closed, deferred, msgs, e
			}
		}
	}
	if !mayClose {
		return
	}
	rules := make([]string, 0, len(tickets))
	for r := range tickets {
		rules = append(rules, r)
	}
	sort.Strings(rules)
	for _, r := range rules {
		if seen[r] {
			continue
		}
		t := tickets[r]
		closed++
		msgs = append(msgs, fmt.Sprintf("Scorecard %s: close #%d: no repository has its alert open", r, t.Number))
		if !dry {
			c := "No repository has an open alert of this check any more (fixed, or dismissed by the maintainer): closing." + Footer
			if _, e := g.do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", full, t.Number), map[string]any{"body": c}); e != nil {
				return opened, updated, closed, deferred, msgs, e
			}
			if _, e := g.do("PATCH", fmt.Sprintf("repos/%s/issues/%d", full, t.Number),
				map[string]any{"state": "closed", "state_reason": "completed"}); e != nil {
				return opened, updated, closed, deferred, msgs, e
			}
		}
	}
	return
}

// planItem is one new ticket a run may open.
type planItem struct {
	key     string
	prio    string
	created time.Time
}

// Plan picks the run's new tickets: the limit highest-priority, then oldest,
// across every repository and policy group; it returns the Budget and how
// many new tickets wait.
func Plan(results []Result, groups []Group, tickets map[string]Issue, limit int, now time.Time) (*Budget, int) {
	var items []planItem
	for _, r := range results {
		for _, a := range r.New {
			items = append(items, planItem{a.URL, a.Priority(now), a.Created})
		}
	}
	for _, g := range groups {
		if _, ok := tickets[g.Rule]; !ok {
			items = append(items, planItem{g.Key(), g.Priority(now), g.Oldest()})
		}
	}
	sort.SliceStable(items, func(i, j int) bool {
		if items[i].prio != items[j].prio {
			return items[i].prio < items[j].prio
		}
		if !items[i].created.Equal(items[j].created) {
			return items[i].created.Before(items[j].created)
		}
		return items[i].key < items[j].key
	})
	b := &Budget{Allow: map[string]bool{}}
	for i, it := range items {
		if i >= limit {
			break
		}
		b.Allow[it.key] = true
	}
	return b, len(items) - len(b.Allow)
}
