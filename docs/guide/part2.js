// Part 2 of the system guide: the data collected and why.
module.exports = function part2(h) {
  const { P, H1, H2, B, C, bullet, table, gap, caption, TextRun, Paragraph, PageBreak, data } = h;
  const d = data;
  const pr = d.participant;
  const S = Object.fromEntries(d.sessions.map((s) => [s.type + (s.condition || ""), s]));
  const pre = S.pretest, post = S.posttest, K = S.trainingK, D = S.trainingD;
  const v = (s, k) => s.verdicts[k] || 0;
  const feat = d.by_feature;
  const FEAT_LABEL = { trap_palm_strut: "TRAP / PALM / STRUT", kit_fleece: "KIT / FLEECE", foot_goose: "FOOT / GOOSE", schwa_reduction: "Schwa and reduction", dental_fricative: "Dental fricatives", polysyllabic_stress: "Polysyllabic stress", rhotic_lateral: "Tapped /r/" };
  const ex = d.example_attempt;

  return [
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ spacing: { before: 1200, after: 120 }, children: [new TextRun({ text: "Part 2", bold: true, size: 48, color: "1F3A5F" })] }),
    new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "The data collected, and why each piece is there", size: 30, color: "555555" })] }),
    P("Every table below is read with the same question: what claim in the final paper rests on this column? A column with no claim behind it is not collected. The worked example throughout is participant P1, who completed the full sequence on 1 October: pre-test, condition D with list B, condition K with list A, post-test. P1 is the researcher's own end-to-end run, so the questionnaire answers are tap-throughs and the pronunciation errors are partly deliberate; the numbers show the shape of the data, not a result."),

    H1("8. What is collected, at a glance"),
    table(["Table", "One row per", "Rows for P1", "Carries the evidence for"], [
      ["children", "participant", "1", "Who the sample was; covariates for the mixed model; consent."],
      ["study_assignments", "participant", "1", "Which group, so which condition and list came first."],
      ["therapy_sessions", "session", "4", "The session type and condition every attempt inherits."],
      ["session_activities", "attempt (spoken or tapped)", `${d.sessions.reduce((a, s) => a + s.attempts, 0)}`, "Everything about what was said and what the robot did. The central table."],
      ["activity_categories, activity_items", "list and item", "3 lists, 63 items", "What was asked, with its target feature and exercise type."],
      ["session_questionnaires", "training session", "2", "Perception of the robot, motivation, trust in the feedback."],
      ["session_notes", "session, when something happened", "0", "Interruptions, noise, equipment trouble, exclusion recommendations."],
      ["rating_sets, ratings", "clip in a rating set; one judgement", "0 yet", "Human ground truth: the false-correction rate and inter-rater agreement."],
    ], [2300, 1900, 1200, 3960]),
    gap(),
    P("Audio is not in the database. Each attempt row points at its WAV file on the server, and the model recordings sit beside them. The database can be exported without the audio, and the audio can be re-scored without the database."),

    H1("9. The participant record"),
    P("The table is still called children for historical reasons; it holds adult volunteers. Names are not stored. The code-to-name link lives on paper with the researcher."),
    table(["Column", "P1", "Why it is collected"], [
      ["participant_code", pr.participant_code, "The only identifier. Appears in every export; never spoken aloud by the robot."],
      ["age, gender", `${pr.age}, ${pr.gender}`, "Sample description."],
      ["first_language", pr.first_language, "The main predictor of which transfer features appear. Gikuyu speakers and Dholuo speakers do not make the same substitutions."],
      ["other_languages, home_language", `${pr.other_languages}; ${pr.home_language}`, "Kenyan multilingualism is the norm; a two-language model of the speaker is wrong."],
      ["region_of_upbringing", pr.region_of_upbringing, "Dialect proxy."],
      ["english_onset_age, primary_medium_of_instruction", `${pr.english_onset_age}, ${pr.primary_medium_of_instruction}`, "Standard second-language covariates; both predict baseline accuracy."],
      ["self_rated_english", pr.self_rated_english, "CEFR self-rating. A covariate and a check that the sample is who the paper says."],
      ["voice_assistant_use", pr.voice_assistant_use, "Novelty control: someone who talks to a phone daily reacts differently to a talking robot."],
      ["hearing_or_speech_difficulty", String(pr.hearing_or_speech_difficulty), "Exclusion criterion."],
      ["consent_participation, consent_audio_retention, consent_date", `${pr.consent_participation}, ${pr.consent_audio_retention}, ${pr.consent_date}`, "The ethics trail. Audio retention consent decides whether a clip may ever be served to an external rater."],
    ], [2600, 1900, 4860]),
    gap(),
    P("Dropped on purpose: diagnosis date and therapy goals. They came from the clinical application this system grew out of, and a healthy volunteer's medical details are special-category data with no purpose behind them."),

    H1("10. The assignment and the sessions"),
    H2("10.1 study_assignments"),
    P(`P1 is in group ${d.assignment.group_index}: block 1 is ${d.assignment.block1}, block 2 is ${d.assignment.block2}. The row is written once, by the server, when the participant is assigned, and carries both conditions and both lists so that the plan screen and the analysis never have to recompute them. An excluded flag and reason keep a withdrawn or unusable participant in the table rather than deleting them, because the balance report must still count them.`),
    H2("10.2 therapy_sessions"),
    table(["Column", "Why"], [
      ["session_type", "training, pretest, posttest or delayed. The analysis selects assessments for learning and training blocks for feedback effects. A session that cannot be told apart afterwards is unusable for either."],
      ["condition, block_index", "K or D, and whether it was the first or second block. Stamped by the server from the assignment; the tablet cannot set them."],
      ["category_id", "Which list (A, B or the test set) was used, through its study_role."],
      ["item_order_seed", "The random order of items is reproducible from this one number."],
      ["start_time, end_time, is_completed, ended_early", "Session duration and whether it was finished. An unfinished session is analysed as such, not silently included."],
    ], [2800, 6560]),
    gap(),
    P("P1's four sessions:"),
    table(["Session", "Condition / list", "Minutes", "Items", "Attempts", "Spoken", "Tapped"], d.sessions.map((s) => [
      s.type, s.type === "training" ? `${s.condition} / ${s.list.replace("list_", "list ").toUpperCase()}` : "test set",
      String(s.minutes), String(s.items), String(s.attempts), String(s.spoken), String(s.tapped),
    ]), [1500, 1900, 1100, 1000, 1200, 1200, 1460]),
    gap(),
    P("The training sessions have more attempts than items because a wrong first attempt gets a second try. The assessments have exactly one attempt per item and no tapped items: assessment production is measured by recording only, so that every pre/post comparison is on the same kind of evidence."),

    H1("11. Attempts: the central table"),
    P("session_activities has one row per attempt, spoken or tapped. Its columns fall into six groups. The example beside each group is P1's pre-test attempt at \"hat\"."),
    H2("11.1 What was attempted"),
    table(["Column", "Example", "Why"], [
      ["session_id, item_id, attempt_number", "pretest, hat, 1", "The keys. Attempt number distinguishes the retry."],
      ["exercise_type", ex.exercise_type, "Copied from the item at the time, so editing an item later cannot rewrite history."],
      ["condition", "null (assessment)", "Copied from the session for the same reason."],
      ["selected_answer", "null", "For tapped items: the option or syllable chosen. Null for spoken items, whose answer is the recording."],
      ["skipped, skip_reason", "false", "A declined item. Excluded from error rates; storing a skip as an error would be a false rejection by the back door."],
    ], [2800, 1800, 4760]),
    H2("11.2 The verdict"),
    table(["Column", "Example", "Why"], [
      ["verdict", ex.verdict, "correct, close, incorrect, stress_error, gated, unscorable. The categorical outcome."],
      ["is_correct", "false", "The binary outcome the correction-rate hypothesis uses."],
      ["verdict_score", String(ex.verdict_score), "Mean of the two worst phone scores. The number the threshold is applied to."],
      ["pronunciation_score", String(ex.pronunciation_score), "Duration-weighted mean over all phones. The continuous outcome for the graded hypothesis."],
      ["confidence", String(ex.confidence), "How sure the recogniser was of its frames. Below the gate the attempt is gated and excluded, not marked wrong."],
      ["gated", "false", "The exclusion flag that keeps unclear recordings out of denominators."],
    ], [2800, 1800, 4760]),
    H2("11.3 The evidence behind the verdict"),
    table(["Column", "Example", "Why"], [
      ["expected_phones", ex.expected_phones.join(" "), "The dictionary variant that aligned best."],
      ["observed_phones", ex.observed_phones.join(" "), "What the free decode heard. Here AA for AE: the TRAP/PALM merger."],
      ["phone_scores", ex.phone_scores.map(([p, s]) => `${p} ${s}`).join(", "), "Per-phone calibrated scores with GOP, span and competitor. This is what a per-feature analysis is computed from."],
      ["diagnoses", ex.diagnoses.map((x) => `${x[1]} > ${x[2]} (${x[0]}, ${x[3]})`).join("; "), "Which phones were substituted, deleted or weak, with the score that corroborates it."],
      ["transcript, transcript_matches", `${ex.transcript}, ${ex.transcript_matches}`, "What the recogniser wrote and whether it contained the target. The rescue and the focus rule read these; the D feedback quotes it."],
      ["reference_source, reference_needs_review", "beep, false", "Where the target pronunciation came from. A g2p-predicted target is flagged for a human check."],
      ["applied_folds, stress_error, named_phone", "[], false, null", "Phone contrasts the model cannot represent; whether stress was judged wrong; which phone the robot named in D."],
    ], [2800, 2600, 3960]),
    H2("11.4 What the robot did"),
    table(["Column", "Example", "Why"], [
      ["feedback", `"${ex.feedback}"`, "The exact utterance. In an assessment it is always the fixed acknowledgement."],
      ["feedback_word_count", "7", "K and D utterances differ in length; the count lets the length confound be reported and modelled."],
      ["celebration_shown", "false", "Whether the robot was told to celebrate. Three pilot participants named the celebration as what gave them confidence."],
      ["prompt_replays, slow_replay_used", "0, false", "An item heard four times is a different trial from one heard once; the slow replay changes the stimulus itself."],
      ["feedback_helpful", "null", "A 1 to 5 tap, sampled after some corrections rather than every one."],
    ], [2800, 1800, 4760]),
    H2("11.5 Timing and recording quality"),
    table(["Column", "Example", "Why"], [
      ["prompt_ended_at, speech_started_at, speech_ended_at", "11:06:49.5, 11:06:50.8, 11:06:51.3", "Device-side instants. Response time is speech start minus prompt end, both measured on the tablet so wifi latency is not in it."],
      ["response_time_seconds", String(ex.response_time_seconds), "The derived latency. P1's K block has a mean of " + K.mean_response_s + " s because of one long pause between items; part 3 deals with outliers like it."],
      ["audio_peak, audio_rms_dbfs, audio_clipped_fraction, audio_quality", `${ex.audio_peak}, ${ex.audio_rms_dbfs} dB, 0, ${ex.audio_quality}`, "About the recording, not the speaker. Separates \"said it oddly\" from \"microphone was far away\". A batch on 15 September contained clucking and a bystander's conversation and nothing in the row said so."],
    ], [2800, 2200, 4360]),
    H2("11.6 Reproducibility"),
    table(["Column", "Example", "Why"], [
      ["audio_ref", "study_audio/<session>/<item>_attempt1.wav", "The recording. Re-scoring starts here."],
      ["pipeline_version, config_hash, model_id", `${ex.pipeline_version}, ${ex.config_hash}, wav2vec2-large-robust`, "Which rules judged this attempt. Two rows with the same hash were judged identically; a re-score under the same hash must reproduce the verdict."],
      ["stage_timings_ms", "lexicon 0, acoustic 240, ...", "Per-stage latency for the latency table in the instrument paper."],
    ], [2800, 2600, 3960]),

    H1("12. Items and lists"),
    P("Three categories carry a study role: list A, list B and the test set. Each has 21 items, three per target feature, and the two training lists are matched type for type so that list difficulty cannot masquerade as a condition effect."),
    table(["List", "Items", "Spoken", "Read aloud", "Minimal pair", "Stress / schwa taps", "Model audio"], ["list_a", "list_b", "test"].map((k) => {
      const i = d.inventory[k]; const t = i.by_type;
      return [i.name, String(i.items), String(t.repeat_word || 0), String(t.read_sentence || 0), String(t.minimal_pair_id || 0), String((t.stress_place || 0) + (t.schwa_spot || 0)), String(i.with_audio)];
    }), [2200, 900, 1000, 1200, 1300, 1700, 1060]),
    gap(),
    table(["Column", "Why"], [
      ["exercise_type", "repeat_word, read_sentence, minimal_pair_id, stress_place, schwa_spot and four others. Decides whether the microphone is used and how the answer is judged."],
      ["spec", "The typed content: the word, the carrier sentence and target word, the pair and its answer, the syllables and the stressed index. Validated on entry; frozen once attempts exist."],
      ["target_feature", "One of the seven Kenyan English transfer features. Every per-feature number and the focus-phone rule depend on it."],
      ["match_key", "Pairs an item in list A with its counterpart in list B, so the lists can be checked for balance."],
      ["audio_url", "The stored model recording. Required for a minimal-pair item, which has nothing to play otherwise."],
    ], [2400, 6960]),

    H1("13. Questionnaires and notes"),
    P("After each training block the tablet asks eighteen seven-point items in three scales: Godspeed (likeability and competence of the robot, six items), intrinsic motivation (seven items, two reversed), and trust in the feedback (five items, one reversed). Reversed items are scored as 8 minus the answer; the tablet does not reveal which they are. The row stores the raw answers, the scale means, the instrument version, and how long the questionnaire took."),
    table(["Block", "Condition", "Godspeed", "Motivation", "Feedback trust", "Seconds"], d.questionnaires.sort((a, b) => a.block - b.block).map((q) => [
      String(q.block), q.condition, String(q.scores.godspeed), String(q.scores.motivation), String(q.scores.feedback_trust), String(q.duration_seconds),
    ]), [1200, 1400, 1600, 1700, 1900, 1560]),
    gap(),
    P("P1's answers were entered in sequence (7, 6, 5, ... then 1, 2, 3, ...) in under thirty seconds, which is what a tap-through looks like. The duration column exists so that such a questionnaire can be excluded by rule rather than by judgement."),
    P("Session notes are the researcher's record of anything that could explain an odd session: an interruption, a noisy room, an equipment problem, an unwell participant, instructions given in another language, and a recommendation to exclude. None were filed for P1."),

    H1("14. Ratings"),
    P("The pipeline's verdict is not the ground truth; a listener's judgement is. The rating tables hold that judgement, made blind. A rating set lists which clips are to be judged, in strata (session type, condition, feature) so that the sample covers the design, with a tenth repeated to measure each rater's consistency with themselves. A rating holds one person's verdict on one clip: correct or not, a 1 to 5 accuracy, the sound heard wrong, or unusable, plus how long they took. From these come the false-correction rate (how often the robot corrected something said right) and the inter-rater kappa. Nothing has been rated yet."),

    H1("15. The worked example, read across"),
    P("What P1's four sessions look like when the columns above are summarised. These are pipeline verdicts, unrated, from a run where some errors were made on purpose."),
    table(["", "Pre-test", "D block (list B)", "K block (list A)", "Post-test"], [
      ["Spoken attempts", String(pre.spoken), String(D.spoken), String(K.spoken), String(post.spoken)],
      ["First attempts correct", `${pre.first_attempt_correct} / ${pre.first_attempts}`, `${D.first_attempt_correct} / ${D.first_attempts}`, `${K.first_attempt_correct} / ${K.first_attempts}`, `${post.first_attempt_correct} / ${post.first_attempts}`],
      ["Verdicts correct / close / incorrect", `${v(pre, "correct")} / ${v(pre, "close")} / ${v(pre, "incorrect")}`, `${v(D, "correct")} / ${v(D, "close")} / ${v(D, "incorrect")}`, `${v(K, "correct")} / ${v(K, "close")} / ${v(K, "incorrect")}`, `${v(post, "correct")} / ${v(post, "close")} / ${v(post, "incorrect")}`],
      ["Retries taken", "none offered", String(D.retries), String(K.retries), "none offered"],
      ["Tapped items correct", "-", `${D.tapped_correct} / ${D.tapped}`, `${K.tapped_correct} / ${K.tapped}`, "-"],
      ["Mean graded score", String(pre.mean_graded_score), String(D.mean_graded_score), String(K.mean_graded_score), String(post.mean_graded_score)],
      ["Mean feedback length (words)", String(pre.mean_feedback_words), String(D.mean_feedback_words), String(K.mean_feedback_words), String(post.mean_feedback_words)],
      ["Prompt replays", String(pre.replays), String(D.replays), String(K.replays), String(post.replays)],
      ["Gated or skipped", `${pre.gated} / ${pre.skipped}`, `${D.gated} / ${D.skipped}`, `${K.gated} / ${K.skipped}`, `${post.gated} / ${post.skipped}`],
    ], [2600, 1600, 1800, 1800, 1560]),
    gap(),
    P("Two things to read off this before any analysis. The D utterances average about twice the length of the K utterances, which is the confound the length-matching filler exists to reduce and which must be reported. And the per-feature view below is where the learning question actually lives; the totals above hide it."),
    table(["Target feature", "Pre-test correct", "Post-test correct"], Object.keys(FEAT_LABEL).map((k) => [
      FEAT_LABEL[k], feat[k] ? `${feat[k].pretest[0]} / ${feat[k].pretest[1]}` : "-", feat[k] ? `${feat[k].posttest[0]} / ${feat[k].posttest[1]}` : "-",
    ]), [3600, 2800, 2960]),
    gap(),
    P("The tapped /r/ row moves from 0 of 3 to 2 of 3. Part 1 explained why that is not yet evidence of learning: the model scores a Kenyan tapped R between R and L, and three of those verdicts were disagreements between the acoustic model and the recogniser. Part 3 shows how the analysis is set up so that a feature the instrument measures badly cannot carry a result on its own, and part 4 what the rated clips must show before the row above means anything."),
  ];
};
