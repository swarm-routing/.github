// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"fmt"
	"io"
	"regexp"
	"strings"
)

// Remote is the network the check reads: bestpractices.dev's public JSON
// and GitHub.
type Remote interface {
	Searcher
	// Site returns the project's public JSON (/projects/<id>.json).
	Site(project string) (any, error)
	// File returns the file's text on main; ok is false when it is absent.
	File(repo, path string) (text string, ok bool, err error)
	// Tree returns the paths of every file and directory on main.
	Tree(repo string) (map[string]bool, error)
	// Repos returns the public, unarchived org repositories, sorted.
	Repos() ([]string, error)
}

// GitHub is the API the issues are written through; a 404 is (nil, nil).
type GitHub interface {
	API(method, path string, body map[string]any, paginate bool) (any, error)
}

// CheckArgs are the check's options.
type CheckArgs struct {
	Repos  string // NAME or NAME=ID, comma-separated; empty: every public repository
	Issues bool   // open, update or close one issue per repository
	DryRun bool   // write no issue
}

// target is a repository to check: its project, or, when project is "",
// a repository in scope (Scope) that is not registered.
type target struct {
	repo, project string
	configured    bool
	scope         string // why an unregistered repository is in scope
	outOfScope    bool   // not registered and out of scope: only an open issue is closed
}

// repoConfig is what the check reads from a repository's
// .github/org-sync.toml: top-level bestpractices_project, and the opt-out
// `bestpractices = false` in [settings] (absent or true: in scope).
type repoConfig struct {
	project string
	scope   *bool
}

func configOf(r Remote, repo string) (repoConfig, error) {
	var c repoConfig
	text, ok, err := r.File(repo, Config)
	if err != nil {
		return c, err
	}
	if !ok || text == "" {
		return c, nil
	}
	cfg, err := parseTOML(text)
	if err != nil {
		return c, nil
	}
	if v, ok := cfg["bestpractices_project"]; ok {
		if p := strings.TrimSpace(tomlStr(v)); isDigits(p) {
			c.project = p
		}
	}
	if settings, ok := cfg["settings"].(map[string]any); ok {
		if b, ok := settings["bestpractices"].(bool); ok {
			c.scope = &b
		}
	}
	return c, nil
}

// tomlStr is Python's str() of a value tomllib returned.
func tomlStr(v any) string {
	switch x := v.(type) {
	case int64:
		return fmt.Sprint(x)
	case float64:
		return pyFloat(x)
	}
	return pyStr(v)
}

// inScope says whether a repository should be registered: every public
// org repository is (maintainer decision 2026-11-16), unless its
// .github/org-sync.toml opts out with `bestpractices = false` in
// [settings]. The reason is "" when it is out of scope.
func inScope(c repoConfig) string {
	if c.scope != nil && !*c.scope {
		return ""
	}
	return "a public org repository"
}

// targets: --repos entries (NAME=ID or NAME), else every public org
// repository. A repository whose config names no project is looked up on the
// site by its URL: registered there, it is checked and its missing key is a
// finding; not registered and in scope, it is a target with no project.
func targets(r Remote, spec string) ([]target, []string, error) {
	var names []string
	named := spec != ""
	if named {
		for _, s := range strings.Split(spec, ",") {
			if s = strings.TrimSpace(s); s != "" {
				names = append(names, s)
			}
		}
	} else {
		repos, err := r.Repos()
		if err != nil {
			return nil, nil, err
		}
		names = repos
	}
	if len(names) > maxRepoEntries {
		names = names[:maxRepoEntries]
	}
	var out []target
	var failed []string
	for _, entry := range names {
		repo, given, _ := strings.Cut(entry, "=")
		cfg, err := configOf(r, repo)
		pid := strings.TrimSpace(given)
		if err == nil && pid == "" {
			pid = cfg.project
			if pid == "" {
				pid, err = Registered(r, Org+"/"+repo)
			}
		}
		if err != nil {
			failed = append(failed, fmt.Sprintf("%s: FAILED: the lookup: %s", repo, described(err)))
			continue
		}
		scope := inScope(cfg)
		switch {
		case isDigits(pid):
			out = append(out, target{repo: repo, project: pid, configured: cfg.project != ""})
		case scope != "":
			out = append(out, target{repo: repo, scope: scope})
		default:
			out = append(out, target{repo: repo, outOfScope: true, configured: named})
		}
	}
	return out, failed, nil
}

// Report is what the check finds for one registered project.
type Report struct {
	Info  []string // level, percentage, what the owner still answers
	Items []string // the findings: each is drift
	// Propose is the criteria whose answer in .bestpractices.json the site
	// should take: unanswered there, answered otherwise, or justified by a
	// file no longer on main.
	Propose map[string]bool
	// OwnerOpen is the owner-only criteria still unanswered on the site.
	OwnerOpen []string
}

func unanswered(v any) bool { return v == nil || pyEqual(v, "?") || pyEqual(v, "unknown") }

// Findings compares a project's site JSON (data) with the repository's
// .bestpractices.json (proposed) and main's paths (tree).
func Findings(repo string, data, proposed map[string]any, tree map[string]bool) Report {
	get := func(m map[string]any, k string, def any) any {
		if v, ok := m[k]; ok {
			return v
		}
		return def
	}
	rep := Report{Propose: map[string]bool{}}
	rep.Info = []string{fmt.Sprintf("level %s, passing %s%%", pyStr(get(data, "badge_level", "?")),
		pyStr(get(data, "badge_percentage_0", "?")))}
	answered := func(c string) bool {
		want := proposed[c+"_status"]
		return truthy(want) && !unanswered(want) && (!OwnerOnly[c] || Attested[c])
	}
	var out, missing []string
	for _, c := range Passing {
		if !answered(c) {
			continue
		}
		want, have := proposed[c+"_status"], data[c+"_status"]
		if unanswered(have) {
			missing = append(missing, c)
			rep.Propose[c] = true
		} else if !pyEqual(have, want) {
			out = append(out, fmt.Sprintf("%s: the site says %s, %s says %s", c, pyStr(have), Out, pyStr(want)))
			rep.Propose[c] = true
		}
	}
	out = append(out, staleEvidence(repo, data, proposed, rep.Propose)...)
	if len(missing) > 0 {
		out = append([]string{fmt.Sprintf("%d answer(s) in %s not on the site yet: %s",
			len(missing), Out, strings.Join(missing, ", "))}, out...)
	}
	if len(proposed) == 0 {
		rep.Info = append(rep.Info, "no "+Out+" on main")
	}
	for _, c := range Passing {
		why, _ := data[c+"_justification"].(string)
		for _, m := range urlIn.FindAllStringSubmatch(why, -1) {
			owner, name, path := m[1], m[2], strings.TrimRight(m[3], ".,;:")
			if owner != Org || name != repo || tree[path] {
				continue
			}
			prefix := strings.TrimRight(path, "/") + "/"
			found := false
			for t := range tree {
				if strings.HasPrefix(t, prefix) {
					found = true
					break
				}
			}
			if found {
				continue
			}
			out = append(out, fmt.Sprintf("%s: the justification points at %s, not on main", c, path))
			if answered(c) {
				rep.Propose[c] = true
			}
		}
	}
	for _, level := range Levels {
		lost, won := data["lost_"+level+"_at"], data["achieved_"+level+"_at"]
		if truthy(lost) && (!truthy(won) || pyStr(lost) > pyStr(won)) {
			l := []rune(pyStr(lost))
			if len(l) > 10 {
				l = l[:10]
			}
			out = append(out, fmt.Sprintf("level lost: %s since %s", level, string(l)))
		}
	}
	for _, c := range Passing {
		if OwnerOnly[c] && unanswered(data[c+"_status"]) && !rep.Propose[c] {
			rep.OwnerOpen = append(rep.OwnerOpen, c)
		}
	}
	if len(rep.OwnerOpen) > 0 {
		rep.Info = append(rep.Info, fmt.Sprintf("%d owner-only criteria unanswered", len(rep.OwnerOpen)))
	}
	seen := map[string]bool{}
	for _, x := range out {
		if !seen[x] {
			seen[x] = true
			rep.Items = append(rep.Items, x)
		}
	}
	return rep
}

// proposalLinks are the proposal links for the criteria rep proposes, from
// the repository's .bestpractices.json, in the form's order.
func proposalLinks(project string, proposed map[string]any, rep Report) ([]string, error) {
	var ans Answers
	for _, c := range Passing {
		if rep.Propose[c] {
			why := ""
			if j, ok := proposed[c+"_justification"]; ok {
				why = pyStr(j)
			}
			ans = append(ans, Answer{c, pyStr(proposed[c+"_status"]), why})
		}
	}
	return ProposalURLs(project, ans, "passing", ProposalLimit)
}

// Title is the issue's title for these findings.
func Title(items []string) string { return fmt.Sprintf("%s %d finding(s)", Prefix, len(items)) }

// Body is the issue's body for a registered project's findings: the
// proposal links that fix what the repository can answer, then the
// owner-only criteria still open (listed, never a finding, so they alone
// neither open nor update an issue).
func Body(repo, project string, items, links, ownerOpen []string, owner OwnerReport, runURL string) string {
	run := "."
	if runURL != "" {
		run = fmt.Sprintf(" ([run](%s)).", runURL)
	}
	lines := []string{
		"## Context",
		"",
		fmt.Sprintf("The weekly `bestpractices` check (swarm-routing/.github `cmd/bestpractices`) "+
			"found `%s`'s OpenSSF Best Practices entry (%s/projects/%s) out of "+
			"step with the repository%s", repo, Site, project, run),
		"",
		"## Findings",
		"",
	}
	for _, i := range items {
		lines = append(lines, "- [ ] "+i)
	}
	lines = append(lines, "", "## Save", "")
	if len(links) > 0 {
		lines = append(lines,
			"**Open, review, Save.** Each link opens the project's form, logged in, with the "+
				"answers from `"+Out+"` on main filled in; nothing changes until you press "+
				"\"Save (and continue)\". The owner-only criteria the maintainer attested "+
				"(`"+OwnerFile+"` in swarm-routing/.github) are included when the check finds "+
				"nothing against them; the other owner-only criteria are left out.",
			"")
		for i, l := range links {
			lines = append(lines, fmt.Sprintf("%d. %s", i+1, l))
		}
	} else {
		lines = append(lines, fmt.Sprintf("Nothing to propose from `%s`: answer on the site, "+
			"logged in at %s/projects/%s/passing (a lost level is answered there first).", Out, Site, project))
	}
	lines = append(lines, ownerSection(ownerOpen, owner)...)
	lines = append(lines,
		"",
		"## Scope",
		"",
		"bestpractices.dev has no write API: the bot never logs in or saves. `"+Out+"` is "+
			"regenerated from the repository by org-bot (task `bestpractices`), and a fix "+
			"belongs in the repository first; then the link above carries it.",
		"",
		"This issue is updated in place by the weekly run and closed when the entry matches.",
	)
	return strings.Join(lines, "\n") + Footer
}

// ownerSection is the "Only the owner can answer" section: the owner-only
// criteria still `?` on the site and not proposed, each with why, and the
// alert listings the token could not read.
func ownerSection(ownerOpen []string, owner OwnerReport) []string {
	if len(ownerOpen) == 0 && len(owner.Unread) == 0 {
		return nil
	}
	lines := []string{"", "## Only the owner can answer", "",
		"Still `?` on the site and not proposed (swarm-routing/AntHocNet#790). Five are " +
			"attested by the maintainer in `" + OwnerFile + "` (swarm-routing/.github) and proposed " +
			"above once the check finds nothing against them; the others are never proposed. " +
			"Listed here, not counted as findings:", ""}
	for _, c := range ownerOpen {
		l := "- `" + c + "`"
		if why, ok := owner.Blocked[c]; ok {
			l += ": " + why
		} else if !Attested[c] {
			l += ": not attested; answered on the site only"
		}
		lines = append(lines, l)
	}
	if len(owner.Unread) > 0 {
		lines = append(lines, "", "The check could not read these alert listings with the bot's token, "+
			"so the criteria they back stay `?` (the org App needs read access to Code scanning "+
			"alerts / Security events, Dependabot alerts and Secret scanning alerts):", "")
		for _, u := range owner.Unread {
			lines = append(lines, "- "+u)
		}
	}
	return lines
}

// RegisterBody is the issue's body for a repository in scope that is not
// registered.
func RegisterBody(repo, scope, runURL string) string {
	run := "."
	if runURL != "" {
		run = fmt.Sprintf(" ([run](%s)).", runURL)
	}
	lines := []string{
		"## Context",
		"",
		fmt.Sprintf("The weekly `bestpractices` check (swarm-routing/.github `cmd/bestpractices`) "+
			"found `%s` in scope for the OpenSSF Best Practices badge (%s) but not registered "+
			"on bestpractices.dev%s", repo, scope, run),
		"",
		"## Findings",
		"",
		"- [ ] " + notRegistered,
		"",
		"## Register",
		"",
		"Registration is the maintainer's, on the site (it has no registration API):",
		"",
		fmt.Sprintf("1. Logged in, add the project at %s/en/projects/new with https://github.com/%s/%s.", Site, Org, repo),
		"2. Nothing else: the next weekly run finds the project by its URL, and this issue then " +
			"carries the proposal link(s) to Save and asks for `bestpractices_project = \"<id>\"` in " +
			"`" + Config + "`.",
		"",
		fmt.Sprintf("Not wanted for this repository? `bestpractices = false` under `[settings]` in "+
			"`%s` takes it out of scope, and this issue closes at the next run.", Config),
	}
	return strings.Join(lines, "\n") + Footer
}

const notRegistered = "not registered on bestpractices.dev"

var proposalLine = Site + "/en/projects/"

// sameIssue: the open issue already lists these findings and these links,
// and the same owner-only section.
func sameIssue(body string, items, links []string, owner []string) bool {
	if owner != nil && !strings.Contains(body, strings.Join(owner, "\n")) {
		return false
	}
	var got, gotLinks []string
	for _, x := range strings.Split(body, "\n") {
		x = strings.TrimSuffix(x, "\r")
		if strings.HasPrefix(x, "- [ ] ") || strings.HasPrefix(x, "- [x] ") {
			got = append(got, x[6:])
		}
		if _, l, ok := strings.Cut(x, ". "+proposalLine); ok {
			gotLinks = append(gotLinks, proposalLine+l)
		}
	}
	return equal(got, items) && equal(gotLinks, links)
}

func equal(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func syncIssue(gh GitHub, repo string, items, links, owner []string, body string, dryRun bool, runURL string) (string, error) {
	got, err := gh.API("GET", fmt.Sprintf("repos/%s/%s/issues?state=open&labels=chore&per_page=100", Org, repo), nil, true)
	if err != nil {
		return "", err
	}
	list, _ := got.([]any)
	var issue map[string]any
	for _, x := range list {
		i, ok := x.(map[string]any)
		if !ok {
			continue
		}
		title, _ := i["title"].(string)
		if _, pr := i["pull_request"]; strings.HasPrefix(title, Prefix) && !pr {
			issue = i
			break
		}
	}
	if len(items) == 0 {
		if issue == nil {
			return "clean", nil
		}
		n := pyStr(issue["number"])
		if !dryRun {
			note := "Clean: the bestpractices check finds nothing any more"
			if runURL != "" {
				note += " (" + runURL + ")"
			}
			if _, err := gh.API("POST", fmt.Sprintf("repos/%s/%s/issues/%s/comments", Org, repo, n),
				map[string]any{"body": note + "." + Footer}, false); err != nil {
				return "", err
			}
			if _, err := gh.API("PATCH", fmt.Sprintf("repos/%s/%s/issues/%s", Org, repo, n),
				map[string]any{"state": "closed", "state_reason": "completed"}, false); err != nil {
				return "", err
			}
		}
		return "close #" + n, nil
	}
	title := Title(items)
	if issue == nil {
		if dryRun {
			return "open", nil
		}
		labels := make([]any, len(Labels))
		for i, l := range Labels {
			labels[i] = l
		}
		got, err := gh.API("POST", fmt.Sprintf("repos/%s/%s/issues", Org, repo),
			map[string]any{"title": title, "body": body, "labels": labels}, false)
		if err != nil {
			return "", err
		}
		m, _ := got.(map[string]any)
		return "open #" + pyStr(m["number"]), nil
	}
	n := pyStr(issue["number"])
	oldBody, _ := issue["body"].(string)
	if issue["title"] == title && sameIssue(oldBody, items, links, owner) {
		return "unchanged #" + n, nil
	}
	if !dryRun {
		if _, err := gh.API("PATCH", fmt.Sprintf("repos/%s/%s/issues/%s", Org, repo, n),
			map[string]any{"title": title, "body": body}, false); err != nil {
			return "", err
		}
	}
	return "update #" + n, nil
}

// Check compares every registered project with its repository, and finds
// the repositories in scope that are not registered, and returns the exit
// code: 0 clean, 1 drift, 2 a project could not be read. With --issues the
// issues carry the drift, so drift alone is 0 (#611): the run is red only
// when it failed, 2, which then also counts an alert listing the reader
// could not read and an issue that could not be written. env gives
// BESTPRACTICES_TOKEN (the issue token) and the GITHUB_* run variables;
// newGitHub makes the API client the issues are written with, from that
// token.
func Check(args CheckArgs, r Remote, newGitHub func(token string) GitHub, env func(string) string, stdout io.Writer) int {
	token := env("BESTPRACTICES_TOKEN")
	dryRun := args.DryRun || token == ""
	var gh GitHub
	if args.Issues {
		if token == "" && !args.DryRun {
			fmt.Fprintln(stdout, "bestpractices: BESTPRACTICES_TOKEN is not set; issues: dry run")
		}
		gh = newGitHub(token)
	}
	runURL := ""
	if env("GITHUB_RUN_ID") != "" {
		server := env("GITHUB_SERVER_URL")
		if server == "" {
			server = "https://github.com"
		}
		runURL = fmt.Sprintf("%s/%s/actions/runs/%s", server, pyStr(envOrNone(env, "GITHUB_REPOSITORY")), env("GITHUB_RUN_ID"))
	}
	todo, failed, err := targets(r, args.Repos)
	if err != nil {
		fmt.Fprintf(stdout, "bestpractices: the org listing: %s\n", described(err))
		return 2
	}
	for _, line := range failed { // a lookup that failed, or a named repository on no project: not drift
		fmt.Fprintln(stdout, line)
	}
	projects, unregistered, drift, broken := 0, 0, 0, len(failed)
	var att *Attestation
	attLoaded := false
	for _, t := range todo {
		var info, items, links, ownerLines []string
		var body, head string
		if t.outOfScope {
			// not registered, out of scope: nothing to find; an issue left
			// open from when it was in scope is closed
			action := ""
			if args.Issues {
				a, err := syncIssue(gh, t.repo, nil, nil, nil, "", dryRun, runURL)
				switch {
				case err != nil:
					broken++
					action = "; issue: FAILED: " + described(err)
				case a != "clean" && dryRun:
					action = "; issue: would " + a
				case a != "clean":
					action = "; issue: " + a
				}
			}
			if t.configured || action != "" { // named, or an issue to report
				fmt.Fprintf(stdout, "%s (not registered): out of scope; 0 finding(s)%s\n", t.repo, action)
			}
			continue
		}
		if t.project == "" {
			unregistered++
			head = t.repo + " (not registered)"
			info = []string{"in scope: " + t.scope}
			items = []string{notRegistered}
			body = RegisterBody(t.repo, t.scope, runURL)
		} else {
			projects++
			head = fmt.Sprintf("%s (project %s)", t.repo, t.project)
			data, proposed, tree, err := read(r, t)
			if err != nil {
				broken++
				fmt.Fprintf(stdout, "%s: FAILED: %s\n", head, described(err))
				continue
			}
			repoURL := data["repo_url"]
			if !truthy(repoURL) {
				repoURL = ""
			}
			if !strings.EqualFold(strings.TrimRight(pyStr(repoURL), "/"), fmt.Sprintf("https://github.com/%s/%s", Org, t.repo)) {
				broken++
				fmt.Fprintf(stdout, "%s: FAILED: the project's repo_url is %s\n", head, pyStr(data["repo_url"]))
				continue
			}
			if !attLoaded {
				attLoaded = true
				if att, err = LoadAttestation(r); err != nil {
					fmt.Fprintf(stdout, "bestpractices: %s: %s\n", OwnerFile, described(err))
					att = nil
				}
			}
			reader, _ := r.(AlertReader)
			owner := ownerAnswers(att, t.repo, proposed, tree, reader)
			proposed = owner.merge(proposed)
			rep := Findings(t.repo, data, proposed, tree)
			info, items = rep.Info, rep.Items
			items = append(items, ownerDrift(data, owner)...)
			if len(owner.Unread) > 0 {
				info = append(info, fmt.Sprintf("%d alert listing(s) unreadable", len(owner.Unread)))
				// the issue run reads with the bot's token, which must read them (#611)
				if args.Issues && reader != nil {
					broken++
					for _, u := range owner.Unread {
						fmt.Fprintf(stdout, "%s: FAILED: the alerts: %s\n", head, u)
					}
				}
			}
			if args.Issues {
				bugs, err := alertBugs(gh, t.repo, owner, dryRun)
				if err != nil {
					broken++
					fmt.Fprintf(stdout, "%s: FAILED: the alert bugs: %s\n", head, described(err))
				}
				for _, b := range bugs {
					fmt.Fprintf(stdout, "    alert bug: %s\n", b)
				}
			}
			if !t.configured {
				items = append([]string{fmt.Sprintf("registered as project %s, but %s has no "+
					"bestpractices_project = \"%s\"", t.project, Config, t.project)}, items...)
			}
			if links, err = proposalLinks(t.project, proposed, rep); err != nil {
				broken++
				fmt.Fprintf(stdout, "%s: FAILED: %s\n", head, described(err))
				continue
			}
			if len(links) > 0 {
				info = append(info, fmt.Sprintf("%d proposal link(s)", len(links)))
			}
			body = Body(t.repo, t.project, items, links, rep.OwnerOpen, owner, runURL)
			ownerLines = ownerSection(rep.OwnerOpen, owner)
		}
		if len(items) > 0 {
			drift++
		}
		action := ""
		if args.Issues {
			a, err := syncIssue(gh, t.repo, items, links, ownerLines, body, dryRun, runURL)
			if err != nil {
				broken++
				action = "; issue: FAILED: " + described(err)
			} else {
				verb := ""
				if dryRun {
					switch strings.Fields(a)[0] {
					case "open", "update", "close":
						verb = "would "
					}
				}
				action = "; issue: " + verb + a
			}
		}
		fmt.Fprintf(stdout, "%s: %s; %d finding(s)%s\n", head, strings.Join(info, "; "), len(items), action)
		for _, i := range items {
			fmt.Fprintf(stdout, "    %s\n", i)
		}
		for i, l := range links {
			fmt.Fprintf(stdout, "    proposal %d: %s\n", i+1, l)
		}
	}
	if projects+unregistered == 0 && broken == 0 {
		fmt.Fprintf(stdout, "bestpractices: no repository is registered or in scope (%s)\n", Config)
		return 0
	}
	fmt.Fprintf(stdout, "bestpractices: %d project(s), %d in scope and not registered, %d drifting, %d unreadable\n",
		projects, unregistered, drift, broken)
	switch {
	case broken > 0:
		return 2
	case drift > 0 && !args.Issues:
		return 1
	}
	return 0
}

// envOrNone is os.environ.get(name): None when unset.
func envOrNone(env func(string) string, name string) any {
	if v := env(name); v != "" {
		return v
	}
	return nil
}

func read(r Remote, t target) (map[string]any, map[string]any, map[string]bool, error) {
	site, err := r.Site(t.project)
	if err != nil {
		return nil, nil, nil, err
	}
	text, ok, err := r.File(t.repo, Out)
	if err != nil {
		return nil, nil, nil, err
	}
	var proposedAny any = map[string]any{}
	if ok && text != "" {
		if proposedAny, err = decodeJSON([]byte(text)); err != nil {
			return nil, nil, nil, err
		}
	}
	data, okData := site.(map[string]any)
	proposed, okProposed := proposedAny.(map[string]any)
	if !okData || !okProposed {
		what := Out
		if !okData {
			what = "the site"
		}
		return nil, nil, nil, valueError("not a JSON object: " + what)
	}
	tree, err := r.Tree(t.repo)
	if err != nil {
		return nil, nil, nil, err
	}
	return data, proposed, tree, nil
}

// ownerLeft are the criteria Derive leaves to the owner (`?` in the file by
// design): a site answer there is the owner's, never drift.
func ownerLeft(c string) bool {
	if OwnerOnly[c] || c == "test_most" || c == "tests_are_added" || c == "static_analysis_fixed" {
		return true
	}
	for _, x := range Crypto {
		if x == c {
			return true
		}
	}
	return false
}

// workflowEvidence are the criteria Derive justifies by what a CI workflow
// runs (#559).
var workflowEvidence = regexp.MustCompile(`^(dynamic_analysis|static_analysis|test_continuous_integration|warnings)`)

// staleEvidence is the drift a saved answer keeps after Derive stopped
// finding its evidence (#559): Met on the site where the file now finds
// none (`?`), or, for a criterion justified by a CI workflow, the same
// answer citing a workflow the file no longer cites (proposed again with
// the file's justification). A hand-written justification elsewhere is the
// owner's and never drift.
func staleEvidence(repo string, data, proposed map[string]any, propose map[string]bool) []string {
	var out []string
	for _, c := range Passing {
		want, ok := proposed[c+"_status"]
		if !ok || ownerLeft(c) {
			continue
		}
		have := data[c+"_status"]
		if unanswered(want) {
			if pyEqual(have, "Met") {
				out = append(out, fmt.Sprintf("%s: the site says Met, %s finds no evidence for it on main", c, Out))
			}
			continue
		}
		if !pyEqual(have, want) || !workflowEvidence.MatchString(c) {
			continue
		}
		site, _ := data[c+"_justification"].(string)
		file := pyStr(proposed[c+"_justification"])
		for _, m := range urlIn.FindAllStringSubmatch(site, -1) {
			path := strings.TrimRight(m[3], ".,;:")
			if m[1] != Org || m[2] != repo || !strings.HasPrefix(path, ".github/workflows/") ||
				strings.Contains(file, "/blob/main/"+path) {
				continue
			}
			out = append(out, fmt.Sprintf("%s: the site's justification cites %s, %s no longer does", c, path, Out))
			propose[c] = true
			break
		}
	}
	return out
}

// ownerDrift: an attested criterion the site says is Met while an open
// alert stands against it; and each open alert that blocks one.
func ownerDrift(data map[string]any, owner OwnerReport) []string {
	var out []string
	for _, c := range attestedOrder {
		why, blocked := owner.Blocked[c]
		if blocked && strings.HasPrefix(why, "open ") && pyEqual(data[c+"_status"], "Met") {
			out = append(out, fmt.Sprintf("%s: the site says Met, but %s", c, why))
		}
	}
	for _, a := range owner.Alerts {
		out = append(out, "open security alert blocks an owner-only answer: "+a.String())
	}
	return out
}

// alertBugs opens one bug per open alert that blocks an attested answer,
// unless an open issue already names the alert's URL.
func alertBugs(gh GitHub, repo string, owner OwnerReport, dryRun bool) ([]string, error) {
	if len(owner.Alerts) == 0 || gh == nil {
		return nil, nil
	}
	got, err := gh.API("GET", fmt.Sprintf("repos/%s/%s/issues?state=open&labels=bug&per_page=100", Org, repo), nil, true)
	if err != nil {
		return nil, err
	}
	list, _ := got.([]any)
	var out []string
	for _, a := range owner.Alerts {
		found := ""
		for _, x := range list {
			i, _ := x.(map[string]any)
			if b, _ := i["body"].(string); strings.Contains(b, a.url) {
				found = pyStr(i["number"])
				break
			}
		}
		if found != "" {
			out = append(out, "#"+found+" (open) "+a.url)
			continue
		}
		if dryRun {
			out = append(out, "would open: "+a.url)
			continue
		}
		title := fmt.Sprintf("%s open %s alert #%s", Prefix, a.kind, a.number)
		body := strings.Join([]string{"## Context", "",
			"The weekly `bestpractices` check (swarm-routing/.github `cmd/bestpractices`) found an open " +
				"security alert that keeps an owner-only OpenSSF Best Practices answer `?` " +
				"(swarm-routing/.github#559, swarm-routing/AntHocNet#790):", "",
			"- " + a.String(), "",
			"## Acceptance criteria", "",
			"- [ ] The alert is fixed, or dismissed with its reason on the alert.",
			"- [ ] The next weekly check proposes the answer again on the `[bestpractices]` issue."}, "\n") + Footer
		res, err := gh.API("POST", fmt.Sprintf("repos/%s/%s/issues", Org, repo),
			map[string]any{"title": title, "body": body, "labels": []any{"bug", "packaging", "model:haiku-5.5", "priority:P2"}}, false)
		if err != nil {
			return out, err
		}
		m, _ := res.(map[string]any)
		out = append(out, "opened #"+pyStr(m["number"])+" "+a.url)
	}
	return out, nil
}
