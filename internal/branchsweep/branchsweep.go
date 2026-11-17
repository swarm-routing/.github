// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package branchsweep deletes the org's stale branches (#595). Head branches are
// deleted on merge, but the head of a PR closed without merging, a validation
// branch that never had a PR and a bot branch left by a superseded PR stay, and
// agent sessions cannot delete a branch. In every repository it deletes:
//
//   - a branch whose PRs are all closed (merged or not), the newest closed more
//     than ClosedAge ago, whose tip commit is older than ClosedAge too (nobody
//     pushed to it after the close), and that no open PR uses as head or base;
//   - a claude/* or org-bot/* branch with no PR at all and no commit for
//     IdleAge.
//
// It never deletes the default branch, main, bot/release, gh-readonly-queue/*,
// release/* or releases/* branches, a protected branch, or a branch an open PR
// uses; it never touches a tag. Every other branch is kept. A private
// repository is never named in its output, nor are its branches: a public
// workflow log holds it.
package branchsweep

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/repomask"
)

// Org is the organization swept.
const Org = "swarm-routing"

const (
	// ClosedAge is how long a branch stays after its last PR closed.
	ClosedAge = 48 * time.Hour
	// IdleAge is how long a claude/* or org-bot/* branch with no PR stays after its last commit.
	IdleAge = 7 * 24 * time.Hour
	// MaxDeletes bounds one run (golden rule 7); the rest waits for the next day.
	MaxDeletes = 200
	// maxPages bounds every listing: 100 items a page.
	maxPages = 20
)

var repoName = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

// Protected says why a branch name is never deleted, or "" when it may be.
func Protected(name, defaultBranch string) string {
	switch {
	case name == defaultBranch:
		return "the default branch"
	case name == "main":
		return "main"
	case name == "bot/release":
		return "the release PR's branch"
	case strings.HasPrefix(name, "gh-readonly-queue/"):
		return "a merge-queue branch"
	case name == "release" || name == "releases" ||
		strings.HasPrefix(name, "release/") || strings.HasPrefix(name, "releases/"):
		return "a release branch"
	}
	return ""
}

// agentOrBot is a branch rule 2 may delete without any PR.
func agentOrBot(name string) bool {
	return strings.HasPrefix(name, "claude/") || strings.HasPrefix(name, "org-bot/")
}

// GitHub is the REST client: base URL, token, HTTP client.
type GitHub struct {
	API    string
	Token  string
	Client *http.Client
}

// apiError carries the status of a failed call.
type apiError struct {
	status int
	msg    string
}

func (e *apiError) Error() string { return e.msg }

func (g GitHub) do(method, path string, body any) ([]byte, error) {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, g.API+"/"+path, rd)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "swarm-routing-branch-sweep")
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	resp, err := g.Client.Do(req)
	if err != nil {
		msg := err.Error()
		if g.Token != "" {
			msg = strings.ReplaceAll(msg, g.Token, "[redacted]")
		}
		return nil, fmt.Errorf("%s %s: %s", method, path, msg)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg := strings.TrimSpace(string(data))
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return nil, &apiError{resp.StatusCode, fmt.Sprintf("%s %s: HTTP %d: %s", method, path, resp.StatusCode, msg)}
	}
	return data, nil
}

// list reads every page of a listing (path has a query already).
func list[T any](g GitHub, path string) ([]T, error) {
	var all []T
	for page := 1; page <= maxPages; page++ {
		data, err := g.do("GET", fmt.Sprintf("%s&per_page=100&page=%d", path, page), nil)
		if err != nil {
			return nil, err
		}
		var got []T
		if err := json.Unmarshal(data, &got); err != nil {
			return nil, fmt.Errorf("GET %s: %v", path, err)
		}
		all = append(all, got...)
		if len(got) < 100 {
			return all, nil
		}
	}
	return nil, fmt.Errorf("GET %s: more than %d pages", path, maxPages)
}

// Repo is the part of a repository the sweep reads.
type Repo struct {
	Name          string `json:"name"`
	FullName      string `json:"full_name"`
	DefaultBranch string `json:"default_branch"`
	Archived      bool   `json:"archived"`
	Private       bool   `json:"private"`
}

type branch struct {
	Name      string `json:"name"`
	Protected bool   `json:"protected"`
	Commit    struct {
		SHA string `json:"sha"`
	} `json:"commit"`
}

type pull struct {
	Number   int        `json:"number"`
	ClosedAt *time.Time `json:"closed_at"`
	Head     struct {
		Ref  string `json:"ref"`
		Repo *struct {
			FullName string `json:"full_name"`
		} `json:"repo"`
	} `json:"head"`
	Base struct {
		Ref string `json:"ref"`
	} `json:"base"`
}

func (p pull) headIn(full string) bool {
	return p.Head.Repo != nil && p.Head.Repo.FullName == full
}

// repos is every unarchived org repository, or the named ones.
func (g GitHub) repos(names []string) ([]Repo, error) {
	if len(names) == 0 {
		all, err := list[Repo](g, "orgs/"+Org+"/repos?type=all")
		if err != nil {
			return nil, err
		}
		sort.Slice(all, func(i, j int) bool { return strings.ToLower(all[i].Name) < strings.ToLower(all[j].Name) })
		return all, nil
	}
	var out []Repo
	for _, n := range names {
		if !repoName.MatchString(n) {
			return nil, fmt.Errorf("%q is not a repository name", n)
		}
		data, err := g.do("GET", "repos/"+Org+"/"+n, nil)
		if err != nil {
			return nil, err
		}
		var r Repo
		if err := json.Unmarshal(data, &r); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

func (g GitHub) commitDate(full, sha string) (time.Time, error) {
	data, err := g.do("GET", fmt.Sprintf("repos/%s/commits/%s", full, sha), nil)
	if err != nil {
		return time.Time{}, err
	}
	var c struct {
		Commit struct {
			Committer struct {
				Date time.Time `json:"date"`
			} `json:"committer"`
		} `json:"commit"`
	}
	if err := json.Unmarshal(data, &c); err != nil || c.Commit.Committer.Date.IsZero() {
		return time.Time{}, fmt.Errorf("commit %s of %s: no date", sha, full)
	}
	return c.Commit.Committer.Date, nil
}

// refPath is a branch name as a refs/heads path, each segment escaped.
func refPath(name string) string {
	parts := strings.Split(name, "/")
	for i, p := range parts {
		parts[i] = url.PathEscape(p)
	}
	return strings.Join(parts, "/")
}

// Decision is what the sweep does with one branch.
type Decision struct {
	Branch string
	Delete bool
	Why    string
}

// decide applies the rules to one branch; it reads the branch's PRs and tip commit only when needed.
func (g GitHub) decide(r Repo, b branch, open map[string]int, now time.Time) (Decision, error) {
	d := Decision{Branch: b.Name}
	if why := Protected(b.Name, r.DefaultBranch); why != "" {
		d.Why = "kept: " + why
		return d, nil
	}
	if b.Protected {
		d.Why = "kept: a protected branch"
		return d, nil
	}
	if n, ok := open[b.Name]; ok {
		d.Why = fmt.Sprintf("kept: open PR #%d", n)
		return d, nil
	}
	head := url.QueryEscape(Org + ":" + b.Name)
	prs, err := list[pull](g, fmt.Sprintf("repos/%s/pulls?state=closed&head=%s&sort=updated&direction=desc", r.FullName, head))
	if err != nil {
		return d, err
	}
	var last *pull
	for i := range prs {
		p := &prs[i]
		if !p.headIn(r.FullName) || p.Head.Ref != b.Name || p.ClosedAt == nil {
			continue
		}
		if last == nil || p.ClosedAt.After(*last.ClosedAt) {
			last = p
		}
	}
	if last == nil && !agentOrBot(b.Name) {
		d.Why = "kept: no PR, not claude/* or org-bot/*"
		return d, nil
	}
	if last != nil && now.Sub(*last.ClosedAt) < ClosedAge {
		d.Why = fmt.Sprintf("kept: PR #%d closed %s ago", last.Number, now.Sub(*last.ClosedAt).Truncate(time.Minute))
		return d, nil
	}
	tip, err := g.commitDate(r.FullName, b.Commit.SHA)
	if err != nil {
		return d, err
	}
	age := now.Sub(tip).Truncate(time.Minute)
	if last != nil {
		if age < ClosedAge {
			d.Why = fmt.Sprintf("kept: PR #%d closed, but a commit %s ago", last.Number, age)
			return d, nil
		}
		d.Delete = true
		d.Why = fmt.Sprintf("PR #%d closed %s ago", last.Number, now.Sub(*last.ClosedAt).Truncate(time.Hour))
		return d, nil
	}
	if age < IdleAge {
		d.Why = fmt.Sprintf("kept: no PR, last commit %s ago", age)
		return d, nil
	}
	d.Delete = true
	d.Why = fmt.Sprintf("no PR, last commit %s ago", age.Truncate(time.Hour))
	return d, nil
}

// Result counts one run.
type Result struct {
	Deleted, Kept, Failed, Deferred int
}

// sweepRepo decides every branch of one repository and deletes what is stale; it
// writes one line per deletion (or would-be deletion) and one summary line.
func (g GitHub) sweepRepo(r Repo, label string, now time.Time, dry, verbose bool, budget *int, res *Result, out io.Writer) error {
	branches, err := list[branch](g, fmt.Sprintf("repos/%s/branches?protected=false", r.FullName))
	if err != nil {
		return err
	}
	// protected branches are left out of the listing (and refused again in decide)
	pulls, err := list[pull](g, fmt.Sprintf("repos/%s/pulls?state=open", r.FullName))
	if err != nil {
		return err
	}
	open := map[string]int{}
	for _, p := range pulls {
		if p.headIn(r.FullName) {
			open[p.Head.Ref] = p.Number
		}
		open[p.Base.Ref] = p.Number // a stacked PR's base
	}
	sort.Slice(branches, func(i, j int) bool { return branches[i].Name < branches[j].Name })
	deleted, kept, failed := 0, 0, 0
	for i, b := range branches {
		name, show := b.Name, func(e error) error { return e }
		if r.Private { // a private repository's branch names and paths never reach a public log
			name = fmt.Sprintf("branch %d", i+1)
			show = func(e error) error {
				return errors.New(strings.NewReplacer(r.FullName, repomask.Hidden, url.QueryEscape(b.Name), "<branch>",
					refPath(b.Name), "<branch>", b.Name, "<branch>").Replace(e.Error()))
			}
		}
		d, err := g.decide(r, b, open, now)
		if err != nil {
			fmt.Fprintf(out, "%s %s: error: %v\n", label, name, show(err))
			failed++
			continue
		}
		if !d.Delete {
			kept++
			if verbose {
				fmt.Fprintf(out, "%s %s: %s\n", label, name, d.Why)
			}
			continue
		}
		if *budget <= 0 {
			res.Deferred++
			kept++
			fmt.Fprintf(out, "%s %s: %s; deferred (%d deletions a run)\n", label, name, d.Why, MaxDeletes)
			continue
		}
		*budget--
		if dry {
			fmt.Fprintf(out, "%s %s: %s; dry run: would delete\n", label, name, d.Why)
			deleted++
			continue
		}
		_, err = g.do("DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", r.FullName, refPath(b.Name)), nil)
		var ae *apiError
		switch {
		case err == nil:
			fmt.Fprintf(out, "%s %s: %s; deleted\n", label, name, d.Why)
			deleted++
		case errors.As(err, &ae) && ae.status == http.StatusUnprocessableEntity:
			fmt.Fprintf(out, "%s %s: %s; already gone\n", label, name, d.Why)
		case errors.As(err, &ae) && ae.status == http.StatusForbidden:
			fmt.Fprintf(out, "%s %s: delete refused (the token needs Contents: write): %v\n", label, name, show(err))
			failed++
		default:
			fmt.Fprintf(out, "%s %s: delete failed: %v\n", label, name, show(err))
			failed++
		}
	}
	verb := "deleted"
	if dry {
		verb = "would delete"
	}
	fmt.Fprintf(out, "%s: %d branches, %s %d, kept %d", label, len(branches), verb, deleted, kept)
	if failed > 0 {
		fmt.Fprintf(out, ", %d failed", failed)
	}
	fmt.Fprintln(out)
	res.Deleted += deleted
	res.Kept += kept
	res.Failed += failed
	if failed > 0 {
		return fmt.Errorf("%d branches failed", failed)
	}
	return nil
}

// Run sweeps every unarchived repository (or the named ones); it tries them all and
// returns an error when any failed.
func Run(g GitHub, names []string, now time.Time, dry, verbose bool, out io.Writer) (Result, error) {
	var res Result
	repos, err := g.repos(names)
	if err != nil {
		return res, err
	}
	budget, failed := MaxDeletes, 0
	var mask repomask.Masker // a private repository is never named in the output, which a public workflow log holds
	for _, r := range repos {
		label := mask.Repo(r.Name, r.Private, r.FullName, r.Name)
		if r.Archived {
			fmt.Fprintf(out, "%s: archived, skipped\n", label)
			continue
		}
		if r.FullName != Org+"/"+r.Name || !repoName.MatchString(r.Name) {
			fmt.Fprintf(out, "%s: not an %s repository, skipped\n", label, Org)
			continue
		}
		if err := g.sweepRepo(r, label, now, dry, verbose, &budget, &res, out); err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", label, mask.Error(err))
			failed++
		}
	}
	verb := "deleted"
	if dry {
		verb = "would delete"
	}
	fmt.Fprintf(out, "branch-sweep: %d repositories, %s %d branches, kept %d", len(repos), verb, res.Deleted, res.Kept)
	if res.Deferred > 0 {
		fmt.Fprintf(out, ", %d deferred to the next run", res.Deferred)
	}
	fmt.Fprintln(out)
	if failed > 0 {
		return res, fmt.Errorf("%d of %d repositories failed", failed, len(repos))
	}
	return res, nil
}

const usage = "usage: branch-sweep [--dry-run] [--verbose] [--repos A,B] [--now RFC3339]"

// Main is the command. GH_TOKEN: Contents write on every repository to delete
// (read, with Pull requests read, to decide); no token is a dry run.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	dry, verbose, nowS := false, false, ""
	var names []string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case a == "--verbose":
			verbose = true
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
			fmt.Fprintln(stderr, "branch-sweep: --now:", err)
			return 2
		}
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "branch-sweep: no GH_TOKEN: dry run")
		dry = true
	}
	g := GitHub{API: api, Token: token, Client: client}
	if _, err := Run(g, names, now, dry, verbose, stdout); err != nil {
		fmt.Fprintln(stderr, "branch-sweep:", err)
		return 1
	}
	return 0
}
