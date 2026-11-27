// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package labels applies labels.json, the org's label taxonomy, to every
// repository of the org, private ones included (swarm-routing/.github#570):
// a label missing from a repository is created, one whose colour, description
// or name's case differs is updated, and no label is ever deleted (golden rule
// 11), so a repository's own labels stay; a repository labels.json lists in
// own_release_labels (AntHocNet) gets no release:* label created or updated
// (#998). It is what sync-labels.yml does for
// one repository, done for all of them from this repository with the org
// App's token, so a labels.json change reaches a private repository, which
// runs no pipelines, as soon as it merges.
//
// A private repository's name never reaches the output (a public log): it is
// printed as "private repository N", N its place in the sorted list.
package labels

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/repomask"
)

// Org is the organisation whose repositories get the labels.
const Org = "swarm-routing"

// Bounds (golden rule 7): labels.json holds a few dozen labels, the org a few
// dozen repositories.
const (
	MaxLabels   = 200
	MaxRepos    = 500
	maxPages    = 20
	perPage     = 100
	maxDescLen  = 100
	maxNameLen  = 50
	maxBodySize = 4 << 20
)

// Label is one entry of labels.json.
type Label struct {
	Name        string `json:"name"`
	Color       string `json:"color"`
	Description string `json:"description"`
}

var (
	colorRe = regexp.MustCompile(`^[0-9a-fA-F]{6}$`)
	repoRe  = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,100}$`)
)

// Load reads and checks labels.json.
func Load(data []byte) ([]Label, error) {
	var f struct {
		Labels []Label `json:"labels"`
	}
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, err
	}
	if len(f.Labels) == 0 || len(f.Labels) > MaxLabels {
		return nil, fmt.Errorf("labels.json has %d labels (1 to %d)", len(f.Labels), MaxLabels)
	}
	seen := map[string]bool{}
	for i, l := range f.Labels {
		where := fmt.Sprintf("label %d", i+1)
		if l.Name == "" || len(l.Name) > maxNameLen || strings.TrimSpace(l.Name) != l.Name {
			return nil, fmt.Errorf("%s: name %q is empty, too long or padded", where, l.Name)
		}
		if !colorRe.MatchString(l.Color) {
			return nil, fmt.Errorf("%s (%s): color %q is not six hex digits", where, l.Name, l.Color)
		}
		if len([]rune(l.Description)) > maxDescLen {
			return nil, fmt.Errorf("%s (%s): description longer than %d characters", where, l.Name, maxDescLen)
		}
		k := strings.ToLower(l.Name)
		if seen[k] {
			return nil, fmt.Errorf("%s: %q listed twice (label names ignore case)", where, l.Name)
		}
		seen[k] = true
	}
	return f.Labels, nil
}

// ReleasePrefix starts the release labels a repository may keep as its own.
const ReleasePrefix = "release:"

// OwnRelease reads labels.json's own_release_labels: the repositories that
// keep their own release:* labels (AntHocNet, CONTRIBUTING's label table),
// keyed by lower-case name (GitHub's names ignore case; #998).
func OwnRelease(data []byte) (map[string]bool, error) {
	var f struct {
		Own []string `json:"own_release_labels"`
	}
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, err
	}
	if len(f.Own) > MaxRepos {
		return nil, fmt.Errorf("own_release_labels has %d repositories (at most %d)", len(f.Own), MaxRepos)
	}
	out := map[string]bool{}
	for _, n := range f.Own {
		if !repoRe.MatchString(n) {
			return nil, fmt.Errorf("own_release_labels: %q is not a repository name", n)
		}
		out[strings.ToLower(n)] = true
	}
	return out, nil
}

// withoutRelease is want less its release:* labels.
func withoutRelease(want []Label) []Label {
	var out []Label
	for _, l := range want {
		if !strings.HasPrefix(strings.ToLower(l.Name), ReleasePrefix) {
			out = append(out, l)
		}
	}
	return out
}

// GitHub is the REST client: base URL, token, HTTP client, and the wait a
// rate-limit answer asks for (nil: time.Sleep; tests inject their own).
type GitHub struct {
	API    string
	Token  string
	Client *http.Client
	Sleep  func(time.Duration)
}

// MaxCooldown bounds the wait after a rate-limit answer; the request is then
// retried once. A longer cooldown, or a retry rate-limited again, stops the
// run (ErrRateLimited): no request goes out before GitHub allows it, and
// the next run (weekly, or the next labels.json change) starts over.
const MaxCooldown = 60 * time.Second

// ErrRateLimited is returned when GitHub's cooldown cannot be waited out.
var ErrRateLimited = errors.New("rate limited")

func (g GitHub) do(method, path string, body any) ([]byte, error) {
	var payload []byte
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		payload = b
	}
	for attempt := 1; ; attempt++ {
		data, wait, err := g.once(method, path, payload)
		if wait == 0 {
			return data, err
		}
		if attempt == 2 || wait > MaxCooldown {
			return nil, fmt.Errorf("%w (cooldown %s): %v", ErrRateLimited, wait.Round(time.Second), err)
		}
		if g.Sleep != nil {
			g.Sleep(wait)
		} else {
			time.Sleep(wait)
		}
	}
}

// once sends one request. A rate-limit answer (429, or 403 with Retry-After
// or no requests left) returns the cooldown to wait before a retry.
func (g GitHub) once(method, path string, payload []byte) ([]byte, time.Duration, error) {
	var rd io.Reader
	if payload != nil {
		rd = bytes.NewReader(payload)
	}
	req, err := http.NewRequest(method, g.API+"/"+path, rd)
	if err != nil {
		return nil, 0, fmt.Errorf("%s: building the request failed", method)
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "swarm-routing-labels")
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := g.Client.Do(req)
	if err != nil {
		// a *url.Error names the URL, which may name a private repository:
		// keep only the cause
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		msg := err.Error()
		if g.Token != "" {
			msg = strings.ReplaceAll(msg, g.Token, "[redacted]")
		}
		return nil, 0, fmt.Errorf("%s: %s", method, msg)
	}
	defer resp.Body.Close()
	var wait time.Duration
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		wait = cooldown(resp) // from the headers, even when the body cannot be read
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxBodySize))
	if err != nil {
		return nil, wait, fmt.Errorf("%s: HTTP %d: reading the answer failed", method, resp.StatusCode)
	}
	if resp.StatusCode >= 200 && resp.StatusCode <= 299 {
		return data, 0, nil
	}
	// the message only: the path may name a private repository
	var m struct {
		Message string `json:"message"`
	}
	_ = json.Unmarshal(data, &m)
	if len(m.Message) > 120 {
		m.Message = m.Message[:120]
	}
	return nil, wait, fmt.Errorf("%s: HTTP %d %s", method, resp.StatusCode, m.Message)
}

// cooldown is the wait a rate-limit answer asks for (at least a second;
// MaxCooldown when it names none), else 0.
func cooldown(resp *http.Response) time.Duration {
	ra := resp.Header.Get("Retry-After")
	left := resp.Header.Get("X-RateLimit-Remaining")
	limited := resp.StatusCode == http.StatusTooManyRequests ||
		(resp.StatusCode == http.StatusForbidden && (ra != "" || left == "0"))
	if !limited {
		return 0
	}
	d := MaxCooldown
	if n, err := strconv.Atoi(ra); err == nil && n >= 0 {
		d = time.Duration(n) * time.Second
	} else if reset, err := strconv.ParseInt(resp.Header.Get("X-RateLimit-Reset"), 10, 64); err == nil {
		d = time.Until(time.Unix(reset, 0))
	}
	if d < time.Second {
		d = time.Second
	}
	return d
}

// pages GETs path page by page (per_page=100) into decode until a short page.
func (g GitHub) pages(path string, decode func([]byte) (int, error)) error {
	sep := "?"
	if strings.Contains(path, "?") {
		sep = "&"
	}
	for page := 1; page <= maxPages; page++ {
		data, err := g.do("GET", fmt.Sprintf("%s%sper_page=%d&page=%d", path, sep, perPage, page), nil)
		if err != nil {
			return err
		}
		n, err := decode(data)
		if err != nil {
			return err
		}
		if n < perPage {
			return nil
		}
	}
	return fmt.Errorf("more than %d pages", maxPages)
}

// Repo is an org repository the labels go to. OwnRelease: it keeps its own
// release:* labels, so none is created or updated there (#998).
type Repo struct {
	Name       string
	Private    bool
	OwnRelease bool
}

// Repos lists the org's repositories that are neither archived nor disabled,
// sorted by name (a private one only when the token can see it).
func (g GitHub) Repos() ([]Repo, error) {
	var out []Repo
	err := g.pages("orgs/"+Org+"/repos?type=all&sort=full_name", func(data []byte) (int, error) {
		var rs []struct {
			Name     string `json:"name"`
			Private  bool   `json:"private"`
			Archived bool   `json:"archived"`
			Disabled bool   `json:"disabled"`
		}
		if err := json.Unmarshal(data, &rs); err != nil {
			return 0, err
		}
		for _, r := range rs {
			if r.Archived || r.Disabled || !repoRe.MatchString(r.Name) {
				continue
			}
			out = append(out, Repo{Name: r.Name, Private: r.Private})
		}
		if len(out) > MaxRepos {
			return 0, fmt.Errorf("more than %d repositories", MaxRepos)
		}
		return len(rs), nil
	})
	if err != nil {
		return nil, fmt.Errorf("listing the org's repositories: %v", err)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

func (g GitHub) labels(repo string) ([]Label, error) {
	var out []Label
	err := g.pages("repos/"+Org+"/"+repo+"/labels", func(data []byte) (int, error) {
		var ls []Label
		if err := json.Unmarshal(data, &ls); err != nil {
			return 0, err
		}
		out = append(out, ls...)
		return len(ls), nil
	})
	return out, err
}

// Change is one write a repository needs.
type Change struct {
	Label Label
	From  string // the current name, for an update; empty for a create
}

// Plan compares a repository's labels with the taxonomy: what to create and
// what to update. Labels the taxonomy does not name are left alone.
func Plan(want, have []Label) []Change {
	cur := map[string]Label{}
	for _, l := range have {
		cur[strings.ToLower(l.Name)] = l
	}
	var out []Change
	for _, w := range want {
		h, ok := cur[strings.ToLower(w.Name)]
		switch {
		case !ok:
			out = append(out, Change{Label: w})
		case h.Name != w.Name || !strings.EqualFold(h.Color, w.Color) || h.Description != w.Description:
			out = append(out, Change{Label: w, From: h.Name})
		}
	}
	return out
}

func (g GitHub) apply(repo string, c Change) error {
	if c.From == "" {
		_, err := g.do("POST", "repos/"+Org+"/"+repo+"/labels", map[string]string{
			"name": c.Label.Name, "color": strings.ToLower(c.Label.Color), "description": c.Label.Description,
		})
		return err
	}
	_, err := g.do("PATCH", "repos/"+Org+"/"+repo+"/labels/"+url.PathEscape(c.From), map[string]string{
		"new_name": c.Label.Name, "color": strings.ToLower(c.Label.Color), "description": c.Label.Description,
	})
	return err
}

func names(cs []Change) string {
	var n []string
	for _, c := range cs {
		n = append(n, c.Label.Name)
	}
	return strings.Join(n, ", ")
}

// Run applies want to every repository in repos, one line per repository. It
// tries every repository and returns an error when any of them failed.
func Run(g GitHub, want []Label, repos []Repo, dry bool, out io.Writer) error {
	failed := 0
	var mask repomask.Masker
	for _, r := range repos {
		name := mask.Repo(Org+"/"+r.Name, r.Private, Org+"/"+r.Name, r.Name)
		have, err := g.labels(r.Name)
		if err != nil {
			fmt.Fprintf(out, "%s: error: reading its labels: %v\n", name, mask.Error(err))
			failed++
			if errors.Is(err, ErrRateLimited) {
				return fmt.Errorf("stopped at %s: %w", name, mask.Error(err))
			}
			continue
		}
		w := want
		if r.OwnRelease {
			w = withoutRelease(want)
		}
		plan := Plan(w, have)
		var created, updated []Change
		for _, c := range plan {
			if c.From == "" {
				created = append(created, c)
			} else {
				updated = append(updated, c)
			}
		}
		if len(plan) == 0 {
			fmt.Fprintf(out, "%s: up to date (%d labels)\n", name, len(w))
			continue
		}
		if dry {
			fmt.Fprintf(out, "%s: dry run: would create %d [%s], update %d [%s]\n",
				name, len(created), names(created), len(updated), names(updated))
			continue
		}
		bad := 0
		for _, c := range plan {
			if err := g.apply(r.Name, c); err != nil {
				fmt.Fprintf(out, "%s: error: %s: %v\n", name, c.Label.Name, mask.Error(err))
				if errors.Is(err, ErrRateLimited) {
					return fmt.Errorf("stopped at %s: %w", name, mask.Error(err))
				}
				bad++
			}
		}
		if bad > 0 {
			failed++
		}
		fmt.Fprintf(out, "%s: created %d [%s], updated %d [%s], %d failed\n",
			name, len(created), names(created), len(updated), names(updated), bad)
	}
	if failed > 0 {
		return fmt.Errorf("%d of %d repositories failed", failed, len(repos))
	}
	return nil
}

// Main is the command: labels [--labels FILE] [--repos a,b] [--dry-run].
// GH_TOKEN: Issues write on every repository (the org App's installation
// token); without one it is a dry run over the repositories it can read.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	file, only, dry := "labels.json", "", false
	usage := "usage: labels [--labels FILE] [--repos a,b] [--dry-run]"
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case (a == "--labels" || a == "--repos") && i+1 < len(args):
			if a == "--labels" {
				file = args[i+1]
			} else {
				only = args[i+1]
			}
			i++
		default:
			fmt.Fprintln(stderr, usage)
			return 2
		}
	}
	path, err := inside(file)
	if err != nil {
		fmt.Fprintln(stderr, "labels:", err)
		return 2
	}
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintln(stderr, "labels:", err)
		return 2
	}
	want, err := Load(data)
	if err != nil {
		fmt.Fprintf(stderr, "labels: %s: %v\n", file, err)
		return 2
	}
	own, err := OwnRelease(data)
	if err != nil {
		fmt.Fprintf(stderr, "labels: %s: %v\n", file, err)
		return 2
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "labels: no GH_TOKEN: dry run")
		dry = true
	}
	g := GitHub{API: api, Token: token, Client: client}
	repos, err := g.Repos()
	if err != nil {
		fmt.Fprintln(stderr, "labels:", err)
		return 1
	}
	if only != "" {
		repos, err = pick(repos, only)
		if err != nil {
			fmt.Fprintln(stderr, "labels:", err)
			return 2
		}
	}
	for i := range repos {
		repos[i].OwnRelease = own[strings.ToLower(repos[i].Name)]
	}
	if len(repos) == 0 {
		fmt.Fprintln(stderr, "labels: no repository to apply to")
		return 1
	}
	if err := Run(g, want, repos, dry, stdout); err != nil {
		fmt.Fprintln(stderr, "labels:", err)
		return 1
	}
	return 0
}

// pick keeps the named repositories; a name the org listing lacks is an error.
func pick(repos []Repo, only string) ([]Repo, error) {
	by := map[string]Repo{}
	for _, r := range repos {
		by[r.Name] = r
	}
	var out []Repo
	seen := map[string]bool{}
	for _, n := range strings.Split(only, ",") {
		n = strings.TrimSpace(n)
		if n == "" || seen[n] {
			continue
		}
		seen[n] = true
		r, ok := by[n]
		if !ok {
			return nil, fmt.Errorf("--repos: %q is not a repository this token sees in %s", n, Org)
		}
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

// inside is a relative path within the working directory.
func inside(p string) (string, error) {
	if filepath.IsAbs(p) {
		return "", errors.New("--labels is a path relative to the working directory")
	}
	c := filepath.Clean(p)
	if c == ".." || strings.HasPrefix(c, "../") {
		return "", errors.New("--labels is outside the working directory")
	}
	return c, nil
}
