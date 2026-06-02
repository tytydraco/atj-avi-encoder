#!/usr/bin/env python3
"""ATJ AVI muxer: copy official.avi hdrl, interleave 00dc/01wb, write idx1."""

import struct
import sys
from pathlib import Path

from atj_avi_jpeg import rewrite_jpeg

JPEG_MODES = ("full", "minimal", "none")

AUD_LEN_MUL = 258
AUD_BLOCK_SIZE = 512
NULL_ADPCM_BLOCK = bytes(AUD_BLOCK_SIZE)  # silent mono IMA ADPCM @ 22050 Hz
IDX_KEY = 0x10


def u32(n: int) -> bytes:
    return struct.pack("<I", n)


def find_movi(data: bytes) -> int:
    p = 0
    while True:
        p = data.find(b"LIST", p)
        if p < 0:
            raise ValueError("movi LIST not found")
        if data[p + 8 : p + 12] == b"movi":
            return p
        p += 4


def load_header(template: Path, width: int = 128, height: int = 128) -> tuple[bytes, int, int]:
    hdr = bytearray(template.read_bytes())
    if len(hdr) < 200 or hdr[:4] != b"RIFF":
        raise ValueError(f"bad header template: {template}")
    avih = hdr.index(b"avih") + 8
    strf = hdr.index(b"strf") + 8
    aud_len = hdr.rindex(b"strh") + 8 + 32
    struct.pack_into("<I", hdr, avih + 32, width)
    struct.pack_into("<I", hdr, avih + 36, height)
    struct.pack_into("<I", hdr, strf + 4, width)
    struct.pack_into("<I", hdr, strf + 8, height)
    struct.pack_into("<I", hdr, strf + 20, width * height * 3)
    return bytes(hdr), avih + 16, aud_len


def patch_header(hdr: bytes, frames_off: int, aud_len_off: int, n: int) -> bytes:
    out = bytearray(hdr)
    struct.pack_into("<I", out, frames_off, n)
    struct.pack_into("<I", out, aud_len_off, n * AUD_LEN_MUL)
    return bytes(out)


def extract(path: Path) -> tuple[list[bytes], list[bytes]]:
    data = path.read_bytes()
    base = find_movi(data) + 8
    idx = data.find(b"idx1", base)
    if idx < 0:
        raise ValueError(f"no idx1 in {path}")
    body = data[idx + 8 : idx + 8 + struct.unpack_from("<I", data, idx + 4)[0]]
    v, a = [], []
    for i in range(0, len(body) - 15, 16):
        tag, off, size = body[i : i + 4], *struct.unpack_from("<II", body, i + 8)
        payload = data[base + off + 8 : base + off + 8 + size]
        if tag == b"00dc":
            v.append(payload)
        elif tag == b"01wb":
            a.append(payload)
    return v, a


def pair_streams(v: list[bytes], a: list[bytes], trim: bool) -> tuple[list[bytes], list[bytes]]:
    if not v:
        raise ValueError("need at least one video frame")
    v, a = list(v), list(a)
    if not a:
        return v, [NULL_ADPCM_BLOCK] * len(v)
    if trim:
        n = min(len(v), len(a))
        return v[:n], a[:n]
    while len(a) > len(v):
        v.append(v[-1])
    while len(v) > len(a):
        a.append(NULL_ADPCM_BLOCK)
    return v, a


def mux(v: list[bytes], a: list[bytes], hdr: bytes, frames_off: int, aud_len_off: int) -> bytes:
    n = len(v)
    out = bytearray(patch_header(hdr, frames_off, aud_len_off, n))
    movi = bytearray()
    idx = bytearray()
    off = 4
    for i in range(n):
        for tag, payload in ((b"00dc", v[i]), (b"01wb", a[i])):
            idx.extend(tag + u32(IDX_KEY) + u32(off) + u32(len(payload)))
            movi.extend(tag + u32(len(payload)) + payload)
            if len(payload) & 1:
                movi.append(0)
            off += 8 + len(payload) + (len(payload) & 1)
    inner = b"movi" + bytes(movi)
    out.extend(b"LIST" + u32(len(inner)) + inner)
    out.extend(b"idx1" + u32(len(idx)) + idx)
    struct.pack_into("<I", out, 4, len(out) - 8)
    return bytes(out)


def pad_leading_dup(videos: list[bytes], n: int = 8) -> list[bytes]:
    if not videos or n <= 1:
        return videos
    lead = min(n, len(videos))
    f0 = videos[0]
    return [f0] * lead + videos[lead:]


def main() -> None:
    if len(sys.argv) < 3:
        print(
            f"usage: {sys.argv[0]} <source.avi> <out.avi> [--trim] [--no-jpeg-rewrite]"
            f" [--jpeg-mode full|minimal] [--pad-lead N]",
            file=sys.stderr,
        )
        sys.exit(2)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    extra = sys.argv[3:]
    trim = "--trim" in extra
    rewrite = "--no-jpeg-rewrite" not in extra
    jpeg_mode = "full"
    pad_lead = 0
    i = 0
    while i < len(extra):
        arg = extra[i]
        if arg == "--jpeg-mode" and i + 1 < len(extra):
            jpeg_mode = extra[i + 1]
            i += 2
        elif arg == "--pad-lead" and i + 1 < len(extra):
            pad_lead = int(extra[i + 1])
            i += 2
        else:
            i += 1
    if jpeg_mode not in JPEG_MODES:
        sys.exit(f"bad --jpeg-mode: {jpeg_mode}")
    root = Path(__file__).resolve().parent
    tpl = root / "atj_avi_hdrl.bin"
    if not tpl.is_file():
        tpl = root / "official.avi"
        if tpl.is_file():
            data = tpl.read_bytes()
            movi = find_movi(data)
            tpl.write_bytes(data[:movi])  # one-time extract for older checkouts
            tpl = root / "atj_avi_hdrl.bin"
    if not tpl.is_file():
        sys.exit("header template missing: atj_avi_hdrl.bin (or official.avi to generate it)")
    hdr, frames_off, aud_len_off = load_header(tpl)
    videos, audios = extract(src)
    if rewrite and jpeg_mode != "none":
        videos = [rewrite_jpeg(v, jpeg_mode) for v in videos]
    if pad_lead:
        videos = pad_leading_dup(videos, pad_lead)
    v, a = pair_streams(videos, audios, trim)
    data = mux(v, a, hdr, frames_off, aud_len_off)
    dst.write_bytes(data)
    note = " (trimmed)" if trim else ""
    if pad_lead:
        note += f" (pad-lead={pad_lead})"
    if rewrite and jpeg_mode != "full":
        note += f" (jpeg={jpeg_mode})"
    print(f"wrote {dst}  pairs={len(v)}  bytes={len(data)}{note}")


if __name__ == "__main__":
    main()
