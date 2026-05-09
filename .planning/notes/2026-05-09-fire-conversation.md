# 2026-05-09 — Fire conversation (post-deploy)

**Setting:** by the fire, after Phase 30+31 deploy + UAT. Stormy/cold day.

**Participants:**
- Farmer #1 (already capturing today in `2026-05-09-farmer-1-quotes.md`)
- Farmer #2 (new voice today)
- Zoy (dev team — farmOS side)
- radicheta (mushy side)
- Boss (present but not expected to participate)

**Capture format:** verbatim quotes per speaker + minimal context. Parse / promote / file later. If a topic was already raised in farmer-1-quotes.md (Q1–Q6) or in the visit plan discussion list, cross-reference.

---

## Discussion topic queue (pre-loaded)

From visit plan + farmer-1 morning quotes + today's bug findings:

- **A. Forced-condensation operational fit** — when does farmer use it? default duration 15 min the right ballpark? (visit plan #1, Phase 31 force-condensation just shipped)
- **B. VPD recommendation: Option B** (expose VPD as derived telemetry, defer closed-loop control) — get farmer agreement (vpd-and-water-mass-observer-research.md)
- **C. First real Phase 30 schedule profile** — what time-of-day windows do they actually want? (visit plan #4, Phase 30 just shipped)
- **D. Camera coverage gap** — what to point a 2nd camera at (visit plan #3)
- **E. Outside weather data** (Q6 today) — confirm worth a small follow-up phase, agree API-vs-sensor scope
- **F. Chip color cleanup + dead HUMIDIFIER chip** (Q4/Q5) — preview proposed semantic palette
- **G. Power-bank UPS** (SEED-007) — share today's storm-day blackout incident data, prioritize?
- **H. 1-second alert noise debounce** (Q1) — agree threshold (≥30s? ≥60s?)
- **I. Farmer-2 onboarding context** — anything specific to their role / what they need from mushy
- **J. Zoy / farmOS-side topics** — any blockers from farmOS proxy work, SEED-002 event writer, multi-farmer routing (Phase 999.20)?

---

## DECISION-1 (group agreement) — Next major milestone is freeform farm-event data entry via Signal

**Speakers:** consensus across the group (farmer #1, farmer #2, zoy, radicheta)

**radicheta-paraphrased:**
> "Agreement is: next major milestone is free-form data entry of farm events through Signal stream."

**What this means:**
- This is the **trigger condition for SEED-006 firing**. SEED-006 ("Farmer freeform stream → automatic farmOS bookkeeping") was filed 2026-05-08 with trigger condition: "Next major milestone (v1.6+) — agentic / farmer-UX themed milestone." That trigger has now been verbally locked at the fire today.
- Implies v1.6 is shaped around: multimodal Signal intake (text + audio + photo), an extraction agent that drafts farmOS event candidates, a low-friction farmer confirmation UX, and farmOS write integration.
- Composes with SEED-002 (FarmOS event writer from captured Signal content), SEED-003 (Farmer app "Mission Control" section), and the farmOS-proxy architecture (memory `project_phase18_22_farmos_proxy_architecture`).

**Action items downstream of this decision** (not for tonight, just naming them):
- Promote SEED-006 from `seeds/` to active backlog when v1.5 closes
- Start `/gsd-new-milestone v1.6` scoping conversation when ready
- The cross-side farmOS coordination (zoy on the farmOS write path, radicheta on the Signal/agent side) is the natural workstream split
- Pre-requisites: SEED-002 needs to ship first (or at least produce ≥1 month of text-only event-writer accuracy data per SEED-006 notes) — possibly do that as a v1.5.x.y bridge milestone, or fold its first iteration into v1.6 itself
- Photo intake adds privacy/storage shape unlike text-only (per SEED-006 notes) — needs a retention story before launch

**Cross-references to memories that just became more load-bearing:**
- `project_co2_unexpected_win` — CO2 was the v1.0 unexpected hit; bias future agent suggestions toward sensor-aware framing
- `project_farmos_people_directory_seed` — farmOS people dir as identity source for "who sent what" (multi-farmer routing)
- `project_phase18_22_farmos_proxy_architecture` — proxy pattern this writer extends
- `project_v14_cv_milestone_planned` — the v1.4 CV work supplies vision capabilities for photo intake

---

## DECISION-2 — UI work split: zoy team vs radicheta side

**Context:** I had proposed 4 UI threads + a camera coverage open question. Group walked through them. Outcomes:

| Thread | Owner | Status / Note |
|---|---|---|
| **Chip-row palette + dead HUMIDIFIER chip** (Q4 + Q5) | **radicheta** | Lives on OpenMCT / Mission Control side, not farmer-app. Historic reason — these chips are the OpenMCT engineer-view, never migrated to farmer-app. Q4/Q5 cleanup is a mushy-side fix, not zoy-team. |
| **Phase 30 schedule UI** (farmer-app surface for `schedule_windows`) | **zoy team** | ✅ Accepted. Farmer-facing time-of-day mode editor goes in farmer-app. |
| **Phase 31 experiment-trigger surface** | **zoy team (eventually)** | Trigger button + countdown + history is fine to ship, BUT visual-evidence overlay (close-up photos of condensation/evaporation outcome) needs a **macro lens**, **not on hand yet**. Defer the photo-evidence overlay; ship pure button + history first. |
| **Outside weather card** | **zoy team + radicheta** | ✅ Yes for farmer-app — but ALSO put it in Mission Control. Weather context helps both farmer (operational) and engineer (debugging) views. Ingest once, display twice. |

**Bonus open item:**
- **Camera coverage gap** (visit plan #3) — gated on **macro lens** arriving. No second-camera install unblocked until then. **Macro lens is the single hardware item gating two UI deliverables** (camera coverage + Phase 31 photo overlay). Worth tracking as a procurement / wait-state with its own follow-up trigger ("when macro lens arrives → unblock camera coverage AND Phase 31 photo overlay").

---

## DECISION-3 — farmOS rollout sequencing + the no-bookkeeping-tax principle

**Speakers:** group consensus, with a strong principle from farmer/radicheta side.

**Step-by-step decisions on the proposed sequencing:**

| Step | Decision | Reason |
|---|---|---|
| 1. Schema design session | ✅ ACCEPTED — **radicheta + zoy** session on the farmos project to design schema | Joint design with farmer ground-truth via existing artifacts, not workshops |
| 2. Manual entry pilot (1-2 weeks) | ❌ **REJECTED** | Adds tasks to farmers. "ouch painful. no new tasks for farmers please, they already busy farming, we're supposed to make life easier" |
| 3. SEED-002 text-only writer | ✅ ACCEPTED | Builds on existing Phase 25 captured Signal stream — no new farmer task |
| 4. v1.6 = SEED-006 multimodal | ✅ ACCEPTED | Already locked as DECISION-1 |

**Substituting Step 2 with real-data + synthetic-data approach:**
The farmer's hard pushback on manual entry triggered an alternative path that's actually BETTER for SEED-002/006 readiness. Instead of asking farmers to enter events by hand:

- **Existing artifacts the farmers already produce:**
  - **Inoculation log scans** — handwritten/printed paper logs already kept by farmers as part of normal work
  - **Recordings of inoculation sessions** — audio/video already captured during these sessions
- **Synthetic data** — LLM-generated examples to validate schema shape and writer-pipeline edge cases without any farmer time

**This actually accelerates v1.6 readiness rather than delaying it,** because:
1. Inoc log scans → OCR → event extraction is the SAME pipeline shape as SEED-006's multimodal photo intake. We're testing the v1.6 multimodal capability with real existing data while the schema is being designed.
2. Recorded inoculation sessions → Whisper transcribe (already shipped in Phase 25 stack) → event extraction is the SAME pipeline shape as SEED-006's audio intake.
3. Synthetic data covers schema edge-cases (rare event types, malformed inputs) without waiting for them to occur in real data.

So the revised pipeline path:
- Schema design (radicheta + zoy on farmos repo)
- Test SEED-002 writer against scans + recordings + synthetic data
- v1.6 SEED-006 lands with the multimodal shape already validated

---

## CORE PRINCIPLE (north-star) — No bookkeeping tax on farmers

**Verbatim from the conversation (radicheta-side, with farmer agreement):**
> "no new tasks for farmers please, they already busy farming, we're supposed to make life easier"

**What this means for all future planning:**
- Any phase that proposes "ask the farmer to enter X by hand" should be rejected by default. The burden of proof is on showing why this is necessary AND why it can't be replaced by extracting from artifacts the farmer already produces.
- Phases that REMOVE existing farmer bookkeeping tax (e.g. SEED-006 replacing every farmOS form) are first-class. Phases that ADD to it are last-class.
- This is the explicit antithesis of `feedback_no_sparklines` ("annotated event timeline preferred")'s underlying logic — it's not just about UI preference, it's about the farmer's time being the most expensive resource in the system.
- This composes with `user_operator_and_grower` (farmer-as-operator preference) and the `project_co2_unexpected_win` lesson (the unexpected v1.0 hit was a passive-observation feature, not an active-input one).

**Saved as feedback memory: `feedback_no_farmer_bookkeeping_tax.md`** so future planning sessions reference it.

---

## DECISION-4 — VPD path: Option B locked, with water mass exposed too

**Speakers:** group consensus after radicheta presentation of `2026-05-09-vpd-and-water-mass-observer-research.md` Options A/B/C.

**Verbatim:**
> "B. let's start by having VPD and estimated water mass in MC"

**What this locks in:**
- **Option B from the research note** is the next step on this thread.
- **Both** VPD and estimated water mass go into Mission Control (OpenMCT) as derived telemetry — not just VPD.
- No fc_controller changes. PID kernel stays byte-identical to Phase 27 (memory `project_phase28_d10_target_semantics`).
- Regime A psychrometric calc only. Regimes B (actuator-integral past saturation) and C (camera macro) stay deferred.
- SEED-004 (closed-loop VPD) stays dormant — no controller setpoint change.
- SEED-005 partial implementation now justified — regime A only.

**Implementation shape (for the next planning conversation, NOT tonight):**

This becomes a small phase, naturally fitting into the existing 999.27 placeholder (`fc_metrics` bridge-side derivation). Concretely:

- New bridge-side module `fc_metrics` (or extend existing) that subscribes to `fc.temperature` + `fc.humidity` and publishes:
  - `fc1/derived/vpd_kpa` — Magnus formula, Float32, 0.5 Hz (matches sensor cadence)
  - `fc1/derived/water_mass_g` — `(RH/100) · P_sat(T) · M_water · V_chamber / (R · T_K)`, Float32, 0.5 Hz
- Both sink to Timescale via existing telemetry insert path.
- Both visible in OpenMCT next to RH and temp.
- Replay-aware (per memory `project_999_27_bridge_side_derivation`) — recompute on backfilled samples; idempotent.
- Configurable `V_chamber` parameter — needs the actual chamber free-air volume measured (open question #1 in the research note §6).

**Cross-references that just shifted from "speculative" to "load-bearing":**
- `project_999_27_bridge_side_derivation` — phase placeholder now has a concrete first deliverable
- `project_dynamic_rh_target_groundwork` — RH(t) work composes; VPD is a richer setpoint surface than RH(t) alone
- `project_alerter_is_ws_only` — alerter doesn't see backfilled rows, but VPD/water_mass are pure functions of T+RH so any aggregation is downstream-only
- `project_phase26_sht30_happy_path_unverified` — SCD41 RH clipping at 100% noted; water_mass observer using SHT30 as primary (more accurate per memory) is correct sensor choice
- SEED-005 — regime A satisfied by this work; regimes B/C parked for v1.6+ (post-macro-lens)

**Pre-requisite to gather (open question #1 from research note):**
- **Free-air volume `V_chamber`** — measure or derive from inner dimensions minus substrate trays. Needed to make `water_mass_g` a real number rather than a placeholder.

---

## DECISION-5 — Three room-locked answers + a global alerter floor

**Q1 — alert noise (resolved):**
> "A LOT LESS NOISE please. farmers don't care if fc1 was offline for 2 mins! Let's not report any out of band events less than 15min long"

- **Global rule: do not fire ANY out-of-band alert for events lasting less than 15 minutes.**
- Applies across all sensor-offline + threshold-cross alerts (CO2, RH, temp, Pi-reachable, sensor-stale, etc).
- This is a global floor, not per-channel. Per-channel can have HIGHER floors but never lower.
- Replaces the band-aid `ALERT_SENSOR_OFFLINE_MIN=1440` from 2026-05-06 (memory `project_alerter_watchdog_quiet_topic_bug`) with a real principled threshold.
- **Implementation:** alerter `.env` change (`ALERT_OOB_FLOOR_MIN=15` or similar), restart alerter container. ~30 seconds. Could happen tonight.
- Composes with the Q5 broken HUMIDIFIER chip fix and the Q4 chip-color cleanup as part of "make signal/noise ratio match farmer reality."

**A — Phase 31 default duration (resolved):**
> "let's do force 15min yes"

- **Default `duration_minutes` for `/force-condensation` and `/force-evaporation` is 15.**
- Cap stays at 120 (per Phase 31 hard cap). Range is now [1, 120] with default 15.
- Implementation: alerter Signal command parser default + bridge POST default if body omits `duration_minutes`. Small follow-up to land alongside other Phase 31 polish.

**C — Phase 30 schedule profile (resolved-as-deferred):**
> "we want to keep it manual control for now"

- **Phase 30 (`schedule_windows`) ships as opt-in infrastructure ONLY.** Default empty schedule (already the case — `schedule_windows: "[]"`).
- No automatic mode transitions configured at this time. Farmer keeps manually toggling modes via existing path.
- The infrastructure is in place for the day they want to switch on (a colonization→fruiting auto-transition, for instance), but no operational use today.
- Implication: **no farmer-app schedule UI urgency** either. zoy's Phase 30 schedule UI task can move down the priority list — useful eventually but not blocking.
- This is a clean "feature exists, dormant, ready when needed" outcome.

---

## DECISION-6 — Provision a $5/mo public VPS as multi-purpose infrastructure

**Trigger:** beta-tester WireGuard access surfaced as a need. radicheta initially framed it as "VPS hub vs ISP port-forward". Group asked "can we justify $5/mo by stacking other things on it?" → yes.

**Decision:** **Provision a Hetzner CX22 (~$4.50/mo, Nuremberg region) as a public-facing infrastructure box.** Stack four workloads on it.

**STATUS UPDATE (2026-05-09 same session):** ✅ **Box provisioned at Hetzner Nuremberg.** radicheta picked Nuremberg over Ashburn after seeing it was the cheaper of the two regions in practice. ~200 ms latency to Uruguay (vs ~120 ms Ashburn) — non-issue for our workload. Box is live; next steps are workload installs.

**Why provisioned today (ahead of install):** opportunistic — farmer #2 had a credit card on hand at the fire. Took the chance to lock in the box; install steps (WG hub → monitoring → backups) will run in a separate dedicated autonomous session, not under time pressure.

**Why Hetzner over Vultr/DO** (locked after follow-up comparison):
- 2 vCPU / 4 GB RAM / 40 GB SSD / 20 TB bw at ~$4.50, vs Vultr/DO 1 vCPU / 1 GB / 25 GB / 1 TB at $5. Roughly 2× the resources for the same price.
- Latency cost: ~120 ms (Ashburn) vs ~30 ms (Vultr/DO São Paulo) — acceptable for our use case (WG + backups + monitoring; no live interactive workload). One extra round-trip on WG handshake; ongoing UDP relay unaffected.
- Resource headroom matters more than latency for the stack we're building — uptime-kuma + borgbackup + heartbeat + WG fits comfortably on 4 GB; would be snug on 1 GB.

**Stack (in suggested implementation order):**

1. **WireGuard hub** — primary justification. Public static IP terminates beta-tester peers + can backstop fc1↔elder-plops if home WAN dies. Resolves the parked architecture from `project_fc1_link_architecture_options` and `project_fc1_cgnat_confirmed`.
2. **Outside-in monitoring** (uptime-kuma or healthchecks.io self-hosted) — pings fc1, elder-plops, farmer-app, openmct, signal-cli FROM OUTSIDE the home network. **Killer combo with #4.** Catches the failure mode that the 2026-05-07 incident hit: home network reachable LAN-only but invisible to the world.
3. **Heartbeat receiver + outage-alert relay** — fc1/elder-plops POST hourly heartbeat; VPS alerts (Signal/email/SMS) when pings stop. When home network dies, the in-house alerter is also dead — VPS is the ONLY thing that can scream. Direct mitigation for `project_2026_05_07_fc1_reboot_unrecoverable` (11h offline, nobody knew).
4. **Offsite backup target** (borgbackup or restic) — encrypted incremental backups pushed nightly from elder-plops. Mushy Timescale ~1.2 GB; daily diff ~200-500 MB compressed; ~30-90 days retention fits in 20 GB. farmOS db too. Mitigates `project_2026_05_03_ssd_failure` (SD failure recovery).

**Resource budget (Hetzner CX22 ~$4.50: 2 vCPU / 4 GB RAM / 40 GB SSD / 20 TB bw):**

| Workload | Resource cost |
|---|---|
| WG hub | <1% CPU, ~10 MB RAM |
| Uptime-kuma | <100 MB RAM, low CPU |
| Heartbeat + alert relay | Negligible |
| Backups | Disk-bound (~20 GB usable after OS); low CPU; nightly burst on bandwidth |

Headroom: comfortable. Could add a fifth workload later (e.g. private Docker registry, status page mirror) if useful.

**Critical risk acknowledgement:**
- Single point of failure for the four hosted workloads — yes, but **none of those is chamber control.** fc1 keeps growing mushrooms even if VPS dies. Worst case during VPS outage: no offsite backups for a day, no outside-in monitoring, beta-testers can't reach mushy. Chamber unaffected.
- Adds an external attack surface. Standard hardening (UFW, key-only SSH, fail2ban, automatic security updates) mitigates. WG and SMTP are the only public-facing services besides SSH; both well-understood.

**Implementation sequence (suggested):**

1. Provision VPS, harden, install WG (~1 hour)
2. Onboard first beta-tester to validate (~30 min)
3. Add uptime-kuma + heartbeat receiver (~1 hour)
4. Wire elder-plops nightly borgbackup target (~1 hour)
5. Document runbook for adding new beta-tester peers (~15 min)

Total: ~4 hours work spread across 1-2 sessions. Could be a single phase, or split into "VPS infra + WG" first phase and "backups + monitoring" second phase.

**Open questions for the day this gets planned:**
- **Region** — Hetzner Ashburn (closest to Uruguay) is the default; confirm before provisioning. Falkenstein/Helsinki/Nuremberg add ~50 ms but might fit other constraints.
- **Beta-tester scope** — full mesh (can hit fc1) vs proxy-only (read-only farmer-app surface)? Affects firewall rules
- **Backup tooling** — borgbackup (battle-tested, append-only) vs restic (newer, more flexible) — cheap to defer
- **Status page visibility** — uptime-kuma can publish public status pages. Want one? Audience?

**Memories that just shifted from "speculative" to "load-bearing":**
- `project_fc1_link_architecture_options` — VPS path is now the chosen path, not a fallback
- `project_fc1_cgnat_confirmed` — VPS is the workaround we're now committing to
- `project_2026_05_07_fc1_reboot_unrecoverable` — outside-in monitoring directly addresses this incident class
- `project_2026_05_03_ssd_failure` — offsite backups directly mitigate SD/SSD failure recovery
- `project_blackout_2026_05_02_fc_core_stuck` — heartbeat receiver would have caught this within minutes
- SEED-007 (power-bank UPS) composes — UPS keeps fc1 alive through short blackouts; VPS sees longer outages

---

## Quotes (chronological)

