"""Public API transport, normalized request parameters, and immutable capture cache."""
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .alignment import VARIABLES, study_window
from .coordinates import validate_coordinates

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"


def build_request(start, end, latitude, longitude, model):
    begin, finish = study_window(start, end)
    validate_coordinates(latitude, longitude)
    if model not in {"ecmwf_ifs", "era5"}:
        raise ValueError("Choose fixed model ecmwf_ifs or era5")
    return {"latitude": latitude, "longitude": longitude,
            "start_date": (begin-timedelta(days=1)).date().isoformat(),
            "end_date": finish.date().isoformat(),
            "hourly": ",".join(VARIABLES), "timezone": "Asia/Shanghai",
            "models": model, "wind_speed_unit": "ms", "temperature_unit": "celsius",
            "precipitation_unit": "mm", "timeformat": "iso8601", "cell_selection": "land"}


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, data):
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


def fetch_archive(params, cache_dir, offline=False, refresh=False, timeout=30, attempts=3):
    if offline and refresh:
        raise ValueError("offline and refresh cannot be combined")
    if timeout <= 0 or not 1 <= attempts <= 5:
        raise ValueError("timeout must be positive; attempts must be between 1 and 5")
    cache_dir = Path(cache_dir)
    identity = json.dumps({"endpoint": ENDPOINT, "params": params}, sort_keys=True).encode()
    key = hashlib.sha256(identity).hexdigest()
    raw_path, meta_path = cache_dir / (key+".response.json"), cache_dir / (key+".request.json")
    if raw_path.exists() and meta_path.exists() and not refresh:
        raw = raw_path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("params") != params or meta.get("endpoint") != ENDPOINT or meta.get("raw_sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("Cache identity/checksum mismatch; use --refresh to replace it")
        return json.loads(raw), {**meta, "from_cache": True}
    if offline:
        raise ValueError("No complete cache for these request parameters")
    url = ENDPOINT + "?" + urlencode(params)
    last_error = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={"User-Agent": "zgc-weather/0.1.0"}), timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise ValueError(f"API HTTP {error.code}: {error.reason}") from error
            last_error = error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        else:
            break
        if attempt < attempts-1:
            time.sleep(2**attempt)
    else:
        raise ValueError(f"API request failed after {attempts} attempts: {last_error}") from last_error
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("API returned an error or unexpected JSON object")
    meta = {"endpoint": ENDPOINT, "params": params, "request_url": url,
            "http_status": status, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
            "cache_key": key, "raw_file": raw_path.name}
    atomic_bytes(raw_path, raw)
    write_json(meta_path, meta)
    return payload, {**meta, "from_cache": False}
