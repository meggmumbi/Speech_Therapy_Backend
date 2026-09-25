import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert, Autocomplete, Box, Button, Checkbox, FormControl, FormControlLabel, FormHelperText,
  InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import { participants } from "../api/endpoints";
import { CEFR, COMMON_FIRST_LANGUAGES, MEDIUMS, VOICE_USE, type Participant, type ParticipantInput } from "../api/types";
import { PageHeader, Section } from "../components/ui";

/**
 * Enrolment, mirroring the tablet's form and the server's schema.
 *
 * Consent is a hard stop at save, as it is on the tablet. The rest is
 * optional: refusing to answer a background question is a legitimate choice
 * for a volunteer and not a reason to exclude anyone.
 */

type Draft = {
  participant_code: string; age: string; gender: string;
  first_language: string; other_languages: string; home_language: string; region_of_upbringing: string;
  english_onset_age: string; primary_medium_of_instruction: string; self_rated_english: string; voice_assistant_use: string;
  hearing_or_speech_difficulty: boolean; hearing_or_speech_note: string;
  consent_participation: boolean; consent_audio_retention: boolean; consent_date: string; notes: string;
};

const EMPTY: Draft = {
  participant_code: "", age: "", gender: "", first_language: "", other_languages: "", home_language: "",
  region_of_upbringing: "", english_onset_age: "", primary_medium_of_instruction: "", self_rated_english: "",
  voice_assistant_use: "", hearing_or_speech_difficulty: false, hearing_or_speech_note: "",
  consent_participation: false, consent_audio_retention: false,
  consent_date: new Date().toISOString().slice(0, 10), notes: "",
};

function fromParticipant(p: Participant): Draft {
  return {
    ...EMPTY,
    participant_code: p.participant_code ?? "", age: p.age?.toString() ?? "", gender: p.gender ?? "",
    first_language: p.first_language ?? "", other_languages: p.other_languages ?? "", home_language: p.home_language ?? "",
    region_of_upbringing: p.region_of_upbringing ?? "", english_onset_age: p.english_onset_age?.toString() ?? "",
    primary_medium_of_instruction: p.primary_medium_of_instruction ?? "", self_rated_english: p.self_rated_english ?? "",
    voice_assistant_use: p.voice_assistant_use ?? "", hearing_or_speech_difficulty: p.hearing_or_speech_difficulty,
    hearing_or_speech_note: p.hearing_or_speech_note ?? "", consent_participation: p.consent_participation,
    consent_audio_retention: p.consent_audio_retention, consent_date: p.consent_date ?? "", notes: p.notes ?? "",
  };
}

function toInput(d: Draft): ParticipantInput {
  const orNull = (s: string) => (s.trim() ? s.trim() : null);
  const intOrNull = (s: string) => (s.trim() ? Number(s) : null);
  return {
    participant_code: d.participant_code.trim().toUpperCase(),
    age: intOrNull(d.age), gender: orNull(d.gender),
    first_language: orNull(d.first_language), other_languages: orNull(d.other_languages),
    home_language: orNull(d.home_language), region_of_upbringing: orNull(d.region_of_upbringing),
    english_onset_age: intOrNull(d.english_onset_age),
    primary_medium_of_instruction: orNull(d.primary_medium_of_instruction),
    self_rated_english: orNull(d.self_rated_english), voice_assistant_use: orNull(d.voice_assistant_use),
    hearing_or_speech_difficulty: d.hearing_or_speech_difficulty, hearing_or_speech_note: orNull(d.hearing_or_speech_note),
    consent_participation: d.consent_participation,
    // Withdrawing participation withdraws audio retention with it; the stored
    // row must never say someone refused to take part while agreeing to have
    // their audio kept.
    consent_audio_retention: d.consent_participation && d.consent_audio_retention,
    consent_date: d.consent_participation ? orNull(d.consent_date) : null,
    notes: orNull(d.notes), areas_of_interest_ids: [],
  };
}

const grid = { display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 } as const;

export function ParticipantForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const existing = useQuery({ queryKey: ["participant", id], queryFn: () => participants.get(id!), enabled: editing });
  useEffect(() => { if (existing.data) setDraft(fromParticipant(existing.data)); }, [existing.data]);

  const save = useMutation({
    mutationFn: (input: ParticipantInput) => (editing ? participants.update(id!, input) : participants.create(input)),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["participants"] });
      qc.invalidateQueries({ queryKey: ["participant", p.id] });
      navigate(`/participants/${p.id}`, { replace: true });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not save"),
  });

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!draft.participant_code.trim()) return setError("A participant code is required.");
    if (!draft.consent_participation) return setError("Consent to participate is required before saving.");
    save.mutate(toInput(draft));
  }

  return (
    <Box component="form" onSubmit={submit} sx={{ maxWidth: 800 }}>
      <PageHeader
        title={editing ? "Edit participant" : "Enrol participant"}
        actions={<>
          <Button onClick={() => navigate(-1)}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</Button>
        </>}
      />
      <Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}

        <Section title="Identity">
          <Box sx={grid}>
            <TextField label="Participant code" value={draft.participant_code} onChange={(e) => set("participant_code", e.target.value.toUpperCase())} placeholder="P21"
              helperText="The only identifier stored. The code-to-name link stays on paper." />
            <TextField label="Age" type="number" value={draft.age} onChange={(e) => set("age", e.target.value)} inputProps={{ min: 5, max: 120 }} />
            <TextField label="Gender" value={draft.gender} onChange={(e) => set("gender", e.target.value)} />
          </Box>
        </Section>

        <Section title="Language background">
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Which English sounds a Kenyan speaker substitutes depends heavily on their first language. These are the analysis covariates and cannot be collected after the session.
          </Typography>
          <Box sx={grid}>
            <Autocomplete freeSolo options={COMMON_FIRST_LANGUAGES} value={draft.first_language} onInputChange={(_, v) => set("first_language", v)}
              renderInput={(p) => <TextField {...p} label="First language" />} />
            <Autocomplete freeSolo options={COMMON_FIRST_LANGUAGES} value={draft.home_language} onInputChange={(_, v) => set("home_language", v)}
              renderInput={(p) => <TextField {...p} label="Home language" />} />
            <TextField label="Other languages" value={draft.other_languages} onChange={(e) => set("other_languages", e.target.value)} placeholder="Comma-separated, in order of fluency" />
            <TextField label="Region of upbringing" value={draft.region_of_upbringing} onChange={(e) => set("region_of_upbringing", e.target.value)} />
            <TextField label="Age of first sustained English" type="number" value={draft.english_onset_age} onChange={(e) => set("english_onset_age", e.target.value)} inputProps={{ min: 0, max: 60 }} />
            <FormControl>
              <InputLabel>Medium of instruction in lower primary</InputLabel>
              <Select label="Medium of instruction in lower primary" value={draft.primary_medium_of_instruction} onChange={(e) => set("primary_medium_of_instruction", e.target.value)}>
                <MenuItem value="">—</MenuItem>
                {MEDIUMS.map((m) => <MenuItem key={m} value={m}>{m.replace("_", " ")}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl>
              <InputLabel>Self-rated English (CEFR)</InputLabel>
              <Select label="Self-rated English (CEFR)" value={draft.self_rated_english} onChange={(e) => set("self_rated_english", e.target.value)}>
                <MenuItem value="">—</MenuItem>
                {CEFR.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
            <FormControl>
              <InputLabel>Voice assistant use</InputLabel>
              <Select label="Voice assistant use" value={draft.voice_assistant_use} onChange={(e) => set("voice_assistant_use", e.target.value)}>
                <MenuItem value="">—</MenuItem>
                {VOICE_USE.map((v) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
              </Select>
            </FormControl>
          </Box>
        </Section>

        <Section title="Screening">
          <FormControlLabel control={<Checkbox checked={draft.hearing_or_speech_difficulty} onChange={(e) => set("hearing_or_speech_difficulty", e.target.checked)} />}
            label="Reports a hearing or speech difficulty" />
          <FormHelperText sx={{ ml: 4, mt: -0.5 }}>Exclusion criterion; note it and decide before running.</FormHelperText>
          {draft.hearing_or_speech_difficulty && (
            <TextField sx={{ mt: 1.5 }} label="Note" value={draft.hearing_or_speech_note} onChange={(e) => set("hearing_or_speech_note", e.target.value)} />
          )}
        </Section>

        <Section title="Consent">
          <FormControlLabel control={<Checkbox checked={draft.consent_participation} onChange={(e) => set("consent_participation", e.target.checked)} />} label="Consents to take part" />
          <FormHelperText sx={{ ml: 4, mt: -0.5 }}>Required. Nothing is saved without it.</FormHelperText>
          <FormControlLabel sx={{ mt: 1 }} control={<Checkbox disabled={!draft.consent_participation} checked={draft.consent_participation && draft.consent_audio_retention} onChange={(e) => set("consent_audio_retention", e.target.checked)} />}
            label="Consents to their recordings being kept" />
          <FormHelperText sx={{ ml: 4, mt: -0.5 }}>Separately refusable. Someone may take part while refusing to have audio retained.</FormHelperText>
          <TextField sx={{ mt: 2, maxWidth: 260 }} label="Consent date" type="date" disabled={!draft.consent_participation} value={draft.consent_date} onChange={(e) => set("consent_date", e.target.value)} InputLabelProps={{ shrink: true }} />
        </Section>

        <Section title="Notes">
          <TextField multiline minRows={3} value={draft.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Anything worth knowing that is not a name." />
        </Section>
      </Stack>
    </Box>
  );
}
