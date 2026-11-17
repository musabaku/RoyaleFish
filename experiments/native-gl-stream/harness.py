# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded in-memory fixture -> decoder run, with no files/network/runtime."""

import hashlib
import json

from fixture import STREAM_ID, generate
from replay import Receiver
from wire import SNAPSHOT, BlobStore


def run():
    store = BlobStore()
    receiver = Receiver(STREAM_ID, store)
    joined = None
    transcript = hashlib.sha256()
    frames = draws = packet_bytes = 0
    for raw, blobs in generate():
        for digest, data in blobs.items():
            store.put(digest, data)
        packet = receiver.apply(raw)
        # A separate viewer joins at frame 400 with only that snapshot's blobs.
        if packet.kind == SNAPSHOT and packet.frame == 400:
            join_store = BlobStore()
            joined = Receiver(STREAM_ID, join_store)
        if joined is not None:
            for digest, data in blobs.items():
                join_store.put(digest, data)
            joined.apply(raw)
            if joined.state_hash() != receiver.state_hash():
                raise AssertionError("rejoin state differs")
        transcript.update(raw)
        frames += 1
        draws += len(receiver.view()["draws"])
        packet_bytes += len(raw)
    return {"status": "PASS_SYNTHETIC_PROTOCOL_HARNESS", "frames": frames,
            "draw_descriptions": draws, "packet_bytes": packet_bytes,
            "blob_count": store.count, "blob_bytes": store.byte_size,
            "transcript_sha256": transcript.hexdigest(),
            "final_state_sha256": receiver.state_hash(), "rejoin_frame": 400,
            "rejoin_frames": 200, "native_frames_observed": 0,
            "gl_calls_executed": 0, "native_producer": "HOLD",
            "pixel_fidelity": "NOT_MEASURED"}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
