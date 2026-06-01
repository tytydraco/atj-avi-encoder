#!/usr/bin/env python3
"""Composable in-place AVI post-processor for Ruizu device compatibility tests."""

import argparse
import struct
import sys
from pathlib import Path

from ruizu_jpeg import rewrite_jpeg

IMA_ADPCM = 0x0011
RUIZU_BYTE_RATE = 11100
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


def extract_movi_chunks(data: bytes) -> tuple[int, list[tuple[bytes, bytes]]]:
    base = find_movi(data) + 8
    idx = data.find(b"idx1", base)
    if idx < 0:
        raise ValueError("idx1 not found")
    body = data[idx + 8 : idx + 8 + struct.unpack_from("<I", data, idx + 4)[0]]
    chunks: list[tuple[bytes, bytes]] = []
    for i in range(0, len(body) - 15, 16):
        tag = body[i : i + 4]
        off, size = struct.unpack_from("<II", body, i + 8)
        payload = data[base + off + 8 : base + off + 8 + size]
        chunks.append((tag, payload))
    return base, chunks


def rebuild_tail(chunks: list[tuple[bytes, bytes]]) -> bytes:
    movi = bytearray()
    idx = bytearray()
    off = 4
    for tag, payload in chunks:
        idx.extend(tag + u32(IDX_KEY) + u32(off) + u32(len(payload)))
        movi.extend(tag + u32(len(payload)) + payload)
        if len(payload) & 1:
            movi.append(0)
        off += 8 + len(payload) + (len(payload) & 1)
    inner = b"movi" + bytes(movi)
    return b"LIST" + u32(len(inner)) + inner + b"idx1" + u32(len(idx)) + idx


def patch_jpeg(data: bytes) -> bytes:
    _, chunks = extract_movi_chunks(data)
    out_chunks: list[tuple[bytes, bytes]] = []
    for tag, payload in chunks:
        if tag == b"00dc":
            payload = rewrite_jpeg(payload)
        out_chunks.append((tag, payload))
    head = data[: find_movi(data)]
    tail = rebuild_tail(out_chunks)
    out = bytearray(head + tail)
    struct.pack_into("<I", out, 4, len(out) - 8)
    return bytes(out)


def patch_audio_strf(data: bytes) -> bytes:
    out = bytearray(data)
    i = 0
    patched = 0
    while i < len(out) - 8:
        if out[i : i + 4] == b"strf":
            chunk_size = struct.unpack_from("<I", out, i + 4)[0]
            body = i + 8
            if chunk_size >= 16 and struct.unpack_from("<H", out, body)[0] == IMA_ADPCM:
                struct.pack_into("<I", out, body + 8, RUIZU_BYTE_RATE)
                patched += 1
            i += 8 + chunk_size + (chunk_size & 1)
        else:
            i += 1
    if patched == 0:
        raise ValueError("no IMA ADPCM strf chunk found")
    return bytes(out)


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    info: dict = {"path": str(path), "size": len(data)}
    idx = data.find(b"idx1")
    info["idx1_count"] = (
        struct.unpack_from("<I", data, idx + 4)[0] // 16 if idx >= 0 else 0
    )
    info["app0"] = None
    try:
        _, chunks = extract_movi_chunks(data)
        for tag, payload in chunks:
            if tag == b"00dc" and len(payload) >= 10:
                info["app0"] = payload[6:10].decode("latin1", "replace")
                break
    except ValueError:
        pass
    i = 0
    while i < len(data) - 8:
        if data[i : i + 4] == b"strf":
            chunk_size = struct.unpack_from("<I", data, i + 4)[0]
            body = data[i + 8 : i + 8 + chunk_size]
            if len(body) >= 16 and struct.unpack_from("<H", body, 0)[0] == IMA_ADPCM:
                info["audio_strf_size"] = chunk_size
                info["audio_byte_rate"] = struct.unpack_from("<I", body, 8)[0]
                break
            i += 8 + chunk_size + (chunk_size & 1)
        else:
            i += 1
    return info


def verify(path: Path, expect_avi1: bool = False, expect_byte_rate: int | None = None) -> int:
    info = inspect(path)
    ok = True
    print(f"{path.name}: app0={info.get('app0')!r} idx1={info.get('idx1_count')} "
          f"strf={info.get('audio_strf_size')} byte_rate={info.get('audio_byte_rate')}")
    if expect_avi1 and info.get("app0") != "AVI1":
        print("  FAIL: expected APP0 AVI1", file=sys.stderr)
        ok = False
    if expect_byte_rate is not None and info.get("audio_byte_rate") != expect_byte_rate:
        print(f"  FAIL: expected byte_rate {expect_byte_rate}", file=sys.stderr)
        ok = False
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch Ruizu-incompatible AVI headers in place")
    ap.add_argument("infile")
    ap.add_argument("outfile", nargs="?")
    ap.add_argument("--jpeg", action="store_true", help="rewrite 00dc MJPEG to AVI1 layout")
    ap.add_argument("--audio-strf", action="store_true", help="fix IMA ADPCM byte_rate to 11100")
    ap.add_argument("--verify", action="store_true", help="print structure summary and exit")
    ap.add_argument("--expect-avi1", action="store_true")
    ap.add_argument("--expect-byte-rate", type=int)
    args = ap.parse_args()

    src = Path(args.infile)
    if args.verify and not args.outfile:
        sys.exit(verify(src, args.expect_avi1, args.expect_byte_rate))

    if not args.outfile:
        ap.error("outfile required unless --verify without expect flags")
    dst = Path(args.outfile)

    if not args.jpeg and not args.audio_strf:
        ap.error("specify at least one of --jpeg or --audio-strf")

    data = src.read_bytes()
    if args.jpeg:
        data = patch_jpeg(data)
    if args.audio_strf:
        data = patch_audio_strf(data)
    dst.write_bytes(data)
    print(f"wrote {dst} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
