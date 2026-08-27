# External validation environment for be-stats.
#
# NOT a runtime image. `be_stats` depends on scipy and nothing else, and must
# never depend on R. This image exists so that a tier-3 cross-check can be run
# reproducibly by anyone, rather than against whatever R happens to be on a
# developer's machine.
#
#   docker build -t be-stats-validation validation/external
#   docker run --rm -v "$PWD:/work" be-stats-validation
#
# STATUS: this file has never been built. Neither Docker nor R was available
# where it was written. It is a declaration of the environment, checked for
# syntax by eye and not by a build. Treat the first build as part of the work,
# not as a formality - see environment.lock.json.

# Pinned by digest-bearing tag rather than `latest`: the point of the image is
# that two runs a year apart resolve the same PowerTOST.
FROM rocker/r-ver:4.5.1

# A dated Posit Package Manager snapshot rather than live CRAN. Live CRAN gives
# whatever version exists on the day, which is exactly what pinning is for.
ENV CRAN_SNAPSHOT=https://packagemanager.posit.co/cran/2025-10-01

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        libcurl4-openssl-dev \
        libssl-dev \
        libxml2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY install_r_packages.R /tmp/install_r_packages.R
RUN Rscript /tmp/install_r_packages.R

# The Python side. `--break-system-packages` is deliberate in a throwaway
# validation container; a venv here would add a layer of indirection with
# nothing to isolate from.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
        "scipy>=1.11" \
        "pytest>=8"

WORKDIR /work
ENV PYTHONPATH=/work/be-stats/src

# Default: run the whole comparison and fail the container if anything FAILs.
# `--require-r` turns a missing R into a non-zero exit rather than a SKIPPED
# row, because inside this image a missing R is a broken image.
CMD ["python3", "be-stats/validation/external/harness.py", \
     "--require-r", \
     "--json-out", "be-stats/validation/external/report.json", \
     "--text-out", "be-stats/validation/external/report.txt"]
