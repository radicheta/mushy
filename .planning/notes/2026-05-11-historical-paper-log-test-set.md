# Historical paper-log test set — `mushdatadump`

**Where:** `/mnt/mossrock/shared/mushdatadump/` (NFS-mounted, accessible from elder-plops and booko)

**What's in it:**
- `jpeg/` — 73 JPEG scans of Mossrock's 2025 paper notebook (`IMG_3775.jpg` … `IMG_3847.jpg`, ~800KB each)
- `Mossrock Data.csv` / `Mossrock Data.xlsx` — structured extraction of the same notebook
- `mushroom_log.csv`, `mushroom_harvest.csv`, `mushroom_harvest.ods` — domain-split CSVs
- Analysis scripts: `analyze.py`, `batch_simulator.py`, `colonization_analysis.py`, `harvest_analysis.py`, `strain_analysis.py`, `survivorship_analysis.py`, `visualize_lineage.py`, `visualize_timeline.py`
- Visualizations: `lineage_major.png`, `lineage_network.png`, `timeline_batches.png`, `planning_guide.png`
- Reference docs: `README.md`, `contamination-guide.md`, `analysis_report.md`, `batch_simulator_docs.md`, `cultivation_insights_report.md`

**Why this matters for mushy-side:**

This is a ready-made benchmark dataset for the v1.6 multimodal extraction pipeline (SEED-006). Pairs raw multimodal input (the 73 JPEGs of handwritten notebook pages) with ground-truth structured extraction (the CSVs). Use it to:

1. **Evaluate the LLM-extraction agent end-to-end** — feed a JPEG, expect schema-conformant `seeding` / `harvest` / `observation` log writes that match the CSV rows. The CSVs are the labels.
2. **Validate the mushroom schema (locked 2026-05-11)** — every CSV row should round-trip into a B1–B7 asset/log structure. If a row doesn't fit, the schema needs revision (or the row is malformed; either way it's a useful signal).
3. **Seed the dev stack** — populate `:18080` with the historical data before pilot work, so the SHI-on-sawdust pilot lands against a realistic asset graph instead of an empty database.

**Schema reference:** `.planning/notes/` on the farmos repo, specifically `2026-05-09-fungi-schema-strawman.md` and the locked-decisions chat at `2026-05-11-session-chat.md`. Block-name format is `{YYMMDD}_{SPECIES3}_{SEQ}` (e.g. `260504_SHI_3`); substrate is a field on the asset, not part of the name.

**Pilot scope note (P3 reframe, locked 2026-05-11):**

The mushroom schema pilot driver is the multimodal extraction pipeline run against (a) synthetic data, (b) parsed historical paper inoc logs from `mushdatadump`, (c) existing recordings of inoculation sessions — NOT curl/drush manual entry. This dataset is asset (b).

**Found by:** radicheta-side session 2026-05-11 after the joint schema lock. Surfaced to mushy planning so future phases (farmos_agent extraction work, v1.6 pipeline scaffolding) can find it without re-searching.
