"""Storage transaction (progress.md spec: "a new word is learned").

Runs only after the user confirms the extracted items (confirm-first).
One transaction: find-or-create global_dictionary rows, insert missing
user_mastery_matrix rows with fresh SM-2 state, enqueue one NEW_ITEM_ADDED
job. Any failure rolls back all of it — no word without its mastery row,
no new mastery rows without their quiz job.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    GlobalDictionary,
    JobEventType,
    JobStatus,
    QuizGenerationJob,
    UserMasteryMatrix,
)


class DanglingParentError(ValueError):
    """A parent_token matched nothing in the batch or global_dictionary."""


class ConfirmedItem(BaseModel):
    token: str
    type: str
    language: str = "fr"
    meaning_note: str | None = None
    linguistic_metadata: dict = Field(default_factory=dict)
    parent_token: str | None = None


class StoredItem(BaseModel):
    token: str
    entity_id: int


class StorageResult(BaseModel):
    stored: list[StoredItem]
    # Tokens the user already tracks; the chat layer reports these back.
    already_tracked: list[str]
    job_id: int | None = None


def _norm(token: str) -> str:
    return token.strip().lower()


def _resolve_parent(
    session: Session, batch_ids: dict[str, int], item: ConfirmedItem
) -> int | None:
    if item.parent_token is None:
        return None
    key = _norm(item.parent_token)
    if key in batch_ids:
        return batch_ids[key]
    row_id = session.scalars(
        select(GlobalDictionary.id)
        .where(
            func.lower(GlobalDictionary.token) == key,
            GlobalDictionary.language == item.language,
        )
        .order_by(GlobalDictionary.id)
    ).first()
    if row_id is None:
        raise DanglingParentError(
            f"parent_token {item.parent_token!r} matches nothing in this batch "
            "or in global_dictionary; rejecting the whole batch"
        )
    return row_id


def _find_or_create_entity(
    session: Session, item: ConfirmedItem, parent_id: int | None
) -> GlobalDictionary:
    token = item.token.strip()
    entity = session.scalars(
        select(GlobalDictionary).where(
            GlobalDictionary.token == token,
            GlobalDictionary.type == item.type,
            GlobalDictionary.language == item.language,
            # meaning_note is part of the key: "soirée/evening" and
            # "soirée/party" must stay separate rows.
            GlobalDictionary.meaning_note == item.meaning_note,
        )
    ).first()
    if entity is None:
        entity = GlobalDictionary(
            token=token,
            type=item.type,
            language=item.language,
            meaning_note=item.meaning_note,
            linguistic_metadata=item.linguistic_metadata or None,
            parent_id=parent_id,
        )
        session.add(entity)
        session.flush()  # assign the id that children and the job payload need
    return entity


def store_confirmed_items(
    session: Session, user_id: int, items: list[ConfirmedItem]
) -> StorageResult:
    stored: list[StoredItem] = []
    already_tracked: list[str] = []
    new_entity_ids: list[int] = []
    batch_ids: dict[str, int] = {}
    job_id: int | None = None

    with session.begin():
        # Parentless items first, so a child's parent_token can resolve to a
        # row created moments ago in this same batch.
        for item in sorted(items, key=lambda i: i.parent_token is not None):
            parent_id = _resolve_parent(session, batch_ids, item)
            entity = _find_or_create_entity(session, item, parent_id)
            batch_ids.setdefault(_norm(entity.token), entity.id)

            if session.get(UserMasteryMatrix, (user_id, entity.id)):
                already_tracked.append(entity.token)
                continue
            session.add(
                UserMasteryMatrix(
                    user_id=user_id,
                    entity_id=entity.id,
                    # Fresh SM-2 state, due immediately: a brand-new word
                    # should be quizzed the same day.
                    next_review_date=datetime.now(UTC),
                    interval_days=0,
                    ease_factor=2.5,
                    repetition=0,
                )
            )
            stored.append(StoredItem(token=entity.token, entity_id=entity.id))
            new_entity_ids.append(entity.id)

        if new_entity_ids:
            job = QuizGenerationJob(
                user_id=user_id,
                event_type=JobEventType.NEW_ITEM_ADDED,
                payload={"entity_ids": new_entity_ids},
                status=JobStatus.PENDING,
            )
            session.add(job)
            session.flush()
            job_id = job.id

    return StorageResult(
        stored=stored, already_tracked=already_tracked, job_id=job_id
    )
