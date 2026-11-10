import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  Alert, Button, Chip, Paper, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import PersonAddAlt1Icon from "@mui/icons-material/PersonAddAlt1";
import { participants } from "../api/endpoints";
import { PageHeader, formatDay } from "../components/ui";

export function Participants() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["participants"], queryFn: participants.list });

  const rows = (q.data ?? []).slice().sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const needCode = rows.filter((r) => !r.participant_code).length;

  return (
    <>
      <PageHeader
        title="Participants"
        subtitle={`${rows.length} enrolled. Select a row for the study plan.`}
        actions={<Button component={Link} to="/participants/new" variant="contained" color="secondary" startIcon={<PersonAddAlt1Icon />}>Enrol participant</Button>}
      />
      {q.error && <Alert severity="error" sx={{ mb: 2 }}>{(q.error as Error).message}</Alert>}
      {needCode > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {needCode} participant{needCode === 1 ? "" : "s"} enrolled before codes existed and cannot be run until given one.
        </Alert>
      )}
      <Paper>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Code</TableCell><TableCell>Age</TableCell><TableCell>First language</TableCell>
              <TableCell>English</TableCell><TableCell>Consent</TableCell><TableCell>Enrolled</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {q.isLoading && <TableRow><TableCell colSpan={6}><Typography color="text.secondary">Loading…</Typography></TableCell></TableRow>}
            {rows.map((p) => (
              <TableRow key={p.id} hover className="clickable" onClick={() => navigate(`/participants/${p.id}`)}>
                <TableCell>{p.participant_code ? <strong>{p.participant_code}</strong> : <Chip size="small" color="warning" label="Needs a code" />}</TableCell>
                <TableCell>{p.age ?? "—"}</TableCell>
                <TableCell>{p.first_language ?? "—"}</TableCell>
                <TableCell>{p.self_rated_english ?? "—"}</TableCell>
                <TableCell>
                  {p.consent_participation
                    ? <Chip size="small" color="success" variant="outlined" label={p.consent_audio_retention ? "Full" : "No audio"} />
                    : <Chip size="small" color="error" label="Missing" />}
                </TableCell>
                <TableCell><Typography color="text.secondary" variant="body2">{formatDay(p.created_at)}</Typography></TableCell>
              </TableRow>
            ))}
            {!q.isLoading && rows.length === 0 && <TableRow><TableCell colSpan={6}><Typography color="text.secondary">Nobody enrolled yet.</Typography></TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
    </>
  );
}
