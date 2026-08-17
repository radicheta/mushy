# Recovered voice notes (whisper was down 2026-07-09 .. 2026-08-17)

`mushy-whisper-transcribe-1` was stopped 2026-07-09 16:48 UTC and never restarted
(policy `unless-stopped`, so the 08-13 boot correctly left it down). Every voice
note sent in that window was captured to disk but stored `degraded=true` with a
NULL transcript -- the audio survived, the content did not reach farmOS.

Whisper restarted 2026-08-17 04:2x UTC and these were transcribed from the
original `.m4a` files still on disk. **NOT reprocessed through the capture
pipeline** -- doing that would have messaged the farmer in the middle of the
night and minted drafts unattended. These are raw transcripts for a human to act
on.

Each is a full inoculation session. Per `project_session_is_production_shape_per_bag_is_storage`,
the session identity matters; per `project_inoc_shape_multi_parent_batch`, N children
from M parents is the normal shape here.

---

## 2026-08-16 17:26 UTC -- capture `01M05SS3PPR5HX1CENYNHVWVDQ` (+59892893012)

> Okay August 16, August 16 in oculation we're going to do four bags it's going to
> be one DT one COS and two wine caps in that order so number one DT the source is
> 663 June 6 number three DT goes into bag number one bag number one DT is 530
> number seven 530 number seven and four are going to be wine cap of course is
> 41211 wine cap

4 bags: 1x DT, 1x COS, 2x wine cap. Sources named: 663 (June 6) #3, 530 #7, 41211.

**Cross-reference:** an alerter `commit_outcome_ack` at 2026-08-16 18:12 UTC reads
"about the 2026-08-16 Inoc session (4 blocks across 3 parents): couldn't save it
because data validation failed". Same session, same shape (4 blocks / 3 parents).
So this session reached the pipeline by some other route and then FAILED to commit.
Worth confirming whether the 08-16 session exists in farmOS at all.

## 2026-08-02 17:38 UTC -- capture `01KZ1RX4K4X3DGCQY0PPD6HMRA` (+59892893012)

> inoculation session August 2, 2026 802 and I'll be doing one tub and several bags
> of compost first we're gonna do the tub source for the tub is 419 number 8 strain
> is KOS [...] next is a bag DT Delta Tango sources 42510 it's gonna be number two
> [...] Now we're moving on to wine cap. Next source is 530, number 6 [...] Number
> 3, wine cap. Next Source is 530 number 5 [...] two bags out of it. They're number
> 4 and 5 [...] two more bags numbers six and seven also wine cap 530 11 [...]
> Alright, two last bags. Source is 530 number one. Done, those are bags 8 and 9.
> This is also wine cap. And that's it for today's inoculation session.

1 tub + 9 bags. KOS (419 #8), DT (425.10) bag 2, wine cap bags 3..9 from sources
530 #6, 530 #5, 530 #11, 530 #1. Note the farmer's own correction mid-recording
("numbers five and no sorry six and seven").

## 2026-06-06 18:10 UTC -- capture `01KTF22DHTE51PQA3PFKEGN78J` (+59892893012)

> okay June 6 inoculation session June 6 2026 we're gonna be doing oats and compost
> today so first source is 212 7 [...] it's Kos KOS [...] another plate 212 number 9
> wine cap [...] next is sources 228 number 1 it's DT Delta Tango and one last agar
> plate sources 122 number 14 it's MAI maitake [...] one bag of wine cap 24 number
> 11 [...] one maitake sources 0401 number three [...] This is shiitake for 1913
> [...] two bags out of it. Next up also shiitake for 1910, April 19, number 10
> [...] Next source is wine cap 4258 [...] so we did five bags in total, four
> compost, one oats [...] next source is 412 number 6. Koss [...] one bag of
> compost, one bag of grain, and one jar of grain [...] 10 bags of compost we're
> gonna be sterilizing those compost bags 419 number 6 is the source shiitake [...]
> next source is 419 number five also shiitake [...] two bags and one jar extra for
> shiitake Wonderful, and that was it for today.

The largest of the three: KOS, wine cap, DT, MAI (maitake), SHI (shiitake) across
agar plates, bags and jars. Contains conversation with a second person, so
speaker-attribution is not reliable here.

---

## Caveats before trusting any of this

- Whisper `medium` on Uruguayan-accented English. Strain codes came through well
  (KOS, DT, MAI, wine cap, shiitake) but **numeric source IDs are the weak point**:
  "663 June 6 number three", "41211", "42510", "4258", "1913" are transcription of
  spoken digits and need eyeballing against the real block/source IDs.
- "in oculation" / "Koss" / "Delta Tango" are whisper artefacts for "inoculation" /
  "KOS" / "DT".
- Dates spoken inside the audio are the farmer's own and should win over the
  capture timestamp where they disagree.
