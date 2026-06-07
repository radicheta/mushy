/**
 * fc_derived.js — bridge-side derived telemetry.
 *
 * Computes values that aren't read off a sensor but are pure functions of the
 * raw temperature + relative-humidity readings the chamber already publishes:
 *
 *   - VPD (vapor pressure deficit, kPa) — the dryness the crop "feels".
 *   - Water vapor held in the chamber atmosphere (mL) — absolute humidity
 *     integrated over the chamber's air volume.
 *
 * Bridge-side (not fc_core) by design: no new ROS publisher, no edge-buffer
 * entry, no DB migration. The (time, topic, value) hypertable takes the new
 * topic names as-is, and replay of the raw inputs re-derives these on ingest.
 *
 * Chamber geometry: FC-1 interior is 120 x 240 x 200 cm = 5.76 m^3.
 * Override with FC_CHAMBER_VOLUME_M3 if the chamber changes.
 */

'use strict';

// FC-1 interior dimensions (metres). Volume = 1.2 * 2.4 * 2.0 = 5.76 m^3.
const CHAMBER_DIMS_M = { width: 1.2, depth: 2.4, height: 2.0 };
const DEFAULT_CHAMBER_VOLUME_M3 = CHAMBER_DIMS_M.width * CHAMBER_DIMS_M.depth * CHAMBER_DIMS_M.height;

const CHAMBER_VOLUME_M3 = (() => {
    const env = parseFloat(process.env.FC_CHAMBER_VOLUME_M3);
    return Number.isFinite(env) && env > 0 ? env : DEFAULT_CHAMBER_VOLUME_M3;
})();

// Molar mass of water (g/mol) over universal gas constant (J/(mol*K)).
// AH[g/m^3] = (Mw / R) * e_Pa / T_K
const MW_OVER_R = 18.01528 / 8.31446; // ~2.1668

/**
 * Saturation vapor pressure (kPa) over liquid water — Tetens equation.
 * @param {number} tempC  air temperature, deg C
 */
function saturationVaporPressureKpa(tempC) {
    return 0.6108 * Math.exp((17.27 * tempC) / (tempC + 237.3));
}

/**
 * Vapor pressure deficit (kPa).
 * @param {number} tempC      air temperature, deg C
 * @param {number} rhPercent  relative humidity, 0-100
 */
function computeVpdKpa(tempC, rhPercent) {
    const svp = saturationVaporPressureKpa(tempC);
    const rhFrac = Math.max(0, Math.min(1, rhPercent / 100));
    return svp * (1 - rhFrac);
}

/**
 * Water vapor mass held in the chamber air (grams ~= mL, since 1 g water ~ 1 mL).
 * @param {number} tempC      air temperature, deg C
 * @param {number} rhPercent  relative humidity, 0-100
 * @param {number} volumeM3   chamber air volume, m^3 (defaults to FC-1)
 */
function computeWaterVaporMl(tempC, rhPercent, volumeM3 = CHAMBER_VOLUME_M3) {
    const rhFrac = Math.max(0, Math.min(1, rhPercent / 100));
    const avpPa = saturationVaporPressureKpa(tempC) * 1000 * rhFrac; // actual vapor pressure, Pa
    const tempK = tempC + 273.15;
    const absHumidityGm3 = MW_OVER_R * (avpPa / tempK); // g/m^3
    return absHumidityGm3 * volumeM3; // grams ~= mL
}

/**
 * Compute all derived metrics from a temp/RH pair. Returns null if either
 * input is missing or non-finite (callers should skip emitting).
 * @returns {{vpd:number, water_vapor:number}|null}
 */
function computeDerived(tempC, rhPercent) {
    if (!Number.isFinite(tempC) || !Number.isFinite(rhPercent)) return null;
    return {
        vpd: computeVpdKpa(tempC, rhPercent),
        water_vapor: computeWaterVaporMl(tempC, rhPercent)
    };
}

module.exports = {
    CHAMBER_DIMS_M,
    CHAMBER_VOLUME_M3,
    saturationVaporPressureKpa,
    computeVpdKpa,
    computeWaterVaporMl,
    computeDerived
};
