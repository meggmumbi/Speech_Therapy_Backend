"""The planned analysis, run on the exported CSVs or on a simulated study.

    python scripts/analysis/analyse.py                      # analysis/*.csv
    python scripts/analysis/analyse.py --simulate 40        # a synthetic study
    python scripts/analysis/analyse.py --power 40 --reps 200
    python scripts/analysis/analyse.py --json out.json      # tables for the guide

What is computed, and in what order, is the pre-specified plan:

  1. Instrument checks that must pass before any outcome is read: the
     false-correction rate from the rated clips, inter-rater agreement, and
     the K/D utterance-length confound.
  2. Training outcomes, K against D within participant: first-attempt
     accuracy, uptake (a correct second attempt after a correction), graded
     score, response time, and the questionnaire scales.
  3. Learning: assessment accuracy and graded score at pre-test, post-test
     and delayed test, overall and per target feature.
  4. Models: mixed-effects regressions with participant and item as random
     effects (binomial for correct/uptake, linear for scores and scales).
     With fewer than three participants the random effects are not
     estimable, and the script fits the fixed-effects form and says so.

Denominators follow the dashboard: gated and skipped attempts are excluded,
training outcomes use first attempts, learning uses the single assessment
attempt. Nothing here reads the database; it reads the export, so the same
tables can be re-derived from the CSVs alone.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

FEATURES = ("trap_palm_strut", "kit_fleece", "foot_goose", "schwa_reduction",
            "dental_fricative", "polysyllabic_stress", "rhotic_lateral")


# --- loading ------------------------------------------------------------------

def load(directory: str) -> dict[str, pd.DataFrame]:
    d = Path(directory)
    frames = {name: pd.read_csv(d / f"{name}.csv") for name in ("participants", "sessions", "attempts", "questionnaires")}
    a = frames["attempts"]
    for col in ("spoken", "is_first", "is_final", "gated", "skipped", "slow_replay", "celebration"):
        a[col] = a[col].astype(str).str.lower().eq("true")
    a["correct"] = a["correct"].map({"True": 1.0, "False": 0.0, True: 1.0, False: 0.0})
    return frames


# --- simulation ---------------------------------------------------------------

def simulate(n_participants: int, seed: int = 2026, effects: dict | None = None) -> dict[str, pd.DataFrame]:
    """A synthetic study with the real design and stated assumptions.

    Participant and item intercepts are drawn once and reused across
    sessions, which is what makes the within-subject comparison stronger
    than a between-groups one. The effect sizes are assumptions, written
    here so that a reader can change them.
    """
    e = {"base_first": 0.65, "d_first_or": 1.0, "base_uptake": 0.45, "d_uptake_or": 2.0,
         "post_gain_or": 1.6, "delayed_gain_or": 1.3, "sd_participant": 0.8, "sd_item": 0.5,
         "trust_d": 0.4, "sd_scale": 0.9}
    e.update(effects or {})
    rng = np.random.default_rng(seed)
    logit = lambda p: math.log(p / (1 - p))
    inv = lambda x: 1 / (1 + np.exp(-x))
    groups = [(("K", "A"), ("D", "B")), (("K", "B"), ("D", "A")), (("D", "A"), ("K", "B")), (("D", "B"), ("K", "A"))]
    items = {lst: [f"{lst}{i:02d}" for i in range(14)] for lst in ("A", "B", "T")}   # 14 spoken per list, 14 test... 21 in reality
    items["T"] = [f"T{i:02d}" for i in range(21)]
    feat_of = {it: FEATURES[k % 7] for lst in items for k, it in enumerate(items[lst])}
    u_item = {it: rng.normal(0, e["sd_item"]) for lst in items for it in items[lst]}
    rows, qrows, prow = [], [], []
    for p in range(n_participants):
        code = f"S{p + 1:02d}"
        g = p % 4
        u_p = rng.normal(0, e["sd_participant"])
        u_learn = rng.normal(0, 0.4)
        prow.append({"participant": code, "group": g})
        for block, (cond, lst) in enumerate(groups[g], start=1):
            for it in items[lst]:
                eta = logit(e["base_first"]) + u_p + u_item[it] + (math.log(e["d_first_or"]) if cond == "D" else 0)
                c1 = rng.random() < inv(eta)
                rows.append(dict(participant=code, session_type="training", condition=cond, block=block, list=lst,
                                 item=it, target_feature=feat_of[it], spoken=True, attempt_number=1, is_first=True,
                                 is_final=c1, correct=float(c1), graded_score=float(np.clip(inv(eta) + rng.normal(0, 0.12), 0, 1)),
                                 response_time_s=float(np.exp(rng.normal(0.6, 0.4))), feedback_words=7 if cond == "K" else 14,
                                 gated=False, skipped=False))
                if not c1:
                    eta2 = logit(e["base_uptake"]) + u_p + u_item[it] + (math.log(e["d_uptake_or"]) if cond == "D" else 0)
                    c2 = rng.random() < inv(eta2)
                    rows.append(dict(participant=code, session_type="training", condition=cond, block=block, list=lst,
                                     item=it, target_feature=feat_of[it], spoken=True, attempt_number=2, is_first=False,
                                     is_final=True, correct=float(c2), graded_score=float(np.clip(inv(eta2) + rng.normal(0, 0.12), 0, 1)),
                                     response_time_s=float(np.exp(rng.normal(0.6, 0.4))), feedback_words=7 if cond == "K" else 14,
                                     gated=False, skipped=False))
            qrows.append(dict(participant=code, condition=cond, block=block,
                              godspeed=float(np.clip(4.5 + rng.normal(0, e["sd_scale"]), 1, 7)),
                              motivation=float(np.clip(4.8 + rng.normal(0, e["sd_scale"]), 1, 7)),
                              feedback_trust=float(np.clip(4.3 + (e["trust_d"] if cond == "D" else 0) + rng.normal(0, e["sd_scale"]), 1, 7)),
                              duration_seconds=int(rng.normal(150, 30))))
        for phase, gain in (("pretest", 0.0), ("posttest", math.log(e["post_gain_or"])), ("delayed", math.log(e["delayed_gain_or"]))):
            for it in items["T"]:
                eta = logit(e["base_first"]) + u_p + u_item[it] + gain * (1 + u_learn)
                c = rng.random() < inv(eta)
                rows.append(dict(participant=code, session_type=phase, condition=None, block=None, list="T", item=it,
                                 target_feature=feat_of[it], spoken=True, attempt_number=1, is_first=True, is_final=True,
                                 correct=float(c), graded_score=float(np.clip(inv(eta) + rng.normal(0, 0.12), 0, 1)),
                                 response_time_s=float(np.exp(rng.normal(0.6, 0.4))), feedback_words=7, gated=False, skipped=False))
    a = pd.DataFrame(rows)
    a["attempt"] = range(len(a))
    return {"participants": pd.DataFrame(prow), "attempts": a, "questionnaires": pd.DataFrame(qrows),
            "sessions": pd.DataFrame(), "assumptions": e}


# --- the outcomes ---------------------------------------------------------------

def _rate(num: float, den: float) -> float | None:
    return round(100 * num / den, 1) if den else None


def training_outcomes(a: pd.DataFrame) -> dict:
    t = a[(a.session_type == "training") & a.spoken & ~a.gated & ~a.skipped]
    first = t[t.is_first]
    out = {}
    for cond in ("K", "D"):
        f = first[first.condition == cond]
        n_wrong = int((f.correct == 0).sum())
        # Uptake: among items whose first attempt was wrong, was the second right?
        second = t[(t.condition == cond) & (t.attempt_number == 2)]
        out[cond] = {
            "first_attempts": int(len(f)), "first_correct": int(f.correct.sum()),
            "first_accuracy_pct": _rate(f.correct.sum(), len(f)),
            "corrections": n_wrong, "second_attempts": int(len(second)),
            "uptake": int(second.correct.sum()), "uptake_pct": _rate(second.correct.sum(), len(second)),
            "graded_mean": round(float(f.graded_score.mean()), 3) if len(f) else None,
            "response_time_median_s": round(float(f.response_time_s.median()), 2) if len(f) else None,
            "feedback_words_mean": round(float(t[t.condition == cond].feedback_words.mean()), 1) if len(t) else None,
        }
    return out


def learning_outcomes(a: pd.DataFrame) -> dict:
    s = a[a.session_type.isin(["pretest", "posttest", "delayed"]) & a.spoken & ~a.gated & ~a.skipped & a.is_first]
    out = {"overall": {}, "by_feature": {}}
    for phase in ("pretest", "posttest", "delayed"):
        x = s[s.session_type == phase]
        if len(x):
            out["overall"][phase] = {"n": int(len(x)), "correct": int(x.correct.sum()),
                                     "accuracy_pct": _rate(x.correct.sum(), len(x)),
                                     "graded_mean": round(float(x.graded_score.mean()), 3)}
    for f in FEATURES:
        row = {}
        for phase in ("pretest", "posttest", "delayed"):
            x = s[(s.session_type == phase) & (s.target_feature == f)]
            if len(x):
                row[phase] = f"{int(x.correct.sum())} / {len(x)}"
        if row:
            out["by_feature"][f] = row
    return out


def questionnaire_outcomes(q: pd.DataFrame) -> dict:
    out = {}
    if q.empty:
        return out
    for scale in ("godspeed", "motivation", "feedback_trust"):
        by = q.groupby("condition")[scale].agg(["mean", "std", "count"])
        out[scale] = {c: {"mean": round(float(r["mean"]), 2), "sd": None if np.isnan(r["std"]) else round(float(r["std"]), 2),
                          "n": int(r["count"])} for c, r in by.iterrows()}
    return out


# --- the models -----------------------------------------------------------------

def _fit_binomial(df: pd.DataFrame, formula: str, label: str, n_participants: int) -> dict:
    import statsmodels.formula.api as smf
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    df = df.dropna(subset=["correct"]).copy()
    if df.empty or df.correct.nunique() < 2:
        return {"label": label, "note": "no variation in the outcome; nothing to fit"}
    if n_participants >= 3 and df.item.nunique() >= 3:
        try:
            vc = {"participant": "0 + C(participant)", "item": "0 + C(item)"}
            m = BinomialBayesMixedGLM.from_formula(formula, vc, df).fit_vb()
            names = list(m.model.exog_names)
            est = {n: (round(float(b), 3), round(float(s), 3)) for n, b, s in zip(names, m.fe_mean, m.fe_sd)}
            return {"label": label, "formula": formula + " + (1|participant) + (1|item)", "fit": "Bayesian mixed GLM (variational)",
                    "n": int(len(df)), "fixed_effects": est,
                    "odds_ratios": {n: round(math.exp(b), 2) for n, (b, _) in est.items() if n != "Intercept"},
                    "random_sd": {n: round(float(math.exp(v)), 2) for n, v in zip(m.model.vcp_names, m.vcp_mean)}}
        except Exception as exc:  # noqa: BLE001
            note = f"mixed fit failed ({exc}); fixed-effects form below"
    else:
        note = f"only {n_participants} participant(s): random effects not estimable; fixed-effects form"
    try:
        m = smf.logit(formula, df).fit(disp=0)
        if float(np.max(m.bse)) > 50:
            # Every observation on one side for some cell: the estimate runs
            # off to infinity and the standard error with it.
            return {"label": label, "formula": formula, "fit": "logistic regression", "n": int(len(df)),
                    "note": note + "; complete separation in the data, so the coefficients are not estimable"}
        est = {n: (round(float(b), 3), round(float(s), 3)) for n, b, s in zip(m.params.index, m.params, m.bse)}
        return {"label": label, "formula": formula, "fit": "logistic regression", "note": note, "n": int(len(df)),
                "fixed_effects": est, "odds_ratios": {n: round(math.exp(b), 2) for n, (b, _) in est.items() if n != "Intercept"},
                "p_values": {n: round(float(p), 3) for n, p in m.pvalues.items()}}
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "note": f"could not fit: {exc}"}


def _fit_linear(df: pd.DataFrame, formula: str, outcome: str, label: str, n_participants: int) -> dict:
    import statsmodels.formula.api as smf
    df = df.dropna(subset=[outcome]).copy()
    if df.empty:
        return {"label": label, "note": "no data"}
    if n_participants >= 3:
        try:
            kwargs = {"groups": df["participant"], "re_formula": "1"}
            if "item" in df and df.item.nunique() >= 3:
                kwargs["vc_formula"] = {"item": "0 + C(item)"}
            m = smf.mixedlm(formula, df, **kwargs).fit(reml=True)
            est = {n: (round(float(b), 3), round(float(s), 3)) for n, b, s in zip(m.params.index, m.params, m.bse) if "Var" not in n and "Cov" not in n}
            return {"label": label, "formula": formula + " + (1|participant)" + (" + (1|item)" if "item" in df else ""),
                    "fit": "linear mixed model (REML)", "n": int(len(df)), "fixed_effects": est,
                    "p_values": {n: round(float(p), 3) for n, p in m.pvalues.items() if n in est}}
        except Exception as exc:  # noqa: BLE001
            note = f"mixed fit failed ({exc}); OLS below"
    else:
        note = f"only {n_participants} participant(s): random effects not estimable; OLS"
    m = smf.ols(formula, df).fit()
    est = {n: (round(float(b), 3), round(float(s), 3)) for n, b, s in zip(m.params.index, m.params, m.bse)}
    return {"label": label, "formula": formula, "fit": "OLS", "note": note, "n": int(len(df)), "fixed_effects": est,
            "p_values": {n: round(float(p), 3) for n, p in m.pvalues.items()}}


def models(frames: dict[str, pd.DataFrame]) -> list[dict]:
    a, q = frames["attempts"], frames["questionnaires"]
    n_p = a.participant.nunique()
    t = a[(a.session_type == "training") & a.spoken & ~a.gated & ~a.skipped].copy()
    first = t[t.is_first].copy()
    first["D"] = (first.condition == "D").astype(int)
    first["block2"] = (first.block == 2).astype(int)
    second = t[t.attempt_number == 2].copy()
    second["D"] = (second.condition == "D").astype(int)
    s = a[a.session_type.isin(["pretest", "posttest", "delayed"]) & a.spoken & ~a.gated & ~a.skipped & a.is_first].copy()
    s["post"] = (s.session_type == "posttest").astype(int)
    s["delayed"] = (s.session_type == "delayed").astype(int)
    out = [
        _fit_binomial(first, "correct ~ D + block2", "M1 first-attempt accuracy, K vs D", n_p),
        _fit_binomial(second, "correct ~ D", "M2 uptake after a correction, K vs D", n_p),
        _fit_linear(first, "graded_score ~ D + block2", "graded_score", "M3 graded score, K vs D", n_p),
        _fit_binomial(s, "correct ~ post + delayed" if s.delayed.any() else "correct ~ post", "M4 assessment accuracy over time", n_p),
    ]
    if not q.empty:
        qq = q.copy()
        qq["D"] = (qq.condition == "D").astype(int)
        qq["block2"] = (qq.block == 2).astype(int)
        for scale in ("feedback_trust", "godspeed", "motivation"):
            out.append(_fit_linear(qq, f"{scale} ~ D + block2", scale, f"M5 {scale}, K vs D", n_p))
    return out


# --- power by simulation ------------------------------------------------------------

def power(n_participants: int, reps: int, seed: int, effects: dict | None = None) -> dict:
    """Share of simulated studies in which the uptake effect (M2) and the
    post-test gain (M4) are detected at p < .05, using GEE with exchangeable
    correlation within participant: a population-average model that is fast
    enough to run hundreds of times and agrees with the mixed model on the
    sign and rough size of the effect."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    hits = {"uptake": 0, "post_gain": 0, "first_accuracy": 0}
    for r in range(reps):
        f = simulate(n_participants, seed + r, effects)
        a = f["attempts"]
        t = a[a.session_type == "training"]
        second = t[t.attempt_number == 2].copy(); second["D"] = (second.condition == "D").astype(int)
        first = t[t.is_first].copy(); first["D"] = (first.condition == "D").astype(int)
        s = a[a.session_type.isin(["pretest", "posttest"])].copy(); s["post"] = (s.session_type == "posttest").astype(int)
        for key, df, formula, term in (("uptake", second, "correct ~ D", "D"), ("first_accuracy", first, "correct ~ D", "D"),
                                       ("post_gain", s, "correct ~ post", "post")):
            try:
                m = smf.gee(formula, "participant", df, family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
                if m.pvalues[term] < 0.05:
                    hits[key] += 1
            except Exception:  # noqa: BLE001
                pass
    return {"n_participants": n_participants, "reps": reps, "power_pct": {k: round(100 * v / reps, 1) for k, v in hits.items()},
            "assumptions": simulate(2, seed, effects)["assumptions"]}


# --- instrument checks -----------------------------------------------------------------

def instrument_checks(a: pd.DataFrame) -> dict:
    t = a[(a.session_type == "training") & a.spoken & ~a.gated & ~a.skipped]
    words = t.groupby("condition").feedback_words.mean().round(1).to_dict() if len(t) else {}
    return {
        "utterance_length_words": words,
        "gated_pct": _rate(int(a[a.spoken].gated.sum()), int(a.spoken.sum())),
        "skipped_pct": _rate(int(a.skipped.sum()), len(a)),
        "rated_clips": 0, "false_correction_rate": None, "kappa": None,
        "note": "false-correction rate and kappa come from the rating tables once clips are rated (ratings export)",
    }


# --- main --------------------------------------------------------------------------------

def run(frames: dict[str, pd.DataFrame]) -> dict:
    a = frames["attempts"]
    return {
        "participants": int(a.participant.nunique()),
        "attempts": int(len(a)),
        "instrument": instrument_checks(a),
        "training": training_outcomes(a),
        "learning": learning_outcomes(a),
        "questionnaires": questionnaire_outcomes(frames["questionnaires"]),
        "models": models(frames),
    }


def _print(result: dict) -> None:
    print(f"{result['participants']} participants, {result['attempts']} attempts")
    print("\nInstrument:", json.dumps(result["instrument"], indent=1))
    print("\nTraining, K vs D:")
    for c, r in result["training"].items():
        print(f"  {c}: first-attempt accuracy {r['first_correct']}/{r['first_attempts']} ({r['first_accuracy_pct']}%), "
              f"uptake {r['uptake']}/{r['second_attempts']} ({r['uptake_pct']}%), graded {r['graded_mean']}, "
              f"RT median {r['response_time_median_s']} s, feedback {r['feedback_words_mean']} words")
    print("\nLearning:", json.dumps(result["learning"]["overall"], indent=1))
    for f, row in result["learning"]["by_feature"].items():
        print(f"  {f:20} {row}")
    print("\nQuestionnaires:", json.dumps(result["questionnaires"], indent=1))
    print("\nModels:")
    for m in result["models"]:
        print(f"  {m['label']}: {m.get('fit', '')}  n={m.get('n', '')}")
        if m.get("note"):
            print(f"     note: {m['note']}")
        if m.get("formula"):
            print(f"     {m['formula']}")
        for k, v in (m.get("fixed_effects") or {}).items():
            extra = f"  OR {m['odds_ratios'][k]}" if m.get("odds_ratios", {}).get(k) is not None else ""
            pv = f"  p={m['p_values'][k]}" if m.get("p_values", {}).get(k) is not None else ""
            print(f"     {k:12} {v[0]:+.3f} (se {v[1]:.3f}){extra}{pv}")
        if m.get("random_sd"):
            print(f"     random-effect sd: {m['random_sd']}")


def _finite(value):
    """JSON has no inf or nan; a standard error of inf (two observations,
    three parameters) becomes null rather than an invalid file."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", default="analysis")
    parser.add_argument("--simulate", type=int, default=None, metavar="N")
    parser.add_argument("--power", type=int, default=None, metavar="N")
    parser.add_argument("--reps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    out: dict = {}
    if args.power:
        out["power"] = power(args.power, args.reps, args.seed)
        print("Power:", json.dumps(out["power"], indent=1))
    else:
        frames = simulate(args.simulate, args.seed) if args.simulate else load(args.dir)
        out = run(frames)
        out["source"] = f"simulated N={args.simulate}" if args.simulate else f"export in {args.dir}/"
        if args.simulate:
            out["assumptions"] = frames["assumptions"]
        _print(out)
    if args.json:
        Path(args.json).write_text(json.dumps(_finite(out), indent=1, default=str), encoding="utf-8")
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
