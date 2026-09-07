"""Add the acoustic-pipeline columns to an existing database.

    python scripts/migrate_pronunciation_v2.py

``Base.metadata.create_all`` creates missing *tables* but never alters existing
ones, so the new columns on ``therapy_sessions`` and ``session_activities``
would silently not exist on a database that predates them -- and the first
insert would fail mid-session, with a participant in the chair.

Every statement uses ``ADD COLUMN IF NOT EXISTS``, so running this repeatedly
is safe and running it against a fresh database is a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

COLUMNS: dict[str, list[tuple[str, str]]] = {
    "therapy_sessions": [
        ("condition", "VARCHAR(1)"),
    ],
    "session_activities": [
        ("condition", "VARCHAR(1)"),
        ("verdict", "VARCHAR(20)"),
        ("verdict_score", "DOUBLE PRECISION"),
        ("confidence", "DOUBLE PRECISION"),
        ("gated", "BOOLEAN DEFAULT FALSE"),
        ("expected_phones", "JSON"),
        ("observed_phones", "JSON"),
        ("phone_scores", "JSON"),
        ("diagnoses", "JSON"),
        ("applied_folds", "JSON"),
        ("stress_error", "BOOLEAN"),
        ("named_phone", "VARCHAR(4)"),
        ("feedback_word_count", "INTEGER"),
        ("audio_ref", "VARCHAR"),
        ("pipeline_version", "VARCHAR(20)"),
        ("config_hash", "VARCHAR(16)"),
        ("model_id", "VARCHAR(120)"),
        ("stage_timings_ms", "JSON"),
    ],
}


def main() -> int:
    added = 0
    with engine.begin() as conn:
        for table, columns in COLUMNS.items():
            for name, ddl in columns:
                conn.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {ddl}'
                ))
                added += 1
        print(f"Applied {added} ADD COLUMN IF NOT EXISTS statements.")

        # Report what actually exists now, rather than trusting the DDL ran.
        for table in COLUMNS:
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ), {"t": table}).fetchall()
            present = {r[0] for r in rows}
            missing = [n for n, _ in COLUMNS[table] if n not in present]
            status = "OK" if not missing else f"MISSING {missing}"
            print(f"  {table}: {len(present)} columns  {status}")
            if missing:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
