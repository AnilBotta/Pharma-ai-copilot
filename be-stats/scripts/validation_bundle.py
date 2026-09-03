"""Produce a validation bundle for internal QA or statistical review.

    python be-stats/scripts/validation_bundle.py --out build/validation-bundle

Writes three files into the output directory:

    bundle.json      everything, machine-readable
    DOSSIER.md       the same content as a document a person reads
    SUMMARY.txt      the one screen a reviewer looks at first

CERTIFICATION IS A SEPARATE QUESTION FROM CI

Run with `--certify` and the command exits non-zero when anything is
unestablished - a comparison that skipped because R or Julia was missing, an
awaited piece of evidence, a release-gate violation. Without it the command
succeeds and REPORTS those things, which is the right behaviour for an
ordinary pull request where nobody has a licensed SAS or a pinned container.

The distinction matters because the alternative is a build that reports green
with half its validation not run. A missing environment is never a pass.

SECRETS

The bundle records environment variables from an allow-list in
`be_stats.dossier.bundle`. Nothing else from the environment reaches the
output, whatever it is named.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Importable when run as a script from anywhere in the repository.
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from be_stats.dossier.bundle import build_bundle  # noqa: E402
from be_stats.dossier.render import render_dossier  # noqa: E402


def _summary(bundle: dict) -> str:
    lines: list[str] = []
    lines.append("BE-STATS VALIDATION BUNDLE")
    lines.append("=" * 60)
    lines.append(f"be-stats           {bundle['be_stats_version']}")
    lines.append(f"git                {bundle['git']['sha']}")
    dirty = bundle["git"]["working_tree_dirty"]
    lines.append(
        "working tree       "
        + (
            "unknown"
            if dirty is None
            else ("DIRTY - this bundle does not describe that commit" if dirty else "clean")
        )
    )
    lines.append(f"generated          {bundle['generated_at']}")
    lines.append("")

    tests = bundle["test_summary"]
    if tests.get("supplied"):
        lines.append(
            f"tests              {tests['passed']} passed, "
            f"{tests['failures']} failed, {tests['errors']} errored, "
            f"{tests['skipped']} skipped"
        )
    else:
        lines.append(f"tests              not supplied - {tests['note']}")
    lines.append("")

    lines.append("CAPABILITY STATUS")
    counts: dict[str, int] = {}
    for record in bundle["capability_matrix"]:
        counts[record["validation_status"]] = (
            counts.get(record["validation_status"], 0) + 1
        )
    for status, count in sorted(counts.items()):
        lines.append(f"  {status:<28} {count}")
    lines.append("")

    lines.append("BLOCKERS")
    lines.append(f"  partial_oracle_ready       {bundle['blockers']['partial_oracle_ready']}")
    lines.append(f"  real_sas_oracle_status     {bundle['blockers']['real_sas_oracle_status']}")
    for blocker in bundle["blockers"]["records"]:
        lines.append(f"  {blocker['blocker_id']:<28} {blocker['status']}")
    lines.append("")

    lines.append("OPEN FINDINGS")
    open_findings = [f for f in bundle["findings"] if f["status"] == "open"]
    if not open_findings:
        lines.append("  none")
    for finding in open_findings:
        lines.append(f"  {finding['finding_id']:<32} {finding['severity']}")
    lines.append("")

    lines.append("PROVENANCE COVERAGE")
    for key, value in bundle["provenance"]["coverage"].items():
        lines.append(f"  {key:<28} {value}")
    lines.append("")

    gate = bundle["release_gate"]
    lines.append(f"RELEASE GATE       {'PASS' if gate['passed'] else 'FAIL'}")
    for result in gate["results"]:
        for violation in result["violations"]:
            lines.append(f"  FAIL {result['capability_id']}: {violation}")
    lines.append("")

    problems = bundle["certification_blockers"]
    lines.append(f"CERTIFICATION BLOCKERS  {len(problems)}")
    for problem in problems:
        lines.append(f"  - {problem}")
    lines.append("")
    lines.append(
        "A certification blocker is not a test failure. It means a claim is "
        "not currently established -"
    )
    lines.append(
        "most often because an external oracle environment was unavailable, "
        "which is never a pass."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="build/validation-bundle",
        help="Directory to write into (created if absent).",
    )
    parser.add_argument(
        "--junit-xml",
        default=None,
        help=(
            "A JUnit report from the test run being certified. Without it the "
            "bundle makes no claim about the suite."
        ),
    )
    parser.add_argument(
        "--certify",
        action="store_true",
        help=(
            "Exit non-zero if anything is unestablished. For a release or "
            "certification run, NOT for ordinary CI."
        ),
    )
    args = parser.parse_args(argv)

    bundle = build_bundle(junit_xml=args.junit_xml)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "bundle.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out / "DOSSIER.md").write_text(
        render_dossier(), encoding="utf-8", newline="\n"
    )
    summary = _summary(bundle)
    (out / "SUMMARY.txt").write_text(summary, encoding="utf-8", newline="\n")

    print(summary)
    print(f"written to {out.resolve()}")

    problems = bundle["certification_blockers"]
    if args.certify and problems:
        print(
            f"\nCERTIFICATION FAILED: {len(problems)} unestablished claim(s). "
            "See above.",
            file=sys.stderr,
        )
        return 1
    if problems:
        print(
            f"\n{len(problems)} certification blocker(s) recorded. This is not "
            "a build failure: run with --certify to make it one."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
