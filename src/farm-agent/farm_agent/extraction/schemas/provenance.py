"""Provenance Generic wrapper.

Mirrors the Node `Provenanced(valueSchema)` factory:

    z.object({ value, confidence, sources[] }).strict()

The Generic[T] approach replicates the factory pattern.  Every callsite in
seeding_session.py uses e.g. Provenanced[str], Provenanced[int], etc.
The model_config = ConfigDict(extra='forbid') is required to emit
``additionalProperties: false`` on every inline object — mirroring .strict().
"""

from __future__ import annotations

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

SourceEnum = Literal[
    "audio",
    "paper_log_photo",
    "bag_label_photo",
    "text",
    "model_inference",
]


class Provenanced(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    value: T
    confidence: Annotated[float, Field(ge=0, le=1)]
    sources: list[SourceEnum] = Field(min_length=1)
