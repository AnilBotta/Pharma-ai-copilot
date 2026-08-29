#!/usr/bin/env Rscript
#
# Candidate oracles for FDA Appendix C. INSTALLED BEST-EFFORT, ON PURPOSE.
#
# WHY THIS DOES NOT STOP ON FAILURE, WHEN install_r_packages.R DOES
#
# `install_r_packages.R` installs the ORACLE. A missing or wrong-version
# PowerTOST means the tier-3 comparison cannot be trusted, so it stops the
# build - an unpinned oracle is not an oracle.
#
# This script installs CANDIDATES for an oracle that does not exist yet. Their
# job is to be evaluated, and "it would not build" is a legitimate evaluation
# result: the investigation records NOT DETERMINED for anything absent and
# carries on. Making an exploratory package able to break the validation image
# would mean a failed experiment could take down a green cross-check, which is
# the wrong dependency direction entirely.
#
# So: every install is wrapped, the manifest records what actually arrived, and
# `investigate_appendix_c.R` reads that manifest rather than assuming.
#
# nlme is NOT installed here. It ships with R as a recommended package, which
# is itself worth knowing: the most promising candidate is the one with no
# supply-chain risk at all.

options(
  repos = c(CRAN = Sys.getenv("CRAN_SNAPSHOT",
                              "https://packagemanager.posit.co/cran/2025-10-01"))
)

# NEVER PUT A `warning` HANDLER ON install.packages.
#
# This is what went wrong on the first two CI attempts and it is worth
# recording, because the failure looked like a missing system library and was
# not.
#
# `tryCatch(install.packages(...), warning = ...)` UNWINDS at the point the
# first warning is signalled. install.packages does not error when a package
# fails to build - it warns, once per failure, and carries on. So a warning
# handler aborts the whole call at the first stumble, and every package that
# had not yet been reached is silently never attempted. The visible symptom was
# "dependency 'RcppEigen' is not available for package 'lme4'": RcppEigen was
# not broken, it was never installed, because an earlier warning had already
# unwound the call.
#
# suppressWarnings lets it run to completion. Availability is then checked
# afterwards, which is the only claim worth making anyway - "install.packages
# did not warn" is not the same as "the package is usable".
#
# The candidates are installed in ONE call so install.packages resolves the
# dependency order itself. Naming RcppEigen and TMB explicitly is belt and
# braces: they are the two heavy compiles in this chain, and naming them makes
# a failure in either attributable rather than inferred.
candidates <- c("lme4", "lmerTest", "glmmTMB")
build_chain <- c("RcppEigen", "TMB")

cat("--- installing candidates and their heavy dependencies\n")
tryCatch(
  suppressWarnings(
    install.packages(
      c(build_chain, candidates),
      # dependencies = c("Depends", "Imports") for the reason recorded in
      # install_r_packages.R: Suggests dragged in a geospatial library and
      # cost three minutes of build time on the first CI attempt.
      dependencies = c("Depends", "Imports")
    )
  ),
  error = function(e) cat(sprintf("    install.packages errored: %s\n",
                                  conditionMessage(e)))
)

manifest <- list()
for (pkg in c(build_chain, candidates)) {
  manifest[[pkg]] <- if (requireNamespace(pkg, quietly = TRUE)) {
    as.character(utils::packageVersion(pkg))
  } else {
    "absent"
  }
}

# nlme ships with R. Recorded rather than installed.
manifest[["nlme"]] <- if (requireNamespace("nlme", quietly = TRUE)) {
  as.character(utils::packageVersion("nlme"))
} else {
  "absent"
}

cat("\nAppendix C candidate oracles as resolved:\n")
for (pkg in names(manifest)) {
  cat(sprintf("  %-10s %s\n", pkg, manifest[[pkg]]))
}

writeLines(
  jsonlite::toJSON(manifest, auto_unbox = TRUE),
  "/usr/local/lib/R/site-library/appendix_c_manifest.json"
)
cat("\nmanifest written\n")
