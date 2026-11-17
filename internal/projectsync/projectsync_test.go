// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package projectsync

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// ---- the fake GitHub: REST for repositories, labels, issues and views; GraphQL for the project ----

type fIssue struct {
	node, state, reason string
	number              int
	labels              []string
	pr                  bool
	sub                 [2]int // completed, total
}

type fRepo struct {
	name    string
	private bool
	issues  []*fIssue
}

type fOption struct{ id, name, color, desc string }

type fField struct {
	id      string
	dbID    int
	name    string
	typ     string
	options []fOption
}

type fItem struct {
	id, typ, content string
	repo, owner      string
	private          bool
	number           int
	values           map[string]string // field id -> text or option id
}

type fView struct{ name, layout string }

type fake struct {
	mu        sync.Mutex
	repos     []*fRepo
	projNum   int // 0: no project
	title     string
	public    bool
	desc      string
	readme    string
	fields    []*fField
	items     []*fItem
	views     []fView
	viewPosts []map[string]any
	seq       int
	writes    []string // operation names of every write
	refuse    string   // a GraphQL error for every query
	auth      []string
}

func (f *fake) next(p string) string { f.seq++; return fmt.Sprintf("%s_%d", p, f.seq) }

func (f *fake) repo(name string) *fRepo {
	for _, r := range f.repos {
		if r.name == name {
			return r
		}
	}
	return nil
}

// content finds an issue by node id: its repository and the issue.
func (f *fake) content(node string) (*fRepo, *fIssue) {
	for _, r := range f.repos {
		for _, i := range r.issues {
			if i.node == node {
				return r, i
			}
		}
	}
	return nil, nil
}

func (f *fake) field(id string) *fField {
	for _, x := range f.fields {
		if x.id == id {
			return x
		}
	}
	return nil
}

func (f *fake) addField(name, typ string, opts []map[string]any) {
	ff := &fField{id: f.next("PVTF"), dbID: 1000 + f.seq, name: name, typ: typ}
	for _, o := range opts {
		ff.options = append(ff.options, fOption{f.next("opt"), o["name"].(string), o["color"].(string), o["description"].(string)})
	}
	f.fields = append(f.fields, ff)
}

func pageOf[T any](w http.ResponseWriter, r *http.Request, items []T) {
	per, _ := strconv.Atoi(r.URL.Query().Get("per_page"))
	pg, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if per <= 0 || pg <= 0 {
		http.Error(w, "paging", 400)
		return
	}
	lo, hi := (pg-1)*per, pg*per
	if lo > len(items) {
		lo = len(items)
	}
	if hi > len(items) {
		hi = len(items)
	}
	out := items[lo:hi]
	if out == nil {
		out = []T{}
	}
	_ = json.NewEncoder(w).Encode(out)
}

var setRe = regexp.MustCompile(`(u|c)(\d+): (?:update|clear)ProjectV2ItemFieldValue\(input:\{projectId:\$p,itemId:\$i,fieldId:\$f\d+(?:,value:\{(text|singleSelectOptionId):\$v\d+\})?\}\)`)

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.auth = append(f.auth, r.Header.Get("Authorization"))
	path := strings.TrimPrefix(r.URL.Path, "/")
	switch {
	case r.Method == "GET" && path == "orgs/swarm-routing/repos":
		var out []map[string]any
		for _, x := range f.repos {
			if r.URL.Query().Get("type") == "public" && x.private {
				continue
			}
			out = append(out, map[string]any{"name": x.name, "private": x.private, "archived": false})
		}
		pageOf(w, r, out)
	case r.Method == "GET" && strings.HasPrefix(path, "repos/swarm-routing/"):
		parts := strings.Split(strings.TrimPrefix(path, "repos/swarm-routing/"), "/")
		rp := f.repo(parts[0])
		if rp == nil {
			http.Error(w, `{"message":"Not Found"}`, 404)
			return
		}
		switch {
		case len(parts) == 1:
			_ = json.NewEncoder(w).Encode(map[string]any{"name": rp.name, "private": rp.private, "archived": false})
		case parts[1] == "labels":
			seen := map[string]bool{}
			var out []map[string]any
			for _, i := range rp.issues {
				for _, l := range i.labels {
					if !seen[l] {
						seen[l] = true
						out = append(out, map[string]any{"name": l})
					}
				}
			}
			pageOf(w, r, out)
		case parts[1] == "issues":
			label := r.URL.Query().Get("labels")
			var out []map[string]any
			for _, i := range rp.issues {
				has := false
				var ls []map[string]string
				for _, l := range i.labels {
					has = has || l == label
					ls = append(ls, map[string]string{"name": l})
				}
				if !has {
					continue
				}
				m := map[string]any{"node_id": i.node, "number": i.number, "state": i.state, "labels": ls,
					"sub_issues_summary": map[string]int{"completed": i.sub[0], "total": i.sub[1]}}
				if i.reason != "" {
					m["state_reason"] = i.reason
				}
				if i.pr {
					m["pull_request"] = map[string]any{}
				}
				out = append(out, m)
			}
			pageOf(w, r, out)
		default:
			http.Error(w, "unexpected "+path, 500)
		}
	case r.Method == "POST" && strings.HasPrefix(path, "orgs/swarm-routing/projectsV2/") && strings.HasSuffix(path, "/views"):
		if r.Header.Get("X-GitHub-Api-Version") != viewsVersion {
			http.Error(w, "version", 400)
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.viewPosts = append(f.viewPosts, body)
		f.views = append(f.views, fView{body["name"].(string), strings.ToUpper(body["layout"].(string)) + "_LAYOUT"})
		f.writes = append(f.writes, "CreateView")
		w.WriteHeader(201)
		_, _ = w.Write([]byte(`{}`))
	case r.Method == "POST" && path == "graphql":
		var req struct {
			Query     string         `json:"query"`
			Variables map[string]any `json:"variables"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if f.refuse != "" {
			_ = json.NewEncoder(w).Encode(map[string]any{"errors": []map[string]string{{"message": f.refuse}}})
			return
		}
		data, err := f.graphql(opName(req.Query), req.Query, req.Variables)
		if err != nil {
			_ = json.NewEncoder(w).Encode(map[string]any{"errors": []map[string]string{{"message": err.Error()}}})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
	default:
		http.Error(w, "unexpected "+r.Method+" "+path, 500)
	}
}

func (f *fake) projectData() map[string]any {
	var fields []map[string]any
	for _, x := range f.fields {
		m := map[string]any{"__typename": "ProjectV2Field", "id": x.id, "databaseId": x.dbID, "name": x.name, "dataType": x.typ}
		if x.typ == "SINGLE_SELECT" {
			m["__typename"] = "ProjectV2SingleSelectField"
			var os []map[string]any
			for _, o := range x.options {
				os = append(os, map[string]any{"id": o.id, "name": o.name, "color": o.color, "description": o.desc})
			}
			m["options"] = os
		}
		fields = append(fields, m)
	}
	var views []map[string]any
	for _, v := range f.views {
		views = append(views, map[string]any{"name": v.name, "layout": v.layout})
	}
	return map[string]any{"id": "PVT_1", "number": f.projNum, "title": f.title, "public": f.public,
		"shortDescription": f.desc, "readme": f.readme,
		"fields": map[string]any{"nodes": fields}, "views": map[string]any{"nodes": views}}
}

func (f *fake) itemNode(it *fItem) map[string]any {
	var vals []map[string]any
	ids := make([]string, 0, len(it.values))
	for id := range it.values {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		fl := f.field(id)
		if fl == nil {
			continue
		}
		v := it.values[id]
		if fl.typ == "TEXT" {
			vals = append(vals, map[string]any{"__typename": "ProjectV2ItemFieldTextValue", "text": v, "field": map[string]any{"name": fl.name}})
			continue
		}
		for _, o := range fl.options {
			if o.id == v {
				vals = append(vals, map[string]any{"__typename": "ProjectV2ItemFieldSingleSelectValue", "name": o.name, "field": map[string]any{"name": fl.name}})
			}
		}
	}
	// the built-in title value, which every item carries
	vals = append(vals, map[string]any{"__typename": "ProjectV2ItemFieldTextValue", "text": "a title", "field": map[string]any{"name": "Title"}})
	var content any
	if it.typ != "DRAFT_ISSUE" {
		content = map[string]any{"id": it.content, "number": it.number,
			"repository": map[string]any{"name": it.repo, "isPrivate": it.private, "owner": map[string]any{"login": it.owner}}}
	} else {
		content = map[string]any{}
	}
	return map[string]any{"id": it.id, "type": it.typ, "content": content, "fieldValues": map[string]any{"nodes": vals}}
}

func (f *fake) graphql(op, q string, v map[string]any) (any, error) {
	write := strings.HasPrefix(strings.TrimSpace(q), "mutation")
	if write {
		f.writes = append(f.writes, op)
	}
	switch op {
	case "FindProject":
		var nodes []map[string]any
		if f.projNum != 0 && strings.Contains(f.title, v["q"].(string)) {
			nodes = append(nodes, map[string]any{"id": "PVT_1", "number": f.projNum, "title": f.title})
		}
		return map[string]any{"organization": map[string]any{"id": "O_org", "projectsV2": map[string]any{"nodes": nodes}}}, nil
	case "ReadProject":
		if int(v["number"].(float64)) != f.projNum {
			return map[string]any{"organization": map[string]any{"projectV2": nil}}, nil
		}
		return map[string]any{"organization": map[string]any{"projectV2": f.projectData()}}, nil
	case "ReadItems":
		start := 0
		if a, ok := v["after"].(string); ok {
			start, _ = strconv.Atoi(a)
		}
		end := start + 100
		if end > len(f.items) {
			end = len(f.items)
		}
		var nodes []map[string]any
		for _, it := range f.items[start:end] {
			nodes = append(nodes, f.itemNode(it))
		}
		return map[string]any{"organization": map[string]any{"projectV2": map[string]any{"items": map[string]any{
			"pageInfo": map[string]any{"hasNextPage": end < len(f.items), "endCursor": strconv.Itoa(end)}, "nodes": nodes}}}}, nil
	case "CreateProject":
		if v["owner"] != "O_org" {
			return nil, fmt.Errorf("owner")
		}
		f.projNum, f.title = 7, v["title"].(string)
		// a new project has the built-in Status field with GitHub's options
		f.addField("Title", "TITLE", nil)
		f.addField("Repository", "REPOSITORY", nil)
		f.addField("Status", "SINGLE_SELECT", []map[string]any{
			{"name": "Todo", "color": "GRAY", "description": ""}, {"name": "In Progress", "color": "YELLOW", "description": ""},
			{"name": "Done", "color": "GREEN", "description": ""}})
		f.views = append(f.views, fView{"View 1", "TABLE_LAYOUT"})
		return map[string]any{"createProjectV2": map[string]any{"projectV2": map[string]any{"id": "PVT_1", "number": 7}}}, nil
	case "UpdateProject":
		f.title, f.public, f.desc, f.readme = v["title"].(string), v["public"].(bool), v["desc"].(string), v["readme"].(string)
		return map[string]any{}, nil
	case "CreateField":
		var opts []map[string]any
		if o, ok := v["options"].([]any); ok {
			for _, x := range o {
				opts = append(opts, x.(map[string]any))
			}
		}
		f.addField(v["name"].(string), v["type"].(string), opts)
		return map[string]any{}, nil
	case "UpdateField":
		fl := f.field(v["f"].(string))
		if fl == nil {
			return nil, fmt.Errorf("no field")
		}
		// GitHub replaces the options: new ids, and every value of the field is cleared
		fl.options = nil
		for _, x := range v["options"].([]any) {
			o := x.(map[string]any)
			fl.options = append(fl.options, fOption{f.next("opt"), o["name"].(string), o["color"].(string), o["description"].(string)})
		}
		for _, it := range f.items {
			delete(it.values, fl.id)
		}
		return map[string]any{}, nil
	case "AddItem":
		rp, is := f.content(v["c"].(string))
		if rp == nil {
			return nil, fmt.Errorf("no content")
		}
		it := &fItem{id: f.next("PVTI"), typ: "ISSUE", content: is.node, repo: rp.name, owner: "swarm-routing",
			private: rp.private, number: is.number, values: map[string]string{}}
		f.items = append(f.items, it)
		return map[string]any{"addProjectV2ItemById": map[string]any{"item": map[string]any{"id": it.id}}}, nil
	case "DeleteItem":
		for k, it := range f.items {
			if it.id == v["i"] {
				f.items = append(f.items[:k], f.items[k+1:]...)
				return map[string]any{}, nil
			}
		}
		return nil, fmt.Errorf("no item")
	case "SetItem":
		var it *fItem
		for _, x := range f.items {
			if x.id == v["i"] {
				it = x
			}
		}
		if it == nil {
			return nil, fmt.Errorf("no item")
		}
		for _, m := range setRe.FindAllStringSubmatch(q, -1) {
			k := m[2]
			fid := v["f"+k].(string)
			if m[1] == "c" {
				delete(it.values, fid)
				continue
			}
			val := v["v"+k].(string)
			if m[3] == "singleSelectOptionId" {
				ok := false
				for _, o := range f.field(fid).options {
					ok = ok || o.id == val
				}
				if !ok {
					return nil, fmt.Errorf("no option %s", val)
				}
			}
			it.values[fid] = val
		}
		return map[string]any{}, nil
	}
	return nil, fmt.Errorf("unknown operation %s", op)
}

// ---- helpers ----

func defn(t *testing.T, repos ...string) *Definition {
	t.Helper()
	d := &Definition{
		Title: "Swarm routing plan", ShortDescription: "generated", Readme: "read only", Public: true, Repositories: repos,
		Add: []Rule{{LabelPrefix: "release:", Closed: true}, {Label: "rcapa", Closed: true}, {Label: "handoff"}},
		Fields: []Field{
			{Name: "Status", Type: "single_select", From: "status", Options: []Option{
				{Name: StatusOpen, Color: "GRAY"}, {Name: StatusInProgress, Color: "YELLOW"}, {Name: StatusDone, Color: "GREEN"}, {Name: StatusDropped, Color: "RED"}}},
			{Name: "Release", Type: "single_select", From: "label_prefix", Prefix: "release:", Color: "BLUE"},
			{Name: "Track", Type: "single_select", From: "labels", Options: []Option{
				{Name: "RCAPA", Color: "PINK", Label: "rcapa"}, {Name: "Release", Color: "BLUE", LabelPrefix: "release:"}}},
			{Name: "Sub-issues", Type: "text", From: "sub_issues"},
		},
		Views: []View{
			{Name: "Releases", Layout: "table", Filter: "has:release", GroupBy: "Release", SortBy: [][]string{{"Repository", "asc"}}},
			{Name: "RCAPA", Layout: "board", Filter: "track:rcapa", VerticalGroupBy: "Status"},
		},
	}
	if err := d.Validate(); err != nil {
		t.Fatal(err)
	}
	return d
}

func newFake() *fake {
	return &fake{repos: []*fRepo{
		{name: "ns3-tools", issues: []*fIssue{
			{node: "I_t1", number: 1, state: "open", labels: []string{"release:v1.2.0", "priority:P2"}},
			{node: "I_t2", number: 2, state: "closed", reason: "completed", labels: []string{"release:v1.0.0"}},
			{node: "I_t3", number: 3, state: "open", labels: []string{"rcapa"}, sub: [2]int{1, 3}},
			{node: "I_t4", number: 4, state: "closed", reason: "not_planned", labels: []string{"rcapa", "release:v1.10.0"}},
			{node: "I_t5", number: 5, state: "closed", reason: "completed", labels: []string{"handoff"}}, // closed handoff: rule takes open only
			{node: "I_t6", number: 6, state: "open", labels: []string{"release:v1.2.0"}, pr: true},       // a pull request
			{node: "I_t7", number: 7, state: "open", labels: []string{"handoff"}},
		}},
		{name: "ARA", issues: []*fIssue{
			{node: "I_a1", number: 11, state: "open", labels: []string{"release:v0.2.0"}},
		}},
		{name: "secret-lab", private: true, issues: []*fIssue{
			{node: "I_s1", number: 1, state: "open", labels: []string{"rcapa", "release:v9.9.9"}},
		}},
	}}
}

func run(t *testing.T, f *fake, d *Definition, dry bool) (Result, string) {
	t.Helper()
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	res, err := Run(GitHub{API: srv.URL, Token: "tok-secret", Client: srv.Client()}, d, dry, &out)
	if err != nil {
		t.Fatalf("run: %v\n%s", err, out.String())
	}
	if strings.Contains(out.String(), "tok-secret") {
		t.Fatal("token printed")
	}
	return res, out.String()
}

// values renders the fake project as "repo#n field=value ..." lines, sorted.
func (f *fake) render() string {
	var lines []string
	for _, it := range f.items {
		var kv []string
		for _, fl := range f.fields {
			v, ok := it.values[fl.id]
			if !ok {
				continue
			}
			if fl.typ == "SINGLE_SELECT" {
				for _, o := range fl.options {
					if o.id == v {
						v = o.name
					}
				}
			}
			kv = append(kv, fl.name+"="+v)
		}
		lines = append(lines, fmt.Sprintf("%s#%d %s", it.repo, it.number, strings.Join(kv, " ")))
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

// ---- tests ----

func TestValidate(t *testing.T) {
	good := defn(t)
	cases := map[string]func(d *Definition){
		"public must be true":                     func(d *Definition) { d.Public = false },
		"exactly one of label and label_prefix":   func(d *Definition) { d.Add[0].Label = "x" },
		"needs the option":                        func(d *Definition) { d.Fields[0].Options = d.Fields[0].Options[:3] },
		"from label_prefix needs":                 func(d *Definition) { d.Fields[1].Options = []Option{{Name: "a", Color: "RED"}} },
		"colour":                                  func(d *Definition) { d.Fields[2].Options[0].Color = "TEAL" },
		"layout":                                  func(d *Definition) { d.Views[0].Layout = "gantt" },
		"vertical_group_by is for a board":        func(d *Definition) { d.Views[0].VerticalGroupBy = "Status" },
		"defined twice":                           func(d *Definition) { d.Fields[3].Name = "status" },
		"is not a repository name":                func(d *Definition) { d.Repositories = []string{"a/b"} },
		"sort_by entries":                         func(d *Definition) { d.Views[0].SortBy = [][]string{{"Repository"}} },
		"is not status, label_prefix, labels or ": func(d *Definition) { d.Fields[3].From = "milestone" },
	}
	for want, mut := range cases {
		b, _ := json.Marshal(good)
		var d Definition
		_ = json.Unmarshal(b, &d)
		mut(&d)
		if err := d.Validate(); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: got %v", want, err)
		}
	}
	if _, err := Parse([]byte(`{"title":"x","public":true,"surprise":1}`)); err == nil || !strings.Contains(err.Error(), "surprise") {
		t.Errorf("unknown key: %v", err)
	}
}

// The committed definition is valid. The image's build context has no
// templates/, so the test skips there; CI's candidate test runs --validate.
func TestCommittedDefinition(t *testing.T) {
	path := "../../templates/projects/plan.json"
	if _, err := os.Stat(path); err != nil {
		t.Skip("no templates/ here (the image's build context)")
	}
	d, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if !d.Public || len(d.Views) == 0 {
		t.Fatal("the committed project is public and has views")
	}
}

func TestDerive(t *testing.T) {
	d := defn(t)
	st, rel, tr, sub := d.Fields[0], d.Fields[1], d.Fields[2], d.Fields[3]
	dropped, done := "not_planned", "completed"
	mk := func(state string, reason *string, sub [2]int, labels ...string) Issue {
		i := Issue{State: state, StateReason: reason, SubIssues: &struct {
			Total     int `json:"total"`
			Completed int `json:"completed"`
		}{sub[1], sub[0]}}
		for _, l := range labels {
			i.Labels = append(i.Labels, struct {
				Name string `json:"name"`
			}{l})
		}
		return i
	}
	for _, c := range []struct {
		i    Issue
		want [4]string
	}{
		{mk("open", nil, [2]int{0, 2}, "release:v1.2.0", "release:v1.10.0"), [4]string{"Open", "v1.10.0", "Release", "0/2"}},
		{mk("open", nil, [2]int{1, 2}, "rcapa", "release:v0.1.0"), [4]string{"In progress", "v0.1.0", "RCAPA", "1/2"}},
		{mk("closed", &done, [2]int{}, "rcapa"), [4]string{"Done", "", "RCAPA", ""}},
		{mk("closed", nil, [2]int{}), [4]string{"Done", "", "", ""}},
		{mk("closed", &dropped, [2]int{}, "release:"), [4]string{"Dropped", "", "", ""}},
	} {
		got := [4]string{st.Value(c.i), rel.Value(c.i), tr.Value(c.i), sub.Value(c.i)}
		if got != c.want {
			t.Errorf("got %q, want %q", got, c.want)
		}
	}
	v := []string{"v1.10.0", "next", "v1.2.0", "v0.9.1", "v1.2"}
	SortVersions(v)
	if strings.Join(v, " ") != "v0.9.1 v1.2.0 v1.10.0 next v1.2" {
		t.Errorf("SortVersions: %v", v)
	}
}

const wantRendered = `ARA#11 Status=Open Release=v0.2.0 Track=Release
ns3-tools#1 Status=Open Release=v1.2.0 Track=Release
ns3-tools#2 Status=Done Release=v1.0.0 Track=Release
ns3-tools#3 Status=In progress Track=RCAPA Sub-issues=1/3
ns3-tools#4 Status=Dropped Release=v1.10.0 Track=RCAPA
ns3-tools#7 Status=Open`

// From no project to the generated one, then a second run that writes nothing.
func TestCreateAndConverge(t *testing.T) {
	f := newFake()
	d := defn(t) // every public repository
	res, out := run(t, f, d, false)
	if f.projNum == 0 || !f.public || f.desc != "generated" || f.readme != "read only" {
		t.Fatalf("project not created public with its description:\n%s", out)
	}
	if got := f.render(); got != wantRendered {
		t.Fatalf("project:\n%s\nwant:\n%s\n%s", got, wantRendered, out)
	}
	if res.Wanted != 6 || res.Added != 6 || res.Removed != 0 || res.Views != 2 {
		t.Fatalf("result %+v\n%s", res, out)
	}
	// the Status built-in's options replaced by the definition's
	for _, fl := range f.fields {
		if fl.name == "Status" && (len(fl.options) != 4 || fl.options[1].name != "In progress") {
			t.Fatalf("Status options: %+v", fl.options)
		}
		if fl.name == "Release" && (len(fl.options) != 4 || fl.options[3].name != "v1.10.0") {
			t.Fatalf("Release options in version order: %+v", fl.options)
		}
	}
	// views: REST, with the fields' database ids
	if len(f.viewPosts) != 2 {
		t.Fatalf("views: %v", f.viewPosts)
	}
	rel := f.viewPosts[0]
	var relID, repoID, statusID int
	for _, fl := range f.fields {
		switch fl.name {
		case "Release":
			relID = fl.dbID
		case "Repository":
			repoID = fl.dbID
		case "Status":
			statusID = fl.dbID
		}
	}
	if fmt.Sprint(rel["group_by"]) != fmt.Sprintf("[%d]", relID) || fmt.Sprint(rel["sort_by"]) != fmt.Sprintf("[[%d asc]]", repoID) || rel["filter"] != "has:release" {
		t.Fatalf("Releases view: %v", rel)
	}
	if fmt.Sprint(f.viewPosts[1]["vertical_group_by"]) != fmt.Sprintf("[%d]", statusID) || f.viewPosts[1]["layout"] != "board" {
		t.Fatalf("RCAPA view: %v", f.viewPosts[1])
	}
	for _, a := range f.auth {
		if a != "Bearer tok-secret" {
			t.Fatalf("auth header %q", a)
		}
	}
	// converged: nothing to write
	f.writes = nil
	res, out = run(t, f, d, false)
	if len(f.writes) != 0 || res.Added+res.Updated+res.Removed+res.Views != 0 {
		t.Fatalf("second run wrote %v\n%s", f.writes, out)
	}
	if !strings.Contains(out, `"Swarm routing plan": 6 items wanted; add 0, set 0 values, remove 0, create 0 views; 0 private repositories refused`) {
		t.Fatalf("summary:\n%s", out)
	}
}

// Hand edits are overwritten: a value changed, a draft, a pull request and
// another org's issue added by hand, a label removed from an issue.
func TestHandEditsOverwritten(t *testing.T) {
	f := newFake()
	d := defn(t)
	run(t, f, d, false)
	var status, rel *fField
	for _, fl := range f.fields {
		switch fl.name {
		case "Status":
			status = fl
		case "Release":
			rel = fl
		}
	}
	for _, it := range f.items {
		if it.number == 1 {
			it.values[status.id] = status.options[2].id // Done, by hand
			delete(it.values, rel.id)                   // Release cleared by hand
		}
	}
	f.items = append(f.items,
		&fItem{id: "PVTI_draft", typ: "DRAFT_ISSUE", values: map[string]string{}},
		&fItem{id: "PVTI_pr", typ: "PULL_REQUEST", content: "PR_x", repo: "ns3-tools", owner: "swarm-routing", number: 6, values: map[string]string{}},
		&fItem{id: "PVTI_other", typ: "ISSUE", content: "I_other", repo: "elsewhere", owner: "someone", number: 3, values: map[string]string{}},
	)
	f.repo("ARA").issues[0].labels = []string{"enhancement"} // the release label removed
	f.repo("ns3-tools").issues[0].labels = append(f.repo("ns3-tools").issues[0].labels, "release:v1.3.0")
	res, out := run(t, f, d, false)
	want := strings.Replace(strings.Replace(wantRendered, "ARA#11 Status=Open Release=v0.2.0 Track=Release\n", "", 1),
		"ns3-tools#1 Status=Open Release=v1.2.0", "ns3-tools#1 Status=Open Release=v1.3.0", 1)
	if got := f.render(); got != want {
		t.Fatalf("project:\n%s\nwant:\n%s\n%s", got, want, out)
	}
	for _, line := range []string{
		"field Release: set options [v0.2.0, v1.0.0, v1.2.0, v1.10.0] -> [v1.0.0, v1.3.0, v1.10.0]",
		`ns3-tools#1: Status "Done" -> "Open"`,
		"ARA#11: remove (no add rule takes it)",
		"item PVTI_draft: remove (not an org issue (added by hand))",
		"ns3-tools#6: remove (not an org issue (added by hand))",
		"private repository 1#3: remove (not an org issue (added by hand))",
	} {
		if !strings.Contains(out, line) {
			t.Errorf("missing %q in:\n%s", line, out)
		}
	}
	if res.Removed != 4 || strings.Contains(out, "elsewhere") || strings.Contains(out, "someone") {
		t.Fatalf("result %+v\n%s", res, out)
	}
}

// A private repository's issue is never added, and is removed when found;
// its name is never printed.
func TestPrivateNeverAdded(t *testing.T) {
	f := newFake()
	d := defn(t, "ARA", "secret-lab", "ns3-tools") // the definition names it: refused
	res, out := run(t, f, d, false)
	if res.Refused != 1 || !strings.Contains(out, "private repository 1: refused: a private repository is never added to the public project") {
		t.Fatalf("not refused: %+v\n%s", res, out)
	}
	for _, it := range f.items {
		if it.private || it.content == "I_s1" {
			t.Fatal("a private repository's issue was added")
		}
	}
	for _, fl := range f.fields {
		for _, o := range fl.options {
			if o.name == "v9.9.9" {
				t.Fatal("a private repository's release became an option")
			}
		}
	}
	// one is found in the project (added by hand): removed, unnamed
	f.items = append(f.items, &fItem{id: "PVTI_s", typ: "ISSUE", content: "I_s1", repo: "secret-lab", owner: "swarm-routing",
		private: true, number: 1, values: map[string]string{}})
	res, out = run(t, f, d, false)
	if res.Removed != 1 || !strings.Contains(out, "private repository 1#1: remove (a private repository's issue)") {
		t.Fatalf("not removed: %+v\n%s", res, out)
	}
	for _, it := range f.items {
		if it.private {
			t.Fatal("still in the project")
		}
	}
	if strings.Contains(out, "secret-lab") {
		t.Fatalf("a private repository named:\n%s", out)
	}
	// the org listing asks for public repositories only
	f2 := newFake()
	_, out = run(t, f2, defn(t), true)
	if strings.Contains(out, "secret-lab") || strings.Contains(out, "private repository") {
		t.Fatalf("listing:\n%s", out)
	}
}

// A dry run only reads, and prints the diff.
func TestDryRun(t *testing.T) {
	f := newFake()
	res, out := run(t, f, defn(t), true)
	if len(f.writes) != 0 || f.projNum != 0 || len(f.viewPosts) != 0 {
		t.Fatalf("dry run wrote %v", f.writes)
	}
	for _, line := range []string{
		`project "Swarm routing plan": would create (public)`,
		"field Release: would create (single_select: v0.2.0, v1.0.0, v1.2.0, v1.10.0)",
		"ns3-tools#3: would add",
		`ns3-tools#3: Sub-issues "" -> "1/3"`,
		"view RCAPA: would create (board)",
		`"Swarm routing plan": 6 items wanted; would add 6, would set 16 values, would remove 0, would create 2 views`,
	} {
		if !strings.Contains(out, line) {
			t.Errorf("missing %q in:\n%s", line, out)
		}
	}
	if res.Added != 6 {
		t.Fatalf("%+v", res)
	}
	// a dry run on an existing project, with a view whose layout changed by hand
	run(t, f, defn(t), false)
	f.views[1].layout = "BOARD_LAYOUT" // Releases is a table in the definition
	f.writes = nil
	_, out = run(t, f, defn(t), true)
	if len(f.writes) != 0 || !strings.Contains(out, "view Releases: is BOARD_LAYOUT, the definition says TABLE_LAYOUT: the API cannot change a view") {
		t.Fatalf("view note missing or writes %v:\n%s", f.writes, out)
	}
}

// The write budget bounds a run; the next run finishes.
func TestWriteBudget(t *testing.T) {
	f := newFake()
	r := f.repo("ARA")
	for n := 100; n < 100+MaxWrites; n++ {
		r.issues = append(r.issues, &fIssue{node: fmt.Sprintf("I_b%d", n), number: n, state: "open", labels: []string{"rcapa"}})
	}
	d := defn(t)
	res, out := run(t, f, d, false)
	if !res.Deferred || len(f.writes) != MaxWrites || !strings.Contains(out, "write budget spent") {
		t.Fatalf("budget: %d writes, %+v", len(f.writes), res)
	}
	for i := 0; i < 5; i++ {
		f.writes = nil
		res, _ = run(t, f, d, false)
		if !res.Deferred {
			break
		}
	}
	f.writes = nil
	if res, _ = run(t, f, d, false); res.Deferred || len(f.writes) != 0 || len(f.items) != 6+MaxWrites {
		t.Fatalf("not converged: %+v %d items", res, len(f.items))
	}
}

// A token without the Projects permission: the error says so, and never
// prints the token.
func TestRefused(t *testing.T) {
	f := newFake()
	f.refuse = "Resource not accessible by integration (tok-secret)"
	srv := httptest.NewServer(f)
	defer srv.Close()
	var out bytes.Buffer
	_, err := Run(GitHub{API: srv.URL, Token: "tok-secret", Client: srv.Client()}, defn(t), false, &out)
	if err == nil || !strings.Contains(err.Error(), "organization Projects permission") || strings.Contains(err.Error(), "tok-secret") {
		t.Fatalf("err %v", err)
	}
}

func TestMain_(t *testing.T) {
	f := newFake()
	srv := httptest.NewServer(f)
	defer srv.Close()
	dir := t.TempDir()
	path := dir + "/plan.json"
	b, _ := json.Marshal(defn(t))
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	call := func(env map[string]string, args ...string) (int, string, string) {
		var o, e bytes.Buffer
		code := Main(args, func(k string) string { return env[k] }, srv.Client(), srv.URL, &o, &e)
		return code, o.String(), e.String()
	}
	if code, o, _ := call(nil, "--validate", "--definition", path); code != 0 || !strings.Contains(o, "valid (3 add rules, 4 fields, 2 views)") {
		t.Fatalf("validate: %d %s", code, o)
	}
	code, o, _ := call(nil, "--definition", path)
	if code != 0 || !strings.Contains(o, "no GH_TOKEN") || !strings.Contains(o, `ns3-tools#3: Status="In progress" Release="" Track="RCAPA" Sub-issues="1/3"`) ||
		!strings.Contains(o, "6 items wanted") || len(f.writes) != 0 {
		t.Fatalf("no token: %d\n%s", code, o)
	}
	if code, _, e := call(nil, "--bogus"); code != 2 || !strings.Contains(e, "usage") {
		t.Fatalf("usage: %d %s", code, e)
	}
	if code, _, e := call(nil, "--definition", dir+"/missing.json"); code != 1 || !strings.Contains(e, "missing.json") {
		t.Fatalf("missing: %d %s", code, e)
	}
	// Main's real sync paces its writes; the test's fake has no limits, so the
	// sync itself is covered by Run above, and here a dry run with a token
	if code, o, _ := call(map[string]string{"GH_TOKEN": "t"}, "--dry-run", "--definition", path); code != 0 || !strings.Contains(o, "would create (public)") {
		t.Fatalf("dry run: %d\n%s", code, o)
	}
}
