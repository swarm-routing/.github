// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bestpractices

// What the Python tool's output depended on, kept so the port prints the same
// bytes: str() of a decoded JSON value, truthiness, ==, os.path.join,
// urllib.parse.quote(safe=""), json.dumps(indent=2, ensure_ascii=False) and
// the "<type>: <message>" of a caught exception.

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

// PyError is an error printed as Python printed the exception it stands for:
// Type is what `type(e).__name__` gave (URLError, HTTPError, ValueError,
// Failure, ...), Msg what `str(e)` gave.
type PyError struct {
	Type string
	Msg  string
}

func (e *PyError) Error() string { return e.Msg }

func failure(format string, a ...any) error {
	return &PyError{"Failure", fmt.Sprintf(format, a...)}
}

func valueError(msg string) error { return &PyError{"ValueError", msg} }

// typeName is `type(e).__name__` of the exception err stands for.
func typeName(err error) string {
	var pe *PyError
	if errors.As(err, &pe) {
		return pe.Type
	}
	var se *json.SyntaxError
	if errors.As(err, &se) {
		return "JSONDecodeError"
	}
	return "OSError"
}

// described is `f"{type(e).__name__}: {e}"`.
func described(err error) string { return typeName(err) + ": " + err.Error() }

// pyStr is Python's str() of a value json.loads returned (numbers decoded
// as json.Number).
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	case bool:
		if x {
			return "True"
		}
		return "False"
	case json.Number:
		if _, err := strconv.ParseInt(string(x), 10, 64); err == nil {
			return string(x)
		}
		if f, err := strconv.ParseFloat(string(x), 64); err == nil {
			return pyFloat(f)
		}
		return string(x)
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return pyFloat(x)
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = pyRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sortStrings(keys)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = pyRepr(k) + ": " + pyRepr(x[k])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

func pyRepr(v any) string {
	if s, ok := v.(string); ok {
		return "'" + strings.ReplaceAll(strings.ReplaceAll(s, `\`, `\\`), "'", `\'`) + "'"
	}
	return pyStr(v)
}

func pyFloat(f float64) string {
	if math.IsInf(f, 1) {
		return "inf"
	}
	if f == math.Trunc(f) && math.Abs(f) < 1e16 {
		return strconv.FormatFloat(f, 'f', 1, 64)
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}

// truthy is Python's bool() of a decoded JSON value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func number(v any) (float64, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case json.Number:
		f, err := x.Float64()
		return f, err == nil
	}
	return 0, false
}

// pyEqual is Python's == of two decoded JSON values.
func pyEqual(a, b any) bool {
	if fa, ok := number(a); ok {
		fb, ok := number(b)
		return ok && fa == fb
	}
	switch x := a.(type) {
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !pyEqual(x[i], y[i]) {
				return false
			}
		}
		return true
	case map[string]any:
		y, ok := b.(map[string]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for k, v := range x {
			w, ok := y[k]
			if !ok || !pyEqual(v, w) {
				return false
			}
		}
		return true
	}
	return false
}

// pyJoin is os.path.join(a, b) for a relative b.
func pyJoin(a, b string) string {
	if strings.HasPrefix(b, "/") {
		return b
	}
	if a == "" || strings.HasSuffix(a, "/") {
		return a + b
	}
	return a + "/" + b
}

// quote is urllib.parse.quote(s, safe=""): every byte but the unreserved
// characters percent-encoded, upper-case hex.
func quote(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' ||
			c == '_' || c == '.' || c == '-' || c == '~' {
			b.WriteByte(c)
		} else {
			fmt.Fprintf(&b, "%%%02X", c)
		}
	}
	return b.String()
}

// jsonString is json.dumps(s, ensure_ascii=False).
func jsonString(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, r)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

// decodeJSON is json.loads, numbers kept as json.Number.
func decodeJSON(data []byte) (any, error) {
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if dec.More() {
		return nil, &PyError{"JSONDecodeError", "Extra data"}
	}
	return v, nil
}

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}
