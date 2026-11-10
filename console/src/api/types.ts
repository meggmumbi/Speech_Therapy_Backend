/** Mirrors app/schemas/child.py and app/api/study.py. */

export const MEDIUMS = ["english", "kiswahili", "mother_tongue", "mixed", "other"] as const;
export const CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
export const VOICE_USE = ["never", "rarely", "monthly", "weekly", "daily"] as const;
export const COMMON_FIRST_LANGUAGES = [
  "Gikuyu", "Dholuo", "Kamba", "Luhya", "Kalenjin", "Kisii", "Meru",
  "Maasai", "Somali", "Mijikenda", "Turkana", "Kiswahili", "English",
];

export interface ParticipantInput {
  participant_code: string;
  age?: number | null;
  gender?: string | null;
  first_language?: string | null;
  other_languages?: string | null;
  home_language?: string | null;
  region_of_upbringing?: string | null;
  english_onset_age?: number | null;
  primary_medium_of_instruction?: string | null;
  self_rated_english?: string | null;
  voice_assistant_use?: string | null;
  hearing_or_speech_difficulty: boolean;
  hearing_or_speech_note?: string | null;
  consent_participation: boolean;
  consent_audio_retention: boolean;
  consent_date?: string | null;
  notes?: string | null;
  areas_of_interest_ids?: string[];
}

export interface Participant extends Omit<ParticipantInput, "participant_code" | "areas_of_interest_ids"> {
  id: string;
  /** Null for rows enrolled before codes existed. */
  participant_code: string | null;
  created_at: string | null;
}

export interface StudyBlock {
  block: number;
  condition: "K" | "D";
  word_list: "A" | "B";
}

export interface Assignment {
  child_id: string;
  group_index: number;
  group: string;
  blocks: StudyBlock[];
  excluded: boolean;
  exclusion_reason: string | null;
  assigned_at: string | null;
  created?: boolean;
}

export interface StepRun {
  session_id: string;
  started_at: string | null;
  completed: boolean;
}

export interface Step {
  step: string;
  kind: "assessment" | "training";
  label: string;
  condition: "K" | "D" | null;
  block?: number;
  word_list?: string;
  done: StepRun | null;
}

export interface Plan {
  child_id: string;
  participant_code: string | null;
  assignment: Assignment | null;
  steps: Step[];
  unstamped_sessions: string[];
  list_problems: string[];
}

export interface Balance {
  per_group: Record<string, number>;
  condition_in_block_1?: Record<string, number>;
  list_in_block_1?: Record<string, number>;
  balanced?: boolean;
  max_cell_difference?: number;
  excluded: number;
  word_lists: Record<string, string | null>;
  list_problems: string[];
  [key: string]: unknown;
}

export interface QuestionnaireRow {
  session_id: string;
  condition: "K" | "D" | null;
  block: number | null;
  scores: Record<string, { mean: number | null; answered: number; items: number }> | null;
  answered: number;
  duration_seconds: number | null;
  instrument_version: string | null;
  comment: string | null;
}
