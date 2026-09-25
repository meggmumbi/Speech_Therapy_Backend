import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { stimuli, type Category, type ImportReport, type Item, type ItemWrite } from "../api/stimuli";
import { Notice, Pill } from "../components/Layout";
import { ItemEditor } from "./ItemEditor";

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
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  const save = useMutation({
    mutationFn: (body: ItemWrite) =>
      editing && editing !== "new" ? stimuli.updateItem(editing.id, body) : stimuli.createItem(current!, body),
    onSuccess: () => { setEditing(null); setError(null); invalidate(); },
    onError: fail,
  });
  const remove = useMutation({ mutationFn: (id: string) => stimuli.deleteItem(id), onSuccess: invalidate, onError: fail });
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string | null }) => stimuli.setRole(id, role),
    onSuccess: invalidate, onError: fail,
  });
  const createCat = useMutation({
    mutationFn: (name: string) => stimuli.createCategory(name, null),
    onSuccess: (c) => { setSelected(c.id); invalidate(); }, onError: fail,
  });
  const doImport = useMutation({
    mutationFn: ({ apply }: { apply: boolean }) => stimuli.importItems(current!, pendingImport!, apply, replace),
    onSuccess: (r) => { setReport(r); if (r.applied) { setPendingImport(null); invalidate(); } },
    onError: fail,
  });

  const category = cats.data?.find((c) => c.id === current) ?? null;
  const rows = items.data?.items ?? [];
  const featureLabel = useMemo(() => Object.fromEntries((vocab.data?.target_features ?? []).map((f) => [f.key, f.label])), [vocab.data]);
  const typeLabel = useMemo(() => Object.fromEntries((vocab.data?.exercise_types ?? []).map((t) => [t.key, t.label])), [vocab.data]);

  async function onFile(file: File) {
    try {
      const parsed = JSON.parse(await file.text());
      const list = Array.isArray(parsed) ? parsed : parsed.items;
      if (!Array.isArray(list)) throw new Error("Expected {\"items\": [...]} or a JSON array.");
      setPendingImport(list as ItemWrite[]);
      setReport(null);
      setError(null);
    } catch (e) { fail(e); }
  }

  function exportJson() {
    const body = rows.map((i) => ({
      exercise_type: i.exercise_type, spec: i.spec, target_feature: i.target_feature,
      match_key: i.match_key, description: i.description,
    }));
    const blob = new Blob([JSON.stringify({ items: body }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(category?.name ?? "list").replace(/\s+/g, "_").toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  if (!vocab.data) return <p className="muted">Loading…</p>;

  return (
    <div className="stack" style={{ maxWidth: 1100 }}>
      <div className="page-head">
        <div>
          <h1>Stimulus sets</h1>
          <p className="muted">One row per item. The design check runs on every save.</p>
        </div>
      </div>

      <DesignCheck data={check.data} />
      {error && <Notice tone="bad">{error}</Notice>}

      <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 16 }}>
        <aside className="card" style={{ padding: 12 }}>
          <h3 style={{ padding: "4px 8px" }}>Lists</h3>
          {(cats.data ?? []).map((c) => (
            <CategoryRow key={c.id} c={c} active={c.id === current} onClick={() => { setSelected(c.id); setEditing(null); setReport(null); setPendingImport(null); }} />
          ))}
          <button className="btn-ghost" style={{ width: "100%", marginTop: 8 }}
            onClick={() => { const name = prompt("Name for the new list"); if (name?.trim()) createCat.mutate(name.trim()); }}>
            New list
          </button>
        </aside>

        <div className="stack">
          {category && (
            <div className="card">
              <div className="page-head" style={{ marginBottom: 8 }}>
                <div>
                  <h2>{category.name}</h2>
                  <p className="muted small">{rows.length} items · {category.items_with_attempts} with recorded attempts · {category.sessions} sessions</p>
                </div>
                <div className="row">
                  <select value={category.study_role ?? ""} onChange={(e) => setRole.mutate({ id: category.id, role: e.target.value || null })} style={{ width: 180 }}>
                    <option value="">No study role</option>
                    {vocab.data.study_roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                  </select>
                  <button className="btn-ghost" onClick={exportJson} disabled={!rows.length}>Export JSON</button>
                  <button className="btn-ghost" onClick={() => fileRef.current?.click()}>Import JSON…</button>
                  <input ref={fileRef} type="file" accept="application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
                  <button className="btn-accent" onClick={() => setEditing("new")}>Add item</button>
                </div>
              </div>
              {category.sessions > 0 && (
                <p className="hint">Sessions have been run on this list. Items with attempts cannot change their content; add new items instead.</p>
              )}
            </div>
          )}

          {pendingImport && (
            <div className="card">
              <h3>Import {pendingImport.length} items into {category?.name}</h3>
              <label className="check"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
                <span>Replace the existing items first <span className="hint">Refused by the server if any of them has recorded attempts.</span></span></label>
              <div className="row">
                <button className="btn-ghost" onClick={() => doImport.mutate({ apply: false })} disabled={doImport.isPending}>Check only</button>
                <button className="btn-primary" onClick={() => doImport.mutate({ apply: true })} disabled={doImport.isPending || (report !== null && report.errors.length > 0)}>Write it</button>
                <button className="btn-ghost" onClick={() => { setPendingImport(null); setReport(null); }}>Discard</button>
              </div>
              {report && (
                <div style={{ marginTop: 12 }}>
                  <Notice tone={report.errors.length ? "bad" : report.applied ? "good" : "warn"}>{report.message ?? `${report.valid} valid`}</Notice>
                  {report.errors.length > 0 && (
                    <ul className="small" style={{ marginTop: 8 }}>
                      {report.errors.map((e, i) => <li key={i}>Row {e.row ?? "?"}{e.field ? ` · ${e.field}` : ""}: {e.problem}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          {editing !== null && (
            <div className="card">
              <ItemEditor
                item={editing === "new" ? null : editing}
                vocabulary={vocab.data}
                onSave={(b) => save.mutate(b)}
                onCancel={() => { setEditing(null); setError(null); }}
                busy={save.isPending}
                error={error}
              />
            </div>
          )}

          {category && (
            <div className="card" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr><th>#</th><th>Item</th><th>Type</th><th>Feature</th><th>Slot</th><th>Audio</th><th></th></tr>
                </thead>
                <tbody>
                  {rows.map((i, n) => (
                    <tr key={i.id} className="clickable" onClick={() => { setEditing(i); setError(null); }}>
                      <td className="muted">{n + 1}</td>
                      <td><strong>{i.name}</strong><div className="small muted">{summarise(i)}</div></td>
                      <td>{typeLabel[i.exercise_type] ?? i.exercise_type}</td>
                      <td>{i.target_feature ? featureLabel[i.target_feature] ?? i.target_feature : <span className="muted">—</span>}</td>
                      <td className="small">{i.match_key ?? "—"}</td>
                      <td>{needsAudio(i) ? (hasAudio(i) ? <Pill tone="good">recorded</Pill> : <Pill tone="fair">missing</Pill>) : ""}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {i.attempts > 0
                          ? <Pill>{i.attempts} attempts</Pill>
                          : <button className="btn-ghost" onClick={() => { if (confirm(`Delete "${i.name}"?`)) remove.mutate(i.id); }}>Delete</button>}
                      </td>
                    </tr>
                  ))}
                  {items.isLoading && <tr><td colSpan={7} className="muted">Loading…</td></tr>}
                  {!items.isLoading && rows.length === 0 && <tr><td colSpan={7} className="muted">No items yet. Add one, or import a JSON file.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CategoryRow({ c, active, onClick }: { c: Category; active: boolean; onClick: () => void }) {
  return (
    <div onClick={onClick} style={{
      padding: "8px 10px", borderRadius: 8, cursor: "pointer",
      background: active ? "var(--sky-90)" : "transparent", marginBottom: 2,
    }}>
      <div style={{ fontWeight: 600, color: active ? "var(--sky-30)" : "inherit" }}>{c.name}</div>
      <div className="small muted row" style={{ gap: 6 }}>
        <span>{c.item_count} items</span>
        {c.study_role && <Pill tone={c.study_role === "test" ? "coral" : "sky"}>{ROLE_LABEL[c.study_role]}</Pill>}
      </div>
    </div>
  );
}

function DesignCheck({ data }: { data?: { sound: boolean; problems: string[]; by_role: Record<string, { category: string; items: number; features: string[]; origin?: { from_list_a: number; from_list_b: number; novel: number } }> } }) {
  if (!data) return null;
  const roles = Object.entries(data.by_role);
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Design check</h3>
        {data.sound ? <Pill tone="good">Sound</Pill> : <Pill tone="bad">{data.problems.length} problem{data.problems.length === 1 ? "" : "s"}</Pill>}
      </div>
      {roles.length > 0 && (
        <div className="row small" style={{ marginTop: 10, gap: 14 }}>
          {roles.map(([role, r]) => (
            <span key={role}>
              <strong>{ROLE_LABEL[role] ?? role}</strong>: {r.items} items, {r.features.length} features
              {r.origin && ` (A ${r.origin.from_list_a} · B ${r.origin.from_list_b} · novel ${r.origin.novel})`}
            </span>
          ))}
        </div>
      )}
      {data.problems.length > 0 && (
        <ul className="small" style={{ margin: "10px 0 0", paddingLeft: 18 }}>
          {data.problems.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      )}
    </div>
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
