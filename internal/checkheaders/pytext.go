// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

// What the Python tool's results depended on, kept so the port gives the same
// bytes: reading a file as pathlib's read_text(encoding="utf-8",
// errors="replace") does (CPython's replacement of each maximal invalid
// subpart, universal newlines), str.isspace / str.strip, the Unicode \s, \S
// and \d of the `re` module, repr() of a str, and os.path.realpath's
// non-strict resolution.

import (
	"os"
	"strings"
	"unicode"
	"unicode/utf8"
)

// decodeText is bytes.decode("utf-8", errors="replace") followed by the
// universal-newline translation of a text-mode read ("\r\n" and "\r" become
// "\n").
func decodeText(b []byte) string {
	var sb strings.Builder
	sb.Grow(len(b))
	for i := 0; i < len(b); {
		c := b[i]
		if c < 0x80 {
			sb.WriteByte(c)
			i++
			continue
		}
		need, lo, hi := 0, byte(0x80), byte(0xBF)
		switch {
		case c >= 0xC2 && c <= 0xDF:
			need = 1
		case c == 0xE0:
			need, lo = 2, 0xA0
		case c >= 0xE1 && c <= 0xEC, c == 0xEE, c == 0xEF:
			need = 2
		case c == 0xED:
			need, hi = 2, 0x9F
		case c == 0xF0:
			need, lo = 3, 0x90
		case c >= 0xF1 && c <= 0xF3:
			need = 3
		case c == 0xF4:
			need, hi = 3, 0x8F
		default: // 0x80-0xC1, 0xF5-0xFF: never a start byte
			sb.WriteRune(utf8.RuneError)
			i++
			continue
		}
		// CPython replaces the start byte and the continuation bytes that were
		// still valid with one U+FFFD and resumes at the first invalid byte.
		j := i + 1
		ok := true
		for k := 0; k < need; k++ {
			l, h := byte(0x80), byte(0xBF)
			if k == 0 {
				l, h = lo, hi
			}
			if j >= len(b) || b[j] < l || b[j] > h {
				ok = false
				break
			}
			j++
		}
		if !ok {
			sb.WriteRune(utf8.RuneError)
			i = j
			continue
		}
		sb.Write(b[i:j])
		i = j
	}
	s := sb.String()
	if strings.IndexByte(s, '\r') < 0 {
		return s
	}
	s = strings.ReplaceAll(s, "\r\n", "\n")
	return strings.ReplaceAll(s, "\r", "\n")
}

// readText is pathlib.Path(p).read_text(encoding="utf-8", errors="replace").
func readText(p string) (string, error) {
	b, err := os.ReadFile(p)
	if err != nil {
		return "", err
	}
	return decodeText(b), nil
}

// pySpaceClass is the set str.isspace() accepts (and the `re` module's \s for
// a str pattern): bidirectional class WS, B or S, or category Zs.
const pySpaceClass = `\t\n\v\f\r \x1c-\x1f\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}`

func isPySpace(r rune) bool {
	switch {
	case r >= '\t' && r <= '\r', r == ' ', r >= 0x1c && r <= 0x1f, r == 0x85, r == 0xa0,
		r == 0x1680, r >= 0x2000 && r <= 0x200a, r == 0x2028, r == 0x2029, r == 0x202f,
		r == 0x205f, r == 0x3000:
		return true
	}
	return false
}

// pyStrip is str.strip() with no argument.
func pyStrip(s string) string { return strings.TrimFunc(s, isPySpace) }

// pyRepr is repr() of a str.
func pyRepr(s string) string {
	quote := byte('\'')
	if strings.IndexByte(s, '\'') >= 0 && strings.IndexByte(s, '"') < 0 {
		quote = '"'
	}
	var sb strings.Builder
	sb.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
			sb.WriteByte('\\')
			sb.WriteRune(r)
		case r == '\t':
			sb.WriteString(`\t`)
		case r == '\n':
			sb.WriteString(`\n`)
		case r == '\r':
			sb.WriteString(`\r`)
		case r < 0x20 || r == 0x7f:
			sb.WriteString(`\x` + hex2(uint32(r), 2))
		case r < 0x7f:
			sb.WriteRune(r)
		case isPyPrintable(r):
			sb.WriteRune(r)
		case r <= 0xff:
			sb.WriteString(`\x` + hex2(uint32(r), 2))
		case r <= 0xffff:
			sb.WriteString(`\u` + hex2(uint32(r), 4))
		default:
			sb.WriteString(`\U` + hex2(uint32(r), 8))
		}
	}
	sb.WriteByte(quote)
	return sb.String()
}

// isPyPrintable is str.isprintable() of one non-ASCII character: not in Cc,
// Cf, Cs, Co, Cn, Zl, Zp or Zs.
func isPyPrintable(r rune) bool {
	if r == utf8.RuneError {
		return true // U+FFFD is a symbol (So)
	}
	if unicode.Is(unicode.Zs, r) || unicode.Is(unicode.Zl, r) || unicode.Is(unicode.Zp, r) {
		return false
	}
	return unicode.IsPrint(r) || unicode.IsGraphic(r) && !unicode.Is(unicode.Cf, r)
}

func hex2(v uint32, width int) string {
	const digits = "0123456789abcdef"
	b := make([]byte, width)
	for i := width - 1; i >= 0; i-- {
		b[i] = digits[v&0xf]
		v >>= 4
	}
	return string(b)
}

// realpath is os.path.realpath(p) with strict=False (CPython 3.13): symlinks
// resolved one component at a time, a missing component kept as it is, ".."
// applied to what was resolved so far, a symlink loop left unresolved.
func realpath(p string) string {
	path := "/"
	if !strings.HasPrefix(p, "/") {
		wd, err := os.Getwd()
		if err == nil {
			path = wd
		}
	}
	// rest is the stack of unresolved parts; a linkMark entry says the
	// symlink under it is resolved to the path reached when it is popped.
	var rest []part
	for _, s := range reverse(strings.Split(p, "/")) {
		rest = append(rest, part{name: s})
	}
	partCount := len(rest)
	seen := map[string]*string{}
	for partCount > 0 {
		top := rest[len(rest)-1]
		rest = rest[:len(rest)-1]
		if top.mark {
			link := rest[len(rest)-1]
			rest = rest[:len(rest)-1]
			resolved := path
			seen[link.name] = &resolved
			continue
		}
		partCount--
		name := top.name
		if name == "" || name == "." {
			continue
		}
		if name == ".." {
			path = path[:strings.LastIndex(path, "/")]
			if path == "" {
				path = "/"
			}
			continue
		}
		newpath := path + "/" + name
		if path == "/" {
			newpath = "/" + name
		}
		fi, err := os.Lstat(newpath)
		if err != nil || fi.Mode()&os.ModeSymlink == 0 {
			path = newpath
			continue
		}
		if v, ok := seen[newpath]; ok {
			if v != nil {
				path = *v
			} else {
				path = newpath // a loop
			}
			continue
		}
		target, err := os.Readlink(newpath)
		if err != nil {
			path = newpath
			continue
		}
		if len(seen) > maxLinks { // bounded (golden rule 7)
			path = newpath
			continue
		}
		if strings.HasPrefix(target, "/") {
			path = "/"
		}
		seen[newpath] = nil
		rest = append(rest, part{name: newpath}, part{mark: true})
		tparts := reverse(strings.Split(target, "/"))
		for _, t := range tparts {
			rest = append(rest, part{name: t})
		}
		partCount += len(tparts)
	}
	return path
}

// maxLinks bounds the symlinks one realpath follows; a real tree has a few.
const maxLinks = 4096

type part struct {
	name string
	mark bool
}

func reverse(s []string) []string {
	out := make([]string, len(s))
	for i, v := range s {
		out[len(s)-1-i] = v
	}
	return out
}
