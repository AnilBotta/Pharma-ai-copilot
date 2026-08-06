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

Routing: vercel.json rewrites all of `/api/*` here, and FastAPI already mounts
its router on `/api`, so the public paths are unchanged from local development.
Nothing in the Next.js app claims `/api`, so there is no collision.
"""

from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402  (path setup must precede the import)

__all__ = ["app"]
