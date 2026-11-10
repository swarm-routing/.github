# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
# `make dist` for the release self-test: two assets, the second a deterministic
# tarball (sorted, fixed owner and mtime, gzip -n), as a module tarball would be.

dist:
	mkdir -p dist
	printf 'fixture %s\n' "$(RELEASE_VERSION)" > dist/fixture-$(RELEASE_VERSION).txt
	tar --sort=name --owner=0 --group=0 --numeric-owner --mtime=@0 -cf - VERSION .cz.toml | gzip -n > dist/fixture-$(RELEASE_VERSION).tar.gz

.PHONY: dist
