// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package vcpkgwatch makes a release's missed vcpkg port bump visible (#880).
// A release that packages a vcpkg port bumps it from its release workflow's
// `vcpkg` job, after the release is published: reusable-release.yml's, for a
// caller that names `vcpkg-ports`, or the same job in an own release.yml
// (AntHocNet's, `PORT:`). That job pushes `bot/vcpkg-<repo>` to
// swarm-routing/vcpkg-registry and opens the registry PR; when it fails, the
// release stays published and nothing else turns red (swarm-core v2.0.0: the
// portfile still named the old repository, swarm-routing/vcpkg-registry#70).
//
// For the newest release of every public org repository published Grace to
// Window ago, it reads the ports its release workflows name at the tag, and a
// port counts as bumped when the registry's versions/baseline.json holds the
// version or an open registry PR carries it (its title names the version, and
// its head is `bot/vcpkg-<repo>` or its title names the port). While a port is
// neither, one issue
// here, `[vcpkg] <repo> <tag>: port not bumped`, stays open, updated in place;
// it is closed once every port is bumped, or once a newer release of the
// repository is the one watched.
package vcpkgwatch

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/github"
	"github.com/swarm-routing/.github/internal/repomask"
)

const (
	// Org is the organization whose releases are watched.
	Org = "swarm-routing"
	// Registry is the vcpkg registry the ports are bumped in.
	Registry = Org + "/vcpkg-registry"
	// IssueRepo holds the tickets.
	IssueRepo = Org + "/.github"
	// Grace is how long a release's vcpkg job has to open its registry PR: the
	// job runs right after the publish and takes minutes.
	Grace = 2 * time.Hour
	// Window is how far back releases are watched (org-bot's aftercare window).
	Window = 14 * 24 * time.Hour
	// maxPages bounds every listing: 100 items a page.
	maxPages = 10
)

// Labels are the ticket's labels (CONTRIBUTING "Issues").
var Labels = []string{"bug", "packaging", "priority:P2"}

var (
	repoName = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	portName = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)
	// a `vcpkg-ports:` input under a reusable-release.yml call's `with:`
	portsKey = regexp.MustCompile(`^(\s*)vcpkg-ports:\s*(.*)$`)
	// an own release.yml's vcpkg job: `PORT: <name>` in its env
	portEnv = regexp.MustCompile(`^\s+PORT:\s*["']?([a-z0-9-]+)["']?\s*(#.*)?$`)
	// the ticket's title
	titleRe = regexp.MustCompile(`^\[vcpkg\] ([A-Za-z0-9_.-]+) (\S+): port not bumped$`)
)

// Title is a release's ticket.
func Title(repo, tag string) string { return fmt.Sprintf("[vcpkg] %s %s: port not bumped", repo, tag) }

func uncomment(s string) string {
	if i := strings.Index(s, " #"); i >= 0 {
		s = s[:i]
	}
	return strings.Trim(strings.TrimSpace(s), `"'`)
}

func indent(s string) int { return len(s) - len(strings.TrimLeft(s, " ")) }

// Ports are the vcpkg ports a release workflow bumps: the `vcpkg-ports` input
// of a call to reusable-release.yml (one line, or a block scalar beneath it),
// and the `PORT:` of a job that checks out the registry (an own release.yml).
func Ports(text string) []string {
	seen := map[string]bool{}
	add := func(field string) {
		for _, p := range strings.Fields(field) {
			if portName.MatchString(p) {
				seen[p] = true
			}
		}
	}
	lines := strings.Split(text, "\n")
	if strings.Contains(text, "/.github/workflows/reusable-release.yml") {
		for i, ln := range lines {
			m := portsKey.FindStringSubmatch(ln)
			if m == nil {
				continue
			}
			v := uncomment(m[2])
			if v != "" && !strings.ContainsAny(v[:1], ">|") {
				add(v)
				continue
			}
			for _, next := range lines[i+1:] {
				if strings.TrimSpace(next) == "" {
					continue
				}
				if indent(next) <= len(m[1]) {
					break
				}
				add(uncomment(next))
			}
		}
	}
	if strings.Contains(text, Registry) {
		for _, ln := range lines {
			if m := portEnv.FindStringSubmatch(ln); m != nil {
				add(m[1])
			}
		}
	}
	out := make([]string, 0, len(seen))
	for p := range seen {
		out = append(out, p)
	}
	sort.Strings(out)
	return out
}

type repo struct {
	Name     string `json:"name"`
	FullName string `json:"full_name"`
	Private  bool   `json:"private"`
	Archived bool   `json:"archived"`
	Fork     bool   `json:"fork"`
}

// Release is a repository's newest release.
type Release struct {
	Repo      string
	Tag       string
	Published time.Time
}

type pull struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	Head   struct {
		Ref string `json:"ref"`
	} `json:"head"`
}

type issue struct {
	Number int             `json:"number"`
	Title  string          `json:"title"`
	Body   string          `json:"body"`
	PR     json.RawMessage `json:"pull_request"`
}

// Registry state: each port's baseline version and the open PRs.
type registry struct {
	baseline map[string]string
	pulls    []pull
}

func (w watcher) repos(names []string) ([]repo, error) {
	if len(names) == 0 {
		return github.List[repo](w.c, "orgs/"+Org+"/repos?type=public&sort=full_name", maxPages)
	}
	var out []repo
	for _, n := range names {
		if !repoName.MatchString(n) {
			return nil, fmt.Errorf("%q is not a repository name", n)
		}
		data, err := w.c.Do("GET", "repos/"+Org+"/"+n, nil)
		if err != nil {
			return nil, err
		}
		var r repo
		if err := json.Unmarshal(data, &r); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

func (w watcher) newest(name string) (*Release, error) {
	data, err := w.c.Do("GET", fmt.Sprintf("repos/%s/%s/releases?per_page=20", Org, name), nil)
	if err != nil {
		return nil, err
	}
	var rels []struct {
		Tag        string     `json:"tag_name"`
		Draft      bool       `json:"draft"`
		Prerelease bool       `json:"prerelease"`
		Published  *time.Time `json:"published_at"`
	}
	if err := json.Unmarshal(data, &rels); err != nil {
		return nil, err
	}
	var best *Release
	for _, r := range rels {
		if r.Draft || r.Prerelease || r.Published == nil {
			continue
		}
		if best == nil || r.Published.After(best.Published) {
			best = &Release{Repo: name, Tag: r.Tag, Published: *r.Published}
		}
	}
	return best, nil
}

func (w watcher) file(full, path, ref string) (string, error) {
	q := ""
	if ref != "" {
		q = "?ref=" + url.QueryEscape(ref)
	}
	data, err := w.c.Do("GET", "repos/"+full+"/contents/"+path+q, nil)
	if err != nil {
		return "", err
	}
	var f struct {
		Content  string `json:"content"`
		Encoding string `json:"encoding"`
	}
	if err := json.Unmarshal(data, &f); err != nil {
		return "", fmt.Errorf("GET %s: %v", path, err)
	}
	if f.Encoding != "base64" {
		return "", fmt.Errorf("GET %s: encoding %q", path, f.Encoding)
	}
	b, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(f.Content, "\n", ""))
	return string(b), err
}

// ports reads the release's workflows at its tag: port -> the workflow naming it.
func (w watcher) ports(rel Release) (map[string]string, error) {
	full := Org + "/" + rel.Repo
	data, err := w.c.Do("GET", "repos/"+full+"/contents/.github/workflows?ref="+url.QueryEscape(rel.Tag), nil)
	if github.Status(err) == http.StatusNotFound {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var entries []struct {
		Name string `json:"name"`
		Path string `json:"path"`
		Type string `json:"type"`
	}
	if err := json.Unmarshal(data, &entries); err != nil {
		return nil, err
	}
	out := map[string]string{}
	for _, e := range entries {
		if e.Type != "file" || !(strings.HasSuffix(e.Name, ".yml") || strings.HasSuffix(e.Name, ".yaml")) {
			continue
		}
		text, err := w.file(full, e.Path, rel.Tag)
		if err != nil {
			return nil, err
		}
		for _, p := range Ports(text) {
			if _, ok := out[p]; !ok {
				out[p] = e.Name
			}
		}
	}
	return out, nil
}

func (w watcher) registry() (registry, error) {
	text, err := w.file(Registry, "versions/baseline.json", "")
	if err != nil {
		return registry{}, err
	}
	var b struct {
		Default map[string]struct {
			Baseline string `json:"baseline"`
		} `json:"default"`
	}
	if err := json.Unmarshal([]byte(text), &b); err != nil {
		return registry{}, fmt.Errorf("versions/baseline.json: %v", err)
	}
	reg := registry{baseline: map[string]string{}}
	for p, v := range b.Default {
		reg.baseline[p] = v.Baseline
	}
	reg.pulls, err = github.List[pull](w.c, "repos/"+Registry+"/pulls?state=open", maxPages)
	return reg, err
}

// carried is the open registry PR that bumps port to version for repo, or nil:
// its title names the version (the bot's `feat(ports): <ports> <version>`),
// and its head is the release's bot branch or its title names the port (a
// hand PR). A bot PR left open for an older version does not count.
func (reg registry) carried(repo, port, version string) *pull {
	for i, p := range reg.pulls {
		words := strings.FieldsFunc(p.Title, func(r rune) bool { return strings.ContainsRune(" :(),", r) })
		hasPort, hasVer := false, false
		for _, w := range words {
			hasPort = hasPort || w == port
			hasVer = hasVer || strings.TrimPrefix(w, "v") == version
		}
		if hasVer && (hasPort || p.Head.Ref == "bot/vcpkg-"+repo) {
			return &reg.pulls[i]
		}
	}
	return nil
}

// Missing is a port the registry lacks: its baseline and the workflow naming it.
type Missing struct {
	Port, Baseline, Workflow string
}

// Body is a release's ticket.
func Body(rel Release, missing []Missing, now time.Time) string {
	full := Org + "/" + rel.Repo
	var b strings.Builder
	fmt.Fprintf(&b, "%s %s was published %s, and %s still lacks its port bump: no `versions/baseline.json` "+
		"entry at the version and no open registry PR carrying it (a title naming the version, from head "+
		"`bot/vcpkg-%s` or naming the port). The release workflow's `vcpkg` job opens that PR right after the "+
		"publish; it failed, or never ran.\n\n",
		full, rel.Tag, rel.Published.UTC().Format(time.RFC3339), Registry, rel.Repo)
	b.WriteString("| Port | Baseline | Want | Bumped by |\n|---|---|---|---|\n")
	for _, m := range missing {
		have := m.Baseline
		if have == "" {
			have = "(none)"
		}
		fmt.Fprintf(&b, "| `%s` | %s | %s | `%s` job `vcpkg` (https://github.com/%s/actions/workflows/%s) |\n",
			m.Port, have, strings.TrimPrefix(rel.Tag, "v"), m.Workflow, full, m.Workflow)
	}
	b.WriteString("\n## What to do\n\n" +
		"1. Read the release run's `vcpkg` job (the workflow above, the run for " + rel.Tag + ").\n" +
		"2. Fix the cause, then re-run that job, or bump by hand with the registry's `tools/port_bump.py` " +
		"(swarm-routing/vcpkg-registry README \"How a port is bumped\"; a port whose repository moved " +
		"needs its `portfile.cmake` pointed at the new one first, as swarm-routing/vcpkg-registry#70 did).\n" +
		"3. Nothing else: org-bot's hourly `vcpkg-watch` closes this issue once the registry PR is open " +
		"or the baseline holds the version.\n\n")
	fmt.Fprintf(&b, "Opened by org-bot's `vcpkg-watch` (cmd/vcpkg-watch, #880); updated in place hourly, last checked %s.\n",
		now.UTC().Format("2006-01-02 15:04 UTC"))
	return b.String()
}

// strip drops the last line (the time of the check) so a body compares by its content.
func strip(body string) string {
	body = strings.TrimSpace(body)
	if i := strings.LastIndex(body, "\n"); i >= 0 {
		return body[:i]
	}
	return body
}

type watcher struct {
	c   github.Client
	dry bool
	out io.Writer
}

// open lists the open tickets here, whatever their labels: repo -> issues.
func (w watcher) open() (map[string][]issue, error) {
	got, err := github.List[issue](w.c, "repos/"+IssueRepo+"/issues?state=open", maxPages)
	if err != nil {
		return nil, err
	}
	out := map[string][]issue{}
	for _, i := range got {
		if len(i.PR) > 0 {
			continue
		}
		if m := titleRe.FindStringSubmatch(strings.TrimSpace(i.Title)); m != nil {
			out[m[1]] = append(out[m[1]], i)
		}
	}
	return out, nil
}

func (w watcher) close(i issue, why string) (string, error) {
	if w.dry {
		return fmt.Sprintf("dry run: would close #%d", i.Number), nil
	}
	msg := why + "\n\n---\n_Generated by org-bot's `vcpkg-watch` (#880)_"
	if _, err := w.c.Do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", IssueRepo, i.Number), map[string]any{"body": msg}); err != nil {
		return "", err
	}
	if _, err := w.c.Do("PATCH", fmt.Sprintf("repos/%s/issues/%d", IssueRepo, i.Number),
		map[string]any{"state": "closed", "state_reason": "completed"}); err != nil {
		return "", err
	}
	return fmt.Sprintf("closed #%d", i.Number), nil
}

// keep opens or updates the release's ticket.
func (w watcher) keep(rel Release, have []issue, body string) (string, error) {
	title := Title(rel.Repo, rel.Tag)
	for _, i := range have {
		if i.Title != title {
			continue
		}
		if strip(i.Body) == strip(body) {
			return fmt.Sprintf("#%d open, unchanged", i.Number), nil
		}
		if w.dry {
			return fmt.Sprintf("dry run: would update #%d", i.Number), nil
		}
		if _, err := w.c.Do("PATCH", fmt.Sprintf("repos/%s/issues/%d", IssueRepo, i.Number), map[string]any{"body": body}); err != nil {
			return "", err
		}
		return fmt.Sprintf("updated #%d", i.Number), nil
	}
	if w.dry {
		return "dry run: would open " + IssueRepo + " issue \"" + title + "\"", nil
	}
	data, err := w.c.Do("POST", "repos/"+IssueRepo+"/issues", map[string]any{"title": title, "body": body, "labels": Labels})
	if err != nil {
		return "", err
	}
	var got issue
	if err := json.Unmarshal(data, &got); err != nil {
		return "", err
	}
	return fmt.Sprintf("opened #%d", got.Number), nil
}

// Run checks the newest release of every public repository (or the named ones)
// and keeps a ticket open for each one whose port bump is missing; one line per
// release with a port. It returns an error when a read or a write failed.
func Run(c github.Client, names []string, now time.Time, dry bool, out io.Writer) error {
	w := watcher{c: c, dry: dry, out: out}
	repos, err := w.repos(names)
	if err != nil {
		return err
	}
	var mask repomask.Masker
	var due []Release
	failed := 0
	for _, r := range repos {
		if r.Private { // the vcpkg job never runs for a private repository; the log is public
			fmt.Fprintf(out, "%s: private, skipped\n", mask.Repo(r.Name, true, r.FullName, r.Name))
			continue
		}
		if r.Archived || r.Fork || r.FullName != Org+"/"+r.Name {
			continue
		}
		rel, err := w.newest(r.Name)
		if err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", r.Name, err)
			failed++
			continue
		}
		if rel != nil && now.Sub(rel.Published) < Window {
			due = append(due, *rel)
		}
	}
	var reg *registry
	var tickets map[string][]issue
	checked, alerts := 0, 0
	for _, rel := range due {
		name := fmt.Sprintf("%s %s (published %s)", rel.Repo, rel.Tag, rel.Published.UTC().Format(time.RFC3339))
		ports, err := w.ports(rel)
		if err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", name, err)
			failed++
			continue
		}
		if len(ports) == 0 {
			continue // no vcpkg port: not this tool's
		}
		if age := now.Sub(rel.Published); age < Grace {
			fmt.Fprintf(out, "%s: published %s ago, under %s: not yet\n", name, age.Truncate(time.Minute), Grace)
			continue
		}
		if reg == nil { // read once, only when a release has a port
			r, err := w.registry()
			if err != nil {
				return fmt.Errorf("%s: %v", Registry, err)
			}
			reg = &r
			if tickets, err = w.open(); err != nil {
				return fmt.Errorf("%s issues: %v", IssueRepo, err)
			}
		}
		checked++
		version := strings.TrimPrefix(rel.Tag, "v")
		var missing []Missing
		var state []string
		keys := make([]string, 0, len(ports))
		for p := range ports {
			keys = append(keys, p)
		}
		sort.Strings(keys)
		for _, p := range keys {
			switch pr := reg.carried(rel.Repo, p, version); {
			case reg.baseline[p] == version:
				state = append(state, p+" "+version+" is the baseline")
			case pr != nil:
				state = append(state, fmt.Sprintf("%s in %s#%d", p, Registry, pr.Number))
			default:
				missing = append(missing, Missing{Port: p, Baseline: reg.baseline[p], Workflow: ports[p]})
				state = append(state, fmt.Sprintf("%s NOT BUMPED (baseline %s, no registry PR)", p, reg.baseline[p]))
			}
		}
		var acts []string
		for _, i := range tickets[rel.Repo] { // a ticket of an older release: the newest is what counts
			if i.Title == Title(rel.Repo, rel.Tag) {
				continue
			}
			act, err := w.close(i, fmt.Sprintf("%s is the newest release of %s/%s now; vcpkg-watch follows it instead.", rel.Tag, Org, rel.Repo))
			if err != nil {
				fmt.Fprintf(out, "%s: error: %v\n", name, err)
				failed++
				continue
			}
			acts = append(acts, act)
		}
		if len(missing) > 0 {
			alerts++
			act, err := w.keep(rel, tickets[rel.Repo], Body(rel, missing, now))
			if err != nil {
				fmt.Fprintf(out, "%s: error: %v\n", name, err)
				failed++
				continue
			}
			acts = append(acts, act)
		} else {
			for _, i := range tickets[rel.Repo] {
				if i.Title != Title(rel.Repo, rel.Tag) {
					continue
				}
				act, err := w.close(i, "Every port of "+rel.Tag+" is bumped now: "+strings.Join(state, "; ")+".")
				if err != nil {
					fmt.Fprintf(out, "%s: error: %v\n", name, err)
					failed++
					continue
				}
				acts = append(acts, act)
			}
		}
		line := fmt.Sprintf("%s: %s", name, strings.Join(state, "; "))
		if len(acts) > 0 {
			line += "; " + strings.Join(acts, "; ")
		}
		fmt.Fprintln(out, line)
	}
	fmt.Fprintf(out, "vcpkg-watch: %d recent releases, %d with a port checked, %d not bumped\n", len(due), checked, alerts)
	if failed > 0 {
		return fmt.Errorf("%d failed", failed)
	}
	return nil
}

const usage = "usage: vcpkg-watch [--dry-run] [--repos A,B] [--now RFC3339]"

// Main is the command. GH_TOKEN: read on the org's repositories and the
// registry, Issues: write here; no token is a dry run.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	dry, nowS := false, ""
	var names []string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case (a == "--repos" || a == "--now") && i+1 < len(args):
			if a == "--repos" {
				for _, n := range strings.Split(args[i+1], ",") {
					if n = strings.TrimSpace(n); n != "" {
						names = append(names, n)
					}
				}
			} else {
				nowS = args[i+1]
			}
			i++
		case a == "-h" || a == "--help":
			fmt.Fprintln(stdout, usage)
			return 0
		default:
			fmt.Fprintln(stderr, usage)
			return 2
		}
	}
	now := time.Now().UTC()
	if nowS != "" {
		var err error
		if now, err = time.Parse(time.RFC3339, nowS); err != nil {
			fmt.Fprintln(stderr, "vcpkg-watch: --now:", err)
			return 2
		}
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "vcpkg-watch: no GH_TOKEN: dry run")
		dry = true
	}
	c := github.Client{API: api, Token: token, UserAgent: "swarm-routing-vcpkg-watch", HTTP: client}
	if err := Run(c, names, now, dry, stdout); err != nil {
		fmt.Fprintln(stderr, "vcpkg-watch:", err)
		return 1
	}
	return 0
}
