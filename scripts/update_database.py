"""Bring the database up to date with the current models.

    python scripts/update_database.py              # apply changes
    python scripts/update_database.py --check      # report only; exit 1 if stale
    python scripts/update_database.py --dry-run    # print the SQL, change nothing

What it does, in order:

1. creates any table declared in the models but missing from the database;
2. adds any column declared on an existing table but missing from it;
3. adds any declared unique constraint that is missing;
4. verifies the result by reading the schema back, rather than trusting the DDL;
5. checks the things the pronunciation endpoint needs at runtime but that are
   not schema -- the audio directory and the linguistic resources.

The expected schema is derived from ``Base.metadata``, not from a hand-written
list of columns. A hardwired list is a second source of truth that silently
goes stale the moment a model changes, and the failure shows up as an insert
error mid-session with a participant in the chair. This supersedes the earlier
``migrate_pronunciation_v2.py``.

Safe to run repeatedly, and safe to run against a fresh database.

**New columns are always added as nullable, with no server default.** Existing
rows therefore read NULL for them, which is the honest value: a row written by
the old text pipeline genuinely has no ``verdict`` or ``confidence``, and
back-filling a plausible-looking default would make old and new rows
indistinguishable in analysis. Anything needing a real backfill is reported for
a human to decide, never guessed at here.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

# Importing the models package registers every table on Base.metadata.
# app.main is deliberately NOT imported: it runs create_all as an import side
# effect, and this script's whole point is that its actions are explicit.
from app import models  # noqa: E402,F401
from app.database import Base, engine  # noqa: E402

AUDIO_DIR = Path("study_audio")


class Plan:
    """Everything that needs doing, gathered before anything is done."""

    def __init__(self) -> None:
        self.create_tables: list[str] = []
        self.add_columns: list[tuple[str, str, str]] = []   # table, column, ddl
        self.add_unique: list[tuple[str, str, tuple[str, ...]]] = []
        self.warnings: list[str] = []

    @property
    def empty(self) -> bool:
        return not (self.create_tables or self.add_columns or self.add_unique)

    def statements(self) -> list[str]:
        out: list[str] = []
        for table, column, ddl in self.add_columns:
            out.append(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}')
        for table, name, columns in self.add_unique:
            cols = ", ".join(f'"{c}"' for c in columns)
            out.append(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" '
                       f'UNIQUE ({cols})')
        return out


def build_plan() -> Plan:
    plan = Plan()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect

    for name, table in Base.metadata.tables.items():
        if name not in existing_tables:
            plan.create_tables.append(name)
            continue

        present = {c["name"] for c in inspector.get_columns(name)}
        for column in table.columns:
            if column.name in present:
                continue
            try:
                type_sql = column.type.compile(dialect=dialect)
            except Exception as exc:  # noqa: BLE001 - unmappable type
                plan.warnings.append(
                    f"{name}.{column.name}: cannot render type "
                    f"{column.type!r} for this dialect ({exc}); add it by hand")
                continue
            # Always nullable: see the module docstring. A NOT NULL column
            # cannot be added to a table that already has rows without a
            # backfill decision, and that decision is not this script's to make.
            if not column.nullable:
                plan.warnings.append(
                    f"{name}.{column.name} is NOT NULL in the model but is "
                    "being added as nullable; existing rows need a backfill "
                    "before the constraint can be applied")
            plan.add_columns.append((name, column.name, type_sql))

        # Unique constraints, including those declared as unique=True on a
        # column. A table created before the constraint existed will not have
        # it, and the assignment endpoint relies on it to stop a participant
        # being re-assigned mid-study.
        declared: dict[str, tuple[str, ...]] = {}
        for constraint in table.constraints:
            cols = tuple(c.name for c in getattr(constraint, "columns", []))
            if constraint.__class__.__name__ == "UniqueConstraint" and cols:
                declared[constraint.name or f"uq_{name}_{'_'.join(cols)}"] = cols
        for column in table.columns:
            if column.unique and not column.primary_key:
                declared.setdefault(f"uq_{name}_{column.name}", (column.name,))

        have = {tuple(uc["column_names"])
                for uc in inspector.get_unique_constraints(name)}
        have |= {tuple(ix["column_names"]) for ix in inspector.get_indexes(name)
                 if ix.get("unique")}
        for constraint_name, cols in declared.items():
            if cols not in have:
                plan.add_unique.append((name, constraint_name, cols))

    return plan


def describe_plan(plan: Plan) -> None:
    if plan.empty:
        print("  schema is up to date; nothing to do")
    for name in plan.create_tables:
        table = Base.metadata.tables[name]
        n_cols = len(table.columns)
        print(f"  CREATE TABLE {name} ({n_cols} columns)")
    by_table: dict[str, list[str]] = {}
    for table, column, ddl in plan.add_columns:
        by_table.setdefault(table, []).append(f"{column} {ddl}")
    for table, columns in by_table.items():
        print(f"  ALTER TABLE {table}: +{len(columns)} columns")
        for column in columns:
            print(f"      {column}")
    for table, constraint_name, cols in plan.add_unique:
        print(f"  ALTER TABLE {table}: UNIQUE {constraint_name} "
              f"({', '.join(cols)})")
    for warning in plan.warnings:
        print(f"  ! {warning}")


def apply_plan(plan: Plan) -> None:
    if plan.create_tables:
        # create_all only creates what is missing, so this cannot touch an
        # existing table.
        Base.metadata.create_all(bind=engine)
        print(f"  created {len(plan.create_tables)} table(s)")

    statements = plan.statements()
    if not statements:
        return
    applied = failed = 0
    with engine.begin() as conn:
        for statement in statements:
            try:
                conn.execute(text(statement))
                applied += 1
            except SQLAlchemyError as exc:
                # A failing UNIQUE almost always means real duplicate rows,
                # which is a data problem to look at rather than to force.
                failed += 1
                print(f"  ! failed: {statement}\n      {exc.__class__.__name__}: "
                      f"{str(exc).splitlines()[0]}")
    print(f"  applied {applied} statement(s)"
          + (f", {failed} failed" if failed else ""))


def verify() -> list[str]:
    """Read the schema back and report anything still missing."""
    problems: list[str] = []
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    for name, table in Base.metadata.tables.items():
        if name not in existing:
            problems.append(f"table {name} is still missing")
            continue
        present = {c["name"] for c in inspector.get_columns(name)}
        missing = [c.name for c in table.columns if c.name not in present]
        if missing:
            problems.append(f"{name} is missing columns: {', '.join(missing)}")
    return problems


def check_runtime_prerequisites() -> list[str]:
    """Non-schema things the pronunciation endpoint needs to work."""
    problems: list[str] = []

    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        probe = AUDIO_DIR / ".write_probe"
        probe.write_bytes(b"")
        probe.unlink()
        print(f"  audio directory writable: {AUDIO_DIR.resolve()}")
    except OSError as exc:
        problems.append(f"cannot write to {AUDIO_DIR}: {exc}")

    try:
        from app.services.pronunciation import pronunciations
        variants = pronunciations("draught")
        if variants:
            print(f"  CMUdict available: draught -> {' '.join(variants[0])}")
        else:
            problems.append("CMUdict returned nothing for a known word")
    except Exception as exc:  # noqa: BLE001
        problems.append(
            f"linguistic resources unavailable ({exc.__class__.__name__}); "
            "run scripts/setup_resources.py")

    for var in ("STUDY_LIST_A_CATEGORY_ID", "STUDY_LIST_B_CATEGORY_ID"):
        if not os.getenv(var):
            # Not fatal: the lists are bound after the pilot's difficulty
            # matching, which is later than the first time this script runs.
            print(f"  note: {var} is unset; /study/sessions will refuse to "
                  "start blocks until both lists are bound")
    return problems


def emit_sql(path: Path) -> None:
    """Write a standalone, idempotent SQL script for psql / pgAdmin / DBeaver.

    Generated from the models rather than from a diff against whatever
    database happens to be connected. A diff-derived script is only correct
    for the state it was generated against, and would quietly do the wrong
    thing on a host that is further behind; this one states the desired schema
    absolutely, so it brings a database at *any* version up to date.

    Every statement is ``IF NOT EXISTS``, so the script is safe to run
    repeatedly and safe on a fresh database.
    """
    from datetime import datetime, timezone

    from app.services.pronunciation import PIPELINE_VERSION

    lines: list[str] = []
    add = lines.append

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    add("-- Speech therapy backend: bring the schema up to date.")
    add("--")
    add(f"-- GENERATED by scripts/update_database.py --emit-sql, {stamp}")
    add(f"-- pipeline version at generation: {PIPELINE_VERSION}")
    add("-- Do not hand-edit: change the SQLAlchemy models and regenerate.")
    add("--")
    add("-- Idempotent. Every statement is IF NOT EXISTS, so this is safe to")
    add("-- run repeatedly, and safe against a database at any earlier version.")
    add("--")
    add("-- Wrapped in a transaction: if any statement fails, nothing applies.")
    add("--")
    add("-- NOTE: columns are added NULLABLE even where the model declares them")
    add("-- NOT NULL. A NOT NULL column cannot be added to a table that already")
    add("-- has rows without deciding what those rows should contain, and that")
    add("-- decision does not belong in a generated script. Existing rows will")
    add("-- read NULL, which is the honest value -- a row written by the old")
    add("-- text pipeline genuinely has no verdict or confidence.")
    add("")
    add("BEGIN;")
    add("")

    dialect = engine.dialect

    add("-- " + "=" * 70)
    add("-- Tables")
    add("-- " + "=" * 70)
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect))
        add(ddl.strip().rstrip(";") + ";")
        add("")

    add("-- " + "=" * 70)
    add("-- Columns (no-ops where the column already exists)")
    add("-- " + "=" * 70)
    expected: list[tuple[str, str]] = []
    for table in Base.metadata.sorted_tables:
        rendered: list[str] = []
        for column in table.columns:
            expected.append((table.name, column.name))
            if column.primary_key:
                continue  # created with the table; never added later
            try:
                type_sql = column.type.compile(dialect=dialect)
            except Exception:  # noqa: BLE001
                add(f"-- SKIPPED {table.name}.{column.name}: "
                    f"type {column.type!r} could not be rendered")
                continue
            rendered.append(
                f'ALTER TABLE "{table.name}" '
                f'ADD COLUMN IF NOT EXISTS "{column.name}" {type_sql};'
            )
        if rendered:
            add(f"-- {table.name}")
            lines.extend(rendered)
            add("")

    add("COMMIT;")
    add("")
    add("-- " + "=" * 70)
    add("-- Verification: returns ZERO rows when the schema is complete.")
    add("-- Any row is a table.column the models declare but the database lacks.")
    add("-- " + "=" * 70)
    add("SELECT e.table_name, e.column_name")
    add("FROM (VALUES")
    values = ",\n".join(f"    ('{t}', '{c}')" for t, c in expected)
    add(values)
    add(") AS e(table_name, column_name)")
    add("LEFT JOIN information_schema.columns c")
    add("       ON c.table_schema = current_schema()")
    add("      AND c.table_name  = e.table_name")
    add("      AND c.column_name = e.column_name")
    add("WHERE c.column_name IS NULL")
    add("ORDER BY e.table_name, e.column_name;")
    add("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    tables = len(Base.metadata.sorted_tables)
    print(f"  wrote {path} ({tables} tables, {len(expected)} columns, "
          f"{len(lines)} lines)")
    print(f"  run it with:  psql -d {engine.url.database} -f {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report only; exit 1 if the schema is out of date")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the SQL that would run, change nothing")
    parser.add_argument("--emit-sql", metavar="PATH", nargs="?",
                        const="sql/update_schema.sql",
                        help="write a standalone idempotent .sql script and exit "
                             "(default path: sql/update_schema.sql)")
    args = parser.parse_args()

    if args.emit_sql:
        print("emitting SQL:")
        emit_sql(Path(args.emit_sql))
        return 0

    url = engine.url
    print(f"database: {url.database} on {url.host or 'localhost'} "
          f"({engine.dialect.name})")
    if engine.dialect.name != "postgresql":
        print(f"  ! expected postgresql; type rendering may differ on "
              f"{engine.dialect.name}")

    print("\nplan:")
    try:
        plan = build_plan()
    except SQLAlchemyError as exc:
        print(f"  ! could not read the schema: {exc}")
        return 2
    describe_plan(plan)

    if args.check:
        problems = verify()
        print("\nstatus:", "up to date" if plan.empty and not problems
              else "OUT OF DATE")
        for problem in problems:
            print(f"  - {problem}")
        return 0 if (plan.empty and not problems) else 1

    if args.dry_run:
        print("\nSQL that would run:")
        if plan.create_tables:
            for name in plan.create_tables:
                ddl = str(CreateTable(Base.metadata.tables[name])
                          .compile(engine)).strip()
                print(f"  {ddl};")
        for statement in plan.statements():
            print(f"  {statement};")
        if plan.empty:
            print("  (nothing)")
        return 0

    if not plan.empty:
        print("\napplying:")
        apply_plan(plan)

    print("\nverifying:")
    problems = verify()
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
    else:
        tables = len(Base.metadata.tables)
        print(f"  all {tables} tables present with every declared column")

    print("\nruntime prerequisites:")
    problems += check_runtime_prerequisites()

    if problems:
        print(f"\n{len(problems)} problem(s) remain:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nDatabase is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
