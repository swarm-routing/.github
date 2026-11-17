// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// Answers a checkout cannot show, read by the weekly check from the
// repository's history (swarm-routing/.github#634): whether recent changes
// followed the test policy (tests_are_added, from the files of its merged
// pull requests) and how much of main the tests cover (test_most, from
// Codecov's public API). org-bot's checkout is shallow and offline, so
// these stay `?` in .bestpractices.json; the check proposes Met only when
// the data shows it, and otherwise says what it read.

import (
	"fmt"
	"io"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The rules' thresholds.
const (
	RecentMajor  = 10   // merged feat/fix pull requests tests_are_added reads
	MinMajor     = 3    // fewer that change code: not enough to judge
	MostCoverage = 50.0 // test_most: more than this percentage of main covered
	FreshDays    = 90   // a coverage report older than this is not evidence
)

// HistoryReader reads a repository's history: its closed pull requests to
// main (one page, most recently updated first), the files one changed, and
// Codecov's repository record (nil: no report). The real network
// implements it; the check works without one (the criteria stay `?`).
type HistoryReader interface {
	ClosedPulls(repo string) (any, error)
	PullFiles(repo, number string) (any, error)
	Coverage(repo string) (any, error)
	// Issues lists the issues (and pull requests) labelled label updated since since.
	Issues(repo, label, since string) (any, error)
	// IssueComments lists one issue's comments.
	IssueComments(repo, number string) (any, error)
	// Advisories lists the repository's security advisories, private
	// vulnerability reports included (a 404: none can be read).
	Advisories(repo string) (any, error)
}

// Issues lists the issues and pull requests labelled label updated since since.
func (h *HTTP) Issues(repo, label, since string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/issues?state=all&labels=%s&since=%s&per_page=100",
		Org, repo, label, since), nil, true)
}

// IssueComments lists one issue's comments.
func (h *HTTP) IssueComments(repo, number string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/issues/%s/comments?per_page=100", Org, repo, number), nil, true)
}

// Advisories lists the security advisories.
func (h *HTTP) Advisories(repo string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/security-advisories?per_page=100", Org, repo), nil, true)
}

// ClosedPulls lists the closed pull requests to main, most recently updated first.
func (h *HTTP) ClosedPulls(repo string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100",
		Org, repo), nil, false)
}

// PullFiles lists the files a pull request changed.
func (h *HTTP) PullFiles(repo, number string) (any, error) {
	return h.API("GET", fmt.Sprintf("repos/%s/%s/pulls/%s/files?per_page=100", Org, repo, number), nil, true)
}

// Coverage is Codecov's public record of the repository (no token is sent:
// the GitHub token is GitHub's alone); a 404 is (nil, nil).
func (h *HTTP) Coverage(repo string) (any, error) {
	base := h.CodecovURL
	if base == "" {
		base = "https://api.codecov.io"
	}
	u := fmt.Sprintf("%s/api/v2/github/%s/repos/%s/", strings.TrimRight(base, "/"), Org, repo)
	req, err := http.NewRequest(http.MethodGet, u, nil)
	if err != nil {
		return nil, failure("codecov %s: %v", repo, err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "bestpractices-check")
	resp, err := h.Client.Do(req)
	if err != nil {
		return nil, failure("codecov %s: %v", repo, unwrapURL(err))
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxBody))
	if err != nil {
		return nil, failure("codecov %s: %v", repo, err)
	}
	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}
	if resp.StatusCode >= 300 {
		return nil, failure("codecov %s: HTTP %d", repo, resp.StatusCode)
	}
	return decodeJSON(data)
}

// HistoryReport is what the check read from the history: the answers it
// proposes, and for the others why they stay `?`.
type HistoryReport struct {
	Answers map[string][2]string
	Blocked map[string]string
}

// merge returns proposed with the history's answers in place of the file's `?`.
func (h HistoryReport) merge(proposed map[string]any) map[string]any {
	out := make(map[string]any, len(proposed)+2*len(h.Answers))
	for k, v := range proposed {
		out[k] = v
	}
	for c, a := range h.Answers {
		out[c+"_status"], out[c+"_justification"] = a[0], a[1]
	}
	// an owner-only criterion is Met only as the history shows it, never
	// from a hand-edited file
	for c := range FromHistory {
		if why, ok := h.Blocked[c]; ok {
			out[c+"_status"], out[c+"_justification"] = "?", why
		}
	}
	return out
}

var (
	majorTitle = regexp.MustCompile(`^(feat|fix)(\([^)]*\))?!?:`)
	codeFile   = regexp.MustCompile(`\.(c|cc|cpp|cxx|h|hh|hpp|py|sh|go|js|mjs|ts|rs)$`)
	// a test: under a tests/ (testdata/, testbench/) directory, or named as one
	testFile = regexp.MustCompile(`(^|/)(tests?|testdata|testbench|fixtures?)/|(^|/)test_[^/]+\.py$|_test\.(go|py)$` +
		`|(^|/)test-[^/]+$|-test(-suite)?\.[a-z]+$|\.test\.m?[jt]s$|(^|/)[^/]*smoke[^/]*\.m?js$`)
)

// historyAnswers reads one repository's history. proposed is its
// .bestpractices.json (tests_are_added needs its written test policy). A
// nil reader reads nothing.
func historyAnswers(hr HistoryReader, repo string, proposed map[string]any) HistoryReport {
	rep := HistoryReport{Answers: map[string][2]string{}, Blocked: map[string]string{}}
	if hr == nil {
		return rep
	}
	base := fmt.Sprintf("https://github.com/%s/%s", Org, repo)
	if c, why, ok := testsAdded(hr, repo, base, proposed); ok {
		rep.Answers[c] = [2]string{"Met", why}
	} else {
		rep.Blocked[c] = why
	}
	if c, why, ok := testMost(hr, repo); ok {
		rep.Answers[c] = [2]string{"Met", why}
	} else {
		rep.Blocked[c] = why
	}
	for c, r := range responses(hr, repo, base) {
		if r.met {
			rep.Answers[c] = [2]string{"Met", r.why}
		} else {
			rep.Blocked[c] = r.why
		}
	}
	return rep
}

// The response-time rules (swarm-routing/.github#613).
const (
	ResponseDays = 14  // a response within this many days acknowledges a report
	ReportDays   = 365 // bug and enhancement reports: the last 12 months
	VulnDays     = 183 // vulnerability reports: the last 6 months
)

// FromHistory is the owner-only criteria the check may propose from the
// repository's history when the data shows them (#613).
var FromHistory = map[string]bool{
	"report_responses": true, "enhancement_responses": true, "vulnerability_report_response": true,
}

// maintainerRole: an author association that answers for the project.
var maintainerRole = map[string]bool{"OWNER": true, "MEMBER": true, "COLLABORATOR": true}

func responder(m map[string]any) bool {
	u, _ := m["user"].(map[string]any)
	return maintainerRole[pyStr(m["author_association"])] || pyEqual(u["type"], "Bot")
}

func parseTime(v any) (time.Time, bool) {
	s, _ := v.(string)
	t, err := time.Parse(time.RFC3339, s)
	return t, err == nil
}

type response struct {
	met bool
	why string
}

// reportsAnswered counts the reports labelled label from outside the
// project opened since since, and those a maintainer or a bot answered (a
// comment, or the closing) within ResponseDays. A report younger than
// ResponseDays and not answered yet is still open to answer: not counted.
func reportsAnswered(hr HistoryReader, repo, label, since string) (int, int, error) {
	day := 24 * time.Hour
	issues, err := hr.Issues(repo, label, since)
	if err != nil {
		return 0, 0, err
	}
	il, _ := issues.([]any)
	answered, total := 0, 0
	for _, x := range il {
		m, _ := x.(map[string]any)
		if _, pr := m["pull_request"]; pr || responder(m) {
			continue
		}
		opened, ok := parseTime(m["created_at"])
		if !ok || now().Sub(opened) > ReportDays*day {
			continue
		}
		in := func(t time.Time) bool { return t.Sub(opened) <= ResponseDays*day }
		done := false
		if c, ok := parseTime(m["closed_at"]); ok && in(c) {
			done = true
		} else if truthy(m["comments"]) || m["comments"] == nil {
			cs, err := hr.IssueComments(repo, pyStr(m["number"]))
			if err != nil {
				return 0, 0, err
			}
			cl, _ := cs.([]any)
			for _, y := range cl {
				cm, _ := y.(map[string]any)
				if at, ok := parseTime(cm["created_at"]); ok && responder(cm) && in(at) {
					done = true
					break
				}
			}
		}
		if !done && now().Sub(opened) <= ResponseDays*day {
			continue
		}
		total++
		if done {
			answered++
		}
	}
	return answered, total, nil
}

// responses: of the reports from outside the project (an issue labelled
// bug or enhancement, opened by someone who is not a maintainer or a bot)
// in the last ReportDays, how many a maintainer or a bot answered (a
// comment, or the closing) within ResponseDays; a report younger than
// ResponseDays and not answered yet is still open to answer and not
// counted. Met: a majority. Vulnerability reports are the private reports
// (security advisories) of the last VulnDays: Met when every one left
// triage (accepted, published or closed) within ResponseDays, as its
// published or closed date shows.
func responses(hr HistoryReader, repo, base string) map[string]response {
	out := map[string]response{}
	day := 24 * time.Hour
	since := now().Add(-ReportDays * day).UTC().Format(time.RFC3339)
	query := base + "/issues?q=is:issue+label:"
	for c, label := range map[string]string{"report_responses": "bug", "enhancement_responses": "enhancement"} {
		answered, total, err := reportsAnswered(hr, repo, label, since)
		if err != nil {
			out[c] = response{false, "cannot read the " + label + " reports: " + described(err)}
			continue
		}
		read := fmt.Sprintf("%d of the %d %s reports from outside the project in the last 12 months had a "+
			"maintainer's or bot's response within %d days (issues, comments and closings read from the "+
			"GitHub API)", answered, total, label, ResponseDays)
		if total == 0 || 2*answered <= total {
			out[c] = response{false, read + "; Met needs a majority: " + query + label}
		} else {
			out[c] = response{true, "The majority of reports are acknowledged: " + read + ": " + query + label + "."}
		}
	}

	const c = "vulnerability_report_response"
	adv, err := hr.Advisories(repo)
	list, ok := adv.([]any)
	switch {
	case err != nil:
		out[c] = response{false, "cannot read the security advisories: " + described(err)}
	case !ok:
		out[c] = response{false, "the security advisories are not available (HTTP 404)"}
	default:
		total, timely := 0, 0
		for _, x := range list {
			m, _ := x.(map[string]any)
			opened, ok := parseTime(m["created_at"])
			if !ok || now().Sub(opened) > VulnDays*day {
				continue
			}
			total++
			for _, k := range []string{"published_at", "closed_at"} {
				if t, ok := parseTime(m[k]); ok && t.Sub(opened) <= ResponseDays*day {
					timely++
					break
				}
			}
		}
		page := base + "/security/advisories"
		read := fmt.Sprintf("%d of the %d vulnerability reports (security advisories) of the last 6 months were "+
			"published or closed within %d days", timely, total, ResponseDays)
		if total == 0 || timely < total {
			out[c] = response{false, read + "; Met needs every one: " + page}
		} else {
			out[c] = response{true, fmt.Sprintf("Every vulnerability report is answered within %d days: %s: %s.",
				ResponseDays, read, page)}
		}
	}
	return out
}

// testsAdded: of the RecentMajor most recent merged feat/fix pull requests,
// those that change code; at least MinMajor of them, and at least half also
// change a test.
func testsAdded(hr HistoryReader, repo, base string, proposed map[string]any) (string, string, bool) {
	const c = "tests_are_added"
	if !pyEqual(proposed["test_policy_status"], "Met") {
		return c, "no written test policy (test_policy) to have followed", false
	}
	got, err := hr.ClosedPulls(repo)
	if err != nil {
		return c, "cannot read the merged pull requests: " + described(err), false
	}
	list, _ := got.([]any)
	type pull struct{ number, merged string }
	var majors []pull
	for _, x := range list {
		m, _ := x.(map[string]any)
		merged, _ := m["merged_at"].(string)
		title, _ := m["title"].(string)
		if merged != "" && majorTitle.MatchString(title) {
			majors = append(majors, pull{pyStr(m["number"]), merged})
		}
	}
	sort.SliceStable(majors, func(i, j int) bool { return majors[i].merged > majors[j].merged })
	if len(majors) > RecentMajor {
		majors = majors[:RecentMajor]
	}
	var code, tested []string
	for _, p := range majors {
		files, err := hr.PullFiles(repo, p.number)
		if err != nil {
			return c, fmt.Sprintf("cannot read the files of #%s: %s", p.number, described(err)), false
		}
		fl, _ := files.([]any)
		src, tst := false, false
		for _, f := range fl {
			m, _ := f.(map[string]any)
			name, _ := m["filename"].(string)
			switch {
			case testFile.MatchString(name):
				tst = true
			case codeFile.MatchString(name):
				src = true
			}
		}
		if src {
			code = append(code, "#"+p.number)
			if tst {
				tested = append(tested, "#"+p.number)
			}
		}
	}
	query := base + "/pulls?q=is:pr+is:merged+base:main"
	read := fmt.Sprintf("%d of the %d most recent merged feat/fix pull requests that change code also change tests",
		len(tested), len(code))
	if len(code) < MinMajor || 2*len(tested) < len(code) {
		return c, fmt.Sprintf("%s (Met needs at least %d, half of them with tests): %s", read, MinMajor, query), false
	}
	return c, fmt.Sprintf("The test policy (test_policy) is followed: %s (%s): %s.", read,
		strings.Join(tested, ", "), query), true
}

// testMost: Codecov's coverage of main, fresh, above MostCoverage.
func testMost(hr HistoryReader, repo string) (string, string, bool) {
	const c = "test_most"
	got, err := hr.Coverage(repo)
	if err != nil {
		return c, "cannot read Codecov: " + described(err), false
	}
	m, _ := got.(map[string]any)
	totals, _ := m["totals"].(map[string]any)
	cov, err := strconv.ParseFloat(pyStr(totals["coverage"]), 64)
	if m == nil || err != nil {
		return c, "no Codecov coverage report for main", false
	}
	page := fmt.Sprintf("https://app.codecov.io/gh/%s/%s", Org, repo)
	stamp, _ := m["updatestamp"].(string)
	at, err := time.Parse(time.RFC3339Nano, stamp)
	if err != nil || now().Sub(at) > FreshDays*24*time.Hour {
		return c, fmt.Sprintf("Codecov's report of main is not from the last %d days: %s", FreshDays, page), false
	}
	day := at.UTC().Format("2006-01-02")
	if cov <= MostCoverage {
		return c, fmt.Sprintf("Codecov measures %.0f%% of main covered (%s), not more than %.0f%%: %s",
			cov, day, MostCoverage, page), false
	}
	return c, fmt.Sprintf("The automated tests cover most of the code: Codecov measures %.0f%% of main's lines "+
		"and branches covered (%s): %s.", cov, day, page), true
}
