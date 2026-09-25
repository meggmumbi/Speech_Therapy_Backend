import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { participants } from "../api/endpoints";
import { CEFR, COMMON_FIRST_LANGUAGES, MEDIUMS, VOICE_USE, type Participant, type ParticipantInput } from "../api/types";
import { Notice } from "../components/Layout";

/**
 * Enrolment, mirroring the tablet's form and the server's schema.
 *
 * Consent is a hard stop at save, as it is on the tablet. The rest is
 * optional: refusing to answer a background question is a legitimate choice
 * for a volunteer and not a reason to exclude anyone.
 */

type Draft = {
  participant_code: string;
  age: string;
  gender: string;
  first_language: string;
  other_languages: string;
  home_language: string;
  region_of_upbringing: string;
  english_onset_age: string;
  primary_medium_of_instruction: string;
  self_rated_english: string;
  voice_assistant_use: string;
  hearing_or_speech_difficulty: boolean;
  hearing_or_speech_note: string;
  consent_participation: boolean;
  consent_audio_retention: boolean;
  consent_date: string;
  notes: string;
};

const EMPTY: Draft = {
  participant_code: "", age: "", gender: "", first_language: "", other_languages: "",
  home_language: "", region_of_upbringing: "", english_onset_age: "",
  primary_medium_of_instruction: "", self_rated_english: "", voice_assistant_use: "",
  hearing_or_speech_difficulty: false, hearing_or_speech_note: "",
  consent_participation: false, consent_audio_retention: false,
  consent_date: new Date().toISOString().slice(0, 10), notes: "",
};

function fromParticipant(p: Participant): Draft {
  return {
    ...EMPTY,
    participant_code: p.participant_code ?? "",
    age: p.age?.toString() ?? "",
    gender: p.gender ?? "",
    first_language: p.first_language ?? "",
    other_languages: p.other_languages ?? "",
    home_language: p.home_language ?? "",
    region_of_upbringing: p.region_of_upbringing ?? "",
    english_onset_age: p.english_onset_age?.toString() ?? "",
    primary_medium_of_instruction: p.primary_medium_of_instruction ?? "",
    self_rated_english: p.self_rated_english ?? "",
    voice_assistant_use: p.voice_assistant_use ?? "",
    hearing_or_speech_difficulty: p.hearing_or_speech_difficulty,
    hearing_or_speech_note: p.hearing_or_speech_note ?? "",
    consent_participation: p.consent_participation,
    consent_audio_retention: p.consent_audio_retention,
    consent_date: p.consent_date ?? "",
    notes: p.notes ?? "",
  };
}

function toInput(d: Draft): ParticipantInput {
  const orNull = (s: string) => (s.trim() ? s.trim() : null);
  const intOrNull = (s: string) => (s.trim() ? Number(s) : null);
  return {
    participant_code: d.participant_code.trim().toUpperCase(),
    age: intOrNull(d.age),
    gender: orNull(d.gender),
    first_language: orNull(d.first_language),
    other_languages: orNull(d.other_languages),
    home_language: orNull(d.home_language),
    region_of_upbringing: orNull(d.region_of_upbringing),
    english_onset_age: intOrNull(d.english_onset_age),
    primary_medium_of_instruction: orNull(d.primary_medium_of_instruction),
    self_rated_english: orNull(d.self_rated_english),
    voice_assistant_use: orNull(d.voice_assistant_use),
    hearing_or_speech_difficulty: d.hearing_or_speech_difficulty,
    hearing_or_speech_note: orNull(d.hearing_or_speech_note),
    consent_participation: d.consent_participation,
    // Withdrawing participation withdraws audio retention with it; the
    // stored row must never say someone refused to take part while agreeing
    // to have their audio kept.
    consent_audio_retention: d.consent_participation && d.consent_audio_retention,
    consent_date: d.consent_participation ? orNull(d.consent_date) : null,
    notes: orNull(d.notes),
    areas_of_interest_ids: [],
  };
}

export function ParticipantForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const existing = useQuery({
    queryKey: ["participant", id],
    queryFn: () => participants.get(id!),
    enabled: editing,
  });
  useEffect(() => {
    if (existing.data) setDraft(fromParticipant(existing.data));
  }, [existing.data]);

  const save = useMutation({
    mutationFn: (input: ParticipantInput) =>
      editing ? participants.update(id!, input) : participants.create(input),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["participants"] });
      qc.invalidateQueries({ queryKey: ["participant", p.id] });
      navigate(`/participants/${p.id}`, { replace: true });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not save"),
  });

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!draft.participant_code.trim()) return setError("A participant code is required.");
    if (!draft.consent_participation) return setError("Consent to participate is required before saving.");
    save.mutate(toInput(draft));
  }

  return (
    <form onSubmit={submit} className="stack" style={{ maxWidth: 760 }}>
      <div className="page-head">
        <h1>{editing ? "Edit participant" : "Enrol participant"}</h1>
        <div className="row">
          <button type="button" className="btn-ghost" onClick={() => navigate(-1)}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</button>
        </div>
      </div>
      {error && <Notice tone="bad">{error}</Notice>}

      <section className="card">
        <h3>Identity</h3>
        <div className="grid-2">
          <label className="field">
            <span>Participant code</span>
            <input value={draft.participant_code} onChange={(e) => set("participant_code", e.target.value.toUpperCase())} placeholder="P21" />
            <div className="hint">The only identifier stored. The code-to-name link stays on paper.</div>
          </label>
          <label className="field">
            <span>Age</span>
            <input type="number" min={5} max={120} value={draft.age} onChange={(e) => set("age", e.target.value)} />
          </label>
          <label className="field">
            <span>Gender</span>
            <input value={draft.gender} onChange={(e) => set("gender", e.target.value)} />
          </label>
        </div>
      </section>

      <section className="card">
        <h3>Language background</h3>
        <p className="hint">Which English sounds a Kenyan speaker substitutes depends heavily on their first language. These are the analysis covariates and cannot be collected after the session.</p>
        <div className="grid-2">
          <label className="field">
            <span>First language</span>
            <input list="languages" value={draft.first_language} onChange={(e) => set("first_language", e.target.value)} />
            <datalist id="languages">{COMMON_FIRST_LANGUAGES.map((l) => <option key={l} value={l} />)}</datalist>
          </label>
          <label className="field">
            <span>Home language</span>
            <input list="languages" value={draft.home_language} onChange={(e) => set("home_language", e.target.value)} />
          </label>
          <label className="field">
            <span>Other languages</span>
            <input value={draft.other_languages} onChange={(e) => set("other_languages", e.target.value)} placeholder="Comma-separated, in order of fluency" />
          </label>
          <label className="field">
            <span>Region of upbringing</span>
            <input value={draft.region_of_upbringing} onChange={(e) => set("region_of_upbringing", e.target.value)} />
          </label>
          <label className="field">
            <span>Age of first sustained English</span>
            <input type="number" min={0} max={60} value={draft.english_onset_age} onChange={(e) => set("english_onset_age", e.target.value)} />
          </label>
          <label className="field">
            <span>Medium of instruction in lower primary</span>
            <select value={draft.primary_medium_of_instruction} onChange={(e) => set("primary_medium_of_instruction", e.target.value)}>
              <option value="">—</option>
              {MEDIUMS.map((m) => <option key={m} value={m}>{m.replace("_", " ")}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Self-rated English (CEFR)</span>
            <select value={draft.self_rated_english} onChange={(e) => set("self_rated_english", e.target.value)}>
              <option value="">—</option>
              {CEFR.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Voice assistant use</span>
            <select value={draft.voice_assistant_use} onChange={(e) => set("voice_assistant_use", e.target.value)}>
              <option value="">—</option>
              {VOICE_USE.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
        </div>
      </section>

      <section className="card">
        <h3>Screening</h3>
        <label className="check">
          <input type="checkbox" checked={draft.hearing_or_speech_difficulty} onChange={(e) => set("hearing_or_speech_difficulty", e.target.checked)} />
          <span>Reports a hearing or speech difficulty <span className="hint">Exclusion criterion; note it and decide before running.</span></span>
        </label>
        {draft.hearing_or_speech_difficulty && (
          <label className="field">
            <span>Note</span>
            <input value={draft.hearing_or_speech_note} onChange={(e) => set("hearing_or_speech_note", e.target.value)} />
          </label>
        )}
      </section>

      <section className="card">
        <h3>Consent</h3>
        <label className="check">
          <input type="checkbox" checked={draft.consent_participation} onChange={(e) => set("consent_participation", e.target.checked)} />
          <span>Consents to take part <span className="hint">Required. Nothing is saved without it.</span></span>
        </label>
        <label className="check">
          <input type="checkbox" disabled={!draft.consent_participation} checked={draft.consent_participation && draft.consent_audio_retention} onChange={(e) => set("consent_audio_retention", e.target.checked)} />
          <span>Consents to their recordings being kept <span className="hint">Separately refusable. Someone may take part while refusing to have audio retained.</span></span>
        </label>
        <label className="field" style={{ maxWidth: 240 }}>
          <span>Consent date</span>
          <input type="date" disabled={!draft.consent_participation} value={draft.consent_date} onChange={(e) => set("consent_date", e.target.value)} />
        </label>
      </section>

      <section className="card">
        <h3>Notes</h3>
        <textarea value={draft.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Anything worth knowing that is not a name." />
      </section>
    </form>
  );
}
