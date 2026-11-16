// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/BurntSushi/toml"
)

func sortStrings(s []string) { sort.Strings(s) }

// readText is the file's text, invalid UTF-8 replaced as Python's
// errors="replace" does; ok is false when it cannot be read.
func readText(p string) (string, bool) {
	b, err := os.ReadFile(p)
	if err != nil {
		return "", false
	}
	if utf8.Valid(b) {
		return string(b), true
	}
	return strings.ToValidUTF8(string(b), "�"), true
}

// parseTOML decodes a TOML document into plain maps.
func parseTOML(text string) (map[string]any, error) {
	var m map[string]any
	if _, err := toml.Decode(text, &m); err != nil {
		return nil, err
	}
	if m == nil {
		m = map[string]any{}
	}
	return m, nil
}

func loadConfig(repoDir string) (map[string]any, error) {
	text, ok := readText(pyJoin(repoDir, Config))
	if !ok {
		return map[string]any{}, nil
	}
	m, err := parseTOML(text)
	if err != nil {
		return nil, failure("bestpractices: %s: %v", Config, err)
	}
	return m, nil
}

// gitPaths are where git is looked for: fixed system directories, never
// $PATH (a writable directory on it could put another git first).
var gitPaths = []string{"/usr/bin/git", "/usr/local/bin/git", "/bin/git", "/opt/homebrew/bin/git"}

// gitBin is the first of gitPaths that exists, else "".
func gitBin() string {
	for _, p := range gitPaths {
		if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() {
			return p
		}
	}
	return ""
}

// git runs git in repoDir; ok is false when it fails or there is no git
// (the ci-tools image has none).
func git(repoDir string, args ...string) (string, bool) {
	bin := gitBin()
	if bin == "" {
		return "", false
	}
	cmd := exec.Command(bin, append([]string{"-C", repoDir}, args...)...)
	out, err := cmd.Output()
	if err != nil {
		return "", false
	}
	return strings.TrimSpace(string(out)), true
}

var slugRx = regexp.MustCompile(`github\.com[:/]([^/]+/[^/]+?)(\.git)?/?$`)

func gitSlug(repoDir string) string {
	out, ok := git(repoDir, "remote", "get-url", "origin")
	if !ok {
		return ""
	}
	if m := slugRx.FindStringSubmatch(out); m != nil {
		return m[1]
	}
	return ""
}

func lastCommit(repoDir string) string {
	out, _ := git(repoDir, "log", "-1", "--format=%cs")
	return out
}

// filesOf is every file under repoDir, relative, without .git and
// node_modules, in os.walk's order (directories sorted, files sorted).
func filesOf(repoDir string) []string {
	var out []string
	var walk func(rel string)
	walk = func(rel string) {
		if len(out) >= maxFiles {
			return
		}
		entries, err := os.ReadDir(pyJoin(repoDir, rel))
		if err != nil {
			return
		}
		var dirs, files []string
		for _, e := range entries {
			if isDir(pyJoin(repoDir, pyJoin(rel, e.Name())), e) {
				if e.Type()&fs.ModeSymlink == 0 && e.Name() != ".git" && e.Name() != "node_modules" {
					dirs = append(dirs, e.Name())
				}
			} else {
				files = append(files, e.Name())
			}
		}
		sort.Strings(files)
		for _, f := range files {
			out = append(out, pyJoin(rel, f))
		}
		sort.Strings(dirs)
		for _, d := range dirs {
			walk(pyJoin(rel, d))
		}
	}
	walk("")
	return out
}

// isDir is os.walk's test: a directory, or a symbolic link to one (listed
// with the directories, never entered).
func isDir(p string, e fs.DirEntry) bool {
	if e.IsDir() {
		return true
	}
	if e.Type()&fs.ModeSymlink != 0 {
		fi, err := os.Stat(p)
		return err == nil && fi.IsDir()
	}
	return false
}

type workflow struct {
	file, text string
	code       string          // text without comments (evidence.go)
	on         map[string]bool // its triggers, and its local callers'
	filtered   bool            // a paths filter limits its triggers
}

// Repo is what the answers are derived from: the files of one checkout.
type Repo struct {
	dir, slug, owner, base string
	files                  map[string]bool
	sorted                 []string
	cfg                    map[string]any
	workflows              []workflow
}

var workflowFile = regexp.MustCompile(`^\.github/workflows/[^/]+\.ya?ml$`)

func newRepo(repoDir, slug string) (*Repo, error) {
	r := &Repo{dir: repoDir, slug: slug, owner: strings.SplitN(slug, "/", 2)[0], base: "https://github.com/" + slug}
	r.files = map[string]bool{}
	for _, f := range filesOf(repoDir) {
		r.files[f] = true
		r.sorted = append(r.sorted, f)
	}
	sort.Strings(r.sorted)
	cfg, err := loadConfig(repoDir)
	if err != nil {
		return nil, err
	}
	r.cfg = cfg
	// the CI workflows first, so evidence names ci.yml before a manual one
	var ci, other []string
	for _, f := range r.sorted {
		if workflowFile.MatchString(f) {
			if strings.HasPrefix(path.Base(f), "ci") {
				ci = append(ci, f)
			} else {
				other = append(other, f)
			}
		}
	}
	for _, f := range append(ci, other...) {
		t, _ := readText(pyJoin(repoDir, f))
		code := stripComments(t)
		on, filtered := triggersOf(code)
		r.workflows = append(r.workflows, workflow{f, t, code, on, filtered})
	}
	resolveTriggers(r.workflows)
	return r, nil
}

func (r *Repo) has(paths ...string) string {
	for _, p := range paths {
		if r.files[p] {
			return p
		}
	}
	return ""
}

func (r *Repo) text(p string) string {
	if p == "" {
		return ""
	}
	t, _ := readText(pyJoin(r.dir, p))
	return t
}

func (r *Repo) url(p string) string {
	kind := "blob"
	if strings.HasSuffix(p, "/") {
		kind = "tree"
	}
	return r.base + "/" + kind + "/main/" + strings.TrimRight(p, "/")
}

// orgFile is the org default (GitHub shows it in every repository without
// its own).
func (r *Repo) orgFile(name string) string {
	if r.owner == Org {
		return "https://github.com/" + Org + "/.github/blob/main/" + name
	}
	return ""
}

func (r *Repo) grep(pattern string, suffixes ...string) string {
	rx := regexp.MustCompile("(?im)" + pattern)
	for _, f := range r.sorted {
		if endsWith(f, suffixes...) && rx.MatchString(r.text(f)) {
			return f
		}
	}
	return ""
}

func endsWith(s string, suffixes ...string) bool {
	for _, x := range suffixes {
		if strings.HasSuffix(s, x) {
			return true
		}
	}
	return false
}

// dirname is os.path.dirname.
func dirname(p string) string {
	i := strings.LastIndex(p, "/")
	if i < 0 {
		return ""
	}
	d := p[:i]
	if strings.Trim(d, "/") == "" {
		return d
	}
	return strings.TrimRight(d, "/")
}

// basename of an absolute version of p, as os.path.basename(os.path.abspath(p)).
func absBase(p string) string {
	a, err := filepath.Abs(p)
	if err != nil {
		a = p
	}
	return filepath.Base(a)
}
