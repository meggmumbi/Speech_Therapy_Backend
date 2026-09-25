import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Box, Button, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { ratings, type Task } from "../api/ratings";
import { PageHeader, Section, StatCard } from "../components/ui";

/**
 * The researcher's side of rating: build the sample, create rater accounts,
 * read the agreement, adjudicate disagreements, export.
 */
export function Ratings() {
  const qc = useQueryClient();
  const [task, setTask] = useState<Task>("study_rating");
  const [perStratum, setPerStratum] = useState("4");
  const [repeat, setRepeat] = useState("0.1");
  const [rater, setRater] = useState({ username: "", password: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const agreement = useQuery({ queryKey: ["agreement", task], queryFn: () => ratings.agreement(task) });
  const raters = useQuery({ queryKey: ["raters"], queryFn: ratings.raters });
  const fail = (e: unknown) => setError((e as Error).message);
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["agreement"] }); qc.invalidateQueries({ queryKey: ["raters"] }); qc.invalidateQueries({ queryKey: ["queue"] }); qc.invalidateQueries({ queryKey: ["rating-progress"] }); };

  const sample = useMutation({
    mutationFn: () => ratings.sample(task, Number(perStratum) || 4, Number(repeat) || 0.1),
    onSuccess: (r) => { setMsg(`${r.clips} clips + ${r.repeats} repeats in the ${task} set.${r.note ? " " + r.note : ""}`); invalidate(); }, onError: fail,
  });
  const create = useMutation({
    mutationFn: () => ratings.createRater(rater.username, rater.password),
    onSuccess: (r) => { setMsg(`Rater account ${r.username} created. They sign in at this console and see only the rating screen.`); setRater({ username: "", password: "" }); invalidate(); }, onError: fail,
  });
  const exportPilot = useMutation({
    mutationFn: ratings.exportPilot,
    onSuccess: (r) => setMsg(`${r.labelled} of ${r.rows} rows labelled in ${r.path}. Next: ${r.next}`), onError: fail,
  });

  const a = agreement.data;

  return (
    <Box sx={{ maxWidth: 1000 }}>
      <PageHeader title="Rating" subtitle="Build the sample, add raters, read the agreement, export." />
      <Stack spacing={2}>
        {msg && <Alert severity="success" onClose={() => setMsg(null)}>{msg}</Alert>}
        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          <Section title="Rating set">
            <Stack spacing={1.5}>
              <Stack direction="row" spacing={1}>
                <Chip label="Study ratings" clickable color={task === "study_rating" ? "primary" : "default"} onClick={() => setTask("study_rating")} />
                <Chip label="Pilot labels" clickable color={task === "pilot_label" ? "primary" : "default"} onClick={() => setTask("pilot_label")} />
              </Stack>
              {task === "study_rating" ? (
                <Typography variant="body2" color="text.secondary">Spoken items from stamped sessions with a clean recording, from participants who consented to retention, stratified by session type, condition and target feature.</Typography>
              ) : (
                <Typography variant="body2" color="text.secondary">The 78 pilot recordings, for refitting the verdict threshold on labels the pipeline did not influence.</Typography>
              )}
              <Stack direction="row" spacing={1}>
                {task === "study_rating" && <TextField label="Clips per stratum" type="number" value={perStratum} onChange={(e) => setPerStratum(e.target.value)} sx={{ width: 150 }} />}
                <TextField label="Repeat fraction" type="number" value={repeat} onChange={(e) => setRepeat(e.target.value)} inputProps={{ step: 0.05, min: 0, max: 0.5 }} sx={{ width: 150 }} />
              </Stack>
              <Box><Button variant="contained" color="secondary" disabled={sample.isPending} onClick={() => sample.mutate()}>Build the set</Button></Box>
              <Typography variant="caption" color="text.secondary">Refused once anyone has rated: two raters who judged different samples cannot be compared.</Typography>
            </Stack>
          </Section>

          <Section title="Raters">
            <Stack spacing={1.5}>
              {(raters.data ?? []).map((r) => (
                <Stack key={r.username} direction="row" spacing={1} alignItems="center">
                  <Typography fontWeight={600}>{r.username}</Typography>
                  <Chip size="small" label={`${r.study_rating} study`} />
                  <Chip size="small" label={`${r.pilot_label} pilot`} />
                </Stack>
              ))}
              {raters.data?.length === 0 && <Typography color="text.secondary" variant="body2">No rater accounts yet. Two or three are needed for the reliability statistics.</Typography>}
              <Stack direction="row" spacing={1}>
                <TextField label="Username" value={rater.username} onChange={(e) => setRater({ ...rater, username: e.target.value })} />
                <TextField label="Password" type="password" value={rater.password} onChange={(e) => setRater({ ...rater, password: e.target.value })} />
              </Stack>
              <Box><Button variant="outlined" disabled={!rater.username || rater.password.length < 6 || create.isPending} onClick={() => create.mutate()}>Create rater account</Button></Box>
              <Typography variant="caption" color="text.secondary">A rater sees the rating screen and nothing else: no participants, no dashboard, no stimuli.</Typography>
            </Stack>
          </Section>
        </Box>

        {a && (
          <>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 2 }}>
              <StatCard value={a.clips_rated} label="Clips rated" />
              <StatCard value={a.clips_by_everyone} label="By every rater" />
              <StatCard value={a.fleiss_kappa ?? "—"} label={`Fleiss κ · ${a.fleiss_band}`} />
              <StatCard value={a.unusable} label="Marked unusable" />
            </Box>

            {a.pairs.length > 0 && (
              <Section title="Agreement between raters">
                <Table size="small">
                  <TableHead><TableRow><TableCell>Pair</TableCell><TableCell align="right">Clips</TableCell><TableCell align="right">Agreement</TableCell><TableCell align="right">Cohen κ</TableCell><TableCell>Band</TableCell><TableCell align="right">Accuracy Δ</TableCell></TableRow></TableHead>
                  <TableBody>
                    {a.pairs.map((p) => (
                      <TableRow key={p.raters.join("+")}>
                        <TableCell>{p.raters.join(" · ")}</TableCell>
                        <TableCell align="right">{p.clips}</TableCell>
                        <TableCell align="right">{p.percent_agreement ?? "—"}%</TableCell>
                        <TableCell align="right">{p.kappa ?? "—"}</TableCell>
                        <TableCell>{p.kappa_band}</TableCell>
                        <TableCell align="right">{p.accuracy_mean_abs_diff ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Section>
            )}

            {a.within_rater.some((w) => w.repeats > 0) && (
              <Section title="Consistency within each rater (repeated clips)">
                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  {a.within_rater.map((w) => <Chip key={w.rater} label={`${w.rater}: ${w.percent_agreement ?? "—"}% over ${w.repeats} repeats`} />)}
                </Stack>
              </Section>
            )}

            <Section title={`Disagreements to adjudicate (${a.disagreements.length})`}>
              {a.disagreements.length === 0 ? <Typography color="text.secondary" variant="body2">None yet.</Typography> : (
                <Table size="small">
                  <TableHead><TableRow><TableCell>Target</TableCell><TableCell>Votes</TableCell><TableCell>Pipeline said</TableCell></TableRow></TableHead>
                  <TableBody>
                    {a.disagreements.map((d) => (
                      <TableRow key={d.attempt_id}>
                        <TableCell><strong>{d.target}</strong></TableCell>
                        <TableCell>{Object.entries(d.votes).map(([r, v]) => <Chip key={r} size="small" sx={{ mr: 0.5 }} color={v ? "success" : "error"} variant="outlined" label={`${r}: ${v ? "correct" : "wrong"}`} />)}</TableCell>
                        <TableCell><Typography variant="body2" color="text.secondary">{d.pipeline_said ?? "—"}</Typography></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>The pipeline's verdict is shown here, after the fact, only so you can see where people and model part ways. Raters never see it.</Typography>
            </Section>
          </>
        )}

        <Section title="Export">
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            <Button variant="outlined" disabled={exportPilot.isPending} onClick={() => exportPilot.mutate()}>Write pilot labels into the CSV</Button>
            <Button variant="outlined" component="a" href={ratings.studyExportUrl()} target="_blank" rel="noreferrer">Download study ratings (CSV)</Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>The pilot export fills the human_label column that scripts/refit_on_labels.py reads. The study export is one row per rating, for the mixed-effects model.</Typography>
        </Section>
      </Stack>
    </Box>
  );
}
