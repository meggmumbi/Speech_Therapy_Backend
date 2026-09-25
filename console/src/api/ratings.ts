import { api, API_BASE, getToken } from "./client";

/** Mirrors app/api/ratings.py. */

export type Task = "pilot_label" | "study_rating" | "review";

export interface Clip {
  attempt_id: string;
  repeat_index: number;
  audio_url: string;
  exercise_type: string;
  word: string;
  sentence: string | null;
  target_feature: string | null;
}

export interface Queue {
  task: Task;
  total: number;
  remaining: number;
  features: { key: string; label: string }[];
  clips: Clip[];
}

export interface RatingSubmission {
  task: Task;
  attempt_id: string;
  repeat_index: number;
  correct: boolean | null;
  accuracy: number | null;
  wrong_feature: string | null;
  unusable: boolean;
  duration_ms: number;
}

export interface Agreement {
  task: Task;
  raters: string[];
  clips_rated: number;
  clips_by_everyone: number;
  fleiss_kappa: number | null;
  fleiss_band: string;
  pairs: { raters: string[]; clips: number; percent_agreement: number | null; kappa: number | null; kappa_band: string; accuracy_mean_abs_diff: number | null }[];
  within_rater: { rater: string; repeats: number; percent_agreement: number | null }[];
  disagreements: { attempt_id: string; target: string; votes: Record<string, boolean | null>; pipeline_said: string | null }[];
  unusable: number;
}

export interface Confusion {
  clips: number;
  both_correct: number;
  both_wrong: number;
  false_rejections: number;
  false_acceptances: number;
  false_rejection_rate: number | null;
  false_acceptance_rate: number | null;
  accuracy: number | null;
}

export interface AuditRow {
  attempt_id: string;
  target: string;
  sentence: string | null;
  exercise_type: string;
  target_feature: string | null;
  reason: string;
  human_correct: boolean;
  votes: number;
  pipeline_verdict: string | null;
  pipeline_score: number | null;
  transcript: string | null;
  disagree: boolean;
  recorded_at: string | null;
}

export interface Audit {
  task: Task;
  totals: Confusion;
  by_reason: Record<string, Confusion>;
  rows: AuditRow[];
}

export const ratings = {
  me: () => api<{ username: string; role: "researcher" | "rater" }>("auth/me"),
  queue: (task: Task, limit = 12) => api<Queue>("ratings/queue", { query: { task, limit } }),
  progress: (task: Task) => api<{ task: Task; total: number; rated: number }>("ratings/progress", { query: { task } }),
  submit: (body: RatingSubmission) => api<{ rating_id: string }>("ratings/", { method: "POST", json: body }),
  sample: (task: Task, per_stratum: number, repeat_fraction: number) =>
    api<{ task: Task; clips: number; repeats: number; note: string | null }>("ratings/sample", { method: "POST", json: { task, per_stratum, repeat_fraction } }),
  agreement: (task: Task) => api<Agreement>("ratings/agreement", { query: { task } }),
  audit: (task: Task) => api<Audit>("ratings/audit", { query: { task } }),
  exportPilot: () => api<{ labelled: number; rows: number; path: string; next: string }>("ratings/export", { query: { task: "pilot_label" } }),
  createRater: (username: string, password: string) => api<{ username: string }>("ratings/raters", { method: "POST", json: { username, password } }),
  raters: () => api<{ username: string; pilot_label: number; study_rating: number; review: number }[]>("ratings/raters"),
  /** Clip audio needs the token; a plain <audio src> cannot send one, so it is fetched as a blob. */
  clipBlob: async (relative: string): Promise<string> => {
    const res = await fetch(API_BASE + relative, { headers: { Authorization: `Bearer ${getToken() ?? ""}` } });
    if (!res.ok) throw new Error(`could not load audio (${res.status})`);
    return URL.createObjectURL(await res.blob());
  },
  studyExportUrl: () => `${API_BASE}ratings/export?task=study_rating`,
};
