# Stimulus sets

Two generations of lists. The **live** lists are the ones the study runs on;
the pilot lists stay for the record, because the sessions already recorded
point at them.

| File | Role | Items | Built by |
|---|---|---|---|
| `live_list_a.json` | Live study List A | 20 | `scripts/build_live_stimuli.py` |
| `live_list_b.json` | Live study List B | 20 | `scripts/build_live_stimuli.py` |
| `live_assessment.json` | Live study Assessment (pre, post) | 15 | `scripts/build_live_stimuli.py` |
| `list_a.json` | pilot list A | 21 | `scripts/build_stimuli.py` |
| `list_b.json` | pilot list B | 21 | `scripts/build_stimuli.py` |
| `test_set.json` | pilot assessment set | 21 | `scripts/build_stimuli.py` |

All six are the import format for `POST /authoring/categories/{id}/items/import`.

## The live lists (2026-10-05)

Five features, four items each: two spoken words (`-say`, `-say2`), the first
word in a carrier sentence (`-sentence`), and one perception item on the same
contrast (`-hear`). The assessment holds the `-say` word from each list plus a
novel word per feature, spoken only.

| Feature | A: say / say2 / hear | B: say / say2 / hear | Novel |
|---|---|---|---|
| TRAP/PALM/STRUT | paddle / analysis / paddle–puddle | mastered / substantial / mastered–mustard | capacity |
| KIT/FLEECE | litter / statistical / litter–litre | filling / discipline / filling–feeling | significant |
| FOOT/GOOSE | pulling / bulletin / pulling–pooling | cookie / unusual / cookie–kooky | cushion |
| Dental fricatives | thinker / hypothesis / thinker–tinker | worthy / methodology / worthy–wordy | authentic |
| Tapped /r/ | correct / parallel / correct–collect | arrive / relevant / arrive–alive | liberal |

The vocabulary is advanced on purpose: the participants are undergraduates
who self-rate at B2 to C2, and the contrast sits in a stressed syllable of a
low-frequency or polysyllabic word. Longer words carry more phones for the
worst-two-phone verdict to trip on, so the audit's false-rejection rate per
feature matters more with these lists than with the pilot ones.

Why five and not seven, why four and not three, and why no `/r/` appears in
any non-rhotic word, is written at the top of `scripts/build_live_stimuli.py`.
In short: the scorer cannot reject a stress error or a full vowel for schwa,
so those two features could never trigger the feedback manipulation; a third
spoken item per feature is what feeds the primary outcome (repair after a
correction) and the revisit round; and P1's tapped /r/ scores sit below the
verdict threshold, so an /r/ in a "think" item would reject it for the wrong
reason.

Loading them, in the console (Stimuli page):

1. Create the three categories (or use the ones already made), import each
   file, and record model audio for every item. The `-hear` items cannot run
   until their audio exists.
2. Set the study role on each. The pilot lists hold the roles and have
   sessions recorded against them, so the console asks before handing a role
   over; on yes the pilot list keeps it as a *retired* role, its sessions stay
   labelled, and new sessions use the live list.
3. Open the design check. It should read `List A/B 20 items, Assessment 15,
   5 features (A 5 · B 5 · novel 5)` with no problems.

## Loading them

```
python scripts/build_stimuli.py          # regenerate from the contrast tables
```

Then, per category, dry-run first:

```
POST /authoring/categories/{id}/items/import   {"items": [...]}
POST /authoring/categories/{id}/items/import   {"items": [...], "apply": true}
PUT  /authoring/categories/{id}/study-role     {"study_role": "list_a"}
GET  /authoring/item-sets/validate
```

The import reports every problem at once and writes nothing unless `apply` is
true. `replace: true` clears the category first and is refused outright if any
existing item already has a recorded attempt, because deleting those would
orphan the attempts from the item they were answers to.

## What is in them

Seven Kenyan English transfer features, each contributing three items per
training list: the word spoken alone, the same word in a carrier sentence, and
a perception item on the same contrast.

| Feature | List A | List B | Novel |
|---|---|---|---|
| TRAP/PALM/STRUT | hat | cap | match |
| KIT/FLEECE | ship | bit | fill |
| FOOT/GOOSE | pull | full | look |
| Dental fricatives | think | three | thin |
| Tapped /r/ | right | rice | road |
| Schwa reduction | banana | camera | together |
| Polysyllabic stress | photography | economic | industrial |

The assessment set holds the same seven features three ways: the list A word,
the list B word, and a novel word. A participant trains on one list, so for them
those three become trained, matched control, and generalisation. That third
level is what separates learning from having memorised twenty-one words.

## Known gap: perception items have no audio yet

`minimal_pair_id` asks the participant to tap the word they heard. Its
`stimulus_audio` field is null in every generated item, so **these seven items
per list cannot run until audio exists for them**. The spoken and tapped-syllable
items are unaffected.

Two options, in order of preference:

1. Record a single speaker producing both members of each pair. Better for the
   paper: a human model is what the perception-training literature uses, and the
   recording is a fixed stimulus that cannot drift.
2. Synthesise once, store the file, and reference it. Acceptable, but it must be
   synthesised **once and stored**, not generated per turn. A pilot participant
   reported the pronunciation changing between repeats, and a stimulus that
   varies between presentations is not a stimulus.

Whichever is used, set `spec.stimulus_audio` on the item and re-import. Until
then, `GET /authoring/item-sets/validate` reports the design as sound because
the design *is* sound; the gap is production of materials, not structure.

## Changing the words

Edit the tables at the top of `scripts/build_stimuli.py` rather than the JSON,
and regenerate. The script enforces what the JSON cannot: that the three words
for a feature are distinct, that syllable breakdowns spell their word, that the
two lists are the same length, and that they share no words. Maintaining that by
hand across three files is how a list quietly ends up with one extra
KIT/FLEECE item.
