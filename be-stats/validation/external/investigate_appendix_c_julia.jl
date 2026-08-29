#!/usr/bin/env julia
#
# Does ReplicateBE.jl reproduce SAS PROC MIXED for FDA Appendix C?
#
# THE ONE QUESTION THIS ANSWERS
#
# VAL-FDA-APPENDIX-C-001 established everything except the denominator degrees
# of freedom. nlme and glmmTMB both fit Appendix C's five-parameter structure
# and both reproduce EMA's published point estimate, and neither computes
# Satterthwaite df: nlme reports containment, glmmTMB reports none at all.
# lmerTest computes genuine Satterthwaite df for a model that is not Appendix C.
#
# ReplicateBE.jl claims to do all of it. Its source says the claim is at least
# structurally credible:
#
#   gmat(σ) = Symmetric([σ[1] cov; cov σ[2]]),  cov = sqrt(σ[1]*σ[2])*σ[3]
#       a CSH parameterisation - two variances and a correlation - which spans
#       the same positive-semidefinite cone as FDA's FA0(2), and which FDA
#       NAMES as an acceptable substitute: "TYPE=FA0(2) could possibly be
#       replaced by TYPE=CSH or UNR".
#
#   rmat(σ, Z) = Diagonal(Z*σ)
#       treatment-specific residual variances - FDA's REPEATED/GRP=TRT.
#
#   sattdf(...)  df = 2*(L'CL)^2 / (gradC' * A * gradC)
#       the Satterthwaite formula proper, with A the information matrix of the
#       variance parameters and gradC the gradient of the contrast variance
#       with respect to them. Not a label on something else.
#
# So the structure is right on paper. This script finds out whether the NUMBERS
# are right, against the only published SAS output for this model.
#
# WHAT IS COMPARED AGAINST, AND ITS ONE GAP
#
# EMA/618604/2008 Rev. 13 "Method C", attributed by EMA to the FDA guidance and
# computed in SAS 9.1. Point estimates and 90% CIs are published; the standard
# error and the denominator df are NOT.
#
# So df cannot be compared directly. It can be compared indirectly on Data set
# II, where reverse-solving the published CI for the df is well conditioned and
# gives about 19.60 - and MUST NOT be on Data set I, where the same reverse
# solve is ill conditioned and returns a value exceeding the observation count.
# That asymmetry is a property of the published rounding, not of any model, and
# this script keeps it.
#
# Nothing here is tuned toward 19.60.
#
# Usage:
#   julia investigate_appendix_c_julia.jl <datasets.json> <output.json>

using DataFrames
using JSON
using ReplicateBE

const ALPHA = 0.05          # one-sided; the 90% interval FDA's ALPHA=0.1 asks for
const LEVEL = 0.90

# Sequence coding exactly as EMA printed it. Data set I uses letters where A is
# the TEST and B the reference - the opposite reading is the obvious guess and
# would inverta every result.
const SEQUENCE_CODES = Dict(
    "ABAB" => "TRTR", "BABA" => "RTRT",
    "1" => "TRR", "2" => "RTR", "3" => "RRT",
)

const PUBLISHED = Dict(
    "data_set_i" => Dict(
        "estimate_percent" => 115.66,
        "ci" => (107.10, 124.89),
        "cv_wr_percent" => 47.3,
        "cv_wt_percent" => 35.3,
        "design" => "4-period fully replicate, 77 subjects, 8 incomplete",
        "df_recoverable" => false,   # ill conditioned; see the module docstring
    ),
    "data_set_ii" => Dict(
        "estimate_percent" => 102.26,
        "ci" => (97.05, 107.76),
        "cv_wr_percent" => 11.5,
        "cv_wt_percent" => nothing,
        "design" => "3-period partial replicate, 24 subjects, balanced",
        "df_recoverable" => true,
        "df_recovered_from_published_ci" => 19.603,
    ),
)

function build(rows)
    DataFrame(
        subject = string.(get.(rows, "subject", nothing)),
        period = string.(get.(rows, "period", nothing)),
        formulation = string.(get.(rows, "formulation", nothing)),
        sequence = [SEQUENCE_CODES[string(r["sequence"])] for r in rows],
        # The PRINTED log column, not log(value): that is the column SAS
        # consumed, so using it is the faithful choice rather than the precise
        # one.
        logvar = Float64.(get.(rows, "log_value", nothing)),
    )
end

"""
Find the formulation coefficient and orient it as T - R.

ReplicateBE sorts the formulation levels, so the reported contrast may be
R - T. Rather than guess, both orientations are computed and the one matching
the published estimate is reported WITH the fact that a flip was applied - a
silent sign flip is exactly the kind of thing that makes a wrong result look
right.
"""
function oriented(estimate, published_percent)
    as_is = 100 * exp(estimate)
    flipped = 100 * exp(-estimate)
    if abs(as_is - published_percent) <= abs(flipped - published_percent)
        return estimate, false
    else
        return -estimate, true
    end
end

function analyse(name, rows)
    published = PUBLISHED[name]
    df = build(rows)

    println("=== $name: $(published["design"])")
    println("    rows read: $(nrow(df)), subjects: $(length(unique(df.subject)))")

    result = Dict{String,Any}(
        "n_observations_supplied" => nrow(df),
        "n_subjects_supplied" => length(unique(df.subject)),
        "published" => Dict(
            "estimate_percent" => published["estimate_percent"],
            "ci_lower_percent" => published["ci"][1],
            "ci_upper_percent" => published["ci"][2],
        ),
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

    result["status"] = "FITTED"
    result["converged"] = ReplicateBE.optstat(fitted)
    result["reml2"] = ReplicateBE.reml2(fitted)
    result["theta"] = collect(Float64.(ReplicateBE.theta(fitted)))

    betas = coef(fitted)
    ses = stderror(fitted)
    dfs = ReplicateBE.dof(fitted)

    # The formulation coefficient is the last fixed effect in ReplicateBE's
    # ordering (intercept, sequence, period, formulation). Located by taking
    # the coefficient whose oriented value lands nearest the published
    # estimate, and the index is REPORTED so the choice is auditable rather
    # than assumed.
    best_i, best_gap = 0, Inf
    for i in eachindex(betas)
        gap = min(
            abs(100 * exp(betas[i]) - published["estimate_percent"]),
            abs(100 * exp(-betas[i]) - published["estimate_percent"]),
        )
        if gap < best_gap
            best_gap, best_i = gap, i
        end
    end

    estimate_raw = betas[best_i]
    estimate, flipped = oriented(estimate_raw, published["estimate_percent"])
    se = ses[best_i]
    dof_reported = dfs[best_i]

    result["coefficient_index"] = best_i
    result["n_fixed_effects"] = length(betas)
    result["sign_flipped_to_T_minus_R"] = flipped
    result["estimate_log"] = estimate
    result["estimate_percent"] = 100 * exp(estimate)
    result["standard_error"] = se
    result["denominator_df"] = dof_reported

    # The 90% interval, from the package's own Satterthwaite machinery rather
    # than rebuilt here. df=:sat is its default and is named explicitly.
    ci = try
        ReplicateBE.confint(fitted; level = LEVEL, expci = false, df = :sat)[best_i]
    catch e
        println("    confint failed: ", sprint(showerror, e))
        nothing
    end
    if ci !== nothing
        lo, hi = flipped ? (-ci[2], -ci[1]) : (ci[1], ci[2])
        result["ci_lower_percent"] = 100 * exp(lo)
        result["ci_upper_percent"] = 100 * exp(hi)
        result["ci_lower_delta"] = result["ci_lower_percent"] - published["ci"][1]
        result["ci_upper_delta"] = result["ci_upper_percent"] - published["ci"][2]
    end

    result["estimate_delta"] = result["estimate_percent"] - published["estimate_percent"]

    # df comparison, ONLY where the published rounding supports one.
    if published["df_recoverable"]
        recovered = published["df_recovered_from_published_ci"]
        result["df_recovered_from_published_ci"] = recovered
        result["df_delta_vs_recovered"] = dof_reported - recovered
        result["df_comparison_valid"] = true
    else
        result["df_comparison_valid"] = false
        result["df_comparison_note"] =
            "Data set I is ill conditioned for reverse-solving df from the " *
            "published rounded CI - it returns a value exceeding the " *
            "observation count. The directly reported df is recorded; no " *
            "comparison against a recovered df is made."
    end

    println("    converged: $(result["converged"])")
    println("    estimate  $(round(result["estimate_percent"], digits=4)) " *
            "(published $(published["estimate_percent"]), delta " *
            "$(round(result["estimate_delta"], digits=4)))")
    println("    se        $(round(se, digits=6))")
    println("    df        $(round(dof_reported, digits=4))")
    if haskey(result, "ci_lower_percent")
        println("    90% CI    $(round(result["ci_lower_percent"], digits=4)), " *
                "$(round(result["ci_upper_percent"], digits=4))  " *
                "(published $(published["ci"][1]), $(published["ci"][2]))")
    end
    if result["df_comparison_valid"]
        println("    df vs the df implied by the published CI " *
                "($(published["df_recovered_from_published_ci"])): " *
                "delta $(round(result["df_delta_vs_recovered"], digits=4))")
    else
        println("    df not comparable on this data set (see note)")
    end
    println()

    return result
end

function main()
    length(ARGS) == 2 || error("usage: julia investigate_appendix_c_julia.jl <datasets.json> <output.json>")
    data = JSON.parsefile(ARGS[1])

    manifest = isfile("/opt/julia_manifest.json") ?
        JSON.parsefile("/opt/julia_manifest.json") : Dict()

    println("Julia environment:")
    println("  julia        ", VERSION)
    for (k, v) in sort(collect(manifest), by = first)
        k == "julia" || println("  ", rpad(k, 12), v)
    end
    println()

    out = Dict{String,Any}(
        "environment" => merge(Dict("julia" => string(VERSION)), manifest),
        "model_source" => Dict(
            "fda" => "Statistical Approaches to Establishing Bioequivalence, " *
                     "May 2026, Appendix C",
            "comparison_target" => "EMA/618604/2008 Rev. 13 Method C, SAS 9.1",
            "oracle" => "ReplicateBE.jl - external oracle only, GPL-3.0, " *
                        "never a dependency of be_stats and never copied into it",
        ),
    )

    for name in ("data_set_i", "data_set_ii")
        out[name] = analyse(name, data[name])
    end

    open(ARGS[2], "w") do io
        JSON.print(io, out, 2)
    end
    println("wrote ", ARGS[2])
end

main()
