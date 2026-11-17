// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The attested owner-only answers against a fake alert API: proposed only
// when every listing reads and no open alert stands against them.

import (
	"bytes"
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
		if a[0] != "Met" || !strings.Contains(a[1], att.URL) {
			t.Errorf("%s cites the attestation: %s", c, a[1])
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
	gh := &fakeIssues{}
	bugs, err := alertBugs(gh, "X", o, false)
	if err != nil || len(bugs) != 2 || len(gh.posted) != 2 || !strings.Contains(gh.posted[0], "code-scanning/3") {
		t.Errorf("a bug per blocking alert: %v %v %v", bugs, gh.posted, err)
	}
	gh.open = []any{map[string]any{"number": 9, "body": "see https://github.com/swarm-routing/X/security/code-scanning/3"}}
	gh.posted = nil
	bugs, _ = alertBugs(gh, "X", o, false)
	if len(gh.posted) != 1 || !strings.HasPrefix(bugs[0], "#9 (open)") {
		t.Errorf("an alert with an open issue gets no second bug: %v", bugs)
	}
}

func TestOwnerUnreadableBlocks(t *testing.T) {
	f := clean()
	f.errs["dependabot/alerts"] = failure("gh api GET repos/swarm-routing/X/dependabot/alerts: Resource not accessible by integration (HTTP 403)")
	delete(f.lists, "secret-scanning/alerts") // 404: off, or no access
	o := ownerAnswers(attestation(t), "X", evidence, nil, f)
	for _, c := range []string{"vulnerabilities_fixed_60_days", "vulnerabilities_critical_fixed", "no_leaked_credentials"} {
		if _, ok := o.Answers[c]; ok || !strings.HasPrefix(o.Blocked[c], "cannot read") {
			t.Errorf("%s: an unreadable listing blocks it: %q", c, o.Blocked[c])
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
	if o := ownerAnswers(attestation(t), "X", evidence, nil, nil); len(o.Answers) != 2 {
		t.Errorf("no alert reader: only the two attestations: %v", o.Answers)
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

type fakeIssues struct {
	open   []any
	posted []string
}

func (f *fakeIssues) API(method, path string, body map[string]any, paginate bool) (any, error) {
	if method == "GET" {
		return f.open, nil
	}
	f.posted = append(f.posted, pyStr(body["body"]))
	return map[string]any{"number": 100 + len(f.posted)}, nil
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
