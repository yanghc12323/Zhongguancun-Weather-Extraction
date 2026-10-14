"""Command-line acquisition and reproducible CSV delivery."""
import argparse
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from . import __version__
from .alignment import align_hourly, align_halfhour, aggregate_daily, validate_response, study_window
from .client import build_request, fetch_archive, write_json, atomic_bytes
from .coordinates import gcj02_to_wgs84, wgs84_to_gcj02, validate_coordinates


def write_csv(path, rows):
    if not rows:
        raise ValueError("Cannot export an empty weather table")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, stream.getvalue().encode("utf-8-sig"))


def parser():
    p = argparse.ArgumentParser(description="Download regional weather and align hourly/30-minute intervals (Asia/Shanghai).")
    p.add_argument("--start", help="First study date, inclusive; default 2026-03-02")
    p.add_argument("--end", help="Last study date, inclusive; default 2026-05-24")
    p.add_argument("--model", choices=["ecmwf_ifs", "era5"], default="ecmwf_ifs")
    p.add_argument("--config", type=Path, default=Path(__file__).with_name("study_region.json"))
    p.add_argument("--latitude", "--lat", type=float)
    p.add_argument("--longitude", "--lon", type=float)
    p.add_argument("--crs", choices=["GCJ-02", "WGS84"], help="Required with a custom coordinate pair")
    p.add_argument("--output", type=Path, help="Default: data/<model>")
    p.add_argument("--cache-dir", type=Path, help="Default: <output>/raw")
    p.add_argument("--offline", action="store_true", help="Use matching cached response only")
    p.add_argument("--refresh", action="store_true", help="Explicitly re-fetch and replace matching cache")
    p.add_argument("--rain-method", choices=["none", "uniform"], default="none",
                   help="none: hour context only; uniform: add labelled half-hour estimates")
    p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--version", action="version", version=__version__)
    return p


def run(args):
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    start, end = args.start or config["default_start"], args.end or config["default_end"]
    begin, finish = study_window(start, end)
    custom = args.latitude is not None or args.longitude is not None or args.crs is not None
    if custom:
        if args.latitude is None or args.longitude is None or args.crs is None:
            raise ValueError("Supply --latitude, --longitude and --crs together")
        latitude, longitude, crs = args.latitude, args.longitude, args.crs
    else:
        latitude, longitude, crs = config["latitude"], config["longitude"], config["coordinate_system"]
    validate_coordinates(latitude, longitude)
    if crs == "GCJ-02":
        wlat, wlon = gcj02_to_wgs84(latitude, longitude)
        back = wgs84_to_gcj02(wlat, wlon)
        residual = max(abs(back[0]-latitude), abs(back[1]-longitude))
    elif crs == "WGS84":
        wlat, wlon, residual = latitude, longitude, None
    else:
        raise ValueError("Unsupported coordinate_system in config")
    params = build_request(start, end, wlat, wlon, args.model)
    output = args.output or Path("data") / args.model
    cache = args.cache_dir or output / "raw"
    payload, capture = fetch_archive(params, cache, offline=args.offline, refresh=args.refresh,
                                     timeout=args.timeout, attempts=args.attempts)
    quality = validate_response(payload, params["start_date"], params["end_date"])
    write_json(output/"quality_report.json", quality)
    if not quality["ok"]:
        raise ValueError("Source quality check failed; see quality_report.json. No new weather tables were written.")
    hourly = align_hourly(payload, start, end)
    halfhour = align_halfhour(hourly, args.rain_method)
    daily = aggregate_daily(hourly)
    counts = {"hourly": len(hourly), "halfhour": len(halfhour), "daily": len(daily)}
    days = (finish-begin).days
    expected = {"hourly": days*24, "halfhour": days*48, "daily": days}
    hourly_total = sum(r["precipitation_mm"] for r in hourly)
    daily_total = sum(r["precipitation_sum_mm"] for r in daily)
    conservation = math.isclose(hourly_total, daily_total, abs_tol=1e-8)
    if counts != expected or not conservation:
        raise ValueError("Derived row-count or precipitation reconciliation failed")
    files = {"weather_hourly.csv": hourly, "weather_30min.csv": halfhour, "weather_daily.csv": daily}
    for filename, rows in files.items():
        write_csv(output/filename, rows)
    quality.update(derived_counts=counts, expected_derived_counts=expected,
                   precipitation_hourly_to_daily_conserved=conservation,
                   study_precipitation_total_mm=hourly_total)
    if args.rain_method == "uniform":
        quality["precipitation_halfhour_estimate_conserved"] = math.isclose(
            sum(r["precipitation_30min_est_mm"] for r in halfhour), hourly_total, abs_tol=1e-8)
    metadata = {"tool_version": __version__, "source": "Open-Meteo Historical Weather API",
                "model": args.model, "spatial_resolution_km_approx": 9 if args.model == "ecmwf_ifs" else 25,
                "capture": capture, "request": params, "window_start": begin.isoformat(),
                "window_end_exclusive": finish.isoformat(), "timezone": "Asia/Shanghai",
                "coordinate": {"input_crs": crs, "input_latitude": latitude, "input_longitude": longitude,
                               "request_wgs84_latitude": wlat, "request_wgs84_longitude": wlon,
                               "forward_residual_degrees": residual,
                               "conversion": "approximate_gcj_forward_equations_iterative_inverse" if crs == "GCJ-02" else "identity",
                               "representative_point": "custom" if custom else config,
                               "returned_grid_latitude": payload["latitude"], "returned_grid_longitude": payload["longitude"]},
                "source_units": payload["hourly_units"], "state_mapping": "hold_hour_start",
                "rainfall_mapping": "uniform_split_estimate" if args.rain_method == "uniform" else "hourly_context_only",
                "hourly_definition": "[t,t+1h): instantaneous fields at t; preceding-hour rain/precipitation recorded at t+1h",
                "intended_use": "retrospective_analysis; historical_realized_weather_not_available_at_forecast_origin",
                "caveats": ["Regional gridded weather estimates, not a Zhongguancun station observation.",
                            "Numerical coordinate residual is not a geodetic accuracy estimate.",
                            "Repeated precipitation_hour_mm in the half-hour table must not be summed across half-hour rows.",
                            "Uniform half-hour rain, if enabled, is estimated rather than observed.",
                            "Hourly extremes and category mode differ from native daily extrema and severe-weather codes."],
                "attribution": "Weather data: Open-Meteo and ECMWF (IFS/ERA5); follow source CC BY 4.0 attribution.",
                "documentation": "https://open-meteo.com/en/docs/historical-weather-api",
                "files": {name: {"rows": len(rows), "sha256": hashlib.sha256((output/name).read_bytes()).hexdigest()}
                          for name, rows in files.items()}}
    write_json(output/"quality_report.json", quality)
    write_json(output/"metadata.json", metadata)
    print(json.dumps({"output": str(output), "model": args.model, "rows": counts,
                      "from_cache": capture["from_cache"], "quality_ok": quality["ok"]}, ensure_ascii=False))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
