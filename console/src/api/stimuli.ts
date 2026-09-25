import { api, API_BASE } from "./client";

/** Mirrors app/api/authoring.py. */

export interface Category {
  id: string;
  name: string;
  description: string | null;
  study_role: "list_a" | "list_b" | "test" | null;
  difficulty_level: string | null;
  item_count: number;
  items_with_attempts: number;
  sessions: number;
}

export interface Item {
  id: string;
  category_id: string;
  name: string;
  description: string | null;
  exercise_type: string;
  spec: Record<string, unknown>;
  target_feature: string | null;
  match_key: string | null;
  position: number | null;
  audio_url: string | null;
  difficulty_level: string | null;
  /** Recorded attempts. Above zero, the type and spec are fixed. */
  attempts: number;
}

export interface ItemWrite {
  exercise_type: string;
  spec: Record<string, unknown>;
  target_feature?: string | null;
  match_key?: string | null;
  description?: string | null;
  audio_url?: string | null;
  position?: number | null;
}

export interface ExerciseType {
  key: string;
  label: string;
  spoken: boolean;
  scored_by_pipeline: boolean;
  construct: string;
  description: string;
}

export interface Feature {
  key: string;
  label: string;
  contrast: string;
  example: string;
}

export interface Vocabulary {
  exercise_types: ExerciseType[];
  target_features: Feature[];
  study_roles: string[];
}

export interface ImportReport {
  category: string;
  applied: boolean;
  valid: number;
  errors: { row?: number; match_key?: string | null; field?: string; problem: string }[];
  existing_items: number;
  existing_items_with_attempts: number;
  preview: { name: string; exercise_type: string; target_feature: string | null; match_key: string | null }[];
  message?: string;
}

export interface DesignCheck {
  sound: boolean;
  problems: string[];
  by_role: Record<string, {
    category: string;
    items: number;
    features: string[];
    exercise_types: string[];
    missing_feature: number;
    origin?: { from_list_a: number; from_list_b: number; novel: number };
  }>;
}

export const stimuli = {
  vocabulary: () => api<Vocabulary>("authoring/exercise-types"),
  categories: () => api<Category[]>("authoring/categories"),
  createCategory: (name: string, study_role: string | null) =>
    api<Category>("authoring/categories", { method: "POST", json: { name, study_role } }),
  setRole: (categoryId: string, study_role: string | null) =>
    api<{ study_role: string | null }>(`authoring/categories/${categoryId}/study-role`, {
      method: "PUT", json: { study_role },
    }),
  items: (categoryId: string) =>
    api<{ category: { id: string; name: string; study_role: string | null }; items: Item[] }>(
      `authoring/categories/${categoryId}/items`),
  createItem: (categoryId: string, body: ItemWrite) =>
    api<Item>(`authoring/categories/${categoryId}/items`, { method: "POST", json: body }),
  updateItem: (itemId: string, body: ItemWrite) =>
    api<Item>(`authoring/items/${itemId}`, { method: "PUT", json: body }),
  deleteItem: (itemId: string) => api<unknown>(`authoring/items/${itemId}`, { method: "DELETE" }),
  importItems: (categoryId: string, items: ItemWrite[], apply: boolean, replace: boolean) =>
    api<ImportReport>(`authoring/categories/${categoryId}/items/import`, {
      method: "POST", json: { items, apply, replace },
    }),
  validate: () => api<DesignCheck>("authoring/item-sets/validate"),

  // ---- model audio ----
  uploadAudio: (itemId: string, wav: Blob) => {
    const form = new FormData();
    form.append("audio", wav, "model.wav");
    return api<{ item_id: string; audio_url: string; duration_seconds: number }>(
      `authoring/items/${itemId}/audio`, { method: "POST", body: form });
  },
  deleteAudio: (itemId: string) => api<unknown>(`authoring/items/${itemId}/audio`, { method: "DELETE" }),
  /** Where the browser fetches the stored file from. Same base as every other call. */
  audioUrl: (itemId: string) => `${API_BASE}authoring/items/${itemId}/audio`,
};
