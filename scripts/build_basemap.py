"""Regenerate static/maps/basemap.geojson from Natural Earth shapefiles.

Source data (public domain, https://www.naturalearthdata.com/downloads/110m-physical-vectors/):
  - 110m Coastline (110m-physical-vectors/110m-coastline)
  - 110m Land boundaries (110m-cultural-vectors/110m-admin-0-boundary-lines-land)

Download each "Download" link as a shapefile and pass the unzipped .shp paths.
The 1:110m tier is Natural Earth's most generalized -- it's drawn for "zoomed
out, big picture" small-scale maps, which suits this basemap's role as a
backdrop behind location pins.

This is a one-off vendoring tool, not part of the application. It has no test
suite of its own — the output is a static asset checked into the repo and
exercised by tests/js/locationsmap.test.js.

Usage:
    uv run python scripts/build_basemap.py \
        path/to/ne_110m_coastline.shp \
        path/to/ne_110m_admin_0_boundary_lines_land.shp \
        static/maps/basemap.geojson
"""

import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

# Simplification tolerance in decimal degrees (Douglas-Peucker epsilon) and
# the minimum bounding-box diagonal (degrees) a line must span to be kept --
# drops islands/border fragments too small to register at state-scale zoom.
COASTLINE_EPSILON = 0.15
COASTLINE_MIN_DIAGONAL = 0.5
BORDER_EPSILON = 0.15
BORDER_MIN_DIAGONAL = 0.3
# Coordinate rounding for the output file.
DECIMALS = 1

# Shapefile geometry type code for PolyLine records (the only shape type
# these Natural Earth layers use).
_SHAPE_TYPE_POLYLINE = 3
# Douglas-Peucker needs an interior point to consider splitting; below this
# a segment is already minimal.
_MIN_POINTS_TO_SIMPLIFY = 3
_MIN_SEGMENT_POINTS = 2


def read_polylines(path: Path) -> list[list[tuple[float, float]]]:
    """Parse PolyLine records (shape type 3) out of a .shp file."""
    data = path.read_bytes()
    pos = 100  # skip the fixed-size file header
    lines: list[list[tuple[float, float]]] = []
    while pos < len(data):
        _rec_num, content_words = struct.unpack(">ii", data[pos : pos + 8])
        pos += 8
        content_len = content_words * 2
        content = data[pos : pos + content_len]
        shape_type = struct.unpack("<i", content[0:4])[0]
        if shape_type == _SHAPE_TYPE_POLYLINE:
            num_parts, num_points = struct.unpack("<ii", content[36:44])
            parts_off = 44
            parts = struct.unpack(f"<{num_parts}i", content[parts_off : parts_off + 4 * num_parts])
            pts_off = parts_off + 4 * num_parts
            point_bytes = content[pts_off : pts_off + 16 * num_points]
            coords = struct.unpack(f"<{num_points * 2}d", point_bytes)
            points = list(zip(coords[0::2], coords[1::2], strict=True))
            starts = [*parts, num_points]
            lines.extend(points[starts[i] : starts[i + 1]] for i in range(num_parts))
        pos += content_len
    return lines


def simplify(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Simplify a line with iterative Douglas-Peucker, keeping points farther than epsilon."""
    if len(points) < _MIN_POINTS_TO_SIMPLIFY:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < _MIN_SEGMENT_POINTS:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        den = math.hypot(dx, dy)
        dmax, idx = -1.0, -1
        for i in range(start + 1, end):
            x, y = points[i]
            d = math.hypot(x - x1, y - y1) if den == 0 else abs(dx * (y - y1) - dy * (x - x1)) / den
            if d > dmax:
                dmax, idx = d, i
        if dmax > epsilon:
            keep[idx] = True
            stack.append((start, idx))
            stack.append((idx, end))
    return [p for p, k in zip(points, keep, strict=True) if k]


def bbox_diagonal(points: list[tuple[float, float]]) -> float:
    """Return the diagonal length, in degrees, of a line's bounding box."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def simplified_multiline(
    shp_path: Path, epsilon: float, min_diagonal: float, properties: dict[str, str]
) -> JsonDict:
    """Read, simplify, and filter a shapefile's lines into one MultiLineString feature."""
    lines = read_polylines(shp_path)
    simplified = [simplify(line, epsilon) for line in lines if bbox_diagonal(line) >= min_diagonal]
    feature: JsonDict = {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [
                [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in line] for line in simplified
            ],
        },
    }
    total_points = sum(len(line) for line in simplified)
    print(f"{shp_path.name}: {len(simplified)} lines, {total_points} points")
    return feature


def main(coastline_shp: Path, borders_shp: Path, out_path: Path) -> None:
    """Build the combined coastline + border-lines GeoJSON and write it to out_path."""
    geojson: JsonDict = {
        "type": "FeatureCollection",
        "features": [
            simplified_multiline(coastline_shp, COASTLINE_EPSILON, COASTLINE_MIN_DIAGONAL, {}),
            simplified_multiline(
                borders_shp, BORDER_EPSILON, BORDER_MIN_DIAGONAL, {"kind": "border"}
            ),
        ],
    }
    out_path.write_text(json.dumps(geojson, separators=(",", ":")))
    print(f"-> {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
