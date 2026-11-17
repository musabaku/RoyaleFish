# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Conformance/negative controls, separate from the reference event producer."""

import copy
import hashlib
import struct
import unittest

from fixture import STREAM_ID, generate
from harness import run
from replay import Receiver
from wire import (DELTA, HEADER, MAX_BLOB, MAX_BLOBS, MAX_DRAWS, MAX_PACKET,
                  MAX_RESOURCES, MAX_STORE, SNAPSHOT, ZERO_HASH, BlobStore,
                  ProtocolError, canonical, decode, encode, sha256)


def rewritten(raw, **changes):
    packet = decode(raw)
    fields = dict(kind=packet.kind, stream_id=packet.stream_id,
                  sequence=packet.sequence, frame=packet.frame, tick=packet.tick,
                  previous=packet.previous, body=copy.deepcopy(packet.body))
    fields.update(changes)
    return encode(**fields)


def packet_with_payload(payload):
    header = HEADER.pack(b"NGS1", 1, SNAPSHOT, 0, len(payload), STREAM_ID,
                         0, 0, 0, ZERO_HASH, ZERO_HASH)
    return header[:-32] + hashlib.sha256(header[:-32] + payload).digest() + payload


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = list(generate())

    def store_for(self, count=600):
        store = BlobStore()
        for _, blobs in self.fixtures[:count]:
            for digest, data in blobs.items():
                store.put(digest, data)
        return store

    def receiver(self):
        return Receiver(STREAM_ID, self.store_for())

    def assert_rejected_unchanged(self, receiver, raw, rejoin=False):
        before = (receiver.frame, receiver.digest, receiver.view())
        with self.assertRaises(ProtocolError):
            (receiver.rejoin if rejoin else receiver.apply)(raw)
        self.assertEqual(before, (receiver.frame, receiver.digest, receiver.view()))

    def test_full_600_frame_roundtrip_and_independent_oracle(self):
        receiver = self.receiver()
        previous = None
        for frame, (raw, _) in enumerate(self.fixtures):
            packet = receiver.apply(raw)
            self.assertEqual((packet.sequence, packet.frame, packet.tick),
                             (frame, frame, frame * 2))
            self.assertEqual(packet.previous, ZERO_HASH if frame % 200 == 0 else previous)
            view = receiver.view()
            # Expected values are calculated here without calling producer helpers.
            self.assertEqual(view["state"], {
                "transform_q16": [65536, 0, 0, 65536, (frame % 120 - 60) * 256,
                                  (frame % 80 - 40) * 256],
                "clear_rgba8": [frame % 256, frame * 3 % 256, frame * 7 % 256, 255],
                "viewport": [0, 0, 256, 256]})
            tint = bytes((frame % 256, 255 - frame % 256, frame * 5 % 256, 255))
            self.assertEqual(view["resources"]["tint"]["sha256"], sha256(tint))
            self.assertEqual(set(view["resources"]), {"tint", "indices", "quad", "triangle"})
            self.assertEqual([draw["op"] for draw in view["draws"]],
                             ["draw_arrays", "draw_elements"])
            self.assertEqual([draw["count"] for draw in view["draws"]], [3, 6])
            for desc in view["resources"].values():
                self.assertEqual(len(receiver.blobs.get(desc["sha256"], desc["size"])), desc["size"])
            previous = hashlib.sha256(raw).digest()
        self.assertEqual(receiver.frame, 599)

    def test_snapshot_join_has_no_prior_blob_or_decoder_state(self):
        baseline = self.receiver()
        hashes = []
        for raw, _ in self.fixtures:
            baseline.apply(raw)
            hashes.append(baseline.state_hash())
        for start in (0, 200, 400):
            store = BlobStore()
            receiver = Receiver(STREAM_ID, store)
            for frame in range(start, 600):
                raw, blobs = self.fixtures[frame]
                for digest, data in blobs.items():
                    store.put(digest, data)
                receiver.apply(raw)
                self.assertEqual(receiver.state_hash(), hashes[frame])

    def test_loss_reorder_duplicate_and_retry(self):
        receiver = self.receiver()
        self.assert_rejected_unchanged(receiver, self.fixtures[1][0])
        receiver.apply(self.fixtures[0][0])
        for bad in (0, 2, 200):
            self.assert_rejected_unchanged(receiver, self.fixtures[bad][0])
        receiver.apply(self.fixtures[1][0])
        receiver.apply(self.fixtures[2][0])

    def test_explicit_rejoin_recovers_gap_and_rejects_old_or_delta(self):
        receiver = self.receiver()
        receiver.apply(self.fixtures[0][0])
        self.assert_rejected_unchanged(receiver, self.fixtures[200][0])
        receiver.rejoin(self.fixtures[200][0])
        self.assert_rejected_unchanged(receiver, self.fixtures[200][0], rejoin=True)
        self.assert_rejected_unchanged(receiver, self.fixtures[0][0], rejoin=True)
        self.assert_rejected_unchanged(receiver, self.fixtures[201][0], rejoin=True)
        receiver.apply(self.fixtures[201][0])

    def test_chain_tamper_and_metadata_corruption(self):
        receiver = self.receiver()
        receiver.apply(self.fixtures[0][0])
        self.assert_rejected_unchanged(receiver, rewritten(self.fixtures[1][0], previous=b"x" * 32))
        # Every byte, including header metadata and stored checksum, is covered.
        raw = self.fixtures[1][0]
        for offset in (0, 6, 7, 8, 12, 28, 36, 44, 52, 84, HEADER.size, len(raw) - 1):
            changed = bytearray(raw)
            changed[offset] ^= 1
            self.assert_rejected_unchanged(receiver, bytes(changed))

    def test_wrong_stream_version_flags_kind_and_time(self):
        receiver = self.receiver()
        receiver.apply(self.fixtures[0][0])
        for kwargs in ({"stream_id": b"z" * 16}, {"sequence": 3}, {"frame": 4}):
            self.assert_rejected_unchanged(receiver, rewritten(self.fixtures[1][0], **kwargs))
        receiver.apply(self.fixtures[1][0])
        self.assert_rejected_unchanged(receiver, rewritten(self.fixtures[2][0], tick=1))
        for offset, value in ((4, 2), (6, 9), (7, 1)):
            raw = bytearray(self.fixtures[2][0])
            raw[offset] = value
            self.assert_rejected_unchanged(receiver, bytes(raw))

    def test_length_truncation_trailing_and_oversize(self):
        raw = self.fixtures[0][0]
        receiver = self.receiver()
        for size in (0, 1, HEADER.size - 1, HEADER.size, len(raw) - 1):
            self.assert_rejected_unchanged(receiver, raw[:size])
        for bad in (raw + b"\x00", bytes(MAX_PACKET + 1)):
            self.assert_rejected_unchanged(receiver, bad)
        with self.assertRaises(ProtocolError):
            encode(SNAPSHOT, STREAM_ID, 0, 0, 0, ZERO_HASH, {"x": ["x" * 256] * 300})

    def test_missing_blob_and_incomplete_snapshot_are_transactional(self):
        raw, blobs = self.fixtures[0]
        for absent in blobs:
            store = BlobStore()
            for digest, data in blobs.items():
                if digest != absent:
                    store.put(digest, data)
            self.assert_rejected_unchanged(Receiver(STREAM_ID, store), raw)
        receiver = self.receiver()
        receiver.apply(raw)
        body = decode(self.fixtures[200][0]).body
        del body["resources"]["quad"]
        self.assert_rejected_unchanged(receiver, rewritten(self.fixtures[200][0], body=body), rejoin=True)
        body = decode(raw).body
        del body["state"]["viewport"]
        self.assert_rejected_unchanged(self.receiver(), rewritten(raw, body=body))

    def test_blob_tamper_size_and_bounds(self):
        store = BlobStore()
        data = b"abcd"
        digest = sha256(data)
        for bad_hash, bad_data in ((digest, b"abce"), ("../bad", data),
                                   (sha256(b""), b""), (digest, b"x" * (MAX_BLOB + 1))):
            with self.assertRaises(ProtocolError):
                store.put(bad_hash, bad_data)
        store.put(digest, data)
        store.put(digest, data)
        self.assertEqual((store.count, store.byte_size), (1, 4))
        with self.assertRaises(ProtocolError):
            store.get(digest, 3)
        receiver = self.receiver()
        body = decode(self.fixtures[0][0]).body
        body["resources"]["tint"]["size"] = 3
        self.assert_rejected_unchanged(receiver, rewritten(self.fixtures[0][0], body=body))

    def test_store_capacity_is_bounded_and_rejection_keeps_contents(self):
        store = BlobStore()
        for index in range(MAX_STORE // MAX_BLOB):
            data = bytes([index]) * MAX_BLOB
            store.put(sha256(data), data)
        with self.assertRaises(ProtocolError):
            store.put(sha256(b"extra"), b"extra")
        self.assertEqual(store.byte_size, MAX_STORE)
        store = BlobStore()
        for index in range(MAX_BLOBS):
            data = struct.pack("<I", index)
            store.put(sha256(data), data)
        with self.assertRaises(ProtocolError):
            store.put(sha256(b"extra"), b"extra")
        self.assertEqual(store.count, MAX_BLOBS)

    def test_strict_canonical_json(self):
        for payload in (b'{"x":1,"x":2}', b'{ "x":1}', b'{"x":1.0}', b'{"x":NaN}',
                        b'{"x":true}', b'{"x":null}', b'[]', b'{"x":"\xff"}',
                        b'{"x":' + b'[' * 1000 + b'0' + b']' * 1000 + b'}',
                        b'{"x":9223372036854775808}'):
            with self.subTest(payload=payload[:50]), self.assertRaises(ProtocolError):
                decode(packet_with_payload(payload))

    def test_schema_draw_resource_and_range_rejections(self):
        raw = self.fixtures[0][0]
        mutations = [
            lambda b: b.update(extra=1),
            lambda b: b.update(profile="unknown"),
            lambda b: b["state"].update(clear_rgba8=[0, 0, 0, 256]),
            lambda b: b["state"].update(viewport=[0, 0, 0, 256]),
            lambda b: b["state"].update(transform_q16=[0] * 5),
            lambda b: b["draws"][0].update(op="eval"),
            lambda b: b["draws"][0].update(first=1),
            lambda b: b["draws"][0].update(count=4),
            lambda b: b["draws"][1].update(count=9),
            lambda b: b["draws"][0].update(tint="quad"),
            lambda b: b["draws"][0].update(vertices="absent"),
            lambda b: b["draws"][0].update(first=[]),
            lambda b: b["resources"]["quad"].update(format="unknown"),
            lambda b: b.update(draws=b["draws"] * (MAX_DRAWS // 2 + 1)),
            lambda b: b.update(resources={"r" + str(i): b["resources"]["tint"]
                                         for i in range(MAX_RESOURCES + 1)}),
        ]
        for mutate in mutations:
            body = copy.deepcopy(decode(raw).body)
            mutate(body)
            with self.subTest(body=body):
                self.assert_rejected_unchanged(self.receiver(), rewritten(raw, body=body))

    def test_index_value_resource_alignment_and_unused_resource_closure(self):
        raw = self.fixtures[0][0]
        for name, fmt, data in (("indices", "index-u16", struct.pack("<6H", 0, 1, 9, 0, 2, 3)),
                                ("quad", "vertex-i16x2", b"abc")):
            receiver = self.receiver()
            receiver.blobs.put(sha256(data), data)
            body = decode(raw).body
            body["resources"][name] = {"format": fmt, "sha256": sha256(data), "size": len(data)}
            self.assert_rejected_unchanged(receiver, rewritten(raw, body=body))
        body = decode(raw).body
        body["resources"]["unused"] = {"format": "rgba8", "sha256": "0" * 64, "size": 4}
        self.assert_rejected_unchanged(self.receiver(), rewritten(raw, body=body))

    def test_deterministic_wire_and_harness(self):
        self.assertEqual(self.fixtures, list(generate()))
        receipt = run()
        self.assertEqual(receipt, run())
        self.assertEqual(receipt["frames"], 600)
        self.assertEqual(receipt["draw_descriptions"], 1200)
        self.assertEqual(receipt["rejoin_frames"], 200)
        self.assertEqual(receipt["transcript_sha256"],
                         "d39dc248c992bad367fca64b6f4cea5d80ae4faaf9f6d8ef8981d2874d508903")
        self.assertEqual(receipt["final_state_sha256"],
                         "e6260b13311bd6634567a9f73aa41adf8d300bcf4bf1444c1e2eb85cfae2b0d1")
        self.assertEqual(canonical({"b": 2, "a": 1}), b'{"a":1,"b":2}')
        # Golden wire vector is independent of fixture formulas/schema.
        raw = encode(SNAPSHOT, bytes(16), 0, 0, 0, ZERO_HASH, {})
        prefix = b"NGS1\x01\x00\x01\x00\x02\x00\x00\x00" + bytes(72)
        expected = prefix + hashlib.sha256(prefix + b"{}").digest() + b"{}"
        self.assertEqual(raw, expected)
        self.assertEqual(HEADER.size, 116)

    def test_accumulated_resource_and_json_complexity_limits(self):
        receiver = self.receiver()
        raw = self.fixtures[0][0]
        body = decode(raw).body
        descriptor = copy.deepcopy(body["resources"]["tint"])
        for index in range(MAX_RESOURCES - len(body["resources"])):
            body["resources"]["r" + str(index)] = descriptor
        receiver.apply(rewritten(raw, body=body))
        delta = decode(self.fixtures[1][0]).body
        delta["resources"]["overflow"] = descriptor
        packet = rewritten(self.fixtures[1][0], previous=receiver.digest, body=delta)
        self.assert_rejected_unchanged(receiver, packet)
        for body in ({"x": [0] * 8192}, {"x": "x" * 257}):
            with self.assertRaises(ProtocolError):
                canonical(body)

    def test_snapshot_predecessor_must_be_zero(self):
        raw = self.fixtures[0][0]
        fields = list(HEADER.unpack_from(raw))
        fields[-2] = b"x" * 32
        prefix = HEADER.pack(*fields)[:-32]
        payload = raw[HEADER.size:]
        invalid = prefix + hashlib.sha256(prefix + payload).digest() + payload
        self.assert_rejected_unchanged(self.receiver(), invalid)

    def test_receiver_view_is_detached(self):
        receiver = self.receiver()
        receiver.apply(self.fixtures[0][0])
        before = receiver.state_hash()
        view = receiver.view()
        view["state"]["viewport"][0] = 999
        view["resources"].clear()
        self.assertEqual(receiver.state_hash(), before)


if __name__ == "__main__":
    unittest.main()
