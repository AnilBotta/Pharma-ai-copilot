#!/usr/bin/env julia
#
# ReplicateBE.jl, pinned, as an ORACLE ONLY.
#
# Julia exists in this image for one reason: no R package computes
# Satterthwaite denominator degrees of freedom for FDA Appendix C's covariance
# structure, and ReplicateBE.jl claims to. That claim is the last open question
# in VAL-FDA-APPENDIX-C-001 and it has to be tested, not quoted.
#
# `be_stats` does not depend on Julia, must never depend on Julia, and nothing
# here is copied into it. ReplicateBE.jl is GPL-3.0: running it and comparing
# numbers creates no derivative work, and copying its implementation would be a
# different question that is not being asked.
#
# PINNED, and the resolved manifest is recorded. An unpinned oracle is not an
# oracle - the same rule install_r_packages.R applies to PowerTOST.

using Pkg

# 1.0.15, NOT the 1.0.10 the documentation site happens to serve.
#
# 1.0.10's compat is `DataFrames = "0.19, 0.20"`, and DataFrames 0.20 does not
# resolve on Julia 1.10 - SortingAlgorithms drags the requirement to
# DataFrames >= 1.0 and the two are unsatisfiable. The first build failed
# exactly there. 1.0.15 declares `DataFrames = "1"` and `julia = "1"`.
#
# Worth being explicit about what this pin is and is not: it is a pin to the
# newest release, chosen because the older one cannot run, not a pin to
# whatever resolves today. The resolved manifest is recorded either way.
const WANTED = "1.0.15"

Pkg.add(Pkg.PackageSpec(name = "ReplicateBE", version = WANTED))
Pkg.add(Pkg.PackageSpec(name = "JSON"))
# DataFrames deliberately UNPINNED: ReplicateBE's own compat bound should pick
# it, and pinning it separately is how the first build produced an
# unsatisfiable graph rather than a clear error.
Pkg.add("DataFrames")

# Precompile here rather than on first use, so the investigation step measures
# the fit and not the compiler.
Pkg.precompile()

using ReplicateBE

resolved = Dict{String,String}()
for (uuid, dep) in Pkg.dependencies()
    if dep.is_direct_dep
        resolved[dep.name] = string(dep.version)
    end
end

println("Julia environment as resolved:")
println("  julia        ", VERSION)
for name in sort(collect(keys(resolved)))
    println("  ", rpad(name, 12), resolved[name])
end

got = resolved["ReplicateBE"]
if got != WANTED
    error("""
        ReplicateBE $got is installed but this file pins $WANTED.
        An unpinned oracle is not an oracle: fix the pin or update it
        deliberately.
        """)
end

open("/opt/julia_manifest.json", "w") do io
    write(io, "{\"julia\": \"$(VERSION)\", " *
              join(["\"$k\": \"$v\"" for (k, v) in resolved], ", ") * "}")
end
println("\nmanifest written")
