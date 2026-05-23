'use strict';

// Phase 44 Plan-04 D-02: event-gate facade.
// createEventGate({haikuClassifier, rules, logger}) → {classify(envCtx, lastBotOutbound, nowMs)}
//
// Decision flow (D-02 mandatory order):
//   1. rulePositive hit → {gate:'fast_event', allow_extract:true, allow_convo:true}
//   2. ruleNegative hit → {gate:'skipped_rule_neg', allow_extract:false, allow_convo:false}
//   3. else await haikuClassifier.classify
//        - !ok → {gate:'forced', allow_extract:true, allow_convo:true}  (D-03 fail-OPEN)
//        - is_event || confidence < 0.7 → {gate:'haiku_event', allow_extract:true, allow_convo:true}
//        - else → {gate:'haiku_chitchat', allow_extract:false, allow_convo:false}
//
// D-04 enum: skipped_rule_neg | fast_event | haiku_event | haiku_chitchat | forced

function createEventGate({ haikuClassifier, rules, logger = console } = {}) {
  return {
    async classify(envCtx, lastBotOutbound, nowMs) {
      const pos = rules.rulePositive(envCtx);
      if (pos.hit) {
        return { gate: 'fast_event', allow_extract: true, allow_convo: true };
      }
      const neg = rules.ruleNegative(envCtx, lastBotOutbound, nowMs);
      if (neg.hit) {
        return { gate: 'skipped_rule_neg', allow_extract: false, allow_convo: false };
      }
      const r = await haikuClassifier.classify(envCtx);
      if (!r || !r.ok) {
        return { gate: 'forced', allow_extract: true, allow_convo: true };
      }
      if (r.is_event === true || (typeof r.confidence === 'number' && r.confidence < 0.7)) {
        return { gate: 'haiku_event', allow_extract: true, allow_convo: true };
      }
      return { gate: 'haiku_chitchat', allow_extract: false, allow_convo: false };
    },
  };
}

module.exports = { createEventGate };
