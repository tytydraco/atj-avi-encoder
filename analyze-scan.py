#!/usr/bin/env python3
"""Deep analysis of MJPEG scan differences — guides encoder RE."""

import hashlib
import re
import struct
import sys
from pathlib import Path

import atj_avi_mux as m
from atj_avi_jpeg import _entropy_offset, LUMA_Q, CHROMA_Q


def dqt_tables(frame: bytes) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    i = 2
    while i < len(frame) - 1:
        if frame[i] != 0xFF:
            i += 1
            continue
        mk = frame[i + 1]
        if mk == 0xDA:
            break
        ln = struct.unpack_from(">H", frame, i + 2)[0]
        if mk == 0xDB and ln >= 65:
            out[frame[i + 4] & 0xF] = frame[i + 5 : i + 5 + 64]
        i += 2 + ln
    return out


def scan_profile(j: bytes) -> dict:
    off = _entropy_offset(j)
    scan = j[off:]
    eoi = scan.rfind(b"\xff\xd9")
    body = scan[:eoi] if eoi >= 0 else scan
    return {
        "total": len(j),
        "hdr": off,
        "scan": len(body),
        "ff_bytes": body.count(0xFF),
        "rst": len(re.findall(rb"\xff(?:d[0-7]|00)", body[:8000])),
        "md5": hashlib.md5(body).hexdigest()[:16],
        "head": body[:12].hex(),
        "tail": body[-8:].hex() if len(body) >= 8 else body.hex(),
    }


def main() -> None:
    root = Path(__file__).resolve().parent
    ref = root / "official.avi"
    paths = [ref]
    for p in [
        root / ".atj-avi-encoder-work/music/element_avi_mjpeg.avi",
        root / ".atj-avi-encoder-work/music/element.avi",
    ]:
        if p.is_file():
            paths.append(p)

    print("=== DQT reference (atj_avi_jpeg constants) ===")
    print("luma sum", sum(LUMA_Q), "chroma sum", sum(CHROMA_Q))
    print()

    for path in paths:
        v, _ = m.extract(path)
        print(f"=== {path.name} frames={len(v)} ===")
        for i in range(min(3, len(v))):
            prof = scan_profile(v[i])
            dq = dqt_tables(v[i])
            luma = dq.get(0, b"")
            chroma = dq.get(1, b"")
            print(
                f"  f{i}: total={prof['total']} hdr={prof['hdr']} scan={prof['scan']} "
                f"rst={prof['rst']} ff={prof['ff_bytes']} md5={prof['md5']}"
            )
            if luma:
                print(f"       luma[:8]={list(luma[:8])} sum={sum(luma)}")
        print()

    if len(sys.argv) > 1:
        cand = Path(sys.argv[1])
        if cand.is_file():
            rv, _ = m.extract(ref)
            cv, _ = m.extract(cand)
            print(f"=== vs official: {cand.name} ===")
            for i in range(min(5, len(rv), len(cv))):
                ro, co = scan_profile(rv[i]), scan_profile(cv[i])
                ratio = co["scan"] / ro["scan"] if ro["scan"] else 0
                print(
                    f"  f{i}: official_scan={ro['scan']} cand_scan={co['scan']} "
                    f"ratio={ratio:.2f} hdr_match={rv[i][:ro['hdr']]==cv[i][:co['hdr']]}"
                )


if __name__ == "__main__":
    main()
