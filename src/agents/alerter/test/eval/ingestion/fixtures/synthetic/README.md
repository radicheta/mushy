# Synthetic Ingestion Fixtures (Phase 41 Plan 03)

CI-runnable corpus of 25 hand-crafted fixtures covering the B7 log type x
modality matrix. Driven through the ingestion harness in MOCKED mode; no paid
API calls.

## Coverage matrix

| Seq | log_type    | modality          | notes                                       |
|-----|-------------|-------------------|---------------------------------------------|
| 01  | seeding     | text-only         | clean inoc message, all fields explicit     |
| 02  | seeding     | image-only        | photo of paper-log line, no text body       |
| 03  | seeding     | text+image        | farmer writes "see photo", image has SEQ    |
| 04  | seeding     | text+audio        | mock_transcript carries the SEQ             |
| 05  | seeding     | all-three         | rich multimodal; session_id paired-shi-1    |
| 06  | seeding     | low-confidence    | block_name ambiguous; ambiguous true        |
| 07  | seeding     | bad SEQ format    | extractor should ask-back                   |
| 08  | activity    | text-only         | sterilized batch 12                         |
| 09  | activity    | text+image        | photo of autoclave                          |
| 10  | activity    | sterilize_failed  | contam came back                            |
| 11  | activity    | water             |                                             |
| 12  | activity    | cold_shock        |                                             |
| 13  | activity    | archive_spent     |                                             |
| 14  | activity    | contam            | needs photo                                 |
| 15  | input       | text-only         | bran + gypsum                               |
| 16  | input       | image-only        | photo of recipe sheet                       |
| 17  | observation | text-only         | pins emerging                               |
| 18  | observation | text+image        | colonizing well; session_id paired-obs-1    |
| 19  | observation | image-only        | photo of contam                             |
| 20  | observation | text+audio        |                                             |
| 21  | harvest     | text-only         | single-block harvest                        |
| 22  | harvest     | text-only         | multi-block harvest                         |
| 23  | harvest     | text+image        | photo of weighed harvest                    |
| 24  | harvest     | all-three         |                                             |
| 25  | seeding     | text-only         | edge: future-dated message                  |

## How to add a fixture

1. Make a new subdir `fixtures/synthetic/<NN>-<log_type>-<modality>/`.
2. Drop an `input.json` (Signal envelope: sender, body, ts, optional `mock_transcript`, optional `attachments[]`).
3. Drop an `expected.json` (target draft fields: `type`, `requiredFields`, `fields`, `ambiguous`, optional `session_id`, optional `provenance`).
4. Drop attachments as `attachment.png` / `attachment.m4a` (symlinks to `../../test-fixtures/` placeholders or to real files outside the repo).
5. Re-run `cd src/agents/alerter && npm run test:eval-ingestion`; the synthetic.test.js auto-discovers it.

## Session_id naming convention

Paired-session fixtures share a `session_id` key in their `expected.json`. Used
by the cross-stream consistency scorer (Plan 06). Two ship in v1.7:
- `paired-shi-1` (synthetic fixture 05; paper-log + audio peers via Plans 04 + 05)
- `paired-obs-1` (synthetic fixture 18; same pattern)
