"""Authoring the stimulus sets: bulk import, list binding, and validation.

Designing stimuli happens in a spreadsheet. Twelve form submissions per word
list is how transcription errors get in, and a minimal pair is two words plus a
key that has to be edited together or not at all. So a whole list arrives as one
document, every item is validated against its type, and every problem is
reported at once rather than failing on the first.

Import is a dry run unless asked otherwise. Overwriting a list that has already
been run is not recoverable from the app, and the moment to notice is before the
write, not after.

See docs/PHASE3_ITEM_MODEL.md.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import exercise_spec
from ..services import exercises
from ..utils.auth import get_current_user

router = APIRouter(tags=["authoring"])


# --- request shapes ---------------------------------------------------------

class ItemImport(BaseModel):
    """One row of a stimulus spreadsheet."""

    exercise_type: str
    spec: dict[str, Any] = Field(default_factory=dict)
    target_feature: str | None = None
    #: Ties this item to its counterpart in the other training list and to the
    #: untrained test item for the same slot.
    match_key: str | None = None
    #: Overrides the type's standard instruction. Leave unset unless there is a
    #: reason: an instruction that varies between lists is itself a difficulty
    #: difference between them.
    description: str | None = None
    image_url: str | None = None
    audio_url: str | None = None
    difficulty_level: str | None = None


class ListImport(BaseModel):
    items: list[ItemImport]
    #: Without this the import is reported and discarded.
    apply: bool = False
    #: Delete the category's existing items first. Refused outright if any of
    #: them already has a recorded attempt.
    replace: bool = False


class StudyRoleRequest(BaseModel):
    #: list_a | list_b | test, or null to unbind.
    study_role: str | None


# --- import -----------------------------------------------------------------

@router.post("/categories/{category_id}/items/import")
def import_items(
    category_id: uuid.UUID,
    request: ListImport,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Validate a whole list, and write it only if asked.

    Every row is checked before anything is written, and every failure is
    returned together. Stopping at the first error means the author fixes one
    typo, re-runs, and finds the next one.
    """
    category = (
        db.query(models.ActivityCategory)
        .filter(models.ActivityCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(404, "Category not found")
    if not request.items:
        raise HTTPException(400, "No items in the import")

    errors: list[dict] = []
    prepared: list[dict] = []

    for index, row in enumerate(request.items):
        where = {"row": index, "match_key": row.match_key}
        try:
            parsed = exercise_spec.parse(row.exercise_type, row.spec)
        except exercises.UnknownExerciseType as exc:
            errors.append({**where, "problem": str(exc)})
            continue
        except ValidationError as exc:
            for detail in exc.errors():
                errors.append({
                    **where,
                    "field": ".".join(str(p) for p in detail["loc"]),
                    "problem": detail["msg"],
                })
            continue

        if row.target_feature and row.target_feature not in exercises.TARGET_FEATURES:
            errors.append({
                **where, "field": "target_feature",
                "problem": f"{row.target_feature!r} is not a known feature. "
                           f"Known: {', '.join(exercises.TARGET_FEATURES)}",
            })
            continue

        prepared.append({
            "position": index,
            "name": exercise_spec.display_name(parsed)[:300],
            "description": (row.description
                            or exercise_spec.default_prompt(parsed))[:300],
            "exercise_type": parsed.exercise_type,
            "spec": parsed.model_dump(exclude={"exercise_type"}),
            "target_feature": row.target_feature,
            "match_key": row.match_key,
            "image_url": row.image_url,
            "audio_url": row.audio_url,
            "difficulty_level": row.difficulty_level or category.difficulty_level,
        })

    duplicates = _duplicate_match_keys(prepared)
    for key in duplicates:
        errors.append({
            "match_key": key,
            "problem": "two items in this list share a match_key; a slot holds "
                       "one item per list or the lists cannot be paired",
        })

    existing = (
        db.query(models.ActivityItem)
        .filter(models.ActivityItem.category_id == category_id)
        .all()
    )
    attempted = _items_with_attempts(db, [item.id for item in existing])

    report = {
        "category": category.name,
        "applied": False,
        "valid": len(prepared),
        "errors": errors,
        "existing_items": len(existing),
        "existing_items_with_attempts": len(attempted),
        "preview": [
            {"name": p["name"], "exercise_type": p["exercise_type"],
             "target_feature": p["target_feature"], "match_key": p["match_key"]}
            for p in prepared[:10]
        ],
    }

    if errors:
        report["message"] = (
            f"{len(errors)} problem(s) found. Nothing was written."
        )
        return report
    if not request.apply:
        report["message"] = (
            "Dry run: everything validates. Re-send with apply=true to write it."
        )
        return report

    if request.replace:
        if attempted:
            raise HTTPException(
                409,
                f"{len(attempted)} existing item(s) in this category already "
                f"have recorded attempts. Replacing them would orphan those "
                f"attempts from the item they were answers to. Create a new "
                f"category instead."
            )
        for item in existing:
            db.delete(item)
        db.flush()

    for values in prepared:
        db.add(models.ActivityItem(id=uuid.uuid4(), category_id=category_id, **values))
    db.commit()

    report["applied"] = True
    report["message"] = f"Wrote {len(prepared)} item(s) to {category.name}."
    return report


def _duplicate_match_keys(prepared: list[dict]) -> list[str]:
    seen: dict[str, int] = {}
    for item in prepared:
        key = item.get("match_key")
        if key:
            seen[key] = seen.get(key, 0) + 1
    return sorted(key for key, n in seen.items() if n > 1)


def _items_with_attempts(db: Session, item_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not item_ids:
        return set()
    rows = (
        db.query(models.SessionActivity.item_id)
        .filter(models.SessionActivity.item_id.in_(item_ids))
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


# --- binding a category to the design ---------------------------------------

@router.put("/categories/{category_id}/study-role")
def set_study_role(
    category_id: uuid.UUID,
    request: StudyRoleRequest,
    db: Session = Depends(get_db),
    current_user: models.Caregiver = Depends(get_current_user),
):
    """Mark a category as training list A, list B, or the assessment set.

    Replaces editing STUDY_LIST_A_CATEGORY_ID on the server and restarting it.
    Refuses to move a role away from a category that has already been used,
    because the stored sessions point at the category by id and re-labelling it
    afterwards would silently change what they were.
    """
    category = (
        db.query(models.ActivityCategory)
        .filter(models.ActivityCategory.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(404, "Category not found")

    role = request.study_role
    if role is not None and role not in exercises.STUDY_ROLES:
        raise HTTPException(
            400, f"study_role must be one of {', '.join(exercises.STUDY_ROLES)} or null")

    if role is not None:
        holder = (
            db.query(models.ActivityCategory)
            .filter(models.ActivityCategory.study_role == role,
                    models.ActivityCategory.id != category_id)
            .first()
        )
        if holder:
            if _category_has_sessions(db, holder.id):
                raise HTTPException(
                    409,
                    f"{holder.name!r} is already bound as {role} and has "
                    f"sessions recorded against it. Moving the role would "
                    f"change what those sessions were."
                )
            holder.study_role = None
            db.flush()

    category.study_role = role
    db.commit()
    db.refresh(category)
    return {
        "category_id": str(category.id),
        "name": category.name,
        "study_role": category.study_role,
        "item_count": db.query(models.ActivityItem)
                        .filter(models.ActivityItem.category_id == category.id).count(),
    }


def _category_has_sessions(db: Session, category_id: uuid.UUID) -> bool:
    return (
        db.query(models.TherapySession)
        .filter(models.TherapySession.category_id == category_id)
        .first()
    ) is not None


# --- is the stimulus design sound -------------------------------------------

@router.get("/item-sets/validate")
def validate_item_sets(db: Session = Depends(get_db)):
    """Check the invariants the within-subject design depends on.

    Reports; refuses nothing. A half-built list during authoring is normal, and
    this belongs before a study day rather than in the way of one.
    """
    by_role: dict[str, models.ActivityCategory] = {}
    for category in db.query(models.ActivityCategory).filter(
            models.ActivityCategory.study_role.isnot(None)).all():
        by_role[category.study_role] = category

    problems: list[str] = []
    summary: dict[str, Any] = {}

    for role in exercises.STUDY_ROLES:
        if role not in by_role:
            problems.append(f"no category is bound as {role}")

    items_by_role: dict[str, list[models.ActivityItem]] = {}
    for role, category in by_role.items():
        items = (
            db.query(models.ActivityItem)
            .filter(models.ActivityItem.category_id == category.id)
            .all()
        )
        items_by_role[role] = items
        summary[role] = {
            "category": category.name,
            "items": len(items),
            "features": sorted({i.target_feature for i in items if i.target_feature}),
            "exercise_types": sorted({i.effective_type for i in items}),
            "missing_feature": sum(1 for i in items if not i.target_feature),
        }
        if not items:
            problems.append(f"{role} ({category.name}) has no items")
        for item in items:
            try:
                exercise_spec.parse(item.exercise_type, item.spec)
            except (exercises.UnknownExerciseType, ValidationError) as exc:
                problems.append(
                    f"{role}: item {item.name!r} has an invalid spec: "
                    f"{str(exc).splitlines()[0]}")

    a = items_by_role.get(exercises.LIST_A, [])
    b = items_by_role.get(exercises.LIST_B, [])
    test = items_by_role.get(exercises.TEST_SET, [])

    if a and b:
        if len(a) != len(b):
            problems.append(
                f"lists A and B are different lengths ({len(a)} vs {len(b)}); "
                f"participants in different groups would not do equal work")
        keys_a = {i.match_key for i in a if i.match_key}
        keys_b = {i.match_key for i in b if i.match_key}
        for key in sorted(keys_a - keys_b):
            problems.append(f"slot {key!r} exists in list A but not list B")
        for key in sorted(keys_b - keys_a):
            problems.append(f"slot {key!r} exists in list B but not list A")

        features_a = _feature_counts(a)
        features_b = _feature_counts(b)
        for feature in sorted(set(features_a) | set(features_b)):
            if features_a.get(feature, 0) != features_b.get(feature, 0):
                problems.append(
                    f"feature {feature!r} appears {features_a.get(feature, 0)} "
                    f"time(s) in list A and {features_b.get(feature, 0)} in "
                    f"list B; the lists are not matched on it")

    if test:
        # The test set deliberately mixes three kinds of item, and a
        # participant trains on only one list, so for them the three become a
        # within-subject factor that no other part of the design provides:
        #
        #   trained    the list they practised           -> item-specific gain
        #   other list the list they did not practise    -> matched control
        #   novel      neither list, same feature        -> generalisation
        #
        # Generalisation is the measure that distinguishes learning from having
        # memorised twelve words, so an assessment set with no novel items for
        # a feature cannot answer the question the study is asking about it.
        words_a = {i.name.strip().lower() for i in a}
        words_b = {i.name.strip().lower() for i in b}
        origin = {"from_list_a": 0, "from_list_b": 0, "novel": 0}
        novel_features: set[str] = set()
        for item in test:
            word = item.name.strip().lower()
            if word in words_a:
                origin["from_list_a"] += 1
            elif word in words_b:
                origin["from_list_b"] += 1
            else:
                origin["novel"] += 1
                if item.target_feature:
                    novel_features.add(item.target_feature)
        summary.setdefault(exercises.TEST_SET, {})["origin"] = origin

        if a and b:
            if not origin["from_list_a"] or not origin["from_list_b"]:
                problems.append(
                    "the assessment set must draw from both training lists, so "
                    "that the list a participant did not train on serves as "
                    "their matched control")
            if origin["from_list_a"] != origin["from_list_b"]:
                problems.append(
                    f"the assessment set draws {origin['from_list_a']} item(s) "
                    f"from list A and {origin['from_list_b']} from list B; "
                    f"unequal draws make the trained/control contrast unbalanced")

        trained_features = set(_feature_counts(a)) | set(_feature_counts(b))
        for feature in sorted(trained_features - set(_feature_counts(test))):
            problems.append(f"feature {feature!r} is trained but never assessed")
        for feature in sorted(trained_features - novel_features):
            problems.append(
                f"feature {feature!r} has no untrained item in the assessment "
                f"set, so generalisation cannot be measured for it")

    return {
        "sound": not problems,
        "problems": problems,
        "by_role": summary,
        "known_features": list(exercises.TARGET_FEATURES),
        "known_exercise_types": list(exercises.EXERCISE_TYPES),
    }


def _feature_counts(items: list[models.ActivityItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if item.target_feature:
            counts[item.target_feature] = counts.get(item.target_feature, 0) + 1
    return counts


# --- what the authoring UI needs to offer -----------------------------------

@router.get("/exercise-types")
def exercise_types():
    """The vocabulary, so the app's pickers cannot drift from the server's."""
    return {
        "exercise_types": [
            {
                "key": t.key, "label": t.label, "spoken": t.spoken,
                "scored_by_pipeline": t.scored_by_pipeline,
                "construct": t.construct, "description": t.description,
            }
            for t in exercises.TYPES
        ],
        "target_features": [
            {"key": f.key, "label": f.label,
             "contrast": f.contrast, "example": f.example}
            for f in exercises.FEATURES
        ],
        "study_roles": list(exercises.STUDY_ROLES),
    }
