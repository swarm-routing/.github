// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The attested owner-only answers against a fake alert API: proposed only
// when every listing reads and no open alert stands against them.

import (
	"bytes"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

type fakeAlerts struct {
	lists map[string]any   // path -> the listing (absent: 404)
	errs  map[string]error // path -> an error (no permission)
	asked []string
}

func (f *fakeAlerts) Alerts(repo, path string) (any, error) {
	f.asked = append(f.asked, repo+" "+path)
	if err, ok := f.errs[path]; ok {
		return nil, err
	}
	if l, ok := f.lists[path]; ok {
		return l, nil
	}
	return nil, nil
}

// clean: every listing reads, none has an alert.
func clean() *fakeAlerts {
	return &fakeAlerts{lists: map[string]any{
		"code-scanning/alerts": []any{}, "dependabot/alerts": []any{}, "secret-scanning/alerts": []any{},
	}, errs: map[string]error{}}
}

// attestation is a copy of the repository's OwnerFile in testdata, so the
// tests also run where only cmd/ and internal/ are present (the ci-tools image
// build). TestOwnerTestdataMatches keeps the copy equal to the real file.
func attestation(t *testing.T) *Attestation {
	t.Helper()
	text, err := os.ReadFile("testdata/owner.toml")
	if err != nil {
		t.Fatal(err)
	}
	f := &fake{files: map[[2]string]string{{".github", OwnerFile}: string(text)}}
	a, err := LoadAttestation(f)
	if err != nil || a == nil {
		t.Fatalf("the attestation: %v", err)
	}
	return a
}

var evidence = map[string]any{
	"dynamic_analysis_status":        "Met",
	"dynamic_analysis_justification": "Dynamic analysis (AddressSanitizer) in CI: https://github.com/swarm-routing/X/blob/main/.github/workflows/core.yml.",
}

func setNow(t *testing.T, s string) {
	t.Helper()
	at, _ := time.Parse(time.RFC3339, s)
	old := now
	now = func() time.Time { return at }
	t.Cleanup(func() { now = old })
}

func TestOwnerAllClear(t *testing.T) {
	att := attestation(t)
	if att.Decided != "2026-11-17" || len(att.Answers) != 5 {
		t.Fatalf("attestation: %+v", att)
	}
	f := clean()
	o := ownerAnswers(att, "X", evidence, map[string]bool{"core": true}, f)
	if len(o.Answers) != 5 || len(o.Blocked) != 0 || len(o.Unread) != 0 {
		t.Fatalf("all clear: %+v", o)
	}
	for c, a := range o.Answers {
		cites := strings.Contains(a[1], att.URL)
		if a[0] != "Met" || cites != (c == "know_secure_design") ||
			(!cites && !strings.HasSuffix(a[1], "(maintainer attestation, 2026-11-17, cited in know_secure_design)")) {
			t.Errorf("%s cites the attestation once, the others name that answer: %s", c, a[1])
		}
	}
	if !strings.Contains(o.Answers["know_secure_design"][1], "core is kept free") {
		t.Error("a repository with core/: the core clause")
	}
	if !strings.Contains(o.Answers["know_common_errors"][1], "AddressSanitizer") ||
		strings.Contains(o.Answers["know_common_errors"][1], "CodeQL") {
		t.Error("know_common_errors names the repository's own checks only")
	}
	links, err := ProposalURLs("7", Answers{{"know_secure_design", "Met", "x"}, {"report_responses", "Met", "y"}},
		"passing", ProposalLimit)
	if err != nil || len(links) != 1 || !strings.Contains(links[0], "know_secure_design_status=Met") ||
		strings.Contains(links[0], "report_responses") {
		t.Errorf("an attested criterion is proposed, a non-attested owner-only one never: %v", links)
	}
	m := o.merge(map[string]any{"know_secure_design_status": "?"})
	if m["know_secure_design_status"] != "Met" {
		t.Error("merge replaces the file's ?")
	}
	none := ownerAnswers(att, "X", evidence, map[string]bool{}, clean())
	if strings.Contains(none.Answers["know_secure_design"][1], "core") {
		t.Error("no core/: no core clause")
	}
	if no := ownerAnswers(att, "X", map[string]any{}, nil, clean()); no.Blocked["know_common_errors"] == "" {
		t.Error("no CI check to name: know_common_errors ?")
	}
}

func TestOwnerOpenAlertBlocks(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	f := clean()
	f.lists["code-scanning/alerts"] = []any{
		map[string]any{"number": 3, "html_url": "https://github.com/swarm-routing/X/security/code-scanning/3",
			"created_at": "2026-08-01T00:00:00Z", "rule": map[string]any{"security_severity_level": "high"}},
		map[string]any{"number": 4, "html_url": "https://github.com/swarm-routing/X/security/code-scanning/4",
			"created_at": "2026-11-16T00:00:00Z", "rule": map[string]any{"security_severity_level": "medium"}},
	}
	f.lists["secret-scanning/alerts"] = []any{
		map[string]any{"number": 1, "html_url": "https://github.com/swarm-routing/X/security/secret-scanning/1",
			"created_at": "2026-11-16T00:00:00Z"},
	}
	o := ownerAnswers(attestation(t), "X", evidence, nil, f)
	for _, c := range []string{"vulnerabilities_fixed_60_days", "no_leaked_credentials"} {
		if _, ok := o.Answers[c]; ok || !strings.HasPrefix(o.Blocked[c], "open ") {
			t.Errorf("%s: an open alert blocks it: %q", c, o.Blocked[c])
		}
	}
	if _, ok := o.Answers["vulnerabilities_critical_fixed"]; !ok {
		t.Error("no critical alert: vulnerabilities_critical_fixed stands")
	}
	if len(o.Alerts) != 2 {
		t.Errorf("the blocking alerts (the 1-day medium one blocks nothing): %v", o.Alerts)
	}
	items := ownerDrift(map[string]any{"no_leaked_credentials_status": "Met"}, o)
	if len(items) != 3 || !strings.HasPrefix(items[0], "no_leaked_credentials: the site says Met, but open secret scanning alert #1") {
		t.Errorf("drift: %q", items)
	}
}

// The age guard (#629): a young alert keeps the default Met, a medium one
// older than 45 days withdraws vulnerabilities_fixed_60_days, a critical one
// older than 14 days withdraws vulnerabilities_critical_fixed.
func TestOwnerAgeGuard(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	cs := func(n int, created, sev string) map[string]any {
		return map[string]any{"number": n, "html_url": fmt.Sprintf("https://github.com/swarm-routing/X/security/code-scanning/%d", n),
			"created_at": created, "rule": map[string]any{"security_severity_level": sev}}
	}
	dep := func(n int, created, sev string) map[string]any {
		return map[string]any{"number": n, "html_url": fmt.Sprintf("https://github.com/swarm-routing/X/security/dependabot/%d", n),
			"created_at": created, "security_advisory": map[string]any{"severity": sev}}
	}
	cases := []struct {
		name            string
		cs, dep         []any
		fixed, critical bool // the answer stands
	}{
		{"young alerts keep Met", []any{cs(1, "2026-11-10T00:00:00Z", "critical"), cs(2, "2026-10-10T00:00:00Z", "high")},
			[]any{dep(1, "2026-11-04T00:00:00Z", "moderate")}, true, true},
		{"a medium alert past 45 days", []any{cs(3, "2026-10-01T00:00:00Z", "medium")}, nil, false, true},
		{"a moderate Dependabot alert past 45 days", nil, []any{dep(2, "2026-09-30T00:00:00Z", "moderate")}, false, true},
		{"a low alert never", []any{cs(4, "2026-01-01T00:00:00Z", "low")}, nil, true, true},
		{"a critical alert past 14 days", []any{cs(5, "2026-11-01T00:00:00Z", "critical")}, nil, true, false},
		{"a critical alert past 45 days", nil, []any{dep(3, "2026-09-01T00:00:00Z", "critical")}, false, false},
	}
	for _, c := range cases {
		f := clean()
		if c.cs != nil {
			f.lists["code-scanning/alerts"] = c.cs
		}
		if c.dep != nil {
			f.lists["dependabot/alerts"] = c.dep
		}
		o := ownerAnswers(attestation(t), "X", evidence, nil, f)
		_, fixed := o.Answers["vulnerabilities_fixed_60_days"]
		_, critical := o.Answers["vulnerabilities_critical_fixed"]
		if fixed != c.fixed || critical != c.critical {
			t.Errorf("%s: fixed_60_days %v (want %v), critical_fixed %v (want %v): %v", c.name, fixed, c.fixed,
				critical, c.critical, o.Blocked)
		}
		if (fixed && critical) != (len(o.Alerts) == 0) {
			t.Errorf("%s: an alert is listed (its ticket is the security-alerts task's) only when it withdraws an answer: %v", c.name, o.Alerts)
		}
	}
	o := ownerAnswers(attestation(t), "X", evidence, nil, func() *fakeAlerts {
		f := clean()
		f.lists["code-scanning/alerts"] = []any{cs(5, "2026-11-01T00:00:00Z", "critical")}
		return f
	}())
	if a := o.Answers["vulnerabilities_fixed_60_days"][1]; !strings.Contains(a, "more than 45 days") ||
		!strings.Contains(a, "security-autofix.yml") {
		t.Errorf("the answer names the guard: %s", a)
	}
}

func TestOwnerUnreadableBlocks(t *testing.T) {
	f := clean()
	f.errs["dependabot/alerts"] = failure("gh api GET repos/swarm-routing/X/dependabot/alerts: Resource not accessible by integration (HTTP 403)")
	delete(f.lists, "secret-scanning/alerts") // 404: off, or no access
	o := ownerAnswers(attestation(t), "X", evidence, nil, f)
	if _, ok := o.Answers["no_leaked_credentials"]; ok || !strings.HasPrefix(o.Blocked["no_leaked_credentials"], "cannot read") {
		t.Errorf("no_leaked_credentials: an unreadable listing blocks it: %q", o.Blocked["no_leaked_credentials"])
	}
	for _, c := range []string{"vulnerabilities_fixed_60_days", "vulnerabilities_critical_fixed"} {
		if _, ok := o.Answers[c]; !ok {
			t.Errorf("%s: Met by default, an unreadable listing is only reported (#629): %q", c, o.Blocked[c])
		}
	}
	if _, ok := o.Answers["know_secure_design"]; !ok {
		t.Error("an attestation needs no alert")
	}
	if len(o.Unread) != 2 || !strings.Contains(o.Unread[0], "not accessible by integration") {
		t.Errorf("unread: %q", o.Unread)
	}
	sec := strings.Join(ownerSection([]string{"no_leaked_credentials", "report_responses"}, o), "\n")
	if !strings.Contains(sec, "- `no_leaked_credentials`: cannot read the secret scanning alerts") ||
		!strings.Contains(sec, "- `report_responses`: not attested") || !strings.Contains(sec, "Dependabot alerts") {
		t.Errorf("owner section:\n%s", sec)
	}
	if o := ownerAnswers(attestation(t), "X", evidence, nil, nil); len(o.Answers) != 4 || o.Blocked["no_leaked_credentials"] == "" {
		t.Errorf("no alert reader: the two attestations and the two default vulnerability answers: %v", o.Answers)
	}
	if o := ownerAnswers(nil, "X", evidence, nil, clean()); len(o.Answers) != 0 || len(o.Blocked) != 5 {
		t.Error("no attestation: nothing proposed")
	}
}

// alertingFake is the golden fake with an alert API.
type alertingFake struct {
	*fake
	*fakeAlerts
}

// With --issues the run is red only when it failed (#611): drift the issues
// carry is exit 0, an alert listing the bot's token cannot read is 2.
// Without --issues drift stays 1, and a read-only run's unreadable alerts
// only leave the answers `?`.
func TestCheckIssuesExit(t *testing.T) {
	setNow(t, "2026-11-17T00:00:00Z")
	g := loadGolden(t, "check.json")
	i := -1
	for j, c := range g.cases {
		if c["name"] == "issues-open" {
			i = j
		}
	}
	if i < 0 {
		t.Fatal("check.json has no issues-open case")
	}
	owner, err := os.ReadFile("testdata/owner.toml")
	if err != nil {
		t.Fatal(err)
	}
	run := func(alerts *fakeAlerts, issues bool) (int, string) {
		f := newFake(t, g.raw(t, i, "world"))
		f.files[[2]string{".github", OwnerFile}] = string(owner)
		env := func(k string) string {
			if k == "BESTPRACTICES_TOKEN" {
				return "t"
			}
			return ""
		}
		var out bytes.Buffer
		rc := Check(CheckArgs{g.str(i, "repos"), issues, false}, alertingFake{f, alerts},
			func(string) GitHub { return f }, env, &out)
		return rc, out.String()
	}
	if rc, out := run(clean(), true); rc != 0 || !strings.Contains(out, "3 drifting, 0 unreadable") {
		t.Errorf("drift reported to the issues: rc %d, want 0\n%s", rc, out)
	}
	if rc, out := run(clean(), false); rc != 1 {
		t.Errorf("drift without --issues: rc %d, want 1\n%s", rc, out)
	}
	denied := clean()
	denied.errs["code-scanning/alerts"] = failure("gh api GET code-scanning/alerts: Resource not accessible by integration (HTTP 403)")
	rc, out := run(denied, true)
	if rc != 2 || !strings.Contains(out, "FAILED: the alerts: code scanning: ") || !strings.Contains(out, "unreadable") {
		t.Errorf("an unreadable alert listing with --issues: rc %d, want 2\n%s", rc, out)
	}
	denied = clean()
	denied.errs["code-scanning/alerts"] = failure("HTTP 403")
	if rc, out := run(denied, false); rc != 1 || strings.Contains(out, "FAILED") {
		t.Errorf("read-only run, alerts unreadable: rc %d, want 1 (drift)\n%s", rc, out)
	}
}

// The testdata copy must equal the real attestation. The real file is absent
// in the image build's context, where this test has nothing to compare.
func TestOwnerTestdataMatches(t *testing.T) {
	real, err := os.ReadFile("../../" + OwnerFile)
	if os.IsNotExist(err) {
		t.Skip("no checkout around the module (image build): compared in the go job")
	}
	if err != nil {
		t.Fatal(err)
	}
	cp, err := os.ReadFile("testdata/owner.toml")
	if err != nil {
		t.Fatal(err)
	}
	if string(real) != string(cp) {
		t.Fatalf("testdata/owner.toml differs from %s: copy it again", OwnerFile)
	}
}
