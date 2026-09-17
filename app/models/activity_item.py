from sqlalchemy import Column, Integer, String, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid

from sqlalchemy.orm import relationship

from app.database import Base


class ActivityItem(Base):
    """One exercise.

    Until Phase 3 there was only one kind: Pepper says a word, the participant
    repeats it, the recogniser scores it. `name` was the word, the prompt and
    the answer key all at once.

    Phase 3 adds eight more types, six of which are answered by tapping and
    never touch the recogniser. See docs/PHASE3_ITEM_MODEL.md for the design;
    app/services/exercises.py holds the fork between spoken and tapped.
    """

    __tablename__ = "activity_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(300), nullable=False)
    description = Column(String(300), nullable=True)
    category_id = Column(UUID, ForeignKey("activity_categories.id"))
    image_url = Column(String(300))
    audio_url = Column(String(300))
    difficulty_level = Column(String(20))

    # --- Phase 3: the typed exercise ---------------------------------------

    # NULL means repeat_word. Every item stored before 2026-09-17 is one, and
    # defaulting rather than backfilling keeps those items and every attempt
    # recorded against them meaning what they meant.
    exercise_type = Column(String(24))

    # Shape determined by exercise_type and validated at the API boundary by
    # app/schemas/exercise_spec.py. JSON rather than a column per type: the
    # alternative is around thirty mostly-null columns and a migration every
    # time an exercise type is added.
    spec = Column(JSON)

    # Which Kenyan English transfer feature this item tests. The analysis is
    # per-feature -- does training on KIT/FLEECE transfer to untrained
    # KIT/FLEECE words -- and without this there is no way to group items for
    # that, or to check that lists A and B cover the same ground.
    target_feature = Column(String(32), index=True)

    # Ties an item to its counterpart in the other list and to the untrained
    # test item for the same feature. "Difficulty-matched lists" has to mean
    # something checkable; this is what makes it checkable.
    match_key = Column(String(32), index=True)

    # Authoring order. Presentation order is randomised per session from the
    # session's own seed, so this never decides what a participant sees.
    position = Column(Integer)

    category = relationship("ActivityCategory", back_populates="items")

    @property
    def effective_type(self) -> str:
        """The exercise type to run this as, resolving the legacy NULL."""
        return self.exercise_type or "repeat_word"
