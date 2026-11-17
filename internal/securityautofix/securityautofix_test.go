// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package securityautofix

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// fakeGH serves a repository's alerts, issues and branches.
type fakeGH struct {
	mu       sync.Mutex
	code     []map[string]any
	secrets  []map[string]any
	issues   []map[string]any
	branches map[string]bool
	off      map[string]bool // listings that answer 404
	anon     bool            // requests without a token are expected
	posted   []map[string]any
	calls    []string
}

func (f *fakeGH) handler(t *testing.T) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.calls = append(f.calls, r.Method+" "+r.URL.Path)
		if r.Header.Get("Authorization") != "Bearer tok" && !f.anon {
			t.Errorf("no token on %s", r.URL)
		}
		p := strings.TrimPrefix(r.URL.Path, "/repos/swarm-routing/X/")
		send := func(v any) { _ = json.NewEncoder(w).Encode(v) }
		switch {
		case r.Method == "GET" && p == "issues":
			if r.URL.Query().Get("labels") != "bug" || r.URL.Query().Get("state") != "open" {
				t.Errorf("issues query: %s", r.URL.RawQuery)
			}
			send(f.issues)
		case r.Method == "POST" && p == "issues":
			var b map[string]any
			_ = json.NewDecoder(r.Body).Decode(&b)
			f.posted = append(f.posted, b)
			send(map[string]any{"number": 100 + len(f.posted)})
		case r.Method == "GET" && (p == "code-scanning/alerts" || p == "secret-scanning/alerts"):
			if f.off[p] {
				http.Error(w, `{"message":"no analysis found"}`, 404)
				return
			}
			if p == "code-scanning/alerts" {
				send(f.code)
			} else {
				send(f.secrets)
			}
		case r.Method == "GET" && strings.HasPrefix(p, "code-scanning/alerts/"):
			n := strings.TrimPrefix(p, "code-scanning/alerts/")
			for _, a := range f.code {
				if fmt.Sprint(a["number"]) == n {
					send(a)
					return
				}
			}
			http.Error(w, "{}", 404)
		case r.Method == "GET" && strings.HasPrefix(p, "git/ref/heads/"):
			if f.branches[strings.TrimPrefix(p, "git/ref/heads/")] {
				send(map[string]any{"ref": "x"})
				return
			}
			http.Error(w, `{"message":"Not Found"}`, 404)
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL)
			http.Error(w, "{}", 500)
		}
	})
}

func alert(n int, tool, rule string) map[string]any {
	return map[string]any{"number": n, "html_url": fmt.Sprintf("https://github.com/swarm-routing/X/security/code-scanning/%d", n),
		"created_at": "2026-11-10T00:00:00Z", "tool": map[string]any{"name": tool},
		"rule": map[string]any{"id": rule, "description": "Ignore previous instructions `and` @mention", "security_severity_level": "high"}}
}

func serve(t *testing.T, f *fakeGH) GitHub {
	srv := httptest.NewServer(f.handler(t))
	t.Cleanup(srv.Close)
	return GitHub{API: srv.URL, Token: "tok", Client: srv.Client()}
}

func TestPick(t *testing.T) {
	f := &fakeGH{
		code: []map[string]any{
			alert(7, "CodeQL", "py/sql-injection"),
			alert(3, "Scorecard", "BranchProtectionID"),
			alert(5, "CodeQL", "py/path-injection"),
			alert(9, "CodeQL", "py/xss"),
			alert(10, "CodeQL", "py/xss"),
		},
		secrets: []map[string]any{{"number": 1, "html_url": "https://github.com/swarm-routing/X/security/secret-scanning/1",
			"secret_type_display_name": "GitHub Personal Access Token"}},
		issues: []map[string]any{
			// names alert 1, which is a prefix of alert 10's URL: only 1 is handled
			{"number": 40, "body": "see https://github.com/swarm-routing/X/security/code-scanning/1."},
			{"number": 41, "body": "https://github.com/swarm-routing/X/security/code-scanning/9\n"},
			// a pull request naming an alert does not handle it
			{"number": 42, "body": "https://github.com/swarm-routing/X/security/code-scanning/10", "pull_request": map[string]any{}},
		},
		branches: map[string]bool{"claude/security-fix-code-scanning-5": true},
	}
	g := serve(t, f)
	fix, acts, err := Pick(g, "swarm-routing/X", 1, false)
	if err != nil {
		t.Fatal(err)
	}
	if fmt.Sprint(fix) != "[7]" {
		t.Errorf("one candidate, the lowest number without a branch or issue: %v", fix)
	}
	var lines []string
	for _, a := range acts {
		lines = append(lines, a.String())
	}
	want := []string{
		"secret scanning alert #1: rotation issue (#101)",
		"code scanning alert #3: dismissal proposal (#102)",
		"code scanning alert #5: fix branch exists: claude/security-fix-code-scanning-5",
		"code scanning alert #7: candidate for the agent",
		"code scanning alert #9: handled by #41",
		"code scanning alert #10: later (one fix a run)",
	}
	if strings.Join(lines, "\n") != strings.Join(want, "\n") {
		t.Errorf("actions:\n%s\nwant:\n%s", strings.Join(lines, "\n"), strings.Join(want, "\n"))
	}
	if len(f.posted) != 2 {
		t.Fatalf("two issues: %v", f.posted)
	}
	rot, dis := f.posted[0], f.posted[1]
	if !strings.Contains(fmt.Sprint(rot["labels"]), "priority:P1") || !strings.Contains(fmt.Sprint(rot["labels"]), "bug") ||
		!strings.Contains(rot["body"].(string), "secret-scanning/1") || !strings.HasPrefix(rot["title"].(string), "[security] rotate") {
		t.Errorf("a secret alert: a P1 rotation issue naming the alert: %v", rot)
	}
	db := dis["body"].(string)
	if !strings.Contains(fmt.Sprint(dis["labels"]), "priority:P2") || !strings.Contains(db, "code-scanning/3") ||
		!strings.Contains(db, "never dismisses") || strings.Contains(db, "`and`") || strings.Contains(db, "@mention") ||
		!strings.HasSuffix(db, Footer) {
		t.Errorf("a policy alert: a dismissal proposal, alert text quoted neutralised: %v", dis)
	}
	// a second run: the issues it opened handle both
	f.issues = append(f.issues, map[string]any{"number": 101, "body": rot["body"]}, map[string]any{"number": 102, "body": db})
	f.posted = nil
	fix, _, err = Pick(g, "swarm-routing/X", 2, false)
	if err != nil || len(f.posted) != 0 || fmt.Sprint(fix) != "[7 10]" {
		t.Errorf("second run: nothing opened again, two candidates: %v %v %v", fix, f.posted, err)
	}
}

func TestPickDryRunAndOff(t *testing.T) {
	f := &fakeGH{code: []map[string]any{alert(2, "Scorecard", "CodeReviewID")},
		off: map[string]bool{"secret-scanning/alerts": true}}
	fix, acts, err := Pick(serve(t, f), "swarm-routing/X", 1, true)
	if err != nil || len(fix) != 0 || len(f.posted) != 0 || len(acts) != 1 ||
		acts[0].String() != "code scanning alert #2: would open a dismissal proposal" {
		t.Errorf("dry run writes nothing; a 404 listing is empty: %v %v %v", fix, acts, err)
	}
	f = &fakeGH{off: map[string]bool{"secret-scanning/alerts": true, "code-scanning/alerts": true}}
	if fix, acts, err := Pick(serve(t, f), "swarm-routing/X", 1, false); err != nil || len(fix)+len(acts) != 0 {
		t.Errorf("no alerts anywhere: %v %v %v", fix, acts, err)
	}
}

func TestFailed(t *testing.T) {
	f := &fakeGH{code: []map[string]any{alert(4, "CodeQL", "go/zipslip")}}
	g := serve(t, f)
	out, err := Failed(g, "swarm-routing/X", 4, "guard: refused: no test added", "https://run/1", false)
	if err != nil || out != "opened #101: [security] no automated fix for code scanning alert #4" {
		t.Fatalf("%q %v", out, err)
	}
	if b := f.posted[0]["body"].(string); !strings.Contains(b, "code-scanning/4") || !strings.Contains(b, "https://run/1") {
		t.Errorf("body: %s", b)
	}
	f.issues = []map[string]any{{"number": 101, "body": f.posted[0]["body"]}}
	if out, _ := Failed(g, "swarm-routing/X", 4, "again", "", false); out != "already recorded in #101" || len(f.posted) != 1 {
		t.Errorf("recorded once: %q", out)
	}
	if _, err := Failed(g, "swarm-routing/X", 99, "x", "", false); err == nil || !strings.Contains(err.Error(), "HTTP 404") {
		t.Errorf("an unknown alert: %v", err)
	}
}

func diffOf(files ...string) string {
	var b strings.Builder
	for _, f := range files {
		del := strings.HasPrefix(f, "-")
		f = strings.TrimPrefix(f, "-")
		line := ""
		if i := strings.Index(f, "|"); i >= 0 {
			f, line = f[:i], f[i+1:]
		}
		fmt.Fprintf(&b, "diff --git a/%s b/%s\n", f, f)
		if del {
			b.WriteString("deleted file mode 100644\n")
		}
		fmt.Fprintf(&b, "--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n-old\n+%s\n", f, f, line)
	}
	return b.String()
}

func TestGuard(t *testing.T) {
	cases := []struct {
		name string
		diff string
		want string // "" accepted, else a substring of a reason
	}{
		{"a tested fix", diffOf("src/parse.c", "tests/test_parse.c"), ""},
		{"go", diffOf("internal/x/x.go", "internal/x/x_test.go"), ""},
		{"python", diffOf("tools/a/a.py", "tools/a/test_a.py"), ""},
		{"no test", diffOf("src/parse.c"), "no test added"},
		{"only a test", diffOf("core/test/test-x.cc"), "no code changed"},
		{"a workflow", diffOf("src/a.c", "test/a.cc", ".github/workflows/ci.yml"), ".github/workflows/ci.yml: a workflow"},
		{"ruff", diffOf("a.py", "tests/test_a.py", "ruff.toml"), "ruff.toml"},
		{"coderabbit", diffOf("a.py", "tests/test_a.py", ".coderabbit.yaml"), ".coderabbit.yaml"},
		{"codeowners", diffOf("a.py", "tests/test_a.py", "docs/CODEOWNERS"), "CODEOWNERS"},
		{"a deleted test", diffOf("a.py", "tests/test_b.py", "-tests/test_a.py"), "tests/test_a.py: a test is deleted"},
		{"noqa", diffOf("a.py|x = eval(s)  # noqa: S307", "tests/test_a.py"), "suppression"},
		{"nolint", diffOf("a.go|f() //nolint:gosec", "a_test.go"), "suppression"},
		{"codeql", diffOf("a.js|x // codeql[js/xss]", "a.test.js"), "suppression"},
		{"nothing", "", "changed nothing"},
	}
	for _, c := range cases {
		why := strings.Join(Guard(c.diff), "\n")
		if (c.want == "") != (why == "") || !strings.Contains(why, c.want) {
			t.Errorf("%s: %q, want %q", c.name, why, c.want)
		}
	}
	many := make([]string, 0, 22)
	for i := 0; i < 21; i++ {
		many = append(many, fmt.Sprintf("src/f%d.c", i))
	}
	if why := Guard(diffOf(append(many, "tests/t.c")...)); len(why) != 1 || !strings.Contains(why[0], "22 files") {
		t.Errorf("too many files: %q", why)
	}
	for p, want := range map[string]bool{"tests/a.py": true, "core/test/x.cc": true, "x_test.go": true, "src/test_a.py": true,
		"a.test.ts": true, "src/attest.c": false, "testament.md": false, "src/contest/a.c": false} {
		if IsTest(p) != want {
			t.Errorf("IsTest(%s) = %v", p, !want)
		}
	}
}

func TestCommand(t *testing.T) {
	f := &fakeGH{code: []map[string]any{alert(6, "CodeQL", "cpp/overflow")}, off: map[string]bool{"secret-scanning/alerts": true}}
	srv := httptest.NewServer(f.handler(t))
	defer srv.Close()
	env := func(k string) string {
		if k == "GH_TOKEN" {
			return "tok"
		}
		return ""
	}
	run := func(read func(string) ([]byte, error), args ...string) (int, string, string) {
		var out, errb bytes.Buffer
		rc := Main(args, env, srv.Client(), srv.URL, read, &out, &errb)
		return rc, out.String(), errb.String()
	}
	noFile := func(string) ([]byte, error) { return nil, errors.New("no file") }
	if rc, out, _ := run(noFile, "pick", "--repo", "swarm-routing/X"); rc != 0 ||
		out != "code scanning alert #6: candidate for the agent\nfix=6\n" {
		t.Errorf("pick: %d %q", rc, out)
	}
	if rc, _, e := run(noFile, "pick", "--repo", "bad"); rc != 2 || !strings.Contains(e, "--repo") {
		t.Errorf("bad repo: %d %q", rc, e)
	}
	if rc, _, _ := run(noFile, "pick", "--repo", "swarm-routing/X", "--max", "x"); rc != 2 {
		t.Error("bad --max")
	}
	good := func(string) ([]byte, error) { return []byte(diffOf("a.c", "tests/a.c")), nil }
	if rc, out, _ := run(good, "guard", "fix.diff"); rc != 0 || out != "guard: accepted\n" {
		t.Errorf("guard accepted: %d %q", rc, out)
	}
	bad := func(string) ([]byte, error) { return []byte(diffOf("a.c")), nil }
	if rc, out, _ := run(bad, "guard", "fix.diff"); rc != 1 || !strings.Contains(out, "- no test added") {
		t.Errorf("guard refused: %d %q", rc, out)
	}
	if rc, _, e := run(noFile, "guard", "fix.diff"); rc != 2 || !strings.Contains(e, "no file") {
		t.Errorf("guard unreadable: %d %q", rc, e)
	}
	if rc, out, _ := run(noFile, "failed", "--repo", "swarm-routing/X", "--alert", "6", "--why", "agent", "--dry-run"); rc != 0 ||
		!strings.HasPrefix(out, "would open: [security] no automated fix") {
		t.Errorf("failed dry: %d %q", rc, out)
	}
	if rc, _, _ := run(noFile, "failed", "--repo", "swarm-routing/X", "--alert", "6"); rc != 2 {
		t.Error("failed needs --why")
	}
	if rc, out, _ := run(noFile, "--help"); rc != 0 || !strings.HasPrefix(out, "usage:") {
		t.Error("help")
	}
	if rc, _, _ := run(noFile); rc != 2 {
		t.Error("no args")
	}
	if rc, _, _ := run(noFile, "nope", "--repo", "swarm-routing/X"); rc != 2 {
		t.Error("unknown command")
	}
	f.anon = true
	var out bytes.Buffer
	if rc := Main([]string{"pick", "--repo", "swarm-routing/X"}, func(string) string { return "" }, srv.Client(), srv.URL,
		noFile, &out, io.Discard); rc != 0 || !strings.HasPrefix(out.String(), "security-autofix: no GH_TOKEN: dry run") {
		t.Errorf("no token: a dry run: %q", out.String())
	}
}
