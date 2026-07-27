"""Shared type helpers for schema parity.

These custom annotated types solve the zod-vs-pydantic JSON Schema gap for
optional (not nullable) fields.

In zod, `.optional()` makes a field non-required WITHOUT adding {type:null} to
the JSON Schema.  In pydantic, `str | None = None` adds {type:null} to anyOf.

Use the types in this module for fields that are optional-but-not-nullable
(i.e., zod source uses .optional() alone, not .nullable().optional()).
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from pydantic import GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema as cs


class _OptStrSchema:
    """Optional str without null in JSON Schema.  Runtime: accepts None."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return cs.nullable_schema(cs.str_schema())

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string"}


class _OptStrMin1Schema:
    """Optional str with minLength:1 without null in JSON Schema."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return cs.nullable_schema(cs.str_schema(min_length=1))

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "minLength": 1}


class _OptLiteralStartingSeqSchema:
    """Optional Literal['starting_seq'] without null in JSON Schema."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return cs.nullable_schema(cs.literal_schema(["starting_seq"]))

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "enum": ["starting_seq"]}


class _StripNullFromAnyOf:
    """Annotation marker: strip {type:null} from anyOf in this field's JSON schema.

    Used for optional-but-not-nullable list (and other non-str) fields where the
    Python type is ``Optional[X]`` but the JSON Schema should show just the base
    type (no null union), mirroring zod's ``.optional()`` behavior.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        return handler(source_type)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        result = handler(schema)
        if "anyOf" in result:
            non_null = [m for m in result["anyOf"] if m != {"type": "null"}]
            if len(non_null) == 1:
                merged = dict(non_null[0])
                for k, v in result.items():
                    if k != "anyOf":
                        merged[k] = v
                return merged
        return result


# Public types

# Optional str field: Python allows None, JSON Schema shows {type:string}
# Use for zod .string().optional() fields (NOT .string().nullable())
OptStr = Annotated[Optional[str], _OptStrSchema()]

# Optional str with minLength:1: JSON Schema shows {type:string, minLength:1}
OptStrMin1 = Annotated[Optional[str], _OptStrMin1Schema()]

# Optional Literal['starting_seq']
OptStartingSeq = Annotated[Optional[str], _OptLiteralStartingSeqSchema()]
