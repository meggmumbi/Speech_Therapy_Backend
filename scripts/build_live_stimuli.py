"""Build the three live-study stimulus sets.

    python scripts/build_live_stimuli.py            # write stimuli/live_*.json
    python scripts/build_live_stimuli.py --check    # verify, write nothing

Writes the import format for ``POST /authoring/categories/{id}/items/import``:

    stimuli/live_list_a.json       Live study List A      20 items
    stimuli/live_list_b.json       Live study List B      20 items
    stimuli/live_assessment.json   Live study Assessment  15 items

WHAT CHANGED FROM THE PILOT LISTS (scripts/build_stimuli.py)

Five features, not seven. The two suprasegmental features are out of the
live protocol because the instrument cannot carry them: the stress rule
never fails a verdict (polysyllabic_stress has no focus phones, and a stress
error is recorded beside the verdict rather than in it), and a full vowel
for schwa scores leniently (ca-me-ra at 0.71; the rule that would catch it
rejects 24 stored corrects). A trained feature the scorer cannot reject is a
feature on which the K/D manipulation can never fire, and the primary
outcome is repair after a correction. The tap-only versions (schwa_spot,
stress_place) are not kept either: a trained feature must be assessed, and
the assessment is spoken.

Four items per feature, not three. Two spoken words, the first in a carrier
sentence, and one perception item. Three spoken items per feature is what
feeds the primary outcome: every correction on a spoken item is one
observation of uptake and, through the revisit round, one of retention.
Twenty items a block is about the same session length as the pilot's
twenty-one.

No /r/ in any non-rhotic word. P1's tapped /r/ scored 0.44 to 0.50 on the
rhotic items, which is below threshold, and the verdict takes the worst two
phones in the word: an /r/ anywhere in a "think" or "mother" item would
reject it for the /r/, not for the feature it tests. So "three" is gone
(replaced by "thin"), "brother" was never used, and the check below reads
each word's reference pronunciation to enforce it.

The arrive/alive pair is from the English with Lucy pronunciation test the
researcher supplied; it is the one pair in that test on a feature this study
trains. Its other pairs (chair/share, which/wish, fan/van, pair/bear) are
contrasts Kenyan English does not typically neutralise, and its stress,
syllable-count and schwa tasks are the suprasegmental material this protocol
sets aside.

The spoken words of a feature share a vowel or consonant class, not a
frequency count; the features are matched A to B slot for slot, and the
import check (GET /authoring/item-sets/validate) is the arbiter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stimuli"
sys.path.insert(0, str(ROOT))

# feature -> per list: say (with its minimal-pair partner), say2, sentence; novel
LIVE: dict[str, dict] = {
    "trap_palm_strut": {
        "a": {"say": ("cat", "cut"), "say2": "cup", "sentence": "The cat is under the table."},
        "b": {"say": ("bag", "bug"), "say2": "bus", "sentence": "She put the bag on the chair."},
        "novel": "map",
    },
    "kit_fleece": {
        "a": {"say": ("ship", "sheep"), "say2": "sit", "sentence": "The ship is leaving the port."},
        "b": {"say": ("hit", "heat"), "say2": "lip", "sentence": "He hit the ball with the bat."},
        "novel": "chip",
    },
    "foot_goose": {
        "a": {"say": ("pull", "pool"), "say2": "book", "sentence": "Please pull the door open."},
        "b": {"say": ("full", "fool"), "say2": "good", "sentence": "The glass is full of water."},
        "novel": "foot",
    },
    "dental_fricative": {
        "a": {"say": ("think", "sink"), "say2": "bath", "sentence": "I think the answer is here."},
        "b": {"say": ("thin", "tin"), "say2": "mouth", "sentence": "This book is thin."},
        "novel": "thumb",
    },
    "rhotic_lateral": {
        "a": {"say": ("right", "light"), "say2": "alive", "sentence": "Turn right at the next corner."},
        "b": {"say": ("rice", "lice"), "say2": "arrive", "sentence": "We cooked rice for dinner."},
        "novel": "road",
    },
}


def training_list(label: str) -> list[dict]:
    key = "a" if label == "A" else "b"
    items: list[dict] = []
    for feature, row in LIVE.items():
        slot = row[key]
        word, partner = slot["say"]
        items.append({"exercise_type": "repeat_word", "spec": {"word": word},
                      "target_feature": feature, "match_key": f"{feature}-say"})
        items.append({"exercise_type": "repeat_word", "spec": {"word": slot["say2"]},
                      "target_feature": feature, "match_key": f"{feature}-say2"})
        items.append({"exercise_type": "read_sentence",
                      "spec": {"sentence": slot["sentence"], "target_word": word},
                      "target_feature": feature, "match_key": f"{feature}-sentence"})
        items.append({"exercise_type": "minimal_pair_id",
                      # The participant hears the answer word and taps which of
                      # the two it was. Needs the item's model audio recorded in
                      # the console before it can run.
                      "spec": {"options": [word, partner], "answer": word},
                      "target_feature": feature, "match_key": f"{feature}-hear"})
    return items


def assessment() -> list[dict]:
    """Spoken only: the list A word, the list B word and a novel word per
    feature. For any one participant those are trained, matched control and
    generalisation."""
    items: list[dict] = []
    for feature, row in LIVE.items():
        for origin in ("a", "b", "novel"):
            word = row[origin]["say"][0] if origin != "novel" else row["novel"]
            items.append({"exercise_type": "repeat_word", "spec": {"word": word},
                          "target_feature": feature, "match_key": f"{feature}-{origin}"})
    return items


def _spoken_words(items: list[dict]) -> set[str]:
    found: set[str] = set()
    for item in items:
        spec = item["spec"]
        for key in ("word", "target_word"):
            if spec.get(key):
                found.add(spec[key])
        for option in spec.get("options", []):
            found.add(option)
    return found


def check() -> list[str]:
    """Everything the server's design check will test, plus the lexicon."""
    from app.schemas import exercise_spec
    from app.services import exercises
    from app.services.pronunciation.references import reference_for

    problems: list[str] = []
    a, b, t = training_list("A"), training_list("B"), assessment()

    for name, items in (("A", a), ("B", b), ("assessment", t)):
        for item in items:
            try:
                exercise_spec.parse(item["exercise_type"], item["spec"])
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{name} {item['match_key']}: {exc}")
            if item["target_feature"] not in exercises.TARGET_FEATURES:
                problems.append(f"{name} {item['match_key']}: unknown feature")
    if len(a) != len(b):
        problems.append(f"lists differ in length: {len(a)} vs {len(b)}")
    if {i["match_key"] for i in a} != {i["match_key"] for i in b}:
        problems.append("match keys differ between A and B")
    shared = _spoken_words(a) & _spoken_words(b)
    if shared:
        problems.append(f"lists share words: {sorted(shared)}")

    # Assessment origin, as the server counts it: by item name.
    names_a = {i["spec"]["word"] for i in a if i["exercise_type"] == "repeat_word" and i["match_key"].endswith("-say")}
    names_b = {i["spec"]["word"] for i in b if i["exercise_type"] == "repeat_word" and i["match_key"].endswith("-say")}
    from_a = sum(1 for i in t if i["spec"]["word"] in names_a)
    from_b = sum(1 for i in t if i["spec"]["word"] in names_b)
    novel = len(t) - from_a - from_b
    if from_a != from_b:
        problems.append(f"assessment draws {from_a} from A and {from_b} from B")
    if novel != len(LIVE):
        problems.append(f"assessment has {novel} novel words for {len(LIVE)} features")

    # Lexicon: every word has a reference, the focus phone is in it, and no
    # non-rhotic word carries an /r/ the tapped-R problem could reject.
    for feature, row in LIVE.items():
        focus = exercises.focus_phones_for(feature)
        # (word, must carry the focus phone). The minimal-pair partners are
        # the words that must NOT carry it; they are checked only for /r/.
        words = [(row["novel"], True)]
        for key in ("a", "b"):
            words += [(row[key]["say"][0], True), (row[key]["say2"], True), (row[key]["say"][1], False)]
        for word, said in words:
            ref = reference_for(word)
            if ref is None:
                problems.append(f"{feature}: {word!r} has no reference pronunciation")
                continue
            phones = {p.rstrip("012") for form in ref.variants for p in form}
            if said and focus and not (phones & set(focus)):
                problems.append(f"{feature}: {word!r} does not contain {sorted(focus)}")
            if feature != "rhotic_lateral" and "R" in phones:
                problems.append(f"{feature}: {word!r} contains /r/, which the tapped-R "
                                f"problem would reject it for")
        for key in ("a", "b"):
            if row[key]["say"][0] not in row[key]["sentence"].lower():
                problems.append(f"{feature}/{key}: the sentence does not contain the target word")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args()
    problems = check()
    for p in problems:
        print("problem:", p)
    if problems:
        return 1
    if args.check:
        print("live stimulus tables are consistent")
        return 0
    files = {"live_list_a.json": training_list("A"), "live_list_b.json": training_list("B"),
             "live_assessment.json": assessment()}
    for name, items in files.items():
        (OUT / name).write_text(json.dumps({"items": items}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote stimuli/{name}: {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
