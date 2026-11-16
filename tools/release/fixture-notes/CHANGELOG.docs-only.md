## v0.2.1 (2026-11-16)

## v0.2.0 (2026-11-16)

### Feat

- **release**: each release opens the beeadhoc-core port pr in swarm-routing/vcpkg-registry (#146)
- **bench**: the anchor plan, generation bee-anchor-2 (#145)
- **core**: core/ installs as the cmake package beeadhoc-core, for its vcpkg port (#143)
- **core**: build core/ at C++23, the standard of the ns-3 release the org supports (#135)
- **core**: consume swarm-core by release: swarm-core.lock, URL + URL_HASH, ns-3 dependencies on tags with a canary on main (#134)
- **ns3**: the adapter carries the core's trailer, swarms and link failure (#108)
- **core**: swarms and link failure (#102)
- **core**: the data path, a versioned source-route trailer, forward and input chains, piggybacking (#96)
- **bench**: benchmark pipeline: a caller of the reusable cell and the change-test smoke plan (#95)
- **observer**: report through swarm-core's router observer (#58)
