#!/usr/bin/env python3
"""Mux ruizu AVI with per-frame MJPEG from a scan encoder backend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

import ruizu_mux as m
from ruizu_jpeg import fit_scan_frame


def build(
    audio_src: Path,
    yuv: bytes,
    width: int,
    height: int,
    nframes: int,
    encode_frame: Callable[[bytes], bytes],
    fit_frame: Callable[[bytes, int], bytes],
    dst: Path,
    trim: bool = True,
) -> None:
    root = Path(__file__).resolve().parent
    frame_bytes = width * height * 3 // 2
    need = frame_bytes * nframes
    if len(yuv) < need:
        raise ValueError(f"YUV too short: have {len(yuv)}, need {need}")

    _, audios = m.extract(audio_src)
    videos: list[bytes] = []
    for i in range(nframes):
        off = i * frame_bytes
        raw = encode_frame(yuv[off : off + frame_bytes])
        videos.append(fit_frame(raw, i))

    hdr, frames_off, aud_len_off = m.load_header(root / "ruizu_hdrl.bin")
    v, a = m.pair_streams(videos, audios, trim=trim)
    dst.write_bytes(m.mux(v, a, hdr, frames_off, aud_len_off))
    sizes = sorted(set(len(x) for x in v[:20]))
    print(f"wrote {dst}  pairs={len(v)}  v0={len(v[0])}B  sizes(sample)={sizes[:6]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("backend", choices=("cjpeg", "turbo", "ffmpeg_frames"))
    p.add_argument("audio_src", type=Path)
    p.add_argument("yuv", type=Path)
    p.add_argument("dst", type=Path)
    p.add_argument("-W", "--width", type=int, default=128)
    p.add_argument("-H", "--height", type=int, default=128)
    p.add_argument("-n", "--frames", type=int, required=True)
    p.add_argument("-q", "--quality", type=int, default=14)
    p.add_argument(
        "--fit",
        choices=("none", "mod4", "tier", "fixed", "reference"),
        default="tier",
        help="per-frame idx1 sizing (reference=use --ref-avi frame sizes)",
    )
    p.add_argument("--fit-size", type=int, default=11568, help="for fixed mode")
    p.add_argument("--ref-avi", type=Path, help="reference AVI for per-frame sizes")
    p.add_argument("--ffmpeg-avi", type=Path, help="for ffmpeg_frames backend")
    args = p.parse_args()

    yuv = args.yuv.read_bytes()
    ref_sizes: list[int] | None = None
    if args.fit == "reference":
        if not args.ref_avi:
            print("--fit reference requires --ref-avi", file=sys.stderr)
            sys.exit(2)
        ref_v, _ = m.extract(args.ref_avi)
        ref_sizes = [len(f) for f in ref_v]

    def fit_frame(jpeg: bytes, index: int) -> bytes:
        if args.fit == "reference":
            assert ref_sizes is not None
            size = ref_sizes[min(index, len(ref_sizes) - 1)]
            return fit_scan_frame(jpeg, "reference", ref_size=size)
        if args.fit == "fixed":
            return fit_scan_frame(jpeg, "fixed", ref_size=args.fit_size)
        return fit_scan_frame(jpeg, args.fit)

    if args.backend == "cjpeg":
        from ruizu_scan_enc import encode_cjpeg

        def enc(chunk: bytes) -> bytes:
            return encode_cjpeg(chunk, args.width, args.height, args.quality)

    elif args.backend == "turbo":
        from ruizu_scan_enc import RuizuScanEnc

        scanner = RuizuScanEnc(args.width, args.height, args.quality)

        def enc(chunk: bytes) -> bytes:
            return scanner.encode(chunk)

    else:
        if not args.ffmpeg_avi:
            print("ffmpeg_frames requires --ffmpeg-avi", file=sys.stderr)
            sys.exit(2)
        ff_frames, _ = m.extract(args.ffmpeg_avi)
        idx = 0

        def enc(_chunk: bytes) -> bytes:
            nonlocal idx
            frame = ff_frames[min(idx, len(ff_frames) - 1)]
            idx += 1
            return frame

    try:
        build(args.audio_src, yuv, args.width, args.height, args.frames, enc, fit_frame, args.dst)
    finally:
        if args.backend == "turbo":
            scanner.close()


if __name__ == "__main__":
    main()
