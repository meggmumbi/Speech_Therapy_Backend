import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Box, Button, Chip, LinearProgress, Paper, Stack, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ReplayIcon from "@mui/icons-material/Replay";
import { ratings, type Clip, type Task } from "../api/ratings";
import { PageHeader } from "../components/ui";

/**
 * Listen and judge. Blind: the target and the clip, nothing else.
 *
 * Built for speed, because someone rating three hundred clips does it in
 * seconds each or not at all. Space plays, the number keys rate, and the
 * next clip loads on its own. The time from load to rating is recorded with
 * every judgement; a rating made in 400 ms was not listened to.
 */
export function Rate({ role }: { role: "researcher" | "rater" }) {
  const qc = useQueryClient();
  const [task, setTask] = useState<Task>(role === "rater" ? "study_rating" : "pilot_label");
  const [index, setIndex] = useState(0);
  const [correct, setCorrect] = useState<boolean | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [wrong, setWrong] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadedAt = useRef<number>(Date.now());
  const audioRef = useRef<HTMLAudioElement>(null);

  const q = useQuery({ queryKey: ["queue", task], queryFn: () => ratings.queue(task), staleTime: 0 });
  const progress = useQuery({ queryKey: ["rating-progress", task], queryFn: () => ratings.progress(task) });
  const clip: Clip | undefined = q.data?.clips[index];

  // Fetch the clip with the token and hand the player a blob URL; a bare
  // <audio src> cannot send Authorization and participant audio is not public.
  useEffect(() => {
    let revoked: string | null = null;
    setAudioUrl(null);
    if (!clip) return;
    ratings.clipBlob(clip.audio_url).then((u) => { revoked = u; setAudioUrl(u); loadedAt.current = Date.now(); setTimeout(() => audioRef.current?.play().catch(() => undefined), 50); })
      .catch((e) => setError(e.message));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [clip?.attempt_id, clip?.repeat_index]);

  const reset = () => { setCorrect(null); setAccuracy(null); setWrong(null); };

  const submit = useMutation({
    mutationFn: (unusable: boolean) => ratings.submit({
      task, attempt_id: clip!.attempt_id, repeat_index: clip!.repeat_index,
      correct: unusable ? null : correct, accuracy: unusable ? null : accuracy,
      wrong_feature: unusable || correct ? null : wrong, unusable,
      duration_ms: Date.now() - loadedAt.current,
    }),
    onSuccess: () => {
      reset();
      qc.invalidateQueries({ queryKey: ["rating-progress", task] });
      if (q.data && index + 1 >= q.data.clips.length) { setIndex(0); qc.invalidateQueries({ queryKey: ["queue", task] }); }
      else setIndex((i) => i + 1);
    },
    onError: (e) => setError((e as Error).message),
  });

  const canSubmit = clip && correct !== null && (task === "pilot_label" || accuracy !== null || correct);
  const play = useCallback(() => { const a = audioRef.current; if (a) { a.currentTime = 0; a.play().catch(() => undefined); } }, []);

  // Keyboard: space plays, 1/0 or y/n decide, 1-5 rate accuracy after a "no", enter submits, u = unusable.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.code === "Space") { e.preventDefault(); play(); return; }
      if (e.key === "y" || (task === "pilot_label" && e.key === "1")) { setCorrect(true); return; }
      if (e.key === "n" || (task === "pilot_label" && e.key === "0")) { setCorrect(false); return; }
      if (task === "study_rating" && /^[1-5]$/.test(e.key)) { setAccuracy(Number(e.key)); return; }
      if (e.key === "u") { if (clip) submit.mutate(true); return; }
      if (e.key === "Enter" && canSubmit && !submit.isPending) submit.mutate(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [task, clip, canSubmit, play, submit]);

  const total = progress.data?.total ?? 0;
  const rated = progress.data?.rated ?? 0;

  return (
    <Box sx={{ maxWidth: 760 }}>
      <PageHeader
        title="Rate recordings"
        subtitle="You hear the recording and see the target. Nothing else about it is shown, on purpose."
        actions={role === "researcher" ? (
          <ToggleButtonGroup exclusive size="small" value={task} onChange={(_, v) => { if (v) { setTask(v); setIndex(0); reset(); } }}>
            <ToggleButton value="pilot_label">Pilot labels</ToggleButton>
            <ToggleButton value="study_rating">Study ratings</ToggleButton>
          </ToggleButtonGroup>
        ) : undefined}
      />
      <Stack spacing={2}>
        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
        <Box>
          <LinearProgress variant="determinate" value={total ? (rated / total) * 100 : 0} sx={{ height: 8, borderRadius: 4 }} />
          <Typography variant="caption" color="text.secondary">{rated} of {total} rated{q.data ? ` · ${q.data.remaining} to go` : ""}</Typography>
        </Box>

        {q.isLoading && <Typography color="text.secondary">Loading…</Typography>}
        {q.data && q.data.total === 0 && <Alert severity="info">No rating set has been built for this task yet.</Alert>}
        {q.data && q.data.total > 0 && q.data.remaining === 0 && <Alert severity="success">All done. Thank you.</Alert>}

        {clip && (
          <Paper sx={{ p: 4 }}>
            <Stack spacing={3} alignItems="center">
              <Typography variant="overline">{clip.sentence ? "Read aloud" : "Say the word"}{clip.repeat_index ? " · repeat" : ""}</Typography>
              <Typography sx={{ fontSize: clip.sentence ? 28 : 44, fontWeight: 700, textAlign: "center" }}>{clip.sentence ?? clip.word}</Typography>
              {clip.sentence && <Typography color="text.secondary">Judge the word <strong>{clip.word}</strong>.</Typography>}
              <Stack direction="row" spacing={1}>
                <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} onClick={play} disabled={!audioUrl}>Play</Button>
                <Button size="large" startIcon={<ReplayIcon />} onClick={play} disabled={!audioUrl}>Again</Button>
              </Stack>
              <audio ref={audioRef} src={audioUrl ?? undefined} preload="auto" />

              <Stack spacing={1.5} alignItems="center" sx={{ width: "100%" }}>
                <Typography variant="subtitle2">Was <strong>{clip.word}</strong> said correctly?</Typography>
                <ToggleButtonGroup exclusive value={correct} onChange={(_, v) => { if (v !== null) setCorrect(v); }}>
                  <ToggleButton value={true} color="success" sx={{ px: 4 }}>Yes (y)</ToggleButton>
                  <ToggleButton value={false} color="error" sx={{ px: 4 }}>No (n)</ToggleButton>
                </ToggleButtonGroup>

                {task === "study_rating" && (
                  <>
                    <Typography variant="subtitle2" sx={{ mt: 1 }}>How accurate overall? 1 = not at all, 5 = native-like</Typography>
                    <ToggleButtonGroup exclusive value={accuracy} onChange={(_, v) => { if (v !== null) setAccuracy(v); }}>
                      {[1, 2, 3, 4, 5].map((n) => <ToggleButton key={n} value={n} sx={{ px: 2.5 }}>{n}</ToggleButton>)}
                    </ToggleButtonGroup>
                  </>
                )}

                {correct === false && (
                  <>
                    <Typography variant="subtitle2" sx={{ mt: 1 }}>Which sound went wrong? Optional.</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="center">
                      {q.data!.features.map((f) => (
                        <Chip key={f.key} label={f.label} clickable color={wrong === f.key ? "primary" : "default"} onClick={() => setWrong(wrong === f.key ? null : f.key)} />
                      ))}
                      <Chip label="Something else" clickable color={wrong === "other" ? "primary" : "default"} onClick={() => setWrong(wrong === "other" ? null : "other")} />
                    </Stack>
                  </>
                )}
              </Stack>

              <Stack direction="row" spacing={1.5} sx={{ pt: 1 }}>
                <Button variant="contained" size="large" disabled={!canSubmit || submit.isPending} onClick={() => submit.mutate(false)}>Next (Enter)</Button>
                <Button color="inherit" disabled={submit.isPending} onClick={() => submit.mutate(true)}>Recording unusable (u)</Button>
              </Stack>
              <Typography variant="caption" color="text.secondary">Space plays. {task === "pilot_label" ? "1 = correct, 0 = not." : "y / n, then 1–5."}</Typography>
            </Stack>
          </Paper>
        )}
      </Stack>
    </Box>
  );
}
