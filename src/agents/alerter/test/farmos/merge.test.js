'use strict';

// Phase 51 UPSERT-03: unit coverage of pure mergeAssetFields rule table.
// Cross-ref: 51-SPEC.md UPSERT-03; 51-CONTEXT.md "Notes-field representation".

const { mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR } = require('../../src/farmos/merge');

function asset(overrides = {}) {
  const base = {
    id: 'a1',
    type: 'asset--fungi',
    attributes: { name: 'X', notes: { value: '', format: 'plain_text' } },
    relationships: {
      parent: { data: [] },
      qr_codes: { data: [] },
      farm_id_tag: { data: [] },
      fungi_type: { data: null },
      fungi_xing: { data: null },
    },
  };
  const out = { ...base, ...overrides };
  out.attributes = { ...base.attributes, ...(overrides.attributes || {}) };
  out.relationships = { ...base.relationships, ...(overrides.relationships || {}) };
  return out;
}

describe('mergeAssetFields (Phase 51 UPSERT-03)', () => {
  it('set-union on relationships.parent.data preserves existing-first order', () => {
    const existing = asset({
      relationships: { parent: { data: [{ id: 'p1', type: 'asset--fungi' }] } },
    });
    const incoming = asset({
      relationships: { parent: { data: [{ id: 'p2', type: 'asset--fungi' }] } },
    });
    const { merged, conflicts } = mergeAssetFields(existing, incoming);
    expect(merged.relationships.parent.data).toEqual([
      { id: 'p1', type: 'asset--fungi' },
      { id: 'p2', type: 'asset--fungi' },
    ]);
    expect(conflicts).toEqual([]);
  });

  it('set-union dedup on relationships.parent.data drops duplicate ids', () => {
    const existing = asset({
      relationships: {
        parent: {
          data: [
            { id: 'p1', type: 'asset--fungi' },
            { id: 'p2', type: 'asset--fungi' },
          ],
        },
      },
    });
    const incoming = asset({
      relationships: {
        parent: {
          data: [
            { id: 'p2', type: 'asset--fungi' },
            { id: 'p3', type: 'asset--fungi' },
          ],
        },
      },
    });
    const { merged, conflicts } = mergeAssetFields(existing, incoming);
    expect(merged.relationships.parent.data.map((r) => r.id)).toEqual(['p1', 'p2', 'p3']);
    expect(conflicts).toEqual([]);
  });

  it('throws IdentityMutationError when attributes.name changes', () => {
    const existing = asset({ attributes: { name: 'X' } });
    const incoming = asset({ attributes: { name: 'Y' } });
    let err;
    try {
      mergeAssetFields(existing, incoming);
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(IdentityMutationError);
    expect(err.field).toBe('name');
    expect(err.existing).toBe('X');
    expect(err.incoming).toBe('Y');
  });

  it('scalar singleton equal is a noop (no conflict, value preserved)', () => {
    const existing = asset({
      relationships: { fungi_type: { data: { id: 'ft-shi', type: 'taxonomy_term--fungi_type' } } },
    });
    const incoming = asset({
      relationships: { fungi_type: { data: { id: 'ft-shi', type: 'taxonomy_term--fungi_type' } } },
    });
    const { merged, conflicts } = mergeAssetFields(existing, incoming);
    expect(conflicts).toEqual([]);
    expect(merged.relationships.fungi_type.data.id).toBe('ft-shi');
  });

  it('scalar singleton differ surfaces conflict and retains existing', () => {
    const existing = asset({
      relationships: { fungi_type: { data: { id: 'ft-shi', type: 'taxonomy_term--fungi_type' } } },
    });
    const incoming = asset({
      relationships: { fungi_type: { data: { id: 'ft-koy', type: 'taxonomy_term--fungi_type' } } },
    });
    const { merged, conflicts } = mergeAssetFields(existing, incoming);
    expect(conflicts.length).toBe(1);
    expect(conflicts[0]).toEqual({
      field: 'fungi_type',
      existing: 'ft-shi',
      incoming: 'ft-koy',
      kind: 'scalar_conflict',
    });
    // merged retains existing (never silent overwrite — T-51-03)
    expect(merged.relationships.fungi_type.data.id).toBe('ft-shi');
  });

  it('notes dedup splits on STABLE_NOTES_SEPARATOR and appends only new entries', () => {
    const existing = asset({
      attributes: { name: 'X', notes: { value: 'entry_A\n---\nentry_B', format: 'plain_text' } },
    });
    const incoming = asset({
      attributes: { name: 'X', notes: { value: 'entry_B\n---\nentry_C', format: 'plain_text' } },
    });
    const { merged } = mergeAssetFields(existing, incoming);
    expect(merged.attributes.notes.value).toBe('entry_A\n---\nentry_B\n---\nentry_C');
    expect(STABLE_NOTES_SEPARATOR).toBe('\n---\n');
  });

  it('STUB_BACKFILL_MARKER text survives merge unstripped', () => {
    const existing = asset({
      attributes: {
        name: 'X',
        notes: { value: 'STUB - awaits 2025-paper-scan backfill', format: 'plain_text' },
      },
    });
    const incoming = asset({
      attributes: {
        name: 'X',
        notes: { value: 'real inoc 2026-05-22', format: 'plain_text' },
      },
    });
    const { merged } = mergeAssetFields(existing, incoming);
    expect(merged.attributes.notes.value).toContain('STUB - awaits 2025-paper-scan backfill');
    expect(merged.attributes.notes.value).toContain('real inoc 2026-05-22');
  });
});
