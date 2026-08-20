"""Database access for the PDP Operations & Stage-Gate Guardian module.

Read `app/repository.py` first: the same rule applies here. The backend connects
with the service role, which bypasses RLS, so every method takes the verified
user id and checks access explicitly. RLS is the second line of defence.

WHAT IS DELIBERATELY ABSENT
---------------------------
There is no method that marks a requirement complete, sets a status, or writes a
readiness percentage. None can be added later without someone noticing, because
the columns do not exist: `gate_requirements` has no completion column at all.
Satisfaction is computed by ``private.requirement_is_satisfied()`` on every read
from evidence, acceptance, approval and dependencies.

A caller who wants a requirement to go green must attach evidence, have a person
confirm the acceptance criteria, and have a *different* person with an approver
role approve it. That is the only path, and it is the same path for a human and
for an agent.

AUTHORISATION
-------------
Access is resolved by ``private.user_capabilities()``, the same predicate the
RLS policies use. It is asked once per request and the answer is passed down,
so a method cannot accidentally run unchecked.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import asyncpg

from app.api.serialise import jsonable

logger = logging.getLogger(__name__)


class NotFound(Exception):
    """Row does not exist, or the caller may not see it.

    The two are not distinguished. Telling a caller that a project exists but is
    someone else's leaks its existence.
    """


class Forbidden(Exception):
    """The caller may see this project but may not take this action."""


class Conflict(Exception):
    """The action is refused because of the current state of the record."""


#: Postgres error code raised by the segregation-of-duties and independent-review
#: triggers. Mapped to Forbidden so the database's rule reaches the user intact.
INSUFFICIENT_PRIVILEGE = "42501"


class Capabilities:
    """What one user may do on one project."""

    __slots__ = (
        "can_access",
        "can_approve",
        "can_gate",
        "is_portfolio_wide",
        "is_project_owner",
        "project_id",
        "role_keys",
        "user_id",
    )

    def __init__(self, user_id: str, project_id: str, row: Any) -> None:
        self.user_id = user_id
        self.project_id = project_id
        self.can_access = bool(row["can_access"])
        self.can_approve = bool(row["can_approve"])
        self.can_gate = bool(row["can_gate"])
        self.is_portfolio_wide = bool(row["is_portfolio_wide"])
        self.is_project_owner = bool(row["is_project_owner"])
        self.role_keys: list[str] = list(row["role_keys"] or [])

    @property
    def can_administer(self) -> bool:
        """May restructure the programme: instantiate a template, edit stages.

        The project owner qualifies because a pilot has no separate
        administrator; in a deployed organisation the role grants carry it.
        """
        return (
            self.is_project_owner
            or "system_administrator" in self.role_keys
            or "project_manager" in self.role_keys
        )

    def as_dict(self) -> dict:
        return {
            "can_access": self.can_access,
            "can_approve": self.can_approve,
            "can_gate": self.can_gate,
            "can_administer": self.can_administer,
            "is_portfolio_wide": self.is_portfolio_wide,
            "is_project_owner": self.is_project_owner,
            "role_keys": self.role_keys,
        }


class PdpRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # ------------------------------------------------------------- access ---

    async def capabilities(self, user_id: str, project_id: str) -> Capabilities:
        """Resolve what this user may do on this project, or raise NotFound."""
        async with self._pool.acquire() as conn:
            return await self._capabilities(conn, user_id, project_id)

    async def _capabilities(self, conn, user_id: str, project_id: str) -> Capabilities:
        exists = await conn.fetchval(
            "select 1 from public.projects where id = $1", project_id
        )
        row = await conn.fetchrow(
            "select * from private.user_capabilities($1, $2)", user_id, project_id
        )
        caps = Capabilities(user_id, project_id, row)
        if not exists or not caps.can_access:
            raise NotFound(f"Project {project_id} not found.")
        return caps

    async def _capabilities_for_stage(self, conn, user_id: str, stage_id: str):
        project_id = await conn.fetchval(
            "select project_id from public.project_stages where id = $1", stage_id
        )
        if project_id is None:
            raise NotFound(f"Stage {stage_id} not found.")
        return str(project_id), await self._capabilities(conn, user_id, str(project_id))

    async def _capabilities_for_requirement(self, conn, user_id: str, requirement_id: str):
        row = await conn.fetchrow(
            "select * from public.gate_requirements where id = $1", requirement_id
        )
        if row is None:
            raise NotFound(f"Requirement {requirement_id} not found.")
        caps = await self._capabilities(conn, user_id, str(row["project_id"]))
        return dict(row), caps

    # -------------------------------------------------------------- audit ---

    async def _audit(
        self,
        conn,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        project_id: str | None = None,
        previous: dict | None = None,
        new: dict | None = None,
        reason: str | None = None,
        actor_role: str | None = None,
    ) -> None:
        """Record a state change. Failure to audit fails the operation.

        Deliberately not best-effort: an unrecorded state change in a
        stage-gate system is worse than a refused one, because the record is the
        only thing a gate decision can later be defended with.

        `entity_id` is coerced because the column is text while every id in this
        module is a uuid. An HTTP caller supplies a string and never notices;
        an internal caller passing the UUID it just read would lose the audit
        entry for a change that did happen.

        `p_actor_agent` is read from `app.acting_agent` inside the query rather
        than threaded through Python. `audit_events.actor_agent` has existed
        since 0007, described there as making accountability unambiguous, and
        nothing ever populated it - every agent action was recorded looking
        exactly like a person's. Taking it from the same transaction-local
        setting that migration 0022's triggers read means one source of truth
        for "an agent is acting", and every call site is covered without any of
        them having to remember.
        """
        await conn.fetchval(
            """
            select private.record_audit_event(
                p_action        => $1,
                p_entity_type   => $2,
                p_entity_id     => $3,
                p_actor_user_id => $4,
                p_actor_role    => $5,
                p_project_id    => $6,
                p_previous      => $7,
                p_new           => $8,
                p_reason        => $9,
                p_actor_agent   => nullif(current_setting('app.acting_agent', true), ''),
                p_source        => 'api'
            )
            """,
            action, entity_type, str(entity_id), actor, actor_role,
            project_id,
            jsonable(previous) if previous is not None else None,
            jsonable(new) if new is not None else None,
            reason,
        )

    # ---------------------------------------------------------- templates ---

    async def list_templates(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select t.*,
                       (select count(*) from public.template_stages s
                         where s.template_id = t.id) as stage_count,
                       (select count(*) from public.template_requirements r
                          join public.template_stages s on s.id = r.template_stage_id
                         where s.template_id = t.id) as requirement_count
                  from public.pdp_templates t
                 where t.status <> 'archived'
              order by t.is_default desc, t.name, t.version desc
                """
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------ instantiation ---

    async def instantiate(
        self,
        user_id: str,
        project_id: str,
        *,
        template_id: str,
        start_date: date | None = None,
    ) -> dict:
        """Copy a template version into the project as its own stages.

        The copy is the point. Once instantiated, the project's requirements are
        its own: a later edit to the template cannot change what a gate demands
        halfway through a programme. Each row keeps a pointer back to the
        template row it came from so a migration to a newer version can be
        offered, diffed, and accepted by a person.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            caps = await self._capabilities(conn, user_id, project_id)
            if not caps.can_administer:
                raise Forbidden(
                    "Instantiating a programme requires the project owner, a "
                    "project manager or a system administrator."
                )

            already = await conn.fetchval(
                "select count(*) from public.project_stages where project_id = $1",
                project_id,
            )
            if already:
                raise Conflict(
                    "This project already has stages. Instantiating again would "
                    "discard recorded evidence and approvals."
                )

            template = await conn.fetchrow(
                "select * from public.pdp_templates where id = $1", template_id
            )
            if template is None:
                raise NotFound(f"Template {template_id} not found.")
            if template["status"] != "active":
                # The schema blocks activation without a recorded approval; this
                # blocks *use* of anything not activated. Seeded content is
                # scaffolding until the organisation approves it.
                raise Conflict(
                    f"Template '{template['name']}' is {template['status']}. Only an "
                    "active template that has been approved by the organisation "
                    "may be instantiated."
                )

            stages = await conn.fetch(
                """
                select * from public.template_stages
                 where template_id = $1 order by position
                """,
                template_id,
            )
            if not stages:
                raise Conflict("That template has no stages defined.")

            # template requirement id -> new gate requirement id, so dependency
            # edges can be remapped after every row exists.
            requirement_map: dict[str, str] = {}
            created_stages: list[dict] = []

            for stage in stages:
                new_stage = await conn.fetchrow(
                    """
                    insert into public.project_stages (
                        project_id, template_stage_id, position, key, name,
                        description, gate_question, exit_criteria,
                        unattended_after_days
                    ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    returning *
                    """,
                    project_id, stage["id"], stage["position"], stage["key"],
                    stage["name"], stage["description"], stage["gate_question"],
                    stage["exit_criteria"],
                    # Copied like every other stage field, so a later template
                    # edit cannot change how long a running programme's gate may
                    # sit before it is reported. Null here means the gate
                    # inherits the system default, which is the ordinary case.
                    stage["unattended_after_days"],
                )
                created_stages.append(dict(new_stage))

                requirements = await conn.fetch(
                    """
                    select * from public.template_requirements
                     where template_stage_id = $1 order by position, ref_code
                    """,
                    stage["id"],
                )
                for req in requirements:
                    due = None
                    if start_date and req["default_lead_days"] is not None:
                        due = start_date + _days(req["default_lead_days"])

                    new_req = await conn.fetchrow(
                        """
                        insert into public.gate_requirements (
                            project_id, project_stage_id, template_requirement_id,
                            position, ref_code, title, description, guidance,
                            discipline, is_mandatory, weight,
                            required_evidence_type, required_document_type,
                            acceptance_criteria, approver_role_key, due_date
                        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                        returning id
                        """,
                        project_id, new_stage["id"], req["id"], req["position"],
                        req["ref_code"], req["title"], req["description"],
                        req["guidance"], req["discipline"], req["is_mandatory"],
                        req["weight"], req["required_evidence_type"],
                        req["required_document_type"], req["acceptance_criteria"],
                        req["approver_role_key"], due,
                    )
                    requirement_map[str(req["id"])] = str(new_req["id"])

            # Dependencies last: both endpoints must exist, and they may live in
            # different stages.
            edges = await conn.fetch(
                """
                select d.requirement_id, d.depends_on_id
                  from public.template_requirement_dependencies d
                  join public.template_requirements r on r.id = d.requirement_id
                  join public.template_stages s on s.id = r.template_stage_id
                 where s.template_id = $1
                """,
                template_id,
            )
            copied_edges = 0
            for edge in edges:
                src = requirement_map.get(str(edge["requirement_id"]))
                dst = requirement_map.get(str(edge["depends_on_id"]))
                if src and dst:
                    await conn.execute(
                        """
                        insert into public.gate_requirement_dependencies
                            (requirement_id, depends_on_id)
                        values ($1, $2) on conflict do nothing
                        """,
                        src, dst,
                    )
                    copied_edges += 1

            await conn.execute(
                """
                update public.projects
                   set pdp_enabled = true,
                       current_stage_id = $2,
                       planned_start_date = coalesce($3, planned_start_date)
                 where id = $1
                """,
                project_id, created_stages[0]["id"], start_date,
            )

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.project.instantiated",
                entity_type="project",
                entity_id=project_id,
                project_id=project_id,
                new={
                    "template_id": str(template_id),
                    "template_key": template["template_key"],
                    "template_version": template["version"],
                    "stages": len(created_stages),
                    "requirements": len(requirement_map),
                    "dependencies": copied_edges,
                    "start_date": start_date,
                },
                reason="Programme instantiated from an approved template version.",
            )

        return {
            "project_id": project_id,
            "template_id": str(template_id),
            "template_name": template["name"],
            "template_version": template["version"],
            "stages_created": len(created_stages),
            "requirements_created": len(requirement_map),
            "dependencies_created": copied_edges,
        }

    # ------------------------------------------------------------- reads ---

    async def list_programmes(self, user_id: str) -> list[dict]:
        """PDP-enabled projects this user may see, with headline readiness.

        The current stage's percentage is returned together with its blocker
        count. Never the percentage alone: a number without its blockers is the
        exact misreading this module exists to prevent.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select p.id, p.name, p.code, p.description, p.product_type,
                       p.health, p.planned_start_date, p.planned_end_date,
                       p.pdp_enabled, p.current_stage_id,
                       s.id   as current_stage_pk,
                       s.key  as current_stage_key,
                       s.name as current_stage_name,
                       s.position as current_stage_position,
                       s.gate_status as current_gate_status,
                       rd.readiness_pct, rd.is_ready, rd.blocker_count,
                       rd.applicable_count, rd.satisfied_count,
                       (select count(*) from public.project_stages ps
                         where ps.project_id = p.id) as stage_count
                  from public.projects p
             left join public.project_stages s on s.id = p.current_stage_id
             left join lateral private.gate_readiness(s.id) rd on s.id is not null
                 where p.pdp_enabled
                   and p.archived_at is null
                   and private.user_can_access_project($1, p.id)
              order by p.name
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def get_programme(self, user_id: str, project_id: str) -> dict:
        """The project's stages, each with readiness and its blocker count."""
        async with self._pool.acquire() as conn:
            caps = await self._capabilities(conn, user_id, project_id)

            project = await conn.fetchrow(
                "select * from public.projects where id = $1", project_id
            )
            stages = await conn.fetch(
                """
                select s.*,
                       rd.readiness_pct, rd.is_ready, rd.applicable_count,
                       rd.satisfied_count, rd.mandatory_count,
                       rd.mandatory_satisfied, rd.blocker_count,
                       (select count(*) from public.gate_requirements r
                         where r.project_stage_id = s.id) as requirement_count,
                       (select count(*) from public.gate_requirements r
                         where r.project_stage_id = s.id
                           and r.due_date < current_date
                           and not private.requirement_is_satisfied(r.id)
                       ) as overdue_count
                  from public.project_stages s,
                       lateral private.gate_readiness(s.id) rd
                 where s.project_id = $1
              order by s.position
                """,
                project_id,
            )

        return {
            "project": dict(project),
            "stages": [dict(s) for s in stages],
            "capabilities": caps.as_dict(),
        }

    async def get_gate(self, user_id: str, stage_id: str) -> dict:
        """Everything needed to work a gate: requirements, evidence, blockers.

        Readiness and blockers are returned in the same payload by design. A
        client cannot fetch the percentage without also receiving the reasons it
        is not 100, so there is no cheap way to render a misleading number.
        """
        async with self._pool.acquire() as conn:
            project_id, caps = await self._capabilities_for_stage(conn, user_id, stage_id)

            stage = await conn.fetchrow(
                "select * from public.project_stages where id = $1", stage_id
            )
            readiness = await conn.fetchrow(
                "select * from private.gate_readiness($1)", stage_id
            )
            blockers = await conn.fetch(
                "select * from private.gate_blockers($1)", stage_id
            )
            requirements = await conn.fetch(
                """
                select r.*,
                       private.requirement_status(r.id)       as status,
                       private.requirement_is_satisfied(r.id) as is_satisfied,
                       (select count(*) from public.evidence_links e
                         where e.requirement_id = r.id) as evidence_count,
                       coalesce(owner_p.full_name, owner_p.email) as owner_name,
                       coalesce(acceptor_p.full_name, acceptor_p.email)
                         as acceptance_confirmed_by_name,
                       (select json_agg(json_build_object(
                                  'id', d.depends_on_id,
                                  'ref_code', dep.ref_code,
                                  'title', dep.title,
                                  'is_mandatory', dep.is_mandatory,
                                  'is_satisfied', private.requirement_is_satisfied(dep.id))
                               order by dep.position)
                          from public.gate_requirement_dependencies d
                          join public.gate_requirements dep on dep.id = d.depends_on_id
                         where d.requirement_id = r.id) as depends_on
                  from public.gate_requirements r
             left join public.profiles owner_p    on owner_p.id = r.owner_user_id
             left join public.profiles acceptor_p on acceptor_p.id = r.acceptance_confirmed_by
                 where r.project_stage_id = $1
              order by r.position, r.ref_code
                """,
                stage_id,
            )
            evidence = await conn.fetch(
                """
                select e.*,
                       run.status            as research_run_status,
                       run.original_question as research_run_question,
                       cd.document_number    as document_number,
                       cd.title              as document_title,
                       cdv.version_label     as document_version_label,
                       cdv.status            as document_version_status,
                       cdv.storage_url       as document_storage_url,
                       case when e.document_version_id is null then null
                            else private.document_version_is_usable(e.document_version_id)
                       end                   as document_is_usable,
                       coalesce(p.full_name, p.email) as added_by_name
                  from public.evidence_links e
                  join public.gate_requirements r on r.id = e.requirement_id
             left join public.research_runs run on run.id = e.research_run_id
             left join public.controlled_document_versions cdv
                    on cdv.id = e.document_version_id
             left join public.controlled_documents cd on cd.id = cdv.document_id
             left join public.profiles p on p.id = e.added_by
                 where r.project_stage_id = $1
              order by e.created_at
                """,
                stage_id,
            )
            approvals = await conn.fetch(
                """
                select a.*, coalesce(p.full_name, p.email) as approver_name
                  from public.approvals a
                  join public.gate_requirements r on r.id = a.requirement_id
             left join public.profiles p on p.id = a.approver_id
                 where r.project_stage_id = $1
              order by a.approved_at desc
                """,
                stage_id,
            )
            unattended_default = await conn.fetchval(
                "select threshold_days from public.notification_rules "
                "where condition = 'gate_unattended'"
            )

        by_requirement: dict[str, list[dict]] = {}
        for row in evidence:
            by_requirement.setdefault(str(row["requirement_id"]), []).append(dict(row))

        approvals_by_requirement: dict[str, list[dict]] = {}
        for row in approvals:
            approvals_by_requirement.setdefault(
                str(row["requirement_id"]), []
            ).append(dict(row))

        enriched = []
        for req in requirements:
            item = dict(req)
            rid = str(req["id"])
            item["evidence"] = by_requirement.get(rid, [])
            item["approvals"] = approvals_by_requirement.get(rid, [])
            item["current_approval"] = next(
                (
                    a for a in item["approvals"]
                    if a["superseded_at"] is None and a["decision"] == "approved"
                ),
                None,
            )
            enriched.append(item)

        # The effective inactivity threshold, and whether it was chosen here or
        # inherited. Both are sent so the page can say "7 days (system default)"
        # rather than printing a number that looks like somebody picked it -
        # which is the whole reason the column is nullable rather than defaulted.
        stage_row = dict(stage)
        chosen = stage_row.get("unattended_after_days")
        stage_row["unattended_effective_days"] = chosen or unattended_default or 7
        stage_row["unattended_is_inherited"] = chosen is None

        return {
            "project_id": project_id,
            "stage": stage_row,
            "readiness": dict(readiness),
            "blockers": [dict(b) for b in blockers],
            "requirements": enriched,
            "capabilities": caps.as_dict(),
        }

    async def set_unattended_threshold(
        self, user_id: str, stage_id: str, days: int | None, *, reason: str | None = None
    ) -> dict:
        """How long this gate may sit untouched before it is reported.

        `None` clears the override and returns the gate to the system default.
        That is a real choice rather than an absence, so it is audited like any
        other - "who made this gate quieter" is exactly the question somebody
        asks after a stage slips unnoticed.

        Deliberately requires no gate authority. Changing when a reminder fires
        is not a decision about whether a gate may open, and gating it behind
        `can_gate` would put a routine setting out of reach of the people who
        actually run the programme.
        """
        if days is not None and not (1 <= days <= 365):
            raise Conflict(
                f"{days} is not a usable threshold. Choose between 1 and 365 days, "
                "or clear it to inherit the system default."
            )

        async with self._pool.acquire() as conn, conn.transaction():
            project_id, caps = await self._capabilities_for_stage(conn, user_id, stage_id)
            if not caps.can_access:
                raise Forbidden("You do not have access to this programme.")

            before = await conn.fetchval(
                "select unattended_after_days from public.project_stages where id = $1",
                stage_id,
            )
            await conn.execute(
                "update public.project_stages set unattended_after_days = $2 "
                "where id = $1",
                stage_id, days,
            )
            # Recorded against `gate_notification_setting`, NOT `project_stage`.
            #
            # The unattended detector measures activity as the newest audit
            # event touching the stage or its requirements. An event filed under
            # `project_stage` therefore counts as somebody working on the gate -
            # so writing this one there means CONFIGURING THE ALERT SILENCES THE
            # ALERT. Measured: after three threshold changes the gate stopped
            # being reported at all, including when the value was put back.
            #
            # This is the second time the same failure arrived by a different
            # route; the first was `project_stages.updated_at`, which a trigger
            # maintains on every write. An exclusion list would work and would
            # fail silently the first time somebody adds another setting, so the
            # record simply is not filed against the gate. It is still fully
            # audited and still found by stage id.
            await self._audit(
                conn,
                actor=user_id,
                action="gate_notification_setting.unattended_threshold_set",
                entity_type="gate_notification_setting",
                entity_id=stage_id,
                project_id=project_id,
                previous={"unattended_after_days": before},
                new={"unattended_after_days": days},
                reason=reason,
            )
        return await self.get_gate(user_id, stage_id)

    async def _requirement_view(self, conn, requirement_id: str) -> dict:
        """One requirement as the engine now sees it.

        Every mutating method returns this rather than the row it just wrote.
        The difference is not cosmetic: attaching evidence supersedes an
        approval, so the state after a write is frequently not the state the
        write alone would suggest. Returning the stored row would invite a
        client to render something the engine does not agree with.
        """
        row = await conn.fetchrow(
            """
            select r.*,
                   private.requirement_status(r.id)       as status,
                   private.requirement_is_satisfied(r.id) as is_satisfied,
                   (select count(*) from public.evidence_links e
                     where e.requirement_id = r.id) as evidence_count,
                   coalesce(owner_p.full_name, owner_p.email)       as owner_name,
                   coalesce(acceptor_p.full_name, acceptor_p.email) as acceptance_confirmed_by_name
              from public.gate_requirements r
         left join public.profiles owner_p    on owner_p.id = r.owner_user_id
         left join public.profiles acceptor_p on acceptor_p.id = r.acceptance_confirmed_by
             where r.id = $1
            """,
            requirement_id,
        )
        if row is None:
            raise NotFound(f"Requirement {requirement_id} not found.")

        evidence = await conn.fetch(
            """
            select e.*, run.status as research_run_status,
                   run.original_question as research_run_question,
                   cd.document_number as document_number,
                   cd.title           as document_title,
                   cdv.version_label  as document_version_label,
                   cdv.status         as document_version_status,
                   cdv.storage_url    as document_storage_url,
                   case when e.document_version_id is null then null
                        else private.document_version_is_usable(e.document_version_id)
                   end                as document_is_usable,
                   coalesce(p.full_name, p.email) as added_by_name
              from public.evidence_links e
         left join public.research_runs run on run.id = e.research_run_id
         left join public.controlled_document_versions cdv
                on cdv.id = e.document_version_id
         left join public.controlled_documents cd on cd.id = cdv.document_id
         left join public.profiles p on p.id = e.added_by
             where e.requirement_id = $1
          order by e.created_at
            """,
            requirement_id,
        )
        current = await conn.fetchrow(
            """
            select a.*, coalesce(p.full_name, p.email) as approver_name
              from public.approvals a
         left join public.profiles p on p.id = a.approver_id
             where a.requirement_id = $1
               and a.superseded_at is null
               and a.decision = 'approved'
             limit 1
            """,
            requirement_id,
        )

        item = dict(row)
        item["evidence"] = [dict(e) for e in evidence]
        item["approvals"] = []
        item["current_approval"] = dict(current) if current else None
        return item

    async def get_requirement(self, user_id: str, requirement_id: str) -> dict:
        async with self._pool.acquire() as conn:
            await self._capabilities_for_requirement(conn, user_id, requirement_id)
            return await self._requirement_view(conn, requirement_id)

    async def list_attachable_runs(self, user_id: str, project_id: str) -> list[dict]:
        """Completed research runs on this project, usable as evidence.

        Only completed runs. A queued or failed run has no verified evidence
        behind it, and attaching one would let an empty result satisfy a
        requirement.
        """
        async with self._pool.acquire() as conn:
            await self._capabilities(conn, user_id, project_id)
            rows = await conn.fetch(
                """
                select r.id, r.original_question, r.status, r.completed_at,
                       (select count(*) from public.evidence_records er
                         where er.run_id = r.id) as evidence_count
                  from public.research_runs r
                 where r.project_id = $1 and r.status = 'completed'
              order by r.completed_at desc nulls last
                 limit 100
                """,
                project_id,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------ controlled documents ---

    async def list_documents(self, user_id: str, project_id: str) -> list[dict]:
        """The register for one project, plus organisation-wide documents.

        Organisation-wide entries (``project_id is null``) are SOPs and policies
        that any programme may cite, so they appear in every register rather
        than having to be duplicated per project.
        """
        async with self._pool.acquire() as conn:
            await self._capabilities(conn, user_id, project_id)
            rows = await conn.fetch(
                """
                select d.*,
                       coalesce(o.full_name, o.email) as owner_name,
                       (select count(*) from public.controlled_document_versions v
                         where v.document_id = d.id) as version_count,
                       (
                         select json_build_object(
                           'id', v.id, 'version_label', v.version_label,
                           'status', v.status, 'storage_url', v.storage_url,
                           'effective_date', v.effective_date,
                           'expiry_date', v.expiry_date,
                           'is_usable', private.document_version_is_usable(v.id))
                           from public.controlled_document_versions v
                          where v.document_id = d.id
                       order by case v.status when 'effective' then 0
                                              when 'approved'  then 1
                                              else 2 end,
                                v.created_at desc
                          limit 1
                       ) as current_version
                  from public.controlled_documents d
             left join public.profiles o on o.id = d.owner_user_id
                 where d.project_id = $1 or d.project_id is null
              order by d.project_id nulls last, d.document_number
                """,
                project_id,
            )
        return [dict(r) for r in rows]

    async def get_document(self, user_id: str, document_id: str) -> dict:
        async with self._pool.acquire() as conn:
            doc = await conn.fetchrow(
                "select * from public.controlled_documents where id = $1", document_id
            )
            if doc is None:
                raise NotFound(f"Document {document_id} not found.")
            if doc["project_id"] is not None:
                await self._capabilities(conn, user_id, str(doc["project_id"]))

            versions = await conn.fetch(
                """
                select v.*,
                       private.document_version_is_usable(v.id) as is_usable,
                       coalesce(a.full_name, a.email) as approved_by_name,
                       (select count(*) from public.evidence_links e
                         where e.document_version_id = v.id) as cited_by_count
                  from public.controlled_document_versions v
             left join public.profiles a on a.id = v.approved_by
                 where v.document_id = $1
              order by v.created_at desc
                """,
                document_id,
            )
        item = dict(doc)
        item["versions"] = [dict(v) for v in versions]
        return item

    async def create_document(
        self,
        user_id: str,
        project_id: str,
        *,
        document_number: str,
        title: str,
        document_type: str,
        discipline: str | None = None,
        description: str | None = None,
        owner_user_id: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._capabilities(conn, user_id, project_id)
            try:
                row = await conn.fetchrow(
                    """
                    insert into public.controlled_documents
                        (project_id, document_number, title, document_type,
                         discipline, description, owner_user_id, created_by)
                    values ($1,$2,$3,$4,$5,$6,$7,$8)
                    returning *
                    """,
                    project_id, document_number.strip(), title.strip(),
                    document_type, discipline, description,
                    owner_user_id or user_id, user_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise Conflict(
                    f"Document number '{document_number}' is already in the "
                    "register. Two documents sharing a number is how the wrong "
                    "file gets approved."
                ) from exc

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.document.registered",
                entity_type="controlled_document",
                entity_id=str(row["id"]),
                project_id=project_id,
                new=dict(row),
            )
        return dict(row)

    async def add_document_version(
        self,
        user_id: str,
        document_id: str,
        *,
        version_label: str,
        storage_url: str,
        status: str = "draft",
        checksum: str | None = None,
        effective_date: date | None = None,
        expiry_date: date | None = None,
        supersedes_version_id: str | None = None,
    ) -> dict:
        """Record a new version. Optionally supersede the one it replaces.

        Superseding is done here rather than left to a second call because a
        register that briefly shows two effective versions of one document is
        worse than one that shows none.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            doc = await conn.fetchrow(
                "select * from public.controlled_documents where id = $1", document_id
            )
            if doc is None:
                raise NotFound(f"Document {document_id} not found.")

            caps = None
            if doc["project_id"] is not None:
                caps = await self._capabilities(conn, user_id, str(doc["project_id"]))

            # 'approved' and 'effective' are assertions about review having
            # happened, so they need the authority that goes with that.
            if status in ("approved", "effective"):
                if caps is None or not caps.can_approve:
                    raise Forbidden(
                        f"Recording a version as '{status}' requires a role with "
                        "approval authority. Record it as 'draft' or "
                        "'in_review' instead."
                    )

            approved_by = user_id if status in ("approved", "effective") else None

            if supersedes_version_id:
                previous = await conn.fetchrow(
                    """
                    select id, document_id, status
                      from public.controlled_document_versions where id = $1
                    """,
                    supersedes_version_id,
                )
                if previous is None or str(previous["document_id"]) != str(document_id):
                    raise Conflict(
                        "The version being superseded belongs to a different "
                        "document."
                    )

                # RETIRE THE OLD ONE FIRST.
                #
                # `controlled_document_versions_one_effective` allows a single
                # effective version per document, so inserting the replacement
                # while the incumbent still holds that status fails on the
                # index - reported, unhelpfully, as "version already exists".
                #
                # Both statements are in one transaction, so no reader ever
                # observes the document with two effective versions or none.
                # The back-reference is filled in after the insert, once there
                # is something to point at.
                await conn.execute(
                    """
                    update public.controlled_document_versions
                       set status = 'superseded',
                           superseded_at = now()
                     where id = $1
                    """,
                    supersedes_version_id,
                )

            try:
                row = await conn.fetchrow(
                    """
                    insert into public.controlled_document_versions
                        (document_id, version_label, status, storage_url, checksum,
                         effective_date, expiry_date, approved_by, approved_at,
                         created_by)
                    values ($1,$2,$3,$4,$5,$6,$7,$8,
                            case when $8::uuid is null then null else now() end, $9)
                    returning *
                    """,
                    document_id, version_label.strip(), status, storage_url.strip(),
                    checksum, effective_date, expiry_date, approved_by, user_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise Conflict(
                    f"Version '{version_label}' already exists for this document, "
                    "or another version is already effective."
                ) from exc

            if supersedes_version_id:
                # Now that the replacement exists, record what replaced it.
                # The status change above already fired the trigger that
                # invalidated approvals resting on the old version.
                await conn.execute(
                    """
                    update public.controlled_document_versions
                       set superseded_by_version_id = $2
                     where id = $1
                    """,
                    supersedes_version_id, row["id"],
                )

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.document.version_added",
                entity_type="controlled_document",
                entity_id=str(document_id),
                project_id=str(doc["project_id"]) if doc["project_id"] else None,
                new={
                    "version_label": row["version_label"],
                    "status": row["status"],
                    "storage_url": row["storage_url"],
                    "supersedes": supersedes_version_id,
                },
                reason=(
                    "Superseded the previous version; approvals resting on it "
                    "were invalidated."
                    if supersedes_version_id else None
                ),
            )
        return dict(row)

    async def set_document_version_status(
        self, user_id: str, version_id: str, *, status: str, reason: str | None = None
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            version = await conn.fetchrow(
                """
                select v.*, d.project_id
                  from public.controlled_document_versions v
                  join public.controlled_documents d on d.id = v.document_id
                 where v.id = $1
                """,
                version_id,
            )
            if version is None:
                raise NotFound(f"Document version {version_id} not found.")

            caps = None
            if version["project_id"] is not None:
                caps = await self._capabilities(conn, user_id, str(version["project_id"]))

            if status in ("approved", "effective") and (caps is None or not caps.can_approve):
                raise Forbidden(
                    f"Marking a version '{status}' requires approval authority."
                )

            try:
                row = await conn.fetchrow(
                    """
                    update public.controlled_document_versions
                       set status = $2,
                           approved_by = case
                             when $2 in ('approved','effective')
                               then coalesce(approved_by, $3::uuid) else approved_by end,
                           approved_at = case
                             when $2 in ('approved','effective')
                               then coalesce(approved_at, now()) else approved_at end,
                           superseded_at = case
                             when $2 = 'superseded' then coalesce(superseded_at, now())
                             else superseded_at end
                     where id = $1
                    returning *
                    """,
                    version_id, status, user_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise Conflict(
                    "Another version of this document is already effective. "
                    "Supersede it first."
                ) from exc

            await self._audit(
                conn,
                actor=user_id,
                action=f"pdp.document.version_{status}",
                entity_type="controlled_document_version",
                entity_id=version_id,
                project_id=str(version["project_id"]) if version["project_id"] else None,
                previous={"status": version["status"]},
                new={"status": row["status"]},
                reason=reason,
            )
        return dict(row)

    # -------------------------------------------------- tasks and schedule ---

    async def get_schedule(self, user_id: str, project_id: str) -> dict:
        """Tasks, milestones and the current baseline, with derived state.

        Status, variance and float are computed on read. None of them is stored,
        so none of them can be edited into saying something more comfortable.
        """
        async with self._pool.acquire() as conn:
            caps = await self._capabilities(conn, user_id, project_id)

            tasks = await conn.fetch(
                """
                select t.*,
                       private.task_status(t.id)         as status,
                       private.task_variance_days(t.id)  as variance_days,
                       f.float_days,
                       coalesce(f.is_critical, false)    as is_critical,
                       coalesce(o.full_name, o.email)    as owner_name,
                       r.ref_code                        as requirement_ref,
                       s.name                            as stage_name,
                       (select coalesce(json_agg(json_build_object(
                                 'predecessor_id', d.predecessor_id,
                                 'title', p.title,
                                 'dependency_type', d.dependency_type,
                                 'lag_days', d.lag_days,
                                 'complete', p.actual_end is not null)), '[]'::json)
                          from public.task_dependencies d
                          join public.project_tasks p on p.id = d.predecessor_id
                         where d.successor_id = t.id) as depends_on
                  from public.project_tasks t
             left join lateral private.task_float_days(t.project_id) f
                    on f.task_id = t.id
             left join public.profiles o on o.id = t.owner_user_id
             left join public.gate_requirements r on r.id = t.requirement_id
             left join public.project_stages s on s.id = t.project_stage_id
                 where t.project_id = $1
              order by coalesce(t.forecast_start, t.baseline_start), t.created_at
                """,
                project_id,
            )

            milestones = await conn.fetch(
                """
                select m.*,
                       case when m.baseline_date is null then null
                            else coalesce(m.actual_date, m.forecast_date) - m.baseline_date
                       end as variance_days
                  from public.project_milestones m
                 where m.project_id = $1
              order by coalesce(m.forecast_date, m.baseline_date)
                """,
                project_id,
            )

            baselines = await conn.fetch(
                """
                select b.id, b.version, b.name, b.reason, b.approved_at,
                       b.superseded_at,
                       coalesce(p.full_name, p.email) as approved_by_name
                  from public.schedule_baselines b
             left join public.profiles p on p.id = b.approved_by
                 where b.project_id = $1
              order by b.version desc
                """,
                project_id,
            )

        return {
            "tasks": [dict(t) for t in tasks],
            "milestones": [dict(m) for m in milestones],
            "baselines": [dict(b) for b in baselines],
            "capabilities": caps.as_dict(),
        }

    async def create_task(
        self,
        user_id: str,
        project_id: str,
        *,
        title: str,
        description: str | None = None,
        requirement_id: str | None = None,
        project_stage_id: str | None = None,
        owner_user_id: str | None = None,
        forecast_start: date | None = None,
        forecast_end: date | None = None,
        effort_days: float | None = None,
        priority: str = "medium",
        wbs_code: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._capabilities(conn, user_id, project_id)
            row = await conn.fetchrow(
                """
                insert into public.project_tasks
                  (project_id, project_stage_id, requirement_id, wbs_code, title,
                   description, owner_user_id, forecast_start, forecast_end,
                   effort_days, priority, created_by)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                returning *
                """,
                project_id, project_stage_id, requirement_id, wbs_code, title.strip(),
                description, owner_user_id, forecast_start, forecast_end,
                effort_days, priority, user_id,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.task.created",
                entity_type="project_task",
                entity_id=str(row["id"]),
                project_id=project_id,
                new=dict(row),
            )
        return dict(row)

    async def update_task(
        self,
        user_id: str,
        task_id: str,
        *,
        forecast_start: date | None = None,
        forecast_end: date | None = None,
        actual_start: date | None = None,
        actual_end: date | None = None,
        owner_user_id: str | None = None,
        priority: str | None = None,
        is_blocked: bool | None = None,
        blocked_reason: str | None = None,
        reason: str | None = None,
    ) -> dict:
        """Move forecast and actual dates. Baseline dates are not touchable here.

        There is no parameter for them, and the database would refuse anyway
        once a baseline is approved. Both, deliberately: the API should not
        offer what the schema forbids.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            task = await conn.fetchrow(
                "select * from public.project_tasks where id = $1", task_id
            )
            if task is None:
                raise NotFound(f"Task {task_id} not found.")
            project_id = str(task["project_id"])
            await self._capabilities(conn, user_id, project_id)

            if is_blocked and not (blocked_reason or "").strip():
                raise Conflict("Blocking a task requires a stated reason.")

            try:
                row = await conn.fetchrow(
                    """
                    update public.project_tasks
                       set forecast_start = coalesce($2::date, forecast_start),
                           forecast_end   = coalesce($3::date, forecast_end),
                           actual_start   = coalesce($4::date, actual_start),
                           actual_end     = coalesce($5::date, actual_end),
                           owner_user_id  = coalesce($6::uuid, owner_user_id),
                           priority       = coalesce($7::text, priority),
                           is_blocked     = coalesce($8::boolean, is_blocked),
                           blocked_reason = case
                             when $8::boolean is true then $9::text
                             when $8::boolean is false then null
                             else blocked_reason end
                     where id = $1
                    returning *
                    """,
                    task_id, forecast_start, forecast_end, actual_start, actual_end,
                    owner_user_id, priority, is_blocked, blocked_reason,
                )
            except asyncpg.PostgresError as exc:
                if getattr(exc, "sqlstate", None) == INSUFFICIENT_PRIVILEGE:
                    raise Forbidden(str(exc)) from exc
                if getattr(exc, "sqlstate", None) == "23514":
                    raise Conflict(
                        "Those dates are not consistent: an end cannot precede a "
                        "start, and a task cannot finish without starting."
                    ) from exc
                raise

            # Only record a schedule change when a date actually moved. An
            # audit trail full of no-op edits is one nobody reads.
            moved = {
                field: [task[field], row[field]]
                for field in (
                    "forecast_start", "forecast_end", "actual_start", "actual_end"
                )
                if task[field] != row[field]
            }
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.task.rescheduled" if moved else "pdp.task.updated",
                entity_type="project_task",
                entity_id=task_id,
                project_id=project_id,
                previous={k: v[0] for k, v in moved.items()} or None,
                new={k: v[1] for k, v in moved.items()} or None,
                reason=reason,
            )
        return dict(row)

    async def add_task_dependency(
        self,
        user_id: str,
        successor_id: str,
        *,
        predecessor_id: str,
        dependency_type: str = "FS",
        lag_days: int = 0,
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "select id, project_id from public.project_tasks where id = any($1::uuid[])",
                [successor_id, predecessor_id],
            )
            if len(rows) != 2:
                raise NotFound("One of those tasks does not exist.")
            projects = {str(r["project_id"]) for r in rows}
            if len(projects) != 1:
                raise Conflict("Tasks in different projects cannot depend on each other.")
            project_id = projects.pop()
            await self._capabilities(conn, user_id, project_id)

            try:
                await conn.execute(
                    """
                    insert into public.task_dependencies
                        (predecessor_id, successor_id, dependency_type, lag_days)
                    values ($1,$2,$3,$4)
                    """,
                    predecessor_id, successor_id, dependency_type, lag_days,
                )
            except asyncpg.PostgresError as exc:
                if getattr(exc, "sqlstate", None) == "23514":
                    raise Conflict(
                        "That would create a circular dependency, which would "
                        "make the critical path uncomputable."
                    ) from exc
                if isinstance(exc, asyncpg.UniqueViolationError):
                    raise Conflict("That dependency already exists.") from exc
                raise

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.task.dependency_added",
                entity_type="project_task",
                entity_id=successor_id,
                project_id=project_id,
                new={"predecessor_id": predecessor_id, "type": dependency_type},
            )

    async def create_milestone(
        self,
        user_id: str,
        project_id: str,
        *,
        name: str,
        forecast_date: date | None = None,
        project_stage_id: str | None = None,
        is_contractual: bool = False,
        description: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            await self._capabilities(conn, user_id, project_id)
            row = await conn.fetchrow(
                """
                insert into public.project_milestones
                  (project_id, project_stage_id, name, description, forecast_date,
                   is_contractual, created_by)
                values ($1,$2,$3,$4,$5,$6,$7)
                returning *
                """,
                project_id, project_stage_id, name.strip(), description,
                forecast_date, is_contractual, user_id,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.milestone.created",
                entity_type="project_milestone",
                entity_id=str(row["id"]),
                project_id=project_id,
                new=dict(row),
            )
        return dict(row)

    async def rebaseline(
        self, user_id: str, project_id: str, *, name: str, reason: str
    ) -> dict:
        """Freeze the current forecast as the new commitment.

        Requires approval authority, because that is what a baseline is: a
        commitment somebody is accountable for. Every previous baseline is kept
        with its snapshot, so "what did we promise in March" stays answerable
        after the dates have moved three times.
        """
        if not (reason or "").strip():
            raise Conflict("A re-baseline must state why the commitment changed.")

        async with self._pool.acquire() as conn, conn.transaction():
            caps = await self._capabilities(conn, user_id, project_id)
            if not caps.can_approve:
                raise Forbidden(
                    "Setting a baseline requires a role with approval authority. "
                    "A baseline is a commitment, not a preference."
                )

            baseline_id = await conn.fetchval(
                "select private.rebaseline($1,$2,$3,$4)",
                project_id, user_id, name.strip(), reason.strip(),
            )
            row = await conn.fetchrow(
                "select * from public.schedule_baselines where id = $1", baseline_id
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.schedule.rebaselined",
                entity_type="schedule_baseline",
                entity_id=str(baseline_id),
                project_id=project_id,
                new={"version": row["version"], "name": row["name"]},
                reason=reason,
            )
        return dict(row)

    # -------------------------------------------------------- agent sessions ---

    async def capabilities_for_stage(self, user_id: str, stage_id: str):
        """Public wrapper, so a route can check access before spending money."""
        async with self._pool.acquire() as conn:
            return await self._capabilities_for_stage(conn, user_id, stage_id)

    async def start_agent_session(
        self, user_id: str, *, agent: str, project_id: str | None, objective: str
    ) -> str:
        """Open an agent run.

        `requested_by` is NOT NULL: an agent always acts on somebody's behalf,
        and an action with no accountable person behind it is not something
        this system should be able to represent.
        """
        async with self._pool.acquire() as conn:
            return str(
                await conn.fetchval(
                    """
                    insert into public.pdp_agent_sessions
                        (agent, project_id, requested_by, objective)
                    values ($1,$2,$3,$4)
                    returning id
                    """,
                    agent, project_id, user_id, objective,
                )
            )

    async def finish_agent_session(
        self,
        session_id: str,
        *,
        findings: dict | None = None,
        recommendations: list | None = None,
        handoff_question: str | None = None,
        usage: Any = None,
        error: str | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update public.pdp_agent_sessions
                   set status = case when $5::text is null then 'completed' else 'failed' end,
                       findings = $2,
                       recommendations = $3,
                       handoff_question = $4,
                       error = $5,
                       total_input_tokens = coalesce($6, 0),
                       total_output_tokens = coalesce($7, 0),
                       estimated_cost_usd = $8,
                       completed_at = now()
                 where id = $1
                """,
                session_id,
                jsonable(findings) if findings is not None else None,
                jsonable(recommendations) if recommendations is not None else None,
                handoff_question,
                error,
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
                (
                    float(usage.estimated_cost_usd)
                    if usage is not None and getattr(usage, "estimated_cost_usd", None)
                    else None
                ),
            )

    async def list_agent_sessions(
        self, user_id: str, project_id: str, limit: int = 20
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            await self._capabilities(conn, user_id, project_id)
            rows = await conn.fetch(
                """
                select s.*, coalesce(p.full_name, p.email) as requested_by_name
                  from public.pdp_agent_sessions s
             left join public.profiles p on p.id = s.requested_by
                 where s.project_id = $1
              order by s.started_at desc
                 limit $2
                """,
                project_id, limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------- notifications ---

    async def list_notifications(
        self, user_id: str, project_id: str, *, include_resolved: bool = False
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            await self._capabilities(conn, user_id, project_id)
            rows = await conn.fetch(
                """
                select e.*, r.key as rule_key, r.name as rule_name,
                       coalesce(a.full_name, a.email) as acknowledged_by_name
                  from public.notification_events e
                  join public.notification_rules r on r.id = e.rule_id
             left join public.profiles a on a.id = e.acknowledged_by
                 where e.project_id = $1
                   and ($2 or e.resolved_at is null)
              order by e.resolved_at nulls first,
                       case e.severity when 'critical' then 0
                                       when 'warning'  then 1 else 2 end,
                       e.raised_at desc
                 limit 200
                """,
                project_id, include_resolved,
            )
        return [dict(r) for r in rows]

    async def acknowledge_notification(self, user_id: str, event_id: str) -> dict:
        """Take ownership of an alert. Stops it escalating; does not close it.

        Acknowledgement and resolution are different acts and must not be
        conflated. Only the condition ceasing to be true resolves an event -
        otherwise acknowledging would be a way to make a problem disappear from
        the list without fixing it, which is the false green again.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            event = await conn.fetchrow(
                "select * from public.notification_events where id = $1", event_id
            )
            if event is None:
                raise NotFound(f"Notification {event_id} not found.")
            if event["project_id"] is not None:
                await self._capabilities(conn, user_id, str(event["project_id"]))
            if event["resolved_at"] is not None:
                raise Conflict("That notification has already been resolved.")

            row = await conn.fetchrow(
                """
                update public.notification_events
                   set acknowledged_by = $2, acknowledged_at = now()
                 where id = $1
                returning *
                """,
                event_id, user_id,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.notification.acknowledged",
                entity_type="notification_event",
                entity_id=event_id,
                project_id=str(event["project_id"]) if event["project_id"] else None,
                new={"title": event["title"]},
            )
        return dict(row)

    async def project_audit(self, user_id: str, project_id: str, limit: int = 100) -> list[dict]:
        async with self._pool.acquire() as conn:
            await self._capabilities(conn, user_id, project_id)
            rows = await conn.fetch(
                """
                select a.*, coalesce(p.full_name, p.email) as actor_name
                  from public.audit_events a
             left join public.profiles p on p.id = a.actor_user_id
                 where a.project_id = $1
              order by a.occurred_at desc
                 limit $2
                """,
                project_id, limit,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ writes ---

    async def attach_evidence(
        self,
        user_id: str,
        requirement_id: str,
        *,
        evidence_type: str,
        research_run_id: str | None = None,
        document_version_id: str | None = None,
        external_url: str | None = None,
        note: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)
            project_id = str(req["project_id"])

            if evidence_type == "document":
                version = await conn.fetchrow(
                    """
                    select v.id, v.status, v.version_label, v.expiry_date,
                           d.project_id, d.document_number,
                           private.document_version_is_usable(v.id) as is_usable
                      from public.controlled_document_versions v
                      join public.controlled_documents d on d.id = v.document_id
                     where v.id = $1
                    """,
                    document_version_id,
                )
                if version is None:
                    raise NotFound("That document version is not in the register.")

                # An organisation-wide document (null project) may be cited by
                # any programme; a project's own document may not be borrowed.
                if (
                    version["project_id"] is not None
                    and str(version["project_id"]) != project_id
                ):
                    raise Conflict(
                        f"Document {version['document_number']} belongs to a "
                        "different project."
                    )

                if not version["is_usable"]:
                    # Refused at attach time as well as in the engine. The
                    # engine would catch it either way, but discovering it now
                    # is far better than discovering it in a gate review.
                    raise Conflict(
                        f"Version '{version['version_label']}' is "
                        f"{version['status']}"
                        + (
                            " and past its expiry date"
                            if version["expiry_date"] else ""
                        )
                        + ". Only an approved or effective version that is still "
                        "in date can support a requirement."
                    )

            if evidence_type == "research_run":
                run = await conn.fetchrow(
                    "select id, project_id, status from public.research_runs where id = $1",
                    research_run_id,
                )
                if run is None:
                    raise NotFound("That research run does not exist.")
                if str(run["project_id"]) != project_id:
                    # Cross-project evidence would let work done under one
                    # programme's scope silently satisfy another's gate.
                    raise Conflict(
                        "That research run belongs to a different project."
                    )
                if run["status"] != "completed":
                    raise Conflict(
                        f"That research run is {run['status']}. Only a completed "
                        "run carries verified evidence."
                    )

            row = await conn.fetchrow(
                """
                insert into public.evidence_links (
                    requirement_id, project_id, evidence_type, research_run_id,
                    document_version_id, external_url, note, title, description,
                    added_by
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                returning *
                """,
                requirement_id, project_id, evidence_type, research_run_id,
                document_version_id, external_url, note, title, description,
                user_id,
            )

            # The evidence_change_supersedes_approval trigger has now
            # invalidated any current approval. Surfaced to the caller so the
            # UI can say why a green requirement just went amber.
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.evidence.attached",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=project_id,
                new=dict(row),
                reason="Any existing approval was superseded by this change.",
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)

        return dict(row)

    async def detach_evidence(self, user_id: str, evidence_id: str) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "select * from public.evidence_links where id = $1", evidence_id
            )
            if row is None:
                raise NotFound(f"Evidence {evidence_id} not found.")
            req, _caps = await self._capabilities_for_requirement(
                conn, user_id, str(row["requirement_id"])
            )

            await conn.execute("delete from public.evidence_links where id = $1", evidence_id)
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.evidence.detached",
                entity_type="gate_requirement",
                entity_id=str(row["requirement_id"]),
                project_id=str(row["project_id"]),
                previous=dict(row),
                reason="Any existing approval was superseded by this change.",
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)

    async def set_acceptance(
        self, user_id: str, requirement_id: str, *, confirmed: bool
    ) -> dict:
        """Confirm or withdraw the statement that acceptance criteria are met.

        This is the doer's act, separate from approval: one person states the
        criteria are met, a different person agrees. Confirming with no evidence
        attached is refused - there would be nothing for the statement to be
        about.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)

            if confirmed:
                evidence_count = await conn.fetchval(
                    "select count(*) from public.evidence_links where requirement_id = $1",
                    requirement_id,
                )
                if not evidence_count:
                    raise Conflict(
                        "Attach evidence before confirming the acceptance "
                        "criteria. There is nothing yet for the confirmation to "
                        "refer to."
                    )
                if req["is_blocked"]:
                    raise Conflict(
                        "This requirement is blocked. Clear the block before "
                        "confirming acceptance."
                    )

            row = await conn.fetchrow(
                """
                update public.gate_requirements
                   set acceptance_confirmed_by = $2::uuid,
                       acceptance_confirmed_at = case when $2::uuid is null then null else now() end
                 where id = $1
                returning *
                """,
                requirement_id, user_id if confirmed else None,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.requirement.acceptance_confirmed" if confirmed
                       else "pdp.requirement.acceptance_withdrawn",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=str(req["project_id"]),
                previous={"acceptance_confirmed_by": req["acceptance_confirmed_by"]},
                new={"acceptance_confirmed_by": row["acceptance_confirmed_by"]},
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)
            return await self._requirement_view(conn, requirement_id)

    async def decide_requirement(
        self,
        user_id: str,
        requirement_id: str,
        *,
        decision: str,
        comments: str | None = None,
    ) -> dict:
        """Approve or reject a requirement.

        Three independent checks stand between a caller and an approval:

        1. the caller holds a role with ``can_approve`` (this method),
        2. the caller is neither the owner nor the acceptance confirmer
           (database trigger, so no code path can skip it),
        3. evidence exists and acceptance is confirmed (this method) - approving
           an empty requirement would produce a satisfied state with nothing
           behind it.
        """
        if decision not in ("approved", "rejected"):
            raise Conflict("A decision must be 'approved' or 'rejected'.")

        async with self._pool.acquire() as conn, conn.transaction():
            req, caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)
            project_id = str(req["project_id"])

            if not caps.can_approve:
                raise Forbidden(
                    "Approving a requirement requires a role with approval "
                    "authority. Your roles: "
                    + (", ".join(caps.role_keys) or "none on this project")
                    + "."
                )

            approver_role = await self._approver_role(conn, user_id, project_id, req)

            if decision == "approved":
                if req["is_blocked"]:
                    raise Conflict("This requirement is blocked and cannot be approved.")
                if req["acceptance_confirmed_by"] is None:
                    raise Conflict(
                        "The acceptance criteria have not been confirmed. "
                        "Approval states that a confirmed claim is correct; "
                        "there is no claim yet."
                    )
                evidence_count = await conn.fetchval(
                    "select count(*) from public.evidence_links where requirement_id = $1",
                    requirement_id,
                )
                if not evidence_count:
                    raise Conflict("This requirement has no evidence attached.")

            snapshot = await conn.fetch(
                """
                select id, evidence_type, research_run_id, external_url, title
                  from public.evidence_links where requirement_id = $1 order by created_at
                """,
                requirement_id,
            )

            # Only one current approval may exist (partial unique index), so any
            # previous decision is superseded explicitly rather than colliding.
            await conn.execute(
                """
                update public.approvals
                   set superseded_at = now(),
                       superseded_reason = 'Superseded by a later decision.'
                 where requirement_id = $1 and superseded_at is null
                """,
                requirement_id,
            )

            try:
                row = await conn.fetchrow(
                    """
                    insert into public.approvals (
                        requirement_id, project_id, approver_id, approver_role,
                        decision, comments, evidence_snapshot
                    ) values ($1,$2,$3,$4,$5,$6,$7)
                    returning *
                    """,
                    requirement_id, project_id, user_id, approver_role,
                    decision, comments, jsonable([dict(s) for s in snapshot]),
                )
            except asyncpg.PostgresError as exc:
                if getattr(exc, "sqlstate", None) == INSUFFICIENT_PRIVILEGE:
                    # Segregation of duties, refused by the database.
                    raise Forbidden(str(exc)) from exc
                raise

            await self._audit(
                conn,
                actor=user_id,
                actor_role=approver_role,
                action=f"pdp.requirement.{decision}",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=project_id,
                new={
                    "decision": decision,
                    "approval_id": row["id"],
                    "evidence_snapshot": [dict(s) for s in snapshot],
                },
                reason=comments,
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)

        return dict(row)

    async def _approver_role(self, conn, user_id: str, project_id: str, req: dict) -> str:
        """The role key this approval is recorded under.

        If the requirement names a required approver role, the caller must
        actually hold it. Otherwise the highest-ranked approving role they hold
        is recorded, so the audit trail says which authority was exercised.
        """
        rows = await conn.fetch(
            """
            select r.key, r.rank
              from public.user_roles ur
              join public.roles r on r.id = ur.role_id
             where ur.user_id = $1
               and r.can_approve
               and (ur.expires_at is null or ur.expires_at > now())
               and (ur.project_id is null or ur.project_id = $2)
          order by r.rank desc
            """,
            user_id, project_id,
        )
        held = [r["key"] for r in rows]
        required = req.get("approver_role_key")

        if required:
            if required not in held:
                raise Forbidden(
                    f"This requirement must be approved by '{required}'. "
                    "You do not hold that role on this project."
                )
            return required

        if not held:
            raise Forbidden("You hold no role with approval authority.")
        return held[0]

    async def set_assignment(
        self,
        user_id: str,
        requirement_id: str,
        *,
        owner_user_id: str | None = None,
        reviewer_user_id: str | None = None,
        due_date: date | None = None,
        priority: str | None = None,
        clear_owner: bool = False,
        clear_due_date: bool = False,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)

            if owner_user_id:
                # Assigning ownership to whoever holds the current approval would
                # retroactively break segregation of duties: the record would
                # show a requirement approved by its own owner.
                clash = await conn.fetchval(
                    """
                    select 1 from public.approvals
                     where requirement_id = $1
                       and superseded_at is null
                       and decision = 'approved'
                       and approver_id = $2
                    """,
                    requirement_id, owner_user_id,
                )
                if clash:
                    raise Conflict(
                        "That person approved this requirement. Making them its "
                        "owner would leave it approved by its own owner. "
                        "Supersede the approval first."
                    )

            row = await conn.fetchrow(
                """
                update public.gate_requirements
                   set owner_user_id    = case when $6::boolean then null
                                               else coalesce($2::uuid, owner_user_id) end,
                       reviewer_user_id = coalesce($3::uuid, reviewer_user_id),
                       due_date         = case when $7::boolean then null
                                               else coalesce($4::date, due_date) end,
                       priority         = coalesce($5::text, priority)
                 where id = $1
                returning *
                """,
                requirement_id, owner_user_id, reviewer_user_id, due_date,
                priority, clear_owner, clear_due_date,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.requirement.assigned",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=str(req["project_id"]),
                previous={
                    "owner_user_id": req["owner_user_id"],
                    "reviewer_user_id": req["reviewer_user_id"],
                    "due_date": req["due_date"],
                    "priority": req["priority"],
                },
                new={
                    "owner_user_id": row["owner_user_id"],
                    "reviewer_user_id": row["reviewer_user_id"],
                    "due_date": row["due_date"],
                    "priority": row["priority"],
                },
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)
            return await self._requirement_view(conn, requirement_id)

    async def set_blocked(
        self, user_id: str, requirement_id: str, *, blocked: bool, reason: str | None
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)

            if blocked and not (reason or "").strip():
                raise Conflict("Blocking a requirement requires a stated reason.")

            row = await conn.fetchrow(
                """
                update public.gate_requirements
                   set is_blocked     = $2::boolean,
                       blocked_reason = case when $2::boolean then $3::text else null end,
                       blocked_by     = case when $2::boolean then $4::uuid else null end,
                       blocked_at     = case when $2::boolean then now() else null end
                 where id = $1
                returning *
                """,
                requirement_id, blocked, reason, user_id,
            )
            await self._audit(
                conn,
                actor=user_id,
                action="pdp.requirement.blocked" if blocked else "pdp.requirement.unblocked",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=str(req["project_id"]),
                previous={"is_blocked": req["is_blocked"], "blocked_reason": req["blocked_reason"]},
                new={"is_blocked": row["is_blocked"], "blocked_reason": row["blocked_reason"]},
                reason=reason,
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)
            return await self._requirement_view(conn, requirement_id)

    async def set_not_applicable(
        self, user_id: str, requirement_id: str, *, not_applicable: bool, reason: str | None
    ) -> dict:
        """Scope a requirement out, with a justification that goes in the pack.

        A mandatory requirement cannot be scoped out at all - the database
        refuses it. Removing one means changing the template or the project's
        scope, which is a visible, audited act rather than a checkbox.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            req, caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)

            if not_applicable:
                if not caps.can_approve:
                    raise Forbidden(
                        "Scoping a requirement out requires a role with approval "
                        "authority."
                    )
                if not (reason or "").strip():
                    raise Conflict("Marking a requirement not applicable requires a reason.")

            try:
                row = await conn.fetchrow(
                    """
                    update public.gate_requirements
                       set is_not_applicable = $2::boolean,
                           not_applicable_reason =
                             case when $2::boolean then $3::text else null end,
                           not_applicable_by =
                             case when $2::boolean then $4::uuid else null end
                     where id = $1
                    returning *
                    """,
                    requirement_id, not_applicable, reason, user_id,
                )
            except asyncpg.PostgresError as exc:
                if getattr(exc, "sqlstate", None) == "23514":  # check_violation
                    raise Conflict(
                        "A mandatory requirement cannot be marked not applicable. "
                        "Change the programme's scope or its template instead."
                    ) from exc
                raise

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.requirement.scoped_out" if not_applicable
                       else "pdp.requirement.scoped_in",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=str(req["project_id"]),
                previous={"is_not_applicable": req["is_not_applicable"]},
                new={"is_not_applicable": row["is_not_applicable"]},
                reason=reason,
            )
            await self._sync_gate_status(conn, str(req["project_stage_id"]), user_id)
            return await self._requirement_view(conn, requirement_id)

    async def record_review(
        self, user_id: str, requirement_id: str, *, outcome: str, comments: str | None
    ) -> dict:
        """Record an independent review. Not an approval, and never treated as one."""
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)
            try:
                row = await conn.fetchrow(
                    """
                    insert into public.reviews
                        (requirement_id, project_id, reviewer_id, outcome, comments)
                    values ($1,$2,$3,$4,$5)
                    returning *
                    """,
                    requirement_id, str(req["project_id"]), user_id, outcome, comments,
                )
            except asyncpg.PostgresError as exc:
                if getattr(exc, "sqlstate", None) == INSUFFICIENT_PRIVILEGE:
                    raise Forbidden(str(exc)) from exc
                raise

            await self._audit(
                conn,
                actor=user_id,
                action="pdp.requirement.reviewed",
                entity_type="gate_requirement",
                entity_id=requirement_id,
                project_id=str(req["project_id"]),
                new={"outcome": outcome},
                reason=comments,
            )
        return dict(row)

    # ------------------------------------------------------ gate decision ---

    async def decide_gate(
        self,
        user_id: str,
        stage_id: str,
        *,
        decision: str,
        note: str | None = None,
        conditions: str | None = None,
    ) -> dict:
        """Record a human gate decision.

        THE RULE THIS MODULE EXISTS FOR: a gate cannot be approved while any
        mandatory requirement is unsatisfied. Not "should not" - the call is
        refused, and the refusal names the blockers.

        `conditionally_approved` remains available while blockers exist, because
        pretending otherwise would push people to fabricate a clean gate. It
        requires written conditions, and the blocker list as it stood is written
        into the audit record, so what was outstanding at the moment of the
        decision is permanently visible.
        """
        allowed = {"approved", "conditionally_approved", "rejected", "on_hold"}
        if decision not in allowed:
            raise Conflict(f"A gate decision must be one of: {', '.join(sorted(allowed))}.")

        async with self._pool.acquire() as conn, conn.transaction():
            project_id, caps = await self._capabilities_for_stage(conn, user_id, stage_id)

            if not caps.can_gate:
                raise Forbidden(
                    "Gate decisions require a role with gate authority "
                    "(gate committee, quality, regulatory, department head or "
                    "executive). Your roles: "
                    + (", ".join(caps.role_keys) or "none on this project")
                    + "."
                )

            stage = await conn.fetchrow(
                "select * from public.project_stages where id = $1", stage_id
            )
            readiness = await conn.fetchrow(
                "select * from private.gate_readiness($1)", stage_id
            )
            blockers = [
                dict(b) for b in
                await conn.fetch("select * from private.gate_blockers($1)", stage_id)
            ]

            if decision == "approved" and not readiness["is_ready"]:
                raise Conflict(
                    f"This gate is {readiness['readiness_pct']}% complete but "
                    f"{readiness['blocker_count']} mandatory requirement(s) are not "
                    "satisfied, so it cannot be approved. A percentage does not "
                    "unlock a gate. Outstanding: "
                    + "; ".join(f"{b['ref_code']} ({b['status']})" for b in blockers[:5])
                    + ("..." if len(blockers) > 5 else "")
                )

            if decision == "conditionally_approved" and not (conditions or "").strip():
                raise Conflict(
                    "Conditional approval requires written conditions stating "
                    "what must still be done."
                )

            row = await conn.fetchrow(
                """
                update public.project_stages
                   set gate_status       = $2,
                       gate_decision_by   = $3,
                       gate_decision_at   = now(),
                       gate_decision_note = $4,
                       gate_conditions    = $5,
                       actual_end_date    = case
                         when $2 in ('approved','conditionally_approved')
                         then coalesce(actual_end_date, current_date)
                         else actual_end_date end
                 where id = $1
                returning *
                """,
                stage_id, decision, user_id, note,
                conditions if decision == "conditionally_approved" else None,
            )

            await self._audit(
                conn,
                actor=user_id,
                action=f"pdp.gate.{decision}",
                entity_type="project_stage",
                entity_id=stage_id,
                project_id=project_id,
                previous={"gate_status": stage["gate_status"]},
                new={
                    "gate_status": decision,
                    "readiness_pct": readiness["readiness_pct"],
                    "is_ready": readiness["is_ready"],
                    # The blockers as they stood. A conditional approval granted
                    # over three outstanding items must remain readable as such
                    # years later.
                    "outstanding_blockers": blockers,
                    "conditions": conditions,
                },
                reason=note,
            )

            # Advance the project to the next stage once this one has passed.
            if decision in ("approved", "conditionally_approved"):
                next_stage = await conn.fetchval(
                    """
                    select id from public.project_stages
                     where project_id = $1 and position > $2
                  order by position limit 1
                    """,
                    project_id, stage["position"],
                )
                if next_stage:
                    await conn.execute(
                        "update public.projects set current_stage_id = $2 where id = $1",
                        project_id, next_stage,
                    )
                    await conn.execute(
                        """
                        update public.project_stages
                           set gate_status = 'in_progress',
                               actual_start_date = coalesce(actual_start_date, current_date)
                         where id = $1 and gate_status = 'not_started'
                        """,
                        next_stage,
                    )

        return dict(row)

    # --------------------------------------------------------- gate state ---

    async def _sync_gate_status(self, conn, stage_id: str, actor: str) -> None:
        """Move the gate's engine-owned status to match the record.

        The engine may advance a gate as far as `ready_for_human_review` and no
        further; the four decision states below that line belong to a person
        with gate authority. Once such a decision exists this function leaves the
        stage alone entirely - an engine must never quietly un-approve or
        re-approve what a human decided.
        """
        stage = await conn.fetchrow(
            "select id, project_id, gate_status from public.project_stages where id = $1",
            stage_id,
        )
        if stage is None:
            return

        human_decided = {"approved", "conditionally_approved", "rejected", "on_hold"}
        if stage["gate_status"] in human_decided:
            return

        readiness = await conn.fetchrow(
            "select * from private.gate_readiness($1)", stage_id
        )
        activity = await conn.fetchrow(
            """
            select
              (select count(*) from public.evidence_links e
                join public.gate_requirements r on r.id = e.requirement_id
               where r.project_stage_id = $1) as evidence_count,
              (select count(*) from public.gate_requirements r
                where r.project_stage_id = $1
                  and (r.owner_user_id is not null or r.is_blocked)) as touched_count,
              (select count(*) from public.gate_requirements r
                where r.project_stage_id = $1
                  and r.is_mandatory
                  and r.due_date < current_date
                  and not private.requirement_is_satisfied(r.id)) as overdue_count
            """,
            stage_id,
        )

        if readiness["is_ready"]:
            new_status = "ready_for_human_review"
        elif activity["overdue_count"]:
            new_status = "at_risk"
        elif activity["evidence_count"] or activity["touched_count"]:
            new_status = "in_progress"
        else:
            new_status = "not_started"

        if new_status == stage["gate_status"]:
            return

        await conn.execute(
            """
            update public.project_stages
               set gate_status = $2,
                   actual_start_date = case
                     when $2 <> 'not_started' then coalesce(actual_start_date, current_date)
                     else actual_start_date end
             where id = $1
            """,
            stage_id, new_status,
        )
        await self._audit(
            conn,
            actor=actor,
            action="pdp.gate.status_recomputed",
            entity_type="project_stage",
            entity_id=stage_id,
            project_id=str(stage["project_id"]),
            previous={"gate_status": stage["gate_status"]},
            new={
                "gate_status": new_status,
                "readiness_pct": readiness["readiness_pct"],
                "is_ready": readiness["is_ready"],
                "blocker_count": readiness["blocker_count"],
            },
            reason="Derived from the record by the readiness engine.",
        )


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
