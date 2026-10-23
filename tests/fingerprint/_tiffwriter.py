"""A deliberately small GeoTIFF writer for the tests — standard library only.

It can write the same pixels in every storage layout `tiff.py` claims to read
(strips or tiles, none/Deflate, predictor 1/2, planar 1/2, either byte order,
classic or BigTIFF), which is what lets one test assert that all of them are
the same data. It is test scaffolding, not plugin code.
"""

from __future__ import annotations

import array
import struct
import zlib

_TYPECODE = {("u", 8): "B", ("u", 16): "H", ("u", 32): "I", ("i", 16): "h", ("f", 32): "f", ("f", 64): "d"}
_SAMPLE_FORMAT = {"u": 1, "i": 2, "f": 3}


def write_tiff(
    path,
    pixels,  # list of rows; each row a list of pixels; each pixel a tuple of bands
    *,
    kind: str = "u",
    bits: int = 16,
    byte_order: str = "<",
    bigtiff: bool = False,
    tiled: tuple[int, int] | None = None,
    rows_per_strip: int | None = None,
    compression: int = 1,
    predictor: int = 1,
    planar: int = 1,
    epsg: int | None = 32644,
    origin: tuple[float, float] = (500000.0, 1300000.0),
    pixel_size: tuple[float, float] = (30.0, 30.0),
    nodata: str | None = None,
    citation: str | None = None,
    write_overview: bool = False,
) -> None:
    height = len(pixels)
    width = len(pixels[0])
    bands = len(pixels[0][0])
    tc = _TYPECODE[(kind, bits)]
    itemsize = bits // 8
    unsigned = {8: "B", 16: "H", 32: "I", 64: "Q"}[bits]

    def encode_block(rows: list[list[tuple]], block_width: int, band: int | None) -> bytes:
        values = array.array(tc)
        for row in rows:
            padded = row + [row[-1]] * (block_width - len(row)) if len(row) < block_width else row
            for px in padded:
                if band is None:
                    values.extend(px)
                else:
                    values.append(px[band])
        raw = array.array(unsigned, values.tobytes())
        per = bands if band is None else 1
        if predictor == 2:
            mask = (1 << bits) - 1
            row_len = block_width * per
            for r in range(len(rows)):
                start = r * row_len
                for i in range(row_len - 1, per - 1, -1):
                    raw[start + i] = (raw[start + i] - raw[start + i - per]) & mask
        if (byte_order == ">") and itemsize > 1:
            raw.byteswap()
        data = raw.tobytes()
        return zlib.compress(data) if compression in (8, 32946) else data

    planes = [None] if planar == 1 else list(range(bands))
    chunks: list[bytes] = []
    if tiled:
        tw, tl = tiled
        for plane in planes:
            for ty in range(0, height, tl):
                for tx in range(0, width, tw):
                    rows = [r[tx : tx + tw] for r in pixels[ty : ty + tl]]
                    while len(rows) < tl:
                        rows.append(rows[-1])
                    chunks.append(encode_block(rows, tw, plane))
    else:
        rps = rows_per_strip or height
        for plane in planes:
            for y in range(0, height, rps):
                chunks.append(encode_block(pixels[y : y + rps], width, plane))

    # Build tags: (tag, type, values)
    tags: list[tuple[int, int, object]] = [
        (256, 4, [width]),
        (257, 4, [height]),
        (258, 3, [bits] * bands),
        (259, 3, [compression]),
        (262, 3, [1]),
        (277, 3, [bands]),
        (284, 3, [planar]),
        (339, 3, [_SAMPLE_FORMAT[kind]] * bands),
    ]
    if predictor != 1:
        tags.append((317, 3, [predictor]))
    off_type = 16 if bigtiff else 4
    if tiled:
        tags += [(322, 3, [tiled[0]]), (323, 3, [tiled[1]]), (324, off_type, None), (325, off_type, [len(c) for c in chunks])]
    else:
        tags += [(273, off_type, None), (278, 4, [rows_per_strip or height]), (279, off_type, [len(c) for c in chunks])]
    if epsg is not None:
        tags.append((33550, 12, [pixel_size[0], pixel_size[1], 0.0]))
        tags.append((33922, 12, [0.0, 0.0, 0.0, origin[0], origin[1], 0.0]))
        keys = [1, 1, 0, 0]
        entries = [(1024, 0, 1, 1), (1025, 0, 1, 1), (3072, 0, 1, epsg)]
        ascii_params = ""
        if citation:
            ascii_params = citation + "|"
            entries.append((3073, 34737, len(ascii_params), 0))
        entries.sort()
        keys[3] = len(entries)
        for e in entries:
            keys.extend(e)
        tags.append((34735, 3, keys))
        if ascii_params:
            tags.append((34737, 2, ascii_params))
    if nodata is not None:
        tags.append((42113, 2, nodata + "\x00"))
    tags.sort(key=lambda t: t[0])

    fmt = {3: "H", 4: "I", 12: "d", 16: "Q"}
    size = {2: 1, 3: 2, 4: 4, 12: 8, 16: 8}
    bo = byte_order
    header_len = 16 if bigtiff else 8
    entry_len, inline, count_fmt = (20, 8, "Q") if bigtiff else (12, 4, "H")
    ifd_offset = header_len
    ifd_len = (8 if bigtiff else 2) + entry_len * len(tags) + (8 if bigtiff else 4)
    cursor = ifd_offset + ifd_len

    # Lay out: IFD, then out-of-line tag data, then image chunks.
    def value_bytes(typ, values):
        if typ == 2:
            return values.encode("latin-1")
        return struct.pack(bo + fmt[typ] * len(values), *values)

    placeholder_offsets = [0] * len(chunks)
    out_of_line: list[tuple[int, bytes]] = []
    entries_bin = []
    data_cursor = cursor
    resolved = []
    for tag, typ, values in tags:
        if values is None:
            values = placeholder_offsets
        resolved.append((tag, typ, values))
    # first pass sizes
    blobs = []
    for tag, typ, values in resolved:
        b = value_bytes(typ, values)
        blobs.append(b)
        if len(b) > inline:
            data_cursor += len(b) + (len(b) % 2)
    image_start = data_cursor
    offsets = []
    pos = image_start
    for c in chunks:
        offsets.append(pos)
        pos += len(c)
    # second pass with real offsets
    data_cursor = cursor
    body = bytearray()
    for (tag, typ, values), b in zip(resolved, blobs):
        if values is placeholder_offsets:
            b = value_bytes(typ, offsets)
        n = len(values) if typ != 2 else len(b)
        if len(b) <= inline:
            field = b + b"\x00" * (inline - len(b))
        else:
            field = struct.pack(bo + ("Q" if bigtiff else "I"), data_cursor)
            out_of_line.append((data_cursor, b))
            data_cursor += len(b) + (len(b) % 2)
        if bigtiff:
            entries_bin.append(struct.pack(bo + "HHQ", tag, typ, n) + field)
        else:
            entries_bin.append(struct.pack(bo + "HHI", tag, typ, n) + field)

    with open(path, "wb") as fh:
        if bigtiff:
            fh.write((b"II" if bo == "<" else b"MM") + struct.pack(bo + "HHHQ", 43, 8, 0, ifd_offset))
        else:
            fh.write((b"II" if bo == "<" else b"MM") + struct.pack(bo + "HI", 42, ifd_offset))
        fh.write(struct.pack(bo + count_fmt, len(tags)))
        for e in entries_bin:
            fh.write(e)
        fh.write(struct.pack(bo + ("Q" if bigtiff else "I"), 0))
        for where, b in out_of_line:
            assert fh.tell() == where, (fh.tell(), where)
            fh.write(b)
            if len(b) % 2:
                fh.write(b"\x00")
        assert fh.tell() == image_start
        for c in chunks:
            fh.write(c)
