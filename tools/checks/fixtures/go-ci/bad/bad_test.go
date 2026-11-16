// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package bad

import "testing"

// TestTwice fails on purpose: go test.
func TestTwice(t *testing.T) {
	if got := Twice(2); got != 5 {
		t.Errorf("Twice(2) = %d, want 5 (a deliberate failure)", got)
	}
}
