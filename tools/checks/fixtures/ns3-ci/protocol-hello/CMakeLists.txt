# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: GPL-2.0-only
#
# ns3-ci-selftest.yml fixture (a copy of swarm-routing/sim-containers'
# test/fixtures/protocol-hello): the smallest protocol module, a
# library on swarm-core and routing-bench, as every swarm-routing protocol
# links them, with a test suite. Built on ns3-protocol-dev it must compile
# only itself: both dependencies are prebuilt in the image.
build_lib(
  LIBNAME protocol-hello
  SOURCE_FILES model/protocol-hello.cc
  HEADER_FILES model/protocol-hello.h
  LIBRARIES_TO_LINK ${libswarm-core} ${librouting-bench}
  TEST_SOURCES test/protocol-hello-test-suite.cc
)
