#!/usr/bin/env Rscript
#
# Install the R side at pinned versions, and refuse if a pin cannot be met.
#
# `install.packages` without a version is how an oracle silently becomes a
# different oracle. Everything here is installed from a dated snapshot and then
# checked, so a mismatch stops the image build rather than surfacing months
# later as an unexplained tolerance failure.

options(
  repos = c(CRAN = Sys.getenv("CRAN_SNAPSHOT",
                              "https://packagemanager.posit.co/cran/2025-10-01")),
  warn = 2  # warnings are errors: a failed install must not scroll past
)

# ---------------------------------------------------------------- what and why

# Only what `run_powertost.R` actually calls. Everything else arrives as a
# dependency or does not arrive at all.
direct <- c("PowerTOST", "jsonlite")

# `dependencies = c("Depends", "Imports")`, NOT `TRUE`.
#
# `TRUE` also installs Suggests, and the first build of this image failed for
# exactly that reason: PowerTOST suggests `emmeans`, whose dependency chain
# reaches `s2`, which needs Abseil C++ and cmake to compile. Three minutes of
# build time to fail on a geospatial library that has nothing to do with
# bioequivalence.
#
# Suggests are for a package's own vignettes and examples. Running PowerTOST's
# power functions needs Depends and Imports, which for PowerTOST are mvtnorm,
# cubature and base packages - all light and all pure enough to build.
install.packages(direct, dependencies = c("Depends", "Imports"))

# ------------------------------------------------------------ what is enforced

# Two tiers, on purpose.
#
# ENFORCED: the packages whose version can change a NUMBER. PowerTOST is the
# oracle - a different version is a different oracle, and the whole point of
# this image is that two runs a year apart compare against the same one.
#
# RECORDED: everything else. Their versions are resolved by the snapshot and
# reported into the results JSON, so the report captures the environment that
# actually ran. Pinning them in this file as well would mean a build failing
# over a transitive patch bump that cannot affect a result - a check that
# creates noise rather than confidence, and that someone would eventually
# relax for the wrong reason.
enforced <- list(PowerTOST = "1.5-7")

problems <- character(0)
for (pkg in names(enforced)) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    problems <- c(problems, sprintf("%s is not installed", pkg))
    next
  }
  got <- as.character(utils::packageVersion(pkg))
  want <- enforced[[pkg]]
  if (!identical(got, want)) {
    problems <- c(problems, sprintf("%s: wanted %s, got %s", pkg, want, got))
  }
}

if (length(problems) > 0L) {
  stop(
    paste0(
      "the pinned oracle could not be satisfied:\n  ",
      paste(problems, collapse = "\n  "),
      "\n\nFix the snapshot date in CRAN_SNAPSHOT, or update ",
      "environment.lock.json and this file together and deliberately. ",
      "Do not relax the check: an unpinned oracle is not an oracle."
    ),
    call. = FALSE
  )
}

# ------------------------------------------------------------------- reporting

relevant <- unique(c(direct, "mvtnorm", "cubature"))
cat("R environment as resolved:\n")
cat(sprintf("  %-12s %s\n", "R", paste(R.version$major, R.version$minor, sep = ".")))
for (pkg in relevant) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    marker <- if (pkg %in% names(enforced)) "  [pinned]" else ""
    cat(sprintf("  %-12s %s%s\n", pkg,
                as.character(utils::packageVersion(pkg)), marker))
  } else {
    cat(sprintf("  %-12s ABSENT\n", pkg))
  }
}
