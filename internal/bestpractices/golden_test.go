// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// The byte-identical proof (#531): testdata/golden/*.json hold what the
// Python tool (tools/bestpractices/bestpractices.py, written by
// testdata/gen_golden.py) printed, exited with and wrote, and every call it
// made to the fake site and GitHub, for each case; these tests run the Go
// port on the same inputs and compare.

import (
	"bytes"
	"encoding/json"
	"errors"
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

// makeRepo writes fixture repository name under dir, as gen_golden.py's
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
			cmd := exec.Command("git", args...)
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

func TestGoldenAnswers(t *testing.T) {
	var cases []struct {
		Name, Repo, Stdout, Stderr string
		Args                       []string
		RC                         int `json:"rc"`
		Written                    *string
	}
	loadJSON(t, "testdata/golden/answers.json", &cases)
	if len(cases) == 0 {
		t.Fatal("no cases")
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			w := t.TempDir()
			d := makeRepo(t, w, c.Repo)
			rc, out, errOut := run(append([]string{"answers", d}, c.Args...), Env{})
			out, errOut = strings.ReplaceAll(out, w, "$WORK"), strings.ReplaceAll(errOut, w, "$WORK")
			if rc != c.RC || out != c.Stdout || errOut != c.Stderr {
				t.Fatalf("rc %d (want %d)\nstdout:\n%s\nwant:\n%s\nstderr: %q\nwant:   %q", rc, c.RC, out, c.Stdout, errOut, c.Stderr)
			}
			if c.Written != nil {
				got, err := os.ReadFile(filepath.Join(d, Out))
				if err != nil || string(got) != *c.Written {
					t.Fatalf("written %s: %v\n%s\nwant:\n%s", Out, err, got, *c.Written)
				}
			}
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

func TestGoldenRegister(t *testing.T) {
	var cases []struct {
		Name, Stdout, Stderr string
		Repo                 *string
		Hits                 json.RawMessage
		AnswersFile          bool `json:"answers_file"`
		WriteFirst           bool `json:"write_first"`
		RC                   int  `json:"rc"`
		Asked                []string
		Limit                int
		URLs                 []string `json:"urls"`
	}
	loadJSON(t, "testdata/golden/register.json", &cases)
	fixture, err := LoadAnswers("testdata/anthocnet-answers.json")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			if c.Limit > 0 {
				urls, err := ProposalURLs("16656", fixture, "passing", c.Limit)
				if err != nil || !reflect.DeepEqual(urls, c.URLs) {
					t.Fatalf("%v\n%q\nwant\n%q", err, urls, c.URLs)
				}
				return
			}
			w := t.TempDir()
			d := "/nonexistent"
			if c.Repo != nil {
				d = makeRepo(t, w, *c.Repo)
			}
			if c.WriteFirst {
				if rc, _, e := run([]string{"answers", d, "--write", "--today", "2026-11-13"}, Env{}); rc != 0 {
					t.Fatal(e)
				}
			}
			hits, err := decodeJSON(c.Hits)
			if err != nil {
				t.Fatal(err)
			}
			l := &lookup{hits: hits.([]any)}
			args := []string{"register", Org + "/Proto", "--dir", d, "--today", "2026-11-13"}
			if c.AnswersFile {
				args = append(args, "--answers", "testdata/anthocnet-answers.json")
			}
			rc, out, errOut := run(args, Env{Remote: l})
			out, errOut = strings.ReplaceAll(out, w, "$WORK"), strings.ReplaceAll(errOut, w, "$WORK")
			if rc != c.RC || out != c.Stdout || errOut != c.Stderr || !reflect.DeepEqual(l.asked, c.Asked) {
				t.Fatalf("rc %d (want %d), asked %v (want %v)\nstdout:\n%s\nwant:\n%s\nstderr: %q\nwant:   %q",
					rc, c.RC, l.asked, c.Asked, out, c.Stdout, errOut, c.Stderr)
			}
		})
	}
}

// fake is gen_golden.py's Fake: a site and GitHub built from a JSON world.
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
	var cases []struct {
		Name, Token, Repos, Stdout string
		World                      json.RawMessage
		Issues                     bool
		DryRun                     bool `json:"dry_run"`
		Env                        map[string]string
		RC                         int `json:"rc"`
		Calls                      json.RawMessage
		Searched                   []string
	}
	loadJSON(t, "testdata/golden/check.json", &cases)
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			f := newFake(t, c.World)
			env := func(k string) string {
				if k == "BESTPRACTICES_TOKEN" {
					return c.Token
				}
				return c.Env[k]
			}
			var out bytes.Buffer
			rc := Check(CheckArgs{c.Repos, c.Issues, c.DryRun}, f, func(string) GitHub { return f }, env, &out)
			var want any
			if err := json.Unmarshal(c.Calls, &want); err != nil {
				t.Fatal(err)
			}
			got := normal(t, f.calls)
			if f.calls == nil {
				got = []any{}
			}
			if rc != c.RC || out.String() != c.Stdout {
				t.Fatalf("rc %d (want %d)\nstdout:\n%s\nwant:\n%s", rc, c.RC, out.String(), c.Stdout)
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("calls\n%v\nwant\n%v", got, want)
			}
			if !reflect.DeepEqual(f.searched, c.Searched) && !(len(f.searched) == 0 && len(c.Searched) == 0) {
				t.Fatalf("searched %v, want %v", f.searched, c.Searched)
			}
		})
	}
}
