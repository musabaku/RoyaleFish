# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""NCAP call audits -> original NGS1 native-call-audit-v1, never GL replay."""

import hashlib
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wire import (DELTA, SNAPSHOT, ZERO_HASH, BlobStore, decode, encode,
                  integer, require, sha256)  # noqa: E402

CAPTURE_HEADER = struct.Struct("<4sIII10Q")
RECORD = struct.Struct("<QQII6I")
MAX_CAPTURE = CAPTURE_HEADER.size + 4096 * RECORD.size
FRAME_BYTES = 6 * RECORD.size
PROFILE = "native-call-audit-v1"


def fields(obj, expected):
    require(type(obj) is dict and set(obj) == expected, "audit object fields")


def frame_state(blob, frame):
    require(type(blob) is bytes and len(blob) == FRAME_BYTES, "audit frame size")
    integer(frame, 0, 599)
    records = [RECORD.unpack_from(blob, i * RECORD.size) for i in range(6)]
    sizes = (4, 4, 1, 3, 3, 1)
    for i, record in enumerate(records):
        seq, recorded_frame, op, argc, *args = record
        require((seq, recorded_frame, op, argc) == (frame * 6 + i, frame, i + 1, sizes[i]),
                "omitted/reordered/unsupported call")
        require(all(arg == 0 for arg in args[argc:]), "nonzero reserved arguments")
    viewport = list(records[0][4:8])
    require(all(0 <= value <= 4096 for value in viewport)
            and viewport[2] > 0 and viewport[3] > 0, "viewport profile")
    color_bits = list(records[1][4:8])
    colors = struct.unpack("<4f", struct.pack("<4I", *color_bits))
    require(all(math.isfinite(value) and 0 <= value <= 1 for value in colors), "color profile")
    require(records[2][4] == 0x4000, "clear profile")
    require(records[3][4:7] == (4, 0, 3), "array draw profile")
    require(records[4][4:7] == (4, 6, 0x1403), "element draw profile")
    require(records[5][4] == 1, "failed swap")
    return {"viewport": viewport, "clear_color_bits": color_bits}


def parse_capture(raw):
    require(type(raw) is bytes and CAPTURE_HEADER.size <= len(raw) <= MAX_CAPTURE,
            "capture size")
    magic, version, record_size, count, *stats = CAPTURE_HEADER.unpack_from(raw)
    require((magic, version, record_size) == (b"NCAP", 1, RECORD.size), "capture version/layout")
    require(len(raw) == CAPTURE_HEADER.size + count * RECORD.size, "capture length")
    require(0 < count <= 3600 and count % 6 == 0, "complete bounded call frames")
    require(stats[:3] == [count, count, count // 6], "capture forwarding/swap totals")
    require(not any(stats[3:]), "capture fault/overflow/reentry/unsupported activity")
    blobs = []
    for frame in range(count // 6):
        offset = CAPTURE_HEADER.size + frame * FRAME_BYTES
        blob = raw[offset:offset + FRAME_BYTES]
        frame_state(blob, frame)
        blobs.append(blob)
    return blobs


def adapt(raw):
    """Validate the complete bounded capture before emitting any packet.

    Snapshots restore audit state, not native GPU objects. Simulation tick is
    explicitly unknown and encoded as zero, never inferred from swap count.
    """
    blobs = parse_capture(raw)
    capture_hash = sha256(raw)
    stream = bytes.fromhex(capture_hash)[:16]
    previous = ZERO_HASH
    packets = []
    for frame, blob in enumerate(blobs):
        body = {"profile": PROFILE, "capture_sha256": capture_hash,
                "event_blob": {"sha256": sha256(blob), "size": len(blob)},
                "state": frame_state(blob, frame), "calls": (frame + 1) * 6}
        kind = SNAPSHOT if frame % 200 == 0 else DELTA
        packet = encode(kind, stream, frame, frame, 0,
                        ZERO_HASH if kind == SNAPSHOT else previous, body)
        packets.append((packet, {sha256(blob): blob}))
        previous = hashlib.sha256(packet).digest()
    return packets


class AuditReceiver:
    """Separate profile receiver. Strict frames and blobs; no graphics execution."""

    def __init__(self, capture_hash, store):
        require(type(capture_hash) is str and len(capture_hash) == 64
                and all(c in "0123456789abcdef" for c in capture_hash), "capture identity")
        require(isinstance(store, BlobStore), "blob store")
        self.capture_hash = capture_hash
        self.stream = bytes.fromhex(capture_hash)[:16]
        self.store = store
        self.packet = None
        self._state = None

    @property
    def state(self):
        return None if self._state is None else {k: list(v) for k, v in self._state.items()}

    def apply(self, raw, *, rejoin=False):
        packet = decode(raw)
        integer(packet.frame, 0, 599)
        require(packet.stream_id == self.stream and packet.sequence == packet.frame
                and packet.tick == 0, "audit identity/sequence/tick")
        require(packet.kind == (SNAPSHOT if packet.frame % 200 == 0 else DELTA), "audit snapshot cadence")
        if self.packet is None or rejoin:
            require(packet.kind == SNAPSHOT, "audit snapshot required")
        if self.packet is not None:
            require(packet.frame > self.packet.frame, "repeated/backward audit frame")
            if not rejoin:
                require(packet.frame == self.packet.frame + 1, "missing audit predecessor")
        if packet.kind == DELTA:
            require(self.packet is not None and packet.previous == self.packet.digest, "audit chain")
        body = packet.body
        fields(body, {"profile", "capture_sha256", "event_blob", "state", "calls"})
        require(body["profile"] == PROFILE and body["capture_sha256"] == self.capture_hash,
                "audit profile/capture identity")
        require(type(body["calls"]) is int and body["calls"] == (packet.frame + 1) * 6,
                "audit call total")
        descriptor = body["event_blob"]
        fields(descriptor, {"sha256", "size"})
        require(type(descriptor["size"]) is int and descriptor["size"] == FRAME_BYTES, "audit blob size")
        blob = self.store.get(descriptor["sha256"], descriptor["size"])
        state = frame_state(blob, packet.frame)
        require(body["state"] == state, "audit state differs from captured calls")
        self._state, self.packet = state, packet
        return packet


def receipt(raw):
    packets = adapt(raw)
    receiver = AuditReceiver(sha256(raw), BlobStore())
    transcript = hashlib.sha256()
    joined = None
    for index, (packet, blobs) in enumerate(packets):
        for digest, blob in blobs.items():
            receiver.store.put(digest, blob)
        receiver.apply(packet)
        if index == 400:
            joined = AuditReceiver(sha256(raw), BlobStore())
        if joined is not None:
            for digest, blob in blobs.items():
                joined.store.put(digest, blob)
            joined.apply(packet)
            require(receiver.state == joined.state, "cold audit join mismatch")
        transcript.update(packet)
    return {"status": "PASS_HOST_CALLBACK_AUDIT_NGS1", "frames": len(packets),
            "captured_calls": len(packets) * 6, "forwarded_calls": len(packets) * 6,
            "capture_sha256": sha256(raw), "transcript_sha256": transcript.hexdigest(),
            "profile": PROFILE, "native_frames_observed": 0, "gpu_frames": 0,
            "android_admission": "HOLD", "renderable_gl_stream": "HOLD"}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 -B adapter.py capture.ncap")
    with open(sys.argv[1], "rb") as source:
        raw = source.read(MAX_CAPTURE + 1)
    print(json.dumps(receipt(raw), indent=2, sort_keys=True))
