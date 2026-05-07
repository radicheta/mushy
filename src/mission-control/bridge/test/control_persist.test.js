// Phase 28 plan 28-01 — Wave 0 RED scaffolds for MODE-05 Layer 2
// (POST /control/persist → overlay yaml on fc1).
//
// Each todo lands in plan 28-06. Layer 2 transport (SSH-from-bridge OR fc_buffer
// HTTP relay) is locked in 28-01-SPIKE.md §B/§C — the last todo's wording stays
// generic until the spike picks the path.
//
// See:
//   - .planning/phases/28-.../28-RESEARCH.md §Pitfall 3 (overlay path, perms)
//   - .planning/phases/28-.../28-CONTEXT.md D-17, D-19
//   - .planning/phases/28-.../28-01-SPIKE.md §B (transport)

describe('POST /control/persist — MODE-05 Layer 2', () => {
    test.todo('writes overlay yaml with fc_controller.ros__parameters tree');
    test.todo('atomic-rename: writes .tmp then renames; previous version preserved as .bak');
    test.todo('rejects path traversal in param name (e.g. modes.../etc/passwd)');
    test.todo('transport: SSH if D-17 Layer 2 SSH path verified, else fc_buffer HTTP relay per spike');
});
