"""Vercel entrypoint for the FastAPI application.

Vercel builds every file under `/api` into a Serverless Function chosen by
extension, so this module is what `.py` requests land on. It contains no logic
of its own: the application is the same `app` that `uvicorn app.main:app` serves
locally, and the two must not be allowed to drift.

`backend/` is added to the import path rather than the package being moved,
because the backend is also run directly (`python -m app.worker`, `pytest`,
`python -m app.pdp_admin`) and those entry points expect it where it is. The
directory is pulled into the deployment bundle by `includeFiles` in
vercel.json - without that this import succeeds locally and fails in the cloud.

`be-stats/src` is on the path for the same reason and with a sharper edge: it
is installed editable in the development venv, so every local run and every
test resolves it, while the deployment had no copy of it at all. The failure
mode is the one this file's neighbours warn about - fine locally, dead in the
cloud - and it took out every API route rather than one feature.

Routing: vercel.json rewrites all of `/api/*` here, and FastAPI already mounts
its router on `/api`, so the public paths are unchanged from local development.
Nothing in the Next.js app claims `/api`, so there is no collision.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

#: be-stats is a LOCAL package, installed editable for development and never
#: published, so pip cannot bring it into the bundle from requirements.txt. Its
#: source has to be shipped by `includeFiles` and put on the path here.
#:
#: `app.sas_validation.program` imports `be_stats.replicate_abe.APPENDIX_C_MODEL`
#: at module scope, and `app.main` imports the sas_validation package, so a
#: missing be-stats does not degrade one feature - it stops `from app.main
#: import app` outright and EVERY /api route returns 500. That is precisely
#: what happened in production: 27 requests, 27 fives, across the dashboard,
#: runs, programmes and SAS endpoints alike.
BE_STATS = ROOT / "be-stats" / "src"

for path in (BACKEND, BE_STATS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app  # noqa: E402  (path setup must precede the import)

__all__ = ["app"]
