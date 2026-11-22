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
//
// An entry with a `title` counts only the runs of that run-name, never a
// cancelled one (a pending run another replaced did no work), so one workflow
// that runs for many reasons, org-bot.yml, has a row per scheduled task
// (swarm-routing/.github#748). An entry with an `alarm` is stalled when no
// such run completed within it: the line says so, the command exits 1, and
// with --issue it keeps one issue here open, listing the stalled rows, until
// every row has completed a run again.
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
	"strconv"
	"strings"
	"time"

	"github.com/BurntSushi/toml"

	"github.com/swarm-routing/.github/internal/repomask"
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
	// Title, when set: only runs whose run-name (display_title) is exactly this count.
	Title string `toml:"title"`
	// Alarm, when set: the row is stalled when no counted run completed within it.
	Alarm string `toml:"alarm"`

	period time.Duration
	alarm  time.Duration
}

// IssueRepo holds the stalled-schedule issue; IssueTitle is its title.
const (
	IssueRepo  = "swarm-routing/.github"
	IssueTitle = "[backstop] scheduled runs stalled"
)

// maxPages bounds a titled row's run listing (100 runs a page, newest first).
const maxPages = 10

var (
	titleRe    = regexp.MustCompile(`^[ -~]{1,100}$`)
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
		if e.Title != "" && !titleRe.MatchString(e.Title) {
			return nil, fmt.Errorf("%s: title %q is not 1 to 100 printable ASCII characters", where, e.Title)
		}
		if e.Alarm != "" {
			a, err := time.ParseDuration(e.Alarm)
			if err != nil || a < d || a > 31*24*time.Hour {
				return nil, fmt.Errorf("%s: alarm %q is not a duration from the period (%s) to 744h", where, e.Alarm, e.Period)
			}
			e.alarm = a
		}
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
		key := e.Repo + " " + e.Workflow + " " + e.Title
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

// repoInfo is the repository's default branch and whether it is private.
type repoInfo struct {
	DefaultBranch string `json:"default_branch"`
	Private       bool   `json:"private"`
}

// info reads the repository's default branch and visibility.
func (g GitHub) info(repo string) (repoInfo, error) {
	var r repoInfo
	data, _, err := g.do("GET", "repos/"+repo, nil)
	if err != nil {
		return r, err
	}
	if err := json.Unmarshal(data, &r); err != nil || r.DefaultBranch == "" {
		return r, fmt.Errorf("repos/%s: no default branch", repo)
	}
	return r, nil
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

// titled reads the runs on branch created since `since`, newest first, and
// returns the newest counted run's start and event and the newest counted
// completed run's end (zero: none). A counted run is not cancelled and, when
// title is set, has that run-name.
func (g GitHub) titled(repo, workflow, branch, title string, since time.Time) (time.Time, string, time.Time, error) {
	var started, done time.Time
	event := ""
	for page := 1; page <= maxPages; page++ {
		data, _, err := g.do("GET", fmt.Sprintf("repos/%s/actions/workflows/%s/runs?branch=%s&created=%s&per_page=100&page=%d",
			repo, workflow, url.QueryEscape(branch), url.QueryEscape(">="+since.UTC().Format(time.RFC3339)), page), nil)
		if err != nil {
			return started, event, done, err
		}
		var r struct {
			Runs []struct {
				CreatedAt    time.Time `json:"created_at"`
				RunStartedAt time.Time `json:"run_started_at"`
				UpdatedAt    time.Time `json:"updated_at"`
				Event        string    `json:"event"`
				Status       string    `json:"status"`
				Conclusion   string    `json:"conclusion"`
				Title        string    `json:"display_title"`
			} `json:"workflow_runs"`
		}
		if err := json.Unmarshal(data, &r); err != nil {
			return started, event, done, err
		}
		for _, run := range r.Runs {
			if run.Conclusion == "cancelled" || (title != "" && run.Title != title) {
				continue
			}
			if started.IsZero() {
				started, event = run.CreatedAt, run.Event
				if run.RunStartedAt.After(started) {
					started = run.RunStartedAt
				}
			}
			if done.IsZero() && run.Status == "completed" {
				done = run.UpdatedAt
			}
			if !done.IsZero() {
				return started, event, done, nil
			}
		}
		if len(r.Runs) < 100 {
			break
		}
	}
	return started, event, done, nil
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
// every entry and returns an error when any of them failed, and the lines of
// the rows with an alarm that are stalled. A private repository is printed as
// "private repository N" (the log is public) and its name is scrubbed from
// every error.
func Run(g GitHub, entries []Entry, now time.Time, dry bool, out io.Writer) ([]string, error) {
	failed := 0
	var stalled []string
	repos := map[string]repoInfo{}
	var mask repomask.Masker
	for _, e := range entries {
		ri, ok := repos[e.Repo]
		if !ok {
			r, err := g.info(e.Repo)
			if err != nil {
				fmt.Fprintf(out, "%s %s: error: %v\n", e.Repo, e.Workflow, err)
				failed++
				continue
			}
			ri, repos[e.Repo] = r, r
		}
		br := ri.DefaultBranch
		name := mask.Repo(e.Repo, ri.Private, e.Repo, strings.TrimPrefix(e.Repo, "swarm-routing/")) + " " + e.Workflow
		var last, done time.Time
		var event string
		var err error
		if e.Title == "" && e.alarm == 0 {
			last, event, err = g.lastRun(e.Repo, e.Workflow, br)
		} else {
			if e.Title != "" {
				name += " " + strconv.Quote(e.Title)
			}
			look := e.period
			if e.alarm > look {
				look = e.alarm
			}
			last, event, done, err = g.titled(e.Repo, e.Workflow, br, e.Title, now.Add(-look-time.Hour))
		}
		if err != nil {
			fmt.Fprintf(out, "%s: error: %v\n", name, mask.Error(err))
			failed++
			continue
		}
		if e.alarm > 0 && (done.IsZero() || now.Sub(done) > e.alarm) {
			ended := "none within " + e.Alarm
			if !done.IsZero() {
				ended = fmt.Sprintf("the last ended %s, %s ago", done.UTC().Format(time.RFC3339), now.Sub(done).Truncate(time.Minute))
			}
			line := fmt.Sprintf("%s: stalled: no run completed within %s (%s)", name, e.Alarm, ended)
			fmt.Fprintln(out, line)
			stalled = append(stalled, line)
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
			fmt.Fprintf(out, "%s: %s: dispatch failed: %v\n", name, since, mask.Error(err))
			failed++
			continue
		}
		fmt.Fprintf(out, "%s: %s: dispatched on %s with %s\n", name, since, br, inputsText(e.Inputs))
	}
	if failed > 0 {
		return stalled, fmt.Errorf("%d of %d entries failed", failed, len(entries))
	}
	return stalled, nil
}

// issue is the part of an issue read.
type issue struct {
	Number int             `json:"number"`
	Title  string          `json:"title"`
	Body   string          `json:"body"`
	PR     json.RawMessage `json:"pull_request"`
}

// IssueBody is the stalled-schedule issue's body for the stalled lines.
func IssueBody(stalled []string, now time.Time) string {
	var b strings.Builder
	b.WriteString("The schedule backstop (`cmd/backstop`, `.github/backstop.toml`) found rows whose " +
		"workflow completed no counted run within the row's `alarm` (swarm-routing/.github#748). " +
		"It dispatches each due row on every run; this issue stays open, updated in place, until " +
		"every row has completed a run again, and then it is closed.\n\n")
	fmt.Fprintf(&b, "Checked %s:\n\n", now.UTC().Format(time.RFC3339))
	for _, l := range stalled {
		b.WriteString("- " + l + "\n")
	}
	b.WriteString("\nWhere to look: the workflow's run list (a pending run that another replaced shows " +
		"as cancelled with no job), its concurrency groups, and the backstop's own run summary.\n")
	return b.String()
}

// KeepIssue opens or updates the stalled-schedule issue while rows are stalled,
// and closes it, with a comment, once none is; one line of what it did.
func KeepIssue(g GitHub, stalled []string, now time.Time, dry bool) (string, error) {
	var open *issue
	for page := 1; page <= maxPages && open == nil; page++ {
		data, _, err := g.do("GET", fmt.Sprintf("repos/%s/issues?state=open&labels=ci&per_page=100&page=%d", IssueRepo, page), nil)
		if err != nil {
			return "", err
		}
		var got []issue
		if err := json.Unmarshal(data, &got); err != nil {
			return "", err
		}
		for i := range got {
			if got[i].Title == IssueTitle && len(got[i].PR) == 0 {
				open = &got[i]
				break
			}
		}
		if len(got) < 100 {
			break
		}
	}
	if len(stalled) == 0 {
		if open == nil {
			return "issue: none open, nothing stalled", nil
		}
		if dry {
			return fmt.Sprintf("issue: dry run: would close #%d", open.Number), nil
		}
		msg := fmt.Sprintf("Every row with an alarm completed a run within it again (checked %s); closing.\n\n"+
			"---\n_Generated by the schedule backstop (`cmd/backstop`)._", now.UTC().Format(time.RFC3339))
		if _, _, err := g.do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", IssueRepo, open.Number), map[string]any{"body": msg}); err != nil {
			return "", err
		}
		if _, _, err := g.do("PATCH", fmt.Sprintf("repos/%s/issues/%d", IssueRepo, open.Number),
			map[string]any{"state": "closed", "state_reason": "completed"}); err != nil {
			return "", err
		}
		return fmt.Sprintf("issue: closed #%d", open.Number), nil
	}
	body := IssueBody(stalled, now)
	if open != nil {
		// the check time alone changing is no update: compare without it
		if strip(open.Body) == strip(body) {
			return fmt.Sprintf("issue: #%d unchanged", open.Number), nil
		}
		if dry {
			return fmt.Sprintf("issue: dry run: would update #%d", open.Number), nil
		}
		_, _, err := g.do("PATCH", fmt.Sprintf("repos/%s/issues/%d", IssueRepo, open.Number), map[string]any{"body": body})
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("issue: updated #%d", open.Number), nil
	}
	if dry {
		return "issue: dry run: would open it", nil
	}
	data, _, err := g.do("POST", fmt.Sprintf("repos/%s/issues", IssueRepo), map[string]any{
		"title": IssueTitle, "body": body, "labels": []string{"bug", "ci", "priority:P1"}})
	if err != nil {
		return "", err
	}
	var got issue
	_ = json.Unmarshal(data, &got)
	return fmt.Sprintf("issue: opened #%d", got.Number), nil
}

var checkedRe = regexp.MustCompile(`(?m)^Checked [^\n]*:$`)

// strip removes the check time and the stalled-since ages, which change on every run.
func strip(body string) string {
	body = checkedRe.ReplaceAllString(body, "")
	return agoRe.ReplaceAllString(body, "")
}

var agoRe = regexp.MustCompile(`the last ended [^)]*`)

// Main is the command: backstop [--config FILE] [--issue] [--dry-run] [--now RFC3339].
// GH_TOKEN (needs Actions: write on each repository to dispatch; read to check;
// with --issue, Issues: write here). It exits 1 when a row failed or is stalled.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	config, dry, keep, nowS := ".github/backstop.toml", false, false, ""
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case a == "--issue":
			keep = true
		case (a == "--config" || a == "--now") && i+1 < len(args):
			if a == "--config" {
				config = args[i+1]
			} else {
				nowS = args[i+1]
			}
			i++
		default:
			fmt.Fprintln(stderr, "usage: backstop [--config FILE] [--issue] [--dry-run] [--now RFC3339]")
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
	stalled, err := Run(g, entries, now, dry, stdout)
	code := 0
	if err != nil {
		fmt.Fprintln(stderr, "backstop:", err)
		code = 1
	}
	// the issue follows the alarms only when every row was read: a read error
	// is no evidence that a stalled row recovered
	if keep && err == nil {
		line, ierr := KeepIssue(g, stalled, now, dry)
		if ierr != nil {
			fmt.Fprintln(stderr, "backstop: issue:", ierr)
			code = 1
		} else {
			fmt.Fprintln(stdout, line)
		}
	}
	if len(stalled) > 0 {
		fmt.Fprintf(stderr, "backstop: %d row(s) stalled\n", len(stalled))
		code = 1
	}
	return code
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
