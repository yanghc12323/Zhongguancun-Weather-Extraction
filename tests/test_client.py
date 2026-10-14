import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from test_core import ContractCase, sample, scratch


class Response(io.BytesIO):
    status = 200


class ClientTests(ContractCase):
    def params(self):
        return self.module("client").build_request("2026-03-02", "2026-03-02", 39.97, 116.31, "ecmwf_ifs")

    def test_padding_and_fixed_units(self):
        p = self.params()
        self.assertEqual(p["start_date"], "2026-03-01")
        self.assertEqual(p["end_date"], "2026-03-03")
        self.assertEqual(p["models"], "ecmwf_ifs")
        self.assertEqual(p["timezone"], "Asia/Shanghai")
        self.assertEqual(p["wind_speed_unit"], "ms")

    def test_invalid_model_and_window(self):
        c = self.module("client")
        for start, end, model in [("2026-03-03", "2026-03-02", "era5"),
                                  ("2026-03-02", "2026-03-03", "best_match")]:
            with self.assertRaises(ValueError):
                c.build_request(start, end, 40, 116, model)

    def test_download_cache_and_offline_replay(self):
        c = self.module("client")
        raw = json.dumps(sample()).encode()
        with scratch() as d:
            with patch("zgc_weather.client.urlopen", return_value=Response(raw)) as http:
                payload, meta = c.fetch_archive(self.params(), Path(d))
                self.assertEqual(http.call_count, 1)
                self.assertEqual(payload, sample())
                self.assertEqual(meta["http_status"], 200)
            with patch("zgc_weather.client.urlopen", side_effect=AssertionError("offline must not connect")):
                replay, cached = c.fetch_archive(self.params(), Path(d), offline=True)
            self.assertEqual(replay, payload)
            self.assertEqual(cached["fetched_at"], meta["fetched_at"])
            self.assertEqual(cached["raw_sha256"], meta["raw_sha256"])
            self.assertTrue(cached["from_cache"])

    def test_offline_cache_miss_and_tampering(self):
        c = self.module("client")
        with scratch() as d:
            with self.assertRaises(ValueError):
                c.fetch_archive(self.params(), Path(d), offline=True)
            with patch("zgc_weather.client.urlopen", return_value=Response(json.dumps(sample()).encode())):
                c.fetch_archive(self.params(), Path(d))
            next(Path(d).glob("*.response.json")).write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                c.fetch_archive(self.params(), Path(d), offline=True)

    def test_retry_transient_error_but_not_bad_request(self):
        c = self.module("client")
        err = HTTPError("https://example.org", 503, "temporary", {}, None)
        with scratch() as d:
            with patch("zgc_weather.client.urlopen", side_effect=[err, Response(json.dumps(sample()).encode())]) as http:
                with patch("zgc_weather.client.time.sleep"):
                    c.fetch_archive(self.params(), Path(d))
                self.assertEqual(http.call_count, 2)
        err = HTTPError("https://example.org", 400, "bad request", {}, None)
        with scratch() as d:
            with patch("zgc_weather.client.urlopen", side_effect=err) as http:
                with self.assertRaises(ValueError):
                    c.fetch_archive(self.params(), Path(d))
                self.assertEqual(http.call_count, 1)

    def test_cache_write_error_does_not_repeat_network_request(self):
        c = self.module("client")
        with scratch() as d:
            with patch("zgc_weather.client.urlopen", side_effect=lambda *a, **kw: Response(json.dumps(sample()).encode())) as http:
                with patch("zgc_weather.client.atomic_bytes", side_effect=OSError("disk write denied")):
                    with patch("zgc_weather.client.time.sleep"):
                        with self.assertRaises(Exception) as caught:
                            c.fetch_archive(self.params(), Path(d))
            self.assertIsInstance(caught.exception, OSError)
            self.assertEqual(http.call_count, 1)


if __name__ == "__main__":
    unittest.main()
