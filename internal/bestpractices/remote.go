// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"time"
)

const maxBody = 32 << 20 // bytes read from one response

// HTTP is the real network: bestpractices.dev's public JSON (GET only, one
// request a second at most, as its API documentation asks; never a POST)
// and the GitHub REST API with a token.
type HTTP struct {
	Client  *http.Client
	SiteURL string // default Site
	APIURL  string // default https://api.github.com
	Token   string // GitHub token; empty: anonymous reads
	Sleep   func(time.Duration)
	Now     func() time.Time
	last    time.Time
}

// NewHTTP returns the real network with token for GitHub.
func NewHTTP(token, apiURL string) *HTTP {
	if apiURL == "" {
		apiURL = "https://api.github.com"
	}
	return &HTTP{
		Client: &http.Client{Timeout: 30 * time.Second}, SiteURL: Site, APIURL: apiURL,
		Token: token, Sleep: time.Sleep, Now: time.Now,
	}
}

func (h *HTTP) siteGet(u string) (any, error) {
	if !h.last.IsZero() {
		if wait := h.last.Add(SiteInterval).Sub(h.Now()); wait > 0 {
			h.Sleep(wait)
		}
	}
	defer func() { h.last = h.Now() }()
	req, err := http.NewRequest(http.MethodGet, u, nil)
	if err != nil {
		return nil, &PyError{"URLError", fmt.Sprintf("<urlopen error %v>", err)}
	}
	req.Header.Set("User-Agent", "bestpractices-check")
	resp, err := h.Client.Do(req)
	if err != nil {
		return nil, &PyError{"URLError", fmt.Sprintf("<urlopen error %v>", unwrapURL(err))}
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBody))
	if err != nil {
		return nil, &PyError{"OSError", err.Error()}
	}
	if resp.StatusCode >= 400 {
		return nil, &PyError{"HTTPError", fmt.Sprintf("HTTP Error %d: %s", resp.StatusCode, http.StatusText(resp.StatusCode))}
	}
	return decodeJSON(body)
}

func unwrapURL(err error) error {
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return errors.New("timed out")
	}
	return err
}

// Site returns the project's public JSON.
func (h *HTTP) Site(project string) (any, error) {
	return h.siteGet(fmt.Sprintf("%s/projects/%s.json", h.SiteURL, project))
}

// Search returns the projects whose repo or home page URL is exactly
// repoURL (read-only, no login).
func (h *HTTP) Search(repoURL string) (any, error) {
	return h.siteGet(h.SiteURL + "/projects.json?url=" + quote(repoURL))
}

var nextLink = regexp.MustCompile(`<([^>]+)>;\s*rel="next"`)

// API calls the GitHub REST API: a 404 is (nil, nil); with paginate, the
// pages of a list are joined (at most maxPages).
func (h *HTTP) API(method, path string, body map[string]any, paginate bool) (any, error) {
	u := strings.TrimRight(h.APIURL, "/") + "/" + strings.TrimLeft(path, "/")
	var all []any
	for page := 0; page < maxPages; page++ {
		var rd io.Reader
		if body != nil {
			b, err := json.Marshal(body)
			if err != nil {
				return nil, err
			}
			rd = bytes.NewReader(b)
		}
		req, err := http.NewRequest(method, u, rd)
		if err != nil {
			return nil, failure("gh api %s %s: %v", method, path, err)
		}
		req.Header.Set("Accept", "application/vnd.github+json")
		req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
		req.Header.Set("User-Agent", "bestpractices-check")
		if h.Token != "" {
			req.Header.Set("Authorization", "Bearer "+h.Token)
		}
		if body != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		resp, err := h.Client.Do(req)
		if err != nil {
			return nil, failure("gh api %s %s: %v", method, path, err)
		}
		data, err := io.ReadAll(io.LimitReader(resp.Body, maxBody))
		resp.Body.Close()
		if err != nil {
			return nil, failure("gh api %s %s: %v", method, path, err)
		}
		if resp.StatusCode == http.StatusNotFound {
			return nil, nil
		}
		if resp.StatusCode >= 300 {
			msg := strings.TrimSpace(string(data))
			var e struct{ Message string }
			if json.Unmarshal(data, &e) == nil && e.Message != "" {
				msg = e.Message
			}
			return nil, failure("gh api %s %s: %s (HTTP %d)", method, path, msg, resp.StatusCode)
		}
		var v any
		if len(bytes.TrimSpace(data)) > 0 {
			if v, err = decodeJSON(data); err != nil {
				return nil, err
			}
		} else {
			v = map[string]any{}
		}
		list, isList := v.([]any)
		if !paginate || !isList {
			return v, nil
		}
		all = append(all, list...)
		m := nextLink.FindStringSubmatch(resp.Header.Get("Link"))
		if m == nil {
			return all, nil
		}
		u = m[1]
	}
	return nil, failure("gh api %s %s: more than %d pages", method, path, maxPages)
}

// File returns the file's text on main.
func (h *HTTP) File(repo, path string) (string, bool, error) {
	got, err := h.API("GET", fmt.Sprintf("repos/%s/%s/contents/%s?ref=main", Org, repo, path), nil, false)
	if err != nil {
		return "", false, err
	}
	m, _ := got.(map[string]any)
	content, ok := m["content"].(string)
	if !ok {
		return "", false, nil
	}
	b, err := base64.StdEncoding.DecodeString(strings.NewReplacer("\n", "", "\r", "").Replace(content))
	if err != nil {
		return "", false, valueError(err.Error())
	}
	return strings.ToValidUTF8(string(b), "�"), true, nil
}

// Tree returns every path on main.
func (h *HTTP) Tree(repo string) (map[string]bool, error) {
	got, err := h.API("GET", fmt.Sprintf("repos/%s/%s/git/trees/main?recursive=1", Org, repo), nil, false)
	if err != nil {
		return nil, err
	}
	m, _ := got.(map[string]any)
	list, _ := m["tree"].([]any)
	out := map[string]bool{}
	for _, t := range list {
		if e, ok := t.(map[string]any); ok {
			if p, ok := e["path"].(string); ok {
				out[p] = true
			}
		}
	}
	return out, nil
}

// Repos returns the public, unarchived org repositories, sorted.
func (h *HTTP) Repos() ([]string, error) {
	got, err := h.API("GET", fmt.Sprintf("orgs/%s/repos?type=public&per_page=100", Org), nil, true)
	if err != nil {
		return nil, err
	}
	list, _ := got.([]any)
	var out []string
	for _, x := range list {
		r, ok := x.(map[string]any)
		if !ok {
			continue
		}
		if truthy(r["archived"]) || truthy(r["private"]) {
			continue
		}
		if name, ok := r["name"].(string); ok {
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out, nil
}
