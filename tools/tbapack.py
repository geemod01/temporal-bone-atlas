"""
Writer for the Temporal Bone Atlas data pack (.tba).

Layout (before gzip):
    magic   4 bytes   b"TBA1"
    hlen    uint32 LE length of the JSON header
    header  JSON (utf-8)
    blobs   concatenated binary blobs, each padded to a 4-byte boundary

The header lists every blob with its byte offset (relative to the start of
the blob section) and length, plus dataset metadata, volume geometry, mesh
tables, label ids and landmark points. All coordinates are RAS millimetres.

Volumes are stored C-order [z][y][x] (x fastest). int16 for CT, uint8 for labels.
"""
import gzip
import json
import struct


def _pad4(n):
    return (4 - (n % 4)) % 4


def write_pack(path, header, blobs, level=6):
    """header: dict (will get a 'blobs' table added). blobs: list of (name, bytes)."""
    table = {}
    body = bytearray()
    for name, data in blobs:
        off = len(body)
        body += data
        body += b"\x00" * _pad4(len(data))
        table[name] = {"offset": off, "length": len(data)}
    header = dict(header)
    header["blobs"] = table
    hjson = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw = b"TBA1" + struct.pack("<I", len(hjson)) + hjson
    raw += b"\x00" * _pad4(len(raw))
    raw += bytes(body)
    with gzip.open(path, "wb", compresslevel=level) as f:
        f.write(raw)
    return len(raw)


def read_pack(path):
    """Reads a pack back (used for tests and by the converter)."""
    with gzip.open(path, "rb") as f:
        raw = f.read()
    assert raw[:4] == b"TBA1", "not a TBA pack"
    hlen = struct.unpack("<I", raw[4:8])[0]
    header = json.loads(raw[8:8 + hlen].decode("utf-8"))
    start = 8 + hlen
    start += _pad4(start)
    body = memoryview(raw)[start:]
    blobs = {k: bytes(body[v["offset"]:v["offset"] + v["length"]]) for k, v in header["blobs"].items()}
    return header, blobs
