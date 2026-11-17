# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Build actual callbacks, run an independent fake driver, validate its bytes."""

import copy
import json
from pathlib import Path
import shutil
import struct
import subprocess
import unittest

from adapter import (AuditReceiver, CAPTURE_HEADER, FRAME_BYTES, MAX_CAPTURE,
                     RECORD, adapt, parse_capture, receipt)
from wire import BlobStore, ProtocolError, decode, encode, sha256

ROOT = Path(__file__).resolve().parent


class NativeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang++")
        if compiler is None:
            raise RuntimeError("clang++ required; no installation attempted")
        build = ROOT / ".local-build"
        build.mkdir(exist_ok=True)
        cls.executable = build / "host-driver"
        subprocess.run([compiler, "-std=c++17", "-DNGS_HOST_TEST", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread",
                        "-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        str(ROOT / "layer.cpp"), str(ROOT / "host_driver.cpp"),
                        "-o", str(cls.executable)], check=True, timeout=60)
        cls.raw = cls.run_driver("good")
        cls.packets = adapt(cls.raw)

    @classmethod
    def run_driver(cls, mode):
        result = subprocess.run([str(cls.executable), mode], capture_output=True,
                                check=True, timeout=10)
        if b"PASS_HOST_CALLBACKS " + mode.encode() not in result.stderr:
            raise AssertionError("independent driver did not finish its assertions")
        return result.stdout

    def receiver(self, populate=True):
        store = BlobStore()
        if populate:
            for _, blobs in self.packets:
                for digest, blob in blobs.items():
                    store.put(digest, blob)
        return AuditReceiver(sha256(self.raw), store)

    def rejected(self, receiver, raw, **kwargs):
        before = (receiver.packet, receiver.state)
        with self.assertRaises(ProtocolError):
            receiver.apply(raw, **kwargs)
        self.assertEqual((receiver.packet, receiver.state), before)

    def rewrite(self, raw, **updates):
        packet = decode(raw)
        fields = dict(kind=packet.kind, stream_id=packet.stream_id, sequence=packet.sequence,
                      frame=packet.frame, tick=packet.tick, previous=packet.previous, body=packet.body)
        fields.update(updates)
        return encode(**fields)

    def test_600_actual_callback_frames_and_independent_state(self):
        blobs = parse_capture(self.raw)
        self.assertEqual(len(blobs), 600)
        self.assertEqual(len(self.raw), CAPTURE_HEADER.size + 3600 * RECORD.size)
        receiver = self.receiver(False)
        for frame, (raw, resources) in enumerate(self.packets):
            for digest, blob in resources.items():
                receiver.store.put(digest, blob)
            receiver.apply(raw)
            bits = struct.unpack("<4I", struct.pack("<4f", (frame % 256) / 256, .25, .5, 1))
            self.assertEqual(receiver.state, {"viewport": [frame % 3, 0, 256 + frame % 4, 256],
                                             "clear_color_bits": list(bits)})
        self.assertEqual(receiver.packet.frame, 599)

    def test_native_faults_preserve_forwarding_and_block_adapter(self):
        # C++ asserts next-call counts even for invalid/reentrant/overflow runs.
        for mode in ("overflow", "omitted", "failed-swap", "unsupported", "lookup",
                     "null-lookup", "conflict", "reentrant", "thread", "pointer"):
            with self.subTest(mode=mode), self.assertRaises(ProtocolError):
                adapt(self.run_driver(mode))

    def test_full_cold_rejoin_at_each_snapshot(self):
        for start in (0, 200, 400):
            receiver = self.receiver(False)
            for raw, blobs in self.packets[start:]:
                for digest, blob in blobs.items():
                    receiver.store.put(digest, blob)
                receiver.apply(raw)
            self.assertEqual(receiver.packet.frame, 599)

    def test_loss_reorder_chain_and_explicit_rejoin(self):
        receiver = self.receiver()
        self.rejected(receiver, self.packets[1][0])
        receiver.apply(self.packets[0][0])
        for index in (0, 2, 200):
            self.rejected(receiver, self.packets[index][0])
        self.rejected(receiver, self.rewrite(self.packets[1][0], previous=b"x" * 32))
        receiver.apply(self.packets[200][0], rejoin=True)
        self.rejected(receiver, self.packets[200][0], rejoin=True)
        receiver.apply(self.packets[201][0])

    def test_invalid_missing_and_tampered_blobs(self):
        receiver = self.receiver(False)
        self.rejected(receiver, self.packets[0][0])
        digest, blob = next(iter(self.packets[0][1].items()))
        with self.assertRaises(ProtocolError):
            receiver.store.put(digest, b"x" + blob[1:])
        receiver.store.put(digest, blob)
        body = copy.deepcopy(decode(self.packets[0][0]).body)
        body["event_blob"]["size"] -= 1
        self.rejected(receiver, self.rewrite(self.packets[0][0], body=body))
        changed = bytearray(blob)
        changed[16] = 9  # Unknown opcode, with a valid new content hash.
        changed = bytes(changed)
        receiver.store.put(sha256(changed), changed)
        body["event_blob"] = {"sha256": sha256(changed), "size": FRAME_BYTES}
        self.rejected(receiver, self.rewrite(self.packets[0][0], body=body))

    def test_capture_bounds_version_order_and_omitted_records(self):
        for bad in (b"", self.raw[:-1], self.raw + b"x", bytes(MAX_CAPTURE + 1)):
            with self.assertRaises(ProtocolError):
                parse_capture(bad)
        for offset in (4, 8, 12, 16, CAPTURE_HEADER.size, CAPTURE_HEADER.size + 16,
                       CAPTURE_HEADER.size + 20, CAPTURE_HEADER.size + 40):
            changed = bytearray(self.raw)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ProtocolError):
                parse_capture(bytes(changed))

    def test_profile_identity_state_and_tick(self):
        raw = self.packets[0][0]
        for kwargs in ({"tick": 1}, {"sequence": 1}, {"stream_id": bytes(16)}):
            self.rejected(self.receiver(), self.rewrite(raw, **kwargs))
        for key, value in (("profile", "synthetic-gles-style-v1"), ("calls", 5),
                           ("capture_sha256", "0" * 64), ("state", {})):
            body = copy.deepcopy(decode(raw).body)
            body[key] = value
            self.rejected(self.receiver(), self.rewrite(raw, body=body))
        changed = bytearray(raw)
        changed[-1] ^= 1
        self.rejected(self.receiver(), bytes(changed))

    def test_deterministic_native_capture_and_ngs1(self):
        self.assertEqual(self.raw, self.run_driver("good"))
        self.assertEqual(self.packets, adapt(self.raw))
        result = receipt(self.raw)
        self.assertEqual((result["frames"], result["captured_calls"], result["gpu_frames"]), (600, 3600, 0))
        self.assertEqual(result["android_admission"], "HOLD")
        self.assertEqual(result["capture_sha256"],
                         "6714b4dc5b3d07facc4e2be44f052e1aa716d2b952933381eea1061a1a73698f")
        self.assertEqual(result["transcript_sha256"],
                         "309fb57c0d784c04c8c037e8fd7c7bb46635ff76f4fd96832abacb3c70b92bd8")
        print("\n" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
