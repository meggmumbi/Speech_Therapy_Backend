import { useQuery } from "@tanstack/react-query";
import { study } from "../api/endpoints";
import { Notice, Pill } from "../components/Layout";

/**
 * Cell counts for the 2x2 counterbalance, and the word-list binding.
 *
 * Worth checking before and during recruitment: an unbalanced design is
 * recoverable while participants are still being run and not afterwards.
 */
export function Balance() {
  const q = useQuery({ queryKey: ["balance"], queryFn: study.balance });
  if (q.isLoading) return <p className="muted">Loading…</p>;
  if (q.error) return <Notice tone="bad">{(q.error as Error).message}</Notice>;
  const b = q.data!;
  const groups = Object.entries(b.per_group ?? {});
  const total = groups.reduce((s, [, n]) => s + n, 0);

  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="page-head">
        <div>
          <h1>Balance</h1>
          <p className="muted">{total} active in the design, {b.excluded} excluded.</p>
        </div>
        {b.balanced === false && (
          <Pill tone="fair">Cells differ by {b.max_cell_difference}</Pill>
        )}
        {b.balanced === true && <Pill tone="good">Balanced</Pill>}
      </div>

      {b.list_problems.length > 0 && (
        <Notice tone="bad">Word lists: {b.list_problems.join("; ")}</Notice>
      )}

      <div className="grid-2">
        {groups.map(([g, n]) => (
          <div key={g} className="stat">
            <div className="value">{n}</div>
            <div className="label">{g}</div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <section className="card">
          <h3>Condition in block 1</h3>
          <Counts data={b.condition_in_block_1} />
        </section>
        <section className="card">
          <h3>List in block 1</h3>
          <Counts data={b.list_in_block_1} />
        </section>
      </div>

      <section className="card">
        <h3>Word lists</h3>
        <table>
          <tbody>
            {Object.entries(b.word_lists).map(([k, v]) => (
              <tr key={k}>
                <td style={{ width: 120 }}><strong>{k === "test" ? "Assessment set" : `List ${k}`}</strong></td>
                <td className="muted small">{v ?? <Pill tone="bad">not bound</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted" style={{ marginTop: 8 }}>Bound in the database by each category's study role. Stimulus editing arrives in the next console step.</p>
      </section>
    </div>
  );
}

function Counts({ data }: { data?: Record<string, number> }) {
  if (!data) return <p className="muted">—</p>;
  return (
    <div className="row">
      {Object.entries(data).map(([k, n]) => <Pill key={k}>{k} · {n}</Pill>)}
    </div>
  );
}
