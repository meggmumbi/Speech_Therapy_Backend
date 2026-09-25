import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { stimuli, type Item } from "../api/stimuli";
import { Recorder } from "../audio/recorder";
import { Notice, Pill } from "../components/Layout";

/**
 * Record one speaker saying this item, listen back, keep it.
 *
 * The flow is record, hear it, then upload -- never record-and-upload in one
 * step. What the researcher approves here is exactly what every participant
 * will hear, on every presentation, so the listen-back is not a nicety.
 */
export function RecordingPanel({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const qc = useQueryClient();
  const recorder = useRef(new Recorder());
  const [recording, setRecording] = useState(false);
  const [take, setTake] = useState<Blob | null>(null);
  const [takeUrl, setTakeUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => () => { if (takeUrl) URL.revokeObjectURL(takeUrl); }, [takeUrl]);
  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const id = setInterval(() => setSeconds((Date.now() - started) / 1000), 100);
    return () => clearInterval(id);
  }, [recording]);
  // A new item selected: drop any take belonging to the previous one.
  useEffect(() => { setTake(null); setTakeUrl(null); setError(null); }, [item.id]);

  const upload = useMutation({
    mutationFn: (blob: Blob) => stimuli.uploadAudio(item.id, blob),
    onSuccess: () => { setTake(null); setTakeUrl(null); qc.invalidateQueries({ queryKey: ["items"] }); onChanged(); },
    onError: (e) => setError((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: () => stimuli.deleteAudio(item.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["items"] }); onChanged(); },
    onError: (e) => setError((e as Error).message),
  });

  async function toggle() {
    setError(null);
    try {
      if (!recording) {
        await recorder.current.start();
        setSeconds(0);
        setRecording(true);
      } else {
        const blob = await recorder.current.stop();
        setRecording(false);
        setTake(blob);
        setTakeUrl(URL.createObjectURL(blob));
      }
    } catch (e) {
      setRecording(false);
      setError(e instanceof Error ? e.message : "Microphone unavailable");
    }
  }

  const hasStored = Boolean(item.audio_url);
  const isPair = item.exercise_type === "minimal_pair_id";
  const say = isPair ? String((item.spec as Record<string, unknown>).answer ?? item.name) : (item.spec as Record<string, unknown>).sentence as string | undefined ?? item.name;

  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Model audio</h3>
        {hasStored ? <Pill tone="good">Recorded</Pill> : isPair ? <Pill tone="fair">Needed before this item can run</Pill> : <Pill>Optional</Pill>}
      </div>
      <p className="hint" style={{ marginTop: 8 }}>
        Say <strong>{say}</strong> once, naturally, in the accent you want modelled.
        {isPair && " This is the recording the participant identifies; say only the correct word, not both."}
        {" "}The same file plays on every presentation.
      </p>
      {error && <Notice tone="bad">{error}</Notice>}

      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className={recording ? "btn-danger" : "btn-accent"} onClick={toggle}>
          {recording ? `Stop (${seconds.toFixed(1)}s)` : "Record"}
        </button>
        {takeUrl && (
          <>
            <audio controls src={takeUrl} style={{ height: 36 }} />
            <button type="button" className="btn-primary" disabled={upload.isPending} onClick={() => take && upload.mutate(take)}>
              {upload.isPending ? "Saving…" : "Keep this take"}
            </button>
            <button type="button" className="btn-ghost" onClick={() => { setTake(null); setTakeUrl(null); }}>Discard</button>
          </>
        )}
      </div>

      {hasStored && !takeUrl && (
        <div className="row" style={{ marginTop: 12 }}>
          <span className="small muted">Stored:</span>
          <audio controls src={stimuli.audioUrl(item.id) + `?v=${encodeURIComponent(item.audio_url ?? "")}`} style={{ height: 36 }} />
          <button type="button" className="btn-ghost" disabled={remove.isPending} onClick={() => { if (confirm("Remove the stored recording?")) remove.mutate(); }}>Remove</button>
        </div>
      )}
    </section>
  );
}
