// Part 1 of the system guide: architecture. Builds docs/SYSTEM_GUIDE.docx.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ImageRun, AlignmentType, LevelFormat, ShadingType, BorderStyle, PageBreak, TableOfContents,
} = require("docx");

const here = __dirname;
const img = (name, w, h) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 120, after: 120 },
  children: [new ImageRun({ type: "png", data: fs.readFileSync(path.join(here, name)), transformation: { width: w, height: h } })],
});
const P = (text, opts = {}) => new Paragraph({ spacing: { after: 140 }, ...opts, children: typeof text === "string" ? [new TextRun(text)] : text });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, spacing: { before: 360, after: 160 }, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, spacing: { before: 240, after: 120 }, children: [new TextRun(t)] });
const B = (t) => new TextRun({ text: t, bold: true });
const I = (t) => new TextRun({ text: t, italics: true });
const C = (t) => new TextRun({ text: t, font: "Consolas", size: 20 });
const bullet = (runs) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 }, children: typeof runs === "string" ? [new TextRun(runs)] : runs });
const step = (runs) => new Paragraph({ numbering: { reference: "steps", level: 0 }, spacing: { after: 80 }, children: typeof runs === "string" ? [new TextRun(runs)] : runs });
const caption = (t) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: t, italics: true, size: 20, color: "555555" })] });

function table(header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (text, isHead, w) => new TableCell({
    width: { size: w, type: WidthType.DXA },
    shading: isHead ? { type: ShadingType.CLEAR, fill: "E8EEF6", color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text, bold: isHead, size: 20 })] })],
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, true, widths[i])) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, false, widths[i])) }))],
  });
}
const gap = () => new Paragraph({ spacing: { after: 200 }, children: [] });

const children = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400, after: 200 }, children: [new TextRun({ text: "Pepper Pronunciation Tutor", bold: true, size: 56 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "System guide", size: 36 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "Parts 1 to 3: how the system is built, the data it collects, and how they will be analysed", size: 24, color: "555555" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "Part 4 (the interpretation of findings) follows in a later revision of this document.", size: 20, color: "777777" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "1 October 2026", size: 22, color: "555555" })] }),
  new Paragraph({ children: [new PageBreak()] }),

  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Contents", bold: true, size: 32, color: "1F3A5F" })] }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),

  new Paragraph({ spacing: { before: 1200, after: 120 }, children: [new TextRun({ text: "Part 1", bold: true, size: 48, color: "1F3A5F" })] }),
  new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "How the system is built, and how a session moves through it", size: 30, color: "555555" })] }),
  H1("1. What the system is for"),
  P("The system runs a within-subject study of pronunciation feedback for Kenyan learners of English. A participant practises target words with the Pepper robot under two feedback conditions. In condition K the robot only re-models the word. In condition D the robot also says what it heard, names the sound to fix, and gives a cue. Production is measured before, after, and some weeks after training, with the robot silent on those occasions."),
  P("Everything described here exists to make three things true at once: the participant gets a fair verdict on what they said, the two conditions differ only in the feedback wording, and every number in the final analysis can be regenerated from the stored audio."),

  H1("2. The parts"),
  img("architecture.png", 620, 339),
  caption("Figure 1. The five components and how they talk to each other."),
  table(["Component", "Technology", "What it does"], [
    ["Tablet app", "Android, Kotlin, Jetpack Compose, QiSDK", "The participant's interface. Shows the item, records the attempt, plays the stored model audio, asks the questionnaires, and drives the robot through the QiSDK. Also runs standalone on a phone for testing, with the robot's speech skipped."],
    ["Pepper robot", "SoftBank Pepper, NAOqi via QiSDK", "Speaks the prompt and the feedback, performs the celebration, holds the tablet. It has no logic of its own; the tablet tells it what to say."],
    ["Backend", "Python, FastAPI, SQLAlchemy", "Owns every decision: which items a session gets, whether an attempt was correct, what the robot should say, who is in which group. Holds the scoring pipeline."],
    ["Research console", "React, TypeScript, Material UI", "The researcher's tool. Participants and group balance, stimulus sets with model audio, the dashboard, and the blind rating screen with its audit."],
    ["Database", "PostgreSQL", "Participants, sessions, attempts with their full scoring record, items, questionnaires, notes, ratings."],
  ], [1700, 2300, 5360]),
  gap(),
  P([B("Where the audio lives. "), new TextRun("Every attempt's recording is kept on the server under "), C("study_audio/<session>/<item>_attempt<n>.wav"), new TextRun(", and every item's model recording under "), C("stimulus_audio/<item>.wav"), new TextRun(". The database stores the path, not the bytes. Nothing in the audio leaves the server except to a signed-in researcher or to a rater for a clip in a rating set whose participant consented to retention.")]),
  P([B("Who may do what. "), new TextRun("Accounts carry a role. A researcher reaches everything. A rater reaches only the rating screen. The tablet signs in as a researcher account. The one route open without a token is the model audio for an item, because the tablet's media player fetches it by bare URL.")]),

  H1("3. A session, end to end"),
  P("The sequence below is a training session. An assessment session is the same except that step 7 says a fixed acknowledgement instead of feedback and never offers a second attempt."),
  step([B("Plan. "), new TextRun("On the tablet the researcher opens the participant's study plan. The backend reports which step is next (pre-test, block 1, block 2, post-test, delayed), from the participant's group and the sessions already completed.")]),
  step([B("Start. "), new TextRun("The tablet posts the session. The backend stamps the session type, the condition (K or D), the block index and the word list, and draws the item order from a seed. None of that is chosen on the tablet.")]),
  step([B("Items. "), new TextRun("The tablet fetches the session's items. Each comes with its exercise type and only the presentation it needs. For a choice item the correct answer is stripped out before sending, and the name is blanked, so the answer key never reaches the device.")]),
  step([B("Prompt. "), new TextRun("The robot speaks the instruction. If the item has a stored model recording, that recording plays from the tablet and the robot does not say the word itself, so every participant hears the same model every time. The tablet notes when the prompt ended.")]),
  step([B("Record. "), new TextRun("The tablet's recorder waits for speech, keeps a quarter second of pre-roll so the first consonant survives, and stops after a silence hangover sized to the item (longer for sentences). It notes when speech started and ended, and refuses only recordings that are silent or badly clipped.")]),
  step([B("Score. "), new TextRun("The recording goes to the backend with the condition, the timestamps, the replay count, and whether the slow replay was used. The pipeline in section 4 produces a verdict, a graded score, and per-phone detail.")]),
  step([B("Feedback. "), new TextRun("The backend composes what the robot says from the verdict and the condition. K hears a warmth marker and a re-model. D hears the same marker, then what the recogniser heard, the sound to fix, a cue, and the re-model. The text, the verdict and whether a retry follows all come from the server in one response.")]),
  step([B("Retry or move on. "), new TextRun("A wrong first attempt in training gets one more try. A skip, with its reason, is recorded as a skip and never as an error. Choice items (minimal pair, syllable stress, schwa spot) are answered by tap and judged on the server; in D the correct answer is revealed after a wrong tap.")]),
  step([B("Questionnaire and summary. "), new TextRun("After the last item the tablet asks the session questionnaire (Godspeed, intrinsic motivation and feedback trust items, seven-point, reversed items hidden), then shows a summary. In assessments the summary shows no scores.")]),
  step([B("Complete. "), new TextRun("The tablet marks the session complete. If the network was down during an assessment, attempts were queued on the device and are uploaded now, with their original timestamps.")]),

  H1("4. The scoring pipeline"),
  img("pipeline.png", 620, 231),
  caption("Figure 2. One attempt through the pipeline, and what is stored."),
  H2("4.1 From the word to its phones"),
  P("The target word is looked up in the BEEP British English dictionary first, then CMUdict with British adaptation rules, then a grapheme-to-phoneme model as a last resort. Every accepted pronunciation variant is kept, and the one that aligns best to the audio is the one scored. The source is recorded with the attempt, and a target that came from the g2p fallback is flagged for review."),
  P("A read-aloud item aligns the whole carrier sentence, with the carrier words as context, and judges only the target word. Before this was done every correctly read sentence was marked wrong, because the word alone was being aligned against three seconds of speech."),
  H2("4.2 Acoustic scoring"),
  P([new TextRun("The acoustic model is "), C("wav2vec2-large-robust"), new TextRun(" fine-tuned for phone recognition on second-language English. It emits a probability over 39 phones for every 20 ms of audio. The expected phones are forced-aligned to those probabilities, and each phone gets a goodness-of-pronunciation score: how much more likely the expected phone was than the best competitor over its span.")]),
  P("A supervised layer on top, trained on the Speechocean762 corpus of rated second-language speech, turns the raw score into a calibrated 0 to 1 probability per phone. It is this calibrated score that the thresholds are set on. Its calibration is lenient on some vowel qualities, which matters in part 4."),
  H2("4.3 The verdict"),
  P("The verdict score is the mean of the two worst phone scores. The attempt is correct when that score is at least 0.60 and no phone is a corroborated error: a phone the free decode heard differently and the alignment scored below 0.45. Both signals must agree before a phone counts against the word, because the free decode alone is noisy (an unreleased final stop is routinely reported deleted)."),
  P("The phones an item's target feature is about are held to a stricter standard, added on 1 October. For a KIT/FLEECE item that is the vowel; for a tapped-R item it is R. If the decode substituted or deleted such a phone and it scored below 0.60, the attempt fails whatever the aggregate said. A minimal pair differs in one phone, and the two-phone average could not see it: \"bit\" said as \"bite\" had passed at 0.74."),
  H2("4.4 The safety net"),
  P("A false rejection is the worst failure this system can have. A volunteer told they mispronounced a word they said correctly stops trusting the feedback, and the error count the analysis rests on is inflated. So when the acoustics say wrong, the server runs a speech recogniser (Whisper, base.en) on the trimmed audio. If the transcript contains the target word and most of its phones had acoustic support, the verdict becomes correct. A transcript can rescue; it can never condemn."),
  P("There are two exceptions, both from the same day. The rescue is refused over a target-feature phone, because the recogniser's language model restores exactly those contrasts (\"tree\" becomes \"three\") and so cannot vouch for them. And a target phone the decode matched but the acoustics scored as weak is failed if the recogniser, asked, does not hear the target word either. Two models must both miss the contrast."),
  H2("4.5 What is stored"),
  P("Every spoken attempt keeps the verdict, the verdict score, the graded score, the recogniser's confidence, the expected and observed phones, every phone's score, the diagnoses, the transcript and whether it matched, the recording's peak, loudness and clipping, the text the robot spoke, the device timestamps, and three provenance fields: the pipeline version, a hash of the full configuration, and the model identifier. Re-scoring a stored recording with the same hash must reproduce the stored verdict, and a script exists to check that and to write corrected verdicts back when the pipeline changes."),

  H1("5. The study design, as the system enforces it"),
  table(["Design element", "Where it lives", "What the code guarantees"], [
    ["Two conditions, two lists, 2 x 2 counterbalance", "study_design.py, study_assignments table", "Groups K-A/D-B, K-B/D-A, D-A/K-B, D-B/K-A. Assignment goes to the least-filled group, ties broken from the participant's own id, so the balance survives N around 40."],
    ["Session types", "therapy_sessions.session_type", "training, pretest, posttest, delayed. Stamped by the server at creation; the analysis selects on it."],
    ["Assessment silence", "feedback.py, study_summary.py", "An assessment acknowledgement takes no verdict argument, so no later edit can make it leak. The summary after an assessment carries no scores."],
    ["Lists and the test set", "activity_categories.study_role", "Roles list_a, list_b, test are set on categories in the console. Sessions resolve items from the role, never from a name typed on the day."],
    ["Item identity over time", "activity_items.spec, session_activities.exercise_type", "An item's content cannot be edited once attempts exist. Each attempt copies the exercise type it was run as."],
    ["Target features", "activity_items.target_feature", "Seven Kenyan English transfer features. Every item names one, which is what makes a per-feature analysis and the focus-phone rule possible."],
    ["Retry budget", "pronunciation.py", "At most two scored attempts per item in training, one in assessments. A gated (unclear) recording does not consume a try."],
  ], [2300, 2600, 4460]),

  H1("6. Reproducibility"),
  bullet([B("Config hash. "), new TextRun("Every threshold, flag and model name is hashed into one string stored on each attempt. Two attempts with the same hash were judged by the same rules.")]),
  bullet([B("Re-scoring. "), new TextRun("scripts/rescore_sessions.py re-runs the pipeline on stored audio and reports every verdict that differs. With --apply it updates the rows, after writing the old values to a backup that --restore reads.")]),
  bullet([B("Deterministic recogniser. "), new TextRun("Whisper decodes at temperature zero, so a re-score sees the same transcript the session saw.")]),
  bullet([B("Blind ratings. "), new TextRun("The rating queue sends the target and the clip and nothing else. Verdicts are shown beside labels only after the labels exist.")]),
  bullet([B("Tests. "), new TextRun("249 automated tests pin the behaviours above, including the ones that protect participants: the answer key never sent, the assessment never scored aloud, the audio route never put behind a login.")]),

  H1("7. Glossary"),
  table(["Term", "Meaning"], [
    ["Attempt", "One recording of one item in one session. The unit the pipeline scores."],
    ["Verdict", "correct, close, incorrect, stress_error, gated or unscorable. Close and incorrect are treated the same by feedback."],
    ["Verdict score", "Mean of the two worst calibrated phone scores. Drives correct versus not."],
    ["Graded score", "Duration-weighted mean over all phones. The continuous outcome."],
    ["Free decode", "The phone sequence the acoustic model heard with no target imposed."],
    ["Forced alignment", "Fitting the expected phones to the audio to find where each one was said."],
    ["GOP", "Goodness of pronunciation: how much the expected phone beat its best competitor."],
    ["MD layer", "The supervised calibration layer trained on Speechocean762."],
    ["Rescue", "The recogniser's transcript turning an acoustic rejection into a correct verdict."],
    ["Focus phone", "A phone belonging to the item's target feature, held to the verdict line on its own."],
    ["Gated", "The recogniser was not confident enough to judge; the robot asks for a repeat and the attempt is excluded from error counts."],
    ["Condition K / D", "Knowledge of correct response only (re-model) / diagnostic (what was heard, the sound, a cue, the re-model)."],
  ], [2200, 7160]),
];

const data = JSON.parse(fs.readFileSync(path.join(here, "part2.json"), "utf8"));
children.push(...require("./part2.js")({ P, H1, H2, B, I, C, bullet, step, table, gap, caption, img, TextRun, Paragraph, PageBreak, data }));
children.push(...require("./part3.js")({ P, H1, H2, B, I, C, bullet, step, table, gap, caption, img, TextRun, Paragraph, PageBreak }));

const doc = new Document({
  features: { updateFields: true },
  creator: "Study team",
  title: "Pepper Pronunciation Tutor: system guide",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, color: "1F3A5F" }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: "2A4F7A" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "steps3", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{ properties: { page: { margin: { top: 1300, bottom: 1300, left: 1300, right: 1300 } } }, children }],
});

const out = path.resolve(here, "../SYSTEM_GUIDE.docx");
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2] || out, buf); console.log("wrote", process.argv[2] || out); });
