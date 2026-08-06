import type { LucideIcon } from "lucide-react";
import {
  ClipboardCheck,
  FlaskConical,
  Microscope,
  Newspaper,
  ScrollText,
  ShieldCheck,
} from "lucide-react";

/**
 * Presentation metadata for the agents that make up the research workflow.
 *
 * This registry is deliberately limited to display concerns — label, blurb,
 * icon, colour. Everything factual about an agent (which model it used, how
 * long it ran, what it produced, whether it succeeded) comes from the backend
 * on a per-run basis and is never asserted here.
 *
 * `id` matches the LangGraph node name in `backend/app/graph/nodes/`, which is
 * how run events are mapped onto these cards.
 */

export type AgentId =
  | "supervisor"
  | "research_agent"
  | "literature_agent"
  | "patent_agent"
  | "development_strategy_agent"
  | "evidence_reviewer";

export interface AgentDefinition {
  id: AgentId;
  name: string;
  description: string;
  icon: LucideIcon;
  /** Tailwind text colour token used for the agent's accent. */
  color: string;
}

export const AGENT_REGISTRY: AgentDefinition[] = [
  {
    id: "supervisor",
    name: "Scientist Supervisor",
    description:
      "Interprets the objective, plans the work, routes it to specialists, reconciles their findings and synthesises the report.",
    icon: Microscope,
    color: "text-sky-600 dark:text-sky-400",
  },
  {
    id: "research_agent",
    name: "General Research Agent",
    description:
      "Establishes scientific and technical background, the target product profile and competing technologies.",
    icon: ScrollText,
    color: "text-teal-600 dark:text-teal-400",
  },
  {
    id: "literature_agent",
    name: "Literature Review Agent",
    description:
      "Builds search strategies, queries PubMed and Europe PMC, then categorises and extracts from what it retrieves.",
    icon: Newspaper,
    color: "text-emerald-600 dark:text-emerald-400",
  },
  {
    id: "patent_agent",
    name: "Patent Research Agent",
    description:
      "Translates the question into patent concepts and classifications, then searches EPO OPS and groups results by family.",
    icon: ShieldCheck,
    color: "text-indigo-600 dark:text-indigo-400",
  },
  {
    id: "development_strategy_agent",
    name: "Development Strategy Agent",
    description:
      "Derives a preliminary development strategy — CQAs, formulation pathway, analytical and nonclinical needs — from retrieved evidence only.",
    icon: FlaskConical,
    color: "text-violet-600 dark:text-violet-400",
  },
  {
    id: "evidence_reviewer",
    name: "Evidence & Citation Reviewer",
    description:
      "Verifies every citation resolves to a stored record, flags unsupported claims and contradictions, and rates section confidence.",
    icon: ClipboardCheck,
    color: "text-amber-600 dark:text-amber-400",
  },
];

const AGENTS_BY_ID = new Map(AGENT_REGISTRY.map((a) => [a.id, a]));

export function getAgent(id: string): AgentDefinition | undefined {
  return AGENTS_BY_ID.get(id as AgentId);
}

/**
 * Legal notice required on every surface that displays patent results.
 * Rendered verbatim — do not paraphrase.
 */
export const PATENT_DISCLAIMER =
  "This patent analysis is preliminary research support and is not a legal opinion, " +
  "validity analysis, infringement analysis, or freedom-to-operate opinion. " +
  "Consult qualified patent counsel.";

export const GENERAL_DISCLAIMER =
  "This platform provides research support only. It does not provide medical, " +
  "regulatory, toxicological, clinical, or legal decisions, and does not replace " +
  "qualified scientists, patent counsel, regulatory experts, toxicologists, " +
  "clinicians, or statisticians.";

export type { LucideIcon };
