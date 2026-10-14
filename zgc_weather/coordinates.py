"""GCJ-02 approximate forward equations and their numerical inverse.

Equations adapted from googollee/eviltransform and wandergis/coordtransform;
see NOTICE. The ellipsoid constant 6378245 agrees with the reference vectors.
All public signatures use (latitude, longitude), in degrees. Solver convergence
measures equation residual, not accuracy against an official geodetic survey.
"""
import math


def validate_coordinates(latitude, longitude):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (latitude, longitude)):
        raise ValueError("Coordinates must be finite numbers")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Latitude/longitude outside valid bounds")


def wgs84_to_gcj02(latitude, longitude):
    validate_coordinates(latitude, longitude)
    if not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271):
        return latitude, longitude
    x, y = longitude - 105, latitude - 35
    common = (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    lat_delta = (-100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
                 + common + (20*math.sin(y*math.pi) + 40*math.sin(y*math.pi/3)) * 2/3
                 + (160*math.sin(y*math.pi/12) + 320*math.sin(y*math.pi/30)) * 2/3)
    lon_delta = (300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
                 + common + (20*math.sin(x*math.pi) + 40*math.sin(x*math.pi/3)) * 2/3
                 + (150*math.sin(x*math.pi/12) + 300*math.sin(x*math.pi/30)) * 2/3)
    radians = math.radians(latitude)
    eccentricity = 0.00669342162296594323
    magic = 1 - eccentricity * math.sin(radians)**2
    radius = 6378245.0
    lat_delta *= 180 / ((radius * (1-eccentricity)) / (magic * math.sqrt(magic)) * math.pi)
    lon_delta *= 180 / (radius / math.sqrt(magic) * math.cos(radians) * math.pi)
    return latitude + lat_delta, longitude + lon_delta


def gcj02_to_wgs84(latitude, longitude):
    validate_coordinates(latitude, longitude)
    estimate_lat, estimate_lon = latitude, longitude
    for _ in range(40):
        forward_lat, forward_lon = wgs84_to_gcj02(estimate_lat, estimate_lon)
        lat_error, lon_error = forward_lat - latitude, forward_lon - longitude
        if max(abs(lat_error), abs(lon_error)) < 1e-10:
            return estimate_lat, estimate_lon
        estimate_lat -= lat_error
        estimate_lon -= lon_error
    raise ValueError("GCJ-02 inverse did not converge")
