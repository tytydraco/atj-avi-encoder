# atj-avi-encoder

Native encoder for ATJ/Actions-chip AMV/AVI players (128×128 MJPEG + IMA ADPCM in
ATJ AVI-specific AVI layout). No Wine or vendor DLL required.

Device-validated pipeline (2025): **libjpeg-turbo scan** + **623-byte AVI1 header graft**

- **per-frame idx1 sizing** (`--fit tier`) + **`atj_avi_mux.py`**.

## Requirements

- **Python 3.10+** (stdlib only for encode/mux)
- **ffmpeg** — decode/scale audio & video
- **libjpeg-turbo** — `libturbojpeg` development headers (`pacman -S libjpeg-turbo`,
  `apt install libturbojpeg0-dev`, etc.)
- **gcc**, **make**

Optional: **cjpeg** / **djpeg** (IJG) for reference encode path in `atj_avi_scan_enc.py`.

## Quick start

```bash
./build.sh          # compile libatj_avi_scan.so + run tests
./make-atj-avi-encoder.sh out.avi

# From your own video:
SOURCE=video.mp4 SS=0 DURATION=60 ./make-atj-avi-encoder.sh music.amv
```

### Environment variables (`make-atj-avi-encoder.sh`)

| Variable   | Default                  | Description                                      |
| ---------- | ------------------------ | ------------------------------------------------ |
| `SOURCE`   | _(testsrc)_              | Input video file                                 |
| `SS`       | `0`                      | Start time (seconds)                             |
| `DURATION` | `30`                     | Clip length (seconds)                            |
| `QUALITY`  | `14`                     | Vendor quality tier 14–22 (use **14** on device) |
| `FIT`      | `tier`                   | `tier`, `mod4`, `none`, `fixed`, `reference`     |
| `REF_AVI`  | `reference/official.avi` | For `FIT=reference` re-encode only               |

**Production:** `FIT=tier` (default) for new content.  
**Re-encode:** `FIT=reference` only when pixels match `REF_AVI`.

Video: 128×128 @ 542/25 fps (~21.68 fps). Audio: mono 22050 Hz IMA ADPCM, 512-byte blocks.

## Layout

```
atj-avi-encoder/
├── README.md
├── build.sh / test.sh / make-atj-avi-encoder.sh
├── atj_avi_mux.py          # AVI muxer (hdrl + idx1 interleave)
├── atj_avi_jpeg.py         # AVI1 header rewrite + frame sizing
├── atj_avi_scan_enc.py     # ctypes wrapper → libatj_avi_scan.so
├── build_scan_mjpeg.py   # Low-level encode+mux API
├── patch_avi.py          # Verify / patch AVI metadata
├── atj_avi_hdrl.bin        # 316-byte header template
├── atj_avi_scan/           # Native MJPEG scan encoder (C)
├── reference/official.avi
└── docs/                 # Muxer porting + encoder history
```

## Low-level API

```bash
# Decode to YUV + element AVI (for audio idx1 template), then:
python3 build_scan_mjpeg.py turbo element.avi frames.yuv out.avi \
    -n 650 -q 14 --fit tier
```

## Diagnostics

```bash
python3 patch_avi.py --verify out.avi
python3 compare-avi.py reference/official.avi out.avi
python3 analyze-scan.py out.avi
python3 compare-scan.py reference/official.avi out.avi 5
```

## Troubleshooting

| Symptom                        | Fix                                                                     |
| ------------------------------ | ----------------------------------------------------------------------- |
| `libatj_avi_scan.so not found` | Run `./build.sh`                                                        |
| Format error after frame 1     | Use native turbo path (`make-atj-avi-encoder.sh`), not raw ffmpeg MJPEG |
| Plays f0 then skips            | Wrong `FIT=reference` sizes for different content — use `tier`          |
| Oversaturated colors           | Lower `QUALITY` (stay at 14)                                            |

See `docs/VENDOR-ENCODER.md` for reverse-engineering history and `docs/MUXER-PORT.md`
for muxer porting notes.

## Credits

This project was a collaboration. An honest split:

**Me** — provided the ATJ AVI player, `official.avi` / `music.webm` references, the AMV
Converter vendor package for RE, and dozens of round-by-round device test reports
(format error vs crash vs perfect). Also set the goal: noWine, no DLL wrappers, full
native reimplementation.

**Cursor Agent (Auto / Claude)** — most of the implementation and analysis:
`atj_avi_mux.py`, `atj_avi_jpeg.py`, `libatj_avi_scan` (C + Python ctypes), bisection
batches (R6–R10), scan-size / idx1-sizing experiments, `make-atj-avi-encoder.sh`, docs, and
this production bundle. Reverse-engineering notes from `AVI_EncDLL.dll` and proxy
logs; the breakthrough that per-frame idx1 sizing (`--fit tier`) unlocks playback
came from interpreting device results together with those tests.

**Prior art / tools** — FFmpeg (decode/mux research), libjpeg-turbo, IJG cjpeg;
ATJ AVI/Actions vendor `AVI_EncDLL.dll` and AMVConverter as the ground-truth reference
(not shipped here).
