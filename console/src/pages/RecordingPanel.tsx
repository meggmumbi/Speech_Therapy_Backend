import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Chip, Stack, Typography } from "@mui/material";
import MicIcon from "@mui/icons-material/Mic";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import StopIcon from "@mui/icons-material/Stop";
import CheckIcon from "@mui/icons-material/Check";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { stimuli, type Item } from "../api/stimuli";
import { Recorder, fileToWav } from "../audio/recorder";
import { ConfirmDialog, Section } from "../components/ui";

/**
 * Record one speaker saying this item, listen back, keep it.
 *
 * The flow is record, hear it, then upload -- never record-and-upload in one
 * step. What the researcher approves here is exactly what every participant
 * will hear, on every presentation, so the listen-back is not a nicety.
 *
 * A file can stand in for the microphone: recorded on a phone, chosen here,
 * decoded and trimmed in the browser, then heard back and kept exactly like
 * a live take. Same listen-back, same upload, same stored format.
 */
export function RecordingPanel({ item, onChanged }: { item: Item; onChanged: () => void }) {
  const qc = useQueryClient();
  const recorder = useRef(new Recorder());
  const [recording, setRecording] = useState(false);
  const [take, setTake] = useState<Blob | null>(null);
  const [takeUrl, setTakeUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [decoding, setDecoding] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => () => { if (takeUrl) URL.revokeObjectURL(takeUrl); }, [takeUrl]);
  useEffect(() => {
    if (!recording) return;
    const started = Date.now();
    const id = setInterval(() => setSeconds((Date.now() - started) / 1000), 100);
    return () => clearInterval(id);
  }, [recording]);
  useEffect(() => { setTake(null); setTakeUrl(null); setError(null); }, [item.id]);

  const upload = useMutation({
    mutationFn: (blob: Blob) => stimuli.uploadAudio(item.id, blob),
    onSuccess: () => { setTake(null); setTakeUrl(null); qc.invalidateQueries({ queryKey: ["items"] }); onChanged(); },
    onError: (e) => setError((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: () => stimuli.deleteAudio(item.id),
    onSuccess: () => { setConfirmRemove(false); qc.invalidateQueries({ queryKey: ["items"] }); onChanged(); },
    onError: (e) => setError((e as Error).message),
  });

  async function toggle() {
    setError(null);
    try {
      if (!recording) { await recorder.current.start(); setSeconds(0); setRecording(true); }
      else { const blob = await recorder.current.stop(); setRecording(false); setTake(blob); setTakeUrl(URL.createObjectURL(blob)); }
    } catch (e) {
      setRecording(false);
      setError(e instanceof Error ? e.message : "Microphone unavailable");
    }
  }

  async function chooseFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setDecoding(true);
    try {
      const blob = await fileToWav(file);
      setTake(blob);
      setTakeUrl(URL.createObjectURL(blob));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that file");
    } finally {
      setDecoding(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const hasStored = Boolean(item.audio_url);
  const isPair = item.exercise_type === "minimal_pair_id";
  const spec = item.spec as Record<string, unknown>;
  const say = isPair ? String(spec.answer ?? item.name) : (typeof spec.sentence === "string" ? spec.sentence : item.name);

  return (
    <Section title="Model audio" actions={
      hasStored ? <Chip size="small" color="success" label="Recorded" />
        : isPair ? <Chip size="small" color="warning" label="Needed before this item can run" />
        : <Chip size="small" label="Optional" />}>
      <Typography variant="body2" color="text.secondary">
        Say <strong>{say}</strong> once, naturally, in the accent you want modelled.
        {isPair && " This is the recording the participant identifies; say only the correct word."}
        {" "}The same file plays on every presentation.
      </Typography>
      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}

      <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
        <Button variant="contained" color={recording ? "error" : "secondary"} startIcon={recording ? <StopIcon /> : <MicIcon />} onClick={toggle}>
          {recording ? `Stop (${seconds.toFixed(1)}s)` : "Record"}
        </Button>
        <Button variant="outlined" color="secondary" startIcon={<UploadFileIcon />} disabled={recording || decoding} onClick={() => fileInput.current?.click()}>
          {decoding ? "Reading…" : "Upload a recording"}
        </Button>
        <input ref={fileInput} type="file" accept="audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.opus" hidden onChange={(e) => chooseFile(e.target.files?.[0])} />
        {takeUrl && (
          <>
            <audio controls src={takeUrl} />
            <Button variant="contained" startIcon={<CheckIcon />} disabled={upload.isPending} onClick={() => take && upload.mutate(take)}>
              {upload.isPending ? "Saving…" : "Keep this take"}
            </Button>
            <Button onClick={() => { setTake(null); setTakeUrl(null); }}>Discard</Button>
          </>
        )}
      </Stack>

      {!takeUrl && !hasStored && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          No working microphone here? Record it on a phone and upload the file: it is converted, trimmed and played back for you to check before it is kept.
        </Typography>
      )}

      {hasStored && !takeUrl && (
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 2 }}>
          <Typography variant="body2" color="text.secondary">Stored:</Typography>
          <audio controls src={`${stimuli.audioUrl(item.id)}?v=${encodeURIComponent(item.audio_url ?? "")}`} />
          <Button size="small" color="inherit" startIcon={<DeleteOutlineIcon />} onClick={() => setConfirmRemove(true)}>Remove</Button>
        </Stack>
      )}
      <ConfirmDialog open={confirmRemove} title="Remove the stored recording?" text="The item will need a new recording before it can run." confirmLabel="Remove" danger busy={remove.isPending}
        onClose={() => setConfirmRemove(false)} onConfirm={() => remove.mutate()} />
    </Section>
  );
}
