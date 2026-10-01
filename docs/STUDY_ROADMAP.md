# Roadmap: from word-repetition demo to a publishable pronunciation study

Six phases. Each one leaves the system runnable and each one is independently
useful, so a phase can slip without blocking the next study day. Phases 1 and 2
are prerequisites for collecting *any* analysable data; phase 3 is what makes
the study worth publishing; phases 4-6 raise quality and are where the second
paper comes from.

Status is updated as phases land. Nothing here is a commitment to dates.

---

## Phase 0 — the scorer (DONE, 2026-09-16)

The acoustic pipeline, the supervised MD layer, the British/Kenyan reference
adaptations, and the two safety nets (MD layer + server-side ASR rescue). On the
78 stored pilot attempts this moved correct verdicts from 24/78 to 62/78.

Outstanding from this phase, carried forward: label
`benchmarks/pilot_to_label.csv` and refit the verdict threshold on local data
(`scripts/refit_on_labels.py`). That is a human task, not a code task.

---

## Phase 1 — the participant record (DONE, 2026-09-17)

**Why first:** every later phase writes rows that reference a participant, and
retro-fitting a covariate you did not collect is impossible. Also the current
record holds clinical fields that the study has no lawful basis to collect.

- Drop `diagnosis_date` and `therapy_goals`. They are ASD-clinical fields; a
  diagnosis date from a healthy volunteer is special-category health data under
  the Data Protection Act 2019 with no purpose to justify it.
- Stop storing names. `participant_code` becomes the identifier; the
  code-to-name link stays on paper, offline, held by the researcher.
- Add the covariates the mixed-effects model needs and the fields that let a
  reviewer judge who the sample was:

  | Field | Why |
  |---|---|
  | `first_language` | Main predictor of which transfer features appear |
  | `other_languages`, `home_language` | Kenyan multilingualism is the norm |
  | `region_of_upbringing` | Dialect proxy |
  | `english_onset_age`, `primary_medium_of_instruction` | Standard SLA covariates |
  | `self_rated_english` (CEFR) | Covariate and sample description |
  | `voice_assistant_use` | Novelty / familiarity control |
  | `hearing_or_speech_difficulty` | Exclusion criterion |
  | `consent_*` + `consent_date` | Ethics trail |

**Landed:** model, Pydantic schema with controlled vocabulary, duplicate-code
409, `sql/2026_09_17_participant_record.sql` (applied), 12 tests in
`tests/test_participant.py`, and the Android enrolment form rebuilt around
sections with consent enforced before save. The robot no longer speaks a
participant identifier aloud.

**Still open in this phase:** an export that produces the participant table for
the paper. Deferred to phase 6 with the rest of the analysis export.

**Note on naming:** the table stays `children` and the FK stays `child_id`. A
rename to `participants` touches ~20 files and every stored session; it is
cosmetic and is deliberately deferred so it cannot break a study day.

---

## Phase 2 — study integrity in the app (DONE, 2026-09-17)

**Why:** without this, data collected is not attributable to a condition and the
pre/post design cannot be run at all. Every session recorded before this phase
has `condition = NULL`.

1. **Sessions created through `POST /study/sessions`**, so the condition is
   stamped at creation. The app currently uses `/activities/sessions/`, which
   defaults to D and logs a warning nobody sees.
2. **Assessment mode**: a session type that records and scores silently and
   gives *no* feedback, for the pre-test, immediate post-test and delayed
   post-test. Without it there is no learning measure, only within-session
   imitation.
3. **Group, block and condition shown in the app**, read from
   `study_assignments`, never re-derived on the device.
4. **Item order randomised from a stored seed**, so the order is reproducible
   and reportable.
5. **Audio quality guard at capture**: level meter, reject clipped or
   near-silent clips before upload, warn on long clips. The last batch contains
   a 2 s clip of clucking and one of a bystander conversation.
6. **Device-side timestamps** for prompt-end and speech-onset, so response time
   is not contaminated by network time.
7. **Offline queue**, so a dropped network does not lose an attempt.

**Landed, backend:** `session_type`, `block_index` and `item_order_seed` on
sessions; device timestamps and four recording-quality columns on attempts;
`POST /study/assessments`, `GET /study/sessions/{id}/items`,
`GET /study/participants/{id}/plan`; a partial unique index enforcing one
assessment per participant per phase; the scoring endpoint refusing to write
into an unstamped session for an enrolled participant, and returning a fixed
acknowledgement with no verdict in it for assessments.
`sql/2026_09_17_study_integrity.sql` (applied), 21 tests in
`tests/test_study_integrity.py`, 123 passing overall.

**Landed, app:** a study plan screen that starts every session through the study
routes and shows the assignment as the server reports it; the session runner
driven by the server's item order; assessment mode with no verdict on screen,
no animation and no colour; prompt-end and speech-onset instants measured in the
capture loop and sent with each attempt; recording-quality advice surfaced to
the researcher; silent and clipped takes discarded before upload, capped at two
per item; and an offline queue.

**Two decisions worth remembering:**

- The offline queue holds *assessment* attempts only. In a training block the
  feedback is the manipulation, so an attempt that queued instead of scoring
  would quietly run a K or D block with no feedback while the stored data still
  said K or D. Training stops visibly on a dropped network; an assessment
  queues, because the participant hears the same acknowledgement either way and
  a delayed post-test cannot be re-run a week later.
- `gives_feedback` is read from the server's response to each attempt, not from
  the step the researcher tapped. A stale screen cannot make a pre-test
  congratulate anyone.

**Still open:** `STUDY_LIST_A_CATEGORY_ID`, `STUDY_LIST_B_CATEGORY_ID` and
`STUDY_TEST_CATEGORY_ID` are not bound in the production `.env`. Until they
are, the plan screen shows the misconfiguration warning and refuses to start a
block. The test category must not overlap the two training lists: generalisation
to untrained words is what separates learning from memorising twelve words.

---

## Phase 3 — the activity engine (backend DONE, 2026-09-17; app pending)

**Why this is the research contribution, not just engagement.** Every
benchmark study measures *perception* alongside production, because perceptual
training is what drives production gains (Bradlow et al. 1997; Thomson 2011;
Fouz-González 2020). Perception items are tap-to-answer: they need no speech
recognition, so they cannot false-reject anyone. Six of twenty pilot
participants complained unprompted that the robot could not hear Kenyan
English; perception items remove that failure mode entirely for part of
the session.

Generalise the activity item into a typed exercise. Proposed types, drawn from
the English-with-Lucy diagnostic and from Duolingo's exercise mix:

| Type | Task | ASR needed | Measures |
|---|---|---|---|
| `repeat_word` | Current behaviour | yes | Production, segmental |
| `read_sentence` | Target word inside a carrier sentence | yes | Production in context |
| `minimal_pair_id` | "Tap what you hear": chair/share | no | Perception, identification |
| `odd_one_out` | Which word has a different vowel sound | no | Perception, categorisation |
| `same_sound_match` | Pair words by vowel (hate→day) | no | Perception, categorisation |
| `syllable_count` | Which word has a different syllable count | no | Prosodic awareness |
| `schwa_spot` | Listen, name the words containing a schwa | no | Reduction awareness |
| `stress_place` | Which syllable is stressed | no | Prosodic awareness |
| `picture_describe` | Timed spontaneous description | record only | Spontaneous production |

The scoring path forks at the top: tap-answer types are right/wrong and never
touch the pronunciation pipeline. Only `repeat_word`, `read_sentence` and
`picture_describe` go through the scorer.

This is also what raises the material above undergraduate boredom. Nobody in
the pilot found the task hard (7 strongly disagreed, 7 disagreed, 6 neutral).

**Stimulus design:** stop using "hardest English words". Those mix lexical
spelling-pronunciation knowledge (epitome, hyperbole) with phonological
transfer, and only the second is teachable in a session. Pick four or five
target features documented for Kenyan English — TRAP/PALM/STRUT, KIT/FLEECE,
FOOT/GOOSE, schwa and vowel reduction, dental fricatives, polysyllabic stress —
and build two difficulty-matched item lists around them, with untrained
generalisation items sharing the same features.

**Landed, backend:** items carry `exercise_type`, a typed `spec`,
`target_feature` and `match_key`; categories carry `study_role`, so which
category is list A is a fact in the database rather than an environment
variable, which is what was blocking a study run. `POST /study/.../answers`
grades tapped items server-side, and the two paths refuse each other's work.
`/authoring` takes a whole list as one document, validates every row and
reports every problem at once. `GET /authoring/item-sets/validate` checks the
invariants the design depends on. 22 tests in `tests/test_exercises.py`, 149
passing overall. See `docs/PHASE3_ITEM_MODEL.md` for why the item model had to
change at all.

**Landed, stimuli:** seven features x three item types x two matched lists,
plus a 21-item assessment set, in `stimuli/`, generated by
`scripts/build_stimuli.py` and imported. The design now validates as sound and
`GET /study/balance` reports no list problems.

**Three decisions worth remembering:**

- The answer key is not sent to the tablet, and option order is shuffled from
  the session seed. Grading happens on the server, so the correct answer is
  never in a payload a participant is holding.
- Tapped items carry no condition, even inside a training block. K and D are
  ways of wording a *pronunciation* correction; a perception item has no
  production to diagnose, so applying a condition would label rows the
  manipulation never touched.
- The assessment set deliberately reuses words from both training lists and
  adds novel ones. A participant trains on one list, so the other becomes their
  matched control for free, and the novel words measure generalisation. An
  earlier version of the validator flagged any reuse as an error; that was
  wrong and contradicted the design.

**Still open:**

1. **Perception items have no audio.** `minimal_pair_id` asks which word was
   heard and `stimulus_audio` is null, so those seven items per list cannot run
   yet. See `stimuli/README.md`; recording one speaker is preferred over TTS.
2. **The app cannot render typed exercises.** It runs `repeat_word` only, so a
   training block would currently present the seven tapped items with a
   microphone button. This is the next piece of work.
3. `odd_one_out`, `same_sound_match`, `syllable_count` and `picture_describe`
   are defined and validated but no stimuli use them yet.

---

## Phase 4 — engagement layer (DONE, 2026-09-17)

Directly traceable to pilot feedback and to what the Duolingo screens do well.

- **Slow replay ("turtle") button.** P18: "the pacing was a little bit fast".
  P6 asked for pauses for processing. Cheap, and it is a genuine pedagogical
  aid, not decoration.
- **Configurable inter-turn pacing** and a longer listening window.
- **"Can't speak now" / "can't listen now" escape hatches.** Duolingo's version
  of consent to skip. Prevents a stuck item from ending a session.
- **Progress bar and session summary.** Finite, visible progress.
- **Keep and formalise Pepper's success celebration.** Three participants
  independently named the movement and the "yay" as what boosted their
  confidence (P7, P13, P18). That is an embodiment effect worth measuring, not
  just keeping.
- **Consistent model audio.** P3: "sometimes the pronunciation was different
  when it repeated." Trace whether the teach turn and the re-model turn use the
  same TTS path; an uncontrolled stimulus invalidates the manipulation.

**Landed:** replay and slow replay, both counted onto the attempt; a skip with
a reason, stored as a skip and never as an error; a progress bar; session
completion that finally sets an end time; and a session summary rewritten from
scratch.

**The session summary was the real find here.** It was bound to the old system
in three ways, and one of them was a correctness bug that went around every
other guarantee in the study:

1. **It scored assessments.** It computed an accuracy percentage, listed each
   item right or wrong, wrote "Excellent progress! Ready for more challenging
   activities", and — worst — had Pepper *read the score out loud*: "your
   accuracy was 43 percent". After a pre-test that is the most direct feedback
   anywhere in the application. Phase 2 had closed this inside the session and
   the summary screen went straight around it.
2. **It reported zero minutes for every study session.** `end_time` was only
   ever set by the ad-hoc `/activities/next-item` route, which a study session
   never calls.
3. **It averaged incomparable things.** Gated attempts counted as errors,
   perception and production went into one number, and nothing was grouped by
   target feature — the entire reason Phase 3 put a feature on every item.

The replacement is `app/services/study_summary.py`: silent after an assessment
by construction (the server sends no score at all, so there is nothing on the
device that could be displayed by mistake), duration derived from the attempts
when no end time was recorded, gated and skipped attempts named rather than
counted as errors, and per-feature and per-exercise breakdowns. 17 tests in
`tests/test_session_summary.py`, 171 passing overall.

**Two decisions worth remembering:**

- A skip is a separate column from `gated`, not the same one. Both are excluded
  from correction-rate denominators, but "the recogniser was not confident" and
  "the person chose not to answer" are different observations and collapsing
  them would lose which.
- The slow replay wraps the same string in speed markup rather than taking a
  second code path. P3 reported the pronunciation changing between repeats, and
  two ways of producing the model is how that happens.

**Still open:** stored model audio per item, which would make the stimulus
identical on every presentation rather than merely consistent within one TTS
engine. It is the same work as the perception-item audio gap from Phase 3 and
should be done once, for both.

---

## Phase 5 — measurement instruments (DONE, 2026-09-17)

- **In-app questionnaire keyed to `session_id`.** Currently the Google Form
  joins to sessions only by a hand-typed code like "P2" while the database uses
  UUIDs, so no rating can be attributed to a condition with certainty.
- **Fix the broken items.** The current form has "The tutor caught my" and "The
  tutor was likable attention" — a line split wrongly — and duplicates
  "likable". Those two columns are unusable.
- **Replace ceiling-bound scales.** Pleasant / kind / friendly / likable all sit
  at strongly-agree; enjoyment is 14/20 at the top. A ceiling cannot show a
  condition difference. Use Godspeed, a short intrinsic-motivation inventory,
  and a feedback-trust scale that can be related to the measured
  false-correction rate.
- **Per-event feedback quality rating**, not one score per session. The
  session-level version (16/20 "accurate and specific") is the most useful item
  in the pilot data and deserves to be measured properly.

**Landed:** a 19-item instrument in `app/services/instruments.py` -- abbreviated
Godspeed, three IMI subscales, and a feedback-trust scale -- served and stored
against `session_id`, plus a per-attempt helpfulness rating and a researcher
session note. 13 tests in `tests/test_instruments.py`, 187 passing overall.

**Where the questionnaire sits, and why it matters.** Between the session and
its summary, never after it. A participant who has just been shown "75%
accuracy" is no longer rating the tutor, they are rating their own result, and
the correlation between accuracy and "the tutor was helpful" would then be a
property of the screen order rather than of the feedback. The route pops itself
off the back stack so Back cannot walk into it after the score has been seen.

**Who is asked.** Training blocks only. There is no tutor behaviour in a
pre-test to form an impression of, so asking would collect ratings of something
that did not happen, and asking at all would frame the test as a performance
worth reflecting on. The endpoint refuses a submission for an assessment rather
than relying on the app to not offer one.

**What replaced the old session feedback.** The star rating and three boxes of
clinical prose are gone. They asked an unblinded researcher for their view of
the participant's "progress and achievements" immediately after watching them,
which is not a measure of anything here -- the recordings are -- and which puts
an impression next to the data. In its place is a set of checkboxes for the
things that would make a session unusable: interrupted, noisy, equipment
problem, participant unwell, instructions explained in another language, plus a
recommend-exclude flag and one free-text line. Quick enough to actually fill in
between participants, which the four-box version was not.

**Three anti-ceiling decisions:**

- Seven points, not five. A five-point scale with a virtuous end is what
  produced the pilot's ceiling.
- Named poles ("Unkind ... Kind") rather than agree/disagree about a virtuous
  statement, which has one obviously nice end.
- Reverse-scored items, and the reversal flag is never sent to the tablet. A
  respondent who knows which items are flipped can stay consistent on purpose,
  which is exactly what reversals exist to detect. Straight-lining now shows up
  as an inconsistent total rather than a perfect one, and the time taken is
  stored alongside.

---

## Interlude, 2026-09-25: what the first real sessions showed

The researcher ran training blocks on 2026-09-18 and reported four things.
Each turned out to be real, and three were the same kind of bug: a decision
made for single words that nobody revisited when sentences arrived.

**Every read-aloud sentence was marked wrong.** The scoring endpoint passed
`item.name` as the reference, and for a sentence item that is the *target
word*. The participant read "He ate a banana for lunch." and the aligner laid
twenty-five phones over the six of "banana". The transcript column showed the
sentence read perfectly on every one. Fixed by `score_sentence`: the whole
sentence is aligned so the carrier words anchor the target, and every
judgement is made over the target's phones alone. Re-scoring the stored audio
of 2026-09-18 through the fixed path: 13/42 correct before, 40/42 after. The
two that stay wrong are "cup" for "cap", which the recogniser also heard.

**"Turn right at the next corner" was unscorable: too long.** The 4 s ceiling
and the recorder's 5 s cap were sized for one word. Sentences now get 10 s on
the server and 12 s with a longer silence hangover on the tablet.

**Pepper did not say the prompt until the speaker was tapped.** Two Say actions
were being started at once: the plan screen's greeting was still playing when
the session asked for the item prompt, the second Say threw, and its callback
fired as though it had been spoken. All robot speech now goes through one
queue and is spoken in order.

**The supervisor could not tell K from D.** Two reasons in the data. D fell
back to K's exact wording whenever no phone was nameable, which after the
sentence bug was most of the time. And even when D did diagnose, it never said
what the participant had actually produced. D now says it: "I heard cup. The
word is cap. The sound to fix is the a sound, as in cat. Drop your jaw and
spread your lips. Listen again: cap." The heard word comes from the
recogniser's transcript, not the phone alignment, because whole-word
recognition is a different and far more reliable signal than phone-pair
identification. For tapped items, D now shows and names the right answer after
a wrong one, and K does not, so tapped rows carry the condition from here on.

`docs/CONSOLE.md` scopes the research console the researcher proposed. It is
the right call: the stimulus lists should not live in a script, and the
perception-item audio needs somewhere to be recorded.

---

## Phase 6 — rater tooling and analysis

- Stratified sampler for the rating set; blind randomised playback UI.
  **Done 2026-09-25**, in the console. One screen for two tasks: the 78
  pilot recordings, labelled binary, which feeds `refit_on_labels.py` through
  an export that fills the CSV's `human_label` column; and the study
  ratings, several raters, binary plus a 1-5 accuracy plus the sound heard
  going wrong, over a sample stratified by session type, condition and
  feature, with a tenth of clips repeated for within-rater consistency.
  Blind by construction: the queue sends the target and the clip and nothing
  else -- the old CSV put the verdict, score and transcript in the columns
  beside the label. Rater accounts carry a role and are refused by every
  researcher endpoint; participant audio is served signed-in only and never
  to a rater for a participant who did not consent to retention. Agreement is
  computed, not described: percent agreement and Cohen's kappa per pair,
  Fleiss' kappa across all raters, within-rater agreement on the repeats, and
  a disagreement list for adjudication.
- Pipeline audit. **Done 2026-09-25.** A third rating task, `review`, for
  the researcher alone: every stored attempt whose verdict rested on the
  least evidence, tagged with why -- `rescued` (the acoustics said wrong and
  the ASR transcript overrode them; the scorer's only route to a false
  acceptance), `heard_but_rejected` (the transcript held the target and the
  verdict was still wrong; the route to a false rejection), `close`, and
  `borderline`. Judged blind on the same screen; `GET /ratings/audit` then
  puts the labels beside the verdicts and reports the false-rejection rate
  (of what a person called right, how much the robot contradicted) and the
  false-acceptance rate (of what a person called wrong, how much got
  through), overall and per reason. The audit of 2026-09-25 that prompted
  it: of 148 stored attempts since 09-17, 18 verdicts were transcript
  rescues with acoustic scores 0.34-0.57, and in 4 of the 7 most recent the
  phone the rescue overrode was the item's own target-feature phone
  ("three" TH=0.21, "pull" UH=0.41). Whisper normalises exactly the
  contrasts the study measures, so a rescue there is not evidence the
  contrast was produced. No threshold was moved: that waits for the audit
  to say so on more than a handful of clips.
- Focus-phone rule. **2026-10-01.** Two attempts in the researcher's own
  session passed and should not have: "bit" said as "bite" (IH 0.58,
  decode B AY) came out 0.74 under worst_k=2 and was praised; "rice" said
  as "lice" (R 0.60, decode L AY S) likewise. A minimal pair differs in one
  phone by definition, so an aggregate over the word is the wrong
  instrument for the contrast the item tests. The scorer now holds an
  item's target-feature phones (`exercises.FEATURE_PHONES`) to the verdict
  threshold on their own: substituted or deleted by the decode AND scored
  below 0.60 fails the attempt, and the transcript rescue is refused over
  such a phone, since Whisper restores exactly these contrasts. Feedback
  names the failed phone even when it scored above the nameable ceiling,
  so D says "I heard bite. The word is bit. The sound to fix is ...".
  Later the same day "lice" passed a second time: the decode put a spurious
  R before the L (R IH L AY S), so the R was "matched", scored 0.45, and the
  word averaged 0.61. A focus phone the decode matched but the acoustics
  scored below phone_error now triggers the recogniser, and if it does not
  hear the target word either the phone fails -- the one place a transcript
  may condemn, and it takes two models not hearing the contrast. On the
  stored data this touches that one attempt and nothing else. The schwa
  case ("camera" read as ca-me-ra, AH -> EH at 0.71) is NOT caught: the
  acoustic model scores a full vowel for schwa leniently, and the only rule
  that would catch it -- fail any decode substitution of a focus phone
  regardless of score -- also rejects 24 other stored corrects including
  productions made right after a correction. That trade-off waits for
  labels. Items without a target feature are untouched;
  `focus_phone_rule=False` restores the 09-25 behaviour exactly. Replayed on the stored per-phone
  data since 09-17 it rejects 20 of 98 "correct" verdicts on feature
  items, including both above and all seven rescues that had overridden a
  target phone; those 20 are in the review task under `focus_phone` so the
  researcher's ear, not the simulation, decides whether the cost in false
  rejections is real.
- Stored verdicts re-scored. `scripts/rescore_sessions.py` now scores
  read-aloud items as the server does (`--apply` writes back, backing the
  touched columns up to a JSON file that `--restore` reads). Every
  read-aloud attempt stored before 09-25 had been scored against the target
  word alone; the dry run over 148 attempts since 09-17 flips 44 verdicts to
  correct and none to wrong. Until `--apply` is run the summaries and the
  dashboard read those 44 as errors the participant did not make.
- Two or three trained raters, ICC / Fleiss kappa reported, adjudication path.
- Analysis in linear mixed-effects models with participant, item and rater as
  random effects, effect sizes against Plonsky & Oswald benchmarks. This is the
  direct answer to the HAI reviewer who objected to unequal item-level Ns and a
  paired t-test "assuming equal variances".
- Reproducible export: every published number regenerable from raw audio plus
  the stored `config_hash`.

---

## Paper split

- **Instrument paper** (Speech Communication / CSL / SLaTE / Interspeech):
  accent-adapted phone-level mispronunciation detection for Kenyan English, the
  labelled corpus, reference-adaptation rules with measured effect, MD layer vs
  GOP vs the original ASR-word-match baseline, Cost/FRR/FAR per phone class,
  agreement with raters, CPU latency.
- **Tutoring study** (IJSR / CAL / ReCALL / THRI): within-subject
  counterbalanced diagnostic vs re-model feedback, pre/post/delayed production
  and perception outcomes on trained and untrained items, uptake, trust.
