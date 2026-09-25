import { useQuery } from "@tanstack/react-query";
import { Alert, Box, Chip, Stack, Table, TableBody, TableCell, TableRow, Typography } from "@mui/material";
import { study } from "../api/endpoints";
import { PageHeader, Section, StatCard } from "../components/ui";

/**
 * Cell counts for the 2x2 counterbalance, and the word-list binding.
 *
 * Worth checking before and during recruitment: an unbalanced design is
 * recoverable while participants are still being run and not afterwards.
 */
export function Balance() {
  const q = useQuery({ queryKey: ["balance"], queryFn: study.balance });
  if (q.isLoading) return <Typography color="text.secondary">Loading…</Typography>;
  if (q.error) return <Alert severity="error">{(q.error as Error).message}</Alert>;
  const b = q.data!;
  const groups = Object.entries(b.per_group ?? {});
  const total = groups.reduce((s, [, n]) => s + n, 0);

  return (
    <Box sx={{ maxWidth: 960 }}>
      <PageHeader
        title="Balance"
        subtitle={`${total} active in the design, ${b.excluded} excluded.`}
        actions={b.balanced === false
          ? <Chip color="warning" label={`Cells differ by ${b.max_cell_difference}`} />
          : b.balanced === true ? <Chip color="success" label="Balanced" /> : null}
      />
      <Stack spacing={2}>
        {b.list_problems.length > 0 && <Alert severity="error">Word lists: {b.list_problems.join("; ")}</Alert>}
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 2 }}>
          {groups.map(([g, n]) => <StatCard key={g} value={n} label={g} />)}
        </Box>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
          <Section title="Condition in block 1"><Counts data={b.condition_in_block_1} /></Section>
          <Section title="List in block 1"><Counts data={b.list_in_block_1} /></Section>
        </Box>
        <Section title="Word lists">
          <Table size="small">
            <TableBody>
              {Object.entries(b.word_lists).map(([k, v]) => (
                <TableRow key={k}>
                  <TableCell sx={{ width: 160 }}><strong>{k === "test" ? "Assessment set" : `List ${k}`}</strong></TableCell>
                  <TableCell>{v ? <Typography variant="body2" color="text.secondary">{v}</Typography> : <Chip size="small" color="error" label="not bound" />}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>Bound in the database by each list's study role, from the Stimulus sets page.</Typography>
        </Section>
      </Stack>
    </Box>
  );
}

function Counts({ data }: { data?: Record<string, number> }) {
  if (!data) return <Typography color="text.secondary">—</Typography>;
  return <Stack direction="row" spacing={1}>{Object.entries(data).map(([k, n]) => <Chip key={k} label={`${k} · ${n}`} />)}</Stack>;
}
