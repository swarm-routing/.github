// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package bad is reusable-go-ci.yml's failing fixture: it builds, but each of
// gofmt, go vet, staticcheck and go test has one finding (go-ci-selftest.yml
// expects exactly those four). It has no dependency, so govulncheck passes:
// a vulnerable module here would raise a real alert on this repository.
package bad

import (
	"fmt"
	"strings"
)

// Label has code after its return: go vet's unreachable check (one that
// go test's own vet subset does not run, so the test step fails only on the
// test).
func Label(n int) string {
	return fmt.Sprint("n=", n)
	n++
	return ""
}

// Same compares case-insensitively the slow way: staticcheck SA6005.
func Same(a, b string) bool {
	return strings.ToLower(a) == strings.ToLower(b)
}

// Twice is not gofmt-formatted.
func  Twice(n int) int { return n*2 }
