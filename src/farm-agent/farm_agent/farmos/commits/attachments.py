"""farm_agent/farmos/commits/attachments.py -- draft photo upload glue (MUSHY-131).

Lifted verbatim out of commit_observation, which was the only handler that had
it. commit_activity did not, so a photo sent with an activity was captured,
written to disk, referenced by the draft, and then silently dropped at commit:
farmer told "Saved to farmOS", photo nowhere in the farm record, nothing logged.

Shared rather than copied on purpose. Two handlers independently carrying the
same block is how MUSHY-126 and MUSHY-128 ended up being the same bug twice.

Attachments are best-effort by design and that is load-bearing: a photo that
will not upload must never unwind a log that is otherwise correct. Every failure
path here returns an empty result instead of raising, and the caller decides
what to say about it.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

from farm_agent.farmos.files import upload_field_attachments

_EMPTY: dict = {"file_ids": [], "skipped": [], "failed": []}


async def upload_draft_attachments(
    client: dict, draft: dict, ctx: dict | None, asset_ids: list
) -> dict:
    """Upload a draft's captured photos to the first target asset's image field.

    Returns the upload_field_attachments envelope
    {"file_ids": [...], "skipped": [...], "failed": [...]}, or an empty one when
    there is nothing to upload, no asset to hang it on, or the path lookup fails.

    The field-scoped binary route is the only one used. The legacy file route
    415s on this farmOS.
    """
    capture_ids = draft.get("source_capture_ids")
    capture_ids = capture_ids if isinstance(capture_ids, list) else []

    paths: list[str] = []
    if ctx and callable(ctx.get("capturePathsFor")) and capture_ids:
        try:
            paths = await ctx["capturePathsFor"](capture_ids)
        except Exception:  # noqa: BLE001
            paths = []

    if not paths or not asset_ids:
        return dict(_EMPTY)

    return await upload_field_attachments(
        client, "/api/asset/fungi", asset_ids[0], "image", paths
    )
