# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# ghcr.io/swarm-routing/ci-tools: the org's Go pipeline tools
# (docs/adr/0002-pipelines-are-go.md). Build from the repository root:
#
#   docker build -f docker/ci-tools/Dockerfile -t ci-tools .
#
# Both stages are pinned by digest and kept current by Dependabot
# (.github/dependabot.yml); the golang tag is the go.mod `toolchain` version,
# which ci-tools-image.yml checks.

FROM golang:1.27.4-trixie@sha256:f18c3d73a184fb0582828510722e723b63a93f7188d11dd223d9be6f6880e65d AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOFLAGS=-buildvcs=false
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY cmd/ cmd/
COPY internal/ internal/
# The tests run on the code that is built; every cmd/<tool> becomes
# /usr/local/bin/<tool>: static, no host paths, no build id.
RUN go vet ./... \
 && go test ./... \
 && mkdir /out \
 && go build -trimpath -ldflags='-s -w -buildid=' -o /out/ ./cmd/...

# No shell, no package manager: the dispatcher runs a tool in its place.
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
LABEL org.opencontainers.image.source="https://github.com/swarm-routing/.github" \
      org.opencontainers.image.description="swarm-routing CI tools: the org's Go pipeline tools (ci-tools <tool> [args...])" \
      org.opencontainers.image.licenses="MIT OR GPL-2.0-only"
COPY --from=build /out/ /usr/local/bin/
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/ci-tools"]
