"""Re-score stored attempts from their raw audio and compare with what the
server wrote at the time.

    python scripts/rescore_sessions.py                  # every stored attempt
    python scripts/rescore_sessions.py --since 2026-09-15
    python scripts/rescore_sessions.py --session <uuid> [--session <uuid> ...]
    python scripts/rescore_sessions.py --no-asr         # acoustic path only
    python scripts/rescore_sessions.py --csv out.csv

Two uses. First, regression checking: after any change to the scorer, this is
how you find out what it did to real recordings rather than to the unit-test
stub. Second, provenance: a stored verdict that this script cannot reproduce
means the server that wrote it was not running the code in the checkout --
which is exactly what happened on 2026-09-15, when a `--reload` worker kept
serving four-day-old code and a second machine ran without the MD layer.

Nothing here writes to the database.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--session", action="append", default=[],
                        help="session id(s) to restrict to")
    parser.add_argument("--since", default=None,
                        help="only attempts created on/after this date (YYYY-MM-DD)")
    parser.add_argument("--no-asr", action="store_true",
                        help="disable the server-side ASR safety net for this run")
    parser.add_argument("--audio-root", default="study_audio")
    parser.add_argument("--csv", default=None, help="write per-attempt rows here")
    args = parser.parse_args()

    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    import soundfile as sf
    from sqlalchemy import text

    from app.database import engine
    from app.services.pronunciation import asr, score_attempt
    from app.services.pronunciation.runtime import get_config, get_model, warmup

    warmup()
    model, config = get_model(), get_config()
    from app.services.pronunciation.md_scorer import md_layer_active
    print(f"pipeline {config.provenance()['pipeline_version']}  "
          f"config {config.config_hash()}  md_layer "
          f"{'active' if md_layer_active() else 'INACTIVE'}  "
          f"asr {'off' if args.no_asr else config.server_asr}")

    where = []
    params: dict = {}
    if args.session:
        where.append("sa.session_id::text = ANY(:sessions)")
        params["sessions"] = args.session
    if args.since:
        where.append("sa.created_at >= :since")
        params["since"] = args.since
    sql = f"""
        SELECT sa.session_id, sa.item_id, ai.name, ac.name, sa.attempt_number,
               sa.verdict, sa.verdict_score, sa.is_correct, sa.transcript,
               sa.config_hash
        FROM session_activities sa
        JOIN activity_items ai ON ai.id = sa.item_id
        LEFT JOIN activity_categories ac ON ac.id = ai.category_id
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY ac.name, ai.name, sa.attempt_number, sa.created_at"""
    with engine.connect() as c:
        rows = list(c.execute(text(sql), params))
    print(f"{len(rows)} stored attempts\n")

    root = Path(args.audio_root)
    header = (f"{'category':<10}{'word':<14}{'#':<3}{'STORED':<21}{'NOW':<21}"
              f"{'asr':<14}{'ms':<6}{'expected -> heard'}")
    print(header)
    print("-" * len(header))

    was, now = Counter(), Counter()
    flips: list[tuple] = []
    missing = 0
    stale_hash = 0
    out_rows = []
    for sid, iid, word, cat, att, v_old, s_old, ok_old, tx_old, cfg_old in rows:
        path = root / str(sid) / f"{iid}_attempt{att}.wav"
        if not path.exists():
            hits = list(root.rglob(f"{iid}_attempt{att}.wav"))
            if not hits:
                missing += 1
                continue
            path = hits[0]
        wav, sr = sf.read(path, dtype="float32", always_2d=False)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        provider = (None if args.no_asr
                    else asr.provider_for(config.server_asr))
        r = score_attempt(word, wav, sr, model, config,
                          transcript=tx_old, transcript_provider=provider)
        was[v_old] += 1
        now[r.verdict] += 1
        if cfg_old != config.config_hash():
            stale_hash += 1
        mark = ""
        if bool(ok_old) != bool(r.is_correct):
            mark = "  <-- FIXED" if r.is_correct else "  <-- now wrong"
            flips.append((word, att, v_old, r.verdict))
        if r.transcript is None:
            asr_txt = "-"                       # acoustics decided alone
        elif r.transcript == tx_old:
            asr_txt = "(client)"                # the tablet's own transcript
        else:
            asr_txt = r.transcript[:13]         # server-side ASR was consulted
        so = "-" if s_old is None else f"{s_old:.3f}"
        print(f"{str(cat)[:9]:<10}{word[:13]:<14}{att:<3}"
              f"{(str(v_old) + ' ' + so):<21}"
              f"{(r.verdict + ' ' + f'{r.verdict_score:.3f}'):<21}"
              f"{asr_txt:<14}{r.timings.total_ms:<6.0f}"
              f"{' '.join(r.expected_phones)} -> {' '.join(r.observed_phones)}{mark}")
        out_rows.append({
            "session_id": str(sid), "item_id": str(iid), "word": word,
            "category": cat, "attempt": att, "stored_verdict": v_old,
            "stored_score": s_old, "verdict": r.verdict,
            "verdict_score": r.verdict_score, "quality": r.score,
            "confidence": r.confidence, "transcript": r.transcript,
            "transcript_matches": r.transcript_matches,
            "expected": " ".join(r.expected_phones),
            "heard": " ".join(r.observed_phones),
            "total_ms": round(r.timings.total_ms, 1),
            "asr_ms": round(r.timings.stages.get("asr", 0.0), 1),
            "audio": str(path),
        })

    n = sum(now.values())
    print(f"\naudio missing for {missing} attempts; "
          f"{stale_hash}/{n} stored rows carry a different config hash")
    print(f"stored : {dict(was)}  correct {was['correct']}/{sum(was.values())}")
    print(f"now    : {dict(now)}  correct {now['correct']}/{n}")
    print(f"{len(flips)} verdicts changed")
    if out_rows:
        ms = sorted(r["total_ms"] for r in out_rows)
        asr_ms = [r["asr_ms"] for r in out_rows if r["asr_ms"]]
        print(f"latency: median {ms[len(ms)//2]:.0f} ms, p95 "
              f"{ms[int(len(ms)*0.95)-1]:.0f} ms"
              + (f"; asr ran on {len(asr_ms)} attempts, median "
                 f"{sorted(asr_ms)[len(asr_ms)//2]:.0f} ms" if asr_ms else ""))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
