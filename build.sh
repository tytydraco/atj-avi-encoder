#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== check dependencies ==="
missing=0
for cmd in python3 ffmpeg cc make; do
    if ! command -v "$cmd" >/dev/null; then
        echo "error: missing $cmd" >&2
        missing=1
    fi
done
if ! pkg-config --exists libturbojpeg 2>/dev/null && \
   ! ldconfig -p 2>/dev/null | grep -q turbojpeg; then
    echo "warning: libturbojpeg not found via pkg-config (link may still work)" >&2
fi
[[ "$missing" -eq 0 ]] || exit 1

echo "=== build libatj_avi_scan ==="
make -C atj_avi_scan clean all

echo "=== verify library ==="
python3 - <<'PY'
from pathlib import Path
from atj_avi_scan_enc import AtjAviScanEnc, LIB
assert LIB.is_file(), LIB
fb = 128 * 128 * 3 // 2
with AtjAviScanEnc(128, 128, 14) as enc:
    j = enc.encode(bytes(fb))
assert j[:2] == b"\xff\xd8" and j[6:10] == b"AVI1"
print(f"OK  libatj_avi_scan  frame0={len(j)}B  lib={LIB}")
PY

echo "build OK"
