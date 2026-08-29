#!/usr/bin/env Rscript
#
# Is there a trustworthy numerical oracle for FDA Appendix C?
#
# THE MODEL, VERBATIM FROM THE REGULATOR
#
# FDA, Statistical Approaches to Establishing Bioequivalence, May 2026,
# Appendix C, "SAS Program Statements for Average BE Analysis of Replicate
# Crossover Studies":
#
#     PROC MIXED;
#     CLASSES SEQ SUBJ PER TRT;
#     MODEL Y = SEQ PER TRT/ DDFM=SATTERTH;
#     RANDOM TRT/TYPE=FA0(2) SUB=SUBJ G;
#     REPEATED/GRP=TRT SUB=SUBJ;
#     ESTIMATE 'T vs. R' TRT 1 -1/CL ALPHA=0.1;
#
# FDA adds two things that matter here:
#
#   "In the Random statement, TYPE=FA0(2) could possibly be replaced by
#    TYPE=CSH or UNR. In the Model statement, DDFM=SATTERTH could possibly be
#    replaced by DDFM=KR2."
#
#   "Alternative software could also be used if same results are generated as
#    in PROC MIXED in SAS."
#
# That last sentence is the licence for this whole exercise - and its burden.
# "Same results" is the bar, and this script exists to find out whether any R
# implementation clears it.
#
# WHAT IS BEING COMPARED AGAINST
#
# The FDA guidance publishes NO worked dataset. EMA does, and it publishes it
# for THIS MODEL: EMA/618604/2008 Rev. 13 calls it "Method C" and attributes it
# to the FDA guidance by name, transcribing the same PROC MIXED specification.
# Two data sets, raw data in the annex, results printed:
#
#     Data set I    point estimate 115.66   90% CI 107.10, 124.89
#                   within-subject CV%: reference 47.3, test 35.3
#     Data set II   point estimate 102.26   90% CI  97.05, 107.76
#                   within-subject CV%: reference 11.5
#
# Neither SE nor denominator df is published. That gap is the central problem
# for validating Appendix C, and `recover_df_from_published_ci` below is the
# one lever available against it.
#
# FOUR REQUIREMENTS, EVALUATED SEPARATELY
#
#   1. fixed SEQ + PER + TRT
#   2. subject-by-formulation covariance (the G matrix)
#   3. treatment-specific residual variances (the R matrix)
#   4. Satterthwaite denominator df for the T-R contrast
#
# A package is not an oracle unless all four hold. Reporting them separately is
# the point: a package that gets 1-3 right and 4 wrong produces a correct
# estimate inside a wrong confidence interval, which is a wrong BE decision
# wearing the right numbers.
#
# Usage:
#   Rscript investigate_appendix_c.R <datasets.json> <output.json>

suppressWarnings(suppressMessages(library(jsonlite)))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: Rscript investigate_appendix_c.R <datasets.json> <output.json>",
       call. = FALSE)
}
data_path <- args[[1]]
out_path <- args[[2]]

SUPPORTED <- "SUPPORTED"
PARTIAL <- "PARTIAL"
NOT_SUPPORTED <- "NOT_SUPPORTED"
NOT_DETERMINED <- "NOT_DETERMINED"

available <- function(pkg) requireNamespace(pkg, quietly = TRUE)

version_of <- function(pkg) {
  if (available(pkg)) as.character(utils::packageVersion(pkg)) else "absent"
}

# --------------------------------------------------------------- the data ---

# Sequence coding, transcribed as EMA printed it. Data set I uses letters where
# A is the TEST and B the reference - the opposite reading is the obvious guess
# and would invert every result.
SEQUENCE_CODES <- list(
  "ABAB" = "TRTR", "BABA" = "RTRT",
  "1" = "TRR", "2" = "RTR", "3" = "RRT"
)

load_dataset <- function(rows) {
  data.frame(
    SUBJ = factor(rows$subject),
    PER = factor(rows$period),
    TRT = factor(rows$formulation, levels = c("R", "T")),
    SEQ = factor(vapply(rows$sequence, function(s) SEQUENCE_CODES[[s]], "")),
    Y = as.numeric(rows$log_value),
    stringsAsFactors = FALSE
  )
}

# EMA's published Method C results. The comparison targets.
PUBLISHED <- list(
  data_set_i = list(
    estimate_percent = 115.66, ci = c(107.10, 124.89),
    cv_wr_percent = 47.3, cv_wt_percent = 35.3,
    design = "4-period fully replicate, 77 subjects, 8 incomplete"
  ),
  data_set_ii = list(
    estimate_percent = 102.26, ci = c(97.05, 107.76),
    cv_wr_percent = 11.5, cv_wt_percent = NA,
    design = "3-period partial replicate, 24 subjects, balanced"
  )
)

# ------------------------------------------- recovering SAS's df, if we can ---

# EMA publishes the point estimate and the 90% CI but not the SE or the df.
# Given a CANDIDATE's SE, the df SAS must have used is recoverable:
#
#     half_width = t(1 - alpha, df) * SE   =>   t = half_width / SE
#
# and inverting the t quantile gives df. This is only as good as the
# candidate's SE - if that is wrong the recovered df is meaningless - so it is
# reported as a DIAGNOSTIC and never as a validated df. Its value is that an
# implausible answer (negative, or far outside [n_subjects, n_obs]) is evidence
# the candidate's SE is wrong, and a plausible one is weak corroboration that
# both the SE and the df line up with SAS.
recover_df_from_published_ci <- function(estimate_log, se, published_ci, alpha = 0.05) {
  if (!is.finite(se) || se <= 0) return(list(recovered_df = NA, note = "no usable SE"))
  half_width <- (log(published_ci[2] / 100) - log(published_ci[1] / 100)) / 2
  t_implied <- half_width / se
  if (!is.finite(t_implied) || t_implied <= 0) {
    return(list(recovered_df = NA, note = "implied t is not usable"))
  }
  # Solve qt(1 - alpha, df) = t_implied for df.
  f <- function(df) stats::qt(1 - alpha, df) - t_implied
  if (f(1) * f(1e6) > 0) {
    return(list(
      recovered_df = NA,
      t_implied = t_implied,
      note = paste0(
        "no df reproduces the published interval from this SE; the implied t ",
        "of ", signif(t_implied, 8), " lies outside what any t distribution ",
        "gives at alpha = 0.05, so this candidate's SE disagrees with SAS"
      )
    ))
  }
  root <- stats::uniroot(f, c(1, 1e6), tol = 1e-9)

  # CONDITIONING. dt/d(df) vanishes as df grows, so when the implied t sits
  # near the normal quantile 1.6449 a change in the SE of a fraction of a
  # percent moves the recovered df by hundreds. The first run recovered 541 df
  # for Data set I - more than its 298 observations, which is impossible for
  # this model - purely because t_implied was 1.6475.
  #
  # So the recovery is reported with the sensitivity that produced it, and an
  # answer exceeding the observation count is marked implausible rather than
  # printed as though it meant something.
  df_hat <- root$root

  # BOTH DIRECTIONS. The df-to-t map is steeply asymmetric near the normal
  # limit: on Data set I, perturbing the SE by 0.1% moved the recovered df by
  # 161 downwards and 773 upwards. Checking only one direction reported that
  # case as "well conditioned" while the same output also flagged it as
  # impossible - two conclusions from one number, which is a bug in the
  # diagnostic rather than a property of the data.
  shift_for <- function(factor) {
    tryCatch(
      abs(
        stats::uniroot(
          function(df) stats::qt(1 - alpha, df) - t_implied * factor,
          c(1, 1e9), tol = 1e-9, extendInt = "yes"
        )$root - df_hat
      ),
      error = function(e) Inf
    )
  }
  worst_shift <- max(shift_for(1.001), shift_for(0.999))

  list(
    recovered_df = df_hat,
    t_implied = t_implied,
    df_shift_per_0.1pct_se = worst_shift,
    well_conditioned = worst_shift < 0.25 * df_hat,
    note = paste(
      "diagnostic only - depends entirely on this candidate's SE, and is",
      "ill-conditioned wherever the implied t approaches 1.645"
    )
  )
}

summarise_fit <- function(estimate_log, se, df, published, n_obs, n_subjects) {
  out <- list(
    estimate_log = estimate_log,
    estimate_percent = 100 * exp(estimate_log),
    standard_error = se,
    reported_df = df,
    n_observations = n_obs,
    n_subjects = n_subjects
  )
  # `df` may legitimately be Inf: glmmTMB reports no denominator df at all and
  # its interval is a Wald z interval, which is exactly qt(., Inf). Treating
  # that as "no interval" would hide the comparison rather than make it.
  if (is.finite(se) && !is.na(df) && df > 0) {
    hw <- stats::qt(0.95, df) * se
    out$ci_lower_percent <- 100 * exp(estimate_log - hw)
    out$ci_upper_percent <- 100 * exp(estimate_log + hw)
    out$ci_lower_delta <- out$ci_lower_percent - published$ci[1]
    out$ci_upper_delta <- out$ci_upper_percent - published$ci[2]
  }
  out$estimate_delta <- out$estimate_percent - published$estimate_percent
  rec <- recover_df_from_published_ci(estimate_log, se, published$ci)
  # A Satterthwaite df for this model cannot exceed the number of
  # observations. Anything larger says the recovery has broken down, not that
  # SAS used 500 degrees of freedom.
  if (!is.null(rec$recovered_df) && is.finite(rec$recovered_df)) {
    rec$exceeds_n_observations <- rec$recovered_df > n_obs
  }
  out$recovered <- rec
  out
}

cv_from_variance <- function(v) if (is.finite(v) && v > 0) 100 * sqrt(exp(v) - 1) else NA

# ------------------------------------------------------------------- nlme ---

# nlme is the leading candidate for one reason beyond its features: it SHIPS
# WITH R as a recommended package, so it carries no supply-chain risk at all.
#
#   random = list(SUBJ = pdSymm(~ TRT - 1))
#       a full 2x2 subject-level covariance for (R, T) - between-subject
#       variance for each formulation plus their covariance. Three parameters.
#       pdSymm parameterises through a Cholesky factor, so the matrix is
#       positive-definite by construction, which is the same guarantee SAS's
#       FA0(2) provides and the reason FDA names FA0(2) rather than UN.
#
#   weights = varIdent(form = ~ 1 | TRT)
#       a separate residual variance per treatment - SAS's REPEATED/GRP=TRT.
#       Two parameters. Five in total, matching FDA's model.
fit_nlme <- function(d, published) {
  if (!available("nlme")) {
    return(list(status = NOT_DETERMINED, reason = "nlme not available"))
  }
  suppressMessages(library(nlme))
  fit <- tryCatch(
    nlme::lme(
      fixed = Y ~ SEQ + PER + TRT,
      random = list(SUBJ = nlme::pdSymm(~ TRT - 1)),
      weights = nlme::varIdent(form = ~ 1 | TRT),
      data = d,
      method = "REML",
      control = nlme::lmeControl(
        opt = "optim", maxIter = 500, msMaxIter = 500, niterEM = 100,
        returnObject = TRUE
      )
    ),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    return(list(status = NOT_DETERMINED,
                reason = paste("lme failed:", conditionMessage(fit))))
  }

  cf <- summary(fit)$tTable
  trt_row <- grep("^TRT", rownames(cf), value = TRUE)
  if (length(trt_row) != 1L) {
    return(list(status = NOT_DETERMINED,
                reason = "could not identify the TRT row in the fixed effects"))
  }
  estimate <- unname(cf[trt_row, "Value"])
  se <- unname(cf[trt_row, "Std.Error"])
  df <- unname(cf[trt_row, "DF"])

  # Residual variances by treatment. varIdent reports RATIOS to the reference
  # stratum, so sigma^2 * ratio^2 gives each group's variance.
  sigma <- fit$sigma
  ratios <- stats::coef(fit$modelStruct$varStruct, unconstrained = FALSE,
                        allCoef = TRUE)
  var_by_trt <- (sigma * ratios)^2

  # getVarCov returns an object of class "VarCov", which jsonlite cannot
  # serialise ("No method asJSON S3 class: VarCov" ended the first run after
  # every number had already been computed). Stripped to plain numerics and
  # named from the matrix's own dimnames rather than by assuming which of T
  # and R is index 1.
  g <- tryCatch(
    {
      m <- nlme::getVarCov(fit)
      labels <- colnames(m)
      if (is.null(labels)) labels <- paste0("level", seq_len(ncol(m)))
      stats::setNames(
        as.list(c(
          as.numeric(m[1, 1]), as.numeric(m[2, 2]), as.numeric(m[1, 2])
        )),
        c(
          paste0("between_subject_variance_", labels[1]),
          paste0("between_subject_variance_", labels[2]),
          "between_subject_covariance"
        )
      )
    },
    error = function(e) NULL
  )

  res <- summarise_fit(estimate, se, df, published, nrow(d),
                       nlevels(droplevels(d$SUBJ)))
  res$status <- SUPPORTED
  res$residual_variance_by_treatment <- as.list(var_by_trt)
  res$cv_within_percent <- lapply(as.list(var_by_trt), cv_from_variance)
  res$subject_covariance_G <- g
  res$df_method <- paste(
    "nlme containment ('inner-outer'), NOT Satterthwaite. lme reports a df",
    "determined by the level at which each term varies, which is a different",
    "quantity from SAS DDFM=SATTERTH."
  )
  res$requirements <- list(
    fixed_seq_per_trt = SUPPORTED,
    subject_by_formulation_covariance = SUPPORTED,
    treatment_specific_residuals = SUPPORTED,
    satterthwaite_df = NOT_SUPPORTED
  )
  res
}

# ------------------------------------------------------------ lme4/lmerTest ---

# lme4 fits a SINGLE residual variance. There is no `weights = varIdent`
# equivalent and no dispersion formula, so requirement 3 cannot be met by the
# model as FDA writes it. lmerTest then supplies genuine Satterthwaite df - for
# a model that is not Appendix C.
#
# Fitted anyway, and reported, because "we did not try" and "we tried and it
# cannot" are different findings, and because the estimate is still worth
# seeing next to nlme's.
fit_lme4 <- function(d, published) {
  if (!available("lme4")) {
    return(list(status = NOT_DETERMINED, reason = "lme4 not available"))
  }
  suppressMessages(library(lme4))
  has_lmertest <- available("lmerTest")
  if (has_lmertest) suppressMessages(library(lmerTest))

  fit <- tryCatch(
    lme4::lmer(Y ~ SEQ + PER + TRT + (0 + TRT | SUBJ), data = d, REML = TRUE),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    return(list(status = NOT_DETERMINED,
                reason = paste("lmer failed:", conditionMessage(fit))))
  }

  cf <- tryCatch(as.data.frame(coef(summary(fit))), error = function(e) NULL)
  if (is.null(cf)) {
    return(list(status = NOT_DETERMINED, reason = "no coefficient table"))
  }
  trt_row <- grep("^TRT", rownames(cf), value = TRUE)[1]
  estimate <- cf[trt_row, "Estimate"]
  se <- cf[trt_row, "Std. Error"]
  df <- if ("df" %in% colnames(cf)) cf[trt_row, "df"] else NA_real_

  res <- summarise_fit(estimate, se, df, published, nrow(d),
                       nlevels(droplevels(d$SUBJ)))
  res$status <- PARTIAL
  res$residual_variance_single <- stats::sigma(fit)^2
  res$df_method <- if (has_lmertest && is.finite(df)) {
    "lmerTest Satterthwaite - genuine, but computed for a model with ONE residual variance"
  } else {
    "no df available"
  }
  res$requirements <- list(
    fixed_seq_per_trt = SUPPORTED,
    subject_by_formulation_covariance = SUPPORTED,
    treatment_specific_residuals = NOT_SUPPORTED,
    satterthwaite_df = if (has_lmertest && is.finite(df)) SUPPORTED else NOT_DETERMINED
  )
  res$why_not_an_oracle <- paste(
    "lme4 estimates a single residual variance. FDA's REPEATED/GRP=TRT",
    "requires one per treatment. Satterthwaite df computed on the wrong",
    "covariance structure is not FDA's Satterthwaite df, however correctly",
    "lmerTest computes it."
  )
  res
}

# ---------------------------------------------------------------- glmmTMB ---

# glmmTMB CAN express both the unstructured subject-by-formulation covariance
# (`us(0 + TRT | SUBJ)`) and treatment-specific residual variances
# (`dispformula = ~ TRT`). It is the only candidate that meets requirements
# 1-3 besides nlme.
#
# Its inference is Wald: standard errors from the observed information and
# NORMAL quantiles, with no denominator df at all. That is not a small
# difference at these sample sizes - z = 1.6449 against t(70) = 1.6669 is about
# 1.3% on the half-width, which moves a borderline BE decision.
fit_glmmTMB <- function(d, published) {
  if (!available("glmmTMB")) {
    return(list(status = NOT_DETERMINED, reason = "glmmTMB not available"))
  }
  suppressMessages(library(glmmTMB))
  fit <- tryCatch(
    glmmTMB::glmmTMB(
      # `us(...)` unqualified: glmmTMB resolves these structure functions when
      # it walks the formula, and a namespace-qualified call in a formula is
      # not the idiom it expects.
      Y ~ SEQ + PER + TRT + us(0 + TRT | SUBJ),
      dispformula = ~ TRT,
      data = d,
      REML = TRUE
    ),
    error = function(e) e
  )
  if (inherits(fit, "error")) {
    return(list(status = NOT_DETERMINED,
                reason = paste("glmmTMB failed:", conditionMessage(fit))))
  }
  cf <- tryCatch(
    as.data.frame(summary(fit)$coefficients$cond), error = function(e) NULL
  )
  if (is.null(cf)) {
    return(list(status = NOT_DETERMINED, reason = "no coefficient table"))
  }
  trt_row <- grep("^TRT", rownames(cf), value = TRUE)[1]
  estimate <- cf[trt_row, "Estimate"]
  se <- cf[trt_row, "Std. Error"]

  res <- summarise_fit(estimate, se, Inf, published, nrow(d),
                       nlevels(droplevels(d$SUBJ)))
  res$status <- PARTIAL
  res$df_method <- paste(
    "Wald z. glmmTMB reports no denominator df; its interval uses normal",
    "quantiles, which is the large-sample limit of FDA's t interval and is",
    "narrower at every finite df."
  )
  res$requirements <- list(
    fixed_seq_per_trt = SUPPORTED,
    subject_by_formulation_covariance = SUPPORTED,
    treatment_specific_residuals = SUPPORTED,
    satterthwaite_df = NOT_SUPPORTED
  )
  res$why_not_an_oracle <- paste(
    "Meets requirements 1-3 and cannot meet 4. A Wald interval is not a",
    "Satterthwaite t interval, and the difference is largest exactly where BE",
    "decisions are closest."
  )
  res
}

# ------------------------------------------------------------------- main ---

datasets <- jsonlite::fromJSON(data_path, simplifyDataFrame = TRUE)

environment_info <- list(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  nlme = version_of("nlme"),
  lme4 = version_of("lme4"),
  lmerTest = version_of("lmerTest"),
  glmmTMB = version_of("glmmTMB"),
  platform = R.version$platform,
  generated = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
)
cat("R environment:\n")
for (k in names(environment_info)) {
  cat(sprintf("  %-12s %s\n", k, environment_info[[k]]))
}
cat("\n")

results <- list()
for (name in c("data_set_i", "data_set_ii")) {
  rows <- datasets[[name]]
  d <- load_dataset(rows)
  published <- PUBLISHED[[name]]
  cat(sprintf("=== %s: %s\n", name, published$design))
  cat(sprintf("    published Method C: %.2f (%.2f, %.2f)\n",
              published$estimate_percent, published$ci[1], published$ci[2]))

  per_dataset <- list(
    published = published,
    n_observations = nrow(d),
    n_subjects = nlevels(droplevels(d$SUBJ)),
    nlme = fit_nlme(d, published),
    lme4 = fit_lme4(d, published),
    glmmTMB = fit_glmmTMB(d, published)
  )

  for (pkg in c("nlme", "lme4", "glmmTMB")) {
    r <- per_dataset[[pkg]]
    if (identical(r$status, NOT_DETERMINED)) {
      cat(sprintf("    %-9s NOT DETERMINED - %s\n", pkg, r$reason))
      next
    }
    cat(sprintf(
      "    %-9s est %.4f (delta %+.4f)  se %.6f  df %s\n",
      pkg, r$estimate_percent, r$estimate_delta, r$standard_error,
      format(r$reported_df)
    ))
    if (!is.null(r$ci_lower_percent)) {
      cat(sprintf(
        "              CI %.4f, %.4f  (delta %+.4f, %+.4f)\n",
        r$ci_lower_percent, r$ci_upper_percent,
        r$ci_lower_delta, r$ci_upper_delta
      ))
    }
    if (!is.null(r$recovered$recovered_df) && is.finite(r$recovered$recovered_df)) {
      cat(sprintf(
        "              df implied by the published CI and THIS se: %.3f  [%s%s]\n",
        r$recovered$recovered_df,
        if (isTRUE(r$recovered$well_conditioned)) "well conditioned"
        else sprintf("ILL CONDITIONED, +-%.0f df per 0.1%% of se",
                     r$recovered$df_shift_per_0.1pct_se),
        if (isTRUE(r$recovered$exceeds_n_observations))
          "; EXCEEDS n_obs, so impossible" else ""
      ))
    }
    if (!is.null(r$cv_within_percent)) {
      cat(sprintf("              within-subject CV%%: %s\n",
                  paste(sprintf("%s=%.2f", names(r$cv_within_percent),
                                unlist(r$cv_within_percent)), collapse = ", ")))
    }
  }
  cat("\n")
  results[[name]] <- per_dataset
}

results[[".environment"]] <- environment_info
results[[".model"]] <- list(
  source = paste(
    "FDA, Statistical Approaches to Establishing Bioequivalence, May 2026,",
    "Appendix C"
  ),
  sas = paste(
    "PROC MIXED; CLASSES SEQ SUBJ PER TRT;",
    "MODEL Y = SEQ PER TRT/ DDFM=SATTERTH;",
    "RANDOM TRT/TYPE=FA0(2) SUB=SUBJ G;",
    "REPEATED/GRP=TRT SUB=SUBJ;",
    "ESTIMATE 'T vs. R' TRT 1 -1/CL ALPHA=0.1;"
  ),
  fda_permitted_alternatives = paste(
    "TYPE=FA0(2) could possibly be replaced by TYPE=CSH or UNR;",
    "DDFM=SATTERTH could possibly be replaced by DDFM=KR2;",
    "alternative software could also be used if same results are generated."
  ),
  comparison_target = paste(
    "EMA/618604/2008 Rev. 13 'Method C', which transcribes this FDA model and",
    "publishes results for two annexed data sets. Neither SE nor denominator",
    "df is published."
  )
)

writeLines(jsonlite::toJSON(results, auto_unbox = TRUE, digits = 15, null = "null"),
           out_path)
cat(sprintf("wrote %s\n", out_path))
