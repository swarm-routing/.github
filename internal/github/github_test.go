// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package github

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

// fake answers each request with the next of answers (status, headers,
// body), and records what it was sent.
type fake struct {
	answers []func(w http.ResponseWriter)
	seen    []*http.Request
	bodies  []string
}

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	b, _ := io.ReadAll(r.Body)
	f.seen = append(f.seen, r)
	f.bodies = append(f.bodies, string(b))
	if len(f.answers) == 0 {
		http.Error(w, "unexpected", http.StatusTeapot)
		return
	}
	a := f.answers[0]
	f.answers = f.answers[1:]
	a(w)
}

func answer(status int, body string, hdr ...string) func(http.ResponseWriter) {
	return func(w http.ResponseWriter) {
		for i := 0; i+1 < len(hdr); i += 2 {
			w.Header().Set(hdr[i], hdr[i+1])
		}
		w.WriteHeader(status)
		fmt.Fprint(w, body)
	}
}

func client(t *testing.T, f *fake) (Client, *[]time.Duration) {
	t.Helper()
	srv := httptest.NewServer(f)
	t.Cleanup(srv.Close)
	var slept []time.Duration
	return Client{API: srv.URL, Token: "tok", UserAgent: "ua-test", HTTP: srv.Client(),
		Sleep: func(d time.Duration) { slept = append(slept, d) }}, &slept
}

func TestDoHeadersAndBody(t *testing.T) {
	f := &fake{answers: []func(http.ResponseWriter){answer(200, `{"ok":1}`), answer(204, "")}}
	c, _ := client(t, f)
	if got, err := c.Do("GET", "repos/o/r", nil); err != nil || string(got) != `{"ok":1}` {
		t.Fatalf("GET: %q %v", got, err)
	}
	if _, err := c.Do("POST", "repos/o/r/dispatches", map[string]string{"ref": "main"}); err != nil {
		t.Fatal(err)
	}
	g, p := f.seen[0], f.seen[1]
	if g.URL.Path != "/repos/o/r" || g.Header.Get("Authorization") != "Bearer tok" || g.Header.Get("User-Agent") != "ua-test" ||
		g.Header.Get("Accept") != "application/vnd.github+json" || g.Header.Get("X-GitHub-Api-Version") != "2022-11-28" ||
		g.Header.Get("Content-Type") != "" {
		t.Errorf("GET headers: %v", g.Header)
	}
	if p.Header.Get("Content-Type") != "application/json" || f.bodies[1] != `{"ref":"main"}` {
		t.Errorf("POST: %v %q", p.Header, f.bodies[1])
	}
	anon := c
	anon.Token = ""
	f.answers = append(f.answers, answer(200, "[]"))
	if _, err := anon.Do("GET", "x", nil); err != nil || f.seen[2].Header.Get("Authorization") != "" {
		t.Errorf("anonymous: %v %v", err, f.seen[2].Header)
	}
}

func TestDoError(t *testing.T) {
	long := strings.Repeat("x", 300)
	f := &fake{answers: []func(http.ResponseWriter){answer(422, "  "+long+"\n"), answer(404, `{"message":"Not Found"}`)}}
	c, slept := client(t, f)
	_, err := c.Do("DELETE", "repos/o/r/git/refs/heads/b", nil)
	if Status(err) != 422 || err.Error() != "DELETE repos/o/r/git/refs/heads/b: HTTP 422: "+long[:200] {
		t.Errorf("422: %d %v", Status(err), err)
	}
	_, err = c.Do("GET", "repos/o/gone", nil)
	if Status(err) != 404 || err.Error() != `GET repos/o/gone: HTTP 404: {"message":"Not Found"}` {
		t.Errorf("404: %v", err)
	}
	if len(*slept) != 0 || len(f.seen) != 2 {
		t.Errorf("no retry on an ordinary error: slept %v, calls %d", *slept, len(f.seen))
	}
	if Status(errors.New("other")) != 0 {
		t.Error("a non-API error has no status")
	}
}

func TestTransportErrorRedactsToken(t *testing.T) {
	c := Client{API: "http://127.0.0.1:1/tok", Token: "tok", HTTP: &http.Client{Timeout: time.Second}}
	_, err := c.Do("GET", "repos/o/r", nil)
	if err == nil || strings.Contains(err.Error(), "tok") || !strings.Contains(err.Error(), "[redacted]") ||
		!strings.HasPrefix(err.Error(), "GET repos/o/r: ") || Status(err) != 0 {
		t.Errorf("transport error: %v", err)
	}
}

func TestRateLimit(t *testing.T) {
	reset := strconv.FormatInt(time.Now().Add(30*time.Second).Unix(), 10)
	cases := []struct {
		name    string
		answers []func(http.ResponseWriter)
		calls   int
		status  int
		wait    bool
	}{
		{"429 with Retry-After, then the answer", []func(http.ResponseWriter){answer(429, "slow", "Retry-After", "7"), answer(200, "ok")}, 2, 0, true},
		{"403 with no requests left and a reset", []func(http.ResponseWriter){answer(403, "rl", "X-RateLimit-Remaining", "0", "X-RateLimit-Reset", reset), answer(200, "ok")}, 2, 0, true},
		{"a second rate-limit answer is returned", []func(http.ResponseWriter){answer(429, "a", "Retry-After", "1"), answer(429, "b", "Retry-After", "1")}, 2, 429, true},
		{"a cooldown past MaxCooldown is not waited", []func(http.ResponseWriter){answer(429, "x", "Retry-After", "3600")}, 1, 429, false},
		{"a plain 403 is no rate limit", []func(http.ResponseWriter){answer(403, "denied")}, 1, 403, false},
	}
	for _, tc := range cases {
		f := &fake{answers: tc.answers}
		c, slept := client(t, f)
		got, err := c.Do("GET", "x", nil)
		if len(f.seen) != tc.calls || Status(err) != tc.status || (len(*slept) > 0) != tc.wait {
			t.Errorf("%s: calls %d, status %d (%v), slept %v", tc.name, len(f.seen), Status(err), err, *slept)
		}
		if tc.status == 0 && string(got) != "ok" {
			t.Errorf("%s: %q", tc.name, got)
		}
	}
	f := &fake{answers: []func(http.ResponseWriter){answer(429, "", "Retry-After", "7"), answer(200, "ok")}}
	c, slept := client(t, f)
	_, _ = c.Do("GET", "x", nil)
	if len(*slept) != 1 || (*slept)[0] != 7*time.Second {
		t.Errorf("Retry-After is the wait: %v", *slept)
	}
}

func TestList(t *testing.T) {
	full := "[" + strings.TrimSuffix(strings.Repeat(`{"n":1},`, 100), ",") + "]"
	f := &fake{answers: []func(http.ResponseWriter){answer(200, full), answer(200, `[{"n":2}]`)}}
	c, _ := client(t, f)
	got, err := List[struct{ N int }](c, "orgs/o/repos?type=all", 5)
	if err != nil || len(got) != 101 || got[100].N != 2 {
		t.Fatalf("two pages: %d %v", len(got), err)
	}
	if q := f.seen[1].URL.RawQuery; q != "type=all&per_page=100&page=2" {
		t.Errorf("page query: %s", q)
	}
	f = &fake{answers: []func(http.ResponseWriter){answer(200, full), answer(200, full)}}
	c, _ = client(t, f)
	if _, err := List[struct{ N int }](c, "x?a=1", 2); err == nil || err.Error() != "GET x?a=1: more than 2 pages" {
		t.Errorf("the page cap: %v", err)
	}
	f = &fake{answers: []func(http.ResponseWriter){answer(200, `{"not":"a list"}`)}}
	c, _ = client(t, f)
	if _, err := List[struct{ N int }](c, "x?a=1", 2); err == nil || !strings.HasPrefix(err.Error(), "GET x?a=1: ") {
		t.Errorf("not a list: %v", err)
	}
}
