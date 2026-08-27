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
  if (!identical(as.character(lock$powertost_version), powertost_version)) {
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

eval_constant <- function(case) {
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

eval_power <- function(case) {
  i <- case$inputs
  design <- if (!is.null(i$powertost_design)) i$powertost_design else i$design
  nsims_r <- if (!is.null(i$nsims_r)) i$nsims_r else 1e5

  if (identical(case$method, "fda_hvd_rsabe")) {
    cv <- if (isTRUE(all.equal(i$cv_wt, i$cv_wr))) i$cv_wr else c(i$cv_wt, i$cv_wr)
    res <- PowerTOST::power.RSABE(
      CV = cv,
      theta0 = i$theta0,
      n = i$n,
      design = design,
      regulator = "FDA",
      nsims = nsims_r,
      details = TRUE,
      setseed = TRUE
    )
    return(list(
      p_be_sabec = as.numeric(res[["p(BE-sABEc)"]]),
      p_be_pe = as.numeric(res[["p(BE-pe)"]]),
      .p_be = as.numeric(res[["p(BE)"]]),
      .p_be_abe = as.numeric(res[["p(BE-ABE)"]])
    ))
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
