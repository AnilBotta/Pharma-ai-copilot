"""Administrative actions that deliberately have no HTTP endpoint.

Two things this module does cannot be done from the web application, and that is
the design rather than an omission:

APPROVING A TEMPLATE. Seeded stage-gate content is scaffolding. Which
requirements are genuinely mandatory for a given product is domain knowledge
that has to come from an organisation's scientific, quality and regulatory
people. The schema refuses to activate a template without a recorded human
approval, and there is no "approve" button, because a button is exactly how that
review turns into a formality. Someone has to run this, name themselves, and say
what they reviewed.

GRANTING ROLES. Role grants decide who may approve work and who may pass a gate.
A self-service endpoint for them would let a user grant themselves approval
authority, which would empty segregation of duties of meaning. Until an identity
provider drives this (Phase I), grants are made here by someone with database
access.

Both actions write to the append-only audit trail.

    python -m app.pdp_admin list-templates
    python -m app.pdp_admin approve-template --key default_pdp \
        --email you@example.com --note "Reviewed with QA and Regulatory, 2026-08-06."
    python -m app.pdp_admin grant-role --email you@example.com --role gate_committee_member
    python -m app.pdp_admin who --email you@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

from app.config import get_settings


async def _connect() -> asyncpg.Connection:
    settings = get_settings()
    return await asyncpg.connect(str(settings.database_url), statement_cache_size=0)


async def _user_id(conn: asyncpg.Connection, email: str) -> str:
    row = await conn.fetchrow("select id from auth.users where email = $1", email)
    if row is None:
        raise SystemExit(
            f"No user with email {email!r}. Sign up through the web app first."
        )
    return str(row["id"])


async def list_templates(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        rows = await conn.fetch(
            """
            select t.template_key, t.version, t.name, t.status, t.is_default,
                   t.approved_at,
                   (select count(*) from public.template_stages s
                     where s.template_id = t.id) as stages,
                   (select count(*) from public.template_requirements r
                      join public.template_stages s on s.id = r.template_stage_id
                     where s.template_id = t.id) as requirements
              from public.pdp_templates t
          order by t.template_key, t.version
            """
        )
        if not rows:
            print("No templates. Apply migration 0012 to seed the default one.")
            return 0
        print(f"{'key':<20} {'ver':>3} {'status':<9} {'stages':>6} {'reqs':>5}  name")
        for r in rows:
            print(
                f"{r['template_key']:<20} {r['version']:>3} {r['status']:<9} "
                f"{r['stages']:>6} {r['requirements']:>5}  {r['name']}"
            )
        return 0
    finally:
        await conn.close()


async def approve_template(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        user_id = await _user_id(conn, args.email)

        template = await conn.fetchrow(
            """
            select * from public.pdp_templates
             where template_key = $1
          order by version desc limit 1
            """,
            args.key,
        )
        if template is None:
            raise SystemExit(f"No template with key {args.key!r}.")
        if template["status"] == "active":
            print(f"{args.key} v{template['version']} is already active.")
            return 0

        print(f"\nTemplate:     {template['name']}")
        print(f"Version:      {template['version']}")
        count = await conn.fetchval(
            """
            select count(*) from public.template_requirements r
              join public.template_stages s on s.id = r.template_stage_id
             where s.template_id = $1
            """,
            template["id"],
        )
        print(f"Requirements: {count}")
        print(
            "\nActivating this template makes it instantiable against real "
            "programmes.\nYou are recording that your organisation has reviewed "
            "its requirements,\nmandatory flags, weights and acceptance criteria "
            "and accepts them.\nThis is not regulatory advice and the system does "
            "not verify it.\n"
        )

        if not args.yes:
            # Off the event loop: a blocking read here would stall the driver's
            # connection keepalives while the operator reads the warning above.
            answer = (await asyncio.to_thread(
                input, "Type the template key to confirm: "
            )).strip()
            if answer != args.key:
                print("Not confirmed. Nothing changed.")
                return 1

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                update public.pdp_templates
                   set status = 'active',
                       approved_by = $2,
                       approved_at = now(),
                       approval_note = $3,
                       is_default = coalesce($4, is_default)
                 where id = $1
                returning template_key, version, status
                """,
                template["id"], user_id, args.note, args.default or None,
            )
            await conn.fetchval(
                """
                select private.record_audit_event(
                    p_action        => 'pdp.template.approved',
                    p_entity_type   => 'pdp_template',
                    p_entity_id     => $1,
                    p_actor_user_id => $2,
                    p_new           => $3::jsonb,
                    p_reason        => $4,
                    p_source        => 'api'
                )
                """,
                str(template["id"]), user_id,
                f'{{"template_key": "{args.key}", "version": {template["version"]}, '
                f'"status": "active"}}',
                args.note,
            )

        print(f"\nActivated {row['template_key']} v{row['version']}.")
        print("Recorded in audit_events against your user id.")
        return 0
    finally:
        await conn.close()


async def grant_role(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        user_id = await _user_id(conn, args.email)

        role = await conn.fetchrow(
            "select * from public.roles where key = $1", args.role
        )
        if role is None:
            keys = await conn.fetch("select key from public.roles order by rank")
            raise SystemExit(
                f"No role {args.role!r}. Available: "
                + ", ".join(r["key"] for r in keys)
            )

        if args.project:
            owns = await conn.fetchval(
                "select 1 from public.projects where id = $1", args.project
            )
            if not owns:
                raise SystemExit(f"No project {args.project}.")

        async with conn.transaction():
            await conn.execute(
                """
                insert into public.user_roles (user_id, role_id, project_id)
                values ($1, $2, $3)
                on conflict do nothing
                """,
                user_id, role["id"], args.project,
            )
            await conn.fetchval(
                """
                select private.record_audit_event(
                    p_action        => 'pdp.role.granted',
                    p_entity_type   => 'user_role',
                    p_entity_id     => $1,
                    p_actor_user_id => $2,
                    p_project_id    => $3,
                    p_new           => $4::jsonb,
                    p_source        => 'api'
                )
                """,
                user_id, user_id, args.project,
                f'{{"role": "{args.role}", "scope": '
                f'"{args.project or "global"}"}}',
            )

        scope = f"project {args.project}" if args.project else "all projects"
        print(f"Granted '{role['name']}' to {args.email} on {scope}.")
        if role["can_approve"]:
            print("  may approve requirements")
        if role["can_gate"]:
            print("  may record gate decisions")
        if role["is_portfolio_wide"]:
            print("  sees every project in the portfolio")
        print(
            "\nSegregation of duties still applies: this user cannot approve a "
            "requirement\nthey own or whose acceptance criteria they confirmed."
        )
        return 0
    finally:
        await conn.close()


async def who(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        user_id = await _user_id(conn, args.email)
        rows = await conn.fetch(
            """
            select r.key, r.name, r.can_approve, r.can_gate, r.is_portfolio_wide,
                   ur.project_id, p.name as project_name, ur.expires_at
              from public.user_roles ur
              join public.roles r on r.id = ur.role_id
         left join public.projects p on p.id = ur.project_id
             where ur.user_id = $1
          order by r.rank desc
            """,
            user_id,
        )
        print(f"{args.email} ({user_id})")
        if not rows:
            print("  no role grants — can act only on projects they own")
            return 0
        for r in rows:
            scope = r["project_name"] or "all projects"
            flags = ", ".join(
                f for f, on in (
                    ("approve", r["can_approve"]),
                    ("gate", r["can_gate"]),
                    ("portfolio-wide", r["is_portfolio_wide"]),
                ) if on
            ) or "no special authority"
            print(f"  {r['name']:<24} on {scope:<28} [{flags}]")
        return 0
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.pdp_admin",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-templates", help="Show every template and its status.")

    p = sub.add_parser("approve-template", help="Record approval and activate a template.")
    p.add_argument("--key", required=True, help="Template key, e.g. default_pdp.")
    p.add_argument("--email", required=True, help="Who is approving. Must be a real user.")
    p.add_argument("--note", help="What was reviewed, and with whom.")
    p.add_argument("--default", action="store_true", help="Also make it the default.")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    p = sub.add_parser("grant-role", help="Grant a role to a user.")
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, help="Role key, e.g. gate_committee_member.")
    p.add_argument("--project", help="Scope to one project id. Omit for a global grant.")

    p = sub.add_parser("who", help="Show a user's role grants.")
    p.add_argument("--email", required=True)

    args = parser.parse_args(argv)
    handler = {
        "list-templates": list_templates,
        "approve-template": approve_template,
        "grant-role": grant_role,
        "who": who,
    }[args.command]

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
