// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"fmt"
	"io"
	"math/big"
	"os"
	"strings"
)

// Searcher looks projects up on the site by their repository URL.
type Searcher interface {
	// Search returns the site's /projects.json?url=<repoURL> answer: the
	// projects whose repo or home page URL is exactly repoURL.
	Search(repoURL string) (any, error)
}

// Registered returns the project id bestpractices.dev holds for
// https://github.com/<slug>, else "".
func Registered(s Searcher, slug string) (string, error) {
	url := "https://github.com/" + slug
	got, err := s.Search(url)
	if err != nil {
		return "", err
	}
	list, _ := got.([]any)
	if len(list) > maxSearchHits {
		list = list[:maxSearchHits]
	}
	var best *big.Float
	bestText := ""
	for _, h := range list {
		m, ok := h.(map[string]any)
		if !ok {
			continue
		}
		repo, ok := m["repo_url"]
		if !ok {
			repo = ""
		}
		if !strings.EqualFold(strings.TrimRight(pyStr(repo), "/"), url) {
			continue
		}
		id := m["id"]
		f, ok := new(big.Float).SetString(pyStr(id))
		if !ok {
			return "", valueError(fmt.Sprintf("project id %s", pyStr(id)))
		}
		if best == nil || f.Cmp(best) < 0 {
			best, bestText = f, pyStr(id)
		}
	}
	return bestText, nil
}

// LoadAnswers reads a .bestpractices.json: the passing criteria it answers.
func LoadAnswers(path string) (Answers, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, failure("bestpractices: %s: %v", path, err)
	}
	v, err := decodeJSON(b)
	if err != nil {
		return nil, failure("bestpractices: %s: %v", path, err)
	}
	data, ok := v.(map[string]any)
	if !ok {
		return nil, failure("bestpractices: %s: not a JSON object", path)
	}
	var out Answers
	for _, c := range Passing {
		st, ok := data[c+"_status"]
		if !ok {
			continue
		}
		why := ""
		if j, ok := data[c+"_justification"]; ok {
			why = pyStr(j)
		}
		out = append(out, Answer{c, pyStr(st), why})
	}
	return out, nil
}

// ProposalURLs returns the site's automation-proposal links for an existing
// project (/en/projects/<id>/<section>/edit?<criterion>_status=..&..):
// every answered criterion except the owner-only ones, split into links of
// at most limit characters, never splitting one criterion's pair. Opening
// one changes nothing: the logged-in maintainer reviews and saves.
func ProposalURLs(project string, ans Answers, section string, limit int) ([]string, error) {
	base := fmt.Sprintf("%s/en/projects/%s/%s/edit?", Site, project, section)
	var urls, cur []string
	for _, a := range ans {
		if a.Status == "?" || a.Status == "unknown" || OwnerOnly[a.Criterion] {
			continue
		}
		part := quote(a.Criterion+"_status") + "=" + quote(a.Status)
		if a.Why != "" {
			part += "&" + quote(a.Criterion+"_justification") + "=" + quote(a.Why)
		}
		if len(base)+len(part) > limit {
			return nil, failure("bestpractices: %s: its answer alone is over %d characters", a.Criterion, limit)
		}
		if len(cur) > 0 && len(base)+len(strings.Join(append(append([]string{}, cur...), part), "&")) > limit {
			urls = append(urls, base+strings.Join(cur, "&"))
			cur = nil
		}
		cur = append(cur, part)
	}
	if len(cur) > 0 {
		urls = append(urls, base+strings.Join(cur, "&"))
	}
	return urls, nil
}

// Register prints, for a registered repository, its id, the org-sync line
// and the proposal links; otherwise where to register (the site has no
// pre-filled registration form: /en/projects?as=edit needs an existing
// project) and that this command then gives the proposal links.
func Register(slug, repoDir, today, answersFile string, s Searcher, stdout, stderr io.Writer) error {
	pid, err := Registered(s, slug)
	if err != nil {
		return err
	}
	if pid == "" {
		fmt.Fprintf(stdout, "%s is not registered on bestpractices.dev.\n", slug)
		fmt.Fprintf(stdout, "1. Logged in, add it at %s/en/projects/new with https://github.com/%s\n", Site, slug)
		fmt.Fprintln(stdout, "2. Run this command again: it prints the proposal links for the new project.")
		return nil
	}
	fmt.Fprintf(stdout, "%s is registered: %s/projects/%s\n", slug, Site, pid)
	fmt.Fprintf(stdout, "add to %s: bestpractices_project = \"%s\" (if it is not there yet)\n", Config, pid)
	if repoDir == "" {
		repoDir = pyJoin("..", strings.SplitN(slug, "/", 2)[1])
	}
	var ans Answers
	switch {
	case answersFile != "":
		ans, err = LoadAnswers(answersFile)
	case isFile(pyJoin(repoDir, Out)):
		ans, err = LoadAnswers(pyJoin(repoDir, Out))
	case isDirPath(repoDir):
		ans, err = Derive(repoDir, slug, today)
	default:
		fmt.Fprintf(stderr, "bestpractices: no checkout at %s: pass --dir for the proposal links\n", repoDir)
		return nil
	}
	if err != nil {
		return err
	}
	urls, err := ProposalURLs(pid, ans, "passing", ProposalLimit)
	if err != nil {
		return err
	}
	fmt.Fprintf(stdout, "Proposal links (open each logged in, review, Save; owner-only criteria left out): %d\n", len(urls))
	longest := 0
	for i, u := range urls {
		fmt.Fprintf(stdout, "%d. %s\n", i+1, u)
		longest = max(longest, len(u))
	}
	fmt.Fprintf(stderr, "bestpractices: %s; %d link(s), longest %d characters\n", ans.Summary(), len(urls), longest)
	return nil
}

func isFile(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.Mode().IsRegular()
}

func isDirPath(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.IsDir()
}
