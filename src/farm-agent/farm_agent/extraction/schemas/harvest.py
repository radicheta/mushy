"""HarvestLog schema — pydantic v2 port of harvest.js.

Zod source:
    z.object({
        type: z.literal('harvest'),
        harvest_batch_id: z.string().min(1),
        source_block_refs: z.array(z.string().min(1)).min(1),
        qty_g: z.number().positive(),
        event_timestamp: z.string().datetime(),
        notes: z.string().optional(),
        confidence: z.record(z.string(), z.number().min(0).max(1)),
    }).strict()

Note: qty_g is z.number().positive() (non-integer) -> float = Field(gt=0)
source_block_refs items have min(1) -> list[Annotated[str, Field(min_length=1)]]
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._types import OptStr


class HarvestLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["harvest"]
    harvest_batch_id: str = Field(min_length=1)
    source_block_refs: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    qty_g: float = Field(gt=0)
    event_timestamp: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    notes: OptStr = None
    confidence: dict[str, Annotated[float, Field(ge=0, le=1)]]

    @field_validator("event_timestamp")
    @classmethod
    def validate_datetime_has_T(cls, v: str) -> str:
        if "T" not in v:
            raise ValueError("event_timestamp must be ISO-8601 with T separator")
        return v
