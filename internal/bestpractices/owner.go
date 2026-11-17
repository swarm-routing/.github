// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The maintainer's answers to five owner-only criteria (maintainer decision
// 2026-11-17, swarm-routing/AntHocNet#790): attested once in
// swarm-routing/.github's OwnerFile, proposed by the weekly check so the
// maintainer only presses Save. Three of them are facts the check verifies
// at run time from the repository's security alerts (code scanning,
// Dependabot, secret scanning), read with the bot's token: an open alert
// that contradicts one, or an alert listing the token cannot read, leaves
// it `?`. Nothing is assumed Met.

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// OwnerFile is the attestation, in swarm-routing/.github.
const OwnerFile = ".github/bestpractices-owner.toml"

// Attested is the owner-only criteria the check may propose from OwnerFile.
var Attested = map[string]bool{
	"know_secure_design": true, "know_common_errors": true, "vulnerabilities_fixed_60_days": true,
	"vulnerabilities_critical_fixed": true, "no_leaked_credentials": true,
}

// attestedOrder is Attested in the form's order.
var attestedOrder = []string{
	"know_secure_design", "know_common_errors", "vulnerabilities_fixed_60_days",
	"vulnerabilities_critical_fixed", "no_leaked_credentials",
}

// now is the clock the alert ages are measured with (tests set it).
var now = time.Now

// Attestation is OwnerFile: per criterion its status and justification.
type Attestation struct {
	Decided string
	URL     string // OwnerFile on main, cited by every answer
	Answers map[string][2]string
}

// LoadAttestation reads OwnerFile from swarm-routing/.github's main; nil
// when it is absent or not usable (every attested criterion stays `?`).
func LoadAttestation(r Remote) (*Attestation, error) {
	text, ok, err := r.File(".github", OwnerFile)
	if err != nil || !ok {
		return nil, err
	}
	cfg, err := parseTOML(text)
	if err != nil {
		return nil, failure("bestpractices: %s: %v", OwnerFile, err)
	}
	a := &Attestation{
		Decided: pyStr(cfg["decided"]),
		URL:     "https://github.com/" + Org + "/.github/blob/main/" + OwnerFile,
		Answers: map[string][2]string{},
	}
	for _, c := range attestedOrder {
		t, ok := cfg[c].(map[string]any)
		if !ok {
			continue
		}
		st, _ := t["status"].(string)
		why, _ := t["justification"].(string)
		if st == "Met" && strings.TrimSpace(why) != "" {
			a.Answers[c] = [2]string{st, strings.TrimSpace(why)}
		}
	}
	return a, nil
}

// alert is one open security alert, as the issue lists it.
type alert struct {
	kind, severity, created, url string
	number                       string
}

func (a alert) String() string {
	s := fmt.Sprintf("%s alert #%s", a.kind, a.number)
	if a.severity != "" {
		s += " (" + a.severity + ")"
	}
	if a.created != "" {
		s += ", open since " + a.created[:min(10, len(a.created))]
	}
	return s + ": " + a.url
}

// alertRead is one listing's result: the open alerts, or why it could not
// be read.
type alertRead struct {
	alerts []alert
	err    string
}

// AlertReader lists a repository's open security alerts of one kind
// (path: code-scanning/alerts, dependabot/alerts, secret-scanning/alerts);
// a 404 is (nil, nil). The real network implements it with the bot's token.
type AlertReader interface {
	Alerts(repo, path string) (any, error)
}

// Alerts lists the open alerts at repos/<org>/<repo>/<path>.
func (h *HTTP) Alerts(repo, path string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/%s?state=open&per_page=100", Org, repo, path), nil, true)
}

// readAlerts lists one kind of open alert. A 404 (the feature is off, or no
// access) and an error (no permission) are both unreadable.
func readAlerts(gh AlertReader, repo, kind, path string) alertRead {
	got, err := gh.Alerts(repo, path)
	if err != nil {
		return alertRead{err: described(err)}
	}
	list, ok := got.([]any)
	if !ok {
		return alertRead{err: kind + " alerts are not available (HTTP 404: not enabled, or no access)"}
	}
	var out alertRead
	for _, x := range list {
		m, _ := x.(map[string]any)
		a := alert{kind: kind, number: pyStr(m["number"]), url: pyStr(m["html_url"])}
		a.created, _ = m["created_at"].(string)
		switch kind {
		case "code scanning":
			if rule, ok := m["rule"].(map[string]any); ok {
				a.severity, _ = rule["security_severity_level"].(string)
			}
		case "Dependabot":
			if adv, ok := m["security_advisory"].(map[string]any); ok {
				a.severity, _ = adv["severity"].(string)
			}
		}
		out.alerts = append(out.alerts, a)
	}
	return out
}

var severityRank = map[string]int{"low": 1, "medium": 2, "moderate": 2, "high": 3, "critical": 4}

// olderThan: the alert was opened more than days ago.
func (a alert) olderThan(days int) bool {
	t, err := time.Parse(time.RFC3339, a.created)
	return err == nil && now().Sub(t) > time.Duration(days)*24*time.Hour
}

// OwnerReport is what the check proposes for the attested criteria.
type OwnerReport struct {
	Answers  map[string][2]string // proposed: status, justification
	Blocked  map[string]string    // left `?`: why
	Alerts   []alert              // open alerts that block an answer
	Unread   []string             // listings the token could not read
	Checked  bool                 // the alerts were read at all
	Attested bool                 // OwnerFile was found
}

// ownerAnswers derives the attested answers for one repository. proposed is
// its .bestpractices.json (the evidence know_common_errors names), tree its
// main (a core/ is named in know_secure_design), gh the API the alerts are
// read through (nil: none can be read).
func ownerAnswers(att *Attestation, repo string, proposed map[string]any, tree map[string]bool, gh AlertReader) OwnerReport {
	rep := OwnerReport{Answers: map[string][2]string{}, Blocked: map[string]string{}, Attested: att != nil}
	if att == nil {
		for _, c := range attestedOrder {
			rep.Blocked[c] = "no maintainer attestation (" + OwnerFile + " in swarm-routing/.github)"
		}
		return rep
	}
	cite := " (maintainer attestation, " + att.Decided + ": " + att.URL + ")"
	security := fmt.Sprintf("https://github.com/%s/%s/security", Org, repo)
	for _, c := range attestedOrder {
		a, ok := att.Answers[c]
		if !ok {
			rep.Blocked[c] = "not attested in " + OwnerFile
			continue
		}
		why := a[1]
		switch c {
		case "know_secure_design":
			if tree["core"] || tree["core/"] {
				why += " The core is kept free of simulator and I/O dependencies."
			}
		case "know_common_errors":
			ev := commonErrorEvidence(proposed)
			if ev == "" {
				rep.Blocked[c] = "no CI check of common errors in " + Out + " to name"
				continue
			}
			why += " In this repository: " + ev
		}
		rep.Answers[c] = [2]string{a[0], why + cite}
	}

	// the three facts: read the alerts, never assume
	reads := map[string]alertRead{}
	if gh == nil {
		for _, k := range []string{"code scanning", "Dependabot", "secret scanning"} {
			reads[k] = alertRead{err: "no alert reader"}
		}
	} else {
		reads["code scanning"] = readAlerts(gh, repo, "code scanning", "code-scanning/alerts")
		reads["Dependabot"] = readAlerts(gh, repo, "Dependabot", "dependabot/alerts")
		reads["secret scanning"] = readAlerts(gh, repo, "secret scanning", "secret-scanning/alerts")
	}
	rep.Checked = true
	kinds := []string{"code scanning", "Dependabot", "secret scanning"}
	for _, k := range kinds {
		if reads[k].err != "" {
			rep.Unread = append(rep.Unread, k+": "+reads[k].err)
		}
	}
	block := func(c, why string) {
		if _, ok := rep.Answers[c]; ok {
			delete(rep.Answers, c)
			rep.Blocked[c] = why
		}
	}
	seen := map[string]bool{}
	blockBy := func(c string, a alert) {
		block(c, "open "+a.String())
		if !seen[a.url] {
			seen[a.url] = true
			rep.Alerts = append(rep.Alerts, a)
		}
	}
	for _, k := range []string{"code scanning", "Dependabot"} {
		if reads[k].err != "" {
			block("vulnerabilities_fixed_60_days", "cannot read the "+k+" alerts: "+reads[k].err)
			block("vulnerabilities_critical_fixed", "cannot read the "+k+" alerts: "+reads[k].err)
		}
		for _, a := range reads[k].alerts {
			r := severityRank[strings.ToLower(a.severity)]
			if r >= 2 && a.olderThan(60) {
				blockBy("vulnerabilities_fixed_60_days", a)
			}
			if r >= 4 {
				blockBy("vulnerabilities_critical_fixed", a)
			}
		}
	}
	if r := reads["secret scanning"]; r.err != "" {
		block("no_leaked_credentials", "cannot read the secret scanning alerts: "+r.err)
	} else {
		for _, a := range r.alerts {
			blockBy("no_leaked_credentials", a)
		}
	}
	for _, c := range []string{"vulnerabilities_fixed_60_days", "vulnerabilities_critical_fixed", "no_leaked_credentials"} {
		if a, ok := rep.Answers[c]; ok {
			rep.Answers[c] = [2]string{a[0], a[1] + " The weekly check reads this repository's open " +
				"code-scanning, Dependabot and secret-scanning alerts and finds none against it: " + security + "."}
		}
	}
	sort.Slice(rep.Alerts, func(i, j int) bool { return rep.Alerts[i].url < rep.Alerts[j].url })
	return rep
}

// commonErrorEvidence names the CI checks for common errors the
// repository's .bestpractices.json already justifies: only tools it runs.
func commonErrorEvidence(proposed map[string]any) string {
	var out []string
	for _, c := range []string{"dynamic_analysis", "dynamic_analysis_unsafe",
		"static_analysis_common_vulnerabilities", "static_analysis", "warnings_strict"} {
		if pyEqual(proposed[c+"_status"], "Met") {
			why := strings.TrimSpace(pyStr(proposed[c+"_justification"]))
			if why != "" {
				out = append(out, why)
			}
		}
	}
	return strings.Join(out, " ")
}

// merge returns proposed with the attested answers in place of the file's `?`.
func (o OwnerReport) merge(proposed map[string]any) map[string]any {
	out := make(map[string]any, len(proposed)+2*len(o.Answers))
	for k, v := range proposed {
		out[k] = v
	}
	for c, a := range o.Answers {
		out[c+"_status"], out[c+"_justification"] = a[0], a[1]
	}
	return out
}
