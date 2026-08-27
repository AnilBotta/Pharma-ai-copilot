#!/usr/bin/env Rscript
#
# The R half of the external validation harness.
#
# Reads the SAME case files the Python half reads, runs PowerTOST for each, and
# writes the results as JSON. It makes no comparisons and applies no tolerances
# - that is `harness.py`'s job, so the two sides cannot quietly agree on a
# lenient rule.
#
# HOW THIS SCRIPT FAILS
#
# Loudly, and on the first problem. A case whose oracle function is unknown, a
# PowerTOST call that errors, a version that does not match the lockfile: all
# stop the run. A validation script that skips what it cannot do and exits 0 is
# worse than no validation script, because its silence reads as agreement.
#
# Usage:
#   Rscript run_powertost.R <cases_dir> <output_json>

suppressWarnings(suppressMessages({
  library(jsonlite)
  library(PowerTOST)
}))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: Rscript run_powertost.R <cases_dir> <output_json>", call. = FALSE)
}
cases_dir <- args[[1]]
output_path <- args[[2]]

# ---------------------------------------------------------------- versions ---

powertost_version <- as.character(utils::packageVersion("PowerTOST"))
r_version <- paste(R.version$major, R.version$minor, sep = ".")

lock_path <- file.path(dirname(normalizePath(sub("--file=", "", grep("--file=",
  commandArgs(trailingOnly = FALSE), value = TRUE)[1]))), "environment.lock.json")
if (file.exists(lock_path)) {
  lock <- jsonlite::fromJSON(lock_path)
  # Version comparison, not string comparison - CRAN's "1.5-7" normalises to
  # "1.5.7" through package_version. See install_r_packages.R.
  pinned <- package_version(gsub("-", ".", as.character(lock$powertost_version),
                                 fixed = TRUE))
  if (utils::packageVersion("PowerTOST") != pinned) {
    stop(sprintf(
      paste0("PowerTOST %s is installed but environment.lock.json pins %s. ",
             "An unpinned oracle is not an oracle: fix the environment or ",
             "update the lockfile deliberately."),
      powertost_version, lock$powertost_version
    ), call. = FALSE)
  }
}

cat(sprintf("R %s, PowerTOST %s\n", r_version, powertost_version))

# ------------------------------------------------------------- evaluators ---

eval_direct <- function(case) {
  i <- case$inputs
  design <- if (!is.null(i$powertost_design)) i$powertost_design else i$design

  ss <- PowerTOST::sampleN.TOST(
    CV = i$cv,
    theta0 = i$theta0,
    theta1 = i$lower_limit,
    theta2 = i$upper_limit,
    targetpower = i$target_power,
    alpha = i$alpha,
    design = design,
    method = "exact",
    print = FALSE,
    details = FALSE
  )
  n <- ss[["Sample size"]]

  pw <- PowerTOST::power.TOST(
    CV = i$cv,
    theta0 = i$theta0,
    theta1 = i$lower_limit,
    theta2 = i$upper_limit,
    n = n,
    alpha = i$alpha,
    design = design,
    method = "exact"
  )
  list(sample_size = as.numeric(n), achieved_power = as.numeric(pw))
}

# EMA's widened acceptance limits, from a DETERMINISTIC PowerTOST function.
#
# `scABEL` simulates nothing: it is a closed-form function of CV. That makes
# this the strongest comparison in the harness - agreement is exact rather than
# statistical, and a difference cannot be explained away as sampling noise.
#
# TWO THINGS TO KNOW ABOUT IT, BOTH READ FROM THE SOURCE FIRST
#
# 1. The lower limit is computed as `1/upper`, not as `exp(-r_const*se)`
#    (R/scABEL.R line 119: "lower acceptance limit is set to 1/upper"). Equal
#    in exact arithmetic; EMA writes the pair symmetrically as exp[+/- k.sWR],
#    which is what be-stats computes.
#
# 2. The cap is RECOMPUTED from CVcap - `exp(r_const*CV2se(CVcap))` - where the
#    guideline states the pair 69.84 - 143.19%. be-stats applies the stated
#    pair. The two differ by 0.0032 / 0.0010 percentage points at and above the
#    cap. That is VAL-EMA-ABEL-002, predicted before this ran, and the capped
#    cases assert the predicted difference rather than widening a tolerance to
#    absorb it.
#
# The switch itself AGREES with the regulator here: widening applies for
# CV > 0.3 (with a 1e-10 tolerance), which is EMA's strict >30%. Unlike the FDA
# case, PowerTOST and the guideline do not disagree about the trigger.
eval_abel_limits <- function(case) {
  i <- case$inputs
  limits <- PowerTOST::scABEL(CV = i$cv_wr, regulator = "EMA")
  reg <- PowerTOST::reg_const("EMA")
  list(
    abel_lower_percent = 100 * as.numeric(limits[["lower"]]),
    abel_upper_percent = 100 * as.numeric(limits[["upper"]]),
    regulatory_constant_k = as.numeric(reg$r_const),
    # PowerTOST's cap, recomputed from CVcap. Reported so the divergence is a
    # number in the report rather than a claim in a comment.
    cap_lower_computed_percent =
      100 / exp(as.numeric(reg$r_const) * PowerTOST::CV2se(as.numeric(reg$CVcap))),
    cap_upper_computed_percent =
      100 * exp(as.numeric(reg$r_const) * PowerTOST::CV2se(as.numeric(reg$CVcap))),
    .cvswitch = as.numeric(reg$CVswitch),
    .cvcap = as.numeric(reg$CVcap),
    .est_method = as.character(reg$est_method)
  )
}

eval_ema_constant <- function(case) {
  reg <- PowerTOST::reg_const("EMA")
  list(
    ema_regulatory_constant_k = as.numeric(reg$r_const),
    ema_cv_switch_percent = 100 * as.numeric(reg$CVswitch),
    ema_cv_cap_percent = 100 * as.numeric(reg$CVcap),
    ema_point_estimate_lower_percent = 80,
    ema_point_estimate_upper_percent = 125,
    .pe_constr = as.logical(reg$pe_constr),
    .est_method = as.character(reg$est_method)
  )
}

eval_constant <- function(case) {
  if (identical(case$inputs$regulator, "EMA")) {
    return(eval_ema_constant(case))
  }
  reg <- PowerTOST::reg_const("FDA")
  list(
    hvd_r_const = as.numeric(reg$r_const),
    # PowerTOST does not carry the point-estimate limits as numbers on the
    # regSet - `pe_constr` is a logical saying whether the constraint applies.
    # The limits themselves are the conventional theta1/theta2, which are the
    # defaults of the RSABE functions. Asserting the default here is what makes
    # the comparison meaningful rather than tautological.
    hvd_point_estimate_lower = 0.8,
    hvd_point_estimate_upper = 1.25,
    nti_variance_ratio_upper_limit = 2.5,
    .pe_constr = as.logical(reg$pe_constr),
    .cvswitch = as.numeric(reg$CVswitch),
    .est_method = as.character(reg$est_method)
  )
}

# WHAT `p(BE-sABEc)` ACTUALLY IS - VAL-FDA-HVD-001
#
# It is NOT the scaled criterion applied to every simulated study. In
# PowerTOST 1.5-7, `R/power_RSABE2L_isc.R`, `power.RSABE` names its second
# element "p(BE-sABEc)" and fills it from `counts["BEul"]` (line 273), which
# accumulates
#
#     BE <- ifelse(s2wRs > s2switch, BE_RSABE, BE_ABE)          # line 257
#
# - the MIXED procedure without the point-estimate constraint. Below the
# switch it reports conventional ABE, not the scaled criterion.
#
# be-stats cannot produce that quantity: it refuses the unscaled replicate
# branch until Appendix C is implemented. Comparing the two as if they were
# the same thing is what produced the 4.61-sigma finding in PR #58.
#
# THE FIX, AND WHY IT IS NOT A FUDGE
#
# `reg_const("USER", CVswitch = 0, ...)` makes `s2switch <- log(0^2+1) = 0`
# (line 156), and `s2wRs` is a scaled chi-square draw, so it exceeds 0 with
# probability one. Every study therefore takes the `BE_RSABE` branch and
# `p(BE-sABEc)` becomes the scaled criterion ALONE - the quantity be-stats
# computes. `CVcap = Inf` leaves `is.finite(CVcap)` false, so the capping
# block at line 260 does not run, and FDA imposes no cap anyway.
#
# Nothing about the criterion changes: r_const is FDA's log(1.25)/0.25 and
# SABE_test is still "fda", including its `Em <- Em - SEs^2` bias correction.
# Only the routing is switched off, on the side that has routing.
#
# `est_method` differs between the two regSets - "ISC" for FDA, "ANOVA" for a
# USER set (`R/scABEL.R` lines 17 and 51). `power.RSABE` never reads it: it
# takes CVswitch, r_const, pe_constr and CVcap from the regSet (lines 44-46)
# and calls `.power.RSABE` directly. `est_method` selects an ESTIMATION route
# in the functions that analyse data, of which this is not one.
experiment_regulator <- function(experiment) {
  if (is.null(experiment) || identical(experiment, "fda_mixed_procedure")) {
    return("FDA")
  }
  if (identical(experiment, "scaled_criterion_isolated")) {
    return(PowerTOST::reg_const(
      "USER",
      r_const = log(1.25) / 0.25,
      CVswitch = 0,
      CVcap = Inf,
      pe_constr = TRUE
    ))
  }
  stop(sprintf("unknown experiment '%s'", experiment), call. = FALSE)
}

# P(a study lands below a given sWR switch), exactly.
#
# sWR^2 * dfRR / sigma^2_wR is chi-square on dfRR degrees of freedom under the
# model both sides simulate, so this needs no simulation. It is the one place
# the two switching RULES can be compared as rules rather than as outcomes.
exact_p_below_switch <- function(swr_threshold, cv_wr, n, design) {
  df_rr <- switch(design,
    "2x2x4" = n - 2,
    "2x3x3" = n - 3,
    stop(sprintf("no dfRR for design '%s'", design), call. = FALSE)
  )
  s2wr <- log(cv_wr^2 + 1)
  stats::pchisq(df_rr * swr_threshold^2 / s2wr, df = df_rr)
}

eval_power <- function(case) {
  i <- case$inputs
  design <- if (!is.null(i$powertost_design)) i$powertost_design else i$design
  nsims_r <- if (!is.null(i$nsims_r)) i$nsims_r else 1e5

  if (identical(case$method, "fda_hvd_rsabe")) {
    cv <- if (isTRUE(all.equal(i$cv_wt, i$cv_wr))) i$cv_wr else c(i$cv_wt, i$cv_wr)
    regulator <- experiment_regulator(i$experiment)
    res <- PowerTOST::power.RSABE(
      CV = cv,
      theta0 = i$theta0,
      n = i$n,
      design = design,
      regulator = regulator,
      nsims = nsims_r,
      details = TRUE,
      setseed = TRUE
    )
    fda <- PowerTOST::reg_const("FDA")
    out <- list(
      p_be_sabec = as.numeric(res[["p(BE-sABEc)"]]),
      p_be_pe = as.numeric(res[["p(BE-pe)"]]),
      .p_be = as.numeric(res[["p(BE)"]]),
      .p_be_abe = as.numeric(res[["p(BE-ABE)"]]),
      .experiment = if (is.null(i$experiment)) "fda_mixed_procedure"
                    else i$experiment,
      # The oracle's own switch, on the sWR scale, so the divergence recorded
      # as VAL-FDA-HVD-002 is a number in the report rather than a claim in a
      # comment: PowerTOST converts CVswitch = 0.3 to sqrt(log(1.09)) =
      # 0.293560..., where FDA Appendix G states 0.294.
      .powertost_swr_switch = sqrt(log(as.numeric(fda$CVswitch)^2 + 1))
    )
    # Only where the case asks for it: the comparison needs cv_wt == cv_wr and
    # a stated be-stats threshold, and asserting it elsewhere would be a
    # tolerance applied to a quantity nobody chose to compare.
    if (!is.null(i$be_stats_swr_switch)) {
      out$p_below_switch <- exact_p_below_switch(
        i$be_stats_swr_switch, i$cv_wr, i$n, design
      )
      out$.p_below_switch_powertost <- exact_p_below_switch(
        out$.powertost_swr_switch, i$cv_wr, i$n, design
      )
    }
    return(out)
  }

  if (identical(case$method, "fda_nti")) {
    cv <- if (isTRUE(all.equal(i$cv_wt, i$cv_wr))) i$cv_wr else c(i$cv_wt, i$cv_wr)
    res <- PowerTOST::power.NTID(
      CV = cv,
      theta0 = i$theta0,
      n = i$n,
      design = design,
      nsims = nsims_r,
      details = TRUE,
      setseed = TRUE
    )
    return(list(
      p_be_sabec = as.numeric(res[["p(BE-sABEc)"]]),
      p_be_sratio = as.numeric(res[["p(BE-sratio)"]]),
      .p_be = as.numeric(res[["p(BE)"]]),
      .p_be_abe = as.numeric(res[["p(BE-ABE)"]])
    ))
  }

  stop(sprintf("no PowerTOST evaluator for method '%s'", case$method), call. = FALSE)
}

# ------------------------------------------------------------------- main ---

files <- sort(list.files(cases_dir, pattern = "[.]json$", full.names = TRUE))
if (length(files) == 0L) {
  stop(sprintf("no case files in %s", cases_dir), call. = FALSE)
}

results <- list()
for (path in files) {
  case <- jsonlite::fromJSON(path, simplifyVector = TRUE)
  kind <- case$comparison_kind
  cat(sprintf("  %-30s %s\n", case$case_id, kind))

  value <- switch(kind,
    "direct" = eval_direct(case),
    "constant" = eval_constant(case),
    "monte_carlo_power" = eval_power(case),
    "abel_limits" = eval_abel_limits(case),
    stop(sprintf("unknown comparison_kind '%s' in %s", kind, case$case_id),
         call. = FALSE)
  )
  results[[case$case_id]] <- value
}

# Every version that could bear on a number, as RESOLVED rather than as
# declared. The lockfile says what was asked for; this says what ran.
resolved <- list()
for (pkg in c("PowerTOST", "jsonlite", "mvtnorm", "cubature")) {
  resolved[[pkg]] <- if (requireNamespace(pkg, quietly = TRUE)) {
    as.character(utils::packageVersion(pkg))
  } else {
    "absent"
  }
}

results[[".environment"]] <- list(
  r_version = r_version,
  powertost_version = powertost_version,
  r_packages_resolved = resolved,
  platform = R.version$platform,
  generated = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
)

writeLines(jsonlite::toJSON(results, auto_unbox = TRUE, digits = 15), output_path)
cat(sprintf("wrote %s\n", output_path))
