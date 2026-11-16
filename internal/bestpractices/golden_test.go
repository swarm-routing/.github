// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// testdata/golden/*.json hold, per case, the inputs and what the tool printed,
// exited with and wrote, and every call it made to the fake site and GitHub.
// They were first written by the Python tool (tools/bestpractices/
// bestpractices.py at f34e046, the byte-identical proof of #531, PR #545);
// a deliberate change of output rewrites them with
//
//	go test ./internal/bestpractices/ -run Golden -update
//
// and the PR shows the diff.

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func loadJSON(t *testing.T, path string, v any) {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, v); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
}

type fixtureRepo struct {
	Git   bool              `json:"git"`
	Files map[string]string `json:"files"`
}

// makeRepo writes fixture repository name under dir, as the Python tool's self-test's
// make() does (a git repository with a fixed date where the fixture says so).
func makeRepo(t *testing.T, dir, name string) string {
	t.Helper()
	var repos map[string]fixtureRepo
	loadJSON(t, "testdata/repos.json", &repos)
	fx, ok := repos[name]
	if !ok {
		t.Fatalf("no fixture repository %s", name)
	}
	d := filepath.Join(dir, name)
	for rel, text := range fx.Files {
		p := filepath.Join(d, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if fx.Git {
		env := append(os.Environ(), "GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@example.org",
			"GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@example.org",
			"GIT_AUTHOR_DATE=2026-11-01T00:00:00Z", "GIT_COMMITTER_DATE=2026-11-01T00:00:00Z")
		for _, args := range [][]string{
			{"init", "-q", "-b", "main", d},
			{"-C", d, "add", "-A"},
			{"-C", d, "commit", "-q", "-m", "init"},
			{"-C", d, "remote", "add", "origin", "https://github.com/" + Org + "/" + name + ".git"},
		} {
			cmd := exec.Command(gitBin(), args...)
			cmd.Env = env
			if out, err := cmd.CombinedOutput(); err != nil {
				t.Fatalf("git %v: %v\n%s", args, err, out)
			}
		}
	}
	return d
}

func run(args []string, env Env) (int, string, string) {
	var out, errOut bytes.Buffer
	if env.Getenv == nil {
		env.Getenv = func(string) string { return "" }
	}
	rc := Main(args, env, &out, &errOut)
	return rc, out.String(), errOut.String()
}

var update = flag.Bool("update", false, "rewrite testdata/golden/ from this code")

// golden is one golden file: its cases as plain maps, so -update rewrites
// the outputs and keeps every input.
type golden struct {
	path  string
	cases []map[string]any
	dirty bool
}

func loadGolden(t *testing.T, name string) *golden {
	t.Helper()
	g := &golden{path: "testdata/golden/" + name}
	loadJSON(t, g.path, &g.cases)
	if len(g.cases) == 0 {
		t.Fatalf("%s: no cases", g.path)
	}
	return g
}

func (g *golden) str(i int, k string) string { s, _ := g.cases[i][k].(string); return s }

func (g *golden) raw(t *testing.T, i int, k string) json.RawMessage {
	t.Helper()
	b, err := json.Marshal(g.cases[i][k])
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// check compares got with the case's field k, or records it under -update.
func (g *golden) check(t *testing.T, i int, k string, got any) {
	t.Helper()
	got = normal(t, got)
	if *update {
		if !reflect.DeepEqual(g.cases[i][k], got) {
			g.cases[i][k], g.dirty = got, true
		}
		return
	}
	if !reflect.DeepEqual(g.cases[i][k], got) {
		t.Errorf("%s: %v\nwant %v", k, got, g.cases[i][k])
	}
}

func (g *golden) save(t *testing.T) {
	t.Helper()
	if !g.dirty {
		return
	}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", " ")
	if err := enc.Encode(g.cases); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(g.path, b.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Logf("rewrote %s", g.path)
}

func TestGoldenAnswers(t *testing.T) {
	g := loadGolden(t, "answers.json")
	defer g.save(t)
	for i, c := range g.cases {
		t.Run(c["name"].(string), func(t *testing.T) {
			var args []string
			if err := json.Unmarshal(g.raw(t, i, "args"), &args); err != nil {
				t.Fatal(err)
			}
			w := t.TempDir()
			d := makeRepo(t, w, g.str(i, "repo"))
			rc, out, errOut := run(append([]string{"answers", d}, args...), Env{})
			g.check(t, i, "rc", rc)
			g.check(t, i, "stdout", strings.ReplaceAll(out, w, "$WORK"))
			g.check(t, i, "stderr", strings.ReplaceAll(errOut, w, "$WORK"))
			var written any
			if b, err := os.ReadFile(filepath.Join(d, Out)); err == nil {
				written = string(b)
			}
			g.check(t, i, "written", written)
		})
	}
}

type lookup struct {
	hits  []any
	asked []string
}

func (l *lookup) Search(url string) (any, error) {
	l.asked = append(l.asked, url)
	return l.hits, nil
}
func (l *lookup) Site(string) (any, error)                  { return nil, errors.New("unused") }
func (l *lookup) File(string, string) (string, bool, error) { return "", false, errors.New("unused") }
func (l *lookup) Tree(string) (map[string]bool, error)      { return nil, errors.New("unused") }
func (l *lookup) Repos() ([]string, error)                  { return nil, errors.New("unused") }
func (l *lookup) HasRelease(string) (bool, error)           { return false, errors.New("unused") }

func TestGoldenRegister(t *testing.T) {
	g := loadGolden(t, "register.json")
	defer g.save(t)
	fixture, err := LoadAnswers("testdata/anthocnet-answers.json")
	if err != nil {
		t.Fatal(err)
	}
	for i, c := range g.cases {
		t.Run(c["name"].(string), func(t *testing.T) {
			if limit, ok := c["limit"].(float64); ok {
				urls, err := ProposalURLs("16656", fixture, "passing", int(limit))
				if err != nil {
					t.Fatal(err)
				}
				g.check(t, i, "urls", urls)
				return
			}
			w := t.TempDir()
			d := "/nonexistent"
			if repo := g.str(i, "repo"); repo != "" {
				d = makeRepo(t, w, repo)
			}
			if c["write_first"] == true {
				if rc, _, e := run([]string{"answers", d, "--write", "--today", "2026-11-13"}, Env{}); rc != 0 {
					t.Fatal(e)
				}
			}
			hits, err := decodeJSON(g.raw(t, i, "hits"))
			if err != nil {
				t.Fatal(err)
			}
			l := &lookup{hits: hits.([]any)}
			args := []string{"register", Org + "/Proto", "--dir", d, "--today", "2026-11-13"}
			if c["answers_file"] == true {
				args = append(args, "--answers", "testdata/anthocnet-answers.json")
			}
			rc, out, errOut := run(args, Env{Remote: l})
			g.check(t, i, "rc", rc)
			g.check(t, i, "stdout", strings.ReplaceAll(out, w, "$WORK"))
			g.check(t, i, "stderr", strings.ReplaceAll(errOut, w, "$WORK"))
			g.check(t, i, "asked", l.asked)
		})
	}
}

// fake is the Python self-test's Fake: a site and GitHub built from a JSON world.
type fake struct {
	sites      map[string]any
	files      map[[2]string]string
	issues     map[string]any
	registry   map[string]any
	down       map[string]bool
	failWrites bool
	tree       map[string]bool
	repos      []string
	calls      []any
	searched   []string
}

func newFake(t *testing.T, raw json.RawMessage) *fake {
	t.Helper()
	v, err := decodeJSON(raw)
	if err != nil {
		t.Fatal(err)
	}
	w := v.(map[string]any)
	f := &fake{files: map[[2]string]string{}, down: map[string]bool{}, tree: map[string]bool{}}
	f.sites, _ = w["sites"].(map[string]any)
	// a site entry marked "$proposed" starts from the world's
	// .bestpractices.json (kept as text, so the golden file holds no JSON key
	// a secret scanner reads as a credential: crypto_password_storage_*)
	for id, s := range f.sites {
		entry, ok := s.(map[string]any)
		if !ok || entry["$proposed"] != true {
			continue
		}
		base, err := decodeJSON([]byte(w["proposed"].(string)))
		if err != nil {
			t.Fatal(err)
		}
		full := base.(map[string]any)
		for k, v := range entry {
			if k != "$proposed" {
				full[k] = v
			}
		}
		f.sites[id] = full
	}
	for _, x := range w["files"].([]any) {
		e := x.([]any)
		f.files[[2]string{e[0].(string), e[1].(string)}] = e[2].(string)
	}
	f.issues, _ = w["issues"].(map[string]any)
	f.registry, _ = w["registry"].(map[string]any)
	if d, ok := w["down"].([]any); ok {
		for _, u := range d {
			f.down[u.(string)] = true
		}
	}
	f.failWrites, _ = w["fail_writes"].(bool)
	for _, p := range w["tree"].([]any) {
		f.tree[p.(string)] = true
	}
	for _, r := range w["repos"].([]any) {
		f.repos = append(f.repos, r.(string))
	}
	return f
}

func (f *fake) Site(project string) (any, error) {
	if s, ok := f.sites[project]; ok {
		return s, nil
	}
	return nil, &PyError{"URLError", "<urlopen error 404>"}
}

func (f *fake) File(repo, path string) (string, bool, error) {
	t, ok := f.files[[2]string{repo, path}]
	return t, ok, nil
}

func (f *fake) Tree(string) (map[string]bool, error) { return f.tree, nil }

func (f *fake) Search(url string) (any, error) {
	f.searched = append(f.searched, url)
	if f.down[url] {
		return nil, &PyError{"URLError", "<urlopen error timed out>"}
	}
	if h, ok := f.registry[url]; ok {
		return h, nil
	}
	return []any{}, nil
}

func (f *fake) Repos() ([]string, error) { return f.repos, nil }

func (f *fake) API(method, path string, body map[string]any, paginate bool) (any, error) {
	var b any
	if body != nil {
		b = body
	}
	f.calls = append(f.calls, []any{method, path, b, paginate})
	if method != "GET" && f.failWrites {
		return nil, failure("gh api %s %s: HTTP 502", method, path)
	}
	if method == "GET" {
		if i, ok := f.issues[strings.Split(path, "/")[2]]; ok {
			return i, nil
		}
		return []any{}, nil
	}
	if method == "POST" && strings.HasSuffix(path, "/issues") {
		return map[string]any{"number": json.Number("9")}, nil
	}
	return map[string]any{}, nil
}

// normal is v through JSON, so Go and Python values compare.
func normal(t *testing.T, v any) any {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestGoldenCheck(t *testing.T) {
	g := loadGolden(t, "check.json")
	defer g.save(t)
	for i, c := range g.cases {
		t.Run(c["name"].(string), func(t *testing.T) {
			f := newFake(t, g.raw(t, i, "world"))
			var vars map[string]string
			if err := json.Unmarshal(g.raw(t, i, "env"), &vars); err != nil {
				t.Fatal(err)
			}
			env := func(k string) string {
				if k == "BESTPRACTICES_TOKEN" {
					return g.str(i, "token")
				}
				return vars[k]
			}
			var out bytes.Buffer
			args := CheckArgs{g.str(i, "repos"), c["issues"] == true, c["dry_run"] == true}
			rc := Check(args, f, func(string) GitHub { return f }, env, &out)
			calls := f.calls
			if calls == nil {
				calls = []any{}
			}
			searched := f.searched
			if searched == nil {
				searched = []string{}
			}
			g.check(t, i, "rc", rc)
			g.check(t, i, "stdout", out.String())
			g.check(t, i, "calls", calls)
			g.check(t, i, "searched", searched)
		})
	}
}
