// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package sum

import "testing"

func TestOf(t *testing.T) {
	for _, c := range []struct {
		in   []int
		want int
	}{{nil, 0}, {[]int{1, 2, 3}, 6}, {[]int{-4, 4}, 0}} {
		if got := Of(c.in); got != c.want {
			t.Errorf("Of(%v) = %d, want %d", c.in, got, c.want)
		}
	}
}
