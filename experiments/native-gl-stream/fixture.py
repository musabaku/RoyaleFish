# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Self-owned synthetic event producer. Does not import replay or read files."""

import hashlib
import struct

from wire import DELTA, SNAPSHOT, ZERO_HASH, encode, integer, sha256

STREAM_ID = b"owned-fixture-01"
FRAME_COUNT = 600
KEYFRAME_INTERVAL = 200


def frame_state(frame):
    integer(frame, 0, FRAME_COUNT - 1)
    return {"transform_q16": [65536, 0, 0, 65536, (frame % 120 - 60) * 256,
                               (frame % 80 - 40) * 256],
            "clear_rgba8": [frame % 256, (frame * 3) % 256, (frame * 7) % 256, 255],
            "viewport": [0, 0, 256, 256]}


def frame_resources(frame):
    integer(frame, 0, FRAME_COUNT - 1)
    # Integer vertex coordinates, u16 indices, and a changing one-pixel tint.
    return {
        "triangle": ("vertex-i16x2", struct.pack("<6h", -64, -64, 64, -64, 0, 64)),
        "quad": ("vertex-i16x2", struct.pack("<8h", -32, -32, 32, -32, 32, 32, -32, 32)),
        "indices": ("index-u16", struct.pack("<6H", 0, 1, 2, 0, 2, 3)),
        "tint": ("rgba8", bytes([frame % 256, 255 - frame % 256, (frame * 5) % 256, 255])),
    }


def frame_draws():
    return [{"op": "draw_arrays", "vertices": "triangle", "first": 0,
             "count": 3, "tint": "tint"},
            {"op": "draw_elements", "vertices": "quad", "indices": "indices",
             "count": 6, "tint": "tint"}]


def generate():
    """Yield (packet bytes, new hash->blob map), bounded to exactly 600 frames.

    Every snapshot re-emits its entire blob closure, even on an existing stream.
    Deltas rebind immutable resource versions rather than mutating blob bytes.
    """
    previous = ZERO_HASH
    sent = set()
    for frame in range(FRAME_COUNT):
        snapshot = frame % KEYFRAME_INTERVAL == 0
        if snapshot:
            # Deduplication is segment-local: a joining viewer has no old cache.
            sent.clear()
        resources, blobs = {}, {}
        for name, (fmt, data) in frame_resources(frame).items():
            digest = sha256(data)
            if snapshot or digest not in sent:
                blobs[digest] = data
                sent.add(digest)
            if snapshot or name == "tint":
                resources[name] = {"sha256": digest, "size": len(data), "format": fmt}
        state = frame_state(frame)
        if not snapshot:
            del state["viewport"]
        body = {"profile": "synthetic-gles-style-v1", "resources": resources,
                "state": state, "draws": frame_draws()}
        raw = encode(SNAPSHOT if snapshot else DELTA, STREAM_ID, frame, frame,
                     frame * 2, ZERO_HASH if snapshot else previous, body)
        yield raw, blobs
        previous = hashlib.sha256(raw).digest()
