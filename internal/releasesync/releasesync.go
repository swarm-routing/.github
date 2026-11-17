// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package releasesync makes sure the site saw each public repository's release
// (#571). The release workflow sends `org-release` to the site's release-sync.yml,
// which opens a `[release-sync] <repo> <tag>` issue and runs as "Release sync
// swarm-routing/<repo> <tag>". For the newest release of every public repository
// published more than MinAge and less than Window ago, when the site has no such
// issue or no green run of that name, it dispatches release-sync.yml with
// `repository` and `tag` (idempotent on the site's side). It waits Backoff after
// any run of that name started, so a release is dispatched at most once in that
// time, and it keeps at most Slots release-sync runs active, since the site's
// concurrency group keeps one pending run and a third would replace the second.
package releasesync

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
)

const (
	// Org is the organization whose releases are watched.
	Org = "swarm-routing"
	// Site is the repository whose release-sync.yml syncs a release.
	Site = Org + "/swarm-routing.github.io"
	// Workflow is the site's workflow.
	Workflow = "release-sync.yml"
	// MinAge is how long a release has to reach the site on its own.
	MinAge = time.Hour
	// Window is how far back releases are watched (org-bot's aftercare window).
	Window = 14 * 24 * time.Hour
	// Backoff is how long a release waits after a run of its name started.
	Backoff = 3 * time.Hour
	// Slots is how many release-sync runs may be active (one running, one pending).
	Slots = 2
	// maxPages bounds every listing: 100 items a page.
	maxPages = 10
)

var repoName = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

// tagRe is the site's own check on a tag before it goes further.
var tagRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]*$`)

// GitHub is the REST client: base URL, token, HTTP client.
type GitHub struct {
	API    string
	Token  string
	Client *http.Client
}

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
	req.Header.Set("User-Agent", "swarm-routing-release-sync-watch")
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
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

// pages reads a listing page by page; each page is decoded by decode, which
// returns how many items it held and whether to stop early.
func (g GitHub) pages(path string, decode func([]byte) (int, bool, error)) error {
	for page := 1; page <= maxPages; page++ {
		data, err := g.do("GET", fmt.Sprintf("%s&per_page=100&page=%d", path, page), nil)
		if err != nil {
			return err
		}
		n, stop, err := decode(data)
		if err != nil {
			return fmt.Errorf("GET %s: %v", path, err)
		}
		if stop || n < 100 {
			return nil
		}
	}
	return nil // the newest maxPages pages are enough: every listing is newest first
}

// repo is the part of a repository read.
type repo struct {
	Name     string `json:"name"`
	FullName string `json:"full_name"`
	Private  bool   `json:"private"`
	Archived bool   `json:"archived"`
	Fork     bool   `json:"fork"`
}

// Release is a repository's newest release.
type Release struct {
	Repo      string // the repository's name
	Tag       string
	Published time.Time
}

type run struct {
	ID         int64     `json:"id"`
	Title      string    `json:"display_title"`
	Status     string    `json:"status"`
	Conclusion string    `json:"conclusion"`
	CreatedAt  time.Time `json:"created_at"`
}

// SiteState is what the site holds: its release-sync issue titles and its runs.
type SiteState struct {
	Issues map[string]int // title -> issue number
	Runs   []run
}

func (g GitHub) repos(names []string) ([]repo, error) {
	var out []repo
	if len(names) == 0 {
		err := g.pages("orgs/"+Org+"/repos?type=public&sort=full_name", func(b []byte) (int, bool, error) {
			var got []repo
			err := json.Unmarshal(b, &got)
			out = append(out, got...)
			return len(got), false, err
		})
		return out, err
	}
	for _, n := range names {
		if !repoName.MatchString(n) {
			return nil, fmt.Errorf("%q is not a repository name", n)
		}
		data, err := g.do("GET", "repos/"+Org+"/"+n, nil)
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

// newest is the repository's newest published release that is not a draft or a prerelease.
func (g GitHub) newest(name string) (*Release, error) {
	data, err := g.do("GET", fmt.Sprintf("repos/%s/%s/releases?per_page=20", Org, name), nil)
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

// site reads the site's release-sync issues and its runs of the window.
func (g GitHub) site(now time.Time) (SiteState, error) {
	s := SiteState{Issues: map[string]int{}}
	since := now.Add(-Window - 24*time.Hour)
	err := g.pages("repos/"+Site+"/issues?state=all&sort=created&direction=desc", func(b []byte) (int, bool, error) {
		var got []struct {
			Number    int             `json:"number"`
			Title     string          `json:"title"`
			CreatedAt time.Time       `json:"created_at"`
			PR        json.RawMessage `json:"pull_request"`
		}
		if err := json.Unmarshal(b, &got); err != nil {
			return 0, false, err
		}
		stop := false
		for _, i := range got {
			if i.CreatedAt.Before(since) {
				stop = true // newest first: older issues name older releases
				continue
			}
			t := strings.TrimSpace(i.Title)
			if i.PR == nil && strings.HasPrefix(t, "[release-sync] ") {
				if _, seen := s.Issues[t]; !seen {
					s.Issues[t] = i.Number
				}
			}
		}
		return len(got), stop, nil
	})
	if err != nil {
		return s, err
	}
	err = g.pages(fmt.Sprintf("repos/%s/actions/workflows/%s/runs?created=%s", Site, Workflow,
		url.QueryEscape(">="+since.Format("2006-01-02"))), func(b []byte) (int, bool, error) {
		var got struct {
			Runs []run `json:"workflow_runs"`
		}
		err := json.Unmarshal(b, &got)
		s.Runs = append(s.Runs, got.Runs...)
		return len(got.Runs), false, err
	})
	return s, err
}

// active is a run that holds one of the site's slots.
func active(r run) bool {
	switch r.Status {
	case "queued", "in_progress", "waiting", "requested", "pending":
		return true
	}
	return false
}

// RunTitle is the name the site gives a release's run.
func RunTitle(name, tag string) string { return fmt.Sprintf("Release sync %s/%s %s", Org, name, tag) }

// IssueTitle is the site's ticket for a release.
func IssueTitle(name, tag string) string { return fmt.Sprintf("[release-sync] %s %s", name, tag) }

// verdict says what a release lacks (gap; "synced: …" when it lacks nothing) and, when its last run
// started under Backoff ago, why it waits instead of being dispatched.
func verdict(rel Release, s SiteState, now time.Time) (gap, wait string) {
	issue, hasIssue := s.Issues[IssueTitle(rel.Repo, rel.Tag)]
	title := RunTitle(rel.Repo, rel.Tag)
	var green, latest *run
	for i := range s.Runs {
		r := &s.Runs[i]
		if r.Title != title {
			continue
		}
		if r.Conclusion == "success" && green == nil {
			green = r
		}
		if latest == nil || r.CreatedAt.After(latest.CreatedAt) {
			latest = r
		}
	}
	switch {
	case hasIssue && green != nil:
		return fmt.Sprintf("synced: issue #%d, run %d green", issue, green.ID), ""
	case !hasIssue && green == nil:
		gap = "no issue and no green run"
	case !hasIssue:
		gap = fmt.Sprintf("no issue (run %d was green)", green.ID)
	default:
		gap = fmt.Sprintf("issue #%d but no green run", issue)
	}
	if latest != nil && now.Sub(latest.CreatedAt) < Backoff {
		state := latest.Status
		if latest.Status == "completed" {
			state = latest.Conclusion
		}
		return gap, fmt.Sprintf("run %d (%s) started %s ago, waiting", latest.ID, state,
			now.Sub(latest.CreatedAt).Truncate(time.Minute))
	}
	return gap, ""
}

func (g GitHub) dispatch(rel Release) error {
	body := map[string]any{"ref": "main", "inputs": map[string]string{
		"repository": Org + "/" + rel.Repo, "tag": rel.Tag}}
	_, err := g.do("POST", fmt.Sprintf("repos/%s/actions/workflows/%s/dispatches", Site, Workflow), body)
	return err
}

// Run checks the newest release of every public repository (or the named ones)
// and dispatches the site's release-sync.yml for each one it missed; one line per
// release considered. It returns an error when a read or a dispatch failed.
func Run(g GitHub, names []string, now time.Time, dry bool, out io.Writer) error {
	repos, err := g.repos(names)
	if err != nil {
		return err
	}
	var due []Release
	failed := 0
	for _, r := range repos {
		if r.Private || r.Archived || r.Fork || r.FullName != Org+"/"+r.Name {
			continue // the site syncs only the org's own public repositories
		}
		rel, err := g.newest(r.Name)
		if err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", r.Name, err)
			failed++
			continue
		}
		if rel == nil || now.Sub(rel.Published) >= Window {
			continue
		}
		if !tagRe.MatchString(rel.Tag) {
			fmt.Fprintf(out, "%s %s: not a tag the site accepts, skipped\n", r.Name, rel.Tag)
			continue
		}
		if age := now.Sub(rel.Published); age < MinAge {
			fmt.Fprintf(out, "%s %s: published %s ago, under %s: not yet\n", r.Name, rel.Tag, age.Truncate(time.Minute), MinAge)
			continue
		}
		due = append(due, *rel)
	}
	if len(due) == 0 {
		fmt.Fprintf(out, "release-sync-watch: no release between %s and %s old\n", MinAge, Window)
		if failed > 0 {
			return fmt.Errorf("%d repositories failed", failed)
		}
		return nil
	}
	s, err := g.site(now)
	if err != nil {
		return fmt.Errorf("the site: %v", err)
	}
	busy := 0
	for _, r := range s.Runs {
		if active(r) {
			busy++
		}
	}
	free := Slots - busy
	sort.Slice(due, func(i, j int) bool { return due[i].Published.Before(due[j].Published) })
	dispatched, missing := 0, 0
	for _, rel := range due {
		name := fmt.Sprintf("%s %s (published %s)", rel.Repo, rel.Tag, rel.Published.UTC().Format(time.RFC3339))
		gap, wait := verdict(rel, s, now)
		if strings.HasPrefix(gap, "synced") {
			fmt.Fprintf(out, "%s: %s\n", name, gap)
			continue
		}
		missing++
		if wait != "" {
			fmt.Fprintf(out, "%s: %s; %s\n", name, gap, wait)
			continue
		}
		if free <= 0 {
			fmt.Fprintf(out, "%s: %s; deferred: %d release-sync runs active (at most %d)\n", name, gap, busy, Slots)
			continue
		}
		with := fmt.Sprintf("%s with repository=%s/%s tag=%s", Workflow, Org, rel.Repo, rel.Tag)
		if dry {
			fmt.Fprintf(out, "%s: %s; dry run: would dispatch %s\n", name, gap, with)
			free--
			busy++
			continue
		}
		err := g.dispatch(rel)
		var ae *apiError
		switch {
		case err == nil:
			fmt.Fprintf(out, "%s: %s; dispatched %s\n", name, gap, with)
			free--
			busy++
			dispatched++
		case errors.As(err, &ae) && (ae.status == http.StatusForbidden || ae.status == http.StatusNotFound):
			fmt.Fprintf(out, "%s: %s; dispatch refused (the token needs Actions: write on %s): %v\n", name, gap, Site, err)
			failed++
		default:
			fmt.Fprintf(out, "%s: %s; dispatch failed: %v\n", name, gap, err)
			failed++
		}
	}
	fmt.Fprintf(out, "release-sync-watch: %d recent releases, %d not synced, %d dispatched\n", len(due), missing, dispatched)
	if failed > 0 {
		return fmt.Errorf("%d failed", failed)
	}
	return nil
}

const usage = "usage: release-sync-watch [--dry-run] [--repos A,B] [--now RFC3339]"

// Main is the command. GH_TOKEN: read on the org's repositories and the site,
// Actions write on the site to dispatch; no token is a dry run.
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
			fmt.Fprintln(stderr, "release-sync-watch: --now:", err)
			return 2
		}
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "release-sync-watch: no GH_TOKEN: dry run")
		dry = true
	}
	g := GitHub{API: api, Token: token, Client: client}
	if err := Run(g, names, now, dry, stdout); err != nil {
		fmt.Fprintln(stderr, "release-sync-watch:", err)
		return 1
	}
	return 0
}
