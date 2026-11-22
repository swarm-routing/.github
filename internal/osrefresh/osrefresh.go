// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package osrefresh decides when a repository's published images get an OS
// security refresh (swarm-routing/sim-containers#218). It reads Trivy's JSON
// reports of the images' rolling tags and counts the vulnerabilities of OS
// packages with a fix available, MEDIUM or higher (the threshold of the
// images' own security stage). When there is one, it dispatches the existing
// refresh path, the image workflow's `workflow_dispatch` with `refresh=true`
// on main, never a second build path, unless a run of that workflow is
// active on main (a third run would replace the pending one in its
// concurrency group) or a dispatch of it already ran today (UTC): at most one
// refresh a day.
//
// It also reports on the last automated refresh, the newest completed
// dispatch of the workflow by the bot (`--actor`, else the token's user):
// a failed one opens, or comments its run link on, one open issue titled
// IssueTitle; a successful one closes that issue. Its output is the run's
// summary, Markdown: the fixable findings per image, the distinct CVEs by
// severity (what the refresh fixes), and what it did. `--dry-run` reads and
// prints what it would do; nothing is written.
package osrefresh

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/github"
)

const (
	// Workflow is the image workflow whose refresh input is dispatched.
	Workflow = "publish-images.yml"
	// Branch is where the refresh runs (it promotes only there).
	Branch = "main"
	// IssueTitle is the one issue a failed automated refresh opens or updates.
	IssueTitle = "OS security refresh failed"
	// Window is how far back runs are read: the last automated refresh.
	Window = 7 * 24 * time.Hour
	// maxPages bounds every listing (100 items a page).
	maxPages = 10
	// maxReports bounds the reports read in one run.
	maxReports = 64
	// maxReport bounds the bytes read from one report.
	maxReport = 64 << 20
	// maxListed bounds the CVE identifiers printed in the summary.
	maxListed = 200
)

// Severities are the ones that trigger a refresh, highest first.
var Severities = []string{"CRITICAL", "HIGH", "MEDIUM"}

var repoRe = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)

func rank(sev string) int {
	for i, s := range Severities {
		if s == sev {
			return len(Severities) - i
		}
	}
	return 0
}

// Image is one report's fixable findings.
type Image struct {
	Name  string
	OS    map[string]int    // severity -> fixable OS-package findings
	Other int               // fixable findings MEDIUM or higher outside OS packages
	CVEs  map[string]string // fixable OS CVE -> its severity
}

type trivyReport struct {
	ArtifactName string `json:"ArtifactName"`
	Results      []struct {
		Target          string `json:"Target"`
		Class           string `json:"Class"`
		Vulnerabilities []struct {
			ID           string `json:"VulnerabilityID"`
			Pkg          string `json:"PkgName"`
			FixedVersion string `json:"FixedVersion"`
			Status       string `json:"Status"`
			Severity     string `json:"Severity"`
		} `json:"Vulnerabilities"`
	} `json:"Results"`
}

// Parse reads one Trivy JSON report (`trivy image --format json`).
func Parse(r io.Reader, fallback string) (Image, error) {
	data, err := io.ReadAll(io.LimitReader(r, maxReport+1))
	if err != nil {
		return Image{}, err
	}
	if len(data) > maxReport {
		return Image{}, fmt.Errorf("larger than %d bytes", maxReport)
	}
	var rep trivyReport
	if err := json.Unmarshal(data, &rep); err != nil {
		return Image{}, fmt.Errorf("not a Trivy JSON report: %v", err)
	}
	img := Image{Name: rep.ArtifactName, OS: map[string]int{}, CVEs: map[string]string{}}
	if img.Name == "" {
		img.Name = fallback
	}
	for _, res := range rep.Results {
		for _, v := range res.Vulnerabilities {
			sev := strings.ToUpper(v.Severity)
			if rank(sev) == 0 || (v.FixedVersion == "" && v.Status != "fixed") {
				continue
			}
			if res.Class != "os-pkgs" {
				img.Other++
				continue
			}
			img.OS[sev]++
			if old, ok := img.CVEs[v.ID]; !ok || rank(sev) > rank(old) {
				img.CVEs[v.ID] = sev
			}
		}
	}
	return img, nil
}

// Fixable is how many fixable OS findings the image has.
func (i Image) Fixable() int {
	n := 0
	for _, c := range i.OS {
		n += c
	}
	return n
}

// Distinct is every image's fixable OS CVEs, each at the highest severity a report gave it.
func Distinct(images []Image) map[string]string {
	all := map[string]string{}
	for _, img := range images {
		for id, sev := range img.CVEs {
			if old, ok := all[id]; !ok || rank(sev) > rank(old) {
				all[id] = sev
			}
		}
	}
	return all
}

// GitHub is the REST client: base URL, token, HTTP client.
type GitHub struct {
	API    string
	Token  string
	Client *http.Client
}

func (g GitHub) rest() github.Client {
	return github.Client{API: g.API, Token: g.Token, UserAgent: "swarm-routing-os-refresh", HTTP: g.Client}
}

// Run is one run of the image workflow.
type Run struct {
	ID         int64     `json:"id"`
	Event      string    `json:"event"`
	Status     string    `json:"status"`
	Conclusion string    `json:"conclusion"`
	CreatedAt  time.Time `json:"created_at"`
	HTMLURL    string    `json:"html_url"`
	Actor      struct {
		Login string `json:"login"`
	} `json:"triggering_actor"`
}

func (r Run) active() bool {
	switch r.Status {
	case "queued", "in_progress", "waiting", "requested", "pending":
		return true
	}
	return false
}

func (r Run) failed() bool {
	switch r.Conclusion {
	case "failure", "cancelled", "timed_out", "startup_failure":
		return true
	}
	return false
}

func (r Run) state() string {
	if r.Status == "completed" {
		return r.Conclusion
	}
	return r.Status
}

func (g GitHub) runs(repo string, now time.Time) ([]Run, error) {
	since := now.Add(-Window).Format("2006-01-02")
	path := fmt.Sprintf("repos/%s/actions/workflows/%s/runs?branch=%s&created=%s", repo, Workflow, Branch,
		url.QueryEscape(">="+since))
	var all []Run
	for page := 1; page <= maxPages; page++ {
		data, err := g.rest().Do("GET", fmt.Sprintf("%s&per_page=100&page=%d", path, page), nil)
		if err != nil {
			return nil, err
		}
		var got struct {
			Runs []Run `json:"workflow_runs"`
		}
		if err := json.Unmarshal(data, &got); err != nil {
			return nil, fmt.Errorf("GET %s: %v", path, err)
		}
		all = append(all, got.Runs...)
		if len(got.Runs) < 100 {
			break
		}
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].CreatedAt.After(all[j].CreatedAt) })
	return all, nil
}

type issue struct {
	Number  int    `json:"number"`
	Title   string `json:"title"`
	Body    string `json:"body"`
	HTMLURL string `json:"html_url"`
	PR      *struct {
		URL string `json:"url"`
	} `json:"pull_request"`
}

func (g GitHub) openIssue(repo string) (*issue, error) {
	got, err := github.List[issue](g.rest(), "repos/"+repo+"/issues?state=open&labels=bug", maxPages)
	if err != nil {
		return nil, err
	}
	for i := range got {
		if got[i].PR == nil && strings.TrimSpace(got[i].Title) == IssueTitle {
			return &got[i], nil
		}
	}
	return nil, nil
}

// mentions is whether the issue's body or a comment already names the run.
func (g GitHub) mentions(repo string, is *issue, runURL string) (bool, error) {
	if strings.Contains(is.Body, runURL) {
		return true, nil
	}
	got, err := github.List[struct {
		Body string `json:"body"`
	}](g.rest(), fmt.Sprintf("repos/%s/issues/%d/comments?sort=created", repo, is.Number), maxPages)
	if err != nil {
		return false, err
	}
	for _, c := range got {
		if strings.Contains(c.Body, runURL) {
			return true, nil
		}
	}
	return false, nil
}

func failureText(r Run) string {
	return fmt.Sprintf("The automated OS security refresh, run %d, ended `%s`: %s\n\n"+
		"Read its failed jobs. The next daily scan dispatches the refresh again while fixable "+
		"findings remain (at most one a day); this issue closes when an automated refresh succeeds.",
		r.ID, r.Conclusion, r.HTMLURL)
}

func issueBody(r Run) string {
	return "## Context\n\n" + failureText(r) + "\n\n" +
		"The daily `os-refresh.yml` scan of the rolling `latest-*` images found fixable OS " +
		"vulnerabilities (MEDIUM or higher) and dispatched `" + Workflow + "` with `refresh=true` on `" +
		Branch + "` (swarm-routing/sim-containers#218). Each later failure adds its run link here.\n\n" +
		"## Acceptance criteria\n\n- [ ] An automated refresh succeeds (the scan then closes this issue).\n"
}

// report handles the issue of the last automated refresh; it returns the summary lines.
func (g GitHub) report(repo string, last *Run, dry bool) ([]string, error) {
	if last == nil {
		return []string{"No automated refresh in the last 7 days."}, nil
	}
	lines := []string{fmt.Sprintf("Last automated refresh: run %d, %s, %s (%s).", last.ID,
		last.CreatedAt.UTC().Format(time.RFC3339), last.state(), last.HTMLURL)}
	is, err := g.openIssue(repo)
	if err != nil {
		return lines, err
	}
	switch {
	case last.failed() && is == nil:
		if dry {
			return append(lines, fmt.Sprintf("Dry run: would open the issue %q.", IssueTitle)), nil
		}
		body := map[string]any{"title": IssueTitle, "body": issueBody(*last),
			"labels": []string{"bug", "packaging", "priority:P2"}}
		data, err := g.rest().Do("POST", "repos/"+repo+"/issues", body)
		if err != nil {
			return lines, err
		}
		var made issue
		_ = json.Unmarshal(data, &made)
		return append(lines, fmt.Sprintf("Opened issue #%d.", made.Number)), nil
	case last.failed():
		seen, err := g.mentions(repo, is, last.HTMLURL)
		if err != nil {
			return lines, err
		}
		if seen {
			return append(lines, fmt.Sprintf("Issue #%d already names this run.", is.Number)), nil
		}
		if dry {
			return append(lines, fmt.Sprintf("Dry run: would comment the run on issue #%d.", is.Number)), nil
		}
		if _, err := g.rest().Do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", repo, is.Number),
			map[string]string{"body": failureText(*last)}); err != nil {
			return lines, err
		}
		return append(lines, fmt.Sprintf("Commented the run on issue #%d.", is.Number)), nil
	case last.Conclusion == "success" && is != nil:
		if dry {
			return append(lines, fmt.Sprintf("Dry run: would close issue #%d.", is.Number)), nil
		}
		text := fmt.Sprintf("The automated OS security refresh, run %d, succeeded: %s", last.ID, last.HTMLURL)
		if _, err := g.rest().Do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", repo, is.Number),
			map[string]string{"body": text}); err != nil {
			return lines, err
		}
		if _, err := g.rest().Do("PATCH", fmt.Sprintf("repos/%s/issues/%d", repo, is.Number),
			map[string]string{"state": "closed", "state_reason": "completed"}); err != nil {
			return lines, err
		}
		return append(lines, fmt.Sprintf("Closed issue #%d.", is.Number)), nil
	}
	return lines, nil
}

// Options is one run's settings.
type Options struct {
	Repo  string
	Actor string // the bot's login; empty: the token's user
	Dry   bool
	Now   time.Time
}

// Decide is what the scan does, given the runs (newest first) and whether a
// fixable finding exists: "" to dispatch, else why not.
func Decide(fixable bool, runs []Run, now time.Time) string {
	if !fixable {
		return "nothing to refresh: no fixable OS vulnerability of MEDIUM or higher"
	}
	for _, r := range runs {
		if r.active() {
			return fmt.Sprintf("waiting: %s run %d on %s is %s (%s)", Workflow, r.ID, Branch, r.Status, r.HTMLURL)
		}
	}
	day := now.UTC().Truncate(24 * time.Hour)
	for _, r := range runs {
		if r.Event == "workflow_dispatch" && !r.CreatedAt.Before(day) {
			return fmt.Sprintf("waiting: a dispatch of %s already ran today, run %d at %s (at most one refresh a day)",
				Workflow, r.ID, r.CreatedAt.UTC().Format(time.RFC3339))
		}
	}
	return ""
}

func (g GitHub) actor(o Options) string {
	if o.Actor != "" || g.Token == "" {
		return o.Actor
	}
	data, err := g.rest().Do("GET", "user", nil)
	if err != nil {
		return "" // an App installation token has no user: --actor names the App's bot
	}
	var u struct {
		Login string `json:"login"`
	}
	_ = json.Unmarshal(data, &u)
	return u.Login
}

// Scan is the whole run on the parsed reports; the summary goes to out.
func Scan(g GitHub, images []Image, o Options, out io.Writer) error {
	fmt.Fprintf(out, "### OS security refresh: `%s`\n\n", o.Repo)
	fmt.Fprintln(out, "| Image | CRITICAL | HIGH | MEDIUM | fixable outside OS packages |")
	fmt.Fprintln(out, "|---|---|---|---|---|")
	for _, img := range images {
		fmt.Fprintf(out, "| `%s` | %d | %d | %d | %d |\n", img.Name, img.OS["CRITICAL"], img.OS["HIGH"], img.OS["MEDIUM"], img.Other)
	}
	distinct := Distinct(images)
	bySev := map[string][]string{}
	for id, sev := range distinct {
		bySev[sev] = append(bySev[sev], id)
	}
	counts := make([]string, 0, len(Severities))
	for _, s := range Severities {
		sort.Strings(bySev[s])
		counts = append(counts, fmt.Sprintf("%s %d", s, len(bySev[s])))
	}
	fmt.Fprintf(out, "\nFixable OS vulnerabilities, MEDIUM or higher, distinct CVEs over the %d images (what a refresh fixes): %s.\n",
		len(images), strings.Join(counts, ", "))
	other := 0
	for _, img := range images {
		other += img.Other
	}
	if other > 0 {
		fmt.Fprintf(out, "%d fixable findings are outside OS packages: a refresh does not fix them, and they do not trigger one.\n", other)
	}
	if len(distinct) > 0 {
		fmt.Fprintln(out, "\n<details><summary>The CVEs</summary>")
		fmt.Fprintln(out)
		listed := 0
		for _, s := range Severities {
			for _, id := range bySev[s] {
				if listed == maxListed {
					break
				}
				fmt.Fprintf(out, "- %s %s\n", s, id)
				listed++
			}
		}
		if len(distinct) > listed {
			fmt.Fprintf(out, "- and %d more\n", len(distinct)-listed)
		}
		fmt.Fprintln(out, "\n</details>")
	}
	fmt.Fprintln(out)

	runs, err := g.runs(o.Repo, o.Now)
	if err != nil {
		return err
	}
	var problems []error
	actor := g.actor(o)
	if actor == "" {
		fmt.Fprintln(out, "The bot's login is unknown (no `--actor`, and the token has no user): the last automated refresh is not checked.")
	} else {
		var last *Run
		for i := range runs {
			r := &runs[i]
			if r.Event == "workflow_dispatch" && r.Actor.Login == actor && r.Status == "completed" {
				last = r
				break
			}
		}
		lines, err := g.report(o.Repo, last, o.Dry)
		for _, l := range lines {
			fmt.Fprintln(out, l)
		}
		if err != nil {
			problems = append(problems, fmt.Errorf("the refresh issue: %v", err))
		}
	}

	decision := Decide(len(distinct) > 0, runs, o.Now)
	with := fmt.Sprintf("%s with refresh=true on %s", Workflow, Branch)
	switch {
	case decision != "":
	case o.Dry:
		decision = "dry run: would dispatch " + with
	default:
		body := map[string]any{"ref": Branch, "inputs": map[string]string{"refresh": "true"}}
		_, err := g.rest().Do("POST", fmt.Sprintf("repos/%s/actions/workflows/%s/dispatches", o.Repo, Workflow), body)
		switch {
		case err == nil:
			decision = "dispatched " + with
		case github.Status(err) == http.StatusForbidden || github.Status(err) == http.StatusNotFound:
			decision = "dispatch refused (the token needs Actions: write)"
			problems = append(problems, err)
		default:
			decision = "dispatch failed"
			problems = append(problems, err)
		}
	}
	fmt.Fprintf(out, "\nos-refresh: %d images, %d fixable OS CVEs (%s); %s\n", len(images), len(distinct),
		strings.Join(counts, ", "), decision)
	return errors.Join(problems...)
}

const usage = "usage: os-refresh --repo OWNER/NAME [--actor LOGIN] [--dry-run] [--now RFC3339] REPORT.json..."

// Main is the command. GH_TOKEN: Actions read and Issues read on the repository; Actions write
// to dispatch, Issues write for the refresh issue; no token is a dry run.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	o := Options{Now: time.Now().UTC()}
	var files []string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			o.Dry = true
		case (a == "--repo" || a == "--actor" || a == "--now") && i+1 < len(args):
			v := args[i+1]
			i++
			switch a {
			case "--repo":
				o.Repo = v
			case "--actor":
				o.Actor = v
			default:
				t, err := time.Parse(time.RFC3339, v)
				if err != nil {
					fmt.Fprintln(stderr, "os-refresh: --now:", err)
					return 2
				}
				o.Now = t.UTC()
			}
		case a == "-h" || a == "--help":
			fmt.Fprintln(stdout, usage)
			return 0
		case strings.HasPrefix(a, "-"):
			fmt.Fprintln(stderr, usage)
			return 2
		default:
			files = append(files, a)
		}
	}
	if !repoRe.MatchString(o.Repo) || len(files) == 0 {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	if len(files) > maxReports {
		fmt.Fprintf(stderr, "os-refresh: more than %d reports\n", maxReports)
		return 2
	}
	images := make([]Image, 0, len(files))
	for _, f := range files {
		fh, err := os.Open(f)
		if err != nil {
			fmt.Fprintln(stderr, "os-refresh:", err)
			return 1
		}
		img, err := Parse(fh, f)
		fh.Close()
		if err != nil {
			fmt.Fprintf(stderr, "os-refresh: %s: %v\n", f, err)
			return 1
		}
		images = append(images, img)
	}
	token := getenv("GH_TOKEN")
	if token == "" && !o.Dry {
		fmt.Fprintln(stderr, "os-refresh: no GH_TOKEN: dry run")
		o.Dry = true
	}
	g := GitHub{API: api, Token: token, Client: client}
	if err := Scan(g, images, o, stdout); err != nil {
		fmt.Fprintln(stderr, "os-refresh:", err)
		return 1
	}
	return 0
}
