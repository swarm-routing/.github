// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package sum is reusable-go-ci.yml's passing fixture: every check is clean
// and its test covers every statement.
package sum

// Of returns the sum of xs.
func Of(xs []int) int {
	total := 0
	for _, x := range xs {
		total += x
	}
	return total
}
