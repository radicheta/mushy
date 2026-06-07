const fc_derived = require('../src/fc_derived');

describe('fc_derived.computeVpdKpa', () => {
    test('Tetens SVP at 20C is ~2.338 kPa (RH=0 -> VPD=SVP)', () => {
        expect(fc_derived.computeVpdKpa(20, 0)).toBeCloseTo(2.338, 2);
    });

    test('saturated air (RH=100) has zero deficit', () => {
        expect(fc_derived.computeVpdKpa(23, 100)).toBeCloseTo(0, 6);
    });

    test('typical fruiting point 23C/95% -> ~0.14 kPa', () => {
        expect(fc_derived.computeVpdKpa(23, 95)).toBeCloseTo(0.14, 2);
    });

    test('dry air 25C/50% -> ~1.58 kPa', () => {
        expect(fc_derived.computeVpdKpa(25, 50)).toBeCloseTo(1.58, 2);
    });

    test('RH clamps above 100 (no negative VPD)', () => {
        expect(fc_derived.computeVpdKpa(23, 120)).toBeGreaterThanOrEqual(0);
    });
});

describe('fc_derived.computeWaterVaporMl', () => {
    test('scales linearly with chamber volume', () => {
        const one = fc_derived.computeWaterVaporMl(23, 90, 1);
        const ten = fc_derived.computeWaterVaporMl(23, 90, 10);
        expect(ten).toBeCloseTo(one * 10, 6);
    });

    test('absolute humidity ~17.3 g/m^3 at 20C saturated', () => {
        // Well-known reference: AH at 20C, 100% RH ~ 17.3 g/m^3.
        expect(fc_derived.computeWaterVaporMl(20, 100, 1)).toBeCloseTo(17.3, 1);
    });

    test('FC-1 default volume (5.76 m^3) at 23C/95% -> ~112 mL', () => {
        expect(fc_derived.computeWaterVaporMl(23, 95)).toBeCloseTo(112.5, 0);
    });
});

describe('fc_derived.computeDerived', () => {
    test('returns both metrics for valid inputs', () => {
        const r = fc_derived.computeDerived(23, 95);
        expect(r).toHaveProperty('vpd');
        expect(r).toHaveProperty('water_vapor');
    });

    test('returns null when an input is non-finite', () => {
        expect(fc_derived.computeDerived(NaN, 90)).toBeNull();
        expect(fc_derived.computeDerived(23, undefined)).toBeNull();
    });
});
