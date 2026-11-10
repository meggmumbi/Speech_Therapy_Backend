"""Give the pre-2026-09-17 participants a participant_code.

    python scripts/backfill_participant_codes.py            # show the plan
    python scripts/backfill_participant_codes.py --apply    # write it

WHAT THIS IS FOR

Twenty-two rows were enrolled before the participant record existed. They have
participant_code NULL and their identifier is sitting in the deprecated `name`
column as "P1".."P21". Nothing reads `name` any more, so in the app they show
as "Participant 509c3ef3" and cannot be told apart.

WHY THE CODES GET A PREFIX

Copying `name` across verbatim collides: a new participant was enrolled on
2026-09-17 as "P1", and participant_code is unique. The two are different
people -- the legacy P1 has four sessions from the earlier pilot, the new one
has none -- so one of them has to be distinguishable, and it should not be the
participant being enrolled now.

So the old cohort becomes PILOT-P1 .. PILOT-P21. The number is preserved, which
is what links a row back to the researcher's paper records, and the prefix says
which round it belongs to. That distinction is worth keeping for its own sake:
every session those rows hold has session_type NULL and no condition, so none
of them can enter the analysis. A code that says PILOT is a standing reminder
of that rather than a trap.

If you would rather the old rows keep their bare numbers, rename the new P1
first and then run this with --prefix "".
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:12345@localhost/asd_therapy")

from app.database import SessionLocal  # noqa: E402
from app.models import Child, TherapySession  # noqa: E402

# "P1", "p 21", "P-3": a code the researcher assigned. Anything else is more
# likely a test row than a participant, and is reported rather than renamed.
CODE_LIKE = re.compile(r"^[A-Z]+[\s\-_]?\d+$")


def normalise(name: str) -> str:
    return re.sub(r"[\s\-_]+", "", name.strip().upper())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes; without this it only prints them")
    parser.add_argument("--prefix", default="PILOT-",
                        help='prepended to each recovered code (default "PILOT-")')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        taken = {
            code for (code,) in db.query(Child.participant_code)
            .filter(Child.participant_code.isnot(None)).all()
        }
        rows = (
            db.query(Child)
            .filter(Child.participant_code.is_(None))
            .order_by(Child.created_at)
            .all()
        )
        if not rows:
            print("Nothing to do: every participant already has a code.")
            return 0

        planned: list[tuple[Child, str]] = []
        skipped: list[tuple[Child, str]] = []

        for child in rows:
            sessions = (
                db.query(TherapySession)
                .filter(TherapySession.child_id == child.id).count()
            )
            source = (child.name or "").strip()
            if not source:
                skipped.append((child, "no name to recover a code from"))
                continue
            if not CODE_LIKE.match(source.upper()):
                skipped.append((child, f"name {source!r} does not look like a code"))
                continue

            code = f"{args.prefix}{normalise(source)}"
            if code in taken:
                skipped.append((child, f"{code} is already taken"))
                continue
            taken.add(code)
            planned.append((child, code))
            print(f"  {str(child.id)[:8]}  {source:<16} -> {code:<12} "
                  f"({sessions} session(s))")

        for child, reason in skipped:
            print(f"  {str(child.id)[:8]}  SKIPPED: {reason}")

        print(f"\n{len(planned)} to update, {len(skipped)} skipped.")

        if not args.apply:
            print("\nDry run. Re-run with --apply to write these codes.")
            return 0

        for child, code in planned:
            child.participant_code = code
        db.commit()
        print(f"\nWrote {len(planned)} participant codes.")
        if skipped:
            print("The skipped rows still need a code set by hand in the app "
                  "before they can be run.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
