"""Exact many-to-one CSV time join without modifying bike source files."""
import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from .alignment import parse_time


def join_csv(bike_csv, weather_csv, output, time_column="slot_start"):
    bike_csv, weather_csv, output = map(Path, (bike_csv, weather_csv, output))
    if output.resolve() in {bike_csv.resolve(), weather_csv.resolve()}:
        raise ValueError("Output must differ from both input files")
    lookup = {}
    with weather_csv.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        weather_fields = reader.fieldnames
        if not weather_fields or "slot_start" not in weather_fields:
            raise ValueError("Weather CSV needs slot_start")
        for row in reader:
            t = parse_time(row["slot_start"])
            if t in lookup or t.minute not in {0, 30} or t.second or t.microsecond:
                raise ValueError("Duplicate or unaligned weather timestamp")
            lookup[t] = row
    if not lookup:
        raise ValueError("Weather CSV is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with bike_csv.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            bike_fields = reader.fieldnames
            if not bike_fields or time_column not in bike_fields:
                raise ValueError("Bike time column not found")
            added = ["weather_"+name for name in weather_fields]
            if set(added) & set(bike_fields):
                raise ValueError("Output weather column collides with a bike column")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=output.parent, delete=False) as handle:
                temporary = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=bike_fields+added)
                writer.writeheader()
                count = 0
                for row in reader:
                    t = parse_time(row[time_column])
                    if t not in lookup:
                        raise ValueError(f"Unmatched bike timestamp: {row[time_column]}")
                    writer.writerow({**row, **{"weather_"+k: v for k, v in lookup[t].items()}})
                    count += 1
        os.replace(temporary, output)
        return {"matched_rows": count, "weather_timestamps": len(lookup)}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="Join a bike CSV to weather_30min.csv on exact slot_start.")
    p.add_argument("--bike-csv", required=True, type=Path)
    p.add_argument("--weather-csv", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--time-column", default="slot_start")
    args = p.parse_args(argv)
    try:
        print(json.dumps(join_csv(args.bike_csv, args.weather_csv, args.output, args.time_column)))
        return 0
    except (ValueError, OSError, KeyError) as error:
        p.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
