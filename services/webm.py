# app/services/webm.py
"""Fill in the Duration that browser-recorded WebM files leave at zero.

Chrome's MediaRecorder (libwebm) streams the file before its length is known, so
Segment > Info > Duration is written as 0.0 and players show a seek bar that
jumps to the end. We know the length (the browser sends duration_ms), so the
value is overwritten in place: same size, same offsets, so Range requests and
seeking keep working. Stored audio is never changed; this runs on the way out.
"""
import math
import struct

_EBML, _SEGMENT, _INFO = 0x1A45DFA3, 0x18538067, 0x1549A966
_TRACKS, _CLUSTER = 0x1654AE6B, 0x1F43B675
_TIMECODE_SCALE, _DURATION = 0x2AD7B1, 0x4489


def _vint(data, pos, keep_marker):
    """EBML variable-length integer at pos -> (value, next pos, is "unknown size")."""
    length = 9 - data[pos].bit_length()
    if not 1 <= length <= 8 or pos + length > len(data):
        raise ValueError("bad vint")
    value = data[pos] if keep_marker else data[pos] & ((1 << (8 - length)) - 1)
    for b in data[pos + 1:pos + length]:
        value = (value << 8) | b
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, pos + length, unknown


def _element(data, pos):
    """Element header at pos -> (id, body start, body size or None if unknown)."""
    eid, pos, _ = _vint(data, pos, keep_marker=True)
    size, pos, unknown = _vint(data, pos, keep_marker=False)
    return eid, pos, None if unknown else size


def with_duration(data: bytes, duration_ms) -> bytes:
    """data with a zero WebM Duration set to duration_ms; anything else unchanged."""
    if not duration_ms or duration_ms <= 0:
        return data
    try:
        eid, body, size = _element(data, 0)
        if eid != _EBML or size is None:
            return data
        eid, pos, _ = _element(data, body + size)
        if eid != _SEGMENT:
            return data
        while True:  # Segment children up to Info (SeekHead / Void may come first)
            eid, body, size = _element(data, pos)
            if size is None or eid in (_TRACKS, _CLUSTER):
                return data
            if eid == _INFO:
                break
            pos = body + size
        scale, duration_at, duration_size = 1_000_000, None, None
        pos, end = body, body + size
        while pos < end:
            eid, value_at, n = _element(data, pos)
            if n is None:
                return data
            if eid == _TIMECODE_SCALE:
                scale = int.from_bytes(data[value_at:value_at + n], "big")
            elif eid == _DURATION:
                duration_at, duration_size = value_at, n
            pos = value_at + n
        if (duration_at is None or duration_size not in (4, 8) or not scale
                or duration_at + duration_size > len(data)):
            return data
        fmt = ">d" if duration_size == 8 else ">f"
        current = struct.unpack(fmt, data[duration_at:duration_at + duration_size])[0]
        if math.isfinite(current) and current > 0:
            return data
        patched = struct.pack(fmt, duration_ms * 1_000_000 / scale)
        return data[:duration_at] + patched + data[duration_at + duration_size:]
    except (ValueError, IndexError, struct.error):
        return data
