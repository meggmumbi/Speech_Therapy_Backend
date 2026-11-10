import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Alert, Box, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { dashboardApi } from "../api/dashboard";
import { BarChart } from "../charts/BarChart";
import { ConditionChip, PageHeader, Section, StatCard, formatDay, staleBackendMessage } from "../components/ui";
import "../charts/viz.css";

/**
 * Read-only. Every number is a query the analysis will also make, with the
 * same definitions: accuracy over final attempts, gated and skipped excluded,
 * training only; questionnaire means by the condition the block ran under.
 *
 * One hero figure, then tiles, then a handful of charts whose forms follow
 * the data's job: cells and the funnel are magnitude, accuracy and ratings
 * are K against D, recording quality is state. Each chart has a table view.
 */
export function Dashboard() {
  const [target, setTarget] = useState<string>(() => localStorage.getItem("console.target") ?? "40");
  const targetN = Number(target) > 0 ? Number(target) : undefined;
  const q = useQuery({ queryKey: ["dashboard", targetN], queryFn: () => dashboardApi.get(targetN), refetchInterval: 60_000 });

  if (q.isLoading) return <Typography color="text.secondary">Loading…</Typography>;
  if (q.error) return <Alert severity="error">{staleBackendMessage(q.error) ?? (q.error as Error).message}</Alert>;
  const d = q.data!;
  const p = d.participants;
  const pct = (v: number) => `${Math.round(v)}%`;

  return (
    <Box sx={{ maxWidth: 1200, opacity: q.isFetching ? 0.7 : 1, transition: "opacity .2s" }}>
      <PageHeader
        title="Dashboard"
        subtitle={`As of ${new Date(d.generated_at + "Z").toLocaleString()}. Refreshes every minute.`}
        actions={
          <TextField label="Recruitment target" type="number" value={target} sx={{ width: 170 }}
            onChange={(e) => { setTarget(e.target.value); localStorage.setItem("console.target", e.target.value); }} />
        }
      />
      <Stack spacing={2}>
        {d.list_problems.length > 0 && <Alert severity="error">Word lists: {d.list_problems.join("; ")}</Alert>}

        {/* The one number this view leads with. */}
        <Paper sx={{ p: 3, display: "flex", alignItems: "baseline", gap: 3, flexWrap: "wrap" }}>
          <Box>
            <Typography component="div" sx={{ fontSize: 56, fontWeight: 700, lineHeight: 1 }}>
              {p.complete}{targetN ? <Typography component="span" sx={{ fontSize: 24, color: "text.secondary", ml: 1 }}>/ {targetN}</Typography> : null}
            </Typography>
            <Typography variant="overline">Participants through the full protocol</Typography>
          </Box>
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460 }}>
            All five steps run: pre-test, both blocks, post-test and the delayed post-test. This is the N the paper's within-subject analysis has.
            {targetN && p.complete < targetN ? ` ${targetN - p.complete} to go.` : ""}
          </Typography>
        </Paper>

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(6, 1fr)" }, gap: 2 }}>
          <StatCard value={p.enrolled} label="Enrolled" />
          <StatCard value={p.assigned} label="Assigned" />
          <StatCard value={p.started} label="Started" />
          <StatCard value={p.excluded} label="Excluded" tone={p.excluded ? "warning" : undefined} />
          <StatCard value={p.needs_code} label="Need a code" tone={p.needs_code ? "warning" : undefined} />
          <StatCard value={d.false_correction_rate == null ? "—" : pct(d.false_correction_rate)} label="False corrections" />
        </Box>

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          <Section title="Counterbalancing cells">
            <BarChart categories={d.cells.map((c) => c.group)} series={[{ key: "n", label: "Participants", color: "--series-1", values: d.cells.map((c) => c.count) }]} height={200} />
          </Section>
          <Section title="Protocol progress">
            <BarChart categories={d.funnel.map((f) => f.label)}
              series={[{ key: "started", label: "Sessions run", color: "--ord-3", values: d.funnel.map((f) => f.started) }]}
              ordinalColors={["--ord-1", "--ord-2", "--ord-3", "--ord-4", "--ord-5"]} height={200} />
          </Section>
        </Box>

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          <Section title="Accuracy in training, by condition">
            <BarChart categories={["All items", "Spoken", "Tapped"]} max={100} format={pct}
              series={d.accuracy.map((a) => ({
                key: a.condition, label: `${a.condition} (${a.attempts} attempts, ${a.participants} people)`,
                color: a.condition === "K" ? "--series-1" : "--series-2",
                values: [a.accuracy, a.spoken_accuracy, a.tapped_accuracy],
              }))}
              emptyText="No training attempts yet." height={220} />
            <Typography variant="caption" color="text.secondary">Final attempt per item; gated and skipped attempts excluded. Not a result until N is in: two conditions with a handful of people each will look different by chance.</Typography>
          </Section>
          <Section title="Questionnaire means, by condition">
            <BarChart categories={["Tutor", "Motivation", "Feedback trust"]} max={7} format={(v) => v.toFixed(1)}
              series={d.ratings.map((r) => ({
                key: r.condition, label: `${r.condition} (n = ${r.n})`,
                color: r.condition === "K" ? "--series-1" : "--series-2",
                values: [r.godspeed, r.motivation, r.feedback_trust],
              }))}
              emptyText="No questionnaires answered yet." height={220} />
            <Typography variant="caption" color="text.secondary">Seven-point scales, answered after each training block, before the summary was shown.</Typography>
          </Section>
        </Box>

        <Section title="Recording quality, per session day">
          <BarChart categories={d.quality.map((x) => formatDay(x.day))} mode="stacked" height={220}
            series={[
              { key: "clean", label: "Clean", color: "--status-good", values: d.quality.map((x) => x.clean) },
              { key: "quiet", label: "Quiet (move the mic closer)", color: "--status-warning", values: d.quality.map((x) => x.quiet) },
              { key: "clipped", label: "Clipped (move it back)", color: "--status-serious", values: d.quality.map((x) => x.clipped) },
              { key: "lost", label: "Lost (silent, cut, or too long)", color: "--status-critical", values: d.quality.map((x) => x.lost) },
            ]}
            emptyText="No recordings yet." />
        </Section>

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(5, 1fr)" }, gap: 2 }}>
          <StatCard value={d.engagement.attempts} label="Attempts" />
          <StatCard value={d.engagement.replays} label="Replays asked for" />
          <StatCard value={d.engagement.skipped} label="Items skipped" />
          <StatCard value={d.engagement.gated} label="Asked to repeat" />
          <StatCard value={d.engagement.helpfulness_mean == null ? "—" : d.engagement.helpfulness_mean.toFixed(1)} label={`Feedback helpfulness (${d.engagement.helpfulness_ratings})`} />
        </Box>

        <Section title="Recent sessions">
          <Table size="small">
            <TableHead>
              <TableRow><TableCell>Participant</TableCell><TableCell>Step</TableCell><TableCell>Condition</TableCell><TableCell>Started</TableCell><TableCell align="right">Attempts</TableCell><TableCell>Recordings</TableCell><TableCell>State</TableCell></TableRow>
            </TableHead>
            <TableBody>
              {d.recent.map((s) => (
                <TableRow key={s.session_id} hover>
                  <TableCell><Link to={`/participants`}>{s.participant}</Link></TableCell>
                  <TableCell>{s.step ?? "—"}</TableCell>
                  <TableCell><ConditionChip condition={s.condition} /></TableCell>
                  <TableCell>{formatDay(s.started_at)}</TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{s.attempts}</TableCell>
                  <TableCell>{s.unusable_recordings ? <Chip size="small" color="warning" label={`${s.unusable_recordings} unusable`} /> : <Typography variant="body2" color="text.secondary">clean</Typography>}</TableCell>
                  <TableCell>
                    {s.flagged ? <Chip size="small" color="error" label="Flagged" />
                      : s.ended_early ? <Chip size="small" label="Ended early" />
                      : s.completed ? <Chip size="small" color="success" variant="outlined" label="Complete" />
                      : <Chip size="small" label="Open" />}
                  </TableCell>
                </TableRow>
              ))}
              {d.recent.length === 0 && <TableRow><TableCell colSpan={7}><Typography color="text.secondary">No study sessions yet.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>
      </Stack>
    </Box>
  );
}
