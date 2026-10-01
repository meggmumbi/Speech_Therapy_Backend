"""Worked-example numbers for part 2 of the guide, from P1's run."""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, r"C:\Users\ADMIN\PycharmProjects\speech_therapy_Backend")
os.chdir(r"C:\Users\ADMIN\PycharmProjects\speech_therapy_Backend")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:12345@localhost/asd_therapy")
from app.database import SessionLocal
from app.models import ActivityCategory, ActivityItem, Child, SessionActivity, TherapySession
from app.models.session_questionnaire import SessionQuestionnaire
from app.models.study_assignment import StudyAssignment
from app.services import exercises

db = SessionLocal()
p = db.query(Child).filter(Child.participant_code == "P1").first()
asg = db.query(StudyAssignment).filter(StudyAssignment.child_id == p.id).first()
out = {
    "participant": {
        "participant_code": p.participant_code, "age": p.age, "gender": p.gender,
        "first_language": p.first_language, "other_languages": p.other_languages, "home_language": p.home_language,
        "region_of_upbringing": p.region_of_upbringing, "english_onset_age": p.english_onset_age,
        "primary_medium_of_instruction": p.primary_medium_of_instruction, "self_rated_english": p.self_rated_english,
        "voice_assistant_use": p.voice_assistant_use, "hearing_or_speech_difficulty": p.hearing_or_speech_difficulty,
        "consent_participation": p.consent_participation, "consent_audio_retention": p.consent_audio_retention,
        "consent_date": str(p.consent_date),
    },
    "assignment": {"group_index": asg.group_index, "block1": f"{asg.block1_condition}-{asg.block1_list}",
                   "block2": f"{asg.block2_condition}-{asg.block2_list}", "excluded": asg.excluded},
}
cats = {c.id: c for c in db.query(ActivityCategory).all()}
sessions = db.query(TherapySession).filter(TherapySession.child_id == p.id).order_by(TherapySession.start_time).all()
out["sessions"] = []
for s in sessions:
    rows = (db.query(SessionActivity, ActivityItem).join(ActivityItem, SessionActivity.item_id == ActivityItem.id)
            .filter(SessionActivity.session_id == s.id).all())
    spoken = [a for a, it in rows if exercises.needs_asr(a.exercise_type or it.effective_type)]
    tapped = [a for a, it in rows if not exercises.needs_asr(a.exercise_type or it.effective_type)]
    firsts = [a for a in spoken if a.attempt_number == 1]
    out["sessions"].append({
        "id": str(s.id)[:8], "type": s.session_type, "condition": s.condition, "block": s.block_index,
        "list": cats[s.category_id].study_role if s.category_id in cats else None,
        "minutes": round((s.end_time - s.start_time).total_seconds() / 60, 1) if s.end_time else None,
        "items": len({a.item_id for a, _ in rows}), "attempts": len(rows), "spoken": len(spoken), "tapped": len(tapped),
        "verdicts": dict(Counter(a.verdict for a in spoken)),
        "first_attempt_correct": sum(1 for a in firsts if a.is_correct), "first_attempts": len(firsts),
        "retries": sum(1 for a in spoken if a.attempt_number == 2),
        "tapped_correct": sum(1 for a in tapped if a.is_correct),
        "skipped": sum(1 for a, _ in rows if a.skipped), "gated": sum(1 for a in spoken if a.gated),
        "replays": sum(a.prompt_replays or 0 for a, _ in rows),
        "mean_response_s": round(sum(a.response_time_seconds or 0 for a in spoken) / max(1, len(spoken)), 2),
        "mean_verdict_score": round(sum(a.verdict_score or 0 for a in spoken) / max(1, len(spoken)), 3),
        "mean_graded_score": round(sum(a.pronunciation_score or 0 for a in spoken) / max(1, len(spoken)), 3),
        "feedback_kinds": dict(Counter(("celebration" if a.celebration_shown else ("correction" if a.verdict and not a.is_correct else "other")) for a in spoken)),
        "mean_feedback_words": round(sum(a.feedback_word_count or 0 for a in spoken) / max(1, len(spoken)), 1),
    })
# per-feature, first attempts, pre vs post
feat = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for s in sessions:
    if s.session_type not in ("pretest", "posttest"):
        continue
    rows = (db.query(SessionActivity, ActivityItem).join(ActivityItem, SessionActivity.item_id == ActivityItem.id)
            .filter(SessionActivity.session_id == s.id, SessionActivity.attempt_number == 1).all())
    for a, it in rows:
        if not it.target_feature or not exercises.needs_asr(a.exercise_type or it.effective_type):
            continue
        feat[it.target_feature][s.session_type][0] += int(bool(a.is_correct))
        feat[it.target_feature][s.session_type][1] += 1
out["by_feature"] = {f: {k: v for k, v in d.items()} for f, d in feat.items()}
qs = db.query(SessionQuestionnaire).filter(SessionQuestionnaire.child_id == p.id).all()
out["questionnaires"] = [{"condition": q.condition, "block": q.block_index, "scores": {k: v["mean"] for k, v in (q.scores or {}).items()},
                          "duration_seconds": q.duration_seconds, "answers": q.answers} for q in qs]
# the item inventory per list
inv = {}
for c in cats.values():
    if not c.study_role:
        continue
    items = db.query(ActivityItem).filter(ActivityItem.category_id == c.id).all()
    inv[c.study_role] = {"name": c.name, "items": len(items),
                         "by_type": dict(Counter(i.effective_type for i in items)),
                         "by_feature": dict(Counter(i.target_feature or "none" for i in items)),
                         "with_audio": sum(1 for i in items if i.audio_url)}
out["inventory"] = inv
# example attempt (the pretest 'hat')
a = (db.query(SessionActivity).join(TherapySession, SessionActivity.session_id == TherapySession.id)
     .filter(TherapySession.child_id == p.id, SessionActivity.transcript == "HUT!").first())
out["example_attempt"] = {
    "item": "hat", "session": "pretest", "attempt_number": a.attempt_number, "exercise_type": a.exercise_type,
    "verdict": a.verdict, "verdict_score": a.verdict_score, "pronunciation_score": a.pronunciation_score,
    "confidence": a.confidence, "expected_phones": a.expected_phones, "observed_phones": a.observed_phones,
    "phone_scores": [(x["phone"], round(x["score"], 2)) for x in a.phone_scores],
    "diagnoses": [(d["kind"], d["expected"], d["observed"], round(d["score"], 2)) for d in a.diagnoses],
    "transcript": a.transcript, "transcript_matches": a.transcript_matches,
    "feedback": a.feedback, "response_time_seconds": a.response_time_seconds,
    "audio_peak": round(a.audio_peak, 2), "audio_rms_dbfs": round(a.audio_rms_dbfs, 1), "audio_quality": a.audio_quality,
    "config_hash": a.config_hash, "pipeline_version": a.pipeline_version,
}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "part2.json"), "w"), indent=1, default=str)
print(json.dumps(out["sessions"], indent=1))
print(json.dumps(out["by_feature"], indent=1))
print(json.dumps(out["inventory"], indent=1))
print([q["scores"] for q in out["questionnaires"]])
