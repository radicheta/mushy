"""ActivityLog schema — pydantic v2 port of activity.js.

Zod source:
    const ACTIVITY_NAMES = ['sterilize', 'sterilize_failed', 'water', 'relocate',
                             'cold_shock', 'archive_spent', 'contam'];
    z.object({
        type: z.literal('activity'),
        name: z.enum(ACTIVITY_NAMES),
        asset_ref: z.string().min(1),
        event_timestamp: z.string().datetime(),
        notes: z.string().optional(),
        confidence: z.record(z.string(), z.number().min(0).max(1)),
    }).strict()
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._types import OptStr

ACTIVITY_NAMES = Literal[
    "sterilize",
    "sterilize_failed",
    "water",
    "relocate",
    "cold_shock",
    "archive_spent",
    "contam",
]


class ActivityLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["activity"]
    name: ACTIVITY_NAMES
    asset_ref: str = Field(min_length=1)
    event_timestamp: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    notes: OptStr = None
    confidence: dict[str, Annotated[float, Field(ge=0, le=1)]]

    @field_validator("event_timestamp")
    @classmethod
    def validate_datetime_has_T(cls, v: str) -> str:
        if "T" not in v:
            raise ValueError("event_timestamp must be ISO-8601 with T separator")
        return v
