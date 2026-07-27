"""SeedingLog schema — pydantic v2 port of seeding.js.

Zod source:
    z.object({
        type: z.literal('seeding'),
        species: z.string().min(1),
        block_name: z.string().regex(BLOCK_NAME_RE),
        qty: z.number().int().positive(),
        event_timestamp: z.string().datetime(),
        parent_batch_name: z.string().min(1).optional(),
        notes: z.string().optional(),
        confidence: z.record(z.string(), z.number().min(0).max(1)),
    }).strict()

Critical rules:
- extra='forbid' -> additionalProperties:false (mirrors .strict())
- qty: int = Field(gt=0) -> exclusiveMinimum:0 (NOT ge=1 which emits minimum:1)
- event_timestamp: Annotated[str, format:date-time] (zod .string().datetime() emits format:date-time)
- parent_batch_name / notes: use OptStrMin1 / OptStr (optional NOT nullable — zod .optional())
- confidence: dict[str, float] with ge=0,le=1 annotation on value type
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._types import OptStr, OptStrMin1

BLOCK_NAME_RE = r"^[0-9]{6}_[A-Z]{2,4}_[0-9]+$"


class SeedingLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["seeding"]
    species: str = Field(min_length=1)
    block_name: str = Field(pattern=BLOCK_NAME_RE)
    qty: int = Field(gt=0)
    # zod .string().datetime() emits format:date-time
    event_timestamp: Annotated[str, Field(json_schema_extra={"format": "date-time"})]
    # zod .optional() (NOT .nullable()) -> OptStrMin1/OptStr (no null in schema)
    parent_batch_name: OptStrMin1 = None
    notes: OptStr = None
    confidence: dict[str, Annotated[float, Field(ge=0, le=1)]]

    @field_validator("event_timestamp")
    @classmethod
    def validate_datetime_has_T(cls, v: str) -> str:
        if "T" not in v:
            raise ValueError("event_timestamp must be ISO-8601 with T separator")
        return v
