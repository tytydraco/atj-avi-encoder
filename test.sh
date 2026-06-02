#!/usr/bin/env bash
# Regression tests for the production bundle (system ffmpeg only).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
OFFICIAL="${OFFICIAL:-$ROOT/reference/official.avi}"
WORK="$ROOT/.test-work"
FFMPEG="${FFMPEG:-$(command -v ffmpeg)}"
PASS=0
FAIL=0

mkdir -p "$WORK"

ok() { echo "  OK  $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL $1"; FAIL=$((FAIL + 1)); }

echo "=== build ==="
./build.sh

echo "=== mux: official round-trip ==="
if [[ -f "$OFFICIAL" ]]; then
    python3 atj_avi_mux.py "$OFFICIAL" "$WORK/remux.avi" --no-jpeg-rewrite
    os=$(stat -c%s "$OFFICIAL")
    rs=$(stat -c%s "$WORK/remux.avi")
    if [[ "$os" == "$rs" ]]; then ok "remux size $rs"; else fail "remux size want=$os got=$rs"; fi
    python3 patch_avi.py --verify "$WORK/remux.avi" && ok "remux verify" || fail "remux verify"
else
    echo "  SKIP no $OFFICIAL"
fi

echo "=== encode: 2s testsrc tier ==="
DURATION=2 FIT=tier ./make-atj-avi-encoder.sh "$WORK/testsrc.avi"
python3 patch_avi.py --verify "$WORK/testsrc.avi" && ok "encode verify" || fail "encode verify"
read -r pairs v0 <<< "$(python3 -c "
import atj_avi_mux as m
v,a=m.extract(__import__('pathlib').Path('$WORK/testsrc.avi'))
print(len(v), len(v[0]))
")"
if [[ "$pairs" -ge 40 ]]; then ok "encode pairs=$pairs v0=${v0}B"; else fail "encode pairs=$pairs"; fi

echo "=== jpeg: AVI1 header rewrite ==="
if [[ -x "$FFMPEG" ]]; then
    "$FFMPEG" -y -loglevel error -f lavfi -i "testsrc2=size=128x128:rate=25" -t 0.04 \
        -c:v mjpeg -huffman default -flags +bitexact -pix_fmt yuvj420p -g 1 \
        -f avi "$WORK/sys.avi"
    python3 - <<PY && ok "jpeg rewrite AVI1" || fail "jpeg rewrite"
import atj_avi_jpeg as j
import atj_avi_mux as m
from pathlib import Path
frame = m.extract(Path("$WORK/sys.avi"))[0][0]
rew = j.rewrite_jpeg(frame)
assert rew[6:10] == b"AVI1"
assert j.rewrite_jpeg(rew) == rew
PY
fi

echo "=== fit modes ==="
python3 - <<'PY' && ok "fit_scan tier/mod4" || fail "fit_scan"
from atj_avi_jpeg import fit_scan_mod4, fit_scan_tier, scan_length, _entropy_offset
from atj_avi_scan_enc import AtjAviScanEnc
fb = 128 * 128 * 3 // 2
with AtjAviScanEnc(128, 128, 14) as enc:
    j = enc.encode(bytes(fb))
m = fit_scan_mod4(j)
t = fit_scan_tier(j)
assert scan_length(m) % 4 == 1
assert scan_length(t) % 4 == 1
assert len(t) > len(j)
PY

echo
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
