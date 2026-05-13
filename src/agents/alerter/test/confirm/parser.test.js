'use strict';

const { parseReply, REPLY_KINDS } = require('../../src/confirm/parser');

describe('parseReply (Phase 39 D-01)', () => {
  describe('YES family', () => {
    it('yes -> YES', () => { expect(parseReply('yes').kind).toBe('YES'); });
    it('YES (uppercase) -> YES', () => { expect(parseReply('YES').kind).toBe('YES'); });
    it('Yes (mixed) -> YES', () => { expect(parseReply('Yes').kind).toBe('YES'); });
    it('y -> YES', () => { expect(parseReply('y').kind).toBe('YES'); });
    it('Y -> YES', () => { expect(parseReply('Y').kind).toBe('YES'); });
    it('ok -> YES', () => { expect(parseReply('ok').kind).toBe('YES'); });
    it('OK -> YES', () => { expect(parseReply('OK').kind).toBe('YES'); });
    it('si -> YES', () => { expect(parseReply('si').kind).toBe('YES'); });
    it('SI -> YES', () => { expect(parseReply('SI').kind).toBe('YES'); });
    it('sí (with accent) -> YES', () => { expect(parseReply('sí').kind).toBe('YES'); });
    it('SÍ -> YES', () => { expect(parseReply('SÍ').kind).toBe('YES'); });
    it('yes please -> YES (only first token)', () => { expect(parseReply('yes please').kind).toBe('YES'); });
  });

  describe('NO family', () => {
    it('no -> NO', () => { expect(parseReply('no').kind).toBe('NO'); });
    it('NO -> NO', () => { expect(parseReply('NO').kind).toBe('NO'); });
    it('No (mixed) -> NO', () => { expect(parseReply('No').kind).toBe('NO'); });
    it('n -> NO', () => { expect(parseReply('n').kind).toBe('NO'); });
    it('N -> NO', () => { expect(parseReply('N').kind).toBe('NO'); });
    it('cancel -> NO', () => { expect(parseReply('cancel').kind).toBe('NO'); });
    it('CANCEL -> NO', () => { expect(parseReply('CANCEL').kind).toBe('NO'); });
    it('stop -> NO', () => { expect(parseReply('stop').kind).toBe('NO'); });
    it('STOP -> NO', () => { expect(parseReply('STOP').kind).toBe('NO'); });
    it('no thanks -> NO', () => { expect(parseReply('no thanks').kind).toBe('NO'); });
  });

  describe('EDIT explicit prefix', () => {
    it('EDIT change qty to 5 -> editText preserved', () => {
      expect(parseReply('EDIT change qty to 5')).toEqual({ kind: 'EDIT', editText: 'change qty to 5' });
    });
    it("edit (trailing space) -> editText=''", () => {
      expect(parseReply('edit ')).toEqual({ kind: 'EDIT', editText: '' });
    });
    it('Edit  with internal spaces preserved after first', () => {
      const r = parseReply('Edit  multiple  spaces');
      expect(r.kind).toBe('EDIT');
      expect(r.editText).toContain('multiple');
    });
    it("just 'EDIT' -> editText=''", () => {
      expect(parseReply('EDIT')).toEqual({ kind: 'EDIT', editText: '' });
    });
  });

  describe('EDIT implicit (any other content)', () => {
    it('actually it was SHI not OYS -> EDIT', () => {
      expect(parseReply('actually it was SHI not OYS')).toEqual({
        kind: 'EDIT',
        editText: 'actually it was SHI not OYS',
      });
    });
    it('change to 260513 -> EDIT', () => {
      expect(parseReply('change to 260513').kind).toBe('EDIT');
    });
    it('qty=7 -> EDIT', () => {
      expect(parseReply('qty=7')).toEqual({ kind: 'EDIT', editText: 'qty=7' });
    });
    it('leading/trailing whitespace trimmed', () => {
      expect(parseReply('  Some leading whitespace  ')).toEqual({
        kind: 'EDIT',
        editText: 'Some leading whitespace',
      });
    });
  });

  describe('NOOP', () => {
    it('null -> NOOP', () => { expect(parseReply(null).kind).toBe('NOOP'); });
    it('undefined -> NOOP', () => { expect(parseReply(undefined).kind).toBe('NOOP'); });
    it('empty string -> NOOP', () => { expect(parseReply('').kind).toBe('NOOP'); });
    it('whitespace only -> NOOP', () => { expect(parseReply('   ').kind).toBe('NOOP'); });
    it('pure emoji -> NOOP', () => { expect(parseReply('👍🏼').kind).toBe('NOOP'); });
    it('pure punctuation -> NOOP', () => { expect(parseReply('???').kind).toBe('NOOP'); });
  });

  describe('Style locks', () => {
    it('pure function: same arg twice returns deep-equal results', () => {
      expect(parseReply('yes')).toEqual(parseReply('yes'));
      expect(parseReply('EDIT foo')).toEqual(parseReply('EDIT foo'));
    });
    it('does not throw on non-string inputs', () => {
      expect(parseReply(123).kind).toBe('NOOP');
      expect(parseReply({}).kind).toBe('NOOP');
      expect(parseReply([]).kind).toBe('NOOP');
    });
  });

  describe('REPLY_KINDS', () => {
    it('exports frozen enum', () => {
      expect(REPLY_KINDS.YES).toBe('YES');
      expect(REPLY_KINDS.NO).toBe('NO');
      expect(REPLY_KINDS.EDIT).toBe('EDIT');
      expect(REPLY_KINDS.NOOP).toBe('NOOP');
    });
  });
});
