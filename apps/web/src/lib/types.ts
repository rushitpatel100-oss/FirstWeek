// Mirrors firstweek_core.contracts.RoleRealityReport as the API returns it.

export type Tier = "posting" | "blog" | "forum" | "interview";

export type Citation = {
  source_url: string;
  tier: Tier;
  quote: string;
  published: string | null;
};

export type Claim = {
  text: string;
  citations: Citation[];
  confidence: number;
  verification: "supported" | "partial" | "unsupported";
};

export type SkillStat = {
  skill_id: string;
  label: string;
  count: number;
  share: number;
  ci_low: number;
  ci_high: number;
  n: number;
};

export type Provenance = {
  stats_version: number;
  writer_model: string;
  verifier_model: string;
  removed: { section: string; text: string; stage: string; reason: string }[];
  /** "researched": kept in the repository, quotes checked by code (ADR 0027). */
  method?: "pipeline" | "researched";
};

export type Report = {
  archetype: string;
  country: string;
  sample_size: number;
  date_range: [string, string];
  summary: Claim[];
  asked_for: SkillStat[];
  responsibilities: Claim[];
  day_to_day: Claim[];
  typical_week: Claim[];
  pain_points: Claim[];
  provenance: Provenance | null;
};

export type RoleSummary = {
  slug: string;
  name: string;
  country: string;
  sample_size: number;
  published_at: string;
};

export type PublishedReport = {
  report_id: string;
  slug: string;
  name: string;
  published_at: string;
  report: Report;
};

export type GapLine = {
  skill_id: string;
  label: string;
  share: number;
  status: "have" | "transferable" | "missing";
  reason: string;
};

export type GapResult = { lines: GapLine[]; coverage: number; model: string };

export type ProjectTicket = {
  key: string;
  title: string;
  description: string;
  acceptance_criteria: string[];
  task_type: string;
  due_day: number;
  skills: string[];
};

export type Project = {
  blueprint: {
    archetype: string;
    scenario: string;
    company_context: string;
    tickets: ProjectTicket[];
  };
  files: Record<string, string>;
};

export type TestRun = { exit_code: number; output: string; timed_out: boolean; passed: boolean };

export type Review = { review: string; model: string; tests: TestRun };

export type Colleague = { key: string; name: string; role: string };

export type InternshipEvent = {
  day: number;
  kind: "message" | "ticket" | "meeting";
  sender: string;
  text: string;
  ticket: string | null;
};

export type Internship = { colleagues: Colleague[]; events: InternshipEvent[] };

export type Turn = { who: "you" | "them"; text: string };

export type Verdict = {
  summary: string;
  skills: { skill_id: string; score: number; evidence: string }[];
  went_well: string[];
  to_work_on: string[];
  next_step: string;
};

export type WeekReview = { verdict: Verdict; model: string; tests: TestRun };
