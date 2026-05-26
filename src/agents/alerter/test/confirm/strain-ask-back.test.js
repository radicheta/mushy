'use strict';

const { renderStrainAskBack, parseStrainAskBackReply } = require('../../src/confirm/strain-ask-back');

describe('renderStrainAskBack', () => {
  it('contains the seen code', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(msg).toContain('XYZ');
  });

  it('contains the nearest suggestion when provided', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(msg).toContain('SHI');
  });

  it('has no em-dashes', () => {
    const msg = renderStrainAskBack('XYZ', 'SHI');
    expect(/[–—]/.test(msg)).toBe(false);
  });

  it('has no em-dashes when nearest is null', () => {
    const msg = renderStrainAskBack('XYZ', null);
    expect(/[–—]/.test(msg)).toBe(false);
  });

  it('omits "did you mean" clause when nearest is null', () => {
    const msg = renderStrainAskBack('XYZ', null);
    expect(msg).toContain('XYZ');
    // should not mention a nearest code
    expect(msg).not.toMatch(/did you mean/i);
  });

  it('is a non-empty string', () => {
    expect(typeof renderStrainAskBack('LIM', 'LIMA')).toBe('string');
    expect(renderStrainAskBack('LIM', 'LIMA').length).toBeGreaterThan(0);
  });
});

describe('parseStrainAskBackReply', () => {
  it('"yes" -> confirm_new', () => {
    expect(parseStrainAskBackReply('yes')).toEqual({ kind: 'confirm_new' });
  });

  it('"YES" -> confirm_new (case-insensitive)', () => {
    expect(parseStrainAskBackReply('YES')).toEqual({ kind: 'confirm_new' });
  });

  it('"confirm" -> confirm_new', () => {
    expect(parseStrainAskBackReply('confirm')).toEqual({ kind: 'confirm_new' });
  });

  it('"si" -> confirm_new', () => {
    expect(parseStrainAskBackReply('si')).toEqual({ kind: 'confirm_new' });
  });

  it('"SHI" bare -> correction with uppercased code', () => {
    expect(parseStrainAskBackReply('SHI')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"shi" bare -> correction with uppercased code', () => {
    expect(parseStrainAskBackReply('shi')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"no, SHI" -> correction with code SHI', () => {
    expect(parseStrainAskBackReply('no, SHI')).toEqual({ kind: 'correction', code: 'SHI' });
  });

  it('"no, lima" -> correction with code LIMA', () => {
    expect(parseStrainAskBackReply('no, lima')).toEqual({ kind: 'correction', code: 'LIMA' });
  });

  it('gibberish / unrecognized -> unknown', () => {
    expect(parseStrainAskBackReply('??')).toEqual({ kind: 'unknown' });
  });

  it('empty string -> unknown', () => {
    expect(parseStrainAskBackReply('')).toEqual({ kind: 'unknown' });
  });

  it('non-string -> unknown', () => {
    expect(parseStrainAskBackReply(null)).toEqual({ kind: 'unknown' });
  });

  it('"maybe" (not a confirm/no/code) -> unknown', () => {
    expect(parseStrainAskBackReply('maybe')).toEqual({ kind: 'unknown' });
  });
});
