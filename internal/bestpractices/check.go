// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"fmt"
	"io"
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

type target struct {
	repo, project string
	configured    bool
}

func projectOf(r Remote, repo string) (string, error) {
	text, ok, err := r.File(repo, Config)
	if err != nil {
		return "", err
	}
	if !ok || text == "" {
		return "", nil
	}
	cfg, err := parseTOML(text)
	if err != nil {
		return "", nil
	}
	v, ok := cfg["bestpractices_project"]
	if !ok {
		v = ""
	}
	p := strings.TrimSpace(tomlStr(v))
	if isDigits(p) {
		return p, nil
	}
	return "", nil
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

// targets: --repos entries (NAME=ID or NAME), else every public org
// repository. A repository whose config names no project is looked up on the
// site by its URL: registered there, it is checked and its missing key is a
// finding.
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
		configured, err := projectOf(r, repo)
		pid := strings.TrimSpace(given)
		if err == nil && pid == "" {
			pid = configured
			if pid == "" {
				pid, err = Registered(r, Org+"/"+repo)
			}
		}
		if err != nil {
			failed = append(failed, fmt.Sprintf("%s: FAILED: the lookup: %s", repo, described(err)))
			continue
		}
		if isDigits(pid) {
			out = append(out, target{repo, pid, configured != ""})
		} else if named {
			failed = append(failed, fmt.Sprintf("%s: FAILED: no bestpractices_project in %s, "+
				"and not registered on bestpractices.dev", repo, Config))
		}
	}
	return out, failed, nil
}

// Findings returns (info lines, finding lines) for one project: data is the
// site's JSON, proposed the repository's .bestpractices.json, tree main's
// paths.
func Findings(repo string, data, proposed map[string]any, tree map[string]bool) ([]string, []string) {
	get := func(m map[string]any, k string, def any) any {
		if v, ok := m[k]; ok {
			return v
		}
		return def
	}
	info := []string{fmt.Sprintf("level %s, passing %s%%", pyStr(get(data, "badge_level", "?")),
		pyStr(get(data, "badge_percentage_0", "?")))}
	var out []string
	unanswered := 0
	for _, c := range Passing {
		want := proposed[c+"_status"]
		have := data[c+"_status"]
		if !truthy(want) || pyEqual(want, "?") || pyEqual(want, "unknown") {
			continue
		}
		if have == nil || pyEqual(have, "?") || pyEqual(have, "unknown") {
			unanswered++
		} else if !pyEqual(have, want) {
			out = append(out, fmt.Sprintf("%s: the site says %s, %s says %s", c, pyStr(have), Out, pyStr(want)))
		}
	}
	if len(proposed) > 0 {
		info = append(info, fmt.Sprintf("%d criteria %s answers are not answered on the site yet", unanswered, Out))
	} else {
		info = append(info, "no "+Out+" on main")
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
	seen := map[string]bool{}
	var items []string
	for _, x := range out {
		if !seen[x] {
			seen[x] = true
			items = append(items, x)
		}
	}
	return info, items
}

// Title is the issue's title for these findings.
func Title(items []string) string { return fmt.Sprintf("%s %d finding(s)", Prefix, len(items)) }

// Body is the issue's body for these findings.
func Body(repo, project string, items []string, runURL string) string {
	run := "."
	if runURL != "" {
		run = fmt.Sprintf(" ([run](%s)).", runURL)
	}
	lines := []string{
		"## Context",
		"",
		fmt.Sprintf("The weekly `bestpractices` check (swarm-routing/.github `tools/bestpractices/`) "+
			"found `%s`'s OpenSSF Best Practices entry (%s/projects/%s) out of "+
			"step with the repository%s", repo, Site, project, run),
		"",
		"## Findings",
		"",
	}
	for _, i := range items {
		lines = append(lines, "- [ ] "+i)
	}
	lines = append(lines,
		"",
		"## Scope",
		"",
		fmt.Sprintf("bestpractices.dev has no write API, so a person fixes each one, logged in at "+
			"%s/projects/%s/passing: correct the answer, or regenerate `%s` "+
			"(`python3 -I ../.github/tools/bestpractices/bestpractices.py answers . --write`) and "+
			"press \"Save (and continue)\" with the robot; a justification pointing at a moved "+
			"file gets the new URL. A lost level is answered on the site first.", Site, project, Out),
		"",
		"This issue is updated in place by the weekly run and closed when the entry is clean.",
	)
	return strings.Join(lines, "\n") + Footer
}

func sameFindings(body string, items []string) bool {
	var got []string
	for _, x := range strings.Split(body, "\n") {
		x = strings.TrimSuffix(x, "\r")
		if strings.HasPrefix(x, "- [ ] ") || strings.HasPrefix(x, "- [x] ") {
			got = append(got, x[6:])
		}
	}
	if len(got) != len(items) {
		return false
	}
	for i := range got {
		if got[i] != items[i] {
			return false
		}
	}
	return true
}

func syncIssue(gh GitHub, repo, project string, items []string, dryRun bool, runURL string) (string, error) {
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
	title, body := Title(items), Body(repo, project, items, runURL)
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
	if issue["title"] == title && sameFindings(oldBody, items) {
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

// Check compares every registered project with its repository and returns
// the exit code: 0 clean, 1 drift, 2 a project could not be read. env gives
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
	if len(todo) == 0 && len(failed) == 0 {
		fmt.Fprintf(stdout, "bestpractices: no repository names bestpractices_project in %s\n", Config)
		return 0
	}
	drift, broken := 0, len(failed)
	for _, t := range todo {
		data, proposed, tree, err := read(r, t)
		if err != nil {
			broken++
			fmt.Fprintf(stdout, "%s (project %s): FAILED: %s\n", t.repo, t.project, described(err))
			continue
		}
		repoURL := data["repo_url"]
		if !truthy(repoURL) {
			repoURL = ""
		}
		if !strings.EqualFold(strings.TrimRight(pyStr(repoURL), "/"), fmt.Sprintf("https://github.com/%s/%s", Org, t.repo)) {
			broken++
			fmt.Fprintf(stdout, "%s (project %s): FAILED: the project's repo_url is %s\n", t.repo, t.project, pyStr(data["repo_url"]))
			continue
		}
		info, items := Findings(t.repo, data, proposed, tree)
		if !t.configured {
			items = append([]string{fmt.Sprintf("registered as project %s, but %s has no "+
				"bestpractices_project = \"%s\"", t.project, Config, t.project)}, items...)
		}
		if len(items) > 0 {
			drift++
		}
		action := ""
		if args.Issues {
			a, err := syncIssue(gh, t.repo, t.project, items, dryRun, runURL)
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
		fmt.Fprintf(stdout, "%s (project %s): %s; %d finding(s)%s\n", t.repo, t.project, strings.Join(info, "; "), len(items), action)
		for _, i := range items {
			fmt.Fprintf(stdout, "    %s\n", i)
		}
	}
	fmt.Fprintf(stdout, "bestpractices: %d project(s), %d drifting, %d unreadable\n", len(todo), drift, broken)
	switch {
	case broken > 0:
		return 2
	case drift > 0:
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
