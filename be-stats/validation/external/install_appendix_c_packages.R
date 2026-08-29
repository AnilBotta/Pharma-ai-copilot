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

candidates <- c("lme4", "lmerTest", "glmmTMB")

manifest <- list()
for (pkg in candidates) {
  cat(sprintf("--- attempting %s\n", pkg))
  ok <- tryCatch(
    {
      # dependencies = c("Depends", "Imports") for the reason recorded in
      # install_r_packages.R: Suggests dragged in a geospatial library and
      # cost three minutes of build time on the first CI attempt.
      install.packages(pkg, dependencies = c("Depends", "Imports"))
      requireNamespace(pkg, quietly = TRUE)
    },
    error = function(e) {
      cat(sprintf("    failed: %s\n", conditionMessage(e)))
      FALSE
    },
    warning = function(w) {
      cat(sprintf("    warning: %s\n", conditionMessage(w)))
      requireNamespace(pkg, quietly = TRUE)
    }
  )
  manifest[[pkg]] <- if (isTRUE(ok)) {
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
