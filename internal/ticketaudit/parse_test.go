// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package ticketaudit

import (
	"os"
	"reflect"
	"testing"
)

func read(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestCount(t *testing.T) {
	cases := []struct {
		file string
		want Boxes
	}{
		// the issue-form shape: every acceptance box ticked
		{"done.md", Boxes{Total: 3, Ticked: 3, AC: 3, ACTicked: 3}},
		// an acceptance box open
		{"open.md", Boxes{Total: 4, Ticked: 3, AC: 4, ACTicked: 3}},
		// unticked boxes inside <details> and code fences (``` and ~~~) do not count
		{"superseded.md", Boxes{Total: 2, Ticked: 2, AC: 2, ACTicked: 2}},
		// a bold heading, numbered and nested boxes, an open box outside the section
		{"bold.md", Boxes{Total: 4, Ticked: 3, AC: 3, ACTicked: 3}},
		// no checkbox at all
		{"none.md", Boxes{}},
		// boxes, none under an acceptance heading
		{"noac.md", Boxes{Total: 2, Ticked: 2}},
		{"unclosed-details.md", Boxes{Unparseable: true, UnparseableReason: "a <details> block never closes"}},
		{"unclosed-fence.md", Boxes{Unparseable: true, UnparseableReason: "a code fence never closes"}},
	}
	for _, c := range cases {
		if got := Count(read(t, c.file)); got != c.want {
			t.Errorf("%s: got %+v, want %+v", c.file, got, c.want)
		}
	}
	if r := (Boxes{Total: 5, Ticked: 4}).Ratio(); r != 0.8 {
		t.Errorf("ratio %v", r)
	}
}

func TestClosingRefs(t *testing.T) {
	body := "Closes #12, fixes swarm-routing/beta#3.\nResolved: https://github.com/swarm-routing/gamma/issues/9\n" +
		"Part of #44. closes other-org/x#5\nFIXES #12\n```\nCloses #77\n```\nprefixcloses #8\n"
	want := []Ref{{"alpha", 12}, {"beta", 3}, {"gamma", 9}}
	if got := ClosingRefs(body, "alpha"); !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
	if got := (Ref{"beta", 3}).String(); got != "swarm-routing/beta#3" {
		t.Error(got)
	}
}

func TestSuperseded(t *testing.T) {
	body := "Supersedes #10 and swarm-routing/alpha#7, swarm-routing/beta#4 & #2. Not #40, kept in #41\n" +
		"Supersedes #648. The security pipeline keeps its own handoff, #643.\n" +
		"Superseded by #99\n- **Supersedes:** #3\n<details>\nSupersedes #5\n</details>\n"
	if got := Superseded(body, "alpha"); !reflect.DeepEqual(got, []int{2, 3, 7, 10, 648}) {
		t.Errorf("got %v", got)
	}
}
