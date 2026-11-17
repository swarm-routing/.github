// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package projectsync

import (
	"fmt"
	"strings"
)

// The GraphQL documents: Projects v2's project, fields, items and their
// values are GraphQL-only (REST reads items and adds fields and views, but
// cannot create or update a project, update a field's options, or list
// views), so the project side is GraphQL throughout, under the exception
// recorded in docs/adr/0002-pipelines-are-go.md (swarm-routing/.github#541).
// Each document's operation name is what the test's fake API dispatches on.
const (
	qFindProject = `query FindProject($org:String!,$q:String!){organization(login:$org){id projectsV2(first:50,query:$q){nodes{id number title}}}}`

	qReadProject = `query ReadProject($org:String!,$number:Int!){organization(login:$org){projectV2(number:$number){` +
		`id number title public shortDescription readme ` +
		`fields(first:50){nodes{__typename ... on ProjectV2FieldCommon{id databaseId name dataType} ... on ProjectV2SingleSelectField{options{id name color description}}}} ` +
		`views(first:50){nodes{name layout}}}}}`

	qReadItems = `query ReadItems($org:String!,$number:Int!,$after:String){organization(login:$org){projectV2(number:$number){` +
		`items(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{id type ` +
		`content{__typename ... on Issue{id number repository{name isPrivate owner{login}}} ... on PullRequest{id number repository{name isPrivate owner{login}}}} ` +
		`fieldValues(first:50){nodes{__typename ` +
		`... on ProjectV2ItemFieldTextValue{text field{... on ProjectV2FieldCommon{name}}} ` +
		`... on ProjectV2ItemFieldSingleSelectValue{name field{... on ProjectV2FieldCommon{name}}}}}}}}}}`

	mCreateProject = `mutation CreateProject($owner:ID!,$title:String!){createProjectV2(input:{ownerId:$owner,title:$title}){projectV2{id number}}}`

	mUpdateProject = `mutation UpdateProject($p:ID!,$title:String!,$desc:String!,$readme:String!){` +
		`updateProjectV2(input:{projectId:$p,title:$title,shortDescription:$desc,readme:$readme}){projectV2{id}}}`

	// the visibility on its own: an App's installation token may be refused
	// it (the org's policy on who changes a project's visibility), and the
	// rest of the sync must not wait on it
	mSetPublic = `mutation SetPublic($p:ID!,$public:Boolean!){updateProjectV2(input:{projectId:$p,public:$public}){projectV2{id}}}`

	mCreateField = `mutation CreateField($p:ID!,$name:String!,$type:ProjectV2CustomFieldType!,$options:[ProjectV2SingleSelectFieldOptionInput!]){` +
		`createProjectV2Field(input:{projectId:$p,name:$name,dataType:$type,singleSelectOptions:$options}){projectV2Field{... on ProjectV2FieldCommon{id}}}}`

	mUpdateField = `mutation UpdateField($f:ID!,$options:[ProjectV2SingleSelectFieldOptionInput!]){` +
		`updateProjectV2Field(input:{fieldId:$f,singleSelectOptions:$options}){projectV2Field{... on ProjectV2FieldCommon{id}}}}`

	mAddItem = `mutation AddItem($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}`

	mDeleteItem = `mutation DeleteItem($p:ID!,$i:ID!){deleteProjectV2Item(input:{projectId:$p,itemId:$i}){deletedItemId}}`
)

// PField is a project field.
type PField struct {
	ID         string    `json:"id"`
	DatabaseID int       `json:"databaseId"`
	Name       string    `json:"name"`
	DataType   string    `json:"dataType"`
	Options    []POption `json:"options"`
}

// POption is a single-select option as the project holds it.
type POption struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Color       string `json:"color"`
	Description string `json:"description"`
}

// PItem is a project item.
type PItem struct {
	ID      string
	Type    string // ISSUE, PULL_REQUEST, DRAFT_ISSUE, REDACTED
	IssueID string // the content's node id, for an issue
	Repo    string
	Owner   string
	Private bool
	Number  int
	Values  map[string]string // field name -> text or option name
}

// Project is what the sync reads of the project.
type Project struct {
	ID               string
	Number           int
	Title            string
	Public           bool
	ShortDescription string
	Readme           string
	Fields           []PField
	Views            []struct{ Name, Layout string }
	Items            []PItem
}

// Field finds a field by name, case-insensitively.
func (p *Project) Field(name string) *PField {
	for i := range p.Fields {
		if strings.EqualFold(p.Fields[i].Name, name) {
			return &p.Fields[i]
		}
	}
	return nil
}

// FindProject returns the org's node id and the number of the project titled
// title (0 when there is none).
func (g GitHub) FindProject(org, title string) (string, int, error) {
	var r struct {
		Organization *struct {
			ID         string `json:"id"`
			ProjectsV2 struct {
				Nodes []struct {
					Number int    `json:"number"`
					Title  string `json:"title"`
				} `json:"nodes"`
			} `json:"projectsV2"`
		} `json:"organization"`
	}
	if err := g.GraphQL(qFindProject, map[string]any{"org": org, "q": title}, &r); err != nil {
		return "", 0, err
	}
	if r.Organization == nil {
		return "", 0, fmt.Errorf("organization %s not readable", org)
	}
	for _, n := range r.Organization.ProjectsV2.Nodes {
		if n.Title == title {
			return r.Organization.ID, n.Number, nil
		}
	}
	return r.Organization.ID, 0, nil
}

// ReadProject reads a project, its fields, views and every item.
func (g GitHub) ReadProject(org string, number int) (*Project, error) {
	var r struct {
		Organization struct {
			ProjectV2 *struct {
				ID               string `json:"id"`
				Number           int    `json:"number"`
				Title            string `json:"title"`
				Public           bool   `json:"public"`
				ShortDescription string `json:"shortDescription"`
				Readme           string `json:"readme"`
				Fields           struct {
					Nodes []PField `json:"nodes"`
				} `json:"fields"`
				Views struct {
					Nodes []struct {
						Name   string `json:"name"`
						Layout string `json:"layout"`
					} `json:"nodes"`
				} `json:"views"`
			} `json:"projectV2"`
		} `json:"organization"`
	}
	if err := g.GraphQL(qReadProject, map[string]any{"org": org, "number": number}, &r); err != nil {
		return nil, err
	}
	pv := r.Organization.ProjectV2
	if pv == nil {
		return nil, fmt.Errorf("project %d not readable", number)
	}
	p := &Project{ID: pv.ID, Number: pv.Number, Title: pv.Title, Public: pv.Public,
		ShortDescription: pv.ShortDescription, Readme: pv.Readme, Fields: pv.Fields.Nodes}
	for _, v := range pv.Views.Nodes {
		p.Views = append(p.Views, struct{ Name, Layout string }{v.Name, v.Layout})
	}
	after := any(nil)
	for page := 0; ; page++ {
		if page >= maxPages {
			return nil, fmt.Errorf("project %d: more than %d pages of items", number, maxPages)
		}
		var ir struct {
			Organization struct {
				ProjectV2 struct {
					Items struct {
						PageInfo struct {
							HasNextPage bool   `json:"hasNextPage"`
							EndCursor   string `json:"endCursor"`
						} `json:"pageInfo"`
						Nodes []struct {
							ID      string `json:"id"`
							Type    string `json:"type"`
							Content *struct {
								ID         string `json:"id"`
								Number     int    `json:"number"`
								Repository *struct {
									Name      string `json:"name"`
									IsPrivate bool   `json:"isPrivate"`
									Owner     struct {
										Login string `json:"login"`
									} `json:"owner"`
								} `json:"repository"`
							} `json:"content"`
							FieldValues struct {
								Nodes []struct {
									Text  *string `json:"text"`
									Name  *string `json:"name"`
									Field *struct {
										Name string `json:"name"`
									} `json:"field"`
								} `json:"nodes"`
							} `json:"fieldValues"`
						} `json:"nodes"`
					} `json:"items"`
				} `json:"projectV2"`
			} `json:"organization"`
		}
		if err := g.GraphQL(qReadItems, map[string]any{"org": org, "number": number, "after": after}, &ir); err != nil {
			return nil, err
		}
		its := ir.Organization.ProjectV2.Items
		for _, n := range its.Nodes {
			it := PItem{ID: n.ID, Type: n.Type, Values: map[string]string{}}
			if n.Content != nil && n.Content.Repository != nil {
				it.Number = n.Content.Number
				it.Repo = n.Content.Repository.Name
				it.Owner = n.Content.Repository.Owner.Login
				it.Private = n.Content.Repository.IsPrivate
				if n.Type == "ISSUE" {
					it.IssueID = n.Content.ID
				}
			}
			for _, v := range n.FieldValues.Nodes {
				if v.Field == nil {
					continue
				}
				switch {
				case v.Text != nil:
					it.Values[strings.ToLower(v.Field.Name)] = *v.Text
				case v.Name != nil:
					it.Values[strings.ToLower(v.Field.Name)] = *v.Name
				}
			}
			p.Items = append(p.Items, it)
		}
		if !its.PageInfo.HasNextPage {
			break
		}
		after = its.PageInfo.EndCursor
	}
	return p, nil
}

func optionInput(o []Option) []map[string]string {
	out := make([]map[string]string, 0, len(o))
	for _, x := range o {
		out = append(out, map[string]string{"name": x.Name, "color": x.Color, "description": x.Description})
	}
	return out
}

// setItemDoc is one mutation that sets or clears several fields of one item
// (one request per item, under the secondary rate limits).
func setItemDoc(n int, kinds []string) string {
	var head, body strings.Builder
	head.WriteString("mutation SetItem($p:ID!,$i:ID!")
	for k := 0; k < n; k++ {
		fmt.Fprintf(&head, ",$f%d:ID!", k)
		switch kinds[k] {
		case "text", "singleSelectOptionId":
			fmt.Fprintf(&head, ",$v%d:String!", k)
			fmt.Fprintf(&body, " u%d: updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f%d,value:{%s:$v%d}}){clientMutationId}", k, k, kinds[k], k)
		default:
			fmt.Fprintf(&body, " c%d: clearProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f%d}){clientMutationId}", k, k)
		}
	}
	return head.String() + "){" + body.String() + "}"
}
