export type ProjectStatus = "Active" | "On Hold" | "Completed" | "Planning";
export type ProjectPriority = "Critical" | "High" | "Medium" | "Low";
export type PipelinePhase =
  | "Discovery"
  | "Preclinical"
  | "IND Enabling"
  | "Phase I"
  | "Phase II"
  | "Phase III";

export interface Project {
  id: string;
  name: string;
  code: string;
  indication: string;
  molecule: string;
  status: ProjectStatus;
  priority: ProjectPriority;
  phase: PipelinePhase;
  progress: number;
  owner: { name: string; initials: string; color: string };
  created: string;
  updated: string;
  budget?: string;
}

export interface PatentAlert {
  id: string;
  patent: string;
  title: string;
  owner: string;
  type: "New Filing" | "Expiry" | "Grant" | "Infringement Risk";
  severity: "high" | "medium" | "low";
  filed: string;
  summary: string;
}

export interface ResearchPaper {
  id: string;
  title: string;
  journal: string;
  year: number;
  citations: number;
  confidence: number;
  relevant: boolean;
  authors: string;
  doi: string;
}

export interface Report {
  id: string;
  title: string;
  type: "Patent Landscape" | "Development Plan" | "Scientific Review" | "Risk Assessment";
  project: string;
  status: "Ready" | "Generating" | "Draft";
  updated: string;
  pages: number;
  author: string;
}

export interface ActivityItem {
  id: string;
  agent: string;
  action: string;
  target: string;
  time: string;
  icon: "patent" | "literature" | "strategy" | "report" | "chat" | "project";
  meta?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  timestamp: string;
  sources?: string[];
}

export interface Citation {
  id: string;
  title: string;
  source: string;
  year: number;
  type: "Patent" | "Journal" | "Guideline" | "Clinical Trial";
}

export interface Conversation {
  id: string;
  title: string;
  project: string;
  messages: ChatMessage[];
  updated: string;
}

/* ---------- Agent domain models ---------- */

export interface PatentSummary {
  drug: string;
  molecule: string;
  patentsAnalyzed: number;
  jurisdictions: number;
  families: number;
  summary: string;
  owners: { name: string; share: number; country: string }[];
  keyClaims: string[];
  expiries: { year: number; patents: number; families: number; notes: string }[];
  opportunities: string[];
  risks: { title: string; level: "High" | "Medium" | "Low"; detail: string }[];
  timeline: { year: number; type: string; owner: string; patent: string; status: "Expired" | "Active" | "Pending" }[];
  score: { freedom: number; density: number; expiry: number };
}

export interface LiteratureReview {
  topic: string;
  papersAnalyzed: number;
  yearsSpan: string;
  journals: number;
  summary: string;
  advantages: { title: string; detail: string }[];
  disadvantages: { title: string; detail: string }[];
  publications: ResearchPaper[];
  comparison: { technology: string; profile: string; duration: string; payload: string; maturity: number; risks: string }[];
  gaps: { title: string; detail: string }[];
  confidence: number;
  methods: string;
}

export interface StrategyInput {
  disease: string;
  target: string;
  dosageForm: string;
  route: string;
}

export interface StrategyOutput {
  overview: string;
  roadmap: { phase: string; timeframe: string; activities: string[]; gate: string }[];
  cqas: { attribute: string; target: string; criticality: "Critical" | "Key" | "Non-Critical"; rationale: string }[];
  manufacturing: { strategy: string; highlights: string[] };
  analytical: { strategy: string; methods: string[] };
  timeline: { year: string; milestones: { label: string; status: "Done" | "In Progress" | "Planned" }[] }[];
  risks: { id: string; category: string; risk: string; likelihood: number; impact: number; mitigation: string }[];
}

export interface ReportSection {
  id: string;
  title: string;
  summary: string;
  content: { heading: string; body: string; bullets?: string[] }[];
}

export interface GeneratedReport {
  id: string;
  title: string;
  projectId: string;
  version: string;
  generated: string;
  sections: ReportSection[];
}

/* ---------- Settings ---------- */

export interface OrgProfile {
  name: string;
  industry: string;
  size: string;
  country: string;
  subscription: string;
  seats: number;
  storageUsed: number;
  storageTotal: number;
}

export interface UserProfile {
  name: string;
  email: string;
  title: string;
  department: string;
  initials: string;
  avatarColor: string;
}
