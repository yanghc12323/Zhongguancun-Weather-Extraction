"""Offline contract tests; coordinate reference vectors are credited in NOTICE."""
import importlib
import importlib.util
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
FIELDS = ["temperature_2m", "relative_humidity_2m", "precipitation", "rain",
          "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "weather_code"]
UNITS = ["°C", "%", "mm", "mm", "m/s", "m/s", "%", "wmo code"]


def scratch():
    # Keep test scratch in the checkout: restricted Windows runners may expose
    # an unwritable default system temporary directory.
    return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)


def sample():
    start = datetime(2026, 3, 1)
    times = [(start + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(72)]
    hourly = {"time": times}
    for f, value in zip(FIELDS, [10, 50, 0, 0, 2, 3, 40, 3]):
        hourly[f] = [value] * 72
    # 00:00 on March 2 belongs to March 1 and must not enter March 2 totals.
    hourly["precipitation"][24] = 99
    hourly["rain"][24] = 99
    hourly["precipitation"][25] = 2
    hourly["rain"][25] = 2
    # March 3 midnight is the final hour of March 2.
    hourly["precipitation"][48] = 6
    hourly["rain"][48] = 6
    return {"latitude": 40.0, "longitude": 116.25, "elevation": 53,
            "timezone": "Asia/Shanghai", "utc_offset_seconds": 28800,
            "hourly_units": dict(zip(FIELDS, UNITS)), "hourly": hourly}


class ContractCase(unittest.TestCase):
    def module(self, name):
        try:
            spec = importlib.util.find_spec("zgc_weather." + name)
        except ModuleNotFoundError:
            spec = None
        self.assertIsNotNone(spec, "Feature not implemented: " + name)
        return importlib.import_module("zgc_weather." + name)


class CoordinateTests(ContractCase):
    def test_public_reference_vectors(self):
        c = self.module("coordinates")
        refs = [(31.1774276, 121.5272106, 31.17530398364597, 121.531541859215),
                (22.543847, 113.912316, 22.540796131694766, 113.9171764808363),
                (39.911954, 116.377817, 39.91334545536069, 116.38404722455657)]
        for lat, lon, glat, glon in refs:
            with self.subTest(lat=lat):
                got = c.wgs84_to_gcj02(lat, lon)
                self.assertAlmostEqual(got[0], glat, places=7)
                self.assertAlmostEqual(got[1], glon, places=7)
                back = c.gcj02_to_wgs84(glat, glon)
                self.assertAlmostEqual(back[0], lat, places=7)
                self.assertAlmostEqual(back[1], lon, places=7)

    def test_outside_china_identity(self):
        c = self.module("coordinates")
        self.assertEqual(c.gcj02_to_wgs84(51.5, -0.1), (51.5, -0.1))

    def test_invalid_coordinates(self):
        c = self.module("coordinates")
        for coords in [(91, 116), (40, 181), (math.nan, 116)]:
            with self.assertRaises(ValueError):
                c.gcj02_to_wgs84(*coords)


class AlignmentTests(ContractCase):
    def hourly(self, payload=None):
        return self.module("alignment").align_hourly(payload or sample(), "2026-03-02", "2026-03-02")

    def test_precipitation_uses_next_timestamp_and_final_boundary(self):
        rows = self.hourly()
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0]["precipitation_mm"], 2)
        self.assertEqual(rows[-1]["precipitation_mm"], 6)
        self.assertEqual(rows[-1]["precipitation_source_time"], "2026-03-03T00:00:00+08:00")

    def test_halfhour_retains_hour_amount_without_invented_split(self):
        a = self.module("alignment")
        rows = a.align_halfhour(self.hourly())
        self.assertEqual(len(rows), 48)
        self.assertEqual(rows[0]["precipitation_hour_mm"], 2)
        self.assertEqual(rows[1]["precipitation_hour_mm"], 2)
        self.assertIsNone(rows[0]["precipitation_30min_est_mm"])
        self.assertEqual(rows[1]["slot_start"], "2026-03-02T00:30:00+08:00")
        self.assertEqual(rows[0]["temperature_c"], rows[1]["temperature_c"])

    def test_optional_uniform_split_conserves_daily_rain(self):
        a = self.module("alignment")
        hours = self.hourly()
        halves = a.align_halfhour(hours, rain_method="uniform")
        self.assertAlmostEqual(sum(x["precipitation_30min_est_mm"] for x in halves), 8)
        self.assertEqual(halves[0]["rainfall_mapping"], "uniform_split_estimate")
        daily = a.aggregate_daily(hours)
        self.assertEqual(daily[0]["precipitation_sum_mm"], 8)
        self.assertEqual(daily[0]["hours"], 24)

    def test_missing_end_record_is_rejected(self):
        p = sample()
        for values in p["hourly"].values():
            del values[48]
        with self.assertRaises(ValueError):
            self.hourly(p)

    def test_response_validation_finds_null_duplicate_and_wrong_units(self):
        a = self.module("alignment")
        p = sample()
        p["hourly"]["temperature_2m"][30] = None
        p["hourly"]["time"][31] = p["hourly"]["time"][30]
        p["hourly_units"]["wind_speed_10m"] = "km/h"
        report = a.validate_response(p, "2026-03-01", "2026-03-03")
        self.assertFalse(report["ok"])
        self.assertEqual(report["duplicate_timestamps"], 1)
        self.assertEqual(report["null_counts"]["temperature_2m"], 1)
        self.assertTrue(any("unit" in e for e in report["errors"]))

    def test_nonfinite_negative_and_short_fields_are_rejected(self):
        a = self.module("alignment")
        for field, value in [("temperature_2m", math.nan), ("precipitation", -1),
                             ("relative_humidity_2m", 101), ("weather_code", 999)]:
            p = sample()
            p["hourly"][field][25] = value
            self.assertFalse(a.validate_response(p, "2026-03-01", "2026-03-03")["ok"])
        p = sample()
        p["hourly"]["rain"].pop()
        self.assertFalse(a.validate_response(p, "2026-03-01", "2026-03-03")["ok"])

    def test_timezone_mismatch_is_rejected(self):
        p = sample()
        p["utc_offset_seconds"] = 0
        self.assertFalse(self.module("alignment").validate_response(p, "2026-03-01", "2026-03-03")["ok"])

    def test_temporal_window_and_method_validation(self):
        a = self.module("alignment")
        with self.assertRaises(ValueError):
            a.align_hourly(sample(), "2026-03-03", "2026-03-02")
        with self.assertRaises(ValueError):
            a.align_halfhour(self.hourly(), rain_method="invented")


if __name__ == "__main__":
    unittest.main()
