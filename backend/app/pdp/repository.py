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
                        description, gate_question, exit_criteria
                    ) values ($1,$2,$3,$4,$5,$6,$7,$8)
                    returning *
                    """,
                    project_id, stage["id"], stage["position"], stage["key"],
                    stage["name"], stage["description"], stage["gate_question"],
                    stage["exit_criteria"],
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
                       coalesce(p.full_name, p.email) as added_by_name
                  from public.evidence_links e
                  join public.gate_requirements r on r.id = e.requirement_id
             left join public.research_runs run on run.id = e.research_run_id
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

        return {
            "project_id": project_id,
            "stage": dict(stage),
            "readiness": dict(readiness),
            "blockers": [dict(b) for b in blockers],
            "requirements": enriched,
            "capabilities": caps.as_dict(),
        }

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
                   coalesce(p.full_name, p.email) as added_by_name
              from public.evidence_links e
         left join public.research_runs run on run.id = e.research_run_id
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
        external_url: str | None = None,
        note: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn, conn.transaction():
            req, _caps = await self._capabilities_for_requirement(conn, user_id, requirement_id)
            project_id = str(req["project_id"])

            if evidence_type == "document":
                raise Conflict(
                    "Document evidence arrives with the controlled document "
                    "register in Phase D. Attach a URL or a research run for now."
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
                    external_url, note, title, description, added_by
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                returning *
                """,
                requirement_id, project_id, evidence_type, research_run_id,
                external_url, note, title, description, user_id,
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
