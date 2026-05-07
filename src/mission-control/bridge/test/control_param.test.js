// Phase 28 plan 28-01 — Wave 0 RED scaffolds for MODE-05 Layer 1
// (POST /control/param → rclnodejs SetParameters via /fc_controller/set_parameters).
//
// Each todo lands in plan 28-05. The exact rclnodejs request shape is locked
// in 28-01-SPIKE.md §A; toParamValue() table is keyed on declared param type.
//
// See:
//   - .planning/phases/28-.../28-RESEARCH.md §Pattern 4 + §Pitfall 4
//   - .planning/phases/28-.../28-CONTEXT.md D-17
//   - .planning/phases/28-.../28-01-SPIKE.md §A (rclnodejs shape)

describe('POST /control/param — MODE-05 Layer 1', () => {
    test.todo('happy path: active_mode=pinning → SetParameters called with {type:4,string_value:"pinning"}');
    test.todo('rejects non-allowlisted param humidifier_pin → 400');
    test.todo('rejects out-of-range pid_kp=99 → 400 (allowlist range bound)');
    test.todo('batches band_low+band_high in one SetParameters call when both present in body.params (Pitfall 4)');
    test.todo('coerces JS Number to DOUBLE (type:3) for band_low, STRING (type:4) for active_mode, BOOL (type:1) — toParamValue table coverage');
});
