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
  `stimulus_audio`, and `GET` to stream it back. Files under `stimulus_audio/`
  next to `study_audio/`.
- `PUT /authoring/items/{id}` to edit one item in place. Import exists;
  single-item edit does not.
- A dashboard aggregate endpoint, or the console composes it from
  `/study/balance`, `/measures/participants/{id}/questionnaires` and the
  session summaries.
- CORS for the console's origin.

## Stack

Vite, React, TypeScript, React Router, TanStack Query. Plain CSS variables
for theme, matching the app's palette. No component library: the surface is
small and a library would bring more UI than the console has screens.
Recording through `MediaRecorder`, resampled to 16 kHz mono WAV on the client
before upload so the server stores exactly the format the tablet plays.

## Order

1. Sign in, participants, assignment. Two days. Replaces the tablet's role
   as the only place a participant can be created.
2. Stimulus sets with validation. Two days. Replaces the script.
3. Model audio. One day. Unblocks the perception items.
4. Dashboard. One day.

Each step ships on its own and is useful on its own.
