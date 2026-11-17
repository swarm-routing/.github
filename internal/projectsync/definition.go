// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package projectsync

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// Definition is the org Project as code (templates/projects/plan.json): what
// the project is, which issues it holds (the add rules), the fields derived
// for each, and its views. Nothing in the project is typed by hand: project-sync
// makes the project match this file and the issues' labels and state.
type Definition struct {
	Title            string   `json:"title"`
	ShortDescription string   `json:"short_description"`
	Readme           string   `json:"readme"`
	Public           bool     `json:"public"`
	Repositories     []string `json:"repositories"`
	Add              []Rule   `json:"add"`
	Fields           []Field  `json:"fields"`
	Views            []View   `json:"views"`
}

// Rule adds every issue carrying Label, or a label starting with
// LabelPrefix, in every repository in scope; closed issues too when Closed.
type Rule struct {
	Label       string `json:"label,omitempty"`
	LabelPrefix string `json:"label_prefix,omitempty"`
	Closed      bool   `json:"closed"`
}

// Field is a project field and how its value is derived for an issue.
//
//	from "status":       Open, In progress (open, a sub-issue closed), Done
//	                     (closed as completed), Dropped (closed otherwise);
//	                     the four options must be listed
//	from "label_prefix": the issue's label starting with Prefix, without it
//	                     (the highest version when several); the options are
//	                     the values found, in version order, coloured Color
//	from "labels":       the first option whose Label or LabelPrefix the
//	                     issue carries
//	from "sub_issues":   "closed/total" of the issue's sub-issues (text)
type Field struct {
	Name    string   `json:"name"`
	Type    string   `json:"type"` // single_select or text
	From    string   `json:"from"`
	Prefix  string   `json:"prefix,omitempty"`
	Color   string   `json:"color,omitempty"`
	Options []Option `json:"options,omitempty"`
}

// Option is one single-select option; Label or LabelPrefix select it for a
// field derived from labels.
type Option struct {
	Name        string `json:"name"`
	Color       string `json:"color"`
	Description string `json:"description,omitempty"`
	Label       string `json:"label,omitempty"`
	LabelPrefix string `json:"label_prefix,omitempty"`
}

// View is a project view. GroupBy, VerticalGroupBy and SortBy name fields
// (one of Fields, or a built-in field such as Repository).
type View struct {
	Name            string     `json:"name"`
	Layout          string     `json:"layout"` // table, board or roadmap
	Filter          string     `json:"filter,omitempty"`
	GroupBy         string     `json:"group_by,omitempty"`
	VerticalGroupBy string     `json:"vertical_group_by,omitempty"`
	SortBy          [][]string `json:"sort_by,omitempty"` // [field, asc|desc]
}

// Status values of a field derived from "status".
const (
	StatusOpen       = "Open"
	StatusInProgress = "In progress"
	StatusDone       = "Done"
	StatusDropped    = "Dropped"
)

var (
	colors     = map[string]bool{"BLUE": true, "GRAY": true, "GREEN": true, "ORANGE": true, "PINK": true, "PURPLE": true, "RED": true, "YELLOW": true}
	layouts    = map[string]bool{"table": true, "board": true, "roadmap": true}
	repoNameRe = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

// Load reads and validates a definition; unknown keys are refused.
func Load(path string) (*Definition, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return Parse(data)
}

// Parse decodes and validates a definition.
func Parse(data []byte) (*Definition, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	var d Definition
	if err := dec.Decode(&d); err != nil {
		return nil, fmt.Errorf("definition: %v", err)
	}
	if err := d.Validate(); err != nil {
		return nil, err
	}
	return &d, nil
}

// Validate checks every rule the sync relies on.
func (d *Definition) Validate() error {
	var errs []string
	bad := func(f string, a ...any) { errs = append(errs, fmt.Sprintf(f, a...)) }
	if strings.TrimSpace(d.Title) == "" {
		bad("title is empty")
	}
	if !d.Public {
		bad("public must be true (maintainer decision on swarm-routing/.github#541)")
	}
	for _, r := range d.Repositories {
		if !repoNameRe.MatchString(r) {
			bad("repository %q is not a repository name", r)
		}
	}
	if len(d.Add) == 0 {
		bad("no add rule")
	}
	for i, r := range d.Add {
		if (r.Label == "") == (r.LabelPrefix == "") {
			bad("add[%d]: exactly one of label and label_prefix", i)
		}
	}
	names := map[string]Field{}
	for _, f := range d.Fields {
		if f.Name == "" {
			bad("a field has no name")
			continue
		}
		if _, dup := names[strings.ToLower(f.Name)]; dup {
			bad("field %q: defined twice", f.Name)
		}
		names[strings.ToLower(f.Name)] = f
		switch f.Type {
		case "single_select", "text":
		default:
			bad("field %q: type %q is not single_select or text", f.Name, f.Type)
		}
		seen := map[string]bool{}
		for _, o := range f.Options {
			if o.Name == "" || seen[o.Name] {
				bad("field %q: an option is unnamed or twice", f.Name)
			}
			seen[o.Name] = true
			if !colors[o.Color] {
				bad("field %q: option %q: colour %q", f.Name, o.Name, o.Color)
			}
		}
		switch f.From {
		case "status":
			if f.Type != "single_select" {
				bad("field %q: from status needs single_select", f.Name)
			}
			for _, s := range []string{StatusOpen, StatusInProgress, StatusDone, StatusDropped} {
				if !seen[s] {
					bad("field %q: from status needs the option %q", f.Name, s)
				}
			}
		case "label_prefix":
			if f.Type != "single_select" || f.Prefix == "" || len(f.Options) > 0 || !colors[f.Color] {
				bad("field %q: from label_prefix needs single_select, a prefix, a colour and no options", f.Name)
			}
		case "labels":
			if f.Type != "single_select" || len(f.Options) == 0 {
				bad("field %q: from labels needs single_select and options", f.Name)
			}
			for _, o := range f.Options {
				if (o.Label == "") == (o.LabelPrefix == "") {
					bad("field %q: option %q: exactly one of label and label_prefix", f.Name, o.Name)
				}
			}
		case "sub_issues":
			if f.Type != "text" {
				bad("field %q: from sub_issues needs text", f.Name)
			}
		default:
			bad("field %q: from %q is not status, label_prefix, labels or sub_issues", f.Name, f.From)
		}
	}
	views := map[string]bool{}
	for _, v := range d.Views {
		if v.Name == "" || views[v.Name] {
			bad("a view is unnamed or twice")
		}
		views[v.Name] = true
		if !layouts[v.Layout] {
			bad("view %q: layout %q is not table, board or roadmap", v.Name, v.Layout)
		}
		if v.VerticalGroupBy != "" && v.Layout != "board" {
			bad("view %q: vertical_group_by is for a board", v.Name)
		}
		for _, s := range v.SortBy {
			if len(s) != 2 || (s[1] != "asc" && s[1] != "desc") {
				bad("view %q: sort_by entries are [field, asc|desc]", v.Name)
			}
		}
	}
	if len(errs) > 0 {
		return fmt.Errorf("definition: %s", strings.Join(errs, "; "))
	}
	return nil
}
