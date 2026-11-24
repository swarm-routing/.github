// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package vcpkgwatch

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/swarm-routing/.github/internal/github"
)

var now = time.Date(2026, 11, 24, 21, 0, 0, 0, time.UTC)

func ago(d time.Duration) time.Time { return now.Add(-d) }

func fixture(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

type fRel struct {
	tag       string
	published time.Time
	draft     bool
}

type fRepo struct {
	name      string
	private   bool
	releases  []fRel
	workflows map[string]string // file name -> text, at every tag
}

type fPull struct {
	number      int
	title, head string
}

type fIssue struct {
	number      int
	title, body string
	state       string
	labels      []string
	comments    []string
	pr          bool
}

// fakeGitHub serves the org's repositories, releases and workflows, the
// registry's baseline and open PRs, and this repository's issues.
type fakeGitHub struct {
	mu       sync.Mutex
	repos    []fRepo
	baseline map[string]string
	pulls    []fPull
	issues   []*fIssue
	calls    []string
}

func page(w http.ResponseWriter, r *http.Request, items []map[string]any) {
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	pg, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", 400)
		return
	}
	lo := min((pg-1)*per, len(items))
	hi := min(lo+per, len(items))
	out := items[lo:hi]
	if out == nil {
		out = []map[string]any{}
	}
	_ = json.NewEncoder(w).Encode(out)
}

func content(w http.ResponseWriter, text string) {
	enc := base64.StdEncoding.EncodeToString([]byte(text))
	var wrapped strings.Builder // GitHub wraps the base64 at 60 columns
	for len(enc) > 60 {
		wrapped.WriteString(enc[:60] + "\n")
		enc = enc[60:]
	}
	wrapped.WriteString(enc)
	_ = json.NewEncoder(w).Encode(map[string]any{"content": wrapped.String(), "encoding": "base64"})
}

func (f *fakeGitHub) repo(name string) *fRepo {
	for i := range f.repos {
		if f.repos[i].name == name {
			return &f.repos[i]
		}
	}
	return nil
}

func (f *fakeGitHub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, r.Method+" "+r.URL.Path)
	p := r.URL.Path
	var body map[string]any
	if r.Body != nil {
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &body)
	}
	switch {
	case p == "/orgs/swarm-routing/repos":
		var out []map[string]any
		for _, x := range f.repos {
			if !x.private {
				out = append(out, map[string]any{"name": x.name, "full_name": Org + "/" + x.name})
			}
		}
		page(w, r, out)
	case p == "/repos/"+Registry+"/contents/versions/baseline.json":
		m := map[string]any{}
		for k, v := range f.baseline {
			m[k] = map[string]any{"baseline": v, "port-version": 0}
		}
		b, _ := json.Marshal(map[string]any{"default": m})
		content(w, string(b))
	case p == "/repos/"+Registry+"/pulls":
		if r.URL.Query().Get("state") != "open" {
			http.Error(w, "state", 400)
			return
		}
		var out []map[string]any
		for _, x := range f.pulls {
			out = append(out, map[string]any{"number": x.number, "title": x.title, "head": map[string]any{"ref": x.head}})
		}
		page(w, r, out)
	case p == "/repos/"+IssueRepo+"/issues" && r.Method == "GET":
		if r.URL.Query().Get("state") != "open" {
			http.Error(w, "state", 400)
			return
		}
		var out []map[string]any
		for _, i := range f.issues {
			if i.state != "open" {
				continue
			}
			m := map[string]any{"number": i.number, "title": i.title, "body": i.body}
			if i.pr {
				m["pull_request"] = map[string]any{"url": "x"}
			}
			out = append(out, m)
		}
		page(w, r, out)
	case p == "/repos/"+IssueRepo+"/issues" && r.Method == "POST":
		n := 900 + len(f.issues)
		var labels []string
		for _, l := range body["labels"].([]any) {
			labels = append(labels, l.(string))
		}
		f.issues = append(f.issues, &fIssue{number: n, title: body["title"].(string), body: body["body"].(string), state: "open", labels: labels})
		_ = json.NewEncoder(w).Encode(map[string]any{"number": n})
	case strings.HasPrefix(p, "/repos/"+IssueRepo+"/issues/"):
		rest := strings.TrimPrefix(p, "/repos/"+IssueRepo+"/issues/")
		num, _ := strconv.Atoi(strings.TrimSuffix(rest, "/comments"))
		var hit *fIssue
		for _, i := range f.issues {
			if i.number == num {
				hit = i
			}
		}
		if hit == nil {
			http.NotFound(w, r)
			return
		}
		switch {
		case strings.HasSuffix(rest, "/comments") && r.Method == "POST":
			hit.comments = append(hit.comments, body["body"].(string))
		case r.Method == "PATCH":
			if s, ok := body["state"].(string); ok {
				hit.state = s
			}
			if b, ok := body["body"].(string); ok {
				hit.body = b
			}
		default:
			http.Error(w, "method", 405)
			return
		}
		_, _ = w.Write([]byte("{}"))
	case strings.HasPrefix(p, "/repos/swarm-routing/"):
		parts := strings.SplitN(strings.TrimPrefix(p, "/repos/swarm-routing/"), "/", 2)
		x := f.repo(parts[0])
		if x == nil {
			http.NotFound(w, r)
			return
		}
		switch {
		case len(parts) == 1:
			_ = json.NewEncoder(w).Encode(map[string]any{"name": x.name, "full_name": Org + "/" + x.name, "private": x.private})
		case parts[1] == "releases":
			var out []map[string]any
			for _, rel := range x.releases {
				out = append(out, map[string]any{"tag_name": rel.tag, "draft": rel.draft, "published_at": rel.published.Format(time.RFC3339)})
			}
			_ = json.NewEncoder(w).Encode(out)
		case parts[1] == "contents/.github/workflows":
			if r.URL.Query().Get("ref") == "" {
				http.Error(w, "ref", 400)
				return
			}
			if x.workflows == nil {
				http.NotFound(w, r)
				return
			}
			var out []map[string]any
			for n := range x.workflows {
				out = append(out, map[string]any{"name": n, "path": ".github/workflows/" + n, "type": "file"})
			}
			_ = json.NewEncoder(w).Encode(out)
		case strings.HasPrefix(parts[1], "contents/.github/workflows/"):
			text, ok := x.workflows[strings.TrimPrefix(parts[1], "contents/.github/workflows/")]
			if !ok || r.URL.Query().Get("ref") == "" {
				http.NotFound(w, r)
				return
			}
			content(w, text)
		default:
			http.NotFound(w, r)
		}
	default:
		http.NotFound(w, r)
	}
}

func (f *fakeGitHub) writes() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, c := range f.calls {
		if !strings.HasPrefix(c, "GET ") {
			out = append(out, c)
		}
	}
	return out
}

func run(t *testing.T, f *fakeGitHub, dry bool, names ...string) (string, error) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	f.calls = nil
	var out bytes.Buffer
	err := Run(github.Client{API: srv.URL, Token: "t", HTTP: srv.Client()}, names, now, dry, &out)
	return out.String(), err
}

func TestPorts(t *testing.T) {
	cases := []struct {
		name, text string
		want       []string
	}{
		{"swarm-core v2.0.0's caller", fixture(t, "swarm-core-v2.0.0-release.yml"), []string{"swarm-core"}},
		{"an own release.yml (AntHocNet's shape)", fixture(t, "own-release.yml"), []string{"anthocnet-core"}},
		{"a quoted list", "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@abc\n    with:\n      vcpkg-ports: \"ara-core swarm-core\"\n", []string{"ara-core", "swarm-core"}},
		{"a folded block", "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@abc\n    with:\n      vcpkg-ports: >-\n        b-core\n        a-core   # two\n      zenodo: true\n", []string{"a-core", "b-core"}},
		{"a comment is not the input", "    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@abc\n    with:\n      # vcpkg-ports: swarm-core\n      zenodo: true\n", []string{}},
		{"no reusable call: the key alone is not enough", "      vcpkg-ports: swarm-core\n", []string{}},
		{"a PORT: in a job that never touches the registry", "    env:\n      PORT: 8080x\n", []string{}},
	}
	for _, c := range cases {
		if got := Ports(c.text); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: got %q, want %q", c.name, got, c.want)
		}
	}
}

// swarmCore is the swarm-core v2.0.0 case (#880): published, its `vcpkg` job
// failed ("port_bump: cannot download …ns3-swarm-core/…/swarm-core-2.0.0.tar.gz:
// HTTP Error 404"), so no `bot/vcpkg-swarm-core` PR was opened and the
// registry's baseline still holds the old version.
func swarmCore(t *testing.T) *fakeGitHub {
	return &fakeGitHub{
		repos: []fRepo{
			{name: "swarm-core", releases: []fRel{{tag: "v2.0.0", published: ago(5 * time.Hour)}, {tag: "v1.4.0", published: ago(300 * time.Hour)}},
				workflows: map[string]string{"release.yml": fixture(t, "swarm-core-v2.0.0-release.yml"), "core.yml": "name: core\n"}},
			{name: "AntHocNet", releases: []fRel{{tag: "v2.8.0", published: ago(30 * time.Hour)}},
				workflows: map[string]string{"release.yml": fixture(t, "own-release.yml")}},
			{name: "sim-tools", releases: []fRel{{tag: "v0.9.0", published: ago(3 * time.Hour)}},
				workflows: map[string]string{"release.yml": "uses: swarm-routing/.github/.github/workflows/reusable-release.yml@abc\n"}},
			{name: "old", releases: []fRel{{tag: "v1.0.0", published: ago(20 * 24 * time.Hour)}}},
			{name: "secret", private: true},
		},
		baseline: map[string]string{"swarm-core": "1.4.0", "anthocnet-core": "2.8.0"},
		pulls:    []fPull{{number: 12, title: "chore: unrelated", head: "claude/x"}},
		issues:   []*fIssue{{number: 5, title: "[backstop] scheduled runs stalled", state: "open"}},
	}
}

func ticket(f *fakeGitHub, title string) *fIssue {
	for _, i := range f.issues {
		if i.title == title {
			return i
		}
	}
	return nil
}

func TestSwarmCoreV200(t *testing.T) {
	f := swarmCore(t)
	out, err := run(t, f, false)
	if err != nil {
		t.Fatalf("run: %v\n%s", err, out)
	}
	title := "[vcpkg] swarm-core v2.0.0: port not bumped"
	i := ticket(f, title)
	if i == nil || i.state != "open" {
		t.Fatalf("no open %q issue:\n%s", title, out)
	}
	if !reflect.DeepEqual(i.labels, Labels) {
		t.Errorf("labels %q, want %q", i.labels, Labels)
	}
	for _, want := range []string{"| `swarm-core` | 1.4.0 | 2.0.0 | `release.yml` job `vcpkg`", "bot/vcpkg-swarm-core", "tools/port_bump.py", "swarm-routing/vcpkg-registry#70"} {
		if !strings.Contains(i.body, want) {
			t.Errorf("body lacks %q:\n%s", want, i.body)
		}
	}
	for _, want := range []string{
		"swarm-core v2.0.0 (published 2026-11-24T16:00:00Z): swarm-core NOT BUMPED (baseline 1.4.0, no registry PR); opened #901\n",
		"AntHocNet v2.8.0 (published 2026-11-23T15:00:00Z): anthocnet-core 2.8.0 is the baseline\n",
		"vcpkg-watch: 3 recent releases, 2 with a port checked, 1 not bumped\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "sim-tools") || strings.Contains(out, "old ") {
		t.Errorf("a release without a port, or outside the window, was reported:\n%s", out)
	}

	// the next hour, nothing changed: the ticket is left as it is
	out, err = run(t, f, false)
	if err != nil || len(f.writes()) != 0 || !strings.Contains(out, "#901 open, unchanged") {
		t.Fatalf("second run wrote %q (err %v):\n%s", f.writes(), err, out)
	}

	// a bot PR for an older version does not count; the hand PR naming the version does
	f.pulls = append(f.pulls, fPull{number: 60, title: "feat(ports): swarm-core 1.4.0", head: "bot/vcpkg-swarm-core"})
	if out, _ = run(t, f, false); !strings.Contains(out, "NOT BUMPED") {
		t.Fatalf("an old version's bot PR counted:\n%s", out)
	}
	f.pulls = append(f.pulls, fPull{number: 70, title: "fix(ports): swarm-core 2.0.0 from swarm-routing/swarm-core", head: "claude/swarm-core-2"})
	out, err = run(t, f, false)
	if err != nil || i.state != "closed" || !strings.Contains(out, "swarm-core in swarm-routing/vcpkg-registry#70; closed #901") {
		t.Fatalf("the open registry PR did not close the ticket (err %v, state %s):\n%s", err, i.state, out)
	}
	if len(i.comments) != 1 || !strings.Contains(i.comments[0], "swarm-routing/vcpkg-registry#70") {
		t.Errorf("closing comment %q", i.comments)
	}
}

func TestAntHocNetOwnReleaseYml(t *testing.T) {
	f := swarmCore(t)
	f.baseline["anthocnet-core"] = "2.7.0"
	out, err := run(t, f, false, "AntHocNet")
	if err != nil {
		t.Fatalf("run: %v\n%s", err, out)
	}
	i := ticket(f, "[vcpkg] AntHocNet v2.8.0: port not bumped")
	if i == nil || !strings.Contains(i.body, "| `anthocnet-core` | 2.7.0 | 2.8.0 | `release.yml` job `vcpkg`") {
		t.Fatalf("no ticket for the own release.yml's port:\n%s", out)
	}
	// its bot PR, titled as the job titles it, clears it
	f.pulls = append(f.pulls, fPull{number: 71, title: "feat(ports): anthocnet-core 2.8.0", head: "bot/vcpkg-AntHocNet"})
	if out, _ = run(t, f, false, "AntHocNet"); i.state != "closed" {
		t.Fatalf("the bot PR did not close the ticket:\n%s", out)
	}
	// so does the baseline, for a newer release; the older release's ticket is closed
	i.state = "open"
	f.pulls = nil
	f.repos[1].releases = append(f.repos[1].releases, fRel{tag: "v2.9.0", published: ago(4 * time.Hour)})
	f.baseline["anthocnet-core"] = "2.9.0"
	out, _ = run(t, f, false, "AntHocNet")
	if i.state != "closed" || !strings.Contains(i.comments[len(i.comments)-1], "v2.9.0 is the newest release") {
		t.Fatalf("the older release's ticket stayed open:\n%s", out)
	}
}

func TestPrivateNeverNamed(t *testing.T) {
	f := swarmCore(t)
	out, err := run(t, f, false, "secret")
	if err != nil || strings.Contains(out, "secret") || !strings.Contains(out, "private, skipped") {
		t.Fatalf("a private repository (err %v):\n%s", err, out)
	}
}

func TestGraceDryRunAndErrors(t *testing.T) {
	f := swarmCore(t)
	f.repos[0].releases[0].published = ago(30 * time.Minute) // the vcpkg job may still be running
	out, err := run(t, f, false, "swarm-core")
	if err != nil || len(f.writes()) != 0 || !strings.Contains(out, "published 30m0s ago, under 2h0m0s: not yet") {
		t.Fatalf("a release under the grace period was acted on (err %v, writes %q):\n%s", err, f.writes(), out)
	}
	f.repos[0].releases[0].published = ago(5 * time.Hour)
	out, err = run(t, f, true)
	if err != nil || len(f.writes()) != 0 || !strings.Contains(out, `dry run: would open swarm-routing/.github issue "[vcpkg] swarm-core v2.0.0: port not bumped"`) {
		t.Fatalf("dry run (err %v, writes %q):\n%s", err, f.writes(), out)
	}
	// an unreadable baseline is an error, and nothing is written
	f.baseline = nil
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/baseline.json") {
			http.Error(w, "boom", 500)
			return
		}
		f.ServeHTTP(w, r)
	}))
	defer srv.Close()
	var buf bytes.Buffer
	err = Run(github.Client{API: srv.URL, Token: "t", HTTP: srv.Client()}, nil, now, false, &buf)
	if err == nil || !strings.Contains(err.Error(), "swarm-routing/vcpkg-registry") || len(f.writes()) != 0 {
		t.Fatalf("an unreadable baseline: err %v, writes %q", err, f.writes())
	}
}

func TestMain_(t *testing.T) {
	var out, errb bytes.Buffer
	if rc := Main([]string{"--nope"}, func(string) string { return "" }, nil, "", &out, &errb); rc != 2 {
		t.Errorf("unknown flag: rc %d", rc)
	}
	f := swarmCore(t)
	srv := httptest.NewServer(f)
	defer srv.Close()
	out.Reset()
	rc := Main([]string{"--now", now.Format(time.RFC3339), "--repos", "swarm-core"}, func(string) string { return "" }, srv.Client(), srv.URL, &out, &errb)
	if rc != 0 || !strings.HasPrefix(out.String(), "vcpkg-watch: no GH_TOKEN: dry run\n") || len(f.writes()) != 0 {
		t.Fatalf("no token must be a dry run: rc %d, writes %q:\n%s%s", rc, f.writes(), out.String(), errb.String())
	}
}
