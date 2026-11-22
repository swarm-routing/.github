// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The maintainer's answers to five owner-only criteria (maintainer decision
// 2026-11-17, swarm-routing/AntHocNet#790): attested once in
// swarm-routing/.github's OwnerFile, proposed by the weekly check so the
// maintainer only presses Save. Three of them are facts the check verifies
// at run time from the repository's security alerts (code scanning,
// Dependabot, secret scanning), read with the bot's token.
//
// The two vulnerability criteria are Met by default (maintainer decision
// 2026-11-17, swarm-routing/.github#629): every alert starts the automated
// fix pipeline (security-autofix.yml), and the answer is withdrawn only when
// a medium-or-higher alert stays open past EscalateDays (an escalation
// margin before the criterion's 60) or a critical one past CriticalDays. An
// alert listing the token cannot read is reported, never withdraws them.
// no_leaked_credentials is withdrawn by any open secret alert, or an
// unreadable secret listing: nothing is assumed there.

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/securityalerts"
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

// The age guard (#629): vulnerabilities_fixed_60_days is withdrawn by a
// medium-or-higher alert open more than EscalateDays, and
// vulnerabilities_critical_fixed by a critical one open more than
// CriticalDays.
// They are the security-alerts task's SLA, which raises the alert's ticket
// to P1 on the same thresholds (#629).
const (
	EscalateDays = securityalerts.EscalateDays
	CriticalDays = securityalerts.CriticalDays
)

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

// alert is one open security alert, read by securityalerts.FromJSON, the
// reading the security-alerts tickets use (#680).
type alert struct{ securityalerts.Alert }

func (a alert) String() string {
	s := fmt.Sprintf("%s alert #%d", a.Kind, a.Number)
	if a.Security {
		s += " (" + a.Severity + ")"
	}
	if !a.Created.IsZero() {
		s += ", open since " + a.Created.UTC().Format("2006-01-02")
	}
	return s + ": " + a.URL
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
		a, err := securityalerts.FromJSON(kind, x)
		if err != nil {
			return alertRead{err: err.Error()}
		}
		out.alerts = append(out.alerts, alert{a})
	}
	return out
}

// severityRank orders the security severities; an alert without one (a
// code-scanning quality rule) ranks 0 and never counts as a vulnerability.
var severityRank = map[string]int{"low": 1, "medium": 2, "high": 3, "critical": 4}

func (a alert) rank() int {
	if !a.Security {
		return 0
	}
	return severityRank[a.Severity]
}

// olderThan: the alert was opened more than days ago.
func (a alert) olderThan(days int) bool {
	return !a.Created.IsZero() && a.Age(now()) > time.Duration(days)*24*time.Hour
}

// openCount is the vulnerability answers' sentence on today's alerts (#680):
// how many code-scanning and Dependabot alerts of at least minRank are open
// and the oldest one, or which listing could not be read.
func openCount(reads map[string]alertRead, minRank int, what string) string {
	var oldest *alert
	n := 0
	var unread []string
	for _, k := range []string{"code scanning", "Dependabot"} {
		if reads[k].err != "" {
			unread = append(unread, k)
			continue
		}
		for i, a := range reads[k].alerts {
			if a.rank() < minRank {
				continue
			}
			n++
			if oldest == nil || a.Created.Before(oldest.Created) {
				oldest = &reads[k].alerts[i]
			}
		}
	}
	var s string
	switch {
	case n == 0:
		s = fmt.Sprintf(" Open now: no %s code-scanning or Dependabot alert", what)
	case n == 1:
		s = fmt.Sprintf(" Open now: 1 %s alert, %s", what, oldest)
	default:
		s = fmt.Sprintf(" Open now: %d %s alerts, the oldest %s", n, what, oldest)
	}
	if len(unread) > 0 {
		s += " (the " + strings.Join(unread, " and ") + " alerts could not be read)"
	}
	return s + "."
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
		rep.Answers[c] = [2]string{a[0], why}
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
		if !seen[a.URL] {
			seen[a.URL] = true
			rep.Alerts = append(rep.Alerts, a)
		}
	}
	// default Met: an unreadable listing is reported (rep.Unread), and only
	// an alert past its age withdraws the answer
	for _, k := range []string{"code scanning", "Dependabot"} {
		for _, a := range reads[k].alerts {
			r := a.rank()
			if r >= 2 && a.olderThan(EscalateDays) {
				blockBy("vulnerabilities_fixed_60_days", a)
			}
			if r >= 4 && a.olderThan(CriticalDays) {
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
	guard := map[string]string{
		"vulnerabilities_fixed_60_days":  fmt.Sprintf("a medium-or-higher alert stays open more than %d days", EscalateDays),
		"vulnerabilities_critical_fixed": fmt.Sprintf("a critical alert stays open more than %d days", CriticalDays),
	}
	today := map[string]string{
		"vulnerabilities_fixed_60_days":  openCount(reads, 2, "medium-or-higher"),
		"vulnerabilities_critical_fixed": openCount(reads, 4, "critical"),
	}
	for _, c := range []string{"vulnerabilities_fixed_60_days", "vulnerabilities_critical_fixed"} {
		if a, ok := rep.Answers[c]; ok {
			rep.Answers[c] = [2]string{a[0], a[1] + " Every code-scanning alert starts an automated fix " +
				"(security-autofix.yml) and Dependabot opens security updates; the weekly check withdraws " +
				"this answer when " + guard[c] + ": " + security + "." + today[c]}
		}
	}
	if a, ok := rep.Answers["no_leaked_credentials"]; ok {
		rep.Answers["no_leaked_credentials"] = [2]string{a[0], a[1] + " The weekly check reads this " +
			"repository's open secret-scanning alerts and finds none: " + security + "."}
	}
	// the attestation is cited once, by URL, in the first attested answer
	// (form order); the others name that answer, so the links do not repeat
	// the URL five times (#626)
	first := ""
	for _, c := range attestedOrder {
		a, ok := rep.Answers[c]
		if !ok {
			continue
		}
		if first == "" {
			first = c
			a[1] += " (maintainer attestation, " + att.Decided + ": " + att.URL + ")"
		} else {
			a[1] += " (maintainer attestation, " + att.Decided + ", cited in " + first + ")"
		}
		rep.Answers[c] = a
	}
	sort.Slice(rep.Alerts, func(i, j int) bool { return rep.Alerts[i].URL < rep.Alerts[j].URL })
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
