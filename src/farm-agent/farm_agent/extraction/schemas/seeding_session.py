"""SeedingSession schema — pydantic v2 port of seeding-session.js.

Complex nested model with Provenanced[T] generics, ConflictEntry, and the
ChildBlockNameOrSentinel union.

Critical rules:
- extra='forbid' on EVERY nested model (SeedingSessionGroup, ConflictEntry, SeedingSession)
- event_date: str with bare-date pattern (NOT datetime) — zod uses .string().regex()
- ChildBlockNameOrSentinel: Literal['NEEDS_SEQ'] FIRST to match fixture anyOf[0] order
- ParentRef = str min_length=1 (Provenanced[ParentRef])
- qty: Provenanced[int Field(gt=0)] -> exclusiveMinimum:0
- conflicts / needs_input / notes: optional (not nullable) using _types helpers
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from ._types import OptStr, OptStartingSeq, _StripNullFromAnyOf
from .provenance import Provenanced, SourceEnum
from .seeding import BLOCK_NAME_RE

# ChildBlockNameOrSentinel: NEEDS_SEQ FIRST to match anyOf member order in fixture
ChildBlockNameOrSentinel = Union[
    Literal["NEEDS_SEQ"],
    Annotated[str, Field(pattern=BLOCK_NAME_RE)],
]

# ParentRef: canonical block_name or shorthand — permissive str min(1)
ParentRef = Annotated[str, Field(min_length=1)]


class SeedingSessionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: Provenanced[ParentRef]
    species: Provenanced[Annotated[str, Field(pattern=r"^[A-Z]{2,4}$")]]
    qty: Provenanced[Annotated[int, Field(gt=0)]]
    child_block_names: Provenanced[
        Annotated[list[ChildBlockNameOrSentinel], Field(min_length=1)]
    ]


class _CandidateEntry(BaseModel):
    """Single candidate in a ConflictEntry.candidates[] — z.unknown() for value.

    value: Any = None (not required) because zod's z.unknown() allows undefined;
    JSON Schema emits {} for value and does not include it in required[].
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = None  # z.unknown() -> not required; emits {} in schema
    source: SourceEnum
    confidence: Annotated[float, Field(ge=0, le=1)]


class ConflictEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    candidates: list[_CandidateEntry] = Field(min_length=2)
    resolution: Literal[
        "photo_wins_implicit",
        "ask_back_required",
        "accepted_consensus",
    ]


class SeedingSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["seeding_session"]
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    groups: list[SeedingSessionGroup] = Field(min_length=1)
    needs_input: OptStartingSeq = None
    # conflicts is optional-not-nullable (zod .optional()): use _StripNullFromAnyOf
    conflicts: Annotated[list[ConflictEntry] | None, _StripNullFromAnyOf()] = None
    notes: OptStr = None
