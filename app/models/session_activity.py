from sqlalchemy import Column, ForeignKey, Boolean, Integer, Float, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from sqlalchemy.orm import relationship

from app.database import Base


class SessionActivity(Base):
    __tablename__ = "session_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID, ForeignKey("therapy_sessions.id"))
    item_id = Column(UUID, ForeignKey("activity_items.id"))
    attempt_number = Column(Integer, default=1)
    is_correct = Column(Boolean)
    response_type = Column(String(10))  # 'verbal' or 'select'
    response_text = Column(String)

    # What this attempt was run as, copied from the item at the time. NULL
    # means repeat_word, like every attempt recorded before Phase 3.
    #
    # Denormalised for the same reason `condition` and `block_index` are:
    # editing an item next month must not rewrite what a stored attempt
    # actually was. A perception item later retyped as a production item would
    # otherwise silently move its history into the production results.
    exercise_type = Column(String(24))
    # The option tapped, or the syllable indices chosen. Null for spoken items,
    # where the answer is the recording.
    selected_answer = Column(JSON)

    # --- Phase 4: what the participant did before answering -----------------
    # P18 said the pacing was too fast and P6 asked for time to process, so the
    # prompt can be replayed. An item heard four times is not the same trial as
    # one heard once, and an analysis that cannot tell them apart is averaging
    # two different things.
    prompt_replays = Column(Integer)
    # Slowing the model down changes the stimulus, not only the pacing, so it
    # is recorded separately from the count.
    slow_replay_used = Column(Boolean)

    # Declined. Excluded from correction-rate denominators exactly as `gated`
    # is, but kept separate because the reason differs: gated means the
    # recogniser was not confident, skipped means the person chose not to
    # answer. Storing a skip as an error would be a false rejection arriving
    # through the back door.
    skipped = Column(Boolean)
    skip_reason = Column(String(20))   # cant_say | cant_hear | other

    # The revisit round. At the end of a training block every spoken item the
    # participant was corrected on comes back once, under the same condition.
    # That single attempt is the only within-session retention measure the
    # design has that carries a condition: the pre/post assessments cannot,
    # because every feature is trained under both conditions in every
    # participant. NULL on rows written before the round existed, which reads
    # as "main round" everywhere; attempt_number keeps counting across the
    # boundary so the ordering of an item's attempts stays one sequence.
    revisit = Column(Boolean)

    # Was the robot instructed to celebrate this attempt? Not inferable from
    # is_correct, which is true in assessments too, where nothing is performed.
    #
    # Records the instruction, not the performance: if the robot had lost focus
    # it stayed still and this column will not know. That limit is worth
    # stating, because three pilot participants named the movement and the
    # "yay" unprompted as what gave them confidence, and a per-session count of
    # instructed celebrations is the granularity that claim can be tested at.
    celebration_shown = Column(Boolean)

    # --- Phase 5: was that correction any good? -----------------------------
    # 1..5, NULL when not asked. Sampled rather than asked after every
    # correction: a tap on every item would turn the session into a survey, and
    # the later answers would be worse than none.
    #
    # The pilot asked this once per session, which was its most useful item and
    # measured at the wrong grain: one number cannot distinguish a session with
    # one bad correction from one with six, and that is exactly the contrast
    # between K and D that needs item-level variance to detect.
    feedback_helpful = Column(Integer)
    feedback = Column(String)
    pronunciation_score = Column(Float)
    response_time_seconds = Column(Float)
    # Enhanced error tracking for sentences
    error_type = Column(String(300))  # 'repetition', 'stammering', 'substitution', 'sentence_errors', 'correct'
    substitutions = Column(JSON)  # Store specific sound substitutions
    repetition_count = Column(Integer, default=0)
    stammering_detected = Column(Boolean, default=False)
    # New fields for sentence analysis
    word_analysis = Column(JSON)  # Store per-word analysis
    correct_word_count = Column(Integer, default=0)
    total_word_count = Column(Integer, default=0)

    # --- acoustic pipeline (v2) -------------------------------------------
    condition = Column(String(1))          # 'K' or 'D', copied from the session
    verdict = Column(String(20))           # correct/close/stress_error/incorrect/gated/unscorable
    verdict_score = Column(Float)          # worst-phone aggregate; drives is_correct (H1)
    confidence = Column(Float)             # recogniser confidence; gates diagnosis
    gated = Column(Boolean, default=False) # excluded from correction-rate denominators
    expected_phones = Column(JSON)
    observed_phones = Column(JSON)
    phone_scores = Column(JSON)            # per-phone GOP + calibrated score
    diagnoses = Column(JSON)
    applied_folds = Column(JSON)           # contrasts the model cannot represent
    stress_error = Column(Boolean)
    named_phone = Column(String(4))        # the phone the robot named, if any
    feedback_word_count = Column(Integer)  # for K/D utterance-length reporting
    # --- reference provenance and the ASR cross-check ----------------------
    reference_source = Column(String(20))      # override/beep/cmudict+gb-rules/cmudict/g2p
    reference_needs_review = Column(Boolean)   # target was a g2p prediction
    transcript = Column(String)                # client ASR output, if sent
    transcript_matches = Column(Boolean)       # did it agree the target was said
    # --- device-side timing ------------------------------------------------
    # The response-time DV is the interval from the end of the robot's prompt
    # to the start of the participant's speech. Both instants happen on the
    # tablet, so both are timed there; a server timestamp would measure upload
    # latency as well and would vary with the wifi in the room.
    #
    # Stored as the raw instants rather than only the difference, so that a
    # suspicious value can be diagnosed afterwards (a long gap because the
    # participant hesitated looks identical to one because the recorder started
    # late, unless you kept both ends).
    prompt_ended_at = Column(DateTime)
    speech_started_at = Column(DateTime)
    speech_ended_at = Column(DateTime)

    # --- recording quality --------------------------------------------------
    # Measured on the uploaded audio, before scoring. This is about the
    # recording, not the recognition: `confidence` already says how sure the
    # acoustic model was, but it cannot distinguish "said it oddly" from
    # "microphone was three metres away". The 2026-09-15 batch contained a
    # two-second clip of clucking and one of a bystander's conversation, and
    # nothing in the stored row said so.
    audio_peak = Column(Float)             # 0..1, absolute peak sample
    audio_rms_dbfs = Column(Float)         # loudness of the speech portion
    audio_clipped_fraction = Column(Float) # fraction of samples at full scale
    audio_quality = Column(String(12))     # ok/quiet/clipped/short/long/silent

    # --- reproducibility ---------------------------------------------------
    audio_ref = Column(String)             # path to the retained recording
    pipeline_version = Column(String(20))
    config_hash = Column(String(16))
    model_id = Column(String(120))
    stage_timings_ms = Column(JSON)        # per-stage latency, for the latency table

    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("TherapySession", back_populates="activities")
    item = relationship("ActivityItem")