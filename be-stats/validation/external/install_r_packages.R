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

required <- list(
  jsonlite  = "2.0.0",
  mvtnorm   = "1.3-3",
  cubature  = "2.1.4",
  PowerTOST = "1.5-7"
)

install.packages(names(required), dependencies = TRUE)

problems <- character(0)
for (pkg in names(required)) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    problems <- c(problems, sprintf("%s is not installed", pkg))
    next
  }
  got <- as.character(utils::packageVersion(pkg))
  want <- required[[pkg]]
  if (!identical(got, want)) {
    problems <- c(problems, sprintf("%s: wanted %s, got %s", pkg, want, got))
  }
}

if (length(problems) > 0L) {
  stop(
    paste0(
      "pinned R packages could not be satisfied:\n  ",
      paste(problems, collapse = "\n  "),
      "\n\nFix the snapshot date in CRAN_SNAPSHOT, or update ",
      "environment.lock.json and this file together and deliberately. ",
      "Do not relax the check."
    ),
    call. = FALSE
  )
}

cat("R package versions verified against the pins:\n")
for (pkg in names(required)) {
  cat(sprintf("  %-12s %s\n", pkg, as.character(utils::packageVersion(pkg))))
}
