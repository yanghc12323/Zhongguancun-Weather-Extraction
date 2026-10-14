# Zhongguancun Weather Implementation Plan

**Goal:** Build a portable hourly-weather downloader with GCJ-02 conversion and interval-aware half-hour features.
**Architecture:** Independent standard-library modules for coordinates, response validation/alignment, transport/cache, and command-line output. Tests run without network. Actual study-window retrieval is a separate integration check.
**Tech Stack:** Python >=3.10, unittest, urllib, csv, json; no mandatory third-party dependencies.

## Global constraints
- Window [2026-03-02, 2026-05-25), timezone Asia/Shanghai (UTC+08:00).
- Fixed model ecmwf_ifs by default, era5 optional.
- Do not modify V8 or include bike-level records in a GitHub package.
- Explicit interval metadata; no unlabelled half-hour rainfall fabrication.
- User has already approved implementation; execute within this chat.

## Tasks
1. Coordinates and interval semantics: create tests/test_core.py first, run `python -m unittest discover -s tests -v` to record missing-feature failures, implement zgc_weather/coordinates.py and alignment.py. Verify Beijing/Shanghai/Shenzhen reference pairs, outside-China identity, invalid inputs, next-day midnight rainfall, daily totals, and optional half-hour conservation.
2. Acquisition: test request padding, fixed model, invalid dates, units, missing/duplicate timestamps, corrupt cache and retries; implement client.py. Request start-1 day through inclusive end+1 day. Cache by normalized parameters with SHA256 and original capture time; retry transient failures only.
3. CLI and CSV connection: test with synthetic response and offline replay, implement cli.py and join.py. Run `python -m zgc_weather --help`; all outputs use UTF-8 and explicit +08:00 times. CSV join uses exact half-hour timestamps and many-to-one mapping, rejecting missing matches and collisions.
4. Integration and delivery: retrieve the real 84-day window at the converted center, validate 2,016/4,032/84 counts, run offline replay and compare output hashes. Document CLI, field semantics, source attribution and GitHub packaging. Deliver a code-only ZIP plus separate local weather output.

## Verification commands
```powershell
python -m unittest discover -s tests -v
python -m zgc_weather --output data/ecmwf_ifs
python -m zgc_weather --output data/ecmwf_ifs_offline --cache-dir data/ecmwf_ifs/raw --offline
```

Repository creation/publishing is deferred to the user's later GitHub step. This workspace is not a Git repository.
