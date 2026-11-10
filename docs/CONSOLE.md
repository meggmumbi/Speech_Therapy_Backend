# The research console

A web console, in React, for the parts of running the study that do not
belong on the robot's tablet. Proposed by the researcher on 2026-09-25 after
trying to author the official stimulus lists and finding that the answer was
"edit a Python script and re-run it". That is not an answer a researcher should
have to accept, and the audio gap on perception items has the same root: there
is no place to *make* the materials.

## Why a console rather than more tablet screens

The tablet is the participant's surface. It runs the session, it must stay
simple, and every screen added to it is a screen a participant can wander
into. Enrolling participants, assigning groups, writing stimulus lists,
recording model audio and reading a dashboard are the researcher's work, done
at a desk before and after sessions. They want a keyboard, a large screen and
a microphone that is not on a robot.

## What it does

**Sign in.** Same accounts as the app (`/auth`). No self-registration: the
console creates researcher accounts; participants never log in anywhere.

**Participants.** The enrolment form from the app, with the same controlled
vocabulary, plus what the tablet deliberately does not show: the
counterbalancing assignment, the five-step plan with dates, questionnaire
completion, session notes and exclusion flags. Assign-to-group is a button
here, with the balance report beside it so the researcher sees the cell counts
before committing a slot.

**Stimulus sets.** A table per list, one row per item, edited in place:
exercise type, spec fields for that type, target feature, match key. Import
from the JSON that `build_stimuli.py` writes, export back. Validation runs on
every save and the design check (`/authoring/item-sets/validate`) is a panel
at the top, so a list that is one KIT/FLEECE item short says so while it is
being written rather than the morning of a session.

**Model audio.** For each item, a record button and a play button. One speaker
records the word, the sentence, and both members of a minimal pair, in one
sitting, and the file is stored against the item as its `stimulus_audio`. This
is the piece that unblocks the seven perception items per list, and it is
also the fix for P3's "sometimes the pronunciation was different when it
repeated": a stored recording cannot vary between presentations.

**Dashboard.** Recruitment against target, cell balance, sessions per step,
false-correction rate from the rater sample once it exists, questionnaire
means by condition, recording quality over time. Read-only; every number is
a query against tables that already exist.

## What it needs from the backend

Nearly everything is already there. Missing:

- `POST /authoring/items/{id}/audio` to accept a recording and set
  `stimulus_audio`, and `GET` to stream it back. Done; files under
  `stimulus_audio/` next to `study_audio/`. The GET is unauthenticated: a
  stimulus word is not sensitive, and the tablet's media player fetches by URL.
- `PUT /authoring/items/{id}` to edit one item in place. Done, with
  `GET /authoring/categories`, `GET /authoring/categories/{id}/items`,
  `POST` to create one item, and `DELETE`.
- A dashboard aggregate endpoint. Done: `GET /study/dashboard?target=N`.
- CORS for the console's origin.

## Stack

Vite, React, TypeScript, React Router, TanStack Query. Plain CSS variables
for theme, matching the app's palette. No component library: the surface is
small and a library would bring more UI than the console has screens.
Recording through `MediaRecorder`, resampled to 16 kHz mono WAV on the client
before upload so the server stores exactly the format the tablet plays.

## Order

1. Sign in, participants, assignment. **Done 2026-09-25.** `console/`,
   Vite + React + TypeScript, builds clean under strict settings. Sign-in,
   participant list with the needs-a-code and consent state visible, enrolment
   and edit with consent as a hard stop, per-participant page with assignment
   (cell counts shown beside the button), exclusion with a reason, the
   five-step protocol as the server reports it, and questionnaire means by
   block. A balance page. `npm run dev` proxies `/api` to the backend.
2. Stimulus sets with validation. **Done 2026-09-25.** Lists in a sidebar
   with their study role, a table of typed rows, an editor shaped by the
   exercise type, JSON import (check first, then write) and export, role
   binding from a dropdown, and the design check pinned to the top of the
   page. The server validates every row against its type before writing and
   refuses to rewrite the question under an item that has recorded attempts;
   the prompt wording, feature and slot can still change.
3. Model audio. **Done 2026-09-25.** A recording panel under the item
   editor: record, listen back, keep. The browser decodes and resamples to
   16 kHz mono WAV before upload, the server normalises level and stores one
   file per item, and the tablet fetches it once, caches it, and plays it
   after the spoken instruction -- at 0.7x for the slow replay, so the slow
   version is the same file at a different rate. With a recording present the
   robot no longer says the word itself; two models is the inconsistency the
   recording exists to remove.
4. Dashboard. **Done 2026-09-25.** The console's landing page. One hero
   figure (participants through the full protocol, against a target the
   researcher sets), stat tiles, and five charts whose forms follow the
   data's job: counterbalancing cells and the protocol funnel are magnitude,
   accuracy and questionnaire means are K against D, recording quality per
   session day is state. Every chart has a table view and a hover readout, the
   categorical pair and the ordinal ramp were validated for colour-vision
   safety on the console's surface, and every number is computed by
   `app/services/dashboard.py` with the same definitions the summaries use:
   final attempts, gated and skipped excluded, training only. The
   false-correction tile exists and says "not yet"; Phase 6 supplies it.

Each step ships on its own and is useful on its own.

5. Rating. **Done 2026-09-25.** Listen-and-judge for the pilot labels and
   the study ratings, blind, keyboard-driven, with rater accounts that see
   nothing else; a researcher page for building the stratified sample,
   creating raters, reading the agreement statistics, adjudicating
   disagreements and exporting. Phase 6's first item.

   Model audio can also be **uploaded** (2026-10-01), for machines whose
   microphone does not work: a recording made on a phone in any format the
   browser decodes is converted to 16 kHz mono WAV and trimmed of its
   leading and trailing silence in the browser, then heard back and kept
   through the same step as a live take. The server never sees anything but
   WAV, so nothing downstream changed. Recording from the Pepper app was the
   other option and was not taken: it would put an authoring screen and a
   researcher login into the participant's app, on the tablet microphone.

   A third task, **Review the pipeline**, was added the same day: the
   researcher's own audit of the attempts the scorer was least sure about
   (transcript rescues, rejections despite the transcript holding the
   target, close calls, near-the-line corrects), judged blind, then read
   back on the Rating page as a false-rejection rate and a false-acceptance
   rate with the disagreements listed. Raters cannot see this task: its set
   is defined by what the model thought.
