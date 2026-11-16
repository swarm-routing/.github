// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

import (
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
)

// Usage is the command line.
const Usage = `usage: bestpractices answers REPO_DIR [--slug OWNER/NAME] [--write] [--today YYYY-MM-DD]
       bestpractices register OWNER/NAME [--dir REPO_DIR] [--answers FILE] [--today YYYY-MM-DD]
       bestpractices check [--repos NAME[=ID],...] [--issues] [--dry-run]
`

// Env is what the command reads from its environment and the network.
type Env struct {
	Getenv    func(string) string
	Remote    Remote                    // nil: the real network (GH_TOKEN for reads)
	NewGitHub func(token string) GitHub // nil: the GitHub REST API with token
}

type options struct {
	pos   []string
	vals  map[string]string
	flags map[string]bool
}

// parse splits args into positionals, options taking a value and flags,
// as argparse does (--opt VALUE, --opt=VALUE, options anywhere).
func parse(args []string, valued, flags []string) (options, error) {
	o := options{vals: map[string]string{}, flags: map[string]bool{}}
	isValued := map[string]bool{}
	for _, v := range valued {
		isValued[v] = true
	}
	isFlag := map[string]bool{}
	for _, f := range flags {
		isFlag[f] = true
	}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			o.pos = append(o.pos, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(a, "--") || a == "-" {
			if strings.HasPrefix(a, "-") && a != "-" {
				return o, fmt.Errorf("unrecognized arguments: %s", a)
			}
			o.pos = append(o.pos, a)
			continue
		}
		name, val, hasVal := strings.Cut(a, "=")
		switch {
		case isValued[name]:
			if !hasVal {
				if i+1 >= len(args) || strings.HasPrefix(args[i+1], "--") {
					return o, fmt.Errorf("argument %s: expected one argument", name)
				}
				i++
				val = args[i]
			}
			o.vals[name] = val
		case isFlag[name] && !hasVal:
			o.flags[name] = true
		default:
			return o, fmt.Errorf("unrecognized arguments: %s", a)
		}
	}
	return o, nil
}

var slugArg = regexp.MustCompile(`^[\w.-]+/[\w.-]+$`)

// Main runs the command line and returns the exit code.
func Main(args []string, env Env, stdout, stderr io.Writer) int {
	if env.Getenv == nil {
		env.Getenv = os.Getenv
	}
	usage := func(msg string) int {
		fmt.Fprint(stderr, Usage)
		fmt.Fprintf(stderr, "bestpractices: error: %s\n", msg)
		return 2
	}
	if len(args) == 0 {
		return usage("a command is required")
	}
	if args[0] == "-h" || args[0] == "--help" {
		fmt.Fprint(stdout, Usage)
		return 0
	}
	fail := func(err error) int {
		var pe *PyError
		if errors.As(err, &pe) && pe.Type == "Failure" {
			fmt.Fprintln(stderr, pe.Msg)
			return 1
		}
		fmt.Fprintf(stderr, "bestpractices: %s\n", described(err))
		return 1
	}
	remote := func() Remote {
		if env.Remote != nil {
			return env.Remote
		}
		return NewHTTP(ghToken(env.Getenv), env.Getenv("GITHUB_API_URL"))
	}
	switch args[0] {
	case "answers":
		o, err := parse(args[1:], []string{"--slug", "--today"}, []string{"--write"})
		if err == nil && len(o.pos) != 1 {
			err = errors.New("answers takes REPO_DIR")
		}
		if err != nil {
			return usage(err.Error())
		}
		dir := o.pos[0]
		ans, err := Derive(dir, o.vals["--slug"], o.vals["--today"])
		if err != nil {
			return fail(err)
		}
		text := ans.JSON()
		if o.flags["--write"] {
			p := pyJoin(dir, Out)
			if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
				return fail(err)
			}
			fmt.Fprintf(stderr, "bestpractices: wrote %s\n", p)
		} else {
			fmt.Fprint(stdout, text)
		}
		fmt.Fprintf(stderr, "bestpractices: %s\n", ans.Summary())
		return 0
	case "register":
		o, err := parse(args[1:], []string{"--dir", "--answers", "--today"}, nil)
		if err == nil && len(o.pos) != 1 {
			err = errors.New("register takes OWNER/NAME")
		}
		if err == nil && !slugArg.MatchString(o.pos[0]) {
			err = errors.New("register takes OWNER/NAME")
		}
		if err != nil {
			return usage(err.Error())
		}
		var s Searcher = env.Remote
		if env.Remote == nil {
			s = remote()
		}
		if err := Register(o.pos[0], o.vals["--dir"], o.vals["--today"], o.vals["--answers"], s, stdout, stderr); err != nil {
			return fail(err)
		}
		return 0
	case "check":
		o, err := parse(args[1:], []string{"--repos"}, []string{"--issues", "--dry-run"})
		if err == nil && len(o.pos) != 0 {
			err = fmt.Errorf("unrecognized arguments: %s", strings.Join(o.pos, " "))
		}
		if err != nil {
			return usage(err.Error())
		}
		newGitHub := env.NewGitHub
		if newGitHub == nil {
			newGitHub = func(token string) GitHub {
				if token == "" {
					token = ghToken(env.Getenv)
				}
				return NewHTTP(token, env.Getenv("GITHUB_API_URL"))
			}
		}
		return Check(CheckArgs{o.vals["--repos"], o.flags["--issues"], o.flags["--dry-run"]},
			remote(), newGitHub, env.Getenv, stdout)
	}
	return usage(fmt.Sprintf("unknown command %q", args[0]))
}

// ghToken is the token `gh api` would use: GH_TOKEN, else GITHUB_TOKEN.
func ghToken(getenv func(string) string) string {
	if t := getenv("GH_TOKEN"); t != "" {
		return t
	}
	return getenv("GITHUB_TOKEN")
}
