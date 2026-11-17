# NGS1 wire and semantic contract (experimental version 1)

One complete packet is a fixed **116-byte** header followed by exactly
`payload_length` bytes. There is no padding, compression, extension header or
implicit trailing data. Integers in the header are little-endian. Parsing a
network byte stream must first read the fixed header, reject an excessive length,
then obtain exactly that payload; `decode()` accepts one complete `bytes` packet.
Transport framing/queues are outside this module.

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | ASCII `NGS1` magic |
| 4 | 2 | Version, exactly 1 |
| 6 | 1 | Kind: 1 snapshot/keyframe, 2 delta |
| 7 | 1 | Reserved flags, exactly zero |
| 8 | 4 | Payload length in bytes |
| 12 | 16 | Opaque stream identity, pinned by the receiving application |
| 28 | 8 | Packet sequence |
| 36 | 8 | Render frame number |
| 44 | 8 | Simulation tick |
| 52 | 32 | Previous complete packet's SHA-256; zero for every snapshot |
| 84 | 32 | Content checksum: SHA-256 of header bytes 0..83 followed by payload |
| 116 | variable | Canonical ASCII JSON payload |

Sequence, frame and tick values are nonnegative and capped at `2^63 - 1`, despite
their unsigned 64-bit storage. Tick is simulation identity, not wall-clock time.
Multiple render frames may share a tick. Sequence and frame must each advance by
exactly one under normal `apply()`; tick must not go backward. The fixture uses
frame/sequence 0..599 and tick `2 * frame`, independent of scheduling or arrival.
There is no claim about a game's tick duration.

The content checksum immediately detects corruption of header metadata and body.
The chain identity is **SHA-256 of the complete packet including that checksum**.
A delta's previous hash must equal the last accepted packet's chain identity.
Snapshots set previous to zero and start independent segments; the transcript
hash in the harness covers concatenated complete packets across all segments.

These hashes provide integrity relative to a trusted anchor, not authentication.
An attacker who can replace a snapshot and recompute checksums can invent a new
valid stream. Pin stream identity plus a trusted snapshot/transcript digest, or
add separately designed authenticated transport, before trusting an external
producer. No key exchange, signature or MAC is implemented here.

## Payload encoding

JSON uses sorted object keys, no whitespace, ASCII escaping, and only objects,
arrays, strings and signed integers in `[-(2^63-1), 2^63-1]`. Floats, exponent
numbers, booleans, null, duplicate keys and noncanonical encodings are rejected.
The decoder reserializes and compares exact canonical bytes. Semantic objects
reject unknown fields. Arbitrary executable strings or GL function names are
never dispatched.

Every payload has exactly these fields:

```json
{"draws":[],"profile":"synthetic-gles-style-v1","resources":{},"state":{}}
```

This shows the field shape only; an actual snapshot needs complete valid state.

`resources` maps logical names (`[a-z][a-z0-9_]{0,31}`) to descriptors containing
exactly `sha256` (64 lowercase hex characters), `size` (bytes), and `format`.
Resource bytes travel separately through `BlobStore.put(expected_hash, bytes)`.
The receiver verifies every live descriptor's size/hash before accepting a frame,
including resources unused by that frame. Missing data rejects the frame; there
is no placeholder/partial replay. Content is immutable; a resource update rebinds
its logical name to a new descriptor/hash. Snapshots replace the entire table;
deltas patch it. Version 1 has no deletion opcode; a snapshot can retire resources.

| Format | Contents | Validation |
| --- | --- | --- |
| `vertex-i16x2` | Little-endian signed i16 `(x,y)` vertex pairs | Nonempty, multiple of 4 bytes |
| `index-u16` | Little-endian unsigned i16 indices | Nonempty, multiple of 2 bytes |
| `rgba8` | Raw unsigned RGBA bytes | Nonempty, multiple of 4; draw tint requires exactly 4 bytes |

Snapshot `state` contains all three fields. Delta `state` may patch any subset:

- `transform_q16`: six integers `[a,b,c,d,tx,ty]`, each in
  `[-8*65536,8*65536]`. Intended affine meaning:
  `x'=(a*x+c*y+tx)/65536`, `y'=(b*x+d*y+ty)/65536`.
- `clear_rgba8`: four integers in `[0,255]`.
- `viewport`: `[x,y,width,height]`, each in `[0,4096]`, with nonzero width/height.

These describe abstract fixture state; there is no implicit shader, framebuffer
or graphics backend. They do not specify rasterization/pixel results.

`draws` is a complete per-frame list, never an incremental list. Supported
descriptions are triangle `draw_arrays` (`op`, `vertices`, `tint`, `first`,
`count`) and triangle `draw_elements` (`op`, `vertices`, `tint`, `indices`,
`count`). `vertices` must resolve to a vertex buffer and `tint` to one RGBA pixel.
Counts are positive multiples of three in `[3,65535]`; `first` is in `[0,65535]`.
Array ranges and indexed buffer reads/vertex indices must stay in bounds. There
are no process addresses, bytecode, shader execution or arbitrary API calls.

## Snapshot, ordering and rejoin

A new receiver requires a complete snapshot and its blob closure; an arbitrary
delta cannot initialize it. The first snapshot may have nonzero sequence/frame
values for a late join. An active receiver's `apply()` accepts only the next
sequence/frame, including when that next packet is a snapshot. A delta also
requires the exact previous packet hash. Duplicate, reordered and missing
predecessors are rejected.

For recovery, `rejoin(snapshot)` explicitly permits a jump forward in both
sequence and frame, with a nondecreasing tick and the same pinned stream ID. It
accepts no delta, repeated or older snapshot. The full new resource table and
state are validated without using old replay state. A new viewer can use a fresh
blob store; the fixture re-emits snapshot resources and resets its deduplication
history at that boundary so future references remain resolvable.

All failures leave the receiver's accepted state/hash/frame unchanged. A caller
may supply missing blobs or resend the missing predecessor and retry, or request
a fresh snapshot. There is no hidden reordering buffer or automatic skipping.
Blob insertion is a separate transaction; previously inserted valid immutable
blobs stay cached if a frame fails. Store reclamation is explicit: a caller can
construct a new store/receiver for a snapshot. No silent eviction is performed.

## Hard limits

| Surface | Bound |
| --- | --- |
| Complete packet, header included | 65,536 bytes |
| Individual raw blob | 1..1,048,576 bytes |
| Blob cache | 8,388,608 bytes and 1,024 unique blobs |
| Live logical resources / updates in a packet | 64 |
| Draw descriptions per frame | 128 |
| JSON depth / nodes | 12 / 8,192 |
| JSON key / string length | 128 / 256 characters |

The whole-packet size is checked before JSON parsing; blob size/hash/capacity are
checked before insertion. Callers must also bound transport input and queues
before constructing the `bytes` objects. Hashing/storage are synchronous; a full
cache rejects further insertion. This is a bounded fixture foundation with no
live throughput, concurrency or denial-of-service acceptance claim.
