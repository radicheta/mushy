const { localDayBounds, localDateOf, formatLocal } = require('../src/localday');

const MVD = 'America/Montevideo'; // UTC-3, no DST

describe('localDayBounds', () => {
    test('Montevideo day runs 03:00Z to next 03:00Z', () => {
        expect(localDayBounds('2026-11-11', MVD)).toEqual(['2026-11-11T03:00:00.000Z', '2026-11-12T03:00:00.000Z']);
    });
    test('UTC zone gives the plain calendar day', () => {
        expect(localDayBounds('2026-11-11', 'UTC')).toEqual(['2026-11-11T00:00:00.000Z', '2026-11-12T00:00:00.000Z']);
    });
    test('a DST-change day is 23 hours long (Toronto, 2026-03-08)', () => {
        const [s, e] = localDayBounds('2026-03-08', 'America/Toronto');
        expect(s).toBe('2026-03-08T05:00:00.000Z');
        expect(e).toBe('2026-03-09T04:00:00.000Z');
    });
});

describe('localDateOf', () => {
    test('21:30 local on the 11th is 00:30Z on the 12th', () => {
        expect(localDateOf(new Date('2026-11-12T00:30:00Z'), MVD)).toBe('2026-11-11');
    });
});

describe('formatLocal', () => {
    test('formats minutes in the local zone', () => {
        expect(formatLocal(new Date('2026-11-11T21:00:18Z').getTime(), MVD)).toBe('2026-11-11 18:00');
    });
    test('midnight is 00, not 24', () => {
        expect(formatLocal(new Date('2026-11-12T03:00:00Z').getTime(), MVD)).toBe('2026-11-12 00:00');
    });
});
