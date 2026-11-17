// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

import (
	_ "embed"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Prog is the command's name in its usage and error lines.
const Prog = "check-headers"

//go:embed help.txt
var helpText string

// usageText is the usage block argparse prints before an error.
var usageText = helpText[:strings.Index(helpText, "\n\n")+1]

// Options are the parsed arguments.
type Options struct {
	Root     string
	Dual     []string
	Core     []string
	GPLOnly  []string
	CoreDep  []string
	Exclude  string
	SelfTest bool
}

// Main runs the command on args (os.Args[1:]) and returns its exit code.
func Main(args []string, stdout, stderr io.Writer) int {
	o, code, done := Parse(args, stdout, stderr)
	if done {
		return code
	}
	if o.SelfTest {
		return SelfTest(stdout)
	}
	gpl := map[string]bool{}
	for _, g := range o.GPLOnly {
		gpl[g] = true
	}
	return Scan(o.Root, Rules{Dual: o.Dual, Core: o.Core, GPLOnly: gpl}, o.Exclude, o.CoreDep, stdout, stderr)
}

// Scan checks every tracked covered file under root and prints a FAIL line
// per finding and the count; 1 when there is a finding. A failure to read the
// tree is exit 1 with the error on stderr (the Python tool's traceback).
func Scan(root string, r Rules, exclude string, deps []string, stdout, stderr io.Writer) int {
	fail := func(err error) int {
		fmt.Fprintf(stderr, "%s: %v\n", Prog, err)
		return 1
	}
	tracked, err := LsFiles(root)
	if err != nil {
		return fail(err)
	}
	var words []string // str.split() of the output: a path with a space is two words
	for _, t := range tracked {
		words = append(words, strings.Fields(t)...)
	}
	var re *regexp.Regexp
	var files []string
	for _, f := range words {
		if !hasSuffix(f, Exts) {
			continue
		}
		if exclude != "" {
			if re == nil {
				if re, err = regexp.Compile(exclude); err != nil {
					return fail(fmt.Errorf("--exclude: %w", err))
				}
			}
			if re.MatchString(f) {
				continue
			}
		}
		files = append(files, f)
	}
	sort.Strings(files)
	depOK := DepResolver(deps)
	exists := func(p string) bool {
		if strings.HasPrefix(p, "/") {
			return isFile(p)
		}
		return isFile(filepath.Join(root, p))
	}
	var problems []string
	for _, rel := range files {
		text, err := readText(filepath.Join(root, rel))
		if err != nil {
			return fail(err)
		}
		problems = append(problems, CheckFile(rel, text, r, exists, depOK)...)
	}
	for _, p := range problems {
		fmt.Fprintf(stdout, "FAIL: %s\n", p)
	}
	fmt.Fprintf(stdout, "checked %d tracked source file(s); %d problem(s)\n", len(files), len(problems))
	if len(problems) > 0 {
		return 1
	}
	return 0
}

func isFile(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.Mode().IsRegular()
}

// option is one of argparse's optional actions, in the order they were added.
type option struct {
	strings []string // its option strings
	name    string   // how an error names it ('/'-joined strings)
	nargs   int      // 0 or 1
}

var options = []option{
	{[]string{"-h", "--help"}, "-h/--help", 0},
	{[]string{"--dual"}, "--dual", 1},
	{[]string{"--core"}, "--core", 1},
	{[]string{"--gpl-only"}, "--gpl-only", 1},
	{[]string{"--core-dep"}, "--core-dep", 1},
	{[]string{"--exclude"}, "--exclude", 1},
	{[]string{"--self-test"}, "--self-test", 0},
}

// optionStrings is argparse's _option_string_actions, in insertion order.
var optionStrings = func() []string {
	var out []string
	for _, o := range options {
		out = append(out, o.strings...)
	}
	return out
}()

func lookup(s string) *option {
	for i := range options {
		for _, os := range options[i].strings {
			if os == s {
				return &options[i]
			}
		}
	}
	return nil
}

// tuple is one interpretation of an option string (argparse's option tuple).
type tuple struct {
	opt      *option // nil: an unknown option
	str      string
	sep      *string
	explicit *string
}

func sptr(s string) *string { return &s }

var negativeNumber = regexp.MustCompile(`^-\p{Nd}+$|^-\p{Nd}*\.\p{Nd}+$`)

// parseOptional is argparse's _parse_optional (Python 3.13): nil for a
// positional, else the option tuples the string may stand for.
func parseOptional(arg string) []tuple {
	if arg == "" || arg[0] != '-' {
		return nil
	}
	if o := lookup(arg); o != nil {
		return []tuple{{o, arg, nil, nil}}
	}
	if len(arg) == 1 {
		return nil
	}
	if i := strings.IndexByte(arg, '='); i >= 0 {
		if o := lookup(arg[:i]); o != nil {
			return []tuple{{o, arg[:i], sptr("="), sptr(arg[i+1:])}}
		}
	}
	var res []tuple
	if arg[1] == '-' {
		prefix, sep, explicit := arg, (*string)(nil), (*string)(nil)
		if i := strings.IndexByte(arg, '='); i >= 0 {
			prefix, sep, explicit = arg[:i], sptr("="), sptr(arg[i+1:])
		}
		for _, s := range optionStrings {
			if strings.HasPrefix(s, prefix) {
				res = append(res, tuple{lookup(s), s, sep, explicit})
			}
		}
	} else {
		prefix, sep, explicit := arg, (*string)(nil), (*string)(nil)
		if i := strings.IndexByte(arg, '='); i >= 0 {
			prefix, sep, explicit = arg[:i], sptr("="), sptr(arg[i+1:])
		}
		short, shortExplicit := arg[:2], arg[2:]
		for _, s := range optionStrings {
			if s == short {
				res = append(res, tuple{lookup(s), s, sptr(""), sptr(shortExplicit)})
			} else if strings.HasPrefix(s, prefix) {
				res = append(res, tuple{lookup(s), s, sep, explicit})
			}
		}
	}
	if len(res) > 0 {
		return res
	}
	if negativeNumber.MatchString(arg) {
		return nil
	}
	if strings.Contains(arg, " ") {
		return nil
	}
	return []tuple{{nil, arg, nil, nil}}
}

type argError struct{ msg string }

func (e *argError) Error() string { return e.msg }

func errFor(o *option, msg string) *argError {
	if o == nil {
		return &argError{msg}
	}
	return &argError{"argument " + o.name + ": " + msg}
}

// Parse is argparse's parse_args for this command's parser (Python 3.13):
// the options, or done with the exit code after help (0) or an error (2).
func Parse(args []string, stdout, stderr io.Writer) (o Options, code int, done bool) {
	o.Root = "."
	help := false
	err := parseArgs(args, &o, &help)
	if help {
		io.WriteString(stdout, helpText)
		return o, 0, true
	}
	if err != nil {
		io.WriteString(stderr, usageText)
		fmt.Fprintf(stderr, "%s: error: %s\n", Prog, err.msg)
		return o, 2, true
	}
	return o, 0, false
}

// parseArgs walks the arguments as argparse's _parse_known_args does. A help
// action stops the walk at once (argparse prints and exits there).
func parseArgs(args []string, o *Options, help *bool) *argError {
	var pattern []byte
	optAt := map[int][]tuple{}
	for i := 0; i < len(args); i++ {
		if args[i] == "--" {
			pattern = append(pattern, '-')
			for i++; i < len(args); i++ {
				pattern = append(pattern, 'A')
			}
			break
		}
		if t := parseOptional(args[i]); t != nil {
			optAt[i] = t
			pattern = append(pattern, 'O')
		} else {
			pattern = append(pattern, 'A')
		}
	}
	var extras []string
	rootDone := false

	take := func(opt *option, vals []string) {
		switch opt.strings[len(opt.strings)-1] {
		case "--help":
			*help = true
		case "--dual":
			o.Dual = append(o.Dual, vals[0])
		case "--core":
			o.Core = append(o.Core, vals[0])
		case "--gpl-only":
			o.GPLOnly = append(o.GPLOnly, vals[0])
		case "--core-dep":
			o.CoreDep = append(o.CoreDep, vals[0])
		case "--exclude":
			o.Exclude = vals[0]
		case "--self-test":
			o.SelfTest = true
		}
	}

	// consumePositionals matches the root's pattern (-*A?-*) at start.
	consumePositionals := func(start int) int {
		if rootDone {
			return start
		}
		sel := pattern[start:]
		n := 0
		for n < len(sel) && sel[n] == '-' {
			n++
		}
		if n < len(sel) && sel[n] == 'A' {
			n++
		}
		for n < len(sel) && sel[n] == '-' {
			n++
		}
		if n == 0 && len(sel) > 0 && sel[0] == 'O' {
			return start // argparse keeps a positional that matched nothing before an option
		}
		vals := append([]string(nil), args[start:start+n]...)
		if strings.IndexByte(string(pattern[start:start+n]), '-') >= 0 {
			for i, v := range vals {
				if v == "--" {
					vals = append(vals[:i], vals[i+1:]...)
					break
				}
			}
		}
		if len(vals) == 1 {
			o.Root = vals[0]
		}
		rootDone = true
		return start + n
	}

	consumeOptional := func(start int) (int, *argError) {
		tuples := optAt[start]
		if len(tuples) > 1 {
			var names []string
			for _, t := range tuples {
				names = append(names, t.str)
			}
			return 0, &argError{"ambiguous option: " + args[start] + " could match " + strings.Join(names, ", ")}
		}
		t := tuples[0]
		opt, str, sep, explicit := t.opt, t.str, t.sep, t.explicit
		type act struct {
			opt  *option
			vals []string
		}
		var acts []act
		var stop int
		for {
			if opt == nil {
				extras = append(extras, args[start])
				return start + 1, nil
			}
			if explicit != nil {
				if opt.nargs == 0 && str[1] != '-' && *explicit != "" {
					if (sep != nil && *sep != "") || (*explicit)[0] == '-' {
						return 0, errFor(opt, "ignored explicit argument "+pyRepr(*explicit))
					}
					acts = append(acts, act{opt, nil})
					str = "-" + (*explicit)[:1]
					if next := lookup(str); next != nil {
						opt = next
						rest := (*explicit)[1:]
						switch {
						case rest == "":
							sep, explicit = nil, nil
						case rest[0] == '=':
							sep, explicit = sptr("="), sptr(rest[1:])
						default:
							sep, explicit = sptr(""), sptr(rest)
						}
						continue
					}
					extras = append(extras, "-"+*explicit)
					stop = start + 1
					break
				}
				if opt.nargs == 1 {
					acts = append(acts, act{opt, []string{*explicit}})
					stop = start + 1
					break
				}
				return 0, errFor(opt, "ignored explicit argument "+pyRepr(*explicit))
			}
			n := 0
			if opt.nargs == 1 {
				if start+1 >= len(pattern) || pattern[start+1] != 'A' {
					return 0, errFor(opt, "expected one argument")
				}
				n = 1
			}
			acts = append(acts, act{opt, args[start+1 : start+1+n]})
			stop = start + 1 + n
			break
		}
		for _, a := range acts {
			take(a.opt, a.vals)
			if *help {
				return stop, nil
			}
		}
		return stop, nil
	}

	maxOpt := -1
	for i := range optAt {
		if i > maxOpt {
			maxOpt = i
		}
	}
	start := 0
	for start <= maxOpt {
		next := start
		for next <= maxOpt {
			if _, ok := optAt[next]; ok {
				break
			}
			next++
		}
		if start != next {
			end := consumePositionals(start)
			if end > start {
				start = end
				continue
			}
			start = end
		}
		if _, ok := optAt[start]; !ok {
			extras = append(extras, args[start:next]...)
			start = next
		}
		var err *argError
		start, err = consumeOptional(start)
		if err != nil || *help {
			return err
		}
	}
	stop := consumePositionals(start)
	extras = append(extras, args[stop:]...)
	if len(extras) > 0 {
		return &argError{"unrecognized arguments: " + strings.Join(extras, " ")}
	}
	return nil
}
