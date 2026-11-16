// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package backstop dispatches a scheduled workflow whose own schedule did not run:
// for each entry of a table (repository, workflow, period, inputs), when no run of
// the workflow on its repository's default branch started within the period, less a
// slack, it sends workflow_dispatch with the entry's inputs. Running it on a
// schedule that fires (this repository's) keeps another repository's pipelines on
// time when GitHub fires none of its schedules
// (swarm-routing/ns3-upstream-report#33). It only reads runs and dispatches; it is
// idempotent within a period: a run of either kind makes it skip.
package backstop

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
	"strings"
	"time"

	"github.com/BurntSushi/toml"
)

// Slack is taken off each period, so a backstop that runs every hour still
// dispatches an hourly workflow every hour despite the jitter of its own start.
const Slack = 10 * time.Minute

// MaxEntries bounds the table (golden rule 7).
const MaxEntries = 64

// Entry is one row of the table.
type Entry struct {
	Repo     string            `toml:"repo"`
	Workflow string            `toml:"workflow"`
	Period   string            `toml:"period"`
	Inputs   map[string]string `toml:"inputs"`

	period time.Duration
}

var (
	repoRe     = regexp.MustCompile(`^swarm-routing/[A-Za-z0-9_.-]+$`)
	workflowRe = regexp.MustCompile(`^[A-Za-z0-9_.-]+\.ya?ml$`)
	inputRe    = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)
)

// Load reads and checks the table.
func Load(data []byte) ([]Entry, error) {
	var t struct {
		Entry []Entry `toml:"entry"`
	}
	md, err := toml.Decode(string(data), &t)
	if err != nil {
		return nil, err
	}
	if und := md.Undecoded(); len(und) > 0 {
		return nil, fmt.Errorf("unknown key %s", und[0])
	}
	if len(t.Entry) == 0 || len(t.Entry) > MaxEntries {
		return nil, fmt.Errorf("the table has %d entries (1 to %d)", len(t.Entry), MaxEntries)
	}
	seen := map[string]bool{}
	for i := range t.Entry {
		e := &t.Entry[i]
		where := fmt.Sprintf("entry %d", i+1)
		if !repoRe.MatchString(e.Repo) {
			return nil, fmt.Errorf("%s: repo %q is not swarm-routing/<name>", where, e.Repo)
		}
		if !workflowRe.MatchString(e.Workflow) {
			return nil, fmt.Errorf("%s: workflow %q is not a workflow file name", where, e.Workflow)
		}
		d, err := time.ParseDuration(e.Period)
		if err != nil || d < time.Hour || d > 31*24*time.Hour {
			return nil, fmt.Errorf("%s: period %q is not a duration from 1h to 744h", where, e.Period)
		}
		e.period = d
		keys := make([]string, 0, len(e.Inputs))
		for k := range e.Inputs {
			keys = append(keys, k)
		}
		sort.Strings(keys) // the same table, the same diagnostic
		for _, k := range keys {
			if !inputRe.MatchString(k) || len(e.Inputs[k]) > 200 {
				return nil, fmt.Errorf("%s: input %q is not a plain name with a short value", where, k)
			}
		}
		key := e.Repo + " " + e.Workflow
		if seen[key] {
			return nil, fmt.Errorf("%s: %s listed twice", where, key)
		}
		seen[key] = true
	}
	return t.Entry, nil
}

// GitHub is the REST client: base URL, token, HTTP client.
type GitHub struct {
	API    string
	Token  string
	Client *http.Client
}

func (g GitHub) do(method, path string, body any) ([]byte, int, error) {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, 0, err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, g.API+"/"+path, rd)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", "swarm-routing-backstop")
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := g.Client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("%s %s: %v", method, path, strings.ReplaceAll(err.Error(), g.Token, "[redacted]"))
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg := string(data)
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return nil, resp.StatusCode, fmt.Errorf("%s %s: HTTP %d: %s", method, path, resp.StatusCode, msg)
	}
	return data, resp.StatusCode, nil
}

// defaultBranch is the repository's default branch.
func (g GitHub) defaultBranch(repo string) (string, error) {
	data, _, err := g.do("GET", "repos/"+repo, nil)
	if err != nil {
		return "", err
	}
	var r struct {
		DefaultBranch string `json:"default_branch"`
	}
	if err := json.Unmarshal(data, &r); err != nil || r.DefaultBranch == "" {
		return "", fmt.Errorf("repos/%s: no default branch", repo)
	}
	return r.DefaultBranch, nil
}

// lastRun is when the newest run of a workflow on branch started, a re-run included (zero: none).
func (g GitHub) lastRun(repo, workflow, branch string) (time.Time, string, error) {
	data, _, err := g.do("GET", fmt.Sprintf("repos/%s/actions/workflows/%s/runs?branch=%s&per_page=1",
		repo, workflow, url.QueryEscape(branch)), nil)
	if err != nil {
		return time.Time{}, "", err
	}
	var r struct {
		Runs []struct {
			CreatedAt    time.Time `json:"created_at"`
			RunStartedAt time.Time `json:"run_started_at"`
			Event        string    `json:"event"`
		} `json:"workflow_runs"`
	}
	if err := json.Unmarshal(data, &r); err != nil {
		return time.Time{}, "", err
	}
	if len(r.Runs) == 0 {
		return time.Time{}, "", nil
	}
	// a re-run keeps its created_at and resets run_started_at: the later of the two
	t := r.Runs[0].CreatedAt
	if r.Runs[0].RunStartedAt.After(t) {
		t = r.Runs[0].RunStartedAt
	}
	return t, r.Runs[0].Event, nil
}

func (g GitHub) dispatch(repo, workflow, ref string, inputs map[string]string) error {
	body := map[string]any{"ref": ref}
	if len(inputs) > 0 {
		body["inputs"] = inputs
	}
	_, _, err := g.do("POST", fmt.Sprintf("repos/%s/actions/workflows/%s/dispatches", repo, workflow), body)
	return err
}

func inputsText(in map[string]string) string {
	keys := make([]string, 0, len(in))
	for k := range in {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		parts = append(parts, k+"="+in[k])
	}
	if len(parts) == 0 {
		return "no inputs"
	}
	return strings.Join(parts, " ")
}

// Run checks every entry and dispatches what is due; one line per entry. It tries
// every entry and returns an error when any of them failed.
func Run(g GitHub, entries []Entry, now time.Time, dry bool, out io.Writer) error {
	failed := 0
	branches := map[string]string{}
	for _, e := range entries {
		name := e.Repo + " " + e.Workflow
		br, ok := branches[e.Repo]
		if !ok {
			b, err := g.defaultBranch(e.Repo)
			if err != nil {
				fmt.Fprintf(out, "%s: error: %v\n", name, err)
				failed++
				continue
			}
			br, branches[e.Repo] = b, b
		}
		last, event, err := g.lastRun(e.Repo, e.Workflow, br)
		if err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", name, err)
			failed++
			continue
		}
		window := e.period - Slack
		if !last.IsZero() && now.Sub(last) < window {
			fmt.Fprintf(out, "%s: last run %s (%s, %s ago), within %s: nothing to do\n",
				name, last.UTC().Format(time.RFC3339), event, now.Sub(last).Truncate(time.Minute), e.Period)
			continue
		}
		since := "no run yet"
		if !last.IsZero() {
			since = fmt.Sprintf("last run %s (%s, %s ago)", last.UTC().Format(time.RFC3339), event, now.Sub(last).Truncate(time.Minute))
		}
		if dry {
			fmt.Fprintf(out, "%s: %s: dry run: would dispatch on %s with %s\n", name, since, br, inputsText(e.Inputs))
			continue
		}
		if err := g.dispatch(e.Repo, e.Workflow, br, e.Inputs); err != nil {
			fmt.Fprintf(out, "%s: %s: dispatch failed: %v\n", name, since, err)
			failed++
			continue
		}
		fmt.Fprintf(out, "%s: %s: dispatched on %s with %s\n", name, since, br, inputsText(e.Inputs))
	}
	if failed > 0 {
		return fmt.Errorf("%d of %d entries failed", failed, len(entries))
	}
	return nil
}

// Main is the command: backstop [--config FILE] [--dry-run] [--now RFC3339].
// GH_TOKEN (needs Actions: write on each repository to dispatch; read to check).
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	config, dry, nowS := ".github/backstop.toml", false, ""
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case (a == "--config" || a == "--now") && i+1 < len(args):
			if a == "--config" {
				config = args[i+1]
			} else {
				nowS = args[i+1]
			}
			i++
		default:
			fmt.Fprintln(stderr, "usage: backstop [--config FILE] [--dry-run] [--now RFC3339]")
			return 2
		}
	}
	path, err := inside(config)
	if err != nil {
		fmt.Fprintln(stderr, "backstop:", err)
		return 2
	}
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintln(stderr, "backstop:", err)
		return 2
	}
	entries, err := Load(data)
	if err != nil {
		fmt.Fprintf(stderr, "backstop: %s: %v\n", config, err)
		return 2
	}
	now := time.Now().UTC()
	if nowS != "" {
		if now, err = time.Parse(time.RFC3339, nowS); err != nil {
			fmt.Fprintln(stderr, "backstop: --now:", err)
			return 2
		}
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "backstop: no GH_TOKEN: dry run")
		dry = true
	}
	g := GitHub{API: api, Token: token, Client: client}
	if err := Run(g, entries, now, dry, stdout); err != nil {
		fmt.Fprintln(stderr, "backstop:", err)
		return 1
	}
	return 0
}

// inside is a relative path within the working directory.
func inside(p string) (string, error) {
	if filepath.IsAbs(p) {
		return "", errors.New("--config is a path relative to the working directory")
	}
	c := filepath.Clean(p)
	if c == ".." || strings.HasPrefix(c, "../") {
		return "", errors.New("--config is outside the working directory")
	}
	return c, nil
}
