# 2026-05-30 inoc: image vs audio vs fused extraction

Question: does adding the audio log improve extraction of the faint-pencil
notebook photo? Ran all three variants through the real extractor
(claude-sonnet-4-6) with the **raised 4MP pixel cap** (full-res 1600x900 image,
no downscale). Read-only; paid responses persisted in `responses.jsonl`.

## Ground truth (notebook page 260530)

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

## Results (8 groups, qty 3/1/2/2/1/1/1/1 = 12 in all three)

| # | truth | image-only (full-res) | audio-only | fused |
|---|---|---|---|---|
| 1 | WIN 419-5 | WIN 419-5 ✓ | WIN 419-**15** ✗ | WIN 419-5 ✓ |
| 2 | MAI 212-24 | MAI 212-24 ✓ | MAI **224-1** ✗ | MAI 212-24 ✓ |
| 3 | WIN 419-14 | WIN 419-14 ✓ | WIN 419-14 ✓ | WIN 419-14 ✓ |
| 4 | KOS 4-12-7 | KOS 412-7 ✓ | KOS 412-7 ✓ | KOS 412-7 ✓ |
| 5 | DT 228-26 | DT 228-26 ✓ | DT 228-26 ✓ | DT 228-26 ✓ |
| 6 | PB2 224-2 | PB2 224-2 ✓ | **PBT** 224-2 ✗ | PB2 224-2 ✓ |
| 7 | WIN 425-6 | WIN 425-6 ✓ | WIN 425-6 ✓ | WIN 425-6 ✓ |
| 8 | SHI 419-12 | SHI 419-12 ✓ | SHI **1912**-1 ✗ | SHI 419-12 ✓ |

Accuracy: image-only **8/8**, audio-only **4/8**, fused **8/8**. Date + species
correct in all three.

## Conclusion (overturns the prior take)

The faint-pencil misreads in the original production draft were caused by the
**1.15MP downscale**, not the model's vision. With the full-res image the
extractor reads the notebook **perfectly** -- better than audio.

Audio is the *weaker* source for the numeric batch codes: speech-to-text turned
419-5 -> "419.15", 212-24 -> "224-1", PB2 -> "PBT", 419-12 -> "1912". These are
exactly the errors in the live audio-only draft cc3944fd that made its farmOS
commit fail. Audio remains valuable for structure/species/qty and free-text
notes (e.g. "bag #2 not sterilized"), but the image owns the codes.

Fused = same as image-only here: when both are present the model trusts the
visible digits over the spoken ones. So the best path is **fuse both** -- image
for codes, audio for the narrative -- which is what the pipeline already does
when both arrive in one capture window.

Net: the downscale fix (commit b49cd98) is the real win. Re-sending the photo
now (post-fix) would extract cleanly on its own.
