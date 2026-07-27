"""InputLog schema — pydantic v2 port of input.js.

Zod source:
    z.object({
        type: z.literal('input'),
        recipe_lot: z.string().min(1),
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


class InputLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["input"]
    recipe_lot: str = Field(min_length=1)
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
