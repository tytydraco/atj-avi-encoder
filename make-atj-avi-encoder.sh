#!/usr/bin/env bash
# Encode ATJ AVI: native turbo scan + per-frame idx1 sizing + atj_avi_mux.
#
# Examples:
#   ./make-atj-avi-encoder.sh out.avi
#   SOURCE=music.webm DURATION=60 SS=10 ./make-atj-avi-encoder.sh music.avi
#   FIT=reference ./make-atj-avi-encoder.sh reenc.avi   # re-encode same pixels as official.avi only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$ROOT/atj-avi-encoder-custom.avi}"
SOURCE="${SOURCE:-}"
DURATION="${DURATION:-30}"
SS="${SS:-0}"
QUALITY="${QUALITY:-14}"
FIT="${FIT:-tier}"          # none | mod4 | tier | fixed | reference
FIT_SIZE="${FIT_SIZE:-11568}"
REF_AVI="${REF_AVI:-}"
if [[ -z "$REF_AVI" ]]; then
    if [[ -f "$ROOT/reference/official.avi" ]]; then
        REF_AVI="$ROOT/reference/official.avi"
    else
        REF_AVI="$ROOT/official.avi"
    fi
fi
WORK="${ATJ_AVI_ENCODER_WORK:-$ROOT/.atj-avi-encoder-work}"
ELEMENT="$WORK/element.avi"
YUV="$WORK/element.yuv"
DECODE_FFMPEG="${DECODE_FFMPEG:-/usr/bin/ffmpeg}"
VF="scale=128:128:flags=bilinear,fps=542/25"
AF="pan=mono|c0=0.5*c0+0.5*c1,aresample=22050"

if [[ ! -x "$DECODE_FFMPEG" ]]; then
    DECODE_FFMPEG="$(command -v ffmpeg || true)"
fi
if [[ ! -x "$DECODE_FFMPEG" ]]; then
    echo "error: ffmpeg not found" >&2
    exit 1
fi

mkdir -p "$WORK"
make -C "$ROOT/atj_avi_scan" -s

NFRAMES=$((DURATION * 542 / 25))
SS_ARGS=()
if [[ "$SS" != "0" ]]; then
    SS_ARGS=(-ss "$SS")
fi

if [[ -n "$SOURCE" ]]; then
    if [[ ! -f "$SOURCE" ]]; then
        echo "error: SOURCE not found: $SOURCE" >&2
        exit 1
    fi
    echo "=== decode ${DURATION}s from $SOURCE (ss=${SS}s) ==="
    "$DECODE_FFMPEG" -y -loglevel warning "${SS_ARGS[@]}" -i "$SOURCE" -t "$DURATION" \
        -vf "$VF" -pix_fmt yuvj420p -c:v mjpeg -g 1 \
        -af "$AF" -c:a adpcm_ima_wav -ac 1 -ar 22050 -block_size 512 "$ELEMENT"
    "$DECODE_FFMPEG" -y -loglevel warning "${SS_ARGS[@]}" -i "$SOURCE" -t "$DURATION" \
        -vf "$VF" -an -c:v rawvideo -pix_fmt yuv420p -f rawvideo "$YUV"
else
    echo "=== decode ${DURATION}s testsrc → YUV + ADPCM element ==="
    "$DECODE_FFMPEG" -y -loglevel warning \
        -f lavfi -i "testsrc2=size=128x128:rate=542/25" \
        -f lavfi -i "sine=frequency=1000:sample_rate=22050" \
        -t "$DURATION" \
        -c:v mjpeg -pix_fmt yuvj420p -g 1 \
        -c:a adpcm_ima_wav -ac 1 -ar 22050 -block_size 512 \
        "$ELEMENT"
    "$DECODE_FFMPEG" -y -loglevel warning \
        -f lavfi -i "testsrc2=size=128x128:rate=542/25" \
        -t "$DURATION" \
        -c:v rawvideo -pix_fmt yuv420p -f rawvideo "$YUV"
fi

FIT_ARGS=(--fit "$FIT")
if [[ "$FIT" == "fixed" ]]; then
    FIT_ARGS+=(--fit-size "$FIT_SIZE")
elif [[ "$FIT" == "reference" ]]; then
    FIT_ARGS+=(--ref-avi "$REF_AVI")
fi

echo "=== encode turbo q=$QUALITY fit=$FIT ==="
python3 "$ROOT/build_scan_mjpeg.py" turbo "$ELEMENT" "$YUV" "$OUT" \
    -n "$NFRAMES" -q "$QUALITY" "${FIT_ARGS[@]}"

python3 "$ROOT/patch_avi.py" --verify "$OUT"
echo "Output: $OUT"
