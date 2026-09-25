import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert, Box, Button, Chip, Stack, Step, StepLabel, Stepper, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import GroupAddOutlinedIcon from "@mui/icons-material/GroupAddOutlined";
import { participants, study } from "../api/endpoints";
import { ConditionChip, ConfirmDialog, PageHeader, Section, formatDay } from "../components/ui";

/**
 * One participant: who they are, where they are in the protocol, and the
 * two decisions the researcher makes about them at a desk rather than at the
 * robot -- assigning a group, and excluding.
 *
 * Nothing about the design is decided here. Condition, list and step order
 * are displayed as the server reports them. The moment a client derives any
 * of that, the client and the database can disagree and no later analysis
 * can say which was right.
 */
export function Participant() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [excludeReason, setExcludeReason] = useState("");
  const [showExclude, setShowExclude] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const p = useQuery({ queryKey: ["participant", id], queryFn: () => participants.get(id) });
  const plan = useQuery({ queryKey: ["plan", id], queryFn: () => study.plan(id) });
  const balance = useQuery({ queryKey: ["balance"], queryFn: study.balance });
  const ratings = useQuery({ queryKey: ["questionnaires", id], queryFn: () => study.questionnaires(id) });

  const refresh = () => { qc.invalidateQueries({ queryKey: ["plan", id] }); qc.invalidateQueries({ queryKey: ["balance"] }); };
  const fail = (e: unknown) => setError((e as Error).message);
  const assign = useMutation({ mutationFn: () => study.assign(id), onSuccess: refresh, onError: fail });
  const exclude = useMutation({ mutationFn: () => study.exclude(id, excludeReason.trim()), onSuccess: () => { setShowExclude(false); refresh(); }, onError: fail });
  const remove = useMutation({
    mutationFn: () => participants.remove(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["participants"] }); navigate("/participants"); },
    onError: fail,
  });

  if (p.isLoading) return <Typography color="text.secondary">Loading…</Typography>;
  if (p.error) return <Alert severity="error">{(p.error as Error).message}</Alert>;
  const person = p.data!;
  const a = plan.data?.assignment ?? null;
  const steps = plan.data?.steps ?? [];
  const activeStep = steps.findIndex((s) => !s.done);
  const hasSessions = steps.some((s) => s.done);
  const cells = Object.entries(balance.data?.per_group ?? {});

  return (
    <Box sx={{ maxWidth: 960 }}>
      <PageHeader
        title={person.participant_code ?? "Participant without a code"}
        subtitle={[person.age && `${person.age} years`, person.first_language, person.self_rated_english && `CEFR ${person.self_rated_english}`].filter(Boolean).join(" · ") || "No background recorded"}
        actions={<>
          <Button component={Link} to={`/participants/${id}/edit`} startIcon={<EditOutlinedIcon />}>Edit</Button>
          {!hasSessions && <Button color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setShowDelete(true)}>Delete</Button>}
        </>}
      />
      <Stack spacing={2}>
        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
        {!person.participant_code && <Alert severity="warning">This participant has no code and cannot be run until given one.</Alert>}
        {!person.consent_participation && <Alert severity="error">Consent to participate is not recorded. Do not run this participant.</Alert>}
        {(plan.data?.list_problems.length ?? 0) > 0 && <Alert severity="error">Word lists are misconfigured: {plan.data!.list_problems.join("; ")}</Alert>}
        {(plan.data?.unstamped_sessions.length ?? 0) > 0 && (
          <Alert severity="warning">{plan.data!.unstamped_sessions.length} earlier session(s) have no condition recorded and cannot be used in analysis.</Alert>
        )}

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          <Section title="Assignment">
            {a ? (
              <Stack spacing={1.5}>
                <Typography fontWeight={700}>{a.group}</Typography>
                <Stack direction="row" spacing={1}>
                  {a.blocks.map((b) => <ConditionChip key={b.block} condition={b.condition} label={`Block ${b.block}: ${b.condition}-${b.word_list}`} />)}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  Assigned {formatDay(a.assigned_at)}. Re-assignment is not possible: it would break the counterbalance in a way the session records could not show.
                </Typography>
                {a.excluded ? (
                  <Alert severity="error">Excluded{a.exclusion_reason ? `: ${a.exclusion_reason}` : ""}. The slot is free for the next participant.</Alert>
                ) : showExclude ? (
                  <Stack spacing={1}>
                    <TextField label="Reason for exclusion" value={excludeReason} onChange={(e) => setExcludeReason(e.target.value)} placeholder="e.g. withdrew after block 1" autoFocus />
                    <Stack direction="row" spacing={1}>
                      <Button variant="contained" color="error" disabled={!excludeReason.trim() || exclude.isPending} onClick={() => exclude.mutate()}>Exclude</Button>
                      <Button onClick={() => setShowExclude(false)}>Cancel</Button>
                    </Stack>
                  </Stack>
                ) : (
                  <Box><Button variant="outlined" color="inherit" onClick={() => setShowExclude(true)}>Exclude from study…</Button></Box>
                )}
              </Stack>
            ) : (
              <Stack spacing={1.5}>
                <Typography color="text.secondary">Not yet assigned to a counterbalancing group.</Typography>
                {cells.length > 0 && (
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {cells.map(([g, n]) => <Chip key={g} size="small" label={`${g} · ${n}`} />)}
                  </Stack>
                )}
                <Box>
                  <Button variant="contained" color="secondary" startIcon={<GroupAddOutlinedIcon />}
                    disabled={assign.isPending || !person.consent_participation || !person.participant_code} onClick={() => assign.mutate()}>
                    {assign.isPending ? "Assigning…" : "Assign to least-filled group"}
                  </Button>
                </Box>
                <Typography variant="body2" color="text.secondary">
                  Least-filled cell, ties broken from the participant's own id. Not random: with forty participants and four cells, random assignment routinely lands 14/8/12/10.
                </Typography>
              </Stack>
            )}
          </Section>

          <Section title="Protocol">
            {steps.length === 0 ? <Typography color="text.secondary">No plan yet.</Typography> : (
              <Stepper orientation="vertical" activeStep={activeStep < 0 ? steps.length : activeStep} nonLinear>
                {steps.map((s) => (
                  <Step key={s.step} completed={Boolean(s.done)}>
                    <StepLabel optional={
                      <Typography variant="caption" color="text.secondary">
                        {s.kind === "assessment" ? "Pepper records and says nothing about the answer." : "Pepper gives feedback after each word."}
                        {s.done && ` Run ${formatDay(s.done.started_at)}${s.done.completed ? "" : " (not completed)"}.`}
                      </Typography>}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <span>{s.label}</span>
                        {s.condition && <ConditionChip condition={s.condition} />}
                      </Stack>
                    </StepLabel>
                  </Step>
                ))}
              </Stepper>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>Sessions are run from the tablet. This shows what has been done; it does not start anything.</Typography>
          </Section>
        </Box>

        <Section title="Ratings">
          {ratings.data?.responses.length ? (
            <Table size="small">
              <TableHead><TableRow><TableCell>Block</TableCell><TableCell>Condition</TableCell><TableCell>Tutor</TableCell><TableCell>Motivation</TableCell><TableCell>Feedback trust</TableCell><TableCell>Answered</TableCell><TableCell>Took</TableCell><TableCell>Comment</TableCell></TableRow></TableHead>
              <TableBody>
                {ratings.data.responses.map((r) => (
                  <TableRow key={r.session_id}>
                    <TableCell>{r.block ?? "—"}</TableCell>
                    <TableCell><ConditionChip condition={r.condition} /></TableCell>
                    <TableCell>{r.scores?.godspeed?.mean ?? "—"}</TableCell>
                    <TableCell>{r.scores?.motivation?.mean ?? "—"}</TableCell>
                    <TableCell>{r.scores?.feedback_trust?.mean ?? "—"}</TableCell>
                    <TableCell>{r.answered}</TableCell>
                    <TableCell>{r.duration_seconds != null ? `${r.duration_seconds}s` : "—"}</TableCell>
                    <TableCell><Typography variant="body2">{r.comment ?? ""}</Typography></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : <Typography color="text.secondary">No questionnaire answered yet. Assessments are never rated; training blocks are.</Typography>}
        </Section>

        {person.notes && <Section title="Notes"><Typography>{person.notes}</Typography></Section>}
      </Stack>

      <ConfirmDialog open={showDelete} title="Delete this participant?" text="They have no sessions. This cannot be undone." confirmLabel="Delete" danger busy={remove.isPending}
        onClose={() => setShowDelete(false)} onConfirm={() => remove.mutate()} />
    </Box>
  );
}
