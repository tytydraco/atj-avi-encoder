# ATJ AVI vendor MJPEG encoder bridge

Device playback requires **vendor entropy-coded MJPEG scans**, not just matching
headers. Round 4 confirmed:

| Component | Status | Tool |
|-----------|--------|------|
| AVI container (hdrl, idx1, interleave) | Solved | `atj_avi_mux.py` |
| JPEG headers (623 B, APP0 `AVI1`, DQT/DHT) | Solved | `-avi_mjpeg 1` or `atj_avi_jpeg.py` |
| JPEG scan bitstream (~11 KB/frame) | **Vendor only** | `AVI_EncDLL.dll` |

Official video + any audio plays perfectly (`01_official_video_music_audio.avi`).
FFmpeg/cjpeg scans fail after frame 1 even when headers are byte-identical.

## Pipeline

```
source (any format)
    │
    ▼
ffmpeg decode ──► 128×128 YUV420 @ 542/25 fps
    │              mono IMA ADPCM @ 22050 Hz, 512-byte blocks
    ▼
AVI_EncDLL.dll ──► vendor MJPEG (~11568 B/frame, ~10945 B scan)
    │              (Wine harness: vendor_enc/avi_enc_test.exe)
    ▼
atj_avi_mux.py ────► ATJ AVI (316-byte hdrl, idx1 flags 0x10)
    │
    ▼
device
```

One command (experimental — use GUI path until `CreateAmvInterface` harness lands):

```bash
# Recommended today: GUI convert, then remux
wine "Media Player Utilities/AMVConverter/amvtransform.exe"
./remux-vendor.sh vendor_output.avi out.avi

# Headless (WIP):
./make-vendor.sh music.webm out.avi
./vendor-batch.sh [USB]   # round 5 device probes
```

## Vendor files

Ship **AMV/AVI Video Converter V4.46** (Actions/Sunplus era) under:

```
Media Player Utilities/AMVConverter/
├── AVI_EncDLL.dll      # MJPEG + audio_resample + idx1 writer
├── FFMpegDll.dll       # decode front-end (GUI converter)
├── transdll.dll        # orchestration
└── AmvTransform.ini    # 128X128(14;22;22) quality tiers
```

These are proprietary binaries. This project does not redistribute them; users
provide their own copy from the original player utilities disc/installer.

## AVI_EncDLL API (reverse-engineered)

Exports (cdecl, 32-bit):

| Export | Role |
|--------|------|
| `AviEncoderInit(cfg, &cfg[8])` | Configure encoder; handle written to second arg |
| `AviHeaderEncoder(slot, cfg)` | Copy 328-byte template into `cfg` buffer |
| `AviEncoder(out_buf, frame_buf)` | Encode one frame; returns total JPEG size |
| `AviEncoderClose()` | Flush idx1 / teardown |

### `AviHeaderEncoder(slot, cfg)` — two arguments (cdecl)

`transdll.dll` calls `AviHeaderEncoder(&obj[0xc], &obj[0x04])`. The second argument
(`cfg` base) receives the 328-byte (`0x148`) template. A single-argument call crashes
under Wine (reads `[esp+0x10]`; one arg leaves garbage in `edi`).

### `AviEncoderInit(cfg, &cfg[8])` — two arguments

`transdll` calls `AviEncoderInit(&obj[0x04], &obj[0x0c])`. The handle is written to
`cfg+0x08` (`obj+0x0c`). Init alone returns success with `handle=0` unless the full
object context from `CreateAmvInterface` is populated first.

### High-level API: `transdll.dll`

| Export | Role |
|--------|------|
| `CreateAmvInterface` | Factory — returns COM-like encoder interface |
| `GetDeviceIdList` | Device enumeration |
| `run_log` | Logging |

The GUI uses `CreateAmvInterface`, not raw `AVI_EncDLL` exports. Frame encode goes
through vtable methods that build output/output buffers then call
`AviEncoder(out_buf, frame_buf)` (see `transdll+0x6f8a`).

### Scan size (measured)

| Source | Header | Scan | vs official |
|--------|--------|------|-------------|
| official.avi | 623 B | ~10943 B | 1.0 |
| `-avi_mjpeg 1` | 623 B (match) | ~1485 B | **0.14** |
| system mjpeg | 542 B JFIF | ~2925 B | 0.27 |

DQT tables match official (`sum=1858` luma). FFmpeg uses ~7× fewer entropy bits per
frame — not fixable by qscale alone (`-q:v 1` caps ~3232 B scan with `-avi_mjpeg`).

Run `python3 analyze-scan.py candidate.avi` for details.

### `AviInitCfg` (partial — use via `CreateAmvInterface`, not standalone)
|--------|-------|---------------------|
| +0x00 | fps_num | 542 |
| +0x04 | reserved | 0 |
| +0x08 | audio_channels | 1 (mono) |
| +0x0c | audio_rate | 22050 |
| +0x14 | width | 128 |
| +0x18 | height | 128 |
| +0x1c | quality | 22 (mid tier in `AVISIZE=128X128(14;22;22)`) |
| +0x30 | fps_den | 25 |
| +0x34 | field34 | 542 |

### `AviFrameIn` (16 bytes)

| Offset | Field | Value |
|--------|-------|-------|
| +0x00 | write_ptr | `out_buf + 328` (after header template) |
| +0x04 | field04 | 0 |
| +0x08 | pixel_stride | 1 (YUV420P) |
| +0x0c | pixels | pointer to `width*height*3/2` bytes |

Input pixels are **planar YUV420P**, not RGB24. Use ffmpeg `-pix_fmt yuv420p -f rawvideo`.

## Debugging

Build logging proxy (captures GUI converter calls):

```bash
cd vendor_enc
./build.sh --proxy
cd "../Media Player Utilities/AMVConverter"
cp -a AVI_EncDLL.dll AVI_EncDLL_real.dll
cp ../../vendor_enc/avi_enc_proxy.dll AVI_EncDLL.dll
wine amvtransform.exe   # run a conversion
cat avi_enc_proxy.log
```

FFMpegDll decode path is already proxied in `ffmpeg_proxy/` (see `ffmpeg_proxy/README.txt`).

## What we tried (and why FFmpeg alone is insufficient)

- `-avi_mjpeg 1` — headers match official (623 B); scan ~1487 B → format error frame 2
- `atj_avi_jpeg.rewrite_jpeg` — fixes markers/DQT/DHT; scan unchanged → same failure
- Duplicate frame 0 — plays smeared (header/scan quant mismatch tolerated once)
- Duplicate frame 1 — rejected (our f1 scan differs from f0)
- Fixed pad to 11568 B — OK for short clips; 30s fails after ~3s (idx1 size must vary per frame)
- **R8: turbo + official idx1 sizes → full 30s on same pixels (`20_match_official_sizes_30s.avi`)**
- **R9: `--fit tier` / `mod4` → perfect on music + testsrc; `--fit reference` only when re-encoding ref pixels**

Device idx1 byte count per frame must track **this clip's** encoded scan (pad `0x00` after EOI;
scan length ≡ 1 mod 4). Do not borrow another file's size schedule.

Production: `SOURCE=music.webm ./make-atj-avi-encoder.sh out.avi` (default `--fit tier`, `QUALITY=14`).
R10 device check: tier/mod4 perfect on music 30s/60s; `QUALITY=18` plays but oversaturated — stay on tier **14**.
Re-encode: `FIT=reference ./make-atj-avi-encoder.sh out.avi` with YUV from `official.avi` only.

The hardware decoder validates **per-frame scan entropy**, not container layout.

## For other ATJ AVI / Actions-chip devices

1. Use `atj_avi_mux.py` + `atj_avi_hdrl.bin` for container (adjust dimensions in header if needed).
2. Provide vendor `AVI_EncDLL.dll` from that device's converter package.
3. Match resolution/fps/quality from the device's `AmvTransform.ini` `AVISIZE=` line.
4. Do **not** run `rewrite_jpeg` on vendor encoder output.

Long-term: reimplement the scan encoder from `AVI_EncDLL.dll` disassembly, or extract
bit-exact parameters via `avi_enc_proxy.log` during a reference conversion.
