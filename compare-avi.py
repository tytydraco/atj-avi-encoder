#!/usr/bin/env python3
"""Byte-level AVI/AMV structure parser and diff tool for Ruizu compatibility work."""

import json
import struct
import sys
from collections import Counter
from pathlib import Path

AVIF = {
    0x10: "HASINDEX",
    0x20: "MUSTUSEINDEX",
    0x100: "ISINTERLEAVED",
    0x800: "TRUSTCKTYPE",
    0x10000: "WASCAPTUREFILE",
    0x20000: "COPYRIGHTED",
}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def fc(b, o):
    return bytes(b[o : o + 4]).decode("latin1", "replace")


def flag_names(v):
    return [n for bit, n in AVIF.items() if v & bit]


class Reader:
    def __init__(self, data, start=0, end=None):
        self.data = data
        self.pos = start
        self.end = len(data) if end is None else end

    def read(self, n):
        if self.pos + n > self.end:
            raise EOFError
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def skip(self, n):
        self.pos = min(self.end, self.pos + n)

    def u32(self):
        return u32(self.read(4), 0)

    def fourcc(self):
        return fc(self.read(4), 0)


def parse_avih(data):
    return {
        "us_per_frame": u32(data, 0),
        "max_bps": u32(data, 4),
        "padding": u32(data, 8),
        "flags": u32(data, 12),
        "flag_names": flag_names(u32(data, 12)),
        "total_frames": u32(data, 16),
        "init_frames": u32(data, 20),
        "streams": u32(data, 24),
        "bufsize": u32(data, 28),
        "width": u32(data, 32),
        "height": u32(data, 36),
    }


def parse_strh(data):
    return {
        "type": fc(data, 0),
        "handler": fc(data, 4),
        "flags": u32(data, 8),
        "scale": u32(data, 20),
        "rate": u32(data, 24),
        "start": u32(data, 28),
        "length": u32(data, 32),
        "bufsize": u32(data, 36),
        "quality": u32(data, 40),
        "sample_size": u32(data, 44),
    }


def parse_strf(data):
    out = {"size": len(data), "hex": data.hex()}
    if len(data) >= 40 and u16(data, 12) <= 1:
        out["kind"] = "video"
        out["video"] = {
            "biSize": u32(data, 0),
            "width": u32(data, 4),
            "height": u32(data, 8),
            "planes": u16(data, 12),
            "bitcount": u16(data, 14),
            "compression": fc(data, 16),
            "imgsize": u32(data, 20),
        }
    elif len(data) >= 16:
        out["kind"] = "audio"
        out["audio"] = {
            "tag": u16(data, 0),
            "channels": u16(data, 2),
            "rate": u32(data, 4),
            "byte_rate": u32(data, 8),
            "align": u16(data, 12),
            "bits": u16(data, 14),
            "extra": data[16:].hex(),
        }
    return out


def parse_idx1(data):
    entries = []
    for i in range(0, len(data), 16):
        if i + 16 > len(data):
            break
        entries.append(
            {
                "chunk": fc(data, i),
                "flags": u32(data, i + 4),
                "offset": u32(data, i + 8),
                "size": u32(data, i + 12),
            }
        )
    return entries


def scan_movi(data, start, limit=200):
    r = Reader(data, start)
    chunks = []
    while r.pos + 8 <= r.end and len(chunks) < limit:
        pos = r.pos
        tag = r.fourcc()
        size = r.u32()
        chunks.append({"pos": pos, "tag": tag, "size": size})
        r.skip(size + (size & 1))
    return chunks


def parse_avi(path):
    data = Path(path).read_bytes()
    info = {
        "path": str(path),
        "size": len(data),
        "riff_form": None,
        "avih": None,
        "streams": [],
        "hdrl_chunks": [],
        "movi": None,
        "movi_chunks": [],
        "idx1": None,
        "has_odml": False,
        "has_junk_in_strl": False,
        "has_vprp": False,
        "has_info": False,
    }
    if len(data) < 12 or data[:4] != b"RIFF":
        info["error"] = "not RIFF"
        return info

    info["riff_form"] = fc(data, 8)
    r = Reader(data, 12)
    while r.pos + 8 <= r.end:
        pos = r.pos
        tag = r.fourcc()
        size = r.u32()
        body = r.pos
        end = body + size
        entry = {"pos": pos, "tag": tag, "size": size}

        if tag == "LIST":
            subtype = fc(data, body)
            entry["subtype"] = subtype
            info["hdrl_chunks"].append(entry)
            if subtype == "hdrl":
                parse_hdrl(data, body + 4, end, info)
            elif subtype == "movi":
                info["movi"] = {"pos": pos, "size": size, "data": body + 4}
                info["movi_chunks"] = scan_movi(data, body + 4)
            elif subtype == "INFO":
                info["has_info"] = True
        elif tag == "idx1":
            info["idx1"] = {"pos": pos, "size": size, "entries": parse_idx1(data[body:end])}
        elif tag == "JUNK" and fc(data, body) == b"odml":
            info["has_odml"] = True
        else:
            info["hdrl_chunks"].append(entry)

        r.pos = end + (size & 1)

    tags = [c["tag"] for c in info["movi_chunks"]]
    info["movi_interleave"] = {
        "first_30": tags[:30],
        "back_to_back": [i for i in range(len(tags) - 1) if tags[i] == tags[i + 1]],
        "video_sizes": [c["size"] for c in info["movi_chunks"] if c["tag"].startswith("00d")][:20],
        "audio_sizes": dict(Counter(c["size"] for c in info["movi_chunks"] if c["tag"].startswith("01w"))),
    }
    if info["idx1"]:
        info["idx1_sequence"] = [e["chunk"] for e in info["idx1"]["entries"][:20]]
    return info


def parse_hdrl(data, start, end, info):
    r = Reader(data, start, end)
    while r.pos + 8 <= r.end:
        pos = r.pos
        tag = r.fourcc()
        size = r.u32()
        body = r.pos
        e = body + size
        if tag == "avih":
            info["avih"] = parse_avih(data[body:e])
        elif tag == "LIST" and fc(data, body) == "strl":
            stream = {"pos": pos, "chunks": []}
            sr = Reader(data, body + 4, e)
            while sr.pos + 8 <= sr.end:
                st = sr.fourcc()
                ss = sr.u32()
                sb = sr.pos
                se = sb + ss
                stream["chunks"].append({"tag": st, "size": ss})
                if st == "strh":
                    stream["strh"] = parse_strh(data[sb:se])
                elif st == "strf":
                    stream["strf"] = parse_strf(data[sb:se])
                elif st == "JUNK":
                    info["has_junk_in_strl"] = True
                elif st == "vprp":
                    info["has_vprp"] = True
                sr.pos = se + (ss & 1)
            info["streams"].append(stream)
        r.pos = e + (size & 1)


def compare(a, b):
    keys = [
        ("avih.flags", lambda x: x.get("avih", {}).get("flags")),
        ("avih.flag_names", lambda x: x.get("avih", {}).get("flag_names")),
        ("avih.max_bps", lambda x: x.get("avih", {}).get("max_bps")),
        ("avih.bufsize", lambda x: x.get("avih", {}).get("bufsize")),
        ("avih.us_per_frame", lambda x: x.get("avih", {}).get("us_per_frame")),
        ("has_odml", lambda x: x.get("has_odml")),
        ("has_junk_in_strl", lambda x: x.get("has_junk_in_strl")),
        ("has_vprp", lambda x: x.get("has_vprp")),
        ("has_info", lambda x: x.get("has_info")),
    ]
    for i in range(max(len(a.get("streams", [])), len(b.get("streams", [])))):
        sa = a.get("streams", [{}])[i] if i < len(a.get("streams", [])) else {}
        sb = b.get("streams", [{}])[i] if i < len(b.get("streams", [])) else {}
        keys += [
            (f"stream{i}.strh", lambda x, i=i: x.get("streams", [{}])[i].get("strh") if i < len(x.get("streams", [])) else None),
            (f"stream{i}.strf", lambda x, i=i: x.get("streams", [{}])[i].get("strf") if i < len(x.get("streams", [])) else None),
        ]
    keys += [
        ("movi_interleave.back_to_back", lambda x: x.get("movi_interleave", {}).get("back_to_back")),
        ("movi_interleave.audio_sizes", lambda x: x.get("movi_interleave", {}).get("audio_sizes")),
        ("idx1.count", lambda x: len(x["idx1"]["entries"]) if x.get("idx1") else 0),
    ]

    print(f"\n{'FIELD':<34} {'A':<28} {'B':<28} MATCH")
    print("-" * 96)
    for name, fn in keys:
        va = fn(a)
        vb = fn(b)
        match = "yes" if va == vb else "NO"
        print(f"{name:<34} {str(va):<28} {str(vb):<28} {match}")


def main():
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <file> [file2]", file=sys.stderr)
        sys.exit(1)

    infos = [parse_avi(p) for p in sys.argv[1:]]
    for info in infos:
        print(json.dumps(info, indent=2))
    if len(infos) == 2:
        compare(infos[0], infos[1])


if __name__ == "__main__":
    main()
