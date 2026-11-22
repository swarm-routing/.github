// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

package citoolsdigest

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
)

// Registry reads the ci-tools image's manifests and configs from GHCR,
// anonymously (the package is public): an image's digest is never typed, and
// the commit an image was built from is its `org.opencontainers.image.revision`
// label, which ci-tools-image.yml sets at the build.
type Registry struct {
	Base   string // https://ghcr.io (no trailing slash)
	Client *http.Client
	token  string
}

// RevisionLabel is the label naming the commit an image was built from.
const RevisionLabel = "org.opencontainers.image.revision"

// maxManifest bounds the bytes read from one registry answer.
const maxManifest = 4 << 20

var (
	digestRe = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	revRe    = regexp.MustCompile(`^[0-9a-f]{40}$`)
)

var manifestTypes = strings.Join([]string{
	"application/vnd.oci.image.manifest.v1+json",
	"application/vnd.docker.distribution.manifest.v2+json",
	"application/vnd.oci.image.index.v1+json",
	"application/vnd.docker.distribution.manifest.list.v2+json",
}, ", ")

func (r *Registry) get(path, accept string) ([]byte, error) {
	if r.token == "" {
		data, err := r.send(fmt.Sprintf("/token?service=ghcr.io&scope=repository:%s:pull", repoPath), "", "")
		if err != nil {
			return nil, err
		}
		var t struct {
			Token string `json:"token"`
		}
		if err := json.Unmarshal(data, &t); err != nil || t.Token == "" {
			return nil, fmt.Errorf("registry token: no token in the answer")
		}
		r.token = t.Token
	}
	return r.send(path, accept, r.token)
}

func (r *Registry) send(path, accept, token string) ([]byte, error) {
	req, err := http.NewRequest("GET", r.Base+path, nil)
	if err != nil {
		return nil, err
	}
	if accept != "" {
		req.Header.Set("Accept", accept)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := r.Client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("GET %s: %v", path, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxManifest))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GET %s: HTTP %d", path, resp.StatusCode)
	}
	return data, nil
}

// content checks that data is the object digest names (content addressing:
// what was asked for is what was read).
func content(data []byte, digest string) error {
	sum := sha256.Sum256(data)
	if got := "sha256:" + hex.EncodeToString(sum[:]); got != digest {
		return fmt.Errorf("registry answered %s for %s", got, digest)
	}
	return nil
}

// Revision is the commit the image digest names was built from: its
// manifest (for an index, its linux/amd64 image), its config, the revision
// label. Any doubt is an error, never a guess.
func (r *Registry) Revision(digest string) (string, error) {
	return r.revision(digest, 0)
}

func (r *Registry) revision(digest string, depth int) (string, error) {
	if !digestRe.MatchString(digest) {
		return "", fmt.Errorf("%q is not a sha256 digest", digest)
	}
	data, err := r.get("/v2/"+repoPath+"/manifests/"+digest, manifestTypes)
	if err != nil {
		return "", err
	}
	if err := content(data, digest); err != nil {
		return "", err
	}
	var m struct {
		Config struct {
			Digest string `json:"digest"`
		} `json:"config"`
		Manifests []struct {
			Digest   string `json:"digest"`
			Platform struct {
				OS           string `json:"os"`
				Architecture string `json:"architecture"`
			} `json:"platform"`
		} `json:"manifests"`
	}
	if err := json.Unmarshal(data, &m); err != nil {
		return "", fmt.Errorf("manifest %s: %v", digest, err)
	}
	if len(m.Manifests) > 0 {
		if depth > 0 {
			return "", fmt.Errorf("manifest %s: an index inside an index", digest)
		}
		for _, e := range m.Manifests {
			if e.Platform.OS == "linux" && e.Platform.Architecture == "amd64" {
				return r.revision(e.Digest, depth+1)
			}
		}
		return "", fmt.Errorf("index %s: no linux/amd64 image", digest)
	}
	if !digestRe.MatchString(m.Config.Digest) {
		return "", fmt.Errorf("manifest %s: no config digest", digest)
	}
	data, err = r.get("/v2/"+repoPath+"/blobs/"+m.Config.Digest, "")
	if err != nil {
		return "", err
	}
	if err := content(data, m.Config.Digest); err != nil {
		return "", err
	}
	var c struct {
		Config struct {
			Labels map[string]string `json:"Labels"`
		} `json:"config"`
	}
	if err := json.Unmarshal(data, &c); err != nil {
		return "", fmt.Errorf("config of %s: %v", digest, err)
	}
	rev := c.Config.Labels[RevisionLabel]
	if !revRe.MatchString(rev) {
		return "", fmt.Errorf("image %s: no %s label naming a commit", digest, RevisionLabel)
	}
	return rev, nil
}
