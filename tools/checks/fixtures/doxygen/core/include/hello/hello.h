// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only
#pragma once

namespace hello
{

/// A greeter: the fixture class doxygen-selftest.yml expects a page for.
class Greeter
{
  public:
    /// The greeting for `name`.
    /// @param name who is greeted
    /// @return "hello, " followed by the name
    const char* Greet(const char* name) const;

    int Undocumented() const; // the fixture's one warning
};

} // namespace hello
