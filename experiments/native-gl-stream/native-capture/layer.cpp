// Copyright 2026 RoyaleFish contributors
// SPDX-License-Identifier: Apache-2.0
#include "layer.hpp"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <limits>
#include <initializer_list>
#include <mutex>
#include <thread>

namespace {
using Viewport = void (GL_APIENTRY *)(GLint, GLint, GLsizei, GLsizei);
using Color = void (GL_APIENTRY *)(GLfloat, GLfloat, GLfloat, GLfloat);
using Clear = void (GL_APIENTRY *)(GLbitfield);
using Arrays = void (GL_APIENTRY *)(GLenum, GLint, GLsizei);
using Elements = void (GL_APIENTRY *)(GLenum, GLsizei, GLenum, const void*);
using Swap = EGLBoolean (EGLAPIENTRY *)(EGLDisplay, EGLSurface);
std::atomic<Viewport> next_viewport{nullptr};
std::atomic<Color> next_color{nullptr};
std::atomic<Clear> next_clear{nullptr};
std::atomic<Arrays> next_arrays{nullptr};
std::atomic<Elements> next_elements{nullptr};
std::atomic<Swap> next_swap{nullptr};
std::mutex mutex;
capture::Log log_data;
std::size_t limit = capture::capacity;
std::uint64_t frame = 0;
bool initialized = false, armed = false;
std::thread::id owner;
thread_local unsigned depth = 0;
constexpr std::size_t absent = capture::capacity;
static_assert(sizeof(GLfloat) == 4 && std::numeric_limits<GLfloat>::is_iec559, "float ABI");
static_assert(sizeof(GLint) == 4 && sizeof(GLenum) == 4, "integer ABI");

std::uint32_t bits(GLfloat value) {
    std::uint32_t word;
    std::memcpy(&word, &value, sizeof(word));
    return word;
}

// Mark entry before calling downstream; never hold our lock during forwarding.
struct Entry {
    std::size_t index = absent;
    bool tracked = false;
    Entry(capture::Op op, std::initializer_list<std::uint32_t> args, bool supported) {
        ++depth;
        std::lock_guard<std::mutex> lock(mutex);
        if (!armed) return;
        tracked = true;
        auto& stats = log_data.stats;
        const auto sequence = stats.calls++;
        if (depth != 1) ++stats.reentrant;
        if (owner != std::this_thread::get_id()) ++stats.thread_errors;
        if (!supported) ++stats.unsupported;
        if (log_data.count >= limit) { ++stats.overflow; return; }
        index = log_data.count++;
        auto& record = log_data.records[index];
        record = {};
        record.sequence = sequence;
        record.frame = frame;
        record.op = op;
        record.argc = static_cast<std::uint32_t>(args.size());
        std::copy(args.begin(), args.end(), record.args.begin());
    }
    void forwarded() {
        if (!tracked) return;
        std::lock_guard<std::mutex> lock(mutex);
        ++log_data.stats.forwards;
    }
    void swapped(EGLBoolean result) {
        if (!tracked) return;
        std::lock_guard<std::mutex> lock(mutex);
        if (index != absent) log_data.records[index].args[0] = result;
        if (result == 1) ++log_data.stats.swaps;
        else ++log_data.stats.failed_swaps;
        ++frame;  // Failed swaps also delimit attempts; acceptance rejects them.
    }
    ~Entry() { --depth; }
};

void GL_APIENTRY record_viewport(GLint x, GLint y, GLsizei w, GLsizei h) {
    Entry entry(capture::viewport, {static_cast<std::uint32_t>(x), static_cast<std::uint32_t>(y),
                                 static_cast<std::uint32_t>(w), static_cast<std::uint32_t>(h)},
                x >= 0 && y >= 0 && w > 0 && h > 0 && x <= 4096 && y <= 4096 && w <= 4096 && h <= 4096);
    const auto next = next_viewport.load();
    if (next) { entry.forwarded(); next(x, y, w, h); }
}
void GL_APIENTRY record_color(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
    const bool supported = std::isfinite(r) && std::isfinite(g) && std::isfinite(b) && std::isfinite(a)
        && r >= 0 && r <= 1 && g >= 0 && g <= 1 && b >= 0 && b <= 1 && a >= 0 && a <= 1;
    Entry entry(capture::color, {bits(r), bits(g), bits(b), bits(a)}, supported);
    const auto next = next_color.load();
    if (next) { entry.forwarded(); next(r, g, b, a); }
}
void GL_APIENTRY record_clear(GLbitfield mask) {
    Entry entry(capture::clear, {mask}, mask == 0x4000);
    const auto next = next_clear.load();
    if (next) { entry.forwarded(); next(mask); }
}
void GL_APIENTRY record_arrays(GLenum mode, GLint first, GLsizei count) {
    Entry entry(capture::arrays, {mode, static_cast<std::uint32_t>(first), static_cast<std::uint32_t>(count)},
                mode == 4 && first == 0 && count == 3);
    const auto next = next_arrays.load();
    if (next) { entry.forwarded(); next(mode, first, count); }
}
void GL_APIENTRY record_elements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
    // Only a null offset is representable. Never dereference/serialize a pointer.
    Entry entry(capture::elements, {mode, static_cast<std::uint32_t>(count), type},
                mode == 4 && count == 6 && type == 0x1403 && indices == nullptr);
    const auto next = next_elements.load();
    if (next) { entry.forwarded(); next(mode, count, type, indices); }
}
EGLBoolean EGLAPIENTRY record_swap(EGLDisplay display, EGLSurface surface) {
    Entry entry(capture::swap, {0}, true);
    const auto next = next_swap.load();
    EGLBoolean result = 0;
    if (next) { entry.forwarded(); result = next(display, surface); }
    entry.swapped(result);
    return result;
}

template <typename Fn>
EGLFuncPointer install(std::atomic<Fn>& slot, Fn wrapper, EGLFuncPointer next) {
    if (!next) { ++log_data.stats.null_lookup; return next; }
    const auto candidate = reinterpret_cast<Fn>(next);
    const auto old = slot.load();
    if (candidate == wrapper || (old && old != candidate)) {
        ++log_data.stats.conflicts;
        return next;  // Never corrupt an established next chain.
    }
    slot.store(candidate);
    return reinterpret_cast<EGLFuncPointer>(wrapper);
}
}  // namespace

extern "C" EGLFuncPointer AndroidGLESLayer_Initialize(const void*, NextLayerProc) {
    std::lock_guard<std::mutex> lock(mutex);
    initialized = true;  // Passive lookup: no platform GPA substitute.
    return nullptr;     // Android 12 loader ignores the typed return value.
}
extern "C" EGLFuncPointer AndroidGLESLayer_GetProcAddress(const char* name, EGLFuncPointer next) {
    std::lock_guard<std::mutex> lock(mutex);
    if (!name) { ++log_data.stats.null_lookup; return next; }
    if (!std::strcmp(name, "glViewport")) return install(next_viewport, record_viewport, next);
    if (!std::strcmp(name, "glClearColor")) return install(next_color, record_color, next);
    if (!std::strcmp(name, "glClear")) return install(next_clear, record_clear, next);
    if (!std::strcmp(name, "glDrawArrays")) return install(next_arrays, record_arrays, next);
    if (!std::strcmp(name, "glDrawElements")) return install(next_elements, record_elements, next);
    if (!std::strcmp(name, "eglSwapBuffers")) return install(next_swap, record_swap, next);
    // Loader enumeration before Begin is normal. A new unsupported lookup while
    // recording invalidates acceptance, while preserving application forwarding.
    if (armed) ++log_data.stats.unsupported;
    return next;  // Includes eglGetProcAddress: the platform owns extension lookup.
}

namespace capture {
bool begin(std::size_t requested_limit) {
    std::lock_guard<std::mutex> lock(mutex);
    if (armed || !initialized || requested_limit == 0 || requested_limit > capacity
        || !next_viewport.load() || !next_color.load() || !next_clear.load()
        || !next_arrays.load() || !next_elements.load() || !next_swap.load()
        || log_data.stats.null_lookup || log_data.stats.conflicts) return false;
    log_data = {};
    limit = requested_limit;
    frame = 0;
    owner = std::this_thread::get_id();
    armed = true;
    return true;
}
Log finish() {
    std::lock_guard<std::mutex> lock(mutex);
    armed = false;
    return log_data;
}
}  // namespace capture
