// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The vulnerability answers against a fake GitHub alerts API (#680), read
// through the real HTTP client: no alert, a young one, one older than 60
// days, and a listing the token cannot read (HTTP 403).

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/swarm-routing/.github/internal/securityalerts"
)

func alertsServer(t *testing.T, lists map[string]string, denied map[string]bool) *HTTP {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/repos/"+Org+"/X/")
		if r.Method != "GET" || r.URL.Query().Get("state") != "open" {
			t.Errorf("only open alerts are read: %s %s", r.Method, r.URL)
		}
		if denied[path] {
			w.WriteHeader(http.StatusForbidden)
			fmt.Fprint(w, `{"message":"Resource not accessible by integration"}`)
			return
		}
		body, ok := lists[path]
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			fmt.Fprint(w, `{"message":"Not Found"}`)
			return
		}
		fmt.Fprint(w, body)
	}))
	t.Cleanup(srv.Close)
	h := NewHTTP("t", srv.URL)
	h.Client = srv.Client()
	return h
}

func TestVulnerabilityAnswersFromAlertsAPI(t *testing.T) {
	setNow(t, "2026-11-22T00:00:00Z")
	cs := func(n int, created, sev string) string {
		return fmt.Sprintf(`{"number":%d,"html_url":"https://github.com/swarm-routing/X/security/code-scanning/%d",`+
			`"created_at":%q,"tool":{"name":"CodeQL"},"rule":{"id":"r","severity":"error","security_severity_level":%q}}`, n, n, created, sev)
	}
	quality := `{"number":9,"html_url":"https://github.com/swarm-routing/X/security/code-scanning/9",` +
		`"created_at":"2026-01-01T00:00:00Z","tool":{"name":"CodeQL"},"rule":{"id":"q","severity":"warning"}}`
	lists := func(code string) map[string]string {
		return map[string]string{"code-scanning/alerts": "[" + code + "]", "dependabot/alerts": "[]", "secret-scanning/alerts": "[]"}
	}
	cases := []struct {
		name   string
		lists  map[string]string
		denied map[string]bool
		met    bool   // vulnerabilities_fixed_60_days is proposed Met
		want   string // in its justification, or in why it is withdrawn
		drift  bool   // a site that says Met drifts
	}{
		{"no alert", lists(""), nil, true,
			"Open now: no medium-or-higher code-scanning or Dependabot alert.", false},
		{"a quality rule is no vulnerability", lists(quality), nil, true,
			"Open now: no medium-or-higher code-scanning or Dependabot alert.", false},
		{"a young alert", lists(cs(4, "2026-11-12T00:00:00Z", "high")), nil, true,
			"Open now: 1 medium-or-higher alert, code scanning alert #4 (high), open since 2026-11-12: https://github.com/swarm-routing/X/security/code-scanning/4.", false},
		{"an alert older than 60 days", lists(cs(10, "2026-08-05T00:00:00Z", "high") + "," + cs(4, "2026-11-12T00:00:00Z", "medium")), nil, false,
			"open code scanning alert #10 (high), open since 2026-08-05: https://github.com/swarm-routing/X/security/code-scanning/10", true},
		{"HTTP 403 on code scanning", lists(""), map[string]bool{"code-scanning/alerts": true}, true,
			"Open now: no medium-or-higher code-scanning or Dependabot alert (the code scanning alerts could not be read).", false},
	}
	for _, c := range cases {
		h := alertsServer(t, c.lists, c.denied)
		o := ownerAnswers(attestation(t), "X", evidence, nil, h)
		a, met := o.Answers["vulnerabilities_fixed_60_days"]
		if met != c.met {
			t.Errorf("%s: Met %v, want %v (blocked: %q)", c.name, met, c.met, o.Blocked["vulnerabilities_fixed_60_days"])
			continue
		}
		got := a[1]
		if !met {
			got = o.Blocked["vulnerabilities_fixed_60_days"]
		}
		if met && !strings.Contains(got, "Critical open: 0, high open: ") {
			t.Errorf("%s: the critical and high counts: %q", c.name, got)
		}
		if !strings.Contains(got, c.want) {
			t.Errorf("%s: %q\nnot in %q", c.name, c.want, got)
		}
		drift := ownerDrift(map[string]any{"vulnerabilities_fixed_60_days_status": "Met"}, o)
		if (len(drift) > 0) != c.drift || c.drift && !strings.HasPrefix(drift[0], "vulnerabilities_fixed_60_days: the site says Met, but open code scanning alert #10") {
			t.Errorf("%s: drift %q, want %v", c.name, drift, c.drift)
		}
		if c.denied != nil && (len(o.Unread) != 1 || !strings.Contains(o.Unread[0], "HTTP 403")) {
			t.Errorf("%s: the 403 is reported as unread: %q", c.name, o.Unread)
		}
	}
}

// A Scorecard finding is policy, not a vulnerability (#629, 2026-11-22):
// it neither counts as critical or high nor withdraws an answer.
func TestScorecardIsNoVulnerability(t *testing.T) {
	a := alert{securityalerts.Alert{Kind: "code scanning", Tool: "Scorecard", Severity: "critical", Security: true}}
	if a.rank() != 0 {
		t.Errorf("a Scorecard alert ranks %d", a.rank())
	}
	if b := (alert{securityalerts.Alert{Kind: "code scanning", Tool: "CodeQL", Severity: "critical", Security: true}}); b.rank() != 4 {
		t.Errorf("a CodeQL critical ranks %d", b.rank())
	}
}
