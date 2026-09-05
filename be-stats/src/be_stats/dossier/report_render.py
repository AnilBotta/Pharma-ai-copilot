"""Renderers for the validation report. They read; they never decide.

ONE OBJECT, THREE OUTPUTS

`ValidationReport` is assembled once from the canonical dossier. JSON, Markdown
and HTML are three views of that one object, and the UI consumes the JSON. None
of them looks up a status, a tier or a citation for itself.

That is the whole architectural point. Three renderers that each reached into
`spec` would be three chances to phrase a regulatory claim differently, and the
one a customer read would be whichever we happened not to review.

HOUSE STYLE

A QA document, not a brochure. No superlatives, no reassurance, no colour used
to mean "fine". Statuses are spelled the way the engine spells them, and every
capability carries its qualification in the same visual weight as its status -
a badge a reader can see from across the room, with the caveat in six-point
grey underneath, is a design that lies.
"""

from __future__ import annotations

import html
from typing import Any

from be_stats.dossier.report import ValidationReport

# --------------------------------------------------------------- markdown ---


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    def cell(value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return lines


def render_report_markdown(report: ValidationReport) -> str:
    data = report.to_dict()
    identity = data["identity"]
    lines: list[str] = [
        "# Statistical validation report",
        "",
        f"`be-stats` {identity['be_stats_version']}",
        "",
        "This report describes what the bioequivalence engine can do, what has",
        "been checked about it, against whose authority, and what remains",
        "outstanding. It is generated from the engine's own canonical records.",
        "",
        "## How to read this report",
        "",
    ]
    for note in data["reading_notes"].values():
        lines += [f"- {note}", ""]

    lines += [
        "## Report identity",
        "",
        "*Generated metadata. Describes the build that produced this document,",
        "not the regulatory evidence it reports.*",
        "",
    ]
    lines += _md_table(
        ["field", "value"],
        [
            ["schema", identity["schema"]],
            ["be-stats version", identity["be_stats_version"]],
            ["git SHA", identity["git_sha"]],
            ["generated at", identity["generated_at"]],
            ["audience", identity["audience"]],
            ["python", identity["runtime"].get("python", "")],
            ["platform", identity["runtime"].get("platform", "")],
        ],
    )
    lines.append("")

    # ------------------------------------------------------ capabilities ---
    lines += [
        "## Capability status",
        "",
        "`implementation` and `validation` are two axes. A row that says",
        "*implemented* says the code runs; whether anybody may rely on it is",
        "the next column and only the next column.",
        "",
    ]
    lines += _md_table(
        [
            "capability",
            "regulator",
            "implementation",
            "validation",
            "shown as",
            "decides",
            "evidence established",
        ],
        [
            [
                f"`{c['capability_id']}`",
                c["jurisdiction"],
                c["implementation_status"],
                c["validation_status"],
                c["display_status"],
                "yes" if c["decision_supported"] else "no",
                c["established_evidence_tier"],
            ]
            for c in data["capabilities"]
        ],
    )
    lines.append("")

    for c in data["capabilities"]:
        lines += [
            f"### `{c['capability_id']}` - {c['method']}",
            "",
            f"- **status shown to users** - {c['display_status']}",
            f"- **validation status** - {c['validation_status']}",
            f"- **qualification** - {c['qualification']}",
            f"- **produces a regulatory decision** - "
            f"{'yes' if c['decision_supported'] else 'no'}",
            f"- **design** - {c['design']}",
            f"- **endpoints** - {c['endpoints']}",
            f"- **regulatory source** - {c['regulatory_source']}",
            f"- **source pinned** - {'yes' if c['source_pinned'] else 'NO'}",
        ]
        if c["source_pinning_gap"]:
            lines.append(f"- **pinning gap** - {c['source_pinning_gap']}")
        if c["citation_exception"]:
            lines.append(f"- **citation exception** - {c['citation_exception']}")
        lines.append(
            f"- **submission-ready** - {'yes' if c['submission_ready'] else 'no'}"
        )
        lines.append(f"- **what this does NOT establish** - {c['does_not_establish']}")

        if c["explainability"]["limitations"]:
            lines += ["", "**Limitations**", ""]
            lines += [f"- {item}" for item in c["explainability"]["limitations"]]

        if c["evidence"]:
            lines += ["", "**Evidence**", ""]
            lines += _md_table(
                ["evidence", "tier", "what that tier means", "authority", "status"],
                [
                    [
                        f"`{e['evidence_id']}`",
                        e["tier"],
                        e["tier_meaning"],
                        e["source_authority"],
                        e["status"],
                    ]
                    for e in c["evidence"]
                ],
            )

        if c["refusal_conditions"]:
            lines += ["", "**Refuses when**", ""]
            lines += _md_table(
                ["code", "meaning", "lifted by"],
                [
                    [f"`{r['code']}`", r["meaning"], r["lifted_by"]]
                    for r in c["refusal_conditions"]
                ],
            )

        if c["blockers"] or c["open_findings"]:
            lines += ["", "**Outstanding**", ""]
            if c["blockers"]:
                lines.append(
                    "- blockers: " + ", ".join(f"`{b}`" for b in c["blockers"])
                )
            if c["open_findings"]:
                lines.append(
                    "- open findings: "
                    + ", ".join(f"`{f}`" for f in c["open_findings"])
                )
        lines.append("")

    # ---------------------------------------------------------- evidence ---
    lines += ["## Validation evidence by tier", ""]
    for tier, records in data["evidence_by_tier"].items():
        lines += [f"### {tier}", ""]
        if not records:
            lines += [
                "*No evidence of this tier exists in this package.* Shown as an",
                "explicit empty section rather than omitted: an absent heading",
                "and an empty one look identical, and only one means somebody",
                "checked.",
                "",
            ]
            continue
        lines += _md_table(
            ["evidence", "authority", "status", "scenario"],
            [
                [f"`{r['evidence_id']}`", r["source_authority"], r["status"], r["scenario"]]
                for r in records
            ],
        )
        lines.append("")

    # -------------------------------------------------------- provenance ---
    provenance = data["provenance"]
    coverage = provenance["coverage"]
    lines += [
        "## Source provenance",
        "",
        provenance["note"],
        "",
        f"- indexed constants: {coverage['total']}",
        f"- normative: {coverage['normative']}, of which pinned to authority, "
        f"document, section and version: **{coverage['normative_pinned']}"
        f"/{coverage['normative']}**",
        f"- normative with a declared citation exception: "
        f"{coverage['normative_exceptions']}",
        f"- derived: {coverage['derived']}, all stating a derivation and its "
        "inputs",
        f"- illustrative: {coverage['illustrative']}, consumed by no decision "
        "path",
        "",
    ]
    lines += _md_table(
        ["constant", "value", "authority", "document", "section", "version", "pinned"],
        [
            [
                f"`{r['constant_id']}`",
                f"{r['value']:g}",
                r["authority"],
                r["document"],
                r["section"] or "-",
                r["document_version"] or "-",
                "yes" if r["pinned"] else "NO",
            ]
            for r in provenance["normative"]
        ],
    )
    lines += ["", "### Derived values", ""]
    lines += _md_table(
        ["constant", "value", "derivation", "derived from", "read by"],
        [
            [
                f"`{r['constant_id']}`",
                f"{r['value']:g}",
                r["derivation"],
                ", ".join(r["derived_from"]),
                ", ".join(r["consumed_by"]) or "nothing",
            ]
            for r in provenance["derived"]
        ],
    )
    lines.append("")

    # ------------------------------------------------------- limitations ---
    limitations = data["limitations"]
    lines += ["## Outstanding limitations", "", limitations["note"], ""]

    lines += ["### Open findings", ""]
    if limitations["open_findings"]:
        lines += _md_table(
            ["finding", "severity", "affects", "description", "closed by"],
            [
                [
                    f"`{f['finding_id']}`",
                    f["severity"],
                    ", ".join(f["affected_capabilities"]) or "-",
                    f["description"],
                    f["resolution_condition"],
                ]
                for f in limitations["open_findings"]
            ],
        )
    else:
        lines.append("None.")
    lines.append("")

    lines += ["### Open blockers", ""]
    for blocker in limitations["open_blockers"]:
        lines += [
            f"**`{blocker['blocker_id']}`** - {blocker['summary']}",
            "",
            f"- affects: {', '.join(blocker['affected_capabilities']) or '-'}",
            f"- current behaviour: {blocker['current_behaviour']}",
            f"- resolved by: {blocker['required_evidence']}",
            "",
        ]

    lines += ["### Evidence not established", ""]
    lines += _md_table(
        ["evidence", "tier", "status", "why"],
        [
            [f"`{e['evidence_id']}`", e["tier"], e["status"], e["why"]]
            for e in limitations["evidence_not_established"]
        ],
    )
    lines.append("")

    # -------------------------------------------------------- governance ---
    governance = data["governance"]
    lines += [
        "## Governance",
        "",
        f"- **release gate** - {'PASS' if governance['release_gate_passed'] else 'FAIL'}. "
        f"{governance['release_gate_meaning']}",
        f"- **partial-replicate oracle ready** - "
        f"{str(governance['partial_oracle_ready']).lower()}",
        f"- **real SAS oracle evidence** - {governance['real_sas_oracle_status']}",
        f"- **promotion policy** - {governance['promotion_policy']}",
        f"- **data scope** - {governance['tenancy']}",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------- html ---

_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto,
       Helvetica, Arial, sans-serif; margin: 0; background: #fbfbfa;
       color: #1a1a1a; }
main { max-width: 60rem; margin: 0 auto; padding: 2.5rem 1.25rem 5rem; }
h1 { font-size: 1.65rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 .75rem; padding-bottom: .35rem;
     border-bottom: 1px solid #e2e0dc; }
h3 { font-size: .98rem; margin: 1.75rem 0 .5rem; }
p, li { margin: .4rem 0; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
       font-size: .87em; background: #f0efec; padding: .1em .35em;
       border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: .75rem 0;
        font-size: .86rem; }
th, td { text-align: left; vertical-align: top; padding: .45rem .6rem;
         border-bottom: 1px solid #e6e4e0; }
th { font-weight: 600; background: #f4f3f0; }
.scroll { overflow-x: auto; }
.note { background: #f4f3f0; border-left: 3px solid #c9c6c0;
        padding: .7rem .9rem; margin: 1rem 0; font-size: .88rem; }
.status { display: inline-block; font-size: .75rem; font-weight: 600;
          padding: .12rem .5rem; border-radius: 3px; border: 1px solid; }
.s-validated { border-color: #7a9a7e; background: #eef4ef; color: #2f5136; }
.s-pending  { border-color: #b39a63; background: #f7f2e6; color: #6b5320; }
.s-none     { border-color: #b0aca5; background: #f1efec; color: #4a4741; }
.qual { margin: .35rem 0 .6rem; }
.cap { border: 1px solid #e6e4e0; border-radius: 6px; padding: 1rem 1.15rem;
       margin: 1rem 0; background: #fff; }
.k { color: #5c584f; }
footer { margin-top: 3rem; font-size: .8rem; color: #5c584f; }
@media (prefers-color-scheme: dark) {
  body { background: #16161a; color: #e8e6e3; }
  h2 { border-bottom-color: #33323a; }
  th { background: #22222a; }
  th, td { border-bottom-color: #2c2c34; }
  code { background: #24242c; }
  .note { background: #1e1e25; border-left-color: #45444e; }
  .cap { background: #1b1b21; border-color: #2f2f38; }
  .s-validated { border-color: #4d6b53; background: #1c2a20; color: #a9cdb0; }
  .s-pending  { border-color: #7a683f; background: #2a2418; color: #ddc389; }
  .s-none     { border-color: #4a4850; background: #232329; color: #b6b2ab; }
  .k, footer { color: #a5a199; }
}
"""


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _status_class(display_status: str) -> str:
    if display_status == "VALIDATED":
        return "s-validated"
    if display_status == "NOT IMPLEMENTED":
        return "s-none"
    return "s-pending"


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def render_report_html(report: ValidationReport) -> str:
    """A self-contained page. No external requests, no scripts, no fonts.

    Deliberately dependency-free: a report a reviewer saves and opens two years
    later must not need a CDN to render, and a document that phones home is not
    one an auditor should be handed.
    """
    data = report.to_dict()
    identity = data["identity"]
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Statistical validation report - be-stats "
        f"{_e(identity['be_stats_version'])}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        "<h1>Statistical validation report</h1>",
        f"<p class=\"k\">be-stats {_e(identity['be_stats_version'])} &middot; "
        f"generated {_e(identity['generated_at'])} &middot; "
        f"audience: {_e(identity['audience'])}</p>",
        "<p>This report describes what the bioequivalence engine can do, what "
        "has been checked about it, against whose authority, and what remains "
        "outstanding. It is generated from the engine's own canonical "
        "records.</p>",
        "<h2>How to read this report</h2>",
    ]
    for note in data["reading_notes"].values():
        parts.append(f'<div class="note">{_e(note)}</div>')

    parts += [
        "<h2>Report identity</h2>",
        '<div class="note">Generated metadata. Describes the build that '
        "produced this document, not the regulatory evidence it reports.</div>",
        _html_table(
            ["field", "value"],
            [
                ["schema", identity["schema"]],
                ["be-stats version", identity["be_stats_version"]],
                ["git SHA", identity["git_sha"]],
                ["generated at", identity["generated_at"]],
                ["audience", identity["audience"]],
                ["python", identity["runtime"].get("python", "")],
                ["platform", identity["runtime"].get("platform", "")],
            ],
        ),
        "<h2>Capability status</h2>",
        "<p><code>implementation</code> and <code>validation</code> are two "
        "axes. A row that says <em>implemented</em> says the code runs; "
        "whether anybody may rely on it is the next column and only the next "
        "column.</p>",
        _html_table(
            [
                "capability",
                "regulator",
                "implementation",
                "validation",
                "shown as",
                "decides",
                "evidence established",
            ],
            [
                [
                    c["capability_id"],
                    c["jurisdiction"],
                    c["implementation_status"],
                    c["validation_status"],
                    c["display_status"],
                    "yes" if c["decision_supported"] else "no",
                    c["established_evidence_tier"],
                ]
                for c in data["capabilities"]
            ],
        ),
    ]

    for c in data["capabilities"]:
        parts.append('<div class="cap">')
        parts.append(
            f"<h3>{_e(c['capability_id'])} &mdash; {_e(c['method'])} "
            f'<span class="status {_status_class(c["display_status"])}">'
            f"{_e(c['display_status'])}</span></h3>"
        )
        parts.append(f'<p class="qual">{_e(c["qualification"])}</p>')
        rows = [
            ["validation status", c["validation_status"]],
            ["implementation status", c["implementation_status"]],
            [
                "produces a regulatory decision",
                "yes" if c["decision_supported"] else "no",
            ],
            ["design", c["design"]],
            ["endpoints", c["endpoints"]],
            ["regulatory source", c["regulatory_source"]],
            ["source pinned", "yes" if c["source_pinned"] else "NO"],
            ["submission-ready", "yes" if c["submission_ready"] else "no"],
        ]
        if c["source_pinning_gap"]:
            rows.append(["pinning gap", c["source_pinning_gap"]])
        if c["citation_exception"]:
            rows.append(["citation exception", c["citation_exception"]])
        parts.append(_html_table(["field", "value"], rows))
        parts.append(
            f'<div class="note"><strong>What this does not establish.</strong> '
            f"{_e(c['does_not_establish'])}</div>"
        )
        if c["explainability"]["limitations"]:
            parts.append("<p><strong>Limitations</strong></p><ul>")
            parts += [
                f"<li>{_e(item)}</li>" for item in c["explainability"]["limitations"]
            ]
            parts.append("</ul>")
        if c["evidence"]:
            parts.append("<p><strong>Evidence</strong></p>")
            parts.append(
                _html_table(
                    ["evidence", "tier", "what that tier means", "authority", "status"],
                    [
                        [
                            e["evidence_id"],
                            e["tier"],
                            e["tier_meaning"],
                            e["source_authority"],
                            e["status"],
                        ]
                        for e in c["evidence"]
                    ],
                )
            )
        if c["refusal_conditions"]:
            parts.append("<p><strong>Refuses when</strong></p>")
            parts.append(
                _html_table(
                    ["code", "meaning", "lifted by"],
                    [
                        [r["code"], r["meaning"], r["lifted_by"]]
                        for r in c["refusal_conditions"]
                    ],
                )
            )
        parts.append("</div>")

    parts.append("<h2>Validation evidence by tier</h2>")
    for tier, records in data["evidence_by_tier"].items():
        parts.append(f"<h3>{_e(tier)}</h3>")
        if not records:
            parts.append(
                '<div class="note">No evidence of this tier exists in this '
                "package. Shown as an explicit empty section rather than "
                "omitted: an absent heading and an empty one look identical, "
                "and only one means somebody checked.</div>"
            )
            continue
        parts.append(
            _html_table(
                ["evidence", "authority", "status", "scenario"],
                [
                    [r["evidence_id"], r["source_authority"], r["status"], r["scenario"]]
                    for r in records
                ],
            )
        )

    provenance = data["provenance"]
    coverage = provenance["coverage"]
    parts += [
        "<h2>Source provenance</h2>",
        f'<div class="note">{_e(provenance["note"])}</div>',
        "<ul>",
        f"<li>indexed constants: {coverage['total']}</li>",
        f"<li>normative: {coverage['normative']}, of which pinned to "
        f"authority, document, section and version: "
        f"<strong>{coverage['normative_pinned']}/{coverage['normative']}"
        "</strong></li>",
        f"<li>normative with a declared citation exception: "
        f"{coverage['normative_exceptions']}</li>",
        f"<li>derived: {coverage['derived']}, all stating a derivation and "
        "its inputs</li>",
        f"<li>illustrative: {coverage['illustrative']}, consumed by no "
        "decision path</li>",
        "</ul>",
        _html_table(
            ["constant", "value", "authority", "document", "section", "version", "pinned"],
            [
                [
                    r["constant_id"],
                    f"{r['value']:g}",
                    r["authority"],
                    r["document"],
                    r["section"] or "-",
                    r["document_version"] or "-",
                    "yes" if r["pinned"] else "NO",
                ]
                for r in provenance["normative"]
            ],
        ),
        "<h3>Derived values</h3>",
        _html_table(
            ["constant", "value", "derivation", "derived from", "read by"],
            [
                [
                    r["constant_id"],
                    f"{r['value']:g}",
                    r["derivation"],
                    ", ".join(r["derived_from"]),
                    ", ".join(r["consumed_by"]) or "nothing",
                ]
                for r in provenance["derived"]
            ],
        ),
    ]

    limitations = data["limitations"]
    parts += [
        "<h2>Outstanding limitations</h2>",
        f'<div class="note">{_e(limitations["note"])}</div>',
        "<h3>Open findings</h3>",
    ]
    if limitations["open_findings"]:
        parts.append(
            _html_table(
                ["finding", "severity", "affects", "description", "closed by"],
                [
                    [
                        f["finding_id"],
                        f["severity"],
                        ", ".join(f["affected_capabilities"]) or "-",
                        f["description"],
                        f["resolution_condition"],
                    ]
                    for f in limitations["open_findings"]
                ],
            )
        )
    else:
        parts.append("<p>None.</p>")

    parts.append("<h3>Open blockers</h3>")
    for blocker in limitations["open_blockers"]:
        parts.append(
            f"<p><strong>{_e(blocker['blocker_id'])}</strong> &mdash; "
            f"{_e(blocker['summary'])}</p><ul>"
            f"<li>affects: {_e(', '.join(blocker['affected_capabilities']) or '-')}</li>"
            f"<li>current behaviour: {_e(blocker['current_behaviour'])}</li>"
            f"<li>resolved by: {_e(blocker['required_evidence'])}</li></ul>"
        )

    parts += [
        "<h3>Evidence not established</h3>",
        _html_table(
            ["evidence", "tier", "status", "why"],
            [
                [e["evidence_id"], e["tier"], e["status"], e["why"]]
                for e in limitations["evidence_not_established"]
            ],
        ),
    ]

    governance = data["governance"]
    parts += [
        "<h2>Governance</h2>",
        "<ul>",
        f"<li><strong>release gate</strong> &mdash; "
        f"{'PASS' if governance['release_gate_passed'] else 'FAIL'}. "
        f"{_e(governance['release_gate_meaning'])}</li>",
        f"<li><strong>partial-replicate oracle ready</strong> &mdash; "
        f"{_e(str(governance['partial_oracle_ready']).lower())}</li>",
        f"<li><strong>real SAS oracle evidence</strong> &mdash; "
        f"{_e(governance['real_sas_oracle_status'])}</li>",
        f"<li><strong>promotion policy</strong> &mdash; "
        f"{_e(governance['promotion_policy'])}</li>",
        f"<li><strong>data scope</strong> &mdash; {_e(governance['tenancy'])}</li>",
        "</ul>",
        f"<footer>{_e(identity['schema'])} &middot; "
        f"git {_e(identity['git_sha'])}</footer>",
        "</main></body></html>",
    ]
    return "".join(parts)
