"""PDP Operations & Stage-Gate Guardian.

Tracks a product development programme across Gate 0-7: what each gate demands,
who owns it, what evidence exists, who approved it, and whether the gate may
actually be reviewed.

The module's guarantee is NO FALSE GREEN. A requirement cannot be marked
complete because someone ticked a box, because there is no box: the schema has
no completion column and the API has no endpoint that writes one. Satisfaction
is computed from evidence, acceptance, approval and dependencies on every read.

That is the same shape as the research module's guarantee - a citation cannot
exist unless the source was retrieved - and for the same reason. A rule enforced
by structure survives contact with people in a hurry; a rule enforced by
convention does not.
"""
