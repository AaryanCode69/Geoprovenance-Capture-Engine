"""Generate geoprovenance/icon.png — the menu and toolbar icon.

Owner: Person A.  Sub-phase: A1.

    Run:  make icon

A generator rather than a committed binary nobody can edit: RULES.md §2.2 keeps
image libraries out of this project, so the icon is drawn here with zlib and
struct and is regenerable and reviewable as source. Deterministic — rebuilding
without editing this file produces identical bytes.

The glyph is the smallest picture of what the plugin does: two source datasets
converging into one derived dataset.
"""

from __future__ import annotations

import math
import pathlib
import struct
import zlib

SIZE = 32
SUPERSAMPLE = 4  # render big, box-filter down — cheap anti-aliasing
OUT = pathlib.Path(__file__).resolve().parents[1] / "geoprovenance" / "icon.png"

NODE_RGB = (46, 125, 50)    # green: a dataset
EDGE_RGB = (84, 110, 122)   # slate: "came from"

NODES = [(0.24, 0.22), (0.76, 0.22), (0.50, 0.76)]
EDGES = [(0, 2), (1, 2)]
NODE_RADIUS = 0.155
EDGE_WIDTH = 0.055


def _distance_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _render(resolution: int) -> list[list[tuple[int, int, int, int]]]:
    rows = []
    for y in range(resolution):
        row = []
        for x in range(resolution):
            u = (x + 0.5) / resolution
            v = (y + 0.5) / resolution
            pixel = (0, 0, 0, 0)

            for start, end in EDGES:
                ax, ay = NODES[start]
                bx, by = NODES[end]
                if _distance_to_segment(u, v, ax, ay, bx, by) <= EDGE_WIDTH:
                    pixel = (*EDGE_RGB, 255)
                    break

            for cx, cy in NODES:  # nodes draw over edges
                if math.hypot(u - cx, v - cy) <= NODE_RADIUS:
                    pixel = (*NODE_RGB, 255)
                    break

            row.append(pixel)
        rows.append(row)
    return rows


def _downsample(rows, factor: int) -> list[bytes]:
    """Box filter, averaging in premultiplied space so edges don't get haloes."""
    size = len(rows) // factor
    out = []
    for y in range(size):
        line = bytearray()
        for x in range(size):
            r_sum = g_sum = b_sum = a_sum = 0
            for dy in range(factor):
                for dx in range(factor):
                    r, g, b, a = rows[y * factor + dy][x * factor + dx]
                    r_sum += r * a
                    g_sum += g * a
                    b_sum += b * a
                    a_sum += a
            if a_sum == 0:
                line += bytes(4)
            else:
                n = factor * factor
                line += bytes((r_sum // a_sum, g_sum // a_sum,
                               b_sum // a_sum, a_sum // n))
        out.append(bytes(line))
    return out


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path: pathlib.Path, size: int, scanlines: list[bytes]) -> None:
    raw = b"".join(b"\x00" + line for line in scanlines)  # filter type 0 per row
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> int:
    scanlines = _downsample(_render(SIZE * SUPERSAMPLE), SUPERSAMPLE)
    write_png(OUT, SIZE, scanlines)
    print(f"wrote {OUT.relative_to(OUT.parents[1])}  "
          f"{SIZE}x{SIZE}  {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
