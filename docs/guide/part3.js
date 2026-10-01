// Part 3 of the system guide: how the data will be analysed, demonstrated.
const fs = require("fs");
const path = require("path");

module.exports = function part3(h) {
  const { P, H1, H2, B, C, bullet, table, gap, TextRun, Paragraph, PageBreak } = h;
  // Own numbering, so the list restarts at 1 rather than continuing part 1's.
  const step = (runs) => new Paragraph({ numbering: { reference: "steps3", level: 0 }, spacing: { after: 80 }, children: typeof runs === "string" ? [new TextRun(runs)] : runs });
  const here = __dirname;
  const real = JSON.parse(fs.readFileSync(path.join(here, "part3_real.json"), "utf8"));
  const sim = JSON.parse(fs.readFileSync(path.join(here, "part3_sim.json"), "utf8"));
  let power = null;
  try { power = JSON.parse(fs.readFileSync(path.join(here, "part3_power.json"), "utf8")).power; } catch { /* not run yet */ }
  const FEAT_LABEL = { trap_palm_strut: "TRAP / PALM / STRUT", kit_fleece: "KIT / FLEECE", foot_goose: "FOOT / GOOSE", schwa_reduction: "Schwa and reduction", dental_fricative: "Dental fricatives", polysyllabic_stress: "Polysyllabic stress", rhotic_lateral: "Tapped /r/" };
  const pct = (v) => (v === null || v === undefined ? "-" : `${v}%`);
  const fx = (m, term) => {
    const e = (m.fixed_effects || {})[term];
    if (!e) return "-";
    const or = m.odds_ratios && m.odds_ratios[term] !== undefined ? `, OR ${m.odds_ratios[term]}` : "";
    const p = m.p_values && m.p_values[term] !== undefined && isFinite(m.p_values[term]) ? `, p = ${m.p_values[term]}` : "";
    return `${e[0] >= 0 ? "+" : ""}${e[0]} (se ${e[1]})${or}${p}`;
  };
  const modelRows = (res, terms) => res.models.map((m) => [m.label, m.fit || "-", String(m.n ?? "-"), ...terms.map((t) => fx(m, t))]);
  const trainingTable = (r) => table(["", "K", "D"], [
    ["First-attempt accuracy", `${r.training.K.first_correct} / ${r.training.K.first_attempts} (${pct(r.training.K.first_accuracy_pct)})`, `${r.training.D.first_correct} / ${r.training.D.first_attempts} (${pct(r.training.D.first_accuracy_pct)})`],
    ["Uptake after a correction", `${r.training.K.uptake} / ${r.training.K.second_attempts} (${pct(r.training.K.uptake_pct)})`, `${r.training.D.uptake} / ${r.training.D.second_attempts} (${pct(r.training.D.uptake_pct)})`],
    ["Mean graded score, first attempts", String(r.training.K.graded_mean), String(r.training.D.graded_mean)],
    ["Median response time (s)", String(r.training.K.response_time_median_s), String(r.training.D.response_time_median_s)],
    ["Mean feedback length (words)", String(r.training.K.feedback_words_mean), String(r.training.D.feedback_words_mean)],
    ["Feedback trust (1-7)", String(r.questionnaires.feedback_trust?.K?.mean ?? "-"), String(r.questionnaires.feedback_trust?.D?.mean ?? "-")],
    ["Godspeed (1-7)", String(r.questionnaires.godspeed?.K?.mean ?? "-"), String(r.questionnaires.godspeed?.D?.mean ?? "-")],
    ["Motivation (1-7)", String(r.questionnaires.motivation?.K?.mean ?? "-"), String(r.questionnaires.motivation?.D?.mean ?? "-")],
  ], [3600, 2880, 2880]);
  const learningTable = (r) => {
    const phases = Object.keys(r.learning.overall);
    return table(["", ...phases.map((p) => ({ pretest: "Pre-test", posttest: "Post-test", delayed: "Delayed" }[p]))], [
      ["Accuracy", ...phases.map((p) => `${r.learning.overall[p].correct} / ${r.learning.overall[p].n} (${pct(r.learning.overall[p].accuracy_pct)})`)],
      ["Mean graded score", ...phases.map((p) => String(r.learning.overall[p].graded_mean))],
      ...Object.keys(FEAT_LABEL).filter((f) => r.learning.by_feature[f]).map((f) => [FEAT_LABEL[f], ...phases.map((p) => r.learning.by_feature[f][p] || "-")]),
    ], [3600, ...phases.map(() => Math.floor(5760 / phases.length))]);
  };

  return [
    new Paragraph({ children: [new PageBreak()] }),
    new Paragraph({ spacing: { before: 1200, after: 120 }, children: [new TextRun({ text: "Part 3", bold: true, size: 48, color: "1F3A5F" })] }),
    new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "How the data will be analysed, demonstrated on what is in the database", size: 30, color: "555555" })] }),
    P("This part is written as the analysis plan: the questions, the units and denominators, the confounds and what handles each, the models, the effect sizes and power, and then the whole thing run twice. Once on P1's real export, where one participant means most models cannot be fitted and the script says so, and once on a simulated 40-participant study built from the real design and stated assumptions, so that the full models and their output can be seen before any participant is recruited. Everything is produced by two scripts, named at the end, so the tables regenerate when the data do."),

    H1("16. The questions"),
    P("The study asks whether diagnostic feedback (D) does anything that re-modelling alone (K) does not. The feedback acts on the attempt that follows it, so the primary contrast is on what happens after a correction, not on the first attempt, which precedes any feedback for that item."),
    table(["", "Question", "Outcome", "Prediction"], [
      ["H1", "Does a diagnostic correction lead to a successful second attempt more often than a re-model?", "Uptake: second attempt correct, given a wrong first attempt, in training", "D > K"],
      ["H2", "Does the condition change the graded quality of productions during training?", "Graded score on first attempts", "No difference expected; reported"],
      ["H3", "Do participants pronounce the untrained test words better after training, and does it last?", "Assessment accuracy and graded score at pre-test, post-test, delayed test", "Post > pre; delayed between them"],
      ["H4", "Do participants trust diagnostic feedback more?", "Feedback-trust scale after each block", "D > K"],
      ["H5", "Does the condition change how the robot is perceived or how motivating the session is?", "Godspeed and motivation scales", "Exploratory"],
      ["I1", "Is the instrument good enough to carry H1 to H3?", "False-correction rate, inter-rater kappa, pipeline-versus-rater agreement", "False corrections under 10% of items said right; kappa at least moderate"],
    ], [700, 3900, 3300, 1460]),
    gap(),
    P("I1 is listed with the hypotheses because it is answered first and gates the rest. A false-correction rate that is high, or concentrated in one feature, changes what H1 means: an uptake difference on a feature the scorer cannot judge is a difference in how the two conditions handle the scorer's mistakes."),

    H1("17. Units, outcomes and denominators"),
    bullet([B("The unit is the attempt. "), new TextRun("Participants and items are crossed random effects, which is what stops one talkative participant or one hard word from carrying a result. This is the direct answer to the reviewer who objected to unequal item-level Ns and a paired t-test.")]),
    bullet([B("Training outcomes use first attempts "), new TextRun("for accuracy and the graded score, and second attempts for uptake. A second attempt exists only after a correction, so uptake's denominator is the number of corrections, not of items.")]),
    bullet([B("Learning outcomes use the single assessment attempt "), new TextRun("per item per phase. Assessments never offer a retry.")]),
    bullet([B("Gated and skipped attempts are excluded from every denominator. "), new TextRun("A gated attempt is a recording the recogniser could not judge; a skip is a decision not to answer. Both are reported as rates of their own, by condition, because a condition that produces more skips is itself a finding.")]),
    bullet([B("Response time "), new TextRun("is prompt end to speech onset, both on the tablet. It is analysed on the log scale, and intervals over 20 seconds are treated as off-task and set aside, with the count reported. P1's K block holds one such interval (a pause of several minutes between two items), which is why its median, not its mean, appears below.")]),
    bullet([B("Questionnaires "), new TextRun("are excluded by rule when completed in under 60 seconds or when the answers form a monotone run across a whole scale, which is what a tap-through looks like. P1's two questionnaires fail both tests and are shown here only to demonstrate the shape.")]),
    bullet([B("Tapped items "), new TextRun("(minimal pair, stress, schwa) are analysed as perception accuracy by condition, separately from production, and are not pooled with spoken attempts.")]),

    H1("18. Confounds, and what handles each"),
    table(["Confound", "Handled by", "What still has to be reported"], [
      ["Order and fatigue: block 2 follows block 1", "The 2 x 2 counterbalance; block enters every training model as a covariate", "The block effect itself, which is also the within-session learning estimate"],
      ["List difficulty: A and B are not identical words", "Lists matched item for item by type and feature (match_key); each list appears under each condition across groups", "Per-list accuracy, so a mismatch can be seen"],
      ["Utterance length: D says about twice as much as K", "Length-matching filler in K (on by default); feedback_words stored per attempt", "The mean length per condition, and a sensitivity model with feedback_words as a covariate"],
      ["Instrument error: the scorer is wrong sometimes, and not evenly across features", "Blind human ratings on a stratified sample; the audit's false-rejection and false-acceptance rates per feature", "H1 and H3 re-estimated on the rated subsample with the human label as the outcome; features the audit fails are reported, not pooled"],
      ["Item memory: the same test words at pre, post and delayed", "Assessment silence (no feedback, no scores shown); the item order re-drawn from a new seed each time", "The pre-test score as a covariate in the delayed model"],
      ["Experimenter presence and robot novelty", "voice_assistant_use covariate; the session notes flags", "Sessions with notes flagged, and a model with and without them"],
    ], [2600, 3400, 3360]),
    gap(),
    P([B("One confound the current design does not resolve, and a decision for you. "), new TextRun("The assessments present only the test set, and every target feature is trained under both conditions (three items per feature in list A under one condition and three in list B under the other). So a gain from pre-test to post-test is evidence of learning, but it cannot be attributed to K or to D: both conditions trained every feature. The condition contrast therefore rests on H1, H2 and H4, which are measured inside the training blocks. If the paper needs \"retention by condition\", the post-test and delayed test must also assess the trained words themselves, silently, tagged by the list they came from. The system can do that with one change to how an assessment session resolves its items, at the cost of 14 more spoken items per assessment (about five minutes). I have not made that change; it alters the protocol.")]),

    H1("19. The models"),
    P("All models have participant and item as crossed random intercepts. Binary outcomes use a mixed logistic regression and are reported as odds ratios; continuous outcomes use a linear mixed model. In R these are lme4::glmer and lmer; the scripts here use statsmodels, whose Bayesian mixed GLM gives the same fixed effects to within sampling error. The exported CSVs load directly into either."),
    table(["Model", "Outcome and data", "Formula", "The term that answers the question"], [
      ["M1", "First attempt correct, training", "correct ~ D + block2 + (1|participant) + (1|item)", "D: expected near 1.0 (odds ratio); block2 is within-session learning"],
      ["M2", "Second attempt correct, given a correction", "correct ~ D + (1|participant) + (1|item)", "D: the uptake effect, H1"],
      ["M3", "Graded score, first attempts", "graded_score ~ D + block2 + (1|participant) + (1|item)", "D: H2"],
      ["M4", "Assessment attempt correct", "correct ~ post + delayed + (1|participant) + (1|item)", "post and delayed: H3; the delayed model also takes the pre-test score as a covariate"],
      ["M5", "Scale mean per block", "scale ~ D + block2 + (1|participant)", "D on feedback_trust: H4; on godspeed and motivation: H5"],
      ["M6", "Per-feature versions of M2 and M4", "the same, with feature as a factor and its interaction with D or phase", "Which contrasts the effect lives in; read together with the audit"],
      ["M7", "Sensitivity: human label as the outcome", "M2 and M4 on the rated subsample, outcome = rater majority", "Whether the pipeline's verdicts and the raters' tell the same story"],
    ], [700, 2600, 3500, 2560]),

    H1("20. Effect sizes and power"),
    P("Odds ratios are the effect size for the binary outcomes; for the continuous ones, the fixed effect divided by the residual standard deviation gives a d. Plonsky and Oswald's benchmarks for second-language research are used rather than Cohen's: for within-group contrasts d of 0.60 is small, 1.00 medium and 1.40 large; for between-group contrasts 0.40, 0.70 and 1.00. An uptake odds ratio of 2 at a baseline of 45% corresponds to about 17 percentage points, roughly d = 0.4 on the latent scale, which is a small effect by these standards and the one the simulation below assumes."),
    power ? P(`Power was estimated by simulating the design ${power.reps} times at ${power.n_participants} participants under the assumptions in section 21 and fitting population-average models to each. The share of simulated studies that detected each effect at p < .05: uptake (H1) ${power.power_pct.uptake}%, post-test gain (H3) ${power.power_pct.post_gain}%, and the first-attempt accuracy difference, which is simulated as absent, ${power.power_pct.first_accuracy}% (the false-positive rate, which should sit near 5%).`)
      : P("Power by simulation: run scripts/analysis/analyse.py --power 40 --reps 200; the result is written into this section when the document is rebuilt."),
    P("What this says about recruitment: the uptake contrast is well powered at 40 because every participant contributes to both sides of it, and each wrong first attempt is an observation. The learning contrast is powered by the 21 test items times three phases per participant. The per-feature versions (M6) are not powered at 40 to detect anything but large effects, and should be presented as descriptive."),

    H1("21. The analysis run on the data"),
    H2("21.1 P1's real export"),
    P(`${real.participants} participant, ${real.attempts} attempts. Mean feedback length was ${real.instrument.utterance_length_words.K} words in K and ${real.instrument.utterance_length_words.D} in D; nothing was gated or skipped. No clips have been rated, so the false-correction rate and kappa are blank.`),
    trainingTable(real),
    gap(),
    learningTable(real),
    gap(),
    P("With one participant the models reduce to fixed effects, and condition and block are the same variable (P1 had D first, K second), so M1 and M3 cannot separate them. The script reports this rather than a number:"),
    table(["Model", "Fit", "n", "D", "block2 / post"], real.models.filter((m) => !m.label.startsWith("M5")).map((m) => [m.label, m.fit || "-", String(m.n ?? "-"), fx(m, "D"), m.fixed_effects && m.fixed_effects.post ? fx(m, "post") : fx(m, "block2")]), [3000, 1800, 600, 2000, 1960]),
    gap(),
    P("The one estimable thing is M4, pre-test to post-test on the test words: 12 of 21 to 13 of 21, odds ratio 1.22, p = 0.75. That is the correct reading of a single participant's run: no evidence either way. The per-feature rows in the learning table show why the overall number hides the question, and the tapped /r/ row shows why the audit comes first."),

    H2("21.2 A simulated 40-participant study"),
    P("The same scripts on a synthetic study with the real design (four groups, two lists of 14 spoken items, 21 test words, three assessment phases) and these assumptions: baseline first-attempt accuracy 65%; no condition effect on first attempts; uptake 45% under K with an odds ratio of 2.0 under D; a post-test gain of odds ratio 1.6 and a delayed gain of 1.3; feedback trust 0.4 points higher under D; participant intercepts with sd 0.8 and item intercepts with sd 0.5 on the logit scale. None of these are results; they are the numbers a reader can change in the script."),
    trainingTable(sim),
    gap(),
    learningTable(sim),
    gap(),
    table(["Model", "Fit", "n", "D", "block2 / post", "delayed"], sim.models.map((m) => [m.label, m.fit || "-", String(m.n ?? "-"), fx(m, "D"), m.fixed_effects && m.fixed_effects.post ? fx(m, "post") : fx(m, "block2"), fx(m, "delayed")]), [2600, 1700, 500, 1800, 1700, 1060]),
    gap(),
    P("Reading it: M2 recovers the assumed uptake effect (odds ratio about 1.9 against the assumed 2.0), M1 and M3 show the absence that was simulated, M4 recovers the post-test and delayed gains, and M5 finds the trust difference and nothing on the other two scales. This is what the tables in the paper will look like, with the real numbers in place of these, and the audit's false-correction rates beside them."),

    H1("22. Reproducing every number"),
    step([C("python scripts/analysis/export_analysis.py"), new TextRun(" writes participants.csv, sessions.csv, attempts.csv and questionnaires.csv to analysis/. Participant codes are the only identifier.")]),
    step([C("python scripts/analysis/analyse.py"), new TextRun(" runs sections 17 to 19 on the export and prints them; "), C("--json"), new TextRun(" writes the tables this document is built from.")]),
    step([C("python scripts/analysis/analyse.py --simulate 40"), new TextRun(" runs the same on a synthetic study; "), C("--power 40 --reps 200"), new TextRun(" estimates power.")]),
    step([C("python scripts/rescore_sessions.py --since <date>"), new TextRun(" confirms that the stored verdicts are what the current pipeline produces from the stored audio, before any export is trusted.")]),
    step([new TextRun("The ratings export on the console's Rating page supplies the human labels for I1 and M7.")]),
    P("Part 4 covers what each outcome would mean, the claims each pattern of results supports, and the limits that stay whatever the numbers say."),
  ];
};
