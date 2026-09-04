"""Generate the human-readable dossier from the canonical source.

WHY GENERATE RATHER THAN WRITE

Because hand-written status documentation is wrong within two releases, and
nobody notices, because nothing checks it. This repository already has the
evidence: `validation/findings/README.md` ends with "No finding is currently
OPEN" while `VAL-FDA-APPENDIX-C-002.json` has `status: OPEN`, and its table
lists five findings out of the nine that exist. Nobody was careless; the
document simply had no mechanism that could fail.

So the Markdown comes from the same objects the engine reads, and
`test_generated_documentation_matches_the_canonical_matrix` regenerates it and
compares. Editing the generated file fails the suite; changing a status
regenerates the file. The document cannot be wrong without the build going red.

THE OUTPUT IS FOR A PERSON

Generated does not mean unreadable. Each section opens with what it is for,
statuses are spelled the way a reviewer says them, and the tables are ordered
the way the questions come.
"""

from __future__ import annotations

from be_stats import __version__
from be_stats.dossier.blockers import (
    BLOCKERS,
    PARTIAL_ORACLE_READY,
    REAL_SAS_ORACLE_STATUS,
)
from be_stats.dossier.capabilities import CAPABILITY_MATRIX
from be_stats.dossier.catalogue import method_catalogue
from be_stats.dossier.constants import (
    CONSTANT_INDEX,
    ConstantKind,
    provenance_coverage,
    unpinned_normative_constants,
)
from be_stats.dossier.evidence import EVIDENCE_MANIFEST, SAS_EVIDENCE_INTAKE
from be_stats.dossier.findings import FINDINGS_REGISTER
from be_stats.dossier.refusals import REFUSALS
from be_stats.dossier.release_gate import check_release_gate
from be_stats.dossier.routing import ROUTING_MATRIX, UNSUPPORTED_COMBINATION
from be_stats.dossier.semantics import CONTRACT

#: Written into the generated file so nobody edits it by hand twice.
BANNER = (
    "<!-- GENERATED FILE. Do not edit.\n"
    "     Regenerate with:  python -m be_stats.dossier.render\n"
    "     Source of truth:  be_stats.dossier and be_stats.spec -->"
)


def _escape(text: str) -> str:
    """Make a cell safe for a Markdown table."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_escape(cell) for cell in row) + " |")
    return lines


def _capability_section() -> list[str]:
    lines = [
        "## Capability matrix",
        "",
        "Every method and capability, with the status it currently holds. The",
        "status column is read from `be_stats.spec`; it is not stored here and",
        "not stored twice anywhere.",
        "",
        "**`implementation` and `validation` are two axes.** A row that says",
        "`implemented` says the code runs. Whether anybody may rely on it is",
        "the next column and only the next column.",
        "",
    ]
    rows = []
    for record in CAPABILITY_MATRIX.values():
        rows.append(
            [
                f"`{record.capability_id}`",
                str(record.jurisdiction) if record.jurisdiction else "both",
                str(record.implementation_status),
                str(record.validation_status),
                str(record.evidence_tier),
                "yes" if record.decision_supported else "no",
            ]
        )
    lines += _table(
        [
            "capability",
            "regulator",
            "implementation",
            "validation",
            "evidence tier",
            "decides",
        ],
        rows,
    )
    lines.append("")
    lines.append("### Known limitations")
    lines.append("")
    for record in CAPABILITY_MATRIX.values():
        if not record.known_limitations:
            continue
        lines.append(f"**`{record.capability_id}`** - {record.title}")
        lines.append("")
        for limitation in record.known_limitations:
            lines.append(f"- {limitation}")
        lines.append("")
    return lines


def _routing_section() -> list[str]:
    lines = [
        "## Regulatory decision routing matrix",
        "",
        "Which test applies, before any data is read. A combination with no",
        "row does **not** fall back to the conventional interval - see the",
        "unsupported row at the end.",
        "",
    ]
    rows = []
    for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION):
        endpoints = (
            "all"
            if len(route.endpoints) == 3
            else (", ".join(str(e) for e in route.endpoints) or "n/a")
        )
        rows.append(
            [
                f"`{route.route_id}`",
                str(route.jurisdiction) if route.route_id != "UNSUPPORTED" else "any",
                str(route.drug_class) if route.route_id != "UNSUPPORTED" else "any",
                endpoints,
                str(route.method) if route.method else f"none ({route.raises})",
            ]
        )
    lines += _table(
        ["route", "regulator", "drug class", "endpoints", "method"], rows
    )
    lines.append("")
    for route in (*ROUTING_MATRIX, UNSUPPORTED_COMBINATION):
        lines.append(f"### `{route.route_id}`")
        lines.append("")
        lines.append(f"- **input classification** - {route.input_classification}")
        design = ", ".join(str(d) for d in route.design_requirement) or "not reached"
        lines.append(f"- **design required** - {design}")
        lines.append(f"- **decision rule** - {route.decision_rule}")
        lines.append(f"- **refusal behaviour** - {route.refusal_behaviour}")
        if route.refusal_conditions:
            codes = ", ".join(f"`{c}`" for c in route.refusal_conditions)
            lines.append(f"- **refusal codes** - {codes}")
        lines.append("")
    return lines


def _evidence_section() -> list[str]:
    lines = [
        "## Validation evidence manifest",
        "",
        "What has actually been checked, against what, and where it is",
        "re-established. A record whose environment was unavailable reads",
        "`skipped_environment_unavailable` and never `passed`.",
        "",
    ]
    rows = []
    for record in EVIDENCE_MANIFEST:
        rows.append(
            [
                f"`{record.evidence_id}`",
                str(record.tier),
                record.source_authority,
                str(record.status),
                ", ".join(f"`{c}`" for c in record.capabilities) or "-",
            ]
        )
    lines += _table(
        ["evidence", "tier", "authority", "status", "capabilities"], rows
    )
    lines.append("")
    for record in EVIDENCE_MANIFEST:
        lines.append(f"### `{record.evidence_id}`")
        lines.append("")
        lines.append(f"- **scenario** - {record.scenario}")
        lines.append(f"- **dataset** - {record.dataset}")
        lines.append(f"- **environment** - {record.software_environment}")
        lines.append(f"- **expected** - {record.expected}")
        lines.append(f"- **observed** - {record.observed}")
        lines.append(f"- **tolerance** - {record.tolerance}")
        lines.append(f"- **established by** - `{record.established_by}`")
        if record.artifact:
            lines.append(f"- **artefact (committed)** - `{record.artifact}`")
        if record.run_output:
            lines.append(
                f"- **run output (generated, not committed)** - "
                f"`{record.run_output}`"
            )
        if record.findings:
            lines.append(
                "- **findings** - " + ", ".join(f"`{f}`" for f in record.findings)
            )
        if record.note:
            lines.append(f"- **note** - {record.note}")
        lines.append("")

    lines += [
        "### How an accepted SAS result would enter this manifest",
        "",
        "Written down before there is anything to intake, because the day a",
        "real result arrives is the worst day to design the route it takes.",
        "",
        "```",
        *SAS_EVIDENCE_INTAKE.rstrip().splitlines(),
        "```",
        "",
    ]
    return lines


def _provenance_section() -> list[str]:
    coverage = provenance_coverage()
    unpinned = unpinned_normative_constants()

    lines = [
        "## Source provenance",
        "",
        "Every regulatory number, and why it is here.",
        "",
        "### Coverage",
        "",
        "Counted separately by kind, because the requirements differ and a",
        "single combined figure invites a stronger reading than the data",
        "supports. A derived value has no regulatory section because no",
        "regulator states it, and a normative value without one is",
        "outstanding work - collapsing the two into one denominator hides",
        "the second behind the first.",
        "",
        "The history is recorded in the CHANGELOG and in finding",
        "`DOSSIER-004`, and is deliberately not restated here: a document",
        "that reproduces a wrong claim in order to correct it hands the",
        "sentence to the next reader who quotes one line out of context.",
        "",
        f"**All {coverage['total']} indexed constants** carry an authority, a",
        "source label, a stated role and a verification classification -",
        f"{coverage['classified']}/{coverage['total']}.",
        "",
        f"**Normative ({coverage['normative']})** - the regulator wrote the",
        "number.",
        "",
        f"- pinned to authority, document, **section** and version - "
        f"**{coverage['normative_pinned']}/{coverage['normative']}**",
        f"- carrying a declared citation exception - "
        f"{coverage['normative_exceptions']}/{coverage['normative']}",
        f"- VERIFIED - {coverage['normative_verified']}/{coverage['normative']}",
        "",
        f"**Derived ({coverage['derived']})** - this package computed it.",
        "",
        f"- stating an explicit derivation - "
        f"{coverage['derived_with_derivation']}/{coverage['derived']}",
        f"- naming the normative inputs they derive from - "
        f"{coverage['derived_with_inputs']}/{coverage['derived']}",
        f"- carrying DERIVED status - "
        f"{coverage['derived_status']}/{coverage['derived']}",
        "",
        "A derived value is **not** given a regulatory section. No regulator",
        "states it, and inventing one to complete a percentage would be the",
        "exact failure this index exists to prevent.",
        "",
        f"**Illustrative ({coverage['illustrative']})** - present in a",
        "regulatory document, and not the rule.",
        "",
        f"- consumed by no decision path - "
        f"{coverage['illustrative_unconsumed']}/{coverage['illustrative']}",
        "",
    ]

    if unpinned:
        lines += [
            "### Normative constants not yet pinned",
            "",
            "Declared rather than absorbed. Each is excluded from the pinned",
            "count above and is tracked in the findings register; each is",
            "closed by reading a primary source, never by writing a section",
            "number from memory.",
            "",
        ]
        for record in unpinned:
            lines.append(f"**`{record.constant_id}`** = {record.value:g}")
            lines.append("")
            lines.append(record.citation_exception)
            lines.append("")

    lines += [
        "### Normative and derived are not interchangeable",
        "",
        "FDA states the highly-variable switch as `sWR = 0.294`.",
        "`sqrt(ln(1 + 0.30^2))` is `0.29356...`, and substituting it replaces",
        "the regulator's criterion with this package's arithmetic. Both are",
        "indexed, separately, and a test asserts they never collapse into one",
        "entry.",
        "",
    ]

    rows = []
    for record in CONSTANT_INDEX.values():
        section = record.section or ("declared exception" if record.citation_exception else "-")
        rows.append(
            [
                f"`{record.constant_id}`",
                f"{record.value:g}",
                str(record.kind),
                str(record.verification),
                record.document,
                section,
                record.document_version or "-",
                ", ".join(f"`{i}`" for i in record.derived_from) or "-",
            ]
        )
    lines += _table(
        [
            "constant",
            "value",
            "kind",
            "verification",
            "document",
            "section",
            "version",
            "derived from",
        ],
        rows,
    )
    lines.append("")
    lines.append("### Derived quantities and what they are not")
    lines.append("")
    for record in CONSTANT_INDEX.values():
        if record.kind is ConstantKind.NORMATIVE:
            continue
        lines.append(f"**`{record.constant_id}`** = `{record.derivation or 'n/a'}`")
        lines.append("")
        if record.derived_from:
            inputs = ", ".join(f"`{i}`" for i in record.derived_from)
            lines.append(f"Derived from: {inputs}")
            lines.append("")
        lines.append(f"{record.role}")
        if record.note:
            lines.append("")
            lines.append(record.note)
        lines.append("")
    return lines


def _refusal_section() -> list[str]:
    lines = [
        "## Refusal semantics",
        "",
        CONTRACT,
        "",
        "Every refusal names what would lift it. A refusal that cannot say",
        "that is a dead end rather than an answer.",
        "",
    ]
    rows = [
        [f"`{code}`", reason.summary, reason.lifted_by]
        for code, reason in REFUSALS.items()
    ]
    lines += _table(["code", "meaning", "lifted by"], rows)
    lines.append("")
    return lines


def _blocker_section() -> list[str]:
    lines = [
        "## Known blockers",
        "",
        f"- `partial_oracle_ready` = **{str(PARTIAL_ORACLE_READY).lower()}**",
        f"- `real_sas_oracle_status` = **{REAL_SAS_ORACLE_STATUS}**",
        "",
    ]
    for blocker in BLOCKERS.values():
        lines.append(f"### `{blocker.blocker_id}`")
        lines.append("")
        lines.append(f"- **status** - {blocker.status}")
        lines.append(
            "- **affects** - "
            + (", ".join(f"`{c}`" for c in blocker.affected_capabilities) or "-")
        )
        lines.append(f"- **summary** - {blocker.summary}")
        lines.append(f"- **required evidence** - {blocker.required_evidence}")
        if blocker.current_behaviour:
            lines.append(f"- **current behaviour** - {blocker.current_behaviour}")
        if blocker.candidate_evidence:
            lines.append("- **candidate evidence, none of it sufficient**")
            for candidate in blocker.candidate_evidence:
                lines.append(f"  - *{candidate.source}*")
                lines.append(f"    - establishes: {candidate.establishes}")
                lines.append(
                    f"    - insufficient because: {candidate.insufficient_because}"
                )
        if blocker.reference:
            lines.append(f"- **reference** - `{blocker.reference}`")
        lines.append("")
    return lines


def _findings_section() -> list[str]:
    lines = [
        "## Findings register",
        "",
        "Severity is about consequence for a claim, not about how surprising",
        "the finding was.",
        "",
    ]
    rows = [
        [
            f"`{f.finding_id}`",
            str(f.severity),
            str(f.status),
            ", ".join(f"`{c}`" for c in f.affected_capabilities) or "-",
        ]
        for f in FINDINGS_REGISTER
    ]
    lines += _table(["finding", "severity", "status", "affects"], rows)
    lines.append("")
    for finding in FINDINGS_REGISTER:
        lines.append(f"### `{finding.finding_id}`")
        lines.append("")
        lines.append(finding.description)
        lines.append("")
        lines.append(f"- **evidence** - {finding.evidence}")
        lines.append(f"- **resolution condition** - {finding.resolution_condition}")
        if finding.evidence_file:
            lines.append(f"- **file** - `{finding.evidence_file}`")
        if finding.blocker_id:
            lines.append(f"- **blocker** - `{finding.blocker_id}`")
        lines.append("")
    return lines


def _catalogue_section() -> list[str]:
    lines = [
        "## Method catalogue",
        "",
        "The user-facing view. Three states, one qualification each.",
        "",
    ]
    rows = [
        [
            entry.method,
            entry.jurisdiction,
            entry.design,
            entry.supported_endpoints,
            str(entry.status),
            entry.qualification,
        ]
        for entry in method_catalogue()
    ]
    lines += _table(
        ["method", "regulator", "design", "endpoints", "status", "qualification"],
        rows,
    )
    lines.append("")
    return lines


def _gate_section() -> list[str]:
    report = check_release_gate()
    lines = [
        "## Release gate",
        "",
        "Whether each capability's claimed status is supportable by the",
        "evidence recorded above. A `VALIDATED` claim needs tier-1B evidence",
        "that passed, a pinned source, no open blocking finding, no blocker,",
        "and an explicitly reviewed transition.",
        "",
        f"**Result: {'PASS' if report.passed else 'FAIL'}**",
        "",
    ]
    lines += ["```", *report.to_lines(), "```", ""]
    return lines


def render_dossier() -> str:
    """The whole document."""
    lines = [
        BANNER,
        "",
        "# Statistical validation dossier",
        "",
        f"`be-stats` {__version__}",
        "",
        "This document is generated from the canonical capability matrix. It",
        "states what this engine can do, what has been checked, against whose",
        "authority, and what remains unresolved.",
        "",
        "**Nothing here promotes anything.** A status changes only through the",
        "release gate, with a named reviewer recording the transition.",
        "",
        "---",
        "",
    ]
    lines += _catalogue_section()
    lines += ["---", ""]
    lines += _capability_section()
    lines += ["---", ""]
    lines += _routing_section()
    lines += ["---", ""]
    lines += _refusal_section()
    lines += ["---", ""]
    lines += _evidence_section()
    lines += ["---", ""]
    lines += _provenance_section()
    lines += ["---", ""]
    lines += _blocker_section()
    lines += ["---", ""]
    lines += _findings_section()
    lines += ["---", ""]
    lines += _gate_section()
    return "\n".join(lines).rstrip() + "\n"


#: Markers around the one generated region of an otherwise hand-written file.
#:
#: `validation/findings/README.md` is worth keeping as prose - it explains what
#: a finding IS, why status and classification are separate fields, and the
#: rule VAL-FDA-HVD-001 left behind. None of that can be generated. Its TABLE
#: of records can, and the hand-maintained one had gone stale in two ways at
#: once: it listed five of the nine findings, and it ended with "No finding is
#: currently OPEN" while VAL-FDA-APPENDIX-C-002 was open.
FINDINGS_TABLE_BEGIN = "<!-- BEGIN GENERATED findings table -->"
FINDINGS_TABLE_END = "<!-- END GENERATED findings table -->"


def render_findings_table() -> str:
    """The findings table alone, for splicing into the hand-written README."""
    rows = []
    for finding in FINDINGS_REGISTER:
        link = (
            f"[`{finding.finding_id}`]({finding.finding_id}.md)"
            if finding.evidence_file
            else f"`{finding.finding_id}`"
        )
        rows.append(
            [
                link,
                _escape(finding.description),
                str(finding.severity),
                str(finding.status),
            ]
        )
    lines = [
        FINDINGS_TABLE_BEGIN,
        "",
        "*Generated from `be_stats.dossier.findings`. Do not edit by hand;",
        "regenerate with `python -m be_stats.dossier.render <this file>`.*",
        "",
        *_table(["id", "subject", "severity", "status"], rows),
        "",
    ]

    open_ids = [f.finding_id for f in FINDINGS_REGISTER if f.is_open]
    if open_ids:
        lines.append(
            "Open: " + ", ".join(f"`{i}`" for i in open_ids) + "."
        )
    else:
        lines.append("No finding is currently open.")
    lines += ["", FINDINGS_TABLE_END]
    return "\n".join(lines)


def splice_findings_table(document: str) -> str:
    """Replace the marked region, leaving every other line untouched."""
    start = document.index(FINDINGS_TABLE_BEGIN)
    end = document.index(FINDINGS_TABLE_END) + len(FINDINGS_TABLE_END)
    return document[:start] + render_findings_table() + document[end:]


def main() -> int:
    import pathlib
    import sys

    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if target is None:
        sys.stdout.write(render_dossier())
        return 0

    # A file carrying the markers gets its table refreshed; anything else is
    # written as the whole dossier. One command, and no way to overwrite the
    # findings README's prose by passing the wrong path.
    if target.exists() and FINDINGS_TABLE_BEGIN in target.read_text(
        encoding="utf-8"
    ):
        document = splice_findings_table(target.read_text(encoding="utf-8"))
    else:
        document = render_dossier()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({len(document)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
