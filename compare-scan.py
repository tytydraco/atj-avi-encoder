#!/usr/bin/env python3
"""Compare MJPEG scan entropy between a reference AVI and a candidate."""

import hashlib
import struct
import sys
from pathlib import Path

import ruizu_mux as m
from ruizu_jpeg import _entropy_offset


def scan_stats(j: bytes) -> dict:
    off = _entropy_offset(j)
    scan = j[off:]
    return {
        "total": len(j),
        "header": off,
        "scan": len(scan),
        "scan_md5": hashlib.md5(scan).hexdigest(),
        "scan_head": scan[:16].hex(),
    }


def main() -> None:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} reference.avi candidate.avi [max_frames]", file=sys.stderr)
        sys.exit(2)
    ref_p, cand_p = Path(sys.argv[1]), Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    ref_v, _ = m.extract(ref_p)
    cand_v, _ = m.extract(cand_p)
    print(f"reference: {ref_p.name}  frames={len(ref_v)}")
    print(f"candidate: {cand_p.name}  frames={len(cand_v)}")
    print()
    for i in range(min(n, len(ref_v), len(cand_v))):
        r, c = scan_stats(ref_v[i]), scan_stats(cand_v[i])
        hdr_match = ref_v[i][: r["header"]] == cand_v[i][: c["header"]]
        scan_match = ref_v[i][r["header"] :] == cand_v[i][c["header"] :]
        print(
            f"f{i:03d}  ref scan={r['scan']:5d} md5={r['scan_md5'][:12]}  "
            f"cand scan={c['scan']:5d} md5={c['scan_md5'][:12]}  "
            f"hdr={hdr_match} scan_eq={scan_match}"
        )


if __name__ == "__main__":
    main()
