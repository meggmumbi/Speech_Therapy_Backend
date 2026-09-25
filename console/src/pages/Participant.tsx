import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { participants, study } from "../api/endpoints";
import type { Step } from "../api/types";
import { Notice, Pill, formatDay } from "../components/Layout";

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
  const [error, setError] = useState<string | null>(null);

  const p = useQuery({ queryKey: ["participant", id], queryFn: () => participants.get(id) });
  const plan = useQuery({ queryKey: ["plan", id], queryFn: () => study.plan(id) });
  const balance = useQuery({ queryKey: ["balance"], queryFn: study.balance });
  const ratings = useQuery({ queryKey: ["questionnaires", id], queryFn: () => study.questionnaires(id) });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["plan", id] });
    qc.invalidateQueries({ queryKey: ["balance"] });
  };
  const assign = useMutation({
    mutationFn: () => study.assign(id),
    onSuccess: refresh,
    onError: (e) => setError((e as Error).message),
  });
  const exclude = useMutation({
    mutationFn: () => study.exclude(id, excludeReason.trim()),
    onSuccess: () => { setShowExclude(false); refresh(); },
    onError: (e) => setError((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: () => participants.remove(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["participants"] }); navigate("/participants"); },
    onError: (e) => setError((e as Error).message),
  });

  if (p.isLoading) return <p className="muted">Loading…</p>;
  if (p.error) return <Notice tone="bad">{(p.error as Error).message}</Notice>;
  const person = p.data!;
  const a = plan.data?.assignment ?? null;
  const steps = plan.data?.steps ?? [];
  const nextStep = steps.find((s) => !s.done)?.step;
  const hasSessions = steps.some((s) => s.done);

  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="page-head">
        <div>
          <h1>{person.participant_code ?? "Participant without a code"}</h1>
          <p className="muted">
            {[person.age && `${person.age} years`, person.first_language, person.self_rated_english && `CEFR ${person.self_rated_english}`]
              .filter(Boolean).join(" · ") || "No background recorded"}
          </p>
        </div>
        <div className="row">
          <Link className="btn btn-ghost" to={`/participants/${id}/edit`}>Edit</Link>
          {!hasSessions && (
            <button className="btn-danger" onClick={() => { if (confirm("Delete this participant? They have no sessions.")) remove.mutate(); }}>
              Delete
            </button>
          )}
        </div>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}
      {!person.participant_code && <Notice tone="warn">This participant has no code and cannot be run until given one.</Notice>}
      {!person.consent_participation && <Notice tone="bad">Consent to participate is not recorded. Do not run this participant.</Notice>}
      {(plan.data?.list_problems.length ?? 0) > 0 && (
        <Notice tone="bad">Word lists are misconfigured: {plan.data!.list_problems.join("; ")}</Notice>
      )}
      {(plan.data?.unstamped_sessions.length ?? 0) > 0 && (
        <Notice tone="warn">
          {plan.data!.unstamped_sessions.length} earlier session(s) have no condition recorded and cannot be used in analysis.
        </Notice>
      )}

      <div className="grid-2">
        <section className="card">
          <h3>Assignment</h3>
          {a ? (
            <>
              <p><strong>{a.group}</strong></p>
              <div className="row" style={{ marginBottom: 8 }}>
                {a.blocks.map((b) => (
                  <Pill key={b.block} tone={b.condition === "D" ? "coral" : "sky"}>
                    Block {b.block}: {b.condition}-{b.word_list}
                  </Pill>
                ))}
              </div>
              <p className="small muted">Assigned {formatDay(a.assigned_at)}. Re-assignment is not possible: it would break the counterbalance in a way the session records could not show.</p>
              {a.excluded ? (
                <Notice tone="bad">Excluded{a.exclusion_reason ? `: ${a.exclusion_reason}` : ""}. The slot is free for the next participant.</Notice>
              ) : showExclude ? (
                <div className="stack">
                  <label className="field">
                    <span>Reason for exclusion</span>
                    <input value={excludeReason} onChange={(e) => setExcludeReason(e.target.value)} placeholder="e.g. withdrew after block 1" autoFocus />
                  </label>
                  <div className="row">
                    <button className="btn-danger" disabled={!excludeReason.trim() || exclude.isPending} onClick={() => exclude.mutate()}>Exclude</button>
                    <button className="btn-ghost" onClick={() => setShowExclude(false)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <button className="btn-ghost" onClick={() => setShowExclude(true)}>Exclude from study…</button>
              )}
            </>
          ) : (
            <>
              <p className="muted">Not yet assigned to a counterbalancing group.</p>
              <BalancePreview data={balance.data?.per_group} />
              <button
                className="btn-accent"
                disabled={assign.isPending || !person.consent_participation || !person.participant_code}
                onClick={() => assign.mutate()}
              >
                {assign.isPending ? "Assigning…" : "Assign to least-filled group"}
              </button>
              <p className="small muted" style={{ marginTop: 8 }}>Least-filled cell, ties broken from the participant's own id. Not random: with forty participants and four cells, random assignment routinely lands 14/8/12/10.</p>
            </>
          )}
        </section>

        <section className="card">
          <h3>Protocol</h3>
          <div className="steps">
            {steps.map((s) => <StepRow key={s.step} step={s} isNext={s.step === nextStep} />)}
            {steps.length === 0 && <p className="muted">No plan yet.</p>}
          </div>
          <p className="small muted" style={{ marginTop: 10 }}>Sessions are run from the tablet. This shows what has been done; it does not start anything.</p>
        </section>
      </div>

      <section className="card">
        <h3>Ratings</h3>
        {ratings.data?.responses.length ? (
          <table>
            <thead><tr><th>Block</th><th>Condition</th><th>Tutor</th><th>Motivation</th><th>Feedback trust</th><th>Answered</th><th>Took</th><th>Comment</th></tr></thead>
            <tbody>
              {ratings.data.responses.map((r) => (
                <tr key={r.session_id}>
                  <td>{r.block ?? "—"}</td>
                  <td><Pill tone={r.condition === "D" ? "coral" : "sky"}>{r.condition ?? "—"}</Pill></td>
                  <td>{r.scores?.godspeed?.mean ?? "—"}</td>
                  <td>{r.scores?.motivation?.mean ?? "—"}</td>
                  <td>{r.scores?.feedback_trust?.mean ?? "—"}</td>
                  <td>{r.answered}</td>
                  <td>{r.duration_seconds != null ? `${r.duration_seconds}s` : "—"}</td>
                  <td className="small">{r.comment ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No questionnaire answered yet. Assessments are never rated; training blocks are.</p>
        )}
      </section>

      {person.notes && (
        <section className="card">
          <h3>Notes</h3>
          <p>{person.notes}</p>
        </section>
      )}
    </div>
  );
}

function StepRow({ step, isNext }: { step: Step; isNext: boolean }) {
  return (
    <div className={`step ${step.done ? "done" : ""}`}>
      <div className="dot">{step.done ? "✓" : step.kind === "assessment" ? "T" : "B"}</div>
      <div>
        <div><strong>{step.label}</strong> {isNext && <Pill tone="sky">Next</Pill>}</div>
        <div className="small muted">
          {step.kind === "assessment" ? "Pepper records and says nothing about the answer." : "Pepper gives feedback after each word."}
          {step.done && ` Run ${formatDay(step.done.started_at)}${step.done.completed ? "" : " (not completed)"}.`}
        </div>
      </div>
      <div>{step.condition && <Pill tone={step.condition === "D" ? "coral" : "sky"}>{step.condition}</Pill>}</div>
    </div>
  );
}

function BalancePreview({ data }: { data?: Record<string, number> }) {
  if (!data) return null;
  const entries = Object.entries(data);
  return (
    <div className="row small muted" style={{ marginBottom: 12 }}>
      <span>Cells now:</span>
      {entries.map(([g, n]) => <Pill key={g}>{g.replace(/^group \d: /i, "")} · {n}</Pill>)}
    </div>
  );
}
