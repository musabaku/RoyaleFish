# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Original NGS1 framing and bounded immutable blob storage; no GL runtime."""

import hashlib
import json
import re
import struct
from dataclasses import dataclass

VERSION = 1
SNAPSHOT, DELTA = 1, 2
ZERO_HASH = bytes(32)
HEADER = struct.Struct("<4sHBBI16sQQQ32s32s")
MAX_PACKET = 64 * 1024
MAX_BLOB = 1024 * 1024
MAX_STORE = 8 * 1024 * 1024
MAX_BLOBS = 1024
MAX_RESOURCES = 64
MAX_DRAWS = 128
MAX_DEPTH = 12
MAX_NODES = 8192
MAX_INT = (1 << 63) - 1
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ProtocolError(ValueError):
    """Untrusted input rejected without changing replay state."""


def require(condition, message):
    if not condition:
        raise ProtocolError(message)


def integer(value, low=0, high=MAX_INT):
    require(type(value) is int and low <= value <= high, "integer out of range")
    return value


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _tree(value, depth=0, budget=None):
    if budget is None:
        budget = [MAX_NODES]
    budget[0] -= 1
    require(depth <= MAX_DEPTH and budget[0] >= 0, "JSON tree limit")
    if type(value) is dict:
        require(all(type(k) is str for k in value), "JSON key type")
        for key, item in value.items():
            require(len(key) <= 128, "JSON key length")
            _tree(item, depth + 1, budget)
    elif type(value) is list:
        for item in value:
            _tree(item, depth + 1, budget)
    elif type(value) is int:
        integer(value, -MAX_INT, MAX_INT)
    else:
        require(type(value) is str and len(value) <= 256, "JSON value type/length")


def canonical(value):
    """Restricted integer/string JSON; floats, booleans and null are forbidden."""
    _tree(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def encode(kind, stream_id, sequence, frame, tick, previous, body):
    require(type(kind) is int and kind in (SNAPSHOT, DELTA), "packet kind")
    require(type(stream_id) is bytes and len(stream_id) == 16, "stream identity")
    require(type(previous) is bytes and len(previous) == 32, "previous hash")
    for value in (sequence, frame, tick):
        integer(value)
    require(kind != SNAPSHOT or previous == ZERO_HASH, "snapshot predecessor")
    payload = canonical(body)
    require(HEADER.size + len(payload) <= MAX_PACKET, "packet limit")
    header = HEADER.pack(b"NGS1", VERSION, kind, 0, len(payload), stream_id,
                         sequence, frame, tick, previous, ZERO_HASH)
    checksum = hashlib.sha256(header[:-32] + payload).digest()
    return header[:-32] + checksum + payload


@dataclass(frozen=True)
class Packet:
    kind: int
    stream_id: bytes
    sequence: int
    frame: int
    tick: int
    previous: bytes
    digest: bytes
    body: dict


def decode(raw):
    require(type(raw) is bytes, "packet must be bytes")
    require(HEADER.size <= len(raw) <= MAX_PACKET, "packet length/limit")
    magic, version, kind, flags, length, stream, seq, frame, tick, prev, digest = HEADER.unpack_from(raw)
    require(magic == b"NGS1", "magic")
    require(version == VERSION, "version")
    require(kind in (SNAPSHOT, DELTA) and flags == 0, "kind/reserved flags")
    require(length == len(raw) - HEADER.size, "payload length")
    for value in (seq, frame, tick):
        integer(value)
    require(kind != SNAPSHOT or prev == ZERO_HASH, "snapshot predecessor")
    payload = raw[HEADER.size:]
    require(hashlib.sha256(raw[:HEADER.size - 32] + payload).digest() == digest,
            "packet content hash")
    try:
        body = json.loads(payload.decode("ascii"), object_pairs_hook=_pairs)
        require(type(body) is dict, "body object")
        require(canonical(body) == payload, "noncanonical JSON")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError("invalid canonical payload: " + str(exc)) from exc
    return Packet(kind, stream, seq, frame, tick, prev,
                  hashlib.sha256(raw).digest(), body)


class BlobStore:
    """Content-addressed raw bytes. Caller must supply the expected digest."""

    def __init__(self):
        self._blobs = {}
        self._size = 0

    @property
    def byte_size(self):
        return self._size

    @property
    def count(self):
        return len(self._blobs)

    def put(self, digest, data):
        require(type(digest) is str and DIGEST.fullmatch(digest), "blob digest")
        require(type(data) is bytes and 0 < len(data) <= MAX_BLOB, "blob size")
        require(sha256(data) == digest, "blob hash")
        if digest in self._blobs:
            return
        require(self._size + len(data) <= MAX_STORE, "blob store byte limit")
        require(len(self._blobs) < MAX_BLOBS, "blob store count limit")
        self._blobs[digest] = data
        self._size += len(data)

    def get(self, digest, size):
        require(type(digest) is str and DIGEST.fullmatch(digest), "blob digest")
        integer(size, 1, MAX_BLOB)
        require(digest in self._blobs, "missing resource blob")
        data = self._blobs[digest]
        require(len(data) == size and sha256(data) == digest, "resource integrity")
        return data
