"""The five tables from document/planning.md (Data schema + decision log).

Notes vs the planning doc:
- `interval` is named `interval_days` here: INTERVAL is a Postgres type keyword,
  and the suffix documents the unit.
- Enums are stored as plain VARCHAR (native_enum=False) so adding a value later
  is a data change, not a Postgres type migration.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))
    # Demo account gets a nightly state reset; the owner account never does.
    is_demo: Mapped[bool] = mapped_column(default=False)


class GlobalDictionary(Base):
    """Every word / phrase / grammar rule, shared across all users."""

    __tablename__ = "global_dictionary"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(50))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("global_dictionary.id"))
    meaning_note: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="fr")
    # LLM-extracted, schema-free by design: features differ per language.
    linguistic_metadata: Mapped[dict | None] = mapped_column(JSON)


class UserMasteryMatrix(Base):
    """One row per user per language item: the SM-2 learning state."""

    __tablename__ = "user_mastery_matrix"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("global_dictionary.id"), primary_key=True)
    next_review_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval_days: Mapped[int]
    ease_factor: Mapped[float]
    # Consecutive successful reviews (quality >= 3); resets to 0 on failure.
    repetition: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)


class QuizStatus(enum.StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class PendingQuiz(Base):
    __tablename__ = "pending_quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    quiz_data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[QuizStatus] = mapped_column(
        Enum(QuizStatus, native_enum=False, length=20), default=QuizStatus.PENDING
    )
    # The global_dictionary ids this quiz tests — how grading maps back to SM-2 rows.
    entity_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobEventType(enum.StrEnum):
    NEW_ITEM_ADDED = "NEW_ITEM_ADDED"
    USER_ITEMS_DUE = "USER_ITEMS_DUE"


class JobStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class QuizGenerationJob(Base):
    """The Postgres job queue (decision log #4). Enqueued in the same transaction
    as the user-facing write; workers claim with FOR UPDATE SKIP LOCKED."""

    __tablename__ = "quiz_generation_jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[JobEventType] = mapped_column(
        Enum(JobEventType, native_enum=False, length=20)
    )
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=20), default=JobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
