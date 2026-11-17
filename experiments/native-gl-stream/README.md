# Experimental native GL stream foundation

**Synthetic protocol fixture/harness only.** This original, self-contained module
defines a small producer/receiver contract for a future self-owned offline native
engine. It emits and validates 600 frames of GLES-style descriptions. It executes
no GLES, EGL or WebGL calls, captures no native process, and recreates no game.

The user's exact-fidelity target remains an unmet acceptance gate. Passing this
module's conformance tests establishes framing, resource integrity and replay
state consistency for this fixture profile. It does not establish native Clash
Royale rendering, a fresh Counterpush producer, pixel parity or playable battles.

## Run locally

From the repository root, using Python stdlib only:

```sh
python3 -B -m unittest discover -s experiments/native-gl-stream -p 'test_*.py' -v
python3 -B experiments/native-gl-stream/harness.py
```

No installation, dependency resolution, model loading, network connection, GUI,
server, background job or output file is involved. The module does not import the
`royalefish` training package. Python 3.10+ is the intended baseline; the recorded
local verification used Python 3.15.2. Other interpreter versions are unverified.

The harness reports 600 accepted frames, 1,200 validated draw descriptions,
322,633 packet bytes, and 259 unique blobs totaling 1,064 bytes. A second receiver
joins at frame 400 with an empty cache and matches all 200 remaining frame states.
Tests also cold-join at frames 0 and 200 and exercise explicit gap recovery.

Deterministic test pins:

```text
SHA-256 of concatenated packets:
d39dc248c992bad367fca64b6f4cea5d80ae4faaf9f6d8ef8981d2874d508903
SHA-256 of final canonical semantic state:
e6260b13311bd6634567a9f73aa41adf8d300bcf4bf1444c1e2eb85cfae2b0d1
```

Both hashes describe synthetic bytes/state. They are not framebuffer hashes.
The harness explicitly reports `native_frames_observed=0`,
`gl_calls_executed=0`, `native_producer=HOLD`, and
`pixel_fidelity=NOT_MEASURED`.

## Architecture and owned surface

```text
fixture.py (independent synthetic source)
    | packet bytes                  | immutable self-owned resource bytes
    v                               v
wire.decode()                   wire.BlobStore (SHA-256 addressed)
    |                               |
    +------------> replay.Receiver <+
                        |
               validated semantic state
                        |
         future explicit WebGL2 lowering layer (not implemented)
```

| File | Responsibility |
| --- | --- |
| `wire.py` | Versioned binary envelope, canonical JSON, checksums, hard limits, immutable blob store |
| `fixture.py` | Exactly 600 synthetic frames; independent of receiver logic |
| `replay.py` | Strict profile/schema, resource closure, draw bounds, ordering and transactional state |
| `harness.py` | Bounded in-memory producer-to-receiver receipt and cold join |
| `test_protocol.py` | Full roundtrip, independent state expectations, cold joins, negative controls and hash pins |
| `PROTOCOL.md` | Wire layout and replay semantics |
| `ACCEPTANCE.md` | Gates for a future genuine self-owned Android GLES capture |

The fixture changes integer affine transforms, clear colors and a four-byte tint
buffer. Each frame describes a triangle array draw and an indexed quad draw.
Frames 0, 200 and 400 are independent snapshots; other frames are patches to
logical resource bindings and state. Deduplication restarts at every snapshot,
so a new viewer needs no earlier blob history. No recorded frames or external
assets are inputs to the generator.

The receiver deliberately implements a small semantic validation profile. It has
one context/surface, triangle draws and three raw buffer formats. It does not
model programs, shader compilation, textures, FBOs, extensions, thread ordering,
context loss, audio, input or transport. Unsupported fields/operations are
rejected. Expanding coverage requires a new explicit profile and conformance
fixtures rather than accepting arbitrary GL function names.

## Evidence that informed the boundary

The following owner-held documents and frozen client files were read locally on
17 November 2026. They are not copied, bundled, imported or fetched by this
module. This is an original format, with no Counterpush wire compatibility claim.

- The frozen public Counterpush client files `glplayer.js`, `glcodec.js` and
  `libg_live.js`, together with `receiver-protocol-review.md` (6 November),
  establish a WebGL2 receiver for ordered stateful GL packets, joining GL
  snapshots/keyframes, and separately resolved resources. Its codec supports
  `F` frame and `A` resource messages; the inspected live path normally resolves
  immutable resource files separately. Codec support for `A` does not prove live
  delivery of those messages. Decoder history and complete resource availability
  matter for replay.
- The preserved 6 November `offline-gpu-replay-receipt.json` reports **17,636
  recorded frames and 1,911,103 draws** across two old recorded streams, with no
  recorded GL/player errors, missing assets or stale state. Its UTC timestamp is
  late 5 November (6 November in Istanbul). It explicitly records that the
  original engine was not running, no new private match was generated, and
  audio/pixel parity were not verified. This receipt was inspected; that replay
  was not rerun here.
- The owned `CR-GL-600frame-sample-20261117` report records native/API31 layer and
  unsigned APK build/static checks, while Android runtime admission remains
  HOLD and native frames observed remain zero. That layer forwards/counts calls;
  it is not a command/resource recorder. None of its files or artifacts are
  included here.
- The separate `native-gl-producer-research-20261117.md` proposes a semantic
  recorder with shadow state, virtual resource IDs, snapshots, ordering and
  WebGL2 translation. It is an architecture/experiment proposal, not evidence of
  a completed producer. This module implements a bounded original contract seam
  without adopting its proposed wire format or importing third-party code.

A successful graphics receiver does not identify or supply its native producer.
Simulation state, recorded graphics, fresh native capture, browser execution and
exact visual fidelity remain separate evidence layers.

## Integration direction

For a future owned native engine, place a semantic recorder after lawful loader
admission and before transport. Track virtual object identities, resource
versions and explicit ordering; copy bytes when calls occur rather than sending
process pointers. Serialize a complete snapshot, then validated deltas through a
bounded queue. On a gap/overflow/context loss, stop applying deltas and obtain a
new snapshot. A future browser should validate the same contract before a
separate capability-checked WebGL2 adapter executes supported operations.

The current format is an experimental fixture protocol, not a complete GLES
recorder specification. Real program/VAO/EBO/FBO state, shader lowering,
multi-context synchronization, capability negotiation and backpressure require
their own versioned profiles and runtime evidence. The receiver's explicit
`rejoin()` API exercises the recovery seam without introducing a transport server.

## Publication and license

All added code and fixture bytes are newly authored for this module under the
repository's Apache-2.0 license; see root `LICENSE` and `NOTICE`. No proprietary
Counterpush implementation, recorded commands, game artwork, APK, model weights,
binary, credential, HAR, private endpoint or third-party code is included in this
experimental module. Existing repository contents are outside this change.
