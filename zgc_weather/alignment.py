"""Validate and map API values to explicit Beijing-time intervals."""
import math
from datetime import date, datetime, timedelta, timezone
from collections import Counter

TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
VARIABLES = {
    "temperature_2m": ("temperature_c", "°C"),
    "relative_humidity_2m": ("relative_humidity_pct", "%"),
    "precipitation": ("precipitation_mm", "mm"),
    "rain": ("rain_mm", "mm"),
    "wind_speed_10m": ("wind_speed_ms", "m/s"),
    "wind_gusts_10m": ("wind_gusts_ms", "m/s"),
    "cloud_cover": ("cloud_cover_pct", "%"),
    "weather_code": ("weather_code", "wmo code"),
}
WMO_CODES = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
             71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


def study_window(start, end):
    """end is an inclusive date, returned end boundary is exclusive."""
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if end_date < start_date:
        raise ValueError("end date must not precede start date")
    return (datetime.combine(start_date, datetime.min.time(), TZ),
            datetime.combine(end_date + timedelta(days=1), datetime.min.time(), TZ))


def parse_time(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)


def validate_response(payload, start, end):
    start_dt, end_dt = study_window(start, end)
    expected = [start_dt + timedelta(hours=i) for i in range(int((end_dt-start_dt).total_seconds()/3600))]
    errors = []
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        return {"ok": False, "errors": ["hourly object missing"]}
    if payload.get("timezone") != "Asia/Shanghai" or payload.get("utc_offset_seconds") != 28800:
        errors.append("timezone/UTC offset mismatch")
    raw = payload["hourly"].get("time", [])
    if not isinstance(raw, list):
        raw = []
        errors.append("time must be a list")
    try:
        times = [parse_time(t) for t in raw]
    except (ValueError, TypeError):
        times = []
        errors.append("invalid timestamp")
    if times != expected:
        errors.append("timestamp sequence does not match requested hourly window")
    duplicates = len(times) - len(set(times))
    nulls, lengths, invalids = {}, {}, {}
    for field, (_, unit) in VARIABLES.items():
        values = payload["hourly"].get(field, [])
        if not isinstance(values, list):
            values = []
        lengths[field] = len(values)
        nulls[field] = sum(v is None for v in values)
        invalid = 0
        for v in values:
            numeric = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            bad = not numeric
            if numeric:
                if field in {"relative_humidity_2m", "cloud_cover"}:
                    bad = not 0 <= v <= 100
                elif field in {"precipitation", "rain", "wind_speed_10m", "wind_gusts_10m"}:
                    bad = v < 0
                elif field == "weather_code":
                    bad = v not in WMO_CODES
            invalid += int(bad)
        invalids[field] = invalid
        if len(values) != len(expected) or invalid:
            errors.append(f"invalid values or length: {field}")
        if payload.get("hourly_units", {}).get(field) != unit:
            errors.append(f"unit mismatch: {field}")
    for key in ("latitude", "longitude"):
        value = payload.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"missing grid coordinate: {key}")
    return {"ok": not errors, "errors": errors, "expected_hours": len(expected),
            "actual_hours": len(raw), "duplicate_timestamps": duplicates,
            "timestamp_sequence_matches_expected": times == expected,
            "null_counts": nulls, "variable_lengths": lengths, "invalid_counts": invalids}


def weather_category(code):
    if code == 0:
        return "clear"
    if code in {1, 2, 3}:
        return "cloudy"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55}:
        return "drizzle"
    if code in {56, 57, 66, 67}:
        return "freezing_precipitation"
    if code in {61, 63, 65, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    raise ValueError("Unknown WMO code")


def align_hourly(payload, start, end):
    begin, finish = study_window(start, end)
    report = validate_response(payload, (begin-timedelta(days=1)).date().isoformat(), finish.date().isoformat())
    if not report["ok"]:
        raise ValueError("Invalid source response: " + "; ".join(report["errors"]))
    source = payload["hourly"]
    lookup = {parse_time(t): i for i, t in enumerate(source["time"])}
    rows = []
    t = begin
    while t < finish:
        next_t = t + timedelta(hours=1)
        state_index, rain_index = lookup[t], lookup[next_t]
        row = {"interval_start": t.isoformat(), "interval_end": next_t.isoformat(),
               "state_source_time": t.isoformat(), "precipitation_source_time": next_t.isoformat()}
        for field, (name, _) in VARIABLES.items():
            row[name] = source[field][rain_index if field in {"precipitation", "rain"} else state_index]
        row["weather_category"] = weather_category(row["weather_code"])
        rows.append(row)
        t = next_t
    return rows


def align_halfhour(hourly, rain_method="none"):
    if rain_method not in {"none", "uniform"}:
        raise ValueError("rain_method must be none or uniform")
    rows = []
    for hour in hourly:
        for offset in (0, 30):
            t = parse_time(hour["interval_start"]) + timedelta(minutes=offset)
            row = {"slot_start": t.isoformat(), "slot_end": (t+timedelta(minutes=30)).isoformat(),
                   "state_source_time": hour["state_source_time"],
                   "precipitation_source_time": hour["precipitation_source_time"],
                   "precipitation_interval_start": hour["interval_start"],
                   "precipitation_interval_end": hour["interval_end"]}
            for name in ("temperature_c", "relative_humidity_pct", "wind_speed_ms", "wind_gusts_ms",
                         "cloud_cover_pct", "weather_code", "weather_category"):
                row[name] = hour[name]
            row.update(precipitation_hour_mm=hour["precipitation_mm"], rain_hour_mm=hour["rain_mm"],
                       precipitation_30min_est_mm=hour["precipitation_mm"]/2 if rain_method == "uniform" else None,
                       rain_30min_est_mm=hour["rain_mm"]/2 if rain_method == "uniform" else None,
                       state_mapping="hold_hour_start", rainfall_mapping="uniform_split_estimate" if rain_method == "uniform" else "hourly_context_only")
            rows.append(row)
    return rows


def aggregate_daily(hourly):
    groups = {}
    for row in hourly:
        day = parse_time(row["interval_start"]).date().isoformat()
        groups.setdefault(day, []).append(row)
    output = []
    for day, rows in sorted(groups.items()):
        if len(rows) != 24:
            raise ValueError(f"Incomplete day: {day}")
        temperatures = [r["temperature_c"] for r in rows]
        output.append({"date": day, "hours": len(rows),
                       "temperature_mean_c": sum(temperatures)/24,
                       "temperature_min_hourly_c": min(temperatures), "temperature_max_hourly_c": max(temperatures),
                       "relative_humidity_mean_pct": sum(r["relative_humidity_pct"] for r in rows)/24,
                       "precipitation_sum_mm": sum(r["precipitation_mm"] for r in rows),
                       "rain_sum_mm": sum(r["rain_mm"] for r in rows),
                       "precipitation_hours": sum(r["precipitation_mm"] > 0 for r in rows),
                       "wind_speed_mean_ms": sum(r["wind_speed_ms"] for r in rows)/24,
                       "wind_gusts_max_hourly_ms": max(r["wind_gusts_ms"] for r in rows),
                       "cloud_cover_mean_pct": sum(r["cloud_cover_pct"] for r in rows)/24,
                       "weather_category_mode": Counter(r["weather_category"] for r in rows).most_common(1)[0][0]})
    return output
