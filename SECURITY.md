# Security Policy

This is the default policy for every `swarm-routing` repository that does
not have its own `SECURITY.md`. A repository's own policy, where it has one,
takes precedence: it names that repository's trust boundary and what it ships.

## Posture

The swarm-routing repositories are **research code for network simulation**:
routing protocols as ns-3 modules, the images and tools that build and
compare them, benchmark data and a documentation site. None of it is meant
to route real traffic. This policy records that posture honestly; it
promises nothing the code does not do.

- **Routing control messages are unauthenticated** unless a repository says
  otherwise. Injection, blackhole, wormhole and replay attacks by a malicious
  node are research topics, not vulnerabilities.
- **In scope:** a malformed input that crashes, over-reads, over-allocates or
  hangs a parser the repository documents as its trust boundary; a CI
  workflow, script or published image that can be made to run code it should
  not; a published artifact that does not verify the way its repository says
  it does.

## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting: the
repository's **Security** tab, then **Report a vulnerability**. If that is
not available, open an issue that only asks for a private contact, and put
no vulnerability details in it. This is a research project maintained on a
best-effort basis: expect an acknowledgement within a few days, not an SLA.

## Verifying what is published

A repository that publishes something (an image, a release) says how to
verify it in its own `SECURITY.md`. Where a repository's policy says
nothing about verification, no verification process is documented for it
yet; ask in an issue before relying on its artifacts.
