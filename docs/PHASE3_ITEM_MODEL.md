# Rethinking categories and items for Phase 3

Phase 3 turns the activity item into a typed exercise. The current model cannot
hold one. This is what is wrong, what replaces it, and what that costs.

---

## What the current model assumes

```python
class ActivityItem:
    name              # the word
    description       # what Pepper says
    category_id
    image_url, audio_url
    difficulty_level  # free string
```

Every one of these assumptions is load-bearing somewhere, and every one of them
breaks in Phase 3:

1. **There is exactly one kind of exercise.** Nothing on the item says what the
   participant is supposed to do, because until now the answer was always "say
   the word". Six of the nine Phase 3 types are tap-to-answer and never touch
   the pronunciation pipeline at all.

2. **`name` is both the stimulus and the answer key.** The touch path compares
   the tapped option against `item.name`. For `odd_one_out` the stimulus is four
   words and the answer is one of them; for `stress_place` the answer is a
   syllable index, not a word. There is nowhere to put either.

3. **Distractors are sampled, not designed.** `GET /selection-options` picks
   three other items from the same category at random. That is the opposite of
   what a perception item needs: the whole point of a minimal pair is that the
   distractor differs in exactly one contrast. A randomly-drawn distractor makes
   the item trivially easy and measures nothing.

4. **Nothing says what the item is testing.** The analysis Phase 3 exists to
   support is per-feature: does training on KIT/FLEECE transfer to untrained
   KIT/FLEECE words? With no feature on the item there is no way to group items
   for that, and no way to check that lists A and B are actually matched rather
   than matched by eye.

5. **Nothing links an item to its counterpart in the other list.** The design is
   within-subject across two difficulty-matched lists. "Matched" has to mean
   something checkable, and right now it means a claim in a paragraph.

6. **Which categories *are* the study lists lives in environment variables.**
   `STUDY_LIST_A_CATEGORY_ID` and friends are three UUIDs in a `.env` that is
   not in version control and, as of today, is not set. That is why a study run
   is currently blocked. A deployment detail was the wrong home for a fact about
   the experiment.

7. **`difficulty_level` is a free string** with no relationship to anything
   measurable.

---

## The replacement

### Items gain a type and a typed spec

```python
exercise_type    # repeat_word | read_sentence | minimal_pair_id | ...
spec             # JSON, shape determined by exercise_type
target_feature   # trap_palm_strut | kit_fleece | dental_fricative | ...
match_key        # groups an item with its counterpart in the other list
position         # authoring order
```

`spec` is JSON in the database and a discriminated union at the API boundary.
The alternative, a column per type, means roughly thirty mostly-null columns and
a migration every time an exercise type is added. The alternative to *that*,
untyped JSON with no validation, means a malformed item is discovered by a
participant mid-session. A discriminated union keyed on `exercise_type` gives
one column and a hard failure at authoring time, which is the only time it is
cheap.

The types, and what each spec holds:

| Type | Spec | Scored by | Measures |
|---|---|---|---|
| `repeat_word` | `word` | pipeline | Production, segmental |
| `read_sentence` | `sentence`, `target_word` | pipeline | Production in context |
| `picture_describe` | `prompt`, `seconds` | recorded only | Spontaneous production |
| `minimal_pair_id` | `options[2]`, `answer`, `stimulus_audio` | exact match | Perception, identification |
| `odd_one_out` | `options[3..4]`, `answer` | exact match | Perception, categorisation |
| `same_sound_match` | `cue`, `options[3..4]`, `answer` | exact match | Perception, categorisation |
| `syllable_count` | `options[3..4]`, `answer` | exact match | Prosodic awareness |
| `schwa_spot` | `word`, `syllables[]`, `answer_indices[]` | set match | Reduction awareness |
| `stress_place` | `word`, `syllables[]`, `answer_index` | exact match | Prosodic awareness |

The scoring path forks once, at the top, on `needs_asr(exercise_type)`. A
tap-answer item cannot reach the acoustic model, so it cannot false-reject
anyone. That matters directly: six of twenty pilot participants complained
unprompted that the robot could not hear Kenyan English, and for those six the
perception half of a session simply removes the failure mode.

### Categories gain a study role

```python
study_role   # list_a | list_b | test | NULL
```

The database becomes authoritative for which category is which list. The
environment variables stay as a fallback so nothing breaks mid-study, but the
health check now prefers the database. A researcher can bind a list from the app
instead of editing a file on the server and restarting it.

### Attempts record the exercise type they were run as

`session_activities.exercise_type` is denormalised from the item, for the same
reason `condition` and `block_index` already are: editing an item next month
must not rewrite what a stored attempt actually was.

---

## What `match_key` buys

Items sharing a `match_key` are the same slot in the design:

```
match_key  list A          list B          test set
kf-01      "ship"          "bit"           "pill"      (untrained)
tps-03     "cat"           "bat"           "hat"       (untrained)
```

The participant trains on A or B depending on their group. The assessment set
deliberately draws from **both** lists and adds novel words, which gives a
three-level within-subject factor that nothing else in the design provides:

| Item in the test set | For a participant trained on A | Measures |
|---|---|---|
| from list A | trained | item-specific gain |
| from list B | untrained, matched | control |
| neither list, same feature | novel | generalisation |

The control level is free: it is the list they did not practise, already
difficulty-matched to the one they did. Generalisation is the level that
separates learning from having memorised twelve words, so a feature with no
novel item in the test set cannot answer the question the study asks about it.

Three things become checkable rather than asserted:

- every slot has an item in both lists, so the lists are the same length and
  cover the same features;
- the assessment set draws equally from A and from B, so the trained/control
  contrast is balanced whichever list a participant got;
- every trained feature has a novel assessment item.

A validation endpoint reports violations. It refuses nothing: a half-built list
during authoring is normal, and the check belongs before a study day, not in the
way of one.

---

## Stimulus design

Stop using "hardest English words". Words like *epitome* and *hyperbole* test
whether someone has seen the word written, which is lexical knowledge and is not
what a pronunciation tutor teaches in one session. They also ceiling-out the
difficulty for exactly the wrong reason.

Build the lists around documented Kenyan English transfer features instead:

| Feature | Contrast | Example pair |
|---|---|---|
| `trap_palm_strut` | /æ/ vs /ɑː/ vs /ʌ/ merged | cat / cart / cut |
| `kit_fleece` | /ɪ/ vs /iː/ | ship / sheep |
| `foot_goose` | /ʊ/ vs /uː/ | pull / pool |
| `schwa_reduction` | unstressed vowels kept full | banana, about |
| `dental_fricative` | /θ/ /ð/ to /t/ /d/ | think / tink |
| `polysyllabic_stress` | stress placement | 'photograph / pho'tography |
| `rhotic_lateral` | tapped /r/ heard as /l/ | rot / lot |

These are teachable in a session, they are documented in the literature on
Kenyan English, and they give the paper a per-feature result table rather than
one aggregate number.

---

## Authoring

One item at a time through a form is the wrong shape for this. A minimal pair is
two words and a key; a matched slot is three items across three lists. Designing
stimuli happens in a spreadsheet, and twelve form submissions per list is how
transcription errors get in.

So: a bulk import that takes a whole list as JSON, validates every item against
its type's spec, and reports every problem at once rather than failing on the
first. Dry-run by default, because importing the wrong file over a list that has
already been run is not recoverable from the app.

The existing single-item form stays. It is the right tool for fixing one typo.

---

## What this does not change

- The table names. `activity_items` and `activity_categories` stay, as do every
  foreign key pointing at them. Renaming is cosmetic and would touch every
  stored session.
- The existing `repeat_word` behaviour. Items with no `exercise_type` are
  treated as `repeat_word`, so every stored item and every stored attempt keeps
  meaning what it meant.
- The scoring pipeline. Typed exercises fork *around* it, not through it.
