# Copyright 2026 RoyaleFish contributors
# SPDX-License-Identifier: Apache-2.0
"""Semantic validator for a deliberately small GLES-style fixture profile.

This module neither imports the fixture generator nor executes graphics calls.
"""

import copy
import re
import struct

from wire import (DELTA, MAX_DRAWS, MAX_RESOURCES, SNAPSHOT, BlobStore,
                  canonical, decode, integer, require, sha256)

NAME = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
FORMATS = {"vertex-i16x2": 4, "index-u16": 2, "rgba8": 4}
STATE_KEYS = {"transform_q16", "clear_rgba8", "viewport"}


def keys(value, expected):
    require(type(value) is dict and set(value) == expected, "object fields")


def vector(value, length, low, high):
    require(type(value) is list and len(value) == length, "vector length")
    for item in value:
        integer(item, low, high)


class Receiver:
    """One stream, one context, one surface. Each accepted packet is one frame.

    apply() is strictly contiguous. rejoin() explicitly discards an old segment
    only after validating a complete newer snapshot. Failures are transactional.
    """

    def __init__(self, stream_id, blobs):
        require(type(stream_id) is bytes and len(stream_id) == 16, "stream identity")
        require(isinstance(blobs, BlobStore), "blob store")
        self.stream_id = stream_id
        self.blobs = blobs
        self._packet = None
        self._resources = {}
        self._state = {}
        self._draws = []

    @property
    def frame(self):
        return None if self._packet is None else self._packet.frame

    @property
    def digest(self):
        return None if self._packet is None else self._packet.digest

    def view(self):
        return copy.deepcopy({"resources": self._resources, "state": self._state,
                              "draws": self._draws})

    def state_hash(self):
        return sha256(canonical(self.view()))

    def apply(self, raw):
        return self._accept(raw, rejoin=False)

    def rejoin(self, raw):
        return self._accept(raw, rejoin=True)

    def _accept(self, raw, rejoin):
        packet = decode(raw)
        require(packet.stream_id == self.stream_id, "wrong stream")
        if rejoin or self._packet is None:
            require(packet.kind == SNAPSHOT, "snapshot required")
        if self._packet is not None:
            old = self._packet
            require(packet.sequence > old.sequence and packet.frame > old.frame,
                    "repeated/backward sequence or frame")
            require(packet.tick >= old.tick, "backward tick")
            if not rejoin:
                require(packet.sequence == old.sequence + 1 and packet.frame == old.frame + 1,
                        "missing/reordered predecessor")
        if packet.kind == DELTA:
            require(self._packet is not None and packet.previous == self._packet.digest,
                    "predecessor hash")

        keys(packet.body, {"profile", "resources", "state", "draws"})
        require(packet.body["profile"] == "synthetic-gles-style-v1", "profile")
        resources = {} if packet.kind == SNAPSHOT else copy.deepcopy(self._resources)
        updates = packet.body["resources"]
        require(type(updates) is dict and len(updates) <= MAX_RESOURCES, "resource table limit")
        for name, descriptor in updates.items():
            require(NAME.fullmatch(name), "resource name")
            keys(descriptor, {"sha256", "size", "format"})
            fmt = descriptor["format"]
            require(type(fmt) is str and fmt in FORMATS, "resource format")
            data = self.blobs.get(descriptor["sha256"], descriptor["size"])
            require(len(data) % FORMATS[fmt] == 0, "resource alignment")
            resources[name] = copy.deepcopy(descriptor)
        require(len(resources) <= MAX_RESOURCES, "live resource limit")
        # Full closure is mandatory, including resources not used by this frame.
        for descriptor in resources.values():
            self.blobs.get(descriptor["sha256"], descriptor["size"])

        state = {} if packet.kind == SNAPSHOT else copy.deepcopy(self._state)
        patch = packet.body["state"]
        require(type(patch) is dict and set(patch) <= STATE_KEYS, "state fields")
        state.update(copy.deepcopy(patch))
        keys(state, STATE_KEYS)
        vector(state["transform_q16"], 6, -8 * 65536, 8 * 65536)
        vector(state["clear_rgba8"], 4, 0, 255)
        vector(state["viewport"], 4, 0, 4096)
        require(state["viewport"][2] > 0 and state["viewport"][3] > 0, "empty viewport")

        draws = packet.body["draws"]
        require(type(draws) is list and len(draws) <= MAX_DRAWS, "draw limit")

        def resource(name, fmt):
            require(type(name) is str and name in resources, "missing logical resource")
            desc = resources[name]
            require(desc["format"] == fmt, "resource type")
            return self.blobs.get(desc["sha256"], desc["size"])

        for draw in draws:
            require(type(draw) is dict, "draw object")
            op = draw.get("op")
            require(type(op) is str and op in ("draw_arrays", "draw_elements"), "unsupported draw")
            expected = {"op", "vertices", "tint", "count"}
            keys(draw, expected | ({"first"} if op == "draw_arrays" else {"indices"}))
            vertices = len(resource(draw["vertices"], "vertex-i16x2")) // 4
            require(len(resource(draw["tint"], "rgba8")) == 4, "tint must be one pixel")
            count = integer(draw["count"], 3, 65535)
            require(count % 3 == 0, "triangle count")
            if op == "draw_arrays":
                first = integer(draw["first"], 0, 65535)
                require(first + count <= vertices, "vertex bounds")
            else:
                indices = resource(draw["indices"], "index-u16")
                require(count * 2 <= len(indices), "index buffer bounds")
                require(all(index[0] < vertices for index in
                            struct.iter_unpack("<H", indices[:count * 2])), "index value bounds")

        # No receiver mutation occurs before every envelope/schema/blob check.
        self._resources, self._state = resources, state
        self._draws = copy.deepcopy(draws)
        self._packet = packet
        return packet
