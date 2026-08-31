#!/usr/bin/env julia
#
# ReplicateBE.jl against the nine synthetic full-replicate cases.
#
# WHAT THIS IS FOR
#
# PR #61 established that ReplicateBE.jl reproduces EMA's published SAS Method C
# output exactly on the fully replicate design - estimate, 90% interval and both
# within-subject CVs - and is therefore usable as a tier-3 implementation oracle
# for THAT DESIGN and no other. It also left one thing unsettled: the denominator
# df differs from this package's by 0.17% on Data set I, which sits exactly on
# the correlation boundary.
#
# Data set I is one point. These nine cases put the comparison at eight more:
# balanced and unbalanced, complete and incomplete, equal and unequal residual
# variances, correlation near zero and on the boundary, and four intervals
# placed two hundredths of a percentage point either side of a limit.
#
# WHAT WOULD MAKE THE DF QUESTION ANSWERABLE
#
# The Python side shows a sharp split: interior balanced fits give a df of
# exactly n-2, and the boundary fit jumps to the within-subject scale. If
# ReplicateBE agrees on the interior cases and differs only on case E, the 0.17%
# is a boundary effect and the two parameterisations differ only in how they
# take the same limit. If it differs on the interior cases too, that is a
# different and more serious finding.
#
# Note that ReplicateBE parameterises the correlation through a link
# (`rholink = :psigmoid`), which sends its parameter to infinity at rho = 1.
# Case E may therefore fail to converge. That is a result, not a failure of this
# script - it is recorded as NOT_CONVERGED and the Python comparison treats it
# as unresolved rather than as agreement.
#
# ORIENTATION IS ESTABLISHED ONCE, GLOBALLY, NOT PER CASE
#
# ReplicateBE sorts the formulation levels, so its coefficient may be R - T
# rather than T - R. On Data set I that ambiguity was resolved by comparing
# against EMA's published estimate. There is no published estimate here, and
# picking the orientation that agrees with Python case by case would be
# circular - it would manufacture agreement on the sign and hide a genuinely
# inverted fit.
#
# So this script does not choose. It emits the RAW coefficient and its name for
# every case, and the Python comparison determines a single orientation that
# must hold for all nine. Nine cases agreeing on one global sign is evidence;
# nine independently chosen signs would be none.
#
# Usage:
#   julia replicatebe_cases.jl <full_replicate_cases.json> <output.json>

using DataFrames
using JSON
using ReplicateBE

const coef = ReplicateBE.coef
const stderror = ReplicateBE.stderror

function build(rows)
    DataFrame(
        subject = string.(get.(rows, "subject", nothing)),
        period = string.(get.(rows, "period", nothing)),
        formulation = string.(get.(rows, "treatment", nothing)),
        sequence = string.(get.(rows, "sequence", nothing)),
        # These are values this package generated at full double precision, so
        # taking the log here is exact rather than a re-derivation of a printed
        # column. Data set I was the opposite situation and was handled the
        # opposite way.
        logvar = [log(Float64(r["value"])) for r in rows],
    )
end

function analyse(key, case)
    rows = case["observations"]
    df = build(rows)

    println("=== case $key: $(case["name"])")
    println("    rows: $(nrow(df)), subjects: $(length(unique(df.subject)))")

    result = Dict{String,Any}(
        "case" => key,
        "name" => case["name"],
        "n_observations_supplied" => nrow(df),
        "n_subjects_supplied" => length(unique(df.subject)),
    )

    fitted = try
        ReplicateBE.rbe(
            df;
            dvar = :logvar,
            subject = :subject,
            formulation = :formulation,
            period = :period,
            sequence = :sequence,
        )
    catch e
        println("    FIT FAILED: ", sprint(showerror, e))
        result["status"] = "FIT_FAILED"
        result["error"] = sprint(showerror, e)
        return result
    end

    converged = ReplicateBE.optstat(fitted)
    result["converged"] = converged
    result["status"] = converged ? "FITTED" : "NOT_CONVERGED"
    result["reml2"] = ReplicateBE.reml2(fitted)
    result["theta"] = collect(Float64.(ReplicateBE.theta(fitted)))

    betas = coef(fitted)
    ses = stderror(fitted)
    dfs = ReplicateBE.dof(fitted)

    # Located by NAME. PR #61 rejected an earlier draft that located the
    # coefficient by proximity to the expected value, which selects the answer
    # that agrees and would hide a wrong fit behind a right-looking number.
    names = try
        String.(ReplicateBE.coefnames(fitted.model))
    catch
        try
            String.(ReplicateBE.coefnames(fitted))
        catch
            String[]
        end
    end
    result["coefficient_names"] = names

    i = findfirst(n -> occursin("formulation", lowercase(n)), names)
    if i === nothing
        i = length(betas)
        result["coefficient_located_by"] =
            "position (last fixed effect); coefnames exposed no formulation term"
    else
        result["coefficient_located_by"] = "name: $(names[i])"
    end
    result["coefficient_index"] = i

    # RAW, unoriented. The sign is the Python side's problem, once, for all
    # nine cases together.
    result["estimate_raw"] = Float64(betas[i])
    result["standard_error"] = Float64(ses[i])
    result["denominator_df"] = Float64(dfs[i])

    println("    raw estimate $(result["estimate_raw"])  se $(result["standard_error"])  df $(result["denominator_df"])")
    return result
end

function main()
    length(ARGS) == 2 || error("usage: replicatebe_cases.jl <cases.json> <output.json>")
    payload = JSON.parsefile(ARGS[1])

    results = Dict{String,Any}()
    for key in sort(collect(keys(payload["cases"])))
        results[key] = analyse(key, payload["cases"][key])
    end

    out = Dict{String,Any}(
        "schema" => "be-stats/appendix-c-replicatebe-case-oracle/1",
        "oracle" => Dict(
            "package" => "ReplicateBE.jl",
            # Pinned in the validation image. PR #61 found 1.0.10 unusable on
            # Julia 1.10 - it pins DataFrames 0.19/0.20, which is unsatisfiable.
            "version_pinned" => "1.0.15",
            "julia_version" => string(VERSION),
        ),
        "source_cases" => basename(ARGS[1]),
        "tier" => "3 (independent implementation, not a regulator's output)",
        "note" => "Raw unoriented coefficients; orientation is resolved once, globally, on the Python side.",
        "cases" => results,
    )

    open(ARGS[2], "w") do io
        JSON.print(io, out, 2)
    end
    println("\nwrote ", ARGS[2])

    bad = [k for (k, v) in results if v["status"] != "FITTED"]
    if !isempty(bad)
        println("NOT FITTED: ", join(sort(bad), ", "))
    end
    return 0
end

main()
