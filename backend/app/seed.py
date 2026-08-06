"""Seed the demo project.

Creates "Peptide Depot Delivery Feasibility Assessment" for a given user, with
the research question and parameters only.

It seeds **no results**. There are no pre-baked findings, no sample report and
no example citations, because a demo that ships with invented sources is the
exact defect this system was rebuilt to remove. Running the seeded project
performs a real search against whatever providers are configured, and produces
whatever those providers actually return - including nothing.

    python -m app.seed --email you@example.com
    python -m app.seed --email you@example.com --start
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app import db
from app.config import get_settings
from app.repository import Repository

PROJECT_NAME = "Peptide Depot Delivery Feasibility Assessment"

RESEARCH_QUESTION = (
    "Evaluate the scientific feasibility, patent landscape, critical quality "
    "attributes, formulation-development pathway, analytical strategy, "
    "nonclinical risks, and stage-gate development plan for a sustained-release "
    "depot injection of a therapeutic peptide using carbon nanotube-based "
    "delivery technology."
)

RUN_PARAMETERS = {
    "molecule": "Therapeutic peptide",
    "dosage_form": "Sustained-release depot injection",
    "route_of_administration": "Subcutaneous",
    "delivery_technology": "Carbon nanotube-based carrier",
    "development_stage": "Discovery",
    "jurisdictions": ["EP", "US", "WO"],
    "date_from": 2010,
    "max_results": 40,
}


async def seed(email: str, *, start_run: bool) -> int:
    settings = get_settings()
    pool = await db.create_pool(settings)
    repository = Repository(pool)

    try:
        async with pool.acquire() as conn:
            user_id = await conn.fetchval(
                "select id from auth.users where lower(email) = lower($1)", email
            )

        if user_id is None:
            print(
                f"No user found with email {email!r}.\n"
                "Create an account through the web app first, then re-run this.",
                file=sys.stderr,
            )
            return 1

        user_id = str(user_id)

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "select id from public.projects where user_id = $1 and name = $2",
                user_id,
                PROJECT_NAME,
            )

        if existing:
            project_id = str(existing["id"])
            print(f"Demo project already exists: {project_id}")
        else:
            project = await repository.create_project(
                user_id,
                name=PROJECT_NAME,
                description=(
                    "Shipped demo project. Contains a research question and "
                    "parameters only - no pre-baked results. Running it performs "
                    "a real search against the configured providers."
                ),
                code="PDD-001",
                molecule="Therapeutic peptide",
                is_seed=True,
            )
            project_id = str(project["id"])
            print(f"Created demo project: {project_id}")

        print(f"\nResearch question:\n  {RESEARCH_QUESTION}\n")

        if not start_run:
            print(
                "No run was started. Open the app, choose this project on the "
                "New Research page, and submit.\n"
                "Or re-run this with --start to queue it now."
            )
            return 0

        run = await repository.create_run(
            user_id,
            project_id,
            {"original_question": RESEARCH_QUESTION, **RUN_PARAMETERS},
        )
        print(f"Queued run {run['id']}")
        print("Start the worker to execute it:  python -m app.worker")
        return 0

    finally:
        await db.close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo research project.")
    parser.add_argument(
        "--email",
        required=True,
        help="Email of an existing account. Sign up through the web app first.",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Queue a research run immediately. Consumes API quota and tokens.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(seed(args.email, start_run=args.start)))


if __name__ == "__main__":
    main()
