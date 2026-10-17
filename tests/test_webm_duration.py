import struct

from services.webm import with_duration

# Header of a real Chrome MediaRecorder take (libwebm, "QTmuxingAppLibWebM-0.0.1")
# up to the end of Segment > Info: Duration is present but 0.0. No audio data.
CHROME_HEADER = bytes.fromhex(
    "1a45dfa3010000000000001f4286810142f7810142f2810442f381084282847765626d"
    "42878102428581021853806701ffffffffffffff114d9b7401000000000000001549a966"
    "01000000000000492ad7b1830f42404489880000000000000000"
    "4d809851546d7578696e674170704c69625765624d2d302e302e31"
    "574199515477726974696e674170704c69625765624d2d302e302e31"
)
TAIL = bytes.fromhex("1654ae6b0100000000000060ae") + b"\x00" * 64  # start of Tracks
WEBM = CHROME_HEADER + TAIL
DURATION_AT = 89  # Info body starts at 79; TimecodeScale (7 bytes), then 44 89 88


def _duration(data):
    return struct.unpack(">d", data[DURATION_AT:DURATION_AT + 8])[0]


def test_zero_duration_is_filled_in_place():
    assert _duration(WEBM) == 0.0
    out = with_duration(WEBM, 10416)
    assert _duration(out) == 10416.0  # TimecodeScale 1,000,000 ns -> milliseconds
    assert len(out) == len(WEBM)  # same offsets: Range requests stay valid
    assert out[:DURATION_AT] == WEBM[:DURATION_AT]
    assert out[DURATION_AT + 8:] == WEBM[DURATION_AT + 8:]


def test_other_timecode_scale_is_respected():
    data = WEBM.replace(bytes.fromhex("2ad7b1830f4240"), bytes.fromhex("2ad7b183"
                                                                     "1e8480"))  # 2,000,000
    assert _duration(with_duration(data, 1000)) == 500.0


def test_existing_duration_is_kept():
    data = WEBM[:DURATION_AT] + struct.pack(">d", 777.0) + WEBM[DURATION_AT + 8:]
    assert with_duration(data, 10416) == data


def test_unusable_input_is_returned_unchanged():
    for data in (b"", b"\x00\x00\x00\x18ftypmp42", b"OggS\x00\x02", WEBM[:85],
                 b"\x1a\x45\xdf\xa3\x00"):
        assert with_duration(data, 10416) == data
    for missing in (None, 0, -5):
        assert with_duration(WEBM, missing) == WEBM
