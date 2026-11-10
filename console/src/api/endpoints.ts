import { api } from "./client";
import type { Assignment, Balance, Participant, ParticipantInput, Plan, QuestionnaireRow } from "./types";

// ---- auth ------------------------------------------------------------------
// The backend takes the credentials as query parameters; that is how the
// tablet app signs in, and the console signs in the same way.
export const auth = {
  login: (username: string, password: string) =>
    api<{ access_token: string; token_type: string }>("auth/login", {
      method: "POST",
      query: { username, password },
    }),
  logout: () => api<unknown>("auth/logout", { method: "POST" }).catch(() => undefined),
};

// ---- participants --------------------------------------------------------
export const participants = {
  list: () => api<Participant[]>("children/"),
  get: (id: string) => api<Participant>(`children/${id}`),
  create: (input: ParticipantInput) => api<Participant>("children/", { method: "POST", json: input }),
  update: (id: string, input: ParticipantInput) =>
    api<Participant>(`children/${id}`, { method: "PUT", json: input }),
  remove: (id: string) => api<unknown>(`children/${id}`, { method: "DELETE" }),
};

// ---- study ---------------------------------------------------------------
export const study = {
  plan: (childId: string) => api<Plan>(`study/participants/${childId}/plan`),
  assign: (childId: string) =>
    api<Assignment>(`study/participants/${childId}/assignment`, { method: "POST" }),
  exclude: (childId: string, reason: string) =>
    api<Assignment>(`study/participants/${childId}/exclude`, { method: "POST", json: { reason } }),
  balance: () => api<Balance>("study/balance"),
  questionnaires: (childId: string) =>
    api<{ child_id: string; responses: QuestionnaireRow[] }>(`measures/participants/${childId}/questionnaires`),
};
