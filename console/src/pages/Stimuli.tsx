import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Box, Button, Checkbox, Chip, FormControl, FormControlLabel, InputLabel, List, ListItemButton,
  ListItemText, MenuItem, Paper, Select, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import { stimuli, type Category, type ImportReport, type Item, type ItemWrite } from "../api/stimuli";
import { ConfirmDialog, PageHeader, PromptDialog, Section, staleBackendMessage } from "../components/ui";
import { ItemEditor } from "./ItemEditor";
import { RecordingPanel } from "./RecordingPanel";

/**
 * The stimulus sets.
 *
 * A category is a list. Three of them carry a study role and are what the
 * design runs on; the rest are practice material. The design check at the
 * top runs against the whole database and says, while a list is being
 * written, whether it is one KIT/FLEECE item short -- rather than on the
 * morning of a session.
 */
const ROLE_LABEL: Record<string, string> = { list_a: "List A", list_b: "List B", test: "Assessment set" };

export function Stimuli() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<Item | null | "new">(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [pendingImport, setPendingImport] = useState<ItemWrite[] | null>(null);
  const [replace, setReplace] = useState(false);
  const [newList, setNewList] = useState(false);
  const [toDelete, setToDelete] = useState<Item | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const vocab = useQuery({ queryKey: ["vocabulary"], queryFn: stimuli.vocabulary, staleTime: Infinity });
  const cats = useQuery({ queryKey: ["categories"], queryFn: stimuli.categories });
  const check = useQuery({ queryKey: ["design-check"], queryFn: stimuli.validate });
  const current = selected ?? cats.data?.find((c) => c.study_role === "list_a")?.id ?? cats.data?.[0]?.id ?? null;
  const items = useQuery({ queryKey: ["items", current], queryFn: () => stimuli.items(current!), enabled: Boolean(current) });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["items", current] });
    qc.invalidateQueries({ queryKey: ["categories"] });
    qc.invalidateQueries({ queryKey: ["design-check"] });
  };
  const fail = (e: unknown) => setError(staleBackendMessage(e) ?? (e instanceof Error ? e.message : String(e)));

  const save = useMutation({
    mutationFn: (body: ItemWrite) => (editing && editing !== "new" ? stimuli.updateItem(editing.id, body) : stimuli.createItem(current!, body)),
    onSuccess: () => { setEditing(null); setError(null); invalidate(); }, onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => stimuli.deleteItem(id), onSuccess: () => { setToDelete(null); invalidate(); }, onError: fail });
  const setRole = useMutation({
    mutationFn: ({ id, role, retire }: { id: string; role: string | null; retire?: boolean }) => stimuli.setRole(id, role, retire),
    onSuccess: invalidate,
    onError: (e: unknown, vars) => {
      // The role is held by a list with recorded sessions. Hand it over only
      // on an explicit yes: the old list keeps the label as a retired role,
      // so its sessions still export as that list; new sessions use this one.
      const msg = e instanceof Error ? e.message : String(e);
      if (!vars.retire && /retire_previous/.test(msg)) {
        const holder = cats.data?.find((c) => c.study_role === vars.role && c.id !== vars.id);
        if (window.confirm(`"${holder?.name ?? "Another list"}" is ${ROLE_LABEL[vars.role ?? ""] ?? vars.role} and has sessions recorded against it.

Hand the role to this list? The old list keeps it as a retired role, so its sessions stay labelled; from now on new sessions use this list.`)) {
          setRole.mutate({ ...vars, retire: true });
          return;
        }
      }
      fail(e);
    },
  });
  const createCat = useMutation({ mutationFn: (name: string) => stimuli.createCategory(name, null), onSuccess: (c) => { setNewList(false); setSelected(c.id); invalidate(); }, onError: fail });
  const doImport = useMutation({
    mutationFn: ({ apply }: { apply: boolean }) => stimuli.importItems(current!, pendingImport!, apply, replace),
    onSuccess: (r) => { setReport(r); if (r.applied) { setPendingImport(null); invalidate(); } }, onError: fail,
  });

  const category = cats.data?.find((c) => c.id === current) ?? null;
  const rows = items.data?.items ?? [];
  const featureLabel = useMemo(() => Object.fromEntries((vocab.data?.target_features ?? []).map((f) => [f.key, f.label])), [vocab.data]);
  const typeLabel = useMemo(() => Object.fromEntries((vocab.data?.exercise_types ?? []).map((t) => [t.key, t.label])), [vocab.data]);
  const backendStale = staleBackendMessage(cats.error);

  async function onFile(file: File) {
    try {
      const parsed = JSON.parse(await file.text());
      const list = Array.isArray(parsed) ? parsed : parsed.items;
      if (!Array.isArray(list)) throw new Error('Expected {"items": [...]} or a JSON array.');
      setPendingImport(list as ItemWrite[]); setReport(null); setError(null);
    } catch (e) { fail(e); }
  }

  function exportJson() {
    const body = rows.map((i) => ({ exercise_type: i.exercise_type, spec: i.spec, target_feature: i.target_feature, match_key: i.match_key, description: i.description }));
    const blob = new Blob([JSON.stringify({ items: body }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(category?.name ?? "list").replace(/\s+/g, "_").toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (!vocab.data) return <Typography color="text.secondary">Loading…</Typography>;

  return (
    <Box sx={{ maxWidth: 1200 }}>
      <PageHeader title="Stimulus sets" subtitle="One row per item. The design check runs on every save." />
      <Stack spacing={2}>
        <DesignCheck data={check.data} />
        {backendStale && <Alert severity="warning">{backendStale}</Alert>}
        {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}

        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "250px 1fr" }, gap: 2, alignItems: "start" }}>
          <Paper sx={{ p: 1.5 }}>
            <Typography variant="overline" sx={{ px: 1 }}>Lists</Typography>
            <List dense disablePadding>
              {(cats.data ?? []).map((c) => (
                <CategoryRow key={c.id} c={c} active={c.id === current} onClick={() => { setSelected(c.id); setEditing(null); setReport(null); setPendingImport(null); }} />
              ))}
              {cats.isLoading && <ListItemText sx={{ px: 1 }} secondary="Loading…" />}
            </List>
            <Button fullWidth startIcon={<AddIcon />} sx={{ mt: 1 }} onClick={() => setNewList(true)}>New list</Button>
          </Paper>

          <Stack spacing={2}>
            {category && (
              <Paper sx={{ p: 2.5 }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 2, flexWrap: "wrap" }}>
                  <Box>
                    <Typography variant="h5">{category.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{rows.length} items · {category.items_with_attempts} with recorded attempts · {category.sessions} sessions</Typography>
                  </Box>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <FormControl sx={{ minWidth: 180 }}>
                      <InputLabel>Study role</InputLabel>
                      <Select label="Study role" value={category.study_role ?? ""} onChange={(e) => setRole.mutate({ id: category.id, role: (e.target.value as string) || null })}>
                        <MenuItem value="">No study role</MenuItem>
                        {vocab.data.study_roles.map((r) => <MenuItem key={r} value={r}>{ROLE_LABEL[r] ?? r}</MenuItem>)}
                      </Select>
                    </FormControl>
                    <Button startIcon={<DownloadOutlinedIcon />} onClick={exportJson} disabled={!rows.length}>Export</Button>
                    <Button startIcon={<UploadFileOutlinedIcon />} onClick={() => fileRef.current?.click()}>Import</Button>
                    <input ref={fileRef} type="file" accept="application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
                    <Button variant="contained" color="secondary" startIcon={<AddIcon />} onClick={() => setEditing("new")}>Add item</Button>
                  </Stack>
                </Box>
                {category.sessions > 0 && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>Sessions have been run on this list. Items with attempts cannot change their content; add new items instead.</Typography>
                )}
              </Paper>
            )}

            {pendingImport && (
              <Section title={`Import ${pendingImport.length} items into ${category?.name}`}>
                <FormControlLabel control={<Checkbox checked={replace} onChange={(e) => setReplace(e.target.checked)} />} label="Replace the existing items first" />
                <Typography variant="caption" color="text.secondary" display="block" sx={{ ml: 4, mt: -0.5, mb: 1.5 }}>Refused by the server if any of them has recorded attempts.</Typography>
                <Stack direction="row" spacing={1}>
                  <Button variant="outlined" onClick={() => doImport.mutate({ apply: false })} disabled={doImport.isPending}>Check only</Button>
                  <Button variant="contained" onClick={() => doImport.mutate({ apply: true })} disabled={doImport.isPending || (report !== null && report.errors.length > 0)}>Write it</Button>
                  <Button onClick={() => { setPendingImport(null); setReport(null); }}>Discard</Button>
                </Stack>
                {report && (
                  <Alert sx={{ mt: 2 }} severity={report.errors.length ? "error" : report.applied ? "success" : "info"}>
                    {report.message ?? `${report.valid} valid`}
                    {report.errors.length > 0 && (
                      <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                        {report.errors.map((e, i) => <li key={i}>Row {e.row ?? "?"}{e.field ? ` · ${e.field}` : ""}: {e.problem}</li>)}
                      </ul>
                    )}
                  </Alert>
                )}
              </Section>
            )}

            {editing !== null && (
              <Paper sx={{ p: 2.5 }}>
                <ItemEditor item={editing === "new" ? null : editing} vocabulary={vocab.data}
                  onSave={(b) => save.mutate(b)} onCancel={() => { setEditing(null); setError(null); }} busy={save.isPending} error={error} />
              </Paper>
            )}
            {editing !== null && editing !== "new" && (
              <RecordingPanel item={editing} onChanged={() => {
                invalidate();
                stimuli.items(current!).then((r) => { const fresh = r.items.find((i) => i.id === editing.id); if (fresh) setEditing(fresh); });
              }} />
            )}

            {category && (
              <Paper>
                <Table size="small">
                  <TableHead>
                    <TableRow><TableCell>#</TableCell><TableCell>Item</TableCell><TableCell>Type</TableCell><TableCell>Feature</TableCell><TableCell>Slot</TableCell><TableCell>Audio</TableCell><TableCell align="right" /></TableRow>
                  </TableHead>
                  <TableBody>
                    {rows.map((i, n) => (
                      <TableRow key={i.id} hover className="clickable" selected={editing !== "new" && editing?.id === i.id} onClick={() => { setEditing(i); setError(null); }}>
                        <TableCell><Typography color="text.secondary">{n + 1}</Typography></TableCell>
                        <TableCell><strong>{i.name}</strong><Typography variant="body2" color="text.secondary">{summarise(i)}</Typography></TableCell>
                        <TableCell>{typeLabel[i.exercise_type] ?? i.exercise_type}</TableCell>
                        <TableCell>{i.target_feature ? featureLabel[i.target_feature] ?? i.target_feature : "—"}</TableCell>
                        <TableCell><Typography variant="body2">{i.match_key ?? "—"}</Typography></TableCell>
                        <TableCell>{needsAudio(i) ? (hasAudio(i) ? <Chip size="small" color="success" variant="outlined" label="Recorded" /> : <Chip size="small" color="warning" label="Missing" />) : (hasAudio(i) ? <Chip size="small" variant="outlined" label="Recorded" /> : "")}</TableCell>
                        <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                          {i.attempts > 0
                            ? <Chip size="small" label={`${i.attempts} attempts`} />
                            : <Button size="small" color="inherit" startIcon={<DeleteOutlineIcon />} onClick={() => setToDelete(i)}>Delete</Button>}
                        </TableCell>
                      </TableRow>
                    ))}
                    {items.isLoading && <TableRow><TableCell colSpan={7}><Typography color="text.secondary">Loading…</Typography></TableCell></TableRow>}
                    {!items.isLoading && rows.length === 0 && <TableRow><TableCell colSpan={7}><Typography color="text.secondary">No items yet. Add one, or import a JSON file.</Typography></TableCell></TableRow>}
                  </TableBody>
                </Table>
              </Paper>
            )}
          </Stack>
        </Box>
      </Stack>

      <PromptDialog open={newList} title="New list" label="Name" placeholder="e.g. Study List C" busy={createCat.isPending} onClose={() => setNewList(false)} onSubmit={(v) => createCat.mutate(v)} />
      <ConfirmDialog open={toDelete !== null} title={`Delete "${toDelete?.name}"?`} text="It has no recorded attempts, so nothing else refers to it." confirmLabel="Delete" danger busy={remove.isPending}
        onClose={() => setToDelete(null)} onConfirm={() => toDelete && remove.mutate(toDelete.id)} />
    </Box>
  );
}

function CategoryRow({ c, active, onClick }: { c: Category; active: boolean; onClick: () => void }) {
  return (
    <ListItemButton selected={active} onClick={onClick} sx={{ borderRadius: 2, mb: 0.5, "&.Mui-selected": { bgcolor: "primary.light" } }}>
      <ListItemText
        primary={c.name}
        primaryTypographyProps={{ fontWeight: 600, color: active ? "primary.dark" : "text.primary" }}
        secondary={<Stack direction="row" spacing={0.75} alignItems="center" component="span" sx={{ mt: 0.25 }}>
          <span>{c.item_count} items</span>
          {c.study_role && <Chip size="small" color={c.study_role === "test" ? "secondary" : "primary"} variant="outlined" label={ROLE_LABEL[c.study_role]} sx={{ height: 20 }} />}
          {!c.study_role && c.retired_study_role && <Chip size="small" variant="outlined" label={`was ${ROLE_LABEL[c.retired_study_role]}`} sx={{ height: 20 }} />}
        </Stack>}
      />
    </ListItemButton>
  );
}

function DesignCheck({ data }: { data?: { sound: boolean; problems: string[]; by_role: Record<string, { category: string; items: number; features: string[]; origin?: { from_list_a: number; from_list_b: number; novel: number } }> } }) {
  if (!data) return null;
  const roles = Object.entries(data.by_role);
  return (
    <Section title="Design check" actions={data.sound ? <Chip color="success" label="Sound" /> : <Chip color="error" label={`${data.problems.length} problem${data.problems.length === 1 ? "" : "s"}`} />}>
      <Stack direction="row" spacing={3} flexWrap="wrap" useFlexGap>
        {roles.map(([role, r]) => (
          <Typography key={role} variant="body2">
            <strong>{ROLE_LABEL[role] ?? role}</strong>: {r.items} items, {r.features.length} features
            {r.origin && ` (A ${r.origin.from_list_a} · B ${r.origin.from_list_b} · novel ${r.origin.novel})`}
          </Typography>
        ))}
      </Stack>
      {data.problems.length > 0 && (
        <ul style={{ margin: "10px 0 0", paddingLeft: 18 }}>
          {data.problems.map((p, i) => <li key={i}><Typography variant="body2">{p}</Typography></li>)}
        </ul>
      )}
    </Section>
  );
}

function summarise(i: Item): string {
  const s = i.spec as Record<string, unknown>;
  if (typeof s.sentence === "string") return s.sentence;
  if (Array.isArray(s.options)) return (s.options as string[]).join(" / ") + (typeof s.cue === "string" ? `  (cue: ${s.cue})` : "");
  if (Array.isArray(s.syllables)) return (s.syllables as string[]).join("·");
  if (typeof s.prompt === "string") return s.prompt;
  return "";
}

function needsAudio(i: Item): boolean { return i.exercise_type === "minimal_pair_id"; }
function hasAudio(i: Item): boolean { return Boolean((i.spec as Record<string, unknown>).stimulus_audio || i.audio_url); }
