import { useEffect, useMemo, useState } from "react";
import type { Feature, Item, ItemWrite, Vocabulary } from "../api/stimuli";
import { Notice } from "../components/Layout";

/**
 * One item, edited against its type.
 *
 * The form is shaped by the exercise type, because the spec is: a minimal
 * pair has two options and a key, a stress item has syllables and an index.
 * Everything is validated again on the server before it is written; this is
 * the same set of rules, applied early enough to fix in place.
 */

type Draft = {
  exercise_type: string;
  target_feature: string;
  match_key: string;
  description: string;
  // Spoken
  word: string;
  sentence: string;
  target_word: string;
  prompt: string;
  seconds: string;
  // Choice
  options: string[];
  answer: string;
  cue: string;
  stimulus_audio: string;
  // Syllables
  syllables: string[];
  answer_index: number | null;
  answer_indices: number[];
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
    target_feature: item.target_feature ?? "",
    match_key: item.match_key ?? "",
    description: item.description ?? "",
    word: str("word"), sentence: str("sentence"), target_word: str("target_word"),
    prompt: str("prompt"), seconds: typeof s.seconds === "number" ? String(s.seconds) : "30",
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
  return {
    exercise_type: t,
    spec,
    target_feature: d.target_feature || null,
    match_key: d.match_key.trim() || null,
    description: d.description.trim() || null,
  };
}

export function ItemEditor({
  item, vocabulary, onSave, onCancel, busy, error,
}: {
  item: Item | null;
  vocabulary: Vocabulary;
  onSave: (body: ItemWrite) => void;
  onCancel: () => void;
  busy: boolean;
  error: string | null;
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
    <form className="stack" onSubmit={(e) => { e.preventDefault(); onSave(toWrite(d)); }}>
      <div className="page-head">
        <h2>{item ? `Edit: ${item.name}` : "New item"}</h2>
        <div className="row">
          <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
      {error && <Notice tone="bad">{error}</Notice>}
      {locked && (
        <Notice tone="warn">
          {item!.attempts} attempt{item!.attempts === 1 ? "" : "s"} recorded against this item. Its type and content are fixed; the prompt wording, feature and match key can still change.
        </Notice>
      )}

      <div className="grid-2">
        <label className="field">
          <span>Exercise type</span>
          <select value={d.exercise_type} disabled={locked} onChange={(e) => setD(emptyDraft(e.target.value))}>
            {vocabulary.exercise_types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
          {type && <div className="hint">{type.description} {type.spoken ? "Answered by speaking." : "Answered by tapping."}</div>}
        </label>
        <label className="field">
          <span>Target feature</span>
          <select value={d.target_feature} onChange={(e) => set("target_feature", e.target.value)}>
            <option value="">—</option>
            {vocabulary.target_features.map((f: Feature) => <option key={f.key} value={f.key}>{f.label} ({f.example})</option>)}
          </select>
        </label>
      </div>

      {d.exercise_type === "repeat_word" && (
        <label className="field"><span>Word</span><input value={d.word} disabled={locked} onChange={(e) => set("word", e.target.value)} /></label>
      )}
      {d.exercise_type === "read_sentence" && (
        <div className="grid-2">
          <label className="field"><span>Sentence</span><input value={d.sentence} disabled={locked} onChange={(e) => set("sentence", e.target.value)} placeholder="The ship is leaving the port." /></label>
          <label className="field"><span>Target word</span><input value={d.target_word} disabled={locked} onChange={(e) => set("target_word", e.target.value)} placeholder="ship" />
            <div className="hint">Must appear in the sentence. Only this word is judged; the rest anchors the alignment.</div></label>
        </div>
      )}
      {d.exercise_type === "picture_describe" && (
        <div className="grid-2">
          <label className="field"><span>Prompt</span><input value={d.prompt} disabled={locked} onChange={(e) => set("prompt", e.target.value)} /></label>
          <label className="field"><span>Seconds</span><input type="number" min={5} max={60} value={d.seconds} disabled={locked} onChange={(e) => set("seconds", e.target.value)} /></label>
        </div>
      )}
      {d.exercise_type === "same_sound_match" && (
        <label className="field"><span>Cue word</span><input value={d.cue} disabled={locked} onChange={(e) => set("cue", e.target.value)} placeholder="hate" />
          <div className="hint">The word whose vowel the options are matched against. Must not also be an option.</div></label>
      )}
      {CHOICE_TYPES.has(d.exercise_type) && (
        <section className="card">
          <h3>Options</h3>
          <p className="hint">{d.exercise_type === "minimal_pair_id" ? "Exactly two, differing in one contrast." : "Three to five. The participant taps one."}</p>
          {d.options.map((o, i) => (
            <div className="row" key={i} style={{ marginBottom: 8 }}>
              <input value={o} disabled={locked} onChange={(e) => setOption(i, e.target.value)} style={{ maxWidth: 260 }} />
              <label className="row small"><input type="radio" name="answer" checked={d.answer === o && o !== ""} disabled={locked || !o} onChange={() => set("answer", o)} /> correct</label>
              {d.exercise_type !== "minimal_pair_id" && d.options.length > 3 && !locked && (
                <button type="button" className="btn-ghost" onClick={() => set("options", d.options.filter((_, j) => j !== i))}>Remove</button>
              )}
            </div>
          ))}
          {d.exercise_type !== "minimal_pair_id" && d.options.length < 5 && !locked && (
            <button type="button" className="btn-ghost" onClick={() => set("options", [...d.options, ""])}>Add option</button>
          )}
          {d.exercise_type === "minimal_pair_id" && (
            <label className="field" style={{ marginTop: 12 }}><span>Stimulus audio path</span>
              <input value={d.stimulus_audio} onChange={(e) => set("stimulus_audio", e.target.value)} placeholder="Recorded in the next console step" />
              <div className="hint">The participant hears one recording and taps which. Until a file is here this item cannot run.</div></label>
          )}
        </section>
      )}
      {SYLLABLE_TYPES.has(d.exercise_type) && (
        <section className="card">
          <h3>Syllables</h3>
          <label className="field"><span>Word</span><input value={d.word} disabled={locked} onChange={(e) => set("word", e.target.value)} placeholder="banana" /></label>
          <p className="hint">Break the word into syllables. They must spell it back exactly. {d.exercise_type === "stress_place" ? "Mark the one with primary stress." : "Mark every reduced (weak) syllable; there must be at least one strong one left."}</p>
          {d.syllables.map((syl, i) => (
            <div className="row" key={i} style={{ marginBottom: 8 }}>
              <input value={syl} disabled={locked} onChange={(e) => setSyllable(i, e.target.value)} style={{ maxWidth: 160 }} />
              {d.exercise_type === "stress_place" ? (
                <label className="row small"><input type="radio" name="stress" checked={d.answer_index === i} disabled={locked} onChange={() => set("answer_index", i)} /> stressed</label>
              ) : (
                <label className="row small"><input type="checkbox" checked={d.answer_indices.includes(i)} disabled={locked}
                  onChange={(e) => set("answer_indices", e.target.checked ? [...d.answer_indices, i].sort() : d.answer_indices.filter((x) => x !== i))} /> weak</label>
              )}
              {d.syllables.length > 2 && !locked && (
                <button type="button" className="btn-ghost" onClick={() => set("syllables", d.syllables.filter((_, j) => j !== i))}>Remove</button>
              )}
            </div>
          ))}
          {d.syllables.length < 8 && !locked && <button type="button" className="btn-ghost" onClick={() => set("syllables", [...d.syllables, ""])}>Add syllable</button>}
          {d.word && !spellsWord && <div className="error">Syllables do not spell "{d.word}".</div>}
        </section>
      )}

      <div className="grid-2">
        <label className="field"><span>Match key</span><input value={d.match_key} onChange={(e) => set("match_key", e.target.value)} placeholder="kit_fleece-say" />
          <div className="hint">Same key in list A, list B and the test set marks the same slot of the design.</div></label>
        <label className="field"><span>Prompt override</span><input value={d.description} onChange={(e) => set("description", e.target.value)} placeholder="Leave empty for the type's standard instruction" />
          <div className="hint">An instruction that varies between lists is itself a difficulty difference between them.</div></label>
      </div>
    </form>
  );
}
