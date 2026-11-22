// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package github is the one GitHub REST client of the Go tools (#646): the
// headers, the token and its redaction from transport errors, a status-
// carrying error, a wait on a rate-limit answer, and pagination. Each tool
// moves onto it in its own PR with its output unchanged; branch-sweep is the
// first.
package github

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// Client is one tool's connection to the API: base URL (no trailing slash),
// token (empty: anonymous), User-Agent, HTTP client, and the wait a
// rate-limit answer asks for (nil: time.Sleep; tests inject their own).
type Client struct {
	API       string
	Token     string
	UserAgent string
	HTTP      *http.Client
	Sleep     func(time.Duration)
}

// MaxBody bounds the bytes read from one answer.
const MaxBody = 8 << 20

// MaxCooldown bounds the wait after a rate-limit answer; the request is then
// sent once more. A longer cooldown, or a second rate-limit answer, is
// returned as the error it is.
const MaxCooldown = 60 * time.Second

// Error is a call GitHub answered outside 2xx. Its text is
// "METHOD path: HTTP n: <the body, at most 200 bytes>".
type Error struct {
	Status int
	Msg    string
}

func (e *Error) Error() string { return e.Msg }

// Status is the HTTP status of a failed call, 0 when it never got an answer.
func Status(err error) int {
	var e *Error
	if errors.As(err, &e) {
		return e.Status
	}
	return 0
}

// Do sends one request (body, when not nil, as JSON) and returns the answer.
func (c Client) Do(method, path string, body any) ([]byte, error) {
	var payload []byte
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		payload = b
	}
	for attempt := 1; ; attempt++ {
		data, wait, err := c.once(method, path, payload)
		if wait == 0 || attempt == 2 || wait > MaxCooldown {
			return data, err
		}
		if c.Sleep != nil {
			c.Sleep(wait)
		} else {
			time.Sleep(wait)
		}
	}
}

func (c Client) once(method, path string, payload []byte) ([]byte, time.Duration, error) {
	var rd io.Reader
	if payload != nil {
		rd = bytes.NewReader(payload)
	}
	req, err := http.NewRequest(method, c.API+"/"+path, rd)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", c.UserAgent)
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		msg := err.Error()
		if c.Token != "" {
			msg = strings.ReplaceAll(msg, c.Token, "[redacted]")
		}
		return nil, 0, fmt.Errorf("%s %s: %s", method, path, msg)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, MaxBody))
	if err != nil {
		return nil, 0, err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		msg := strings.TrimSpace(string(data))
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return nil, cooldown(resp), &Error{resp.StatusCode, fmt.Sprintf("%s %s: HTTP %d: %s", method, path, resp.StatusCode, msg)}
	}
	return data, 0, nil
}

// cooldown is the wait a rate-limit answer (429, or 403 with Retry-After or
// no requests left) asks for: at least a second, MaxCooldown when it names
// none; 0 for any other answer.
func cooldown(resp *http.Response) time.Duration {
	ra := resp.Header.Get("Retry-After")
	left := resp.Header.Get("X-RateLimit-Remaining")
	limited := resp.StatusCode == http.StatusTooManyRequests ||
		(resp.StatusCode == http.StatusForbidden && (ra != "" || left == "0"))
	if !limited {
		return 0
	}
	d := MaxCooldown
	if n, err := strconv.Atoi(ra); err == nil && n >= 0 {
		d = time.Duration(n) * time.Second
	} else if reset, err := strconv.ParseInt(resp.Header.Get("X-RateLimit-Reset"), 10, 64); err == nil {
		d = time.Until(time.Unix(reset, 0))
	}
	if d < time.Second {
		d = time.Second
	}
	return d
}

// List reads every page of a listing, 100 items a page (path has a query
// already), until a short page; more than maxPages pages is an error.
func List[T any](c Client, path string, maxPages int) ([]T, error) {
	var all []T
	for page := 1; page <= maxPages; page++ {
		data, err := c.Do("GET", fmt.Sprintf("%s&per_page=100&page=%d", path, page), nil)
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
