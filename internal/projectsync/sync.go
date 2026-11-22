// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Package projectsync generates the org Project, "Swarm routing plan", from
// the record (swarm-routing/.github#541, option (b)): a read-only view of the
// issues, never a second source of truth. templates/projects/plan.json says
// which issues it holds (add rules on labels), which fields are derived for
// each (from labels, issue state and sub-issue progress) and its views; the
// sync makes the project match it:
//
//   - the project is created when missing, public, with the definition's
//     title, description and readme;
//   - each field is created, and a single-select field's options set to the
//     definition's (or, for a release field, to the versions the issues carry);
//   - every issue an add rule takes is added, and every derived value set;
//     a value edited by hand is set back, and an item no rule takes (a
//     removed label, an issue added by hand, a draft, a pull request) is
//     removed;
//   - an issue of a private repository is never added, and one found in the
//     project is removed; its repository is never named in the output (a
//     public workflow log holds it);
//   - a view missing by name is created (REST; the API cannot update or
//     delete a view, so a changed view is reported for the maintainer to
//     delete in the project, and the next run recreates it);
//   - every project the org owns, this one included, is made public, and a
//     refusal fails the run and keeps the maintainer's issue (public.go, #707).
//
// A dry run reads everything and prints the diff. Writes are bounded per run
// (MaxWrites) and paced (GitHub's secondary rate limits); what is left waits
// for the next run.
package projectsync

import (
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/swarm-routing/.github/internal/repomask"
)

// Org is the organization whose project is generated.
const Org = "swarm-routing"

const (
	// MaxItems bounds the project (golden rule 7): a definition that takes
	// more issues is refused, never truncated.
	MaxItems = 2000
	// MaxWrites bounds the write requests of one run.
	MaxWrites = 400
)

// Result counts what a run did (or, dry, would do).
type Result struct {
	Wanted, Added, Updated, Removed, Views, Refused int
	Deferred                                        bool
	// VisibilityRefused: the token may not make an org project public (the
	// maintainer's step, in the issue public.go keeps; the run fails, #707)
	VisibilityRefused bool
	// MadePublic counts the private org projects the run made public.
	MadePublic int
}

type syncer struct {
	g      GitHub
	d      *Definition
	dry    bool
	out    io.Writer
	mask   *repomask.Masker
	writes int
	res    Result
}

func (s *syncer) say(f string, a ...any) {
	fmt.Fprintln(s.out, s.mask.Scrub(fmt.Sprintf(f, a...)))
}

// write spends one write of the budget; false when it is spent.
func (s *syncer) write() bool {
	if s.writes >= MaxWrites {
		s.res.Deferred = true
		return false
	}
	s.writes++
	return true
}

func (s *syncer) would() string {
	if s.dry {
		return "would "
	}
	return ""
}

// Wanted reads the issues the definition takes, from public repositories
// only; a private repository the definition names is refused, unnamed.
func Wanted(g GitHub, d *Definition, mask *repomask.Masker, out io.Writer) ([]Issue, int, error) {
	repos, err := g.Repos(Org, d.Repositories)
	if err != nil {
		return nil, 0, mask.Error(err)
	}
	var all []Issue
	refused := 0
	for _, r := range repos {
		if r.Private {
			refused++
			fmt.Fprintf(out, "%s: refused: a private repository is never added to the public project\n",
				mask.Repo(r.Name, true, Org+"/"+r.Name, r.Name))
			continue
		}
		iss, err := g.Issues(Org, r.Name, d)
		if err != nil {
			return nil, refused, err
		}
		all = append(all, iss...)
	}
	if len(all) > MaxItems {
		return nil, refused, fmt.Errorf("%d issues wanted, more than %d: narrow the add rules", len(all), MaxItems)
	}
	sort.SliceStable(all, func(i, j int) bool {
		if all[i].Repo != all[j].Repo {
			return strings.ToLower(all[i].Repo) < strings.ToLower(all[j].Repo)
		}
		return all[i].Number < all[j].Number
	})
	return all, refused, nil
}

// Run makes the project match the definition (or, dry, prints the diff).
func Run(g GitHub, d *Definition, dry bool, out io.Writer) (Result, error) {
	s := &syncer{g: g, d: d, dry: dry, out: out, mask: &repomask.Masker{}}
	issues, refused, err := Wanted(g, d, s.mask, out)
	s.res.Refused = refused
	if err != nil {
		return s.res, s.mask.Error(err)
	}
	s.res.Wanted = len(issues)
	err = s.sync(issues)
	if err == nil {
		// after the sync, so a project it just created is covered too
		err = s.allPublic()
	}
	verb := map[bool]string{true: "would ", false: ""}[dry]
	fmt.Fprintf(out, "project-sync: %q: %d items wanted; %sadd %d, %sset %d values, %sremove %d, %screate %d views; %d private repositories refused%s\n",
		d.Title, s.res.Wanted, verb, s.res.Added, verb, s.res.Updated, verb, s.res.Removed, verb, s.res.Views, s.res.Refused,
		map[bool]string{true: "; write budget spent, the rest waits for the next run", false: ""}[s.res.Deferred])
	return s.res, s.mask.Error(err)
}

func (s *syncer) sync(issues []Issue) error {
	ownerID, number, err := s.g.FindProject(Org, s.d.Title)
	if err != nil {
		return fmt.Errorf("%w (the org-bot App needs the organization Projects permission)", err)
	}
	var p *Project
	if number == 0 {
		s.say("project %q: %screate (public)", s.d.Title, s.would())
		if s.dry {
			p = &Project{Title: s.d.Title}
		} else {
			if !s.write() {
				return nil
			}
			var r struct {
				CreateProjectV2 struct {
					ProjectV2 struct {
						Number int `json:"number"`
					} `json:"projectV2"`
				} `json:"createProjectV2"`
			}
			if err := s.g.GraphQL(mCreateProject, map[string]any{"owner": ownerID, "title": s.d.Title}, &r); err != nil {
				return err
			}
			s.g.pause()
			number = r.CreateProjectV2.ProjectV2.Number
		}
	}
	if p == nil {
		if p, err = s.g.ReadProject(Org, number); err != nil {
			return err
		}
	}
	if err := s.project(p); err != nil {
		return err
	}
	changed, err := s.fields(p, issues)
	if err != nil {
		return err
	}
	if changed && !s.dry {
		if p, err = s.g.ReadProject(Org, number); err != nil {
			return err
		}
	}
	if err := s.items(p, issues); err != nil {
		return err
	}
	return s.views(p)
}

// VisibilityRefused is the error text GitHub returns when the token may not
// change a project's visibility.
const VisibilityRefused = "not authorized to change project visibility"

// project sets the title, description and readme; its visibility is the
// all-public rule's, with every other org project (public).
func (s *syncer) project(p *Project) error {
	var diff []string
	if p.Title != s.d.Title {
		diff = append(diff, "title")
	}
	if p.ShortDescription != s.d.ShortDescription {
		diff = append(diff, "description")
	}
	if p.Readme != s.d.Readme {
		diff = append(diff, "readme")
	}
	if len(diff) == 0 {
		return nil
	}
	s.say("project %q: %sset %s", s.d.Title, s.would(), strings.Join(diff, ", "))
	if s.dry || !s.write() {
		return nil
	}
	defer s.g.pause()
	return s.g.GraphQL(mUpdateProject, map[string]any{"p": p.ID, "title": s.d.Title,
		"desc": s.d.ShortDescription, "readme": s.d.Readme}, nil)
}

func names(o []Option) []string {
	var n []string
	for _, x := range o {
		n = append(n, x.Name)
	}
	return n
}

func sameOptions(have []POption, want []Option) bool {
	if len(have) != len(want) {
		return false
	}
	for i := range have {
		if have[i].Name != want[i].Name || have[i].Color != want[i].Color || have[i].Description != want[i].Description {
			return false
		}
	}
	return true
}

// fields creates missing fields and sets single-select options; true when
// something was written.
func (s *syncer) fields(p *Project, issues []Issue) (bool, error) {
	changed := false
	for _, f := range s.d.Fields {
		want := f.WantedOptions(issues)
		gqlType := map[string]string{"single_select": "SINGLE_SELECT", "text": "TEXT"}[f.Type]
		have := p.Field(f.Name)
		switch {
		case have == nil:
			s.say("field %s: %screate (%s%s)", f.Name, s.would(), strings.ToLower(gqlType),
				map[bool]string{true: ": " + strings.Join(names(want), ", "), false: ""}[f.Type == "single_select"])
			if s.dry {
				continue
			}
			if f.Type == "single_select" && len(want) == 0 {
				// GitHub needs at least one option; the field waits for a value
				s.say("field %s: no value yet, not created", f.Name)
				continue
			}
			if !s.write() {
				return changed, nil
			}
			vars := map[string]any{"p": p.ID, "name": f.Name, "type": gqlType}
			if f.Type == "single_select" {
				vars["options"] = optionInput(want)
			}
			if err := s.g.GraphQL(mCreateField, vars, nil); err != nil {
				return changed, err
			}
			s.g.pause()
			changed = true
		case have.DataType != gqlType:
			return changed, fmt.Errorf("field %s is %s in the project, %s in the definition: rename or delete it in the project", f.Name, have.DataType, gqlType)
		case f.Type == "single_select" && !sameOptions(have.Options, want) && len(want) > 0:
			var hn []string
			for _, o := range have.Options {
				hn = append(hn, o.Name)
			}
			s.say("field %s: %sset options [%s] -> [%s]", f.Name, s.would(), strings.Join(hn, ", "), strings.Join(names(want), ", "))
			if s.dry {
				continue
			}
			if !s.write() {
				return changed, nil
			}
			if err := s.g.GraphQL(mUpdateField, map[string]any{"f": have.ID, "options": optionInput(want)}, nil); err != nil {
				return changed, err
			}
			s.g.pause()
			changed = true
		}
	}
	return changed, nil
}

// itemName names an item in the output; a private repository is masked.
func (s *syncer) itemName(it PItem) string {
	if it.Repo == "" {
		return "item " + it.ID
	}
	full := it.Owner + "/" + it.Repo
	return fmt.Sprintf("%s#%d", s.mask.Repo(it.Repo, it.Private || it.Owner != Org, full, it.Repo), it.Number)
}

func (s *syncer) items(p *Project, issues []Issue) error {
	want := map[string]Issue{}
	for _, i := range issues {
		want[i.NodeID] = i
	}
	have := map[string]PItem{}
	var remove []struct {
		it     PItem
		reason string
	}
	for _, it := range p.Items {
		reason := ""
		switch {
		case it.Private:
			reason = "a private repository's issue"
		case it.Type != "ISSUE" || it.Owner != Org:
			reason = "not an org issue (added by hand)"
		case have[it.IssueID].ID != "":
			reason = "a duplicate"
		case want[it.IssueID].NodeID == "":
			reason = "no add rule takes it"
		}
		if reason != "" {
			remove = append(remove, struct {
				it     PItem
				reason string
			}{it, reason})
			continue
		}
		have[it.IssueID] = it
	}
	for _, i := range issues {
		it, ok := have[i.NodeID]
		if !ok {
			s.say("%s: %sadd", i.Key(), s.would())
			s.res.Added++
			if !s.dry {
				if !s.write() {
					return nil
				}
				var r struct {
					AddProjectV2ItemByID struct {
						Item struct {
							ID string `json:"id"`
						} `json:"item"`
					} `json:"addProjectV2ItemById"`
				}
				if err := s.g.GraphQL(mAddItem, map[string]any{"p": p.ID, "c": i.NodeID}, &r); err != nil {
					return fmt.Errorf("%s: %w", i.Key(), err)
				}
				s.g.pause()
				it = PItem{ID: r.AddProjectV2ItemByID.Item.ID, Values: map[string]string{}}
			} else {
				it = PItem{Values: map[string]string{}}
			}
		}
		if err := s.values(p, it, i); err != nil {
			return err
		}
	}
	sort.SliceStable(remove, func(a, b int) bool { return s.itemName(remove[a].it) < s.itemName(remove[b].it) })
	for _, r := range remove {
		s.say("%s: %sremove (%s)", s.itemName(r.it), s.would(), r.reason)
		s.res.Removed++
		if s.dry {
			continue
		}
		if !s.write() {
			return nil
		}
		if err := s.g.GraphQL(mDeleteItem, map[string]any{"p": p.ID, "i": r.it.ID}, nil); err != nil {
			return s.mask.Error(fmt.Errorf("%s: %w", s.itemName(r.it), err))
		}
		s.g.pause()
	}
	return nil
}

// values sets every derived field of one item that differs, in one request.
func (s *syncer) values(p *Project, it PItem, i Issue) error {
	vars := map[string]any{"p": p.ID, "i": it.ID}
	var kinds []string
	for _, f := range s.d.Fields {
		want := f.Value(i)
		if it.Values[strings.ToLower(f.Name)] == want {
			continue
		}
		s.say("%s: %s %q -> %q", i.Key(), f.Name, it.Values[strings.ToLower(f.Name)], want)
		s.res.Updated++
		if s.dry {
			continue
		}
		pf := p.Field(f.Name)
		if pf == nil {
			continue // a single-select field with no value yet
		}
		k := len(kinds)
		vars[fmt.Sprintf("f%d", k)] = pf.ID
		switch {
		case want == "":
			kinds = append(kinds, "clear")
		case f.Type == "text":
			kinds = append(kinds, "text")
			vars[fmt.Sprintf("v%d", k)] = want
		default:
			id := ""
			for _, o := range pf.Options {
				if o.Name == want {
					id = o.ID
				}
			}
			if id == "" {
				return fmt.Errorf("%s: field %s has no option %q", i.Key(), f.Name, want)
			}
			kinds = append(kinds, "singleSelectOptionId")
			vars[fmt.Sprintf("v%d", k)] = id
		}
	}
	if s.dry || len(kinds) == 0 {
		return nil
	}
	if !s.write() {
		return nil
	}
	if err := s.g.GraphQL(setItemDoc(len(kinds), kinds), vars, nil); err != nil {
		return fmt.Errorf("%s: %w", i.Key(), err)
	}
	s.g.pause()
	return nil
}

var layoutEnum = map[string]string{"table": "TABLE_LAYOUT", "board": "BOARD_LAYOUT", "roadmap": "ROADMAP_LAYOUT"}

func (s *syncer) views(p *Project) error {
	for _, v := range s.d.Views {
		found := false
		for _, h := range p.Views {
			if h.Name != v.Name {
				continue
			}
			found = true
			if h.Layout != layoutEnum[v.Layout] {
				s.say("view %s: is %s, the definition says %s: the API cannot change a view; delete it in the project and the next run recreates it", v.Name, h.Layout, layoutEnum[v.Layout])
			}
		}
		if found {
			continue
		}
		s.say("view %s: %screate (%s)", v.Name, s.would(), v.Layout)
		s.res.Views++
		if s.dry {
			continue
		}
		body := map[string]any{"name": v.Name, "layout": v.Layout}
		if v.Filter != "" {
			body["filter"] = v.Filter
		}
		id := func(name string) (int, error) {
			f := p.Field(name)
			if f == nil || f.DatabaseID == 0 {
				return 0, fmt.Errorf("view %s: no field %q in the project", v.Name, name)
			}
			return f.DatabaseID, nil
		}
		if v.GroupBy != "" {
			n, err := id(v.GroupBy)
			if err != nil {
				return err
			}
			body["group_by"] = []int{n}
		}
		if v.VerticalGroupBy != "" {
			n, err := id(v.VerticalGroupBy)
			if err != nil {
				return err
			}
			body["vertical_group_by"] = []int{n}
		}
		var sortBy [][]any
		for _, sb := range v.SortBy {
			n, err := id(sb[0])
			if err != nil {
				return err
			}
			sortBy = append(sortBy, []any{n, sb[1]})
		}
		if len(sortBy) > 0 {
			body["sort_by"] = sortBy
		}
		if !s.write() {
			return nil
		}
		if _, err := s.g.do("POST", fmt.Sprintf("orgs/%s/projectsV2/%d/views", Org, p.Number), viewsVersion, body); err != nil {
			return err
		}
		s.g.pause()
	}
	return nil
}

const usage = "usage: project-sync [--dry-run | --validate | --wanted] [--definition PATH]"

// Main is the command. GH_TOKEN: the org App's installation token, with the
// organization Projects permission (read and write) and Issues read on the
// repositories; with no token, --wanted only.
func Main(args []string, getenv func(string) string, client *http.Client, api string, stdout, stderr io.Writer) int {
	dry, validate, wanted := false, false, false
	def := "templates/projects/plan.json"
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--dry-run":
			dry = true
		case a == "--validate":
			validate = true
		case a == "--wanted":
			wanted = true
		case a == "--definition" && i+1 < len(args):
			def = args[i+1]
			i++
		case a == "-h" || a == "--help":
			fmt.Fprintln(stdout, usage)
			return 0
		default:
			fmt.Fprintln(stderr, usage)
			return 2
		}
	}
	d, err := Load(def)
	if err != nil {
		fmt.Fprintln(stderr, "project-sync:", err)
		return 1
	}
	if validate {
		fmt.Fprintf(stdout, "project-sync: %s: valid (%d add rules, %d fields, %d views)\n", def, len(d.Add), len(d.Fields), len(d.Views))
		return 0
	}
	token := getenv("GH_TOKEN")
	g := GitHub{API: api, Token: token, Client: client, Pause: 700 * time.Millisecond, Sleep: time.Sleep}
	if token == "" && !wanted {
		fmt.Fprintln(stdout, "project-sync: no GH_TOKEN: the wanted items only (the project needs a token to read)")
		wanted = true
	}
	if wanted {
		mask := &repomask.Masker{}
		issues, refused, err := Wanted(g, d, mask, stdout)
		if err != nil {
			fmt.Fprintln(stderr, "project-sync:", mask.Scrub(err.Error()))
			return 1
		}
		for _, i := range issues {
			var vals []string
			for _, f := range d.Fields {
				vals = append(vals, fmt.Sprintf("%s=%q", f.Name, f.Value(i)))
			}
			fmt.Fprintf(stdout, "%s: %s\n", i.Key(), strings.Join(vals, " "))
		}
		fmt.Fprintf(stdout, "project-sync: %q: %d items wanted; %d private repositories refused\n", d.Title, len(issues), refused)
		return 0
	}
	if _, err := Run(g, d, dry, stdout); err != nil {
		fmt.Fprintln(stderr, "project-sync:", err)
		return 1
	}
	return 0
}
