"""Keep the database suites out of the unit-test run.

The files in this directory are standalone scripts, not pytest modules. They
require a live database, exercise it inside a transaction they roll back, and
execute their assertions at import time. pytest was therefore *running* them
during collection - which meant a database outage, or any failure inside one,
surfaced as "1 error during collection" and aborted the entire unit suite before
a single unit test ran.

Run them directly:

    python tests/db/test_readiness_engine.py
    python tests/db/test_phase_c_workflow.py

They are named `test_*` because that is what they are; the exclusion is here
rather than in a rename so the naming stays honest.
"""

collect_ignore_glob = ["*.py"]
