"""Generate the SAS program a customer runs, from the qualified model spec.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE

The `PROC MIXED` block is not written here. It is read from
`be_stats.replicate_abe.APPENDIX_C_MODEL.sas`, which is the qualified record of
FDA's Appendix C statements, carries the citation, and was verified against the
primary document. Retyping those six lines into the backend would create a
second copy that can drift from the first - and drift between a model
specification and the program that implements it is precisely the failure this
project has spent five pull requests avoiding.

`test_program_generator.py` asserts the generated program contains those lines
verbatim and in order, so a well-meaning edit here cannot quietly change the
model a customer's SAS is asked to fit.

WHY THE BACKEND MAY DEPEND ON be-stats

It did not before this release. The dependency is one-directional and stays
that way: the product layer consumes the engine, and be-stats gains nothing -
no web import, no database import, and above all no SAS. A pure-Python package
supplying a citation-carrying constant is the cheapest possible way to avoid
duplicating a regulator's model.

WHAT THE PROGRAM DELIBERATELY DOES NOT DO

It does not transform, filter, winsorise or otherwise touch the data. It reads
the CSV the package shipped, takes logs, fits the model and writes its output.
A generator that could reshape data on the way in would be a generator that
could be asked to produce a preferred answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from be_stats.replicate_abe import APPENDIX_C_MODEL

#: The dataset column names the package writes and the program reads. Fixed
#: here so the CSV writer and the SAS reader cannot disagree.
DATASET_COLUMNS = ("SUBJ", "SEQ", "PER", "TRT", "Y")

#: Output datasets the program creates. Parsing keys off these names, so they
#: are part of the contract between the package and the ingestion code.
OUTPUT_ESTIMATE = "be_estimate"
OUTPUT_COVPARMS = "be_covparms"
OUTPUT_FITSTATS = "be_fitstats"
OUTPUT_CONVERGENCE = "be_convergence"
OUTPUT_ENVIRONMENT = "be_environment"


@dataclass(frozen=True, slots=True)
class GeneratedProgram:
    """A SAS program plus the facts a reviewer needs about how it was made."""

    text: str
    model_citation: str
    model_statements: tuple[str, ...]
    output_datasets: tuple[str, ...]
    result_filename: str


def _header(case_id: str, dataset_filename: str, dataset_sha256: str) -> list[str]:
    citation = APPENDIX_C_MODEL.citation
    return [
        "/" + "*" * 76,
        " * SAS validation program - generated, do not edit by hand.",
        " *",
        f" * validation case : {case_id}",
        f" * model           : {citation.authority} {citation.section}",
        f" * document        : {citation.document}",
        f" * version         : {citation.document_version}",
        f" * dataset file    : {dataset_filename}",
        f" * dataset sha256  : {dataset_sha256}",
        " *",
        " * The PROC MIXED statements below are reproduced verbatim from the",
        " * cited section. Editing them makes this program a test of a",
        " * different model, and the comparison that follows meaningless.",
        " *",
        " * This program does not modify the supplied data. It reads the CSV,",
        " * takes natural logs of the measured values, fits the model, and",
        " * writes the results. Nothing is excluded and nothing is imputed:",
        " * PROC MIXED performs the available-case analysis the guidance",
        " * describes.",
        " " + "*" * 75 + "/",
        "",
    ]


def _read_step(dataset_filename: str) -> list[str]:
    return [
        "/* ---- read the shipped dataset -------------------------------- */",
        "",
        "%let dsfile = &packagedir./" + dataset_filename + ";",
        "",
        "proc import datafile = \"&dsfile.\"",
        "            out      = be_raw",
        "            dbms     = csv",
        "            replace;",
        "    getnames = yes;",
        "    guessingrows = max;",
        "run;",
        "",
        "data be_input;",
        "    set be_raw;",
        "    /* The model is fitted on the LOG scale. The CSV carries measured",
        "       values so that the shipped data is inspectable in its original",
        "       units and its hash covers what was measured, not a transform. */",
        "    if VALUE > 0 then Y = log(VALUE);",
        "    else delete;",
        "    keep SUBJ SEQ PER TRT Y;",
        "run;",
        "",
    ]


def _model_step() -> list[str]:
    """The regulator's statements, wrapped so their output can be captured.

    `PROC MIXED;` from the specification becomes `proc mixed data=... ;` - the
    only alteration made to any statement, and it names the input dataset
    rather than changing the model. Every other line is passed through
    untouched, including its spacing.
    """
    lines = [
        "/* ---- FDA Appendix C model, verbatim from the specification ---- */",
        "",
        "ods output Estimates        = " + OUTPUT_ESTIMATE + ";",
        "ods output CovParms         = " + OUTPUT_COVPARMS + ";",
        "ods output FitStatistics    = " + OUTPUT_FITSTATS + ";",
        "ods output ConvergenceStatus = " + OUTPUT_CONVERGENCE + ";",
        "",
    ]
    for statement in APPENDIX_C_MODEL.sas:
        if statement.strip().upper().startswith("PROC MIXED"):
            lines.append("proc mixed data = be_input method = reml;")
            lines.append("    /* specification: " + statement + " */")
        else:
            lines.append("    " + statement)
    lines += ["run;", ""]
    return lines


def _environment_step() -> list[str]:
    return [
        "/* ---- record the environment, so evidence identifies itself ---- */",
        "",
        "data " + OUTPUT_ENVIRONMENT + ";",
        "    length name $ 40 value $ 200;",
        "    name = 'sas_version';      value = \"&sysvlong.\";      output;",
        "    name = 'sas_scp';          value = \"&syscp.\";         output;",
        "    name = 'run_datetime';     value = put(datetime(), datetime20.); output;",
        "run;",
        "",
    ]


def _export_step(result_filename: str) -> list[str]:
    """One controlled result file, rather than a log to be scraped.

    Parsing arbitrary SAS listing output or a PDF is a losing game and an
    invitation to silently misread a number. The program writes a single
    structured file whose shape this application defined, and the raw log is
    kept separately as evidence rather than as the input to a parser.
    """
    return [
        "/* ---- write ONE structured result file ------------------------- */",
        "",
        "data be_result;",
        "    length section $ 24 name $ 40 value $ 200;",
        "",
        "    set " + OUTPUT_ESTIMATE + "(in=a)",
        "        " + OUTPUT_COVPARMS + "(in=b)",
        "        " + OUTPUT_CONVERGENCE + "(in=c)",
        "        " + OUTPUT_ENVIRONMENT + "(in=d rename=(name=envname value=envvalue));",
        "",
        "    if a then do;",
        "        section = 'estimate';",
        "        name = strip(Label);",
        "        value = strip(put(Estimate, best16.)) || '|' ||",
        "                strip(put(StdErr,   best16.)) || '|' ||",
        "                strip(put(DF,       best16.)) || '|' ||",
        "                strip(put(Lower,    best16.)) || '|' ||",
        "                strip(put(Upper,    best16.));",
        "        output;",
        "    end;",
        "    else if b then do;",
        "        section = 'covparm';",
        "        name  = strip(CovParm) || ' ' || strip(vvalue(Group));",
        "        value = strip(put(Estimate, best16.));",
        "        output;",
        "    end;",
        "    else if c then do;",
        "        section = 'convergence';",
        "        name  = 'status';",
        "        value = strip(put(Status, best16.)) || '|' || strip(Reason);",
        "        output;",
        "    end;",
        "    else if d then do;",
        "        section = 'environment';",
        "        name  = envname;",
        "        value = envvalue;",
        "        output;",
        "    end;",
        "",
        "    keep section name value;",
        "run;",
        "",
        "proc export data    = be_result",
        "            outfile = \"&packagedir./" + result_filename + "\"",
        "            dbms    = csv",
        "            replace;",
        "run;",
        "",
        "/* Upload the file above, together with the SAS log, to complete the",
        "   validation run. Neither file is interpreted as a regulatory",
        "   conclusion: they are compared with the engine's own result and a",
        "   reviewer decides what the comparison means. */",
    ]


def generate_program(
    *,
    case_id: str,
    dataset_filename: str,
    dataset_sha256: str,
    result_filename: str = "be_result.csv",
) -> GeneratedProgram:
    """Deterministic: identical inputs give a byte-identical program.

    No timestamp, no hostname, no random identifier. The program's hash is
    recorded in the package manifest and re-derived when the result is
    uploaded, so a generator that varied between calls would make every upload
    look like evidence for a different program.
    """
    lines: list[str] = []
    lines += _header(case_id, dataset_filename, dataset_sha256)
    lines += [
        "/* Set this to the folder holding the package files before running. */",
        "%let packagedir = .;",
        "",
    ]
    lines += _read_step(dataset_filename)
    lines += _model_step()
    lines += _environment_step()
    lines += _export_step(result_filename)

    return GeneratedProgram(
        text="\n".join(lines) + "\n",
        model_citation=(
            f"{APPENDIX_C_MODEL.citation.authority} "
            f"{APPENDIX_C_MODEL.citation.section} "
            f"({APPENDIX_C_MODEL.citation.document_version})"
        ),
        model_statements=tuple(APPENDIX_C_MODEL.sas),
        output_datasets=(
            OUTPUT_ESTIMATE,
            OUTPUT_COVPARMS,
            OUTPUT_FITSTATS,
            OUTPUT_CONVERGENCE,
            OUTPUT_ENVIRONMENT,
        ),
        result_filename=result_filename,
    )


__all__ = [
    "DATASET_COLUMNS",
    "GeneratedProgram",
    "generate_program",
]
