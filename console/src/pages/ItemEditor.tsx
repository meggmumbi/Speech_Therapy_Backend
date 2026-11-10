import { useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Checkbox, FormControl, FormHelperText, IconButton, InputLabel,
  MenuItem, Radio, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import type { Item, ItemWrite, Vocabulary } from "../api/stimuli";

/**
 * One item, edited against its type.
 *
 * The form is shaped by the exercise type, because the spec is: a minimal
 * pair has two options and a key, a stress item has syllables and an index.
 * Everything is validated again on the server before it is written; this is
 * the same set of rules, applied early enough to fix in place.
 */

type Draft = {
  exercise_type: string; target_feature: string; match_key: string; description: string;
  word: string; sentence: string; target_word: string; prompt: string; seconds: string;
  options: string[]; answer: string; cue: string; stimulus_audio: string;
  syllables: string[]; answer_index: number | null; answer_indices: number[];
};

const CHOICE_TYPES = new Set(["minimal_pair_id", "odd_one_out", "same_sound_match", "syllable_count"]);
const SYLLABLE_TYPES = new Set(["schwa_spot", "stress_place"]);

function emptyDraft(type = "repeat_word"): Draft {
  return {
    exercise_type: type, target_feature: "", match_key: "", description: "",
    word: "", sentence: "", target_word: "", prompt: "", seconds: "30",
    options: type === "minimal_pair_id" ? ["", ""] : ["", "", ""], answer: "", cue: "", stimulus_audio: "",
    syllables: ["", ""], answer_index: null, answer_indices: [],
  };
}

function fromItem(item: Item): Draft {
  const s = item.spec as Record<string, unknown>;
  const str = (k: string) => (typeof s[k] === "string" ? (s[k] as string) : "");
  const list = (k: string) => (Array.isArray(s[k]) ? (s[k] as string[]) : []);
  return {
    ...emptyDraft(item.exercise_type),
    target_feature: item.target_feature ?? "", match_key: item.match_key ?? "", description: item.description ?? "",
    word: str("word"), sentence: str("sentence"), target_word: str("target_word"), prompt: str("prompt"),
    seconds: typeof s.seconds === "number" ? String(s.seconds) : "30",
    options: list("options").length ? list("options") : emptyDraft(item.exercise_type).options,
    answer: str("answer"), cue: str("cue"), stimulus_audio: str("stimulus_audio"),
    syllables: list("syllables").length ? list("syllables") : ["", ""],
    answer_index: typeof s.answer_index === "number" ? (s.answer_index as number) : null,
    answer_indices: Array.isArray(s.answer_indices) ? (s.answer_indices as number[]) : [],
  };
}

function toWrite(d: Draft): ItemWrite {
  const t = d.exercise_type;
  const clean = (xs: string[]) => xs.map((x) => x.trim()).filter(Boolean);
  let spec: Record<string, unknown>;
  if (t === "repeat_word") spec = { word: d.word.trim() };
  else if (t === "read_sentence") spec = { sentence: d.sentence.trim(), target_word: d.target_word.trim() };
  else if (t === "picture_describe") spec = { prompt: d.prompt.trim(), seconds: Number(d.seconds) || 30 };
  else if (t === "minimal_pair_id") spec = { options: clean(d.options), answer: d.answer.trim(), ...(d.stimulus_audio.trim() ? { stimulus_audio: d.stimulus_audio.trim() } : {}) };
  else if (t === "same_sound_match") spec = { cue: d.cue.trim(), options: clean(d.options), answer: d.answer.trim() };
  else if (CHOICE_TYPES.has(t)) spec = { options: clean(d.options), answer: d.answer.trim() };
  else if (t === "stress_place") spec = { word: d.word.trim(), syllables: clean(d.syllables), answer_index: d.answer_index ?? 0 };
  else spec = { word: d.word.trim(), syllables: clean(d.syllables), answer_indices: d.answer_indices };
  return { exercise_type: t, spec, target_feature: d.target_feature || null, match_key: d.match_key.trim() || null, description: d.description.trim() || null };
}

const grid = { display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 } as const;

export function ItemEditor({ item, vocabulary, onSave, onCancel, busy, error }: {
  item: Item | null; vocabulary: Vocabulary; onSave: (body: ItemWrite) => void; onCancel: () => void; busy: boolean; error: string | null;
}) {
  const [d, setD] = useState<Draft>(() => (item ? fromItem(item) : emptyDraft()));
  useEffect(() => setD(item ? fromItem(item) : emptyDraft()), [item]);
  const locked = (item?.attempts ?? 0) > 0;
  const type = useMemo(() => vocabulary.exercise_types.find((t) => t.key === d.exercise_type), [d.exercise_type, vocabulary]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const setOption = (i: number, v: string) => set("options", d.options.map((o, j) => (j === i ? v : o)));
  const setSyllable = (i: number, v: string) => set("syllables", d.syllables.map((o, j) => (j === i ? v : o)));
  const spellsWord = d.syllables.join("").replace(/\s/g, "").toLowerCase() === d.word.replace(/\s/g, "").toLowerCase();

  return (
    <Box component="form" onSubmit={(e) => { e.preventDefault(); onSave(toWrite(d)); }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h5">{item ? `Edit: ${item.name}` : "New item"}</Typography>
        <Stack direction="row" spacing={1}>
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        </Stack>
      </Box>
      <Stack spacing={2}>
        {error && <Alert severity="error">{error}</Alert>}
        {locked && <Alert severity="warning">{item!.attempts} attempt{item!.attempts === 1 ? "" : "s"} recorded against this item. Its type and content are fixed; the prompt wording, feature and match key can still change.</Alert>}

        <Box sx={grid}>
          <FormControl>
            <InputLabel>Exercise type</InputLabel>
            <Select label="Exercise type" value={d.exercise_type} disabled={locked} onChange={(e) => setD(emptyDraft(e.target.value as string))}>
              {vocabulary.exercise_types.map((t) => <MenuItem key={t.key} value={t.key}>{t.label}</MenuItem>)}
            </Select>
            {type && <FormHelperText>{type.description} {type.spoken ? "Answered by speaking." : "Answered by tapping."}</FormHelperText>}
          </FormControl>
          <FormControl>
            <InputLabel>Target feature</InputLabel>
            <Select label="Target feature" value={d.target_feature} onChange={(e) => set("target_feature", e.target.value as string)}>
              <MenuItem value="">—</MenuItem>
              {vocabulary.target_features.map((f) => <MenuItem key={f.key} value={f.key}>{f.label} ({f.example})</MenuItem>)}
            </Select>
          </FormControl>
        </Box>

        {d.exercise_type === "repeat_word" && <TextField label="Word" value={d.word} disabled={locked} onChange={(e) => set("word", e.target.value)} />}
        {d.exercise_type === "read_sentence" && (
          <Box sx={grid}>
            <TextField label="Sentence" value={d.sentence} disabled={locked} onChange={(e) => set("sentence", e.target.value)} placeholder="The ship is leaving the port." />
            <TextField label="Target word" value={d.target_word} disabled={locked} onChange={(e) => set("target_word", e.target.value)} placeholder="ship"
              helperText="Must appear in the sentence. Only this word is judged; the rest anchors the alignment." />
          </Box>
        )}
        {d.exercise_type === "picture_describe" && (
          <Box sx={grid}>
            <TextField label="Prompt" value={d.prompt} disabled={locked} onChange={(e) => set("prompt", e.target.value)} />
            <TextField label="Seconds" type="number" value={d.seconds} disabled={locked} onChange={(e) => set("seconds", e.target.value)} inputProps={{ min: 5, max: 60 }} />
          </Box>
        )}
        {d.exercise_type === "same_sound_match" && (
          <TextField label="Cue word" value={d.cue} disabled={locked} onChange={(e) => set("cue", e.target.value)} placeholder="hate"
            helperText="The word whose vowel the options are matched against. Must not also be an option." />
        )}

        {CHOICE_TYPES.has(d.exercise_type) && (
          <Box>
            <Typography variant="overline">Options</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{d.exercise_type === "minimal_pair_id" ? "Exactly two, differing in one contrast. Mark the correct one." : "Three to five. Mark the correct one."}</Typography>
            <Stack spacing={1}>
              {d.options.map((o, i) => (
                <Stack direction="row" spacing={1} alignItems="center" key={i}>
                  <Radio checked={d.answer === o && o !== ""} disabled={locked || !o} onChange={() => set("answer", o)} />
                  <TextField value={o} disabled={locked} onChange={(e) => setOption(i, e.target.value)} sx={{ maxWidth: 280 }} placeholder={`Option ${i + 1}`} />
                  {d.exercise_type !== "minimal_pair_id" && d.options.length > 3 && !locked && (
                    <IconButton size="small" onClick={() => set("options", d.options.filter((_, j) => j !== i))}><CloseIcon fontSize="small" /></IconButton>
                  )}
                </Stack>
              ))}
            </Stack>
            {d.exercise_type !== "minimal_pair_id" && d.options.length < 5 && !locked && (
              <Button size="small" startIcon={<AddIcon />} sx={{ mt: 1 }} onClick={() => set("options", [...d.options, ""])}>Add option</Button>
            )}
            {d.exercise_type === "minimal_pair_id" && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>The participant hears one recording and taps which word it was. Record it in the Model audio panel below after saving.</Typography>
            )}
          </Box>
        )}

        {SYLLABLE_TYPES.has(d.exercise_type) && (
          <Box>
            <Typography variant="overline">Syllables</Typography>
            <TextField sx={{ mt: 1, maxWidth: 320 }} label="Word" value={d.word} disabled={locked} onChange={(e) => set("word", e.target.value)} placeholder="banana" />
            <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>
              Break the word into syllables; they must spell it back exactly. {d.exercise_type === "stress_place" ? "Mark the one with primary stress." : "Mark every reduced (weak) syllable; at least one strong one must remain."}
            </Typography>
            <Stack spacing={1}>
              {d.syllables.map((syl, i) => (
                <Stack direction="row" spacing={1} alignItems="center" key={i}>
                  {d.exercise_type === "stress_place"
                    ? <Radio checked={d.answer_index === i} disabled={locked} onChange={() => set("answer_index", i)} />
                    : <Checkbox checked={d.answer_indices.includes(i)} disabled={locked}
                        onChange={(e) => set("answer_indices", e.target.checked ? [...d.answer_indices, i].sort() : d.answer_indices.filter((x) => x !== i))} />}
                  <TextField value={syl} disabled={locked} onChange={(e) => setSyllable(i, e.target.value)} sx={{ maxWidth: 160 }} placeholder={`Syllable ${i + 1}`} />
                  <Typography variant="body2" color="text.secondary">{d.exercise_type === "stress_place" ? "stressed" : "weak"}</Typography>
                  {d.syllables.length > 2 && !locked && <IconButton size="small" onClick={() => set("syllables", d.syllables.filter((_, j) => j !== i))}><CloseIcon fontSize="small" /></IconButton>}
                </Stack>
              ))}
            </Stack>
            {d.syllables.length < 8 && !locked && <Button size="small" startIcon={<AddIcon />} sx={{ mt: 1 }} onClick={() => set("syllables", [...d.syllables, ""])}>Add syllable</Button>}
            {d.word && !spellsWord && <FormHelperText error>Syllables do not spell "{d.word}".</FormHelperText>}
          </Box>
        )}

        <Box sx={grid}>
          <TextField label="Match key" value={d.match_key} onChange={(e) => set("match_key", e.target.value)} placeholder="kit_fleece-say"
            helperText="Same key in list A, list B and the test set marks the same slot of the design." />
          <TextField label="Prompt override" value={d.description} onChange={(e) => set("description", e.target.value)} placeholder="Leave empty for the type's standard instruction"
            helperText="An instruction that varies between lists is itself a difficulty difference between them." />
        </Box>
      </Stack>
    </Box>
  );
}
