import csv
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import ContractCase, sample, scratch


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class CLITests(ContractCase):
    def invoke(self, cli, argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(argv)

    def test_cli_creates_complete_outputs_and_metadata(self):
        cli = self.module("cli")
        with scratch() as d:
            meta = {"raw_sha256": "test-synthetic", "fetched_at": "2026-10-14T00:00:00+00:00", "from_cache": False}
            with patch("zgc_weather.cli.fetch_archive", return_value=(sample(), meta)):
                code = self.invoke(cli, ["--start", "2026-03-02", "--end", "2026-03-02", "--output", d])
            self.assertEqual(code, 0)
            for filename, count in [("weather_hourly.csv", 24), ("weather_30min.csv", 48), ("weather_daily.csv", 1)]:
                with (Path(d)/filename).open(encoding="utf-8-sig") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), count)
            metadata = json.loads((Path(d)/"metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["coordinate"]["input_crs"], "GCJ-02")
            self.assertLess(metadata["coordinate"]["forward_residual_degrees"], 1e-9)
            self.assertEqual(metadata["rainfall_mapping"], "hourly_context_only")
            self.assertIn("not_available_at_forecast_origin", metadata["intended_use"])

    def test_invalid_response_saves_report_and_no_weather_csv(self):
        cli = self.module("cli")
        payload = sample()
        payload["hourly"]["rain"][30] = None
        with scratch() as d:
            with patch("zgc_weather.cli.fetch_archive", return_value=(payload, {})):
                self.assertEqual(self.invoke(cli, ["--start", "2026-03-02", "--end", "2026-03-02", "--output", d]), 1)
            self.assertFalse((Path(d)/"weather_30min.csv").exists())
            self.assertFalse(json.loads((Path(d)/"quality_report.json").read_text())["ok"])

    def test_coordinate_options_require_a_pair_and_explicit_crs(self):
        cli = self.module("cli")
        with scratch() as d:
            self.assertEqual(self.invoke(cli, ["--latitude", "39.98", "--output", d]), 1)
            self.assertEqual(self.invoke(cli, ["--latitude", "39.98", "--longitude", "116.31", "--output", d]), 1)


class JoinTests(ContractCase):
    def test_join_preserves_bike_rows_and_normalizes_timestamp(self):
        join = self.module("join")
        with scratch() as d:
            d = Path(d)
            write_csv(d/"bike.csv", [{"geohash8": "a", "slot_start": "2026-03-02 00:00:00", "departures": 3},
                                     {"geohash8": "b", "slot_start": "2026-03-02T00:00:00+08:00", "departures": 5}])
            write_csv(d/"weather.csv", [{"slot_start": "2026-03-02T00:00:00+08:00", "temperature_c": 10}])
            result = join.join_csv(d/"bike.csv", d/"weather.csv", d/"joined.csv")
            self.assertEqual(result["matched_rows"], 2)
            with (d/"joined.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["departures"] for r in rows], ["3", "5"])
            self.assertEqual(rows[0]["weather_temperature_c"], "10")

    def test_duplicate_weather_or_unmatched_bike_fails_without_output(self):
        join = self.module("join")
        with scratch() as d:
            d = Path(d)
            write_csv(d/"bike.csv", [{"slot_start": "2026-03-02 00:30:00"}])
            row = {"slot_start": "2026-03-02 00:00:00", "temperature_c": 10}
            for weather in [[row, row], [row]]:
                write_csv(d/"weather.csv", weather)
                with self.assertRaises(ValueError):
                    join.join_csv(d/"bike.csv", d/"weather.csv", d/"joined.csv")
                self.assertFalse((d/"joined.csv").exists())

    def test_input_overwrite_and_column_collision_rejected(self):
        join = self.module("join")
        with scratch() as d:
            d = Path(d)
            write_csv(d/"bike.csv", [{"slot_start": "2026-03-02 00:00:00", "weather_temperature_c": 99}])
            write_csv(d/"weather.csv", [{"slot_start": "2026-03-02 00:00:00", "temperature_c": 10}])
            for output in [d/"bike.csv", d/"joined.csv"]:
                with self.assertRaises(ValueError):
                    join.join_csv(d/"bike.csv", d/"weather.csv", output)


if __name__ == "__main__":
    unittest.main()
