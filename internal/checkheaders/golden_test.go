// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

// testdata/golden.json holds, per case, what the Python tool printed and
// exited with on a fixture repository of testdata/fixtures.json. It was
// written by testdata/gen_golden.py from tools/checks/check-headers.py at
// 864d9b1, the byte-identical proof of #531; a deliberate change of output
// rewrites it with
//
//	go test ./internal/checkheaders/ -run Golden -update
//
// and the PR shows the diff. A case where the Python tool died with a
// traceback is a crash: exit 1, the same stdout, an error on stderr.

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"flag"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

var update = flag.Bool("update", false, "rewrite testdata/golden.json from this code")

type fixture struct {
	Files    map[string]string `json:"files"`
	Raw      map[string]string `json:"raw"`
	Symlinks map[string]string `json:"symlinks"`
	Steps    [][]string        `json:"steps"`
}

type goldenCase struct {
	Fixture string            `json:"fixture"`
	Cwd     string            `json:"cwd"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
	RC      int               `json:"rc"`
	Stdout  string            `json:"stdout"`
	Stderr  string            `json:"stderr"`
	Crash   bool              `json:"crash"`
}

type selfTestGolden struct {
	Label    string   `json:"label"`
	Fire     bool     `json:"fire"`
	Findings []string `json:"findings"`
}

type golden struct {
	Cases    []goldenCase     `json:"cases"`
	SelfTest []selfTestGolden `json:"selftest"`
}

var gitEnv = []string{
	"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@example.org",
	"GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@example.org",
	"GIT_AUTHOR_DATE=2026-11-01T00:00:00Z", "GIT_COMMITTER_DATE=2026-11-01T00:00:00Z",
	"GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_NOSYSTEM=1",
}

var defaultSteps = [][]string{{"git", "init", "-q", "-b", "main", "."}, {"git", "add", "-A"}}

// buildFixture materialises one fixture as gen_golden.py's build() does.
func buildFixture(t *testing.T, fx fixture, d string) {
	t.Helper()
	write := func(rel string, b []byte) {
		p := filepath.Join(d, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(d, 0o755); err != nil {
		t.Fatal(err)
	}
	for rel, text := range fx.Files {
		write(rel, []byte(text))
	}
	for rel, b64 := range fx.Raw {
		b, err := base64.StdEncoding.DecodeString(b64)
		if err != nil {
			t.Fatal(err)
		}
		write(rel, b)
	}
	for rel, target := range fx.Symlinks {
		p := filepath.Join(d, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, p); err != nil {
			t.Fatal(err)
		}
	}
	steps := fx.Steps
	if steps == nil {
		steps = defaultSteps
	}
	for _, step := range steps {
		mayFail := strings.HasPrefix(step[0], "!")
		cmd := exec.Command(strings.TrimPrefix(step[0], "!"), step[1:]...)
		cmd.Dir = d
		cmd.Env = append(os.Environ(), gitEnv...)
		if out, err := cmd.CombinedOutput(); err != nil && !mayFail {
			t.Fatalf("%v: %v\n%s", step, err, out)
		}
	}
}

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

func TestGolden(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git builds the fixture repositories")
	}
	var fixtures map[string]fixture
	loadJSON(t, "testdata/fixtures.json", &fixtures)
	var g golden
	loadJSON(t, "testdata/golden.json", &g)
	goldenPath, err := filepath.Abs("testdata/golden.json")
	if err != nil {
		t.Fatal(err)
	}

	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root = filepath.Join(root, "fx")
	for name, fx := range fixtures {
		buildFixture(t, fx, filepath.Join(root, name))
	}
	dep := filepath.Join(root, "dep", "core")
	for i, c := range g.Cases {
		args := make([]string, len(c.Args))
		for j, a := range c.Args {
			a = strings.ReplaceAll(a, "{depdir}", filepath.Join(root, "dep"))
			args[j] = strings.ReplaceAll(a, "{dep}", dep)
		}
		var stdout, stderr bytes.Buffer
		func() {
			t.Chdir(filepath.Join(root, c.Fixture, c.Cwd))
			for k, v := range c.Env {
				old, had := os.LookupEnv(k)
				os.Setenv(k, v)
				defer func() {
					if had {
						os.Setenv(k, old)
					} else {
						os.Unsetenv(k)
					}
				}()
			}
			rc := Main(args, &stdout, &stderr)
			name := c.Fixture + "/" + c.Cwd + " " + strings.Join(c.Args, " ")
			if *update {
				g.Cases[i].RC, g.Cases[i].Stdout = rc, stdout.String()
				if !c.Crash {
					g.Cases[i].Stderr = stderr.String()
				}
				return
			}
			if rc != c.RC {
				t.Errorf("%s: exit %d, want %d (stderr %q)", name, rc, c.RC, stderr.String())
			}
			if stdout.String() != c.Stdout {
				t.Errorf("%s: stdout\n%s\nwant\n%s", name, stdout.String(), c.Stdout)
			}
			if c.Crash {
				if stderr.Len() == 0 {
					t.Errorf("%s: the Python tool died here; want an error on stderr", name)
				}
			} else if stderr.String() != c.Stderr {
				t.Errorf("%s: stderr\n%s\nwant\n%s", name, stderr.String(), c.Stderr)
			}
		}()
	}

	if len(g.SelfTest) != len(SelfTestCases) {
		t.Fatalf("%d self-test cases, the Python tool had %d", len(SelfTestCases), len(g.SelfTest))
	}
	known := func(p string) bool { return SelfTestKnown[p] }
	for i, c := range SelfTestCases {
		got := CheckFile(c.Rel, c.Text, SelfTestRules, known, nil)
		if *update {
			g.SelfTest[i].Findings = append([]string{}, got...)
			continue
		}
		want := g.SelfTest[i]
		if want.Label != c.Label || want.Fire != c.Fire {
			t.Errorf("case %d is %q (fire %v), the Python's %q (fire %v)", i, c.Label, c.Fire, want.Label, want.Fire)
		}
		if len(got) != 0 || len(want.Findings) != 0 {
			if !reflect.DeepEqual(got, want.Findings) {
				t.Errorf("%s: findings %q, want %q", c.Label, got, want.Findings)
			}
		}
	}
	if *update {
		var b bytes.Buffer
		enc := json.NewEncoder(&b)
		enc.SetEscapeHTML(false)
		enc.SetIndent("", " ")
		if err := enc.Encode(g); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(goldenPath, b.Bytes(), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}
