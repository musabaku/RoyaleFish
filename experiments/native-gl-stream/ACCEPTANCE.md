# Evidence gates

## Current local contract

Protocol/conformance PASS requires the full stdlib suite to pass. It covers:

- 600 contiguous roundtripped frames and 1,200 validated draw descriptions;
- independently calculated expected state, fixed wire/transcript/state hashes;
- complete cold joins at frames 0, 200 and 400, and explicit snapshot recovery;
- rejected loss, reorder, duplicates, wrong stream, version, flags and tick;
- rejected resource/chain/header/body tampering, missing or mis-sized blobs;
- rejected truncated, trailing and oversized packets, invalid schema/JSON;
- bounded store bytes/count, live resource count, draws, JSON complexity and
  vertex/index ranges; and unchanged replay state after failed application.

This gate establishes only synthetic protocol behavior. It does not include a
browser renderer, native layer, Android ABI test, loader admission, running game,
model evaluation, input handling or visual acceptance. A local commit still
needs the parent-controlled independent exact-commit review before publication.

## Future genuine self-owned Android producer

These are required future measurements, not results or permission to run them.
A release must keep separate verdicts for build/static, loader admission, native
capture, protocol validation, browser execution and visual/timing conformance.

1. **Identity and admission:** use a separately authorized, self-owned debuggable
   sample/runtime. Pin source/build/toolchain/ABI/device/driver identities and
   exact layer exports. Demonstrate ordinary loader admission and preserved
   downstream procedure forwarding. No game/account/third-party service is an
   input to this gate.
2. **Unlayered control:** record a baseline on the same sample/source, viewport,
   seed, schedule and renderer; retain its run identity, swap results, GL/EGL
   errors and frame 1/300/600 RGBA hashes. Build success cannot replace a run.
3. **Capture:** one coherent recorder run must show exactly 600 completed sample
   frames and successful swaps, the intended array/indexed draw counts, zero
   null forwards/lookups, failed swaps, GL/EGL errors, dropped records, queue
   overflows or unhandled calls. Report capture overhead and queue peaks.
4. **Semantic coverage:** prove resource creation/update/deletion, virtual IDs,
   program/shader/uniform state, VAO-local EBO state, textures/pixel-store rules,
   FBOs and explicit context/thread/sync ordering for every exercised operation.
   Start with a declared narrow profile; unsupported calls must fail visibly.
   The current synthetic profile does not cover these native states.
5. **Wire/resource closure:** validate all 600 envelopes, complete snapshot
   closure, exact predecessors, blob hashes/lengths and segment/transcript
   identities. Exercise late join, packet loss, context loss and reconnect with
   measured recovery. Do not infer ordering from wall-clock timestamps.
6. **Browser execution:** separately implement/version the WebGL2 lowering
   layer. Record browser/driver/capability identity and rejected features. Require
   600 executed frames, zero missing resources/WebGL errors/stale state, matching
   expected draw/resource lifecycle counts and GPU-completion evidence. Decoder
   acceptance alone is insufficient.
7. **Fidelity and timing:** compare native baseline, layered sample and browser
   checkpoints at frames 1/300/600. Use exact RGBA hashes for intentionally
   identical rendering environments; otherwise retain both hashes and a declared
   justified image-distance threshold. Report capture, encode, transfer, apply,
   GPU completion and presentation timing separately. Do not claim exact fidelity
   from plausible geometry or successful draws.
8. **Receipt/publication:** retain one run identity and immutable input/output
   digests for each measurement. Keep missing measurements as HOLD/NOT_MEASURED.
   Review added public files for source ownership and private data. Proprietary
   games, assets, captures, APKs, model weights and credentials remain excluded.

Passing this future sample gate would establish a self-owned native GLES stream
for its measured subset. A game recreation, mechanics fidelity, lawful engine
integration, human controls and exact game UI/pixels would each require separate
evidence. No such claims are made by this experiment.
