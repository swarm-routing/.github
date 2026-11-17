// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package projectsync

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

const (
	// maxPages bounds every listing (100 a page).
	maxPages = 30
	// restVersion is the REST API version; viewsVersion the one the views
	// endpoint is documented under.
	restVersion  = "2022-11-28"
	viewsVersion = "2026-03-10"
)

// GitHub is the API client: REST for repositories, labels and issues, and
// for creating a view (the one write GraphQL lacks); GraphQL for the
// project itself (the exception recorded in docs/adr/0002-pipelines-are-go.md).
type GitHub struct {
	API    string // https://api.github.com
	Token  string
	Client *http.Client
	// Pause is the wait after each write, under GitHub's secondary rate
	// limits on content-creating requests.
	Pause time.Duration
	Sleep func(time.Duration)
}

func (g GitHub) redact(s string) string {
	if g.Token != "" {
		s = strings.ReplaceAll(s, g.Token, "[redacted]")
	}
	return s
}

func (g GitHub) do(method, path, version string, body any) ([]byte, error) {
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
	req.Header.Set("X-GitHub-Api-Version", version)
	req.Header.Set("User-Agent", "swarm-routing-project-sync")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if g.Token != "" {
		req.Header.Set("Authorization", "Bearer "+g.Token)
	}
	resp, err := g.Client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %s", method, path, g.redact(err.Error()))
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg := strings.TrimSpace(string(data))
		if len(msg) > 300 {
			msg = msg[:300]
		}
		return nil, fmt.Errorf("%s %s: HTTP %d: %s", method, path, resp.StatusCode, g.redact(msg))
	}
	return data, nil
}

func (g GitHub) pause() {
	if g.Pause > 0 && g.Sleep != nil {
		g.Sleep(g.Pause)
	}
}

// list reads every page of a REST listing (path has a query already).
func list[T any](g GitHub, path string) ([]T, error) {
	var all []T
	for page := 1; page <= maxPages; page++ {
		data, err := g.do("GET", fmt.Sprintf("%s&per_page=100&page=%d", path, page), restVersion, nil)
		if err != nil {
			return nil, err
		}
		var got []T
		if err := json.Unmarshal(data, &got); err != nil {
			return nil, fmt.Errorf("GET %s: %v", path, err)
		}
		all = append(all, got...)
		if len(got) < 100 {
			return all, nil
		}
	}
	return nil, fmt.Errorf("GET %s: more than %d pages", path, maxPages)
}

// Repo is the part of a repository the sync reads.
type Repo struct {
	Name     string `json:"name"`
	Private  bool   `json:"private"`
	Archived bool   `json:"archived"`
}

// Repos is the definition's repositories, or every public org repository;
// archived ones are left out. Private ones are returned so the caller can
// refuse them by name.
func (g GitHub) Repos(org string, names []string) ([]Repo, error) {
	var out []Repo
	if len(names) == 0 {
		all, err := list[Repo](g, "orgs/"+org+"/repos?type=public")
		if err != nil {
			return nil, err
		}
		out = all
	} else {
		for _, n := range names {
			data, err := g.do("GET", "repos/"+org+"/"+n, restVersion, nil)
			if err != nil {
				return nil, err
			}
			var r Repo
			if err := json.Unmarshal(data, &r); err != nil {
				return nil, err
			}
			out = append(out, r)
		}
	}
	kept := out[:0]
	for _, r := range out {
		if !r.Archived {
			kept = append(kept, r)
		}
	}
	sort.Slice(kept, func(i, j int) bool { return strings.ToLower(kept[i].Name) < strings.ToLower(kept[j].Name) })
	return kept, nil
}

// Issues is every issue of a repository an add rule takes (pull requests
// left out), each once, in number order.
func (g GitHub) Issues(org, repo string, d *Definition) ([]Issue, error) {
	var labels []string
	needPrefix := false
	for _, r := range d.Add {
		if r.LabelPrefix != "" {
			needPrefix = true
		}
	}
	if needPrefix {
		all, err := list[struct {
			Name string `json:"name"`
		}](g, "repos/"+org+"/"+repo+"/labels?")
		if err != nil {
			return nil, err
		}
		for _, l := range all {
			for _, r := range d.Add {
				if r.LabelPrefix != "" && strings.HasPrefix(l.Name, r.LabelPrefix) {
					labels = append(labels, l.Name)
					break
				}
			}
		}
	}
	for _, r := range d.Add {
		if r.Label != "" {
			labels = append(labels, r.Label)
		}
	}
	sort.Strings(labels)
	byID := map[string]Issue{}
	for i, l := range labels {
		if i > 0 && labels[i-1] == l {
			continue
		}
		iss, err := list[Issue](g, "repos/"+org+"/"+repo+"/issues?state=all&labels="+url.QueryEscape(l))
		if err != nil {
			return nil, err
		}
		for _, x := range iss {
			if x.PullRequest != nil {
				continue
			}
			x.Repo = repo
			if d.Matches(x) {
				byID[x.NodeID] = x
			}
		}
	}
	out := make([]Issue, 0, len(byID))
	for _, x := range byID {
		out = append(out, x)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Number < out[j].Number })
	return out, nil
}

// gqlError is a GraphQL error list.
type gqlError struct {
	Message string `json:"message"`
	Type    string `json:"type"`
}

// GraphQL runs one query or mutation and decodes its data into out.
func (g GitHub) GraphQL(query string, vars map[string]any, out any) error {
	data, err := g.do("POST", "graphql", restVersion, map[string]any{"query": query, "variables": vars})
	if err != nil {
		return err
	}
	var resp struct {
		Data   json.RawMessage `json:"data"`
		Errors []gqlError      `json:"errors"`
	}
	if err := json.Unmarshal(data, &resp); err != nil {
		return fmt.Errorf("graphql: %v", err)
	}
	if len(resp.Errors) > 0 {
		var m []string
		for _, e := range resp.Errors {
			m = append(m, g.redact(e.Message))
		}
		return fmt.Errorf("graphql %s: %s", opName(query), strings.Join(m, "; "))
	}
	if out != nil {
		return json.Unmarshal(resp.Data, out)
	}
	return nil
}

func opName(q string) string {
	f := strings.Fields(q)
	if len(f) >= 2 {
		return strings.SplitN(f[1], "(", 2)[0]
	}
	return "?"
}
