// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package checkheaders

// The tracked files as the Python tool saw them: the words of
// `git ls-files` run in the scan root. The ci-tools image has no git
// (distroless), so the index is read here: every entry, in index order,
// unmerged ones once per stage, relative to the scan root and only those
// under it, with the path quoted as core.quotePath (git's default) quotes it.
// Index versions 2, 3 and 4, SHA-1 and SHA-256 repositories, a worktree's or
// submodule's `.git` file. A split index or a sparse index (entries that only
// git can expand from its objects) is refused rather than misread.

import (
	"bytes"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"hash"
	"os"
	"path/filepath"
	"strings"
)

// maxEntries bounds an index read (golden rule 7): far above any repository here.
const maxEntries = 1 << 22

// LsFiles returns what `git ls-files` prints in dir, one path per entry.
func LsFiles(dir string) ([]string, error) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	if fi, err := os.Stat(abs); err != nil {
		return nil, err
	} else if !fi.IsDir() {
		return nil, fmt.Errorf("%s: not a directory", dir)
	}
	if real, err := filepath.EvalSymlinks(abs); err == nil {
		abs = real
	}
	top, gitDir, err := findRepo(abs)
	if err != nil {
		return nil, err
	}
	prefix := ""
	if top != abs {
		r, err := filepath.Rel(top, abs)
		if err != nil {
			return nil, err
		}
		prefix = filepath.ToSlash(r) + "/"
	}
	entries, err := readIndex(top, gitDir)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range entries {
		if !strings.HasPrefix(e, prefix) {
			continue
		}
		out = append(out, quotePath(e[len(prefix):]))
	}
	return out, nil
}

// findRepo walks up from dir to the work tree holding `.git` (a directory, or
// a file naming the git directory).
func findRepo(dir string) (top, gitDir string, err error) {
	for d := dir; ; {
		g := filepath.Join(d, ".git")
		if fi, err := os.Stat(g); err == nil {
			if fi.IsDir() {
				return d, g, nil
			}
			b, err := os.ReadFile(g)
			if err != nil {
				return "", "", err
			}
			line := strings.TrimSpace(string(b))
			if rest, ok := strings.CutPrefix(line, "gitdir:"); ok {
				p := strings.TrimSpace(rest)
				if !filepath.IsAbs(p) {
					p = filepath.Join(d, p)
				}
				return d, p, nil
			}
			return "", "", fmt.Errorf("%s: not a gitdir file", g)
		}
		parent := filepath.Dir(d)
		if parent == d {
			return "", "", errors.New("fatal: not a git repository (or any of the parent directories): .git")
		}
		d = parent
	}
}

// hashSize is the object id size of the repository at gitDir: 32 bytes when
// its config's [extensions] objectFormat is sha256 (a worktree's config is in
// its commondir).
func hashSize(gitDir string) int {
	cfg := filepath.Join(gitDir, "config")
	if b, err := os.ReadFile(filepath.Join(gitDir, "commondir")); err == nil {
		c := strings.TrimSpace(string(b))
		if !filepath.IsAbs(c) {
			c = filepath.Join(gitDir, c)
		}
		cfg = filepath.Join(c, "config")
	}
	b, err := os.ReadFile(cfg)
	if err != nil {
		return sha1.Size
	}
	section := ""
	for _, line := range strings.Split(string(b), "\n") {
		t := strings.TrimSpace(line)
		if strings.HasPrefix(t, "[") {
			if end := strings.IndexByte(t, ']'); end > 0 {
				section = strings.ToLower(strings.TrimSpace(t[1:end]))
			}
			continue
		}
		k, v, ok := strings.Cut(t, "=")
		if ok && section == "extensions" && strings.EqualFold(strings.TrimSpace(k), "objectformat") &&
			strings.EqualFold(configValue(v), "sha256") {
			return sha256.Size
		}
	}
	return sha1.Size
}

// configValue decodes a git config value: double quotes removed, backslash
// escapes applied, a comment (# or ;) outside quotes dropped, the
// surrounding whitespace trimmed.
func configValue(v string) string {
	var sb strings.Builder
	quoted := false
	for i := 0; i < len(v); i++ {
		c := v[i]
		switch {
		case c == '"':
			quoted = !quoted
		case c == '\\' && i+1 < len(v):
			i++
			sb.WriteByte(v[i])
		case !quoted && (c == '#' || c == ';'):
			return strings.TrimSpace(sb.String())
		default:
			sb.WriteByte(c)
		}
	}
	return strings.TrimSpace(sb.String())
}

// indexPath is the index git reads: GIT_INDEX_FILE when set (a relative one
// from the top of the work tree, as git resolves it after moving there), else
// the git directory's index.
func indexPath(top, gitDir string) string {
	if p := os.Getenv("GIT_INDEX_FILE"); p != "" {
		if !filepath.IsAbs(p) {
			p = filepath.Join(top, p)
		}
		return p
	}
	return filepath.Join(gitDir, "index")
}

func readIndex(top, gitDir string) ([]string, error) {
	b, err := os.ReadFile(indexPath(top, gitDir))
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil // a repository with nothing staged lists nothing
	}
	if err != nil {
		return nil, err
	}
	return parseIndex(b, hashSize(gitDir))
}

var errIndex = errors.New("the git index is corrupt or of an unknown format")

func parseIndex(b []byte, hsz int) ([]string, error) {
	if len(b) < 12+hsz || string(b[:4]) != "DIRC" {
		return nil, errIndex
	}
	var h hash.Hash = sha1.New()
	if hsz == sha256.Size {
		h = sha256.New()
	}
	body, sum := b[:len(b)-hsz], b[len(b)-hsz:]
	if !bytes.Equal(sum, make([]byte, hsz)) { // index.skipHash writes zeros
		h.Write(body)
		if !bytes.Equal(h.Sum(nil), sum) {
			return nil, errIndex
		}
	}
	version := binary.BigEndian.Uint32(b[4:8])
	count := binary.BigEndian.Uint32(b[8:12])
	if version < 2 || version > 4 || count > maxEntries {
		return nil, errIndex
	}
	fixed := 40 + hsz + 2 // stat data, object id, flags
	out := make([]string, 0, count)
	pos := 12
	prev := ""
	for i := uint32(0); i < count; i++ {
		start := pos
		if pos+fixed > len(body) {
			return nil, errIndex
		}
		mode := binary.BigEndian.Uint32(b[pos+24 : pos+28])
		flags := binary.BigEndian.Uint16(b[pos+40+hsz : pos+fixed])
		pos += fixed
		if flags&0x4000 != 0 { // extended flags (version 3 and later)
			if version < 3 || pos+2 > len(body) {
				return nil, errIndex
			}
			pos += 2
		}
		var name string
		if version == 4 {
			strip, n := varint(body[pos:])
			if n == 0 || strip > uint64(len(prev)) {
				return nil, errIndex
			}
			pos += n
			end := bytes.IndexByte(body[pos:], 0)
			if end < 0 {
				return nil, errIndex
			}
			name = prev[:len(prev)-int(strip)] + string(body[pos:pos+end])
			pos += end + 1
		} else {
			end := bytes.IndexByte(body[pos:], 0)
			if end < 0 {
				return nil, errIndex
			}
			name = string(body[pos : pos+end])
			// entries are padded with 1-8 NULs to a multiple of 8 bytes
			pos = start + ((pos+end-start)+8)&^7
		}
		if mode&0o170000 == 0o040000 {
			return nil, errors.New("a sparse index: run `git sparse-checkout disable` or check out without a sparse index")
		}
		out = append(out, name)
		prev = name
	}
	// extensions: refuse the one that moves entries into another file
	for pos+8 <= len(body) {
		sig := string(body[pos : pos+4])
		size := int(binary.BigEndian.Uint32(body[pos+4 : pos+8]))
		if sig == "link" {
			return nil, errors.New("a split index: run `git update-index --no-split-index`")
		}
		if size < 0 || pos+8+size > len(body) {
			return nil, errIndex
		}
		pos += 8 + size
	}
	return out, nil
}

// varint is git's offset varint (decode_varint in varint.c).
func varint(b []byte) (uint64, int) {
	if len(b) == 0 {
		return 0, 0
	}
	c := b[0]
	val := uint64(c & 127)
	n := 1
	for c&128 != 0 {
		if n >= len(b) || n > 9 {
			return 0, 0
		}
		c = b[n]
		n++
		val = ((val + 1) << 7) | uint64(c&127)
	}
	return val, n
}

// quotePath is how git prints a path with core.quotePath on (its default): as
// is, or in double quotes with C escapes when it holds a control character, a
// double quote, a backslash or a byte of 0x80 and above.
func quotePath(p string) string {
	need := false
	for i := 0; i < len(p); i++ {
		if c := p[i]; c < 0x20 || c == '"' || c == '\\' || c >= 0x7f {
			need = true
			break
		}
	}
	if !need {
		return p
	}
	var sb strings.Builder
	sb.WriteByte('"')
	for i := 0; i < len(p); i++ {
		c := p[i]
		switch c {
		case '\a':
			sb.WriteString(`\a`)
		case '\b':
			sb.WriteString(`\b`)
		case '\t':
			sb.WriteString(`\t`)
		case '\n':
			sb.WriteString(`\n`)
		case '\v':
			sb.WriteString(`\v`)
		case '\f':
			sb.WriteString(`\f`)
		case '\r':
			sb.WriteString(`\r`)
		case '"':
			sb.WriteString(`\"`)
		case '\\':
			sb.WriteString(`\\`)
		default:
			if c < 0x20 || c >= 0x7f {
				fmt.Fprintf(&sb, `\%03o`, c)
			} else {
				sb.WriteByte(c)
			}
		}
	}
	sb.WriteByte('"')
	return sb.String()
}
