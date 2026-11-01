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
