'use strict';

// Phase 51 UPSERT-03: pure merge for asset--fungi fields. Zero client / network deps.
// Rules: array-ref → set-union by id; identity scalars (name, type) → throw;
// non-identity scalars → equal=noop, differ=conflict; notes → split-dedup-join.
// Cross-ref: 51-SPEC.md UPSERT-03; 51-CONTEXT.md "Notes-field representation".

const STABLE_NOTES_SEPARATOR = '\n---\n';

const ARRAY_REF_FIELDS = ['parent', 'qr_codes', 'farm_id_tag'];
const SCALAR_REL_FIELDS = ['fungi_type', 'fungi_xing'];
const SCALAR_ATTR_FIELDS = ['status'];

class IdentityMutationError extends Error {
  constructor(field, existing, incoming) {
    super('identity_mutation:' + field);
    this.name = 'IdentityMutationError';
    this.field = field;
    this.existing = existing;
    this.incoming = incoming;
  }
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function unionArrayRef(existingData, incomingData) {
  const existingArr = Array.isArray(existingData) ? existingData : [];
  const incomingArr = Array.isArray(incomingData) ? incomingData : [];
  const byId = new Map();
  for (const ref of existingArr) {
    if (ref && ref.id != null && !byId.has(ref.id)) byId.set(ref.id, ref);
  }
  for (const ref of incomingArr) {
    if (ref && ref.id != null && !byId.has(ref.id)) byId.set(ref.id, ref);
  }
  return Array.from(byId.values());
}

function mergeNotes(existingNotes, incomingNotes) {
  const existingValue = (existingNotes && existingNotes.value) || '';
  const incomingValue = (incomingNotes && incomingNotes.value) || '';
  const sep = STABLE_NOTES_SEPARATOR;
  const existingEntries = existingValue.split(sep).map((s) => s.trim()).filter((s) => s.length > 0);
  const incomingEntries = incomingValue.split(sep).map((s) => s.trim()).filter((s) => s.length > 0);
  const merged = existingEntries.slice();
  for (const entry of incomingEntries) {
    if (!merged.includes(entry)) merged.push(entry);
  }
  return { value: merged.join(sep), format: 'plain_text' };
}

function mergeAssetFields(existing, incoming) {
  // Identity check first — never permit name or bundle/type mutation.
  const existingName = existing && existing.attributes ? existing.attributes.name : undefined;
  const incomingName = incoming && incoming.attributes ? incoming.attributes.name : undefined;
  if (incomingName != null && existingName !== incomingName) {
    throw new IdentityMutationError('name', existingName, incomingName);
  }
  if (incoming && incoming.type != null && existing && existing.type !== incoming.type) {
    throw new IdentityMutationError('type', existing.type, incoming.type);
  }

  const merged = deepClone(existing);
  const conflicts = [];

  // Array-ref set-union by id.
  if (incoming && incoming.relationships) {
    for (const field of ARRAY_REF_FIELDS) {
      const incomingRel = incoming.relationships[field];
      if (!incomingRel) continue;
      const existingRel = (merged.relationships && merged.relationships[field]) || { data: [] };
      const unioned = unionArrayRef(existingRel.data, incomingRel.data);
      if (!merged.relationships) merged.relationships = {};
      merged.relationships[field] = { data: unioned };
    }
  }

  // Scalar singleton relationships — null=take, equal=noop, differ=conflict.
  if (incoming && incoming.relationships) {
    for (const field of SCALAR_REL_FIELDS) {
      const incomingRel = incoming.relationships[field];
      if (incomingRel === undefined) continue;
      const incomingId = incomingRel && incomingRel.data ? incomingRel.data.id : null;
      const existingRel = merged.relationships ? merged.relationships[field] : undefined;
      const existingId = existingRel && existingRel.data ? existingRel.data.id : null;
      if (existingId == null && incomingId != null) {
        merged.relationships[field] = { data: incomingRel.data };
      } else if (existingId != null && incomingId != null && existingId !== incomingId) {
        conflicts.push({
          field,
          existing: existingId,
          incoming: incomingId,
          kind: 'scalar_conflict',
        });
        // merged retains existing (never silent overwrite — T-51-03).
      }
      // equal or incoming-null → noop
    }
  }

  // Scalar attributes (non-identity).
  if (incoming && incoming.attributes) {
    for (const field of SCALAR_ATTR_FIELDS) {
      const incomingVal = incoming.attributes[field];
      if (incomingVal === undefined) continue;
      const existingVal = merged.attributes ? merged.attributes[field] : undefined;
      if (existingVal == null && incomingVal != null) {
        merged.attributes[field] = incomingVal;
      } else if (existingVal != null && incomingVal != null && existingVal !== incomingVal) {
        conflicts.push({
          field,
          existing: existingVal,
          incoming: incomingVal,
          kind: 'scalar_conflict',
        });
      }
    }
  }

  // Notes — split-dedup-join, marker-preserving.
  if (incoming && incoming.attributes && incoming.attributes.notes !== undefined) {
    merged.attributes.notes = mergeNotes(
      merged.attributes && merged.attributes.notes,
      incoming.attributes.notes
    );
  }

  return { merged, conflicts };
}

module.exports = { mergeAssetFields, IdentityMutationError, STABLE_NOTES_SEPARATOR };
