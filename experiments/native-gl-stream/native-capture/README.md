# Native GLES callback capture seam

**PASS: host callback interception, downstream forwarding, ordered capture and
NGS1 call-audit conformance. HOLD: Android build/admission, GPU execution and
renderable native GL stream. GPU/native frames observed: 0.**

This is newly authored Apache-2.0 source for a separately owned debug sample. The
actual C++ layer callbacks now produce records when invoked through
`AndroidGLESLayer_GetProcAddress`. A separate fake downstream driver executes 600
swap-delimited frames and checks the callbacks independently. This is a native
function interception test, not an Android loader run or GPU draw.

## Reproduce

From the repository root, with the installed `clang++` and Python stdlib:

```sh
python3 -B experiments/native-gl-stream/native-capture/test_capture.py
python3 -B -m unittest discover -s experiments/native-gl-stream -p 'test_protocol.py' -v
```

The first command builds only `layer.cpp` and `host_driver.cpp` into the owned
`.local-build/host-driver`, then runs eight tests including ten invalid native
capture scenarios. No downloads or dependencies are installed. The second command
retains the original 17 protocol tests unchanged. Compilation uses C++17,
`-Wall -Wextra -Werror -pedantic -pthread`, and UndefinedBehaviorSanitizer with
`-fno-sanitize-recover=all`. Compiler/run timeouts are 60/10 seconds.

For a standalone capture/adapter demonstration after the test has built the driver:

```sh
cd experiments/native-gl-stream/native-capture
.local-build/host-driver good > .local-build/capture.ncap
python3 -B adapter.py .local-build/capture.ncap
```

The binary stream is on stdout; native assertions/results go to stderr. The
adapter prints a JSON receipt after validating capture bytes, creating 600 NGS1
packets and consuming them with its separate audit receiver. It also cold-joins
at frame 400 with a fresh blob cache. Test builds and example captures are local,
ignored artifacts; no binaries or captured logs are committed.

Recorded verification: Apple Clang 17.0.0, arm64 macOS, Python 3.15.2. An initial
AddressSanitizer build stalled before `main` inside ASan shadow-memory/runtime
initialization; the owned process was stopped after a stack sample. UBSan runs
complete successfully. **ASan coverage is unverified.** No Android NDK compile,
shared-library loading, installation, settings change or device/VM run was done.

## ABI decision

The [Android GLES layer guide](https://developer.android.com/ndk/guides/rootless-debug-gles)
describes debug-app loading and chained forwarding. Its overview and examples
use inconsistent `void*`, `void` and function-pointer returns. This implementation
instead pins the concrete
[Android 12 loader header](https://android.googlesource.com/platform/frameworks/native/+/android-12.0.0_r1/opengl/libs/EGL/egl_layers.h):
the initializer returns `EGLFuncPointer`, takes `const void*` and a next-lookup
callback; setup takes a name and next `EGLFuncPointer`, and returns
`EGLFuncPointer`. The next-lookup callback returns `void*` and takes
`(void*, const char*)`. The
[loader implementation](https://android.googlesource.com/platform/frameworks/native/+/android-12.0.0_r1/opengl/libs/EGL/egl_layers.cpp)
ignores the initializer result; this layer returns null and initializes passively.
It never substitutes a platform GPA lookup for the supplied next function.

`layer.hpp` asserts both export types. Android compilation selects actual EGL and
GLES2 headers; `NGS_HOST_TEST` selects small original ABI doubles. Host assertions
verify the selected prototype contract, not compatibility with a running Android
loader or an untested Android revision. The old counting sample is unchanged.

The [ANGLE capture guide](https://github.com/google/angle/blob/main/doc/CaptureAndReplay.md)
still lists incomplete GLES capture and unsupported EGL capture/replay. ANGLE is
neither imported nor used as evidence that this recorder covers full GLES state.

## Admitted calls and preservation

| Callback | Audit subset |
| --- | --- |
| `glViewport` | Nonnegative x/y, positive width/height, each <=4096 |
| `glClearColor` | Finite [0,1] floats, stored as exact IEEE-754 u32 bits |
| `glClear` | Color-buffer mask only |
| `glDrawArrays` | TRIANGLES, first 0, count 3 |
| `glDrawElements` | TRIANGLES, count 6, UNSIGNED_SHORT, null index offset only |
| `eglSwapBuffers` | Exact display/surface arguments forwarded; actual boolean return recorded |

Each admitted function stores its exact next function pointer. Repeated identical
lookups are permitted; conflicting/self pointers and null next lookups reject
capture admission/acceptance without replacing an established chain. Unknown
lookups return the supplied next pointer unchanged, including platform
`eglGetProcAddress`. Before capture, loader enumeration is allowed. A new unknown
lookup during capture conservatively invalidates the audit.

Wrappers call the next function exactly once with unchanged arguments even when
capture is invalid or full. Swap results are returned unchanged. No `glGetError`
or other state-consuming GL query is inserted. GL/EGL errors are **not measured**.
Non-null index pointers are forwarded but never dereferenced or serialized; that
capture is marked unsupported and the adapter rejects it. No geometry, shaders,
textures, process addresses, display/surface pointers or external assets appear
in records.

Capture requires explicit `capture::begin()` after initialization and all six
next functions are available. Begin/finish are sample-owned control APIs invoked
only while calls are quiescent; they are not Android lifecycle hooks. No implicit
file writer/thread/server runs inside the layer. A future sample bridge must wire
these controls and export the log; that integration is not implemented here.

## Ordering, bounds and fault gates

The log has 4,096 fixed record slots (no overwrite); tests may select a lower
limit. Entry sequence/frame is assigned under a mutex before forwarding, and the
mutex is released while calling the driver. Swap return is filled afterward.
Records are read only after application calls finish. Overflow preserves existing
records, increments a fault counter and continues forwarding. Memory use is fixed
inside the callback log; no per-call heap allocation or asynchronous drain occurs.

Counters cover attempted calls, downstream forwards, successful/failed swaps,
overflow, reentry, unsupported arguments/lookups, null lookups, conflicting next
functions and a second calling thread. An owner-thread ID and thread-local depth
detect unsupported concurrency/reentry. A mutex makes the diagnostic log safe;
it does not invent valid multi-context or cross-thread GL ordering. Any fault
rejects adaptation. Failed swaps still delimit attempts and cannot become
successful frames.

The adapter additionally requires exactly one occurrence of each admitted call
in the order shown above per frame. Omitted, duplicated or reordered admitted
calls reject the capture, as do unsupported arguments, failed swaps and nonzero
reserved data. All 600 host frames contain changing viewport and float-color
values; the native fake driver and Python test each calculate their own expected
values rather than importing a synthetic packet generator.

**Coverage boundary:** an unwrapped function resolved before capture can be called
without this layer observing it. Static/dynamic entrypoint coverage and all setup
state are therefore still HOLD. The profile is an audit of these six callbacks
under an explicit owned-sample contract, not proof that an arbitrary app issued
no other calls. General capture acceptance requires generated wrapper coverage
and independently observed function/context inventories. This limitation cannot
be repaired by treating unknown pointers as callable generic wrappers.

## NCAP and NGS1 audit wire

NCAP is a bounded diagnostic container, serialized field-by-field little-endian,
never by dumping a native struct. Its 96-byte header has `NCAP`, u32 version 1,
u32 record size 48, u32 count, then ten u64 counters in the order listed above.
Each 48-byte record is u64 sequence, u64 frame, u32 opcode, u32 argument count,
and six u32 argument words. Unused words must be zero. Opcodes 1..6 correspond to
the table. Frame/sequence start at zero; successful output is 600 frames, 3,600
records, 172,896 bytes. The bounded parser accepts at most 600 complete frames.
NCAP itself has no checksum/authentication; retain a trusted complete-capture
SHA-256 anchor. Corruption into another plausible NCAP value before anchoring
cannot be detected from syntax alone.

`adapter.py` validates the entire container before producing any packets. It
uses the existing NGS1 envelope unchanged and the new **`native-call-audit-v1`**
profile. Each frame's six raw records become a separate SHA-256 blob; the packet
contains its digest/size, complete viewport/color audit state, capture SHA-256
and cumulative admitted-call count. The stream ID is the capture hash's first
16 bytes. Sequence/frame equal the captured frame; simulation tick is **unknown**
and encoded as zero, never guessed from swap count.

Frames 0/200/400 use NGS1 snapshots of **audit state**, not restorable GL object
snapshots. Other packets require the prior complete packet hash. Each frame
carries its own blob closure; joins require no earlier cache. `AuditReceiver`
pins the capture identity, validates raw events and state, and updates only after
all checks pass. Its explicit `rejoin=True` accepts a newer audit snapshot across
a gap. The original synthetic receiver rejects this distinct profile.

Deterministic host capture SHA-256:
`6714b4dc5b3d07facc4e2be44f052e1aa716d2b952933381eea1061a1a73698f`.
NGS1 transcript SHA-256:
`309fb57c0d784c04c8c037e8fd7c7bb46635ff76f4fd96832abacb3c70b92bd8`.
These are call-audit hashes, not framebuffer hashes or authenticated provenance.

## Next acceptance gate

The achieved increment is real C++ callback-to-log-to-NGS1 audit production under
an independent mock driver. Before claiming a live native producer, separately
verify an Android NDK build against the selected loader revision, lawful debug
sample admission, sample-owned begin/finish/export integration and 600 real swaps.
Then capture resources/programs/VAOs/EBOs and full state with a new rendering
profile, implement a validated GPU receiver, and compare layered/unlayered pixels
at fixed checkpoints. Preserve separate build, loader, capture, browser and exact
fidelity verdicts from the parent experiment's acceptance ledger.

No game/account/Counterpush endpoint, proprietary source/asset, model weight,
Android setting or other writer's working directory is involved. All added source
is original and uses the repository's Apache-2.0 license and notices.
