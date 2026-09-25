import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { participants } from "../api/endpoints";
import { Notice, Pill, formatDay } from "../components/Layout";

export function Participants() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["participants"], queryFn: participants.list });

  const rows = (q.data ?? []).slice().sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  const needCode = rows.filter((r) => !r.participant_code).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Participants</h1>
          <p className="muted">{rows.length} enrolled. Tap a row for the study plan.</p>
        </div>
        <Link className="btn btn-accent" to="/participants/new">Enrol participant</Link>
      </div>

      {q.error && <Notice tone="bad">{(q.error as Error).message}</Notice>}
      {needCode > 0 && (
        <Notice tone="warn">
          {needCode} participant{needCode === 1 ? "" : "s"} enrolled before codes existed and cannot be run until given one.
        </Notice>
      )}

      <div className="card" style={{ marginTop: 16, padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Age</th>
              <th>First language</th>
              <th>English</th>
              <th>Consent</th>
              <th>Enrolled</th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && (
              <tr><td colSpan={6} className="muted">Loading…</td></tr>
            )}
            {rows.map((p) => (
              <tr key={p.id} className="clickable" onClick={() => navigate(`/participants/${p.id}`)}>
                <td>
                  {p.participant_code ? <strong>{p.participant_code}</strong> : <Pill tone="fair">Needs a code</Pill>}
                </td>
                <td>{p.age ?? "—"}</td>
                <td>{p.first_language ?? "—"}</td>
                <td>{p.self_rated_english ?? "—"}</td>
                <td>
                  {p.consent_participation
                    ? <Pill tone="good">{p.consent_audio_retention ? "Full" : "No audio"}</Pill>
                    : <Pill tone="bad">Missing</Pill>}
                </td>
                <td className="muted">{formatDay(p.created_at)}</td>
              </tr>
            ))}
            {!q.isLoading && rows.length === 0 && (
              <tr><td colSpan={6} className="muted">Nobody enrolled yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
