"""Submission schema — top-level model + SUBMISSION_JSON_SCHEMA export.

Mirrors the Node extraction/schemas/index.js assembly:
    const Draft = z.discriminatedUnion('type', [
        SeedingLog, ActivityLog, InputLog, ObservationLogBase, HarvestLog, SeedingSession,
    ]);

Union order is significant: must match anyOf member order in the fixture:
    anyOf[0] = seeding
    anyOf[1] = activity
    anyOf[2] = input
    anyOf[3] = observation
    anyOf[4] = harvest
    anyOf[5] = seeding_session

Union uses plain Union (no Field(discriminator=...)) so pydantic emits anyOf
instead of oneOf+discriminator, matching the zod-to-json-schema fixture shape.
After normalize_schema() inlines $refs, the result matches the fixture exactly.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .activity import ActivityLog
from .harvest import HarvestLog
from .input import InputLog
from .observation import ObservationLogBase
from .seeding import SeedingLog
from .seeding_session import SeedingSession

# anyOf member order must match the fixture
DraftUnion = Union[
    SeedingLog,
    ActivityLog,
    InputLog,
    ObservationLogBase,
    HarvestLog,
    SeedingSession,
]


class DraftSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: DraftUnion
    per_field_confidence: dict[str, Annotated[float, Field(ge=0, le=1)]]


CaptureKind = Literal["paper_log", "physical_object_photo", "voice_note", "text"]


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: list[DraftSubmission] = Field(min_length=1)
    continuity: Literal["append", "replace", "start_new"]
    continuity_reason: str = Field(min_length=1)
    # capture_kind is nullable().optional() in zod — use Optional[CaptureKind] to
    # preserve the anyOf with null in JSON Schema (matches fixture anyOf structure)
    capture_kind: CaptureKind | None = None


SUBMISSION_JSON_SCHEMA = Submission.model_json_schema()
