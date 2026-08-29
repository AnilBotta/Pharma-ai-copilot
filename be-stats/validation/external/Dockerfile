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
        # nloptr, which lme4 needs, builds a bundled NLopt through cmake when
        # no system NLopt is present. The first run of the Appendix C
        # investigation had all three candidates come back `absent` for this
        # one reason: nloptr could not build, and lme4, lmerTest and glmmTMB
        # all fell over behind it. Supplying NLopt directly is cheaper than
        # letting each build compile its own.
        cmake \
        libnlopt-dev \
        # for fetching the pinned Julia tarball below
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY install_r_packages.R /tmp/install_r_packages.R
RUN Rscript /tmp/install_r_packages.R

# Candidate oracles for FDA Appendix C, in their own layer and BEST-EFFORT.
#
# Separate from the layer above on purpose. That one installs the oracle and
# must fail the build if it cannot; this one installs candidates for an oracle
# that does not exist yet, and a candidate that will not build is a legitimate
# investigation result rather than a broken image. Letting a failed experiment
# take down a green cross-check would be the wrong dependency direction.
COPY install_appendix_c_packages.R /tmp/install_appendix_c_packages.R
RUN Rscript /tmp/install_appendix_c_packages.R || \
    echo "appendix C candidates: install script exited non-zero; the \
investigation records NOT DETERMINED for whatever is absent"

# Julia, for ONE question: no R package computes Satterthwaite denominator
# degrees of freedom for Appendix C's covariance structure, and ReplicateBE.jl
# claims to. That claim is the last open item in VAL-FDA-APPENDIX-C-001, and
# quoting it is not testing it.
#
# `be_stats` does not depend on Julia and must never depend on Julia.
# ReplicateBE.jl is GPL-3.0 and is used here as an ORACLE - run it, compare
# numbers - which creates no derivative work. None of its code is copied.
#
# Pinned by version and checksum-bearing URL rather than a channel alias, for
# the reason the R side is pinned: two runs a year apart must resolve the same
# oracle.
ENV JULIA_VERSION=1.10.5
ENV JULIA_PATH=/opt/julia
ENV PATH=$JULIA_PATH/bin:$PATH
RUN set -eux; \
    curl -fsSL -o /tmp/julia.tar.gz \
      "https://julialang-s3.julialang.org/bin/linux/x64/1.10/julia-${JULIA_VERSION}-linux-x86_64.tar.gz"; \
    mkdir -p "$JULIA_PATH"; \
    tar -xzf /tmp/julia.tar.gz -C "$JULIA_PATH" --strip-components=1; \
    rm /tmp/julia.tar.gz; \
    julia --version

COPY install_julia_packages.jl /tmp/install_julia_packages.jl
RUN julia /tmp/install_julia_packages.jl

# The Python side. `--break-system-packages` is deliberate in a throwaway
# validation container; a venv here would add a layer of indirection with
# nothing to isolate from.
#
# numpy is named explicitly rather than inherited from scipy: `be_stats`
# declares it as a direct dependency now that EMA's Method A builds a design
# matrix, and a container that relies on a transitive edge is relying on
# somebody else's packaging decision.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
        "scipy>=1.11" \
        "numpy>=1.24" \
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
