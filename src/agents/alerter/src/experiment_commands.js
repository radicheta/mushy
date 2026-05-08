'use strict';

// Phase 31 D-14, D-15: Signal command grammar for forcing experiments.
// Default duration 15 minutes; hard cap 120 minutes.
// Slash prefix is required to disambiguate from natural-language capture text
// (the capture pipeline runs as the SLOW PATH after experiment + snooze).

const DEFAULT_DURATION_MIN = 15;
const HARD_CAP_MIN = 120;
const VALID_NAMES = new Set(['force-condensation', 'force-evaporation']);

// Strict regex: optional whitespace, slash + name, optional integer N, optional whitespace.
// Case-insensitive on the command prefix so `/Force-Condensation` works too.
const FORCE_RE = /^\s*\/(force-condensation|force-evaporation)(?:\s+(\S+))?\s*$/i;
const CANCEL_RE = /^\s*\/cancel-experiment\s*$/i;
const CANCEL_PREFIX_RE = /^\s*\/cancel-experiment\b/i;

function helpReply(name) {
    return (
        `Usage: /${name} [N]\n` +
        `  N = duration in minutes, integer in [1, ${HARD_CAP_MIN}]; defaults to ${DEFAULT_DURATION_MIN}.\n` +
        `Or: /cancel-experiment to abort an in-flight experiment.`
    );
}

function parseExperimentCommand(text) {
    if (typeof text !== 'string') return { ok: false, reply: null };

    // /cancel-experiment first — short-circuit the canonical form.
    if (CANCEL_RE.test(text)) {
        return { ok: true, kind: 'cancel' };
    }
    // /cancel-experiment with extra args → reject for clarity (don't silently
    // accept a typo like '/cancel-experiment now' as if no args were passed).
    if (CANCEL_PREFIX_RE.test(text)) {
        return { ok: false, reply: 'Usage: /cancel-experiment (no arguments).' };
    }

    const m = text.match(FORCE_RE);
    if (m) {
        const name = m[1].toLowerCase();
        if (!VALID_NAMES.has(name)) {
            // Defensive: regex is anchored to the two valid names already, so
            // this is unreachable in practice. Pass through if it ever fires.
            return { ok: false, reply: null };
        }
        const rawN = m[2];
        let dur;
        if (rawN === undefined) {
            dur = DEFAULT_DURATION_MIN;
        } else {
            // Must be an integer literal in [1, HARD_CAP_MIN].
            if (!/^\d+$/.test(rawN)) {
                return { ok: false, reply: helpReply(name) };
            }
            dur = parseInt(rawN, 10);
            if (dur < 1 || dur > HARD_CAP_MIN) {
                return { ok: false, reply: helpReply(name) };
            }
        }
        return { ok: true, kind: 'start', name, duration_minutes: dur };
    }
    // Not an experiment command — passthrough so the snooze + capture branches
    // get a chance.
    return { ok: false, reply: null };
}

module.exports = {
    parseExperimentCommand,
    DEFAULT_DURATION_MIN,
    HARD_CAP_MIN,
    VALID_NAMES,
};
