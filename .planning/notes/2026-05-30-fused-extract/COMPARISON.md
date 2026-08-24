# 2026-05-30 inoc: image vs audio vs fused extraction

Question: does adding the audio log improve extraction of the faint-pencil
notebook photo? Ran all three variants through the real extractor
(claude-sonnet-4-6) with the **raised 4MP pixel cap** (full-res 1600x900 image,
no downscale). Read-only; paid responses persisted in `responses.jsonl`,
console in `summary.txt`.

## Ground truth (notebook page 260530, as read by Opus from the photo)

| SEQ | species | parent |
|----|---|---|
| 1-3 | WIN | 419-5 |
| 4 | MAI | 212-24 |
| 5-6 | WIN | 419-14 |
| 7-8 | KOS | 4-12-7 |
| 9 | DT | 228-26 |
| 10 | PB2 | 224-2 |
| 11 | WIN | 425-6 |
| 12 | SHI | 419-12 |

12 blocks, 8 parents.

## Actual results (verbatim from responses.jsonl)

### image-only (full-res, post-downscale-fix) -- POOR
- event_date = **2026-05-02** (wrong)
- 9 groups, all qty 1 (multi-qty structure lost)
- parents: **all `NEEDS_SEQ`** (did not read the parent-batch column at all)
- species: WIN WIN WIN WIN **OYS** DT **OYS** WIN **OYS** (OYS noise; truth has
  no OYS)

### audio-only -- GOOD
- event_date = 2026-05-30 (correct)
- 9 groups, structure correct (qty 2+1 / 1 / 2 / 2 / 1 / 1 / 1 / 1 = 12)
- 1: WIN 419-**15** (q2), 2: WIN 419-15 (q1), 3: MAI 224_21224, 4: WIN 419-14,
  5: KOS 412-7, 6: DT 228-26, 7: **PBL** 224-2, 8: WIN 425-6, 9: SHI 419-12

### fused image+audio -- BEST (only complete draft)
- event_date = 2026-05-30 (correct), **needs_input cleared** (no ask-back
  needed -- the other two still wanted the starting SEQ)
- 1: WIN 419-15 (q2), 2: WIN 419-15 (q1), 3: MAI 260221_MAI_4, 4: WIN 419-14,
  5: KOS 412-7, 6: DT 228-26, 7: **PBT** 224-2, 8: WIN 425-6, 9: SHI 419-12

## Conclusion (audio is the stronger source here -- opposite of my first guess)

Adding the audio **clearly improves extraction**. On this photo the full-res
image alone was *worse* than expected: this run it failed to read the parent
column (everything `NEEDS_SEQ`), put the wrong month (May 2), and emitted OYS
noise. The raised pixel cap removes a real failure mode, but it did **not** by
itself make the image a reliable reader of this faint-pencil page.

Audio carried the structure (the spoken "two bags and one jar" -> qty 2+1), the
correct date, and most batch codes. Fused was the only variant that produced a
**complete** draft (needs_input cleared), combining audio structure with the
image.

### One genuine source conflict (not a model error)
Rows 1-3 parent: **audio says 419-15** ("April 19, number 15"), the **notebook
reads 419-5**. Santi spoke a different number than he wrote. This must be a
farmer double-check, not an auto-pick.

### Remaining soft spots in fused
- MAI parent rendered `260221_MAI_4` (truth 212-24) -- still shaky
- PB2 came out `PBT`/`PBL` (Portobello) -- species-code normalization gap; these
  out-of-vocab codes are what made the live audio draft cc3944fd fail to commit
- The `2602..` prefix is the year-context shim prepending 2026 to spoken codes

### Takeaways
1. Audio materially helps; the pipeline already fuses both when they arrive in
   one capture window -- the practical fix is to send the voice note and photo
   together (or within the same draft window) rather than hours apart.
2. The PB2->PBT/PBL and MAI parent issues are species/parent normalization, not
   resolution by image vs audio -- worth a separate look (and likely the commit
   blocker for cc3944fd).
3. Earlier claim that the downscale was the *whole* story is wrong: it was *a*
   real loss, but image-only is still an unreliable reader of this page.
