"""Build the three stimulus sets from one table of Kenyan English contrasts.

    python scripts/build_stimuli.py            # write stimuli/*.json
    python scripts/build_stimuli.py --check    # verify the tables are complete

Why a generator rather than three hand-written files: the design requires lists
A and B to be matched feature for feature and slot for slot, and the assessment
set to draw equally from both plus novel words. Maintaining that by hand across
three files is how a list quietly ends up with one extra KIT/FLEECE item.

The JSON it writes is the import format and is meant to be edited afterwards;
this script exists so the first version is structurally correct and so the
derivation is written down.

WHAT THE WORDS WERE CHOSEN FOR

Each feature is a documented Kenyan English transfer feature and is teachable
inside a session. Words like *epitome* and *hyperbole* were deliberately
excluded: they test whether someone has seen the word written, which is lexical
knowledge, not phonological transfer, and only the second is what this tutor
teaches.

Every training word has a minimal-pair partner, so the same word supports a
production item and a perception item without introducing a second variable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stimuli"

# feature -> (list A word, its pair), (list B word, its pair), (novel, its pair)
#
# The three words in a row are matched: same feature, same syllable count,
# comparable frequency. A participant trains on A or B and is assessed on all
# three, which makes the list they did not train on their own matched control.
CONTRASTS: dict[str, dict] = {
    "trap_palm_strut": {
        "a": ("hat", "heart"), "b": ("cap", "carp"), "novel": ("match", "march"),
        "sentence_a": "She put the hat on the table.",
        "sentence_b": "He wore a red cap to school.",
    },
    "kit_fleece": {
        "a": ("ship", "sheep"), "b": ("bit", "beat"), "novel": ("fill", "feel"),
        "sentence_a": "The ship is leaving the port.",
        "sentence_b": "She ate a small bit of bread.",
    },
    "foot_goose": {
        "a": ("pull", "pool"), "b": ("full", "fool"), "novel": ("look", "Luke"),
        "sentence_a": "Please pull the door open.",
        "sentence_b": "The glass is full of water.",
    },
    "dental_fricative": {
        "a": ("think", "sink"), "b": ("three", "tree"), "novel": ("thin", "tin"),
        "sentence_a": "I think the answer is here.",
        "sentence_b": "There are three books on the desk.",
    },
    "rhotic_lateral": {
        "a": ("right", "light"), "b": ("rice", "lice"), "novel": ("road", "load"),
        "sentence_a": "Turn right at the next corner.",
        "sentence_b": "We cooked rice for dinner.",
    },
}

# Prosodic features are not minimal pairs; they are answered by tapping a
# syllable, so they carry their own table.
PROSODIC: dict[str, dict] = {
    "schwa_reduction": {
        "a": ("banana", ["ba", "na", "na"], [0, 2]),
        "b": ("camera", ["ca", "me", "ra"], [1, 2]),
        "novel": ("together", ["to", "ge", "ther"], [0, 2]),
        "sentence_a": "He ate a banana for lunch.",
        "sentence_b": "The camera is on the shelf.",
    },
    "polysyllabic_stress": {
        "a": ("photography", ["pho", "to", "gra", "phy"], 1),
        "b": ("economic", ["e", "co", "no", "mic"], 2),
        "novel": ("industrial", ["in", "dus", "tri", "al"], 1),
        "sentence_a": "She studies photography at college.",
        "sentence_b": "They discussed the economic report.",
    },
}


def training_list(label: str) -> list[dict]:
    """One training list: production and perception for every feature.

    Each feature contributes a spoken item, the same word in a carrier
    sentence, and a perception item on the same contrast. The spoken items are
    what the K/D feedback manipulation acts on; the perception item is scored
    right or wrong and gets no condition-specific feedback, which is why it can
    sit in a training block without diluting the manipulation.
    """
    key = "a" if label == "A" else "b"
    sentence_key = f"sentence_{key}"
    items: list[dict] = []

    for feature, row in CONTRASTS.items():
        word, partner = row[key]
        items.append({
            "exercise_type": "repeat_word",
            "spec": {"word": word},
            "target_feature": feature,
            "match_key": f"{feature}-say",
        })
        items.append({
            "exercise_type": "read_sentence",
            "spec": {"sentence": row[sentence_key], "target_word": word},
            "target_feature": feature,
            "match_key": f"{feature}-sentence",
        })
        items.append({
            "exercise_type": "minimal_pair_id",
            # The participant hears one of the two and taps which. Needs
            # stimulus audio before it can run; see stimuli/README.md.
            "spec": {"options": [word, partner], "answer": word},
            "target_feature": feature,
            "match_key": f"{feature}-hear",
        })

    for feature, row in PROSODIC.items():
        word, syllables, answer = row[key]
        items.append({
            "exercise_type": "repeat_word",
            "spec": {"word": word},
            "target_feature": feature,
            "match_key": f"{feature}-say",
        })
        items.append({
            "exercise_type": "read_sentence",
            "spec": {"sentence": row[sentence_key], "target_word": word},
            "target_feature": feature,
            "match_key": f"{feature}-sentence",
        })
        if feature == "schwa_reduction":
            items.append({
                "exercise_type": "schwa_spot",
                "spec": {"word": word, "syllables": syllables,
                         "answer_indices": answer},
                "target_feature": feature,
                "match_key": f"{feature}-tap",
            })
        else:
            items.append({
                "exercise_type": "stress_place",
                "spec": {"word": word, "syllables": syllables,
                         "answer_index": answer},
                "target_feature": feature,
                "match_key": f"{feature}-tap",
            })

    return items


def test_set() -> list[dict]:
    """The assessment set: trained, matched control, and novel, per feature.

    Spoken items only. The pre/post/delayed comparison is about production, and
    a perception item answered by tapping would be measuring a different thing
    on the same scale. Perception change is measured inside the training
    blocks, where those items already live.
    """
    items: list[dict] = []
    for feature, row in CONTRASTS.items():
        for origin in ("a", "b", "novel"):
            word, _partner = row[origin]
            items.append({
                "exercise_type": "repeat_word",
                "spec": {"word": word},
                "target_feature": feature,
                "match_key": f"{feature}-{origin}",
            })
    for feature, row in PROSODIC.items():
        for origin in ("a", "b", "novel"):
            word = row[origin][0]
            items.append({
                "exercise_type": "repeat_word",
                "spec": {"word": word},
                "target_feature": feature,
                "match_key": f"{feature}-{origin}",
            })
    return items


def check() -> list[str]:
    problems: list[str] = []
    for feature, row in CONTRASTS.items():
        words = {row["a"][0], row["b"][0], row["novel"][0]}
        if len(words) != 3:
            problems.append(f"{feature}: the three words are not distinct")
        for origin in ("a", "b", "novel"):
            word, partner = row[origin]
            if word == partner:
                problems.append(f"{feature}/{origin}: word and pair are identical")
    for feature, row in PROSODIC.items():
        for origin in ("a", "b", "novel"):
            word, syllables, _ = row[origin]
            if "".join(syllables).lower() != word.lower():
                problems.append(
                    f"{feature}/{origin}: syllables do not spell {word!r}")
    a, b = training_list("A"), training_list("B")
    if len(a) != len(b):
        problems.append(f"lists are different lengths: {len(a)} vs {len(b)}")
    def words(items: list[dict]) -> set[str]:
        # minimal_pair_id carries its words in `options`, not `word`; a plain
        # .get() there returns None and the overlap check silently compares
        # None with None, which looks like every list sharing a word.
        found: set[str] = set()
        for item in items:
            spec = item["spec"]
            for key in ("word", "target_word"):
                if spec.get(key):
                    found.add(spec[key])
            for option in spec.get("options", []):
                found.add(option)
        return found

    words_a, words_b = words(a), words(b)
    if words_a & words_b:
        problems.append(f"lists share words: {sorted(words_a & words_b)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the tables without writing anything")
    args = parser.parse_args()

    problems = check()
    for problem in problems:
        print("  PROBLEM:", problem)
    if problems:
        return 1
    print("Tables are consistent.")
    if args.check:
        return 0

    OUT.mkdir(exist_ok=True)
    for name, items in (("list_a", training_list("A")),
                        ("list_b", training_list("B")),
                        ("test_set", test_set())):
        path = OUT / f"{name}.json"
        path.write_text(json.dumps({"items": items}, indent=2) + "\n",
                        encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}  ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
