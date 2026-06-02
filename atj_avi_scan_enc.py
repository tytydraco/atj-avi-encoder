"""Native ATJ AVI MJPEG scan encoder (ctypes wrapper around libatj_avi_scan.so)."""

from __future__ import annotations

import ctypes
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "atj_avi_scan" / "build" / "libatj_avi_scan.so"
QTABLES = ROOT / "atj_avi_scan" / "atj_avi.qtables"

VENDOR_QUALITY_MIN = 0
VENDOR_QUALITY_MAX = 22
VENDOR_QUALITY_DEFAULT = 22
HEADER_SIZE = 623


def _ensure_qtables() -> Path:
    if QTABLES.is_file():
        return QTABLES
    from atj_avi_jpeg import LUMA_Q, CHROMA_Q

    lines: list[str] = []
    for n, table in enumerate([LUMA_Q, CHROMA_Q]):
        lines.append(f"# {n}")
        for i in range(0, 64, 8):
            lines.append(" ".join(str(x) for x in table[i : i + 8]))
    QTABLES.write_text("\n".join(lines) + "\n")
    return QTABLES


def vendor_to_cjpeg_quality(vendor_quality: int) -> int:
    """IJG quality with ATJ AVI -qtables (scan matches official size)."""
    vendor_quality = max(VENDOR_QUALITY_MIN, min(VENDOR_QUALITY_MAX, vendor_quality))
    return 50 + (vendor_quality - VENDOR_QUALITY_MIN) * 2


def encode_cjpeg(
    yuv420: bytes,
    width: int,
    height: int,
    quality: int = VENDOR_QUALITY_DEFAULT,
) -> bytes:
    """Encode via cjpeg + ATJ AVI quant tables + full AVI1 header rewrite (reference path)."""
    from atj_avi_jpeg import rewrite_jpeg

    need = width * height * 3 // 2
    if len(yuv420) < need:
        raise ValueError(f"need {need} bytes YUV420P, got {len(yuv420)}")
    qtables = _ensure_qtables()
    ijg_q = vendor_to_cjpeg_quality(quality)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        raw = td_path / "in.yuv"
        ppm = td_path / "in.ppm"
        raw.write_bytes(yuv420[:need])
        # yuv420p → ppm for cjpeg (ffmpeg is the simplest converter here)
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "yuv420p",
                "-s",
                f"{width}x{height}",
                "-i",
                str(raw),
                str(ppm),
            ],
            check=True,
        )
        proc = subprocess.run(
            [
                "cjpeg",
                "-quality",
                str(ijg_q),
                "-sample",
                "2x2",
                "-qtables",
                str(qtables),
                "-dct",
                "int",
                str(ppm),
            ],
            capture_output=True,
            check=True,
        )
    return rewrite_jpeg(proc.stdout, mode="full")


class AtjAviScanEnc:
    """Encode YUV420P frames to ATJ AVI-compatible MJPEG (623 B AVI1 header + scan)."""

    def __init__(self, width: int, height: int, quality: int = VENDOR_QUALITY_DEFAULT):
        self._lib = _load_lib()
        self._enc = self._lib.atj_avi_scan_enc_open(width, height, quality)
        if not self._enc:
            raise RuntimeError("atj_avi_scan_enc_open failed")
        self.width = width
        self.height = height
        self.quality = quality

    def encode(self, yuv420: bytes) -> bytes:
        need = self.width * self.height * 3 // 2
        if len(yuv420) < need:
            raise ValueError(f"need {need} bytes YUV420P, got {len(yuv420)}")
        out_cap = max(256 * 1024, need * 4)
        out = (ctypes.c_uint8 * out_cap)()
        n = self._lib.atj_avi_scan_enc_frame(
            self._enc,
            ctypes.c_char_p(yuv420),
            out,
            out_cap,
        )
        if n < 0:
            raise RuntimeError(f"atj_avi_scan_enc_frame failed: {n}")
        return bytes(out[:n])

    def close(self) -> None:
        if self._enc:
            self._lib.atj_avi_scan_enc_close(self._enc)
            self._enc = None

    def __enter__(self) -> AtjAviScanEnc:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def vendor_to_ijg_quality(vendor_quality: int) -> int:
    lib = _load_lib()
    return int(lib.atj_avi_scan_vendor_to_ijg_quality(vendor_quality))


def encode_yuv_file(
    yuv_path: Path,
    width: int,
    height: int,
    quality: int = VENDOR_QUALITY_DEFAULT,
    out_path: Optional[Path] = None,
) -> bytes:
    yuv = yuv_path.read_bytes()
    with AtjAviScanEnc(width, height, quality) as enc:
        jpeg = enc.encode(yuv)
    if out_path:
        out_path.write_bytes(jpeg)
    return jpeg


def extract_yuv_from_avi(avi: Path, frame: int, out: Path) -> None:
    """Extract one YUV420P frame via djpeg (requires JPEG in AVI chunk)."""
    import atj_avi_mux as m

    videos, _ = m.extract(avi)
    if frame >= len(videos):
        raise IndexError(f"frame {frame} out of range ({len(videos)})")
    jpg = out.with_suffix(".jpg")
    jpg.write_bytes(videos[frame])
    ppm = out.with_suffix(".ppm")
    subprocess.run(["djpeg", str(jpg), "-outfile", str(ppm)], check=True)
    # ppm → raw rgb → yuv would need conversion; use ffmpeg on avi if available
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(avi),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            f"select=eq(n\\,{frame})",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "rawvideo",
            str(out),
        ],
        check=True,
    )


_lib: Optional[ctypes.CDLL] = None


def _load_lib() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    if not LIB.is_file():
        raise FileNotFoundError(
            f"{LIB} not found — run: make -C {ROOT / 'atj_avi_scan'}"
        )
    _lib = ctypes.CDLL(str(LIB))
    _lib.atj_avi_scan_enc_open.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    _lib.atj_avi_scan_enc_open.restype = ctypes.c_void_p
    _lib.atj_avi_scan_enc_close.argtypes = [ctypes.c_void_p]
    _lib.atj_avi_scan_enc_close.restype = None
    _lib.atj_avi_scan_enc_frame.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
    ]
    _lib.atj_avi_scan_enc_frame.restype = ctypes.c_int
    _lib.atj_avi_scan_vendor_to_ijg_quality.argtypes = [ctypes.c_int]
    _lib.atj_avi_scan_vendor_to_ijg_quality.restype = ctypes.c_int
    return _lib


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="ATJ AVI native MJPEG scan encoder test")
    p.add_argument("yuv", type=Path, help="raw YUV420P file (128x128)")
    p.add_argument("-q", "--quality", type=int, default=14, help="vendor quality 14-22")
    p.add_argument("-o", "--out", type=Path, default=Path("/tmp/atj_avi_scan_out.jpg"))
    p.add_argument("-W", "--width", type=int, default=128)
    p.add_argument("-H", "--height", type=int, default=128)
    args = p.parse_args()
    jpeg = encode_yuv_file(args.yuv, args.width, args.height, args.quality, args.out)
    from atj_avi_jpeg import _entropy_offset

    print(
        f"quality={args.quality} ijg={vendor_to_ijg_quality(args.quality)} "
        f"total={len(jpeg)} scan={len(jpeg) - _entropy_offset(jpeg)} -> {args.out}"
    )
