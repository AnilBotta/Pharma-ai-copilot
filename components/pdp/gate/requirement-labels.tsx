import type { Requirement } from "@/lib/api";
/** `analytical_lead` reads as "the Analytical Lead" in a sentence. */
export function roleLabel(key: string) {
  return `the ${key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())}`;
}

/**
 * Why the reader cannot approve this requirement, when they can approve
 * others. The button being merely greyed out invites the conclusion that the
 * app is broken, which is what actually happened during testing.
 */
export function approvalBarredReason(req: Requirement) {
  if (req.eligible_approvers.length === 0) {
    return "Nobody can approve this requirement — see the note above.";
  }
  // Three rules can bar you and the reader need not be told which: naming who
  // it is for answers the only question they have. Guessing the rule would
  // sometimes be wrong, since holding approval authority somewhere on the
  // project does not mean holding the role this requirement names.
  const needs = req.approver_role_key
    ? ` Approval here needs ${roleLabel(req.approver_role_key)}, and whoever confirms the acceptance criteria or owns the requirement is excluded.`
    : " Whoever confirms the acceptance criteria or owns the requirement is excluded.";
  return `This one is for ${nameList(
    req.eligible_approvers.map((a) => a.name)
  )}.${needs}`;
}

export function nameList(names: string[]) {
  if (names.length === 0) return "nobody";
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}
