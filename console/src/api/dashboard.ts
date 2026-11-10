import { api } from "./client";

/** Mirrors app/services/dashboard.py. */

export interface Dashboard {
  generated_at: string;
  participants: {
    enrolled: number; consented: number; needs_code: number; assigned: number;
    started: number; complete: number; excluded: number; target: number | null;
  };
  cells: { group: string; count: number }[];
  funnel: { step: string; label: string; started: number; completed: number }[];
  accuracy: {
    condition: "K" | "D"; attempts: number; accuracy: number | null;
    spoken_accuracy: number | null; tapped_accuracy: number | null; participants: number;
  }[];
  engagement: {
    attempts: number; gated: number; skipped: number; replays: number; slow_replays: number;
    helpfulness_ratings: number; helpfulness_mean: number | null;
  };
  ratings: { condition: "K" | "D"; n: number; godspeed: number | null; motivation: number | null; feedback_trust: number | null }[];
  quality: { day: string; clean: number; quiet: number; clipped: number; lost: number }[];
  recent: {
    session_id: string; participant: string; step: string | null; condition: "K" | "D" | null;
    started_at: string | null; completed: boolean; ended_early: boolean; attempts: number;
    unusable_recordings: number; flagged: boolean;
  }[];
  false_correction_rate: number | null;
  list_problems: string[];
}

export const dashboardApi = {
  get: (target?: number) => api<Dashboard>("study/dashboard", { query: { target } }),
};
