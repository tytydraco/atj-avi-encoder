# ATJ AVI muxer — Dart porting notes

The entire muxer is `atj_avi_mux.py` (~120 lines). Map each piece like this:

| Python | Dart |
|--------|------|
| `struct.pack("<I", n)` | `ByteData(4)..setUint32(0, n, Endian.little)` |
| `bytearray` / `bytes` | `Uint8List` / `BytesBuilder` |
| `Path.read_bytes()` | `File(path).readAsBytesSync()` |
| `find(b"LIST")` | `bytes.indexOf([0x4C,0x49,0x53,0x54])` or scan loop |

## Algorithm (5 steps)

1. **Header** — Load `atj_avi_hdrl.bin` (316 bytes, extracted once from a known-good
   ATJ AVI). Patch frame count and optional width/height. No need to ship
   `official.avi` in production.
   - `avih` +16 → frame count (`uint32`)
   - last `strh` +32 → `frame_count * 258` (audio length field)
   - optional width/height in `avih` +32/+36 and video `strf`

2. **Extract** — Walk `idx1` entries (16 bytes each: tag, flags, offset, size).
   Payload at `movi_fourcc_pos + offset + 8`.

3. **Pair** — Default: pad video (duplicate last frame) until counts match; `--trim` to truncate.

4. **Movi** — For each pair: write `00dc` + u32(size) + jpeg, pad to even;
   then `01wb` + u32(512) + adpcm block, pad to even.

5. **Idx1** — Same order; offset starts at `4` (first chunk is 4 bytes after `movi` fourcc).
   Flags always `0x10`. Fix RIFF size at byte 4: `file.length - 8`.

## CLI

```
python3 atj_avi_mux.py <source.avi> <out.avi> [--trim] [--no-jpeg-rewrite]
./make-atj-avi-encoder.sh [out.avi]          # system ffmpeg encode + jpeg rewrite + mux (default pad)
TRIM=1 ./make-atj-avi-encoder.sh out.avi     # truncate longer stream (usually breaks playback)
./test-muxer.sh                    # regression tests
```

## JPEG rewrite (`atj_avi_jpeg.py`)

System ffmpeg writes JFIF MJPEG. The muxer calls `rewrite_jpeg()` on each video
frame by default (matches patched `-avi_mjpeg 1` headers):

- APP0 `AVI1` instead of `JFIF`
- Two vendor DQT tables (from `ff_atj_avi_*_quant`)
- SOF0 with chroma matrix id 1
- Four separate DHT markers (default MJPEG Huffman)

Pass `--no-jpeg-rewrite` to mux container-only (official round-trip).

## A/V count mismatch

FFmpeg often yields 650 video + 651 audio for 30s @ 542/25 fps. Default **pad**
duplicates the last video frame (651/651, same as official). Do not trim on device
targets — it glitches after the first frame.

## FFmpeg: patched vs system

| Piece | Patched `./prefix/bin/ffmpeg` | System `ffmpeg` |
|-------|------------------------------|-----------------|
| **Mux** | `atj_avi_mux.py` | `atj_avi_mux.py` |
| **Encode MJPEG** | `-avi_mjpeg 1` | `atj_avi_jpeg.rewrite_jpeg()` in muxer (default) |
| **Encode ADPCM** | `-block_size 512` | `-block_size 512` |

Patched encoder also uses vendor quant tables during DCT (slightly different frame
sizes). Header rewrite is enough for device **format acceptance**; multi-frame
playback still requires vendor scan entropy — see [VENDOR-ENCODER.md](VENDOR-ENCODER.md).

## Vendor MJPEG (device playback)

FFmpeg/cjpeg scans fail after frame 1 on hardware even with byte-identical headers.
Use **AVI_EncDLL.dll** from the AMV Video Converter package:

```bash
# GUI converter (recommended today)
wine "Media Player Utilities/AMVConverter/amvtransform.exe"
./remux-vendor.sh vendor_output.avi out.avi

# Headless pipeline (experimental harness)
./make-vendor.sh music.webm out.avi
```

See [VENDOR-ENCODER.md](VENDOR-ENCODER.md) for architecture and reverse-engineering notes.
