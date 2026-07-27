"""ObservationLog schema — pydantic v2 port of observation.js.

Two exports:
- ObservationLogBase: pure shape, no cross-field validator (used in discriminated union)
- ObservationLog: adds state_or_notes_required validator (standalone use)

Zod source:
    const ObservationLogBase = z.object({
        type: z.literal('observation'),
        asset_ref: z.string().min(1),
        state: z.string().optional(),
        notes: z.string().optional(),
        event_timestamp: z.string().datetime(),
        confidence: z.record(z.string(), z.number().min(0).max(1)),
    }).strict();

    const ObservationLog = ObservationLogBase.refine(hasStateOrNotes, ...);
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._types import OptStr


class ObservationLogBase(BaseModel):
    """Base shape — used in discriminated union (no cross-field validator)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["observation"]
    asset_ref: str = Field(min_length=1)
    # state/notes are optional-not-nullable (zod .optional(), NOT .nullable())
    state: OptStr = None
    notes: OptStr = None
    event_timestamp: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    confidence: dict[str, Annotated[float, Field(ge=0, le=1)]]

    @field_validator("event_timestamp")
    @classmethod
    def validate_datetime_has_T(cls, v: str) -> str:
        if "T" not in v:
            raise ValueError("event_timestamp must be ISO-8601 with T separator")
        return v


class ObservationLog(ObservationLogBase):
    """Standalone use — adds cross-field validator replicating .refine()."""

    @model_validator(mode="after")
    def state_or_notes_required(self) -> "ObservationLog":
        if not self.state and not self.notes:
            raise ValueError("observation requires state or notes")
        return self
