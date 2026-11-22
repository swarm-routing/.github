// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package citoolsdigest is org-bot's `ci-tools-digest` task (#533): it moves
// every `ghcr.io/swarm-routing/ci-tools@sha256:<digest>` pin in the org's
// public repositories to the image ci-tools-image.yml last promoted, by one
// pull request per repository, so no digest is ever bumped by hand.
//
// The digest comes from the caller (org-bot.yml resolves `ci-tools:latest`
// and verifies its keyless signature by ci-tools-image.yml on main before it
// runs this tool from that very digest). The tool then reads, from the
// registry, the commit each image was built from (its revision label), and
// moves a pin only forward: the new image's commit must be ahead of, or the
// same as, the pinned image's (the compare API here). A pin whose image it
// cannot place is left as it is, and said so.
//
// In each repository it reads the YAML files under .github/workflows/ and
// .github/actions/ (here also templates/) on the default branch, skips the
// files org-sync manages elsewhere (their first line is ManagedMarker: the
// template here carries their pins), and when a pin moves:
//   - an open pull request of someone else that changes the same pin in the
//     same file holds the repository (a hand bump is left alone);
//   - otherwise one commit on org-bot/ci-tools-digest (made through the git
//     data API, so the App signs it), one pull request titled
//     `chore(deps): bump ci-tools to sha-<sha7>`, opened or updated in place,
//     with auto-merge (squash) on.
//
// A repository whose pins are all current closes the task's open pull
// request, if any, as superseded. At most MaxActions repositories are
// written a run (golden rule 7); the rest wait for the next run.
package citoolsdigest

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"sort"
	"strings"

	"github.com/swarm-routing/.github/internal/github"
)

const (
	// Org is the organization whose pins move; Home is this repository.
	Org  = "swarm-routing"
	Home = Org + "/.github"
	// Image is the pinned image, without its digest.
	Image    = "ghcr.io/" + repoPath
	repoPath = Org + "/ci-tools"
	// Branch carries the task's pull request in each repository.
	Branch = "org-bot/ci-tools-digest"
	// ManagedMarker begins every file org-sync renders from templates/.
	ManagedMarker = "# Managed by swarm-routing/.github tools/org-sync"
	// MaxActions bounds the repositories written in one run.
	MaxActions = 30
	maxFiles   = 400
	maxPages   = 20
)

var (
	pinRe      = regexp.MustCompile(`ghcr\.io/swarm-routing/ci-tools@(sha256:[0-9a-f]{64})`)
	promotedRe = regexp.MustCompile(`#\s*promoted from [0-9a-f]{7,40}\b.*$`)
	repoName   = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

// Pins lists the distinct digests text pins, sorted.
func Pins(text string) []string {
	set := map[string]bool{}
	for _, m := range pinRe.FindAllStringSubmatch(text, -1) {
		set[m[1]] = true
	}
	out := make([]string, 0, len(set))
	for d := range set {
		out = append(out, d)
	}
	sort.Strings(out)
	return out
}

// Rewrite moves every pin in text that is not digest, and that move allows,
// to digest. On a line it changed, a `# promoted from <commit> …` comment
// becomes `# promoted from <sha7>` (the reason it named belonged to the old
// image); every other byte is kept.
func Rewrite(text, digest, sha7 string, move func(old string) bool) string {
	lines := strings.SplitAfter(text, "\n")
	for i, line := range lines {
		changed := false
		out := pinRe.ReplaceAllStringFunc(line, func(m string) string {
			old := m[len(Image)+1:]
			if old == digest || !move(old) {
				return m
			}
			changed = true
			return Image + "@" + digest
		})
		if changed {
			body, nl := strings.CutSuffix(out, "\n")
			body = promotedRe.ReplaceAllString(body, "# promoted from "+sha7)
			if nl {
				body += "\n"
			}
			out = body
		}
		lines[i] = out
	}
	return strings.Join(lines, "")
}

// candidate is whether a path of the default branch's tree is read.
func candidate(path string, home bool) bool {
	if !strings.HasSuffix(path, ".yml") && !strings.HasSuffix(path, ".yaml") {
		return false
	}
	return strings.HasPrefix(path, ".github/workflows/") || strings.HasPrefix(path, ".github/actions/") ||
		(home && strings.HasPrefix(path, "templates/"))
}

// Result counts what a run did (or, dry, would do).
type Result struct{ Opened, Updated, Current, Held, Closed, Kept, Deferred, Failed int }

// Tool is one run: the GitHub client, the registry, dry or not, the output.
type Tool struct {
	GH  github.Client
	Reg *Registry
	Dry bool
	Out io.Writer

	digest, rev string
	moves       map[string]bool   // old digest -> may move
	unsure      map[string]bool   // old digest -> its image could not be placed (an error, not a verdict)
	revs        map[string]string // old digest -> its commit
	budget      int
	res         Result
}

func (t *Tool) do(method, path string, body, out any) error {
	data, err := t.GH.Do(method, path, body)
	if err != nil || out == nil {
		return err
	}
	if err := json.Unmarshal(data, out); err != nil {
		return fmt.Errorf("%s %s: %v", method, path, err)
	}
	return nil
}

// move is whether a pin of old may move to the new image: only forward.
func (t *Tool) move(old string) bool {
	if ok, seen := t.moves[old]; seen {
		return ok
	}
	ok := false
	rev, err := t.Reg.Revision(old)
	switch {
	case err != nil:
		t.unsure[old] = true
		fmt.Fprintf(t.Out, "keep %s: its commit is unknown (%v)\n", old, err)
	default:
		var c struct {
			Status string `json:"status"`
		}
		if err := t.do("GET", fmt.Sprintf("repos/%s/compare/%s...%s", Home, rev, t.rev), nil, &c); err != nil {
			t.unsure[old] = true
			fmt.Fprintf(t.Out, "keep %s (from %s): compare failed (%v)\n", old, rev[:7], err)
		} else if c.Status == "ahead" || c.Status == "identical" {
			ok = true
			t.revs[old] = rev
		} else {
			fmt.Fprintf(t.Out, "keep %s (from %s): %s is %s of it, never moved back\n", old, rev[:7], t.rev[:7], c.Status)
		}
	}
	if !ok {
		t.res.Kept++
	}
	t.moves[old] = ok
	return ok
}

type repo struct {
	Name          string `json:"name"`
	FullName      string `json:"full_name"`
	DefaultBranch string `json:"default_branch"`
	Archived      bool   `json:"archived"`
	Private       bool   `json:"private"`
}

type pull struct {
	Number int    `json:"number"`
	NodeID string `json:"node_id"`
	Head   struct {
		Ref string `json:"ref"`
		SHA string `json:"sha"`
	} `json:"head"`
}

type change struct{ path, mode, text string }

func (t *Tool) repos(names []string) ([]repo, error) {
	if len(names) == 0 {
		all, err := github.List[repo](t.GH, "orgs/"+Org+"/repos?type=public", maxPages)
		sort.Slice(all, func(i, j int) bool { return strings.ToLower(all[i].Name) < strings.ToLower(all[j].Name) })
		return all, err
	}
	var out []repo
	for _, n := range names {
		if !repoName.MatchString(n) {
			return nil, fmt.Errorf("%q is not a repository name", n)
		}
		var r repo
		if err := t.do("GET", "repos/"+Org+"/"+n, nil, &r); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

// Run moves every pin to digest in the repositories names lists (every
// public one when empty).
func (t *Tool) Run(digest string, names []string) (Result, error) {
	if !digestRe.MatchString(digest) {
		return t.res, fmt.Errorf("%q is not a sha256 digest", digest)
	}
	rev, err := t.Reg.Revision(digest)
	if err != nil {
		return t.res, fmt.Errorf("the new image: %v", err)
	}
	t.digest, t.rev = digest, rev
	t.moves, t.unsure, t.revs, t.budget = map[string]bool{}, map[string]bool{}, map[string]string{}, MaxActions
	fmt.Fprintf(t.Out, "ci-tools-digest: %s@%s, promoted from %s\n", Image, digest, rev[:7])
	repos, err := t.repos(names)
	if err != nil {
		return t.res, err
	}
	for _, r := range repos {
		if r.Archived || r.Private {
			continue
		}
		if err := t.repo(r); err != nil {
			t.res.Failed++
			fmt.Fprintf(t.Out, "%s: FAILED: %v\n", r.FullName, err)
		}
	}
	fmt.Fprintf(t.Out, "ci-tools-digest: %d opened, %d updated, %d current, %d held by a hand PR, %d closed, %d pins kept, %d deferred, %d failed%s\n",
		t.res.Opened, t.res.Updated, t.res.Current, t.res.Held, t.res.Closed, t.res.Kept, t.res.Deferred, t.res.Failed,
		map[bool]string{true: " (dry run: nothing written)", false: ""}[t.Dry])
	if t.res.Failed > 0 {
		return t.res, fmt.Errorf("%d repositories failed", t.res.Failed)
	}
	return t.res, nil
}

func (t *Tool) blob(full, sha string) (string, error) {
	var b struct {
		Content  string `json:"content"`
		Encoding string `json:"encoding"`
	}
	if err := t.do("GET", fmt.Sprintf("repos/%s/git/blobs/%s", full, sha), nil, &b); err != nil {
		return "", err
	}
	if b.Encoding != "base64" {
		return "", fmt.Errorf("blob %s of %s: encoding %q", sha, full, b.Encoding)
	}
	data, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(b.Content, "\n", ""))
	return string(data), err
}

func (t *Tool) repo(r repo) error {
	full := r.FullName
	var ref struct {
		Object struct {
			SHA string `json:"sha"`
		} `json:"object"`
	}
	if err := t.do("GET", fmt.Sprintf("repos/%s/git/ref/heads/%s", full, r.DefaultBranch), nil, &ref); err != nil {
		if github.Status(err) == http.StatusNotFound || github.Status(err) == http.StatusConflict {
			return nil // an empty repository
		}
		return err
	}
	head := ref.Object.SHA
	var commit struct {
		Tree struct {
			SHA string `json:"sha"`
		} `json:"tree"`
	}
	if err := t.do("GET", fmt.Sprintf("repos/%s/git/commits/%s", full, head), nil, &commit); err != nil {
		return err
	}
	var tree struct {
		Truncated bool `json:"truncated"`
		Tree      []struct {
			Path, Mode, Type, SHA string
		} `json:"tree"`
	}
	if err := t.do("GET", fmt.Sprintf("repos/%s/git/trees/%s?recursive=1", full, commit.Tree.SHA), nil, &tree); err != nil {
		return err
	}
	if tree.Truncated {
		return fmt.Errorf("the tree of %s is truncated", head[:7])
	}
	var changes []change
	moved := map[string]bool{}
	unsure := false
	read := 0
	for _, e := range tree.Tree {
		if e.Type != "blob" || !candidate(e.Path, full == Home) {
			continue
		}
		if read++; read > maxFiles {
			return fmt.Errorf("more than %d workflow files", maxFiles)
		}
		text, err := t.blob(full, e.SHA)
		if err != nil {
			return err
		}
		if strings.HasPrefix(text, ManagedMarker) || !pinRe.MatchString(text) {
			continue
		}
		next := Rewrite(text, t.digest, t.rev[:7], t.move)
		for _, d := range Pins(text) {
			if d != t.digest && t.moves[d] {
				moved[d] = true
			}
			unsure = unsure || t.unsure[d]
		}
		if next == text {
			continue
		}
		changes = append(changes, change{e.Path, e.Mode, next})
	}
	bots, err := github.List[pull](t.GH, fmt.Sprintf("repos/%s/pulls?state=open&head=%s:%s", full, Org, Branch), maxPages)
	if err != nil {
		return err
	}
	if len(changes) == 0 {
		if len(bots) == 0 {
			t.res.Current++
			return nil
		}
		if unsure {
			// a pin kept for an error, not a verdict: the pull request may still be right
			fmt.Fprintf(t.Out, "%s: #%d left open: a pin's image could not be placed\n", full, bots[0].Number)
			return nil
		}
		return t.close(full, bots[0].Number)
	}
	paths := make([]string, 0, len(changes))
	for _, c := range changes {
		paths = append(paths, c.path)
	}
	if n, err := t.hand(full, paths); err != nil {
		return err
	} else if n > 0 {
		t.res.Held++
		fmt.Fprintf(t.Out, "%s: held: #%d bumps the same pin by hand\n", full, n)
		return nil
	}
	if t.budget <= 0 {
		t.res.Deferred++
		fmt.Fprintf(t.Out, "%s: %d files to move; deferred (%d repositories a run)\n", full, len(changes), MaxActions)
		return nil
	}
	t.budget--
	sha7 := t.rev[:7]
	title := "chore(deps): bump ci-tools to sha-" + sha7
	body := t.body(moved, paths)
	verb := "open"
	if len(bots) > 0 {
		verb = fmt.Sprintf("update #%d", bots[0].Number)
	}
	if t.Dry {
		fmt.Fprintf(t.Out, "%s: would %s %q on %s: %s\n", full, verb, title, Branch, strings.Join(paths, ", "))
		if len(bots) > 0 {
			t.res.Updated++
		} else {
			t.res.Opened++
		}
		return nil
	}
	entries := make([]map[string]string, 0, len(changes))
	for _, c := range changes {
		entries = append(entries, map[string]string{"path": c.path, "mode": c.mode, "type": "blob", "content": c.text})
	}
	var made struct {
		SHA string `json:"sha"`
	}
	if err := t.do("POST", fmt.Sprintf("repos/%s/git/trees", full), map[string]any{"base_tree": commit.Tree.SHA, "tree": entries}, &made); err != nil {
		return err
	}
	if len(bots) > 0 {
		var cur struct {
			Tree struct {
				SHA string `json:"sha"`
			} `json:"tree"`
			Parents []struct {
				SHA string `json:"sha"`
			} `json:"parents"`
		}
		if err := t.do("GET", fmt.Sprintf("repos/%s/git/commits/%s", full, bots[0].Head.SHA), nil, &cur); err == nil &&
			cur.Tree.SHA == made.SHA && len(cur.Parents) == 1 && cur.Parents[0].SHA == head {
			t.res.Current++
			fmt.Fprintf(t.Out, "%s: already proposed in #%d\n", full, bots[0].Number)
			return nil
		}
	}
	var c struct {
		SHA string `json:"sha"`
	}
	msg := title + "\n\n" + body
	if err := t.do("POST", fmt.Sprintf("repos/%s/git/commits", full), map[string]any{"message": msg, "tree": made.SHA, "parents": []string{head}}, &c); err != nil {
		return err
	}
	if err := t.do("GET", fmt.Sprintf("repos/%s/git/ref/heads/%s", full, Branch), nil, nil); err != nil {
		if github.Status(err) != http.StatusNotFound {
			return err
		}
		if err := t.do("POST", fmt.Sprintf("repos/%s/git/refs", full), map[string]string{"ref": "refs/heads/" + Branch, "sha": c.SHA}, nil); err != nil {
			return err
		}
	} else if err := t.do("PATCH", fmt.Sprintf("repos/%s/git/refs/heads/%s", full, Branch), map[string]any{"sha": c.SHA, "force": true}, nil); err != nil {
		// the task's own branch, rebuilt on the default branch each time
		return err
	}
	var pr pull
	done := "opened"
	if len(bots) > 0 {
		if err := t.do("PATCH", fmt.Sprintf("repos/%s/pulls/%d", full, bots[0].Number), map[string]string{"title": title, "body": body}, &pr); err != nil {
			return err
		}
		t.res.Updated++
		done = "updated"
	} else {
		if err := t.do("POST", fmt.Sprintf("repos/%s/pulls", full), map[string]string{"title": title, "head": Branch, "base": r.DefaultBranch, "body": body}, &pr); err != nil {
			return err
		}
		t.res.Opened++
	}
	fmt.Fprintf(t.Out, "%s: %s #%d %q: %s; %s\n", full, done, pr.Number, title, strings.Join(paths, ", "), t.autoMerge(pr.NodeID))
	return nil
}

// hand is the number of another open pull request that changes a ci-tools
// pin in one of paths (0: none).
func (t *Tool) hand(full string, paths []string) (int, error) {
	want := map[string]bool{}
	for _, p := range paths {
		want[p] = true
	}
	open, err := github.List[pull](t.GH, fmt.Sprintf("repos/%s/pulls?state=open", full), maxPages)
	if err != nil {
		return 0, err
	}
	type file struct {
		Filename string `json:"filename"`
		Patch    string `json:"patch"`
	}
	for _, p := range open {
		if p.Head.Ref == Branch {
			continue
		}
		files, err := github.List[file](t.GH, fmt.Sprintf("repos/%s/pulls/%d/files?", full, p.Number), 3)
		if err != nil {
			return 0, err
		}
		for _, f := range files {
			if want[f.Filename] && strings.Contains(f.Patch, "ci-tools@sha256:") {
				return p.Number, nil
			}
		}
	}
	return 0, nil
}

// close closes the task's open pull request once every pin is current.
func (t *Tool) close(full string, n int) error {
	t.res.Closed++
	if t.Dry {
		fmt.Fprintf(t.Out, "%s: would close #%d: every pin is current\n", full, n)
		return nil
	}
	text := "Every ci-tools pin here is already at " + t.digest + " (promoted from " + t.rev[:7] +
		") or held at an image it may not move from, so this pull request is superseded. Closing it." + footer
	if err := t.do("POST", fmt.Sprintf("repos/%s/issues/%d/comments", full, n), map[string]string{"body": text}, nil); err != nil {
		return err
	}
	if err := t.do("PATCH", fmt.Sprintf("repos/%s/pulls/%d", full, n), map[string]string{"state": "closed"}, nil); err != nil {
		return err
	}
	fmt.Fprintf(t.Out, "%s: closed #%d: every pin is current\n", full, n)
	return nil
}

const footer = "\n\n---\n_Generated by org-bot's `ci-tools-digest` task (swarm-routing/.github#533)_"

func (t *Tool) body(moved map[string]bool, paths []string) string {
	sha7 := t.rev[:7]
	var b strings.Builder
	fmt.Fprintf(&b, "Moves every `%s` pin here to the image `ci-tools-image.yml` promoted from swarm-routing/.github@%s (`ci-tools:sha-%s`):\n\n`%s`\n\n", Image, sha7, sha7, t.digest)
	b.WriteString("Pins moved, with what changed since the image each named:\n\n")
	olds := make([]string, 0, len(moved))
	for d := range moved {
		olds = append(olds, d)
	}
	sort.Strings(olds)
	for _, d := range olds {
		r := t.revs[d][:7]
		fmt.Fprintf(&b, "- `%s` (promoted from %s): https://github.com/%s/compare/%s...%s\n", d, r, Home, r, sha7)
	}
	b.WriteString("\nFiles:\n\n")
	for _, p := range paths {
		fmt.Fprintf(&b, "- `%s`\n", p)
	}
	b.WriteString("\nThe digest is read from the registry (`ci-tools:latest`, its keyless signature by `ci-tools-image.yml` on `main` verified before the run), never typed, and a pin moves only forward: the new image's commit is ahead of the pinned image's (each image's `" + RevisionLabel + "` label). Files org-sync manages move with their template in swarm-routing/.github.")
	b.WriteString(footer)
	return b.String()
}

// autoMerge turns on auto-merge (squash) for the pull request; GraphQL is the
// only API for it. Its outcome is a phrase for the run's line, never an error:
// the pull request stands either way.
func (t *Tool) autoMerge(node string) string {
	if node == "" {
		return "auto-merge not enabled (no node id): merge once green"
	}
	q := map[string]any{
		"query":     "mutation($pr: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $pr, mergeMethod: SQUASH}) { clientMutationId } }",
		"variables": map[string]string{"pr": node},
	}
	var out struct {
		Errors []struct {
			Message string `json:"message"`
		} `json:"errors"`
	}
	if err := t.do("POST", "graphql", q, &out); err != nil {
		return fmt.Sprintf("auto-merge not enabled (%v): merge once green", err)
	}
	if len(out.Errors) > 0 {
		return fmt.Sprintf("auto-merge not enabled (%s): merge once green", out.Errors[0].Message)
	}
	return "auto-merge on"
}

const usage = "usage: ci-tools-digest --digest sha256:<64 hex> [--repos a,b] [--dry-run]\n" +
	"  moves every " + Image + "@sha256 pin in the org's public repositories to that image, by pull request"

// Main is the command: arguments, environment, HTTP client, the API and
// registry bases, the output streams; it returns the exit code.
func Main(args []string, getenv func(string) string, client *http.Client, api, registry string, stdout, stderr io.Writer) int {
	dry, digest := false, ""
	var names []string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case a == "--digest" && i+1 < len(args):
			digest = args[i+1]
			i++
		case a == "--repos" && i+1 < len(args):
			for _, n := range strings.Split(args[i+1], ",") {
				if n = strings.TrimSpace(n); n != "" {
					names = append(names, n)
				}
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
	if digest == "" {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	token := getenv("GH_TOKEN")
	if token == "" && !dry {
		fmt.Fprintln(stdout, "ci-tools-digest: no GH_TOKEN: dry run")
		dry = true
	}
	t := &Tool{
		GH:  github.Client{API: api, Token: token, UserAgent: "swarm-routing-ci-tools-digest", HTTP: client},
		Reg: &Registry{Base: registry, Client: client},
		Dry: dry,
		Out: stdout,
	}
	if _, err := t.Run(digest, names); err != nil {
		fmt.Fprintln(stderr, "ci-tools-digest:", err)
		return 1
	}
	return 0
}
