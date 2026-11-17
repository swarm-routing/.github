// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package fixture

// DO NOT MERGE: the proof for swarm-routing/.github#610. This test reads a
// file outside the image's build context, as #567's did: it passes from a
// full checkout (the go job) and fails in the image's build stage, so the
// required `ci-tools image gate` must be red and the PR unmergeable.

import (
	"os"
	"testing"
)

func TestProof610OutsideBuildContext(t *testing.T) {
	if _, err := os.ReadFile("../../.github/bestpractices-owner.toml"); err != nil {
		t.Fatalf("outside the build context: %v", err)
	}
}
