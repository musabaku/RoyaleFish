// Copyright 2026 RoyaleFish contributors
// SPDX-License-Identifier: Apache-2.0
// Independent fake downstream driver; no graphics API or Android runtime linked.
#include "layer.hpp"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>

namespace {
using VP = void (*)(GLint, GLint, GLsizei, GLsizei);
using CC = void (*)(GLfloat, GLfloat, GLfloat, GLfloat);
using CL = void (*)(GLbitfield);
using DA = void (*)(GLenum, GLint, GLsizei);
using DE = void (*)(GLenum, GLsizei, GLenum, const void*);
using SW = EGLBoolean (*)(EGLDisplay, EGLSurface);
VP viewport;
CC color;
CL clear;
DA arrays;
DE elements;
SW swap;
std::array<std::uint64_t, 6> counts{};
unsigned invocation = 0, sample_frame = 0;
bool strict = true, nested = false, failed = false;
int display_object, surface_object, index_object;
bool saw_pointer = false;

void check(bool ok, const char* reason) {
    if (!ok) { std::cerr << "FAIL: " << reason << '\n'; std::exit(1); }
}
void called(unsigned op) {
    if (strict) check(invocation % 6 == op, "next-driver ordering");
    ++invocation;
    ++counts[op];
}
void fake_viewport(GLint x, GLint y, GLsizei w, GLsizei h) {
    called(0);
    if (strict) check(x == static_cast<int>(sample_frame % 3) && y == 0
        && w == 256 + static_cast<int>(sample_frame % 4) && h == 256, "viewport forwarding");
}
void fake_color(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
    called(1);
    if (strict) check(r == (sample_frame % 256) / 256.0f && g == .25f && b == .5f && a == 1,
                      "float argument forwarding");
}
void fake_clear(GLbitfield mask) {
    called(2);
    if (strict) check(mask == 0x4000, "clear forwarding");
    if (nested) viewport(0, 0, 256, 256);
}
void fake_arrays(GLenum mode, GLint first, GLsizei count) {
    called(3);
    if (strict) check(mode == 4 && first == 0 && count == 3, "array forwarding");
}
void fake_elements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
    called(4);
    if (indices) { check(indices == &index_object, "unsupported pointer preserved"); saw_pointer = true; }
    if (strict) check(mode == 4 && count == 6 && type == 0x1403 && indices == nullptr,
                      "element forwarding");
}
EGLBoolean fake_swap(EGLDisplay display, EGLSurface surface) {
    called(5);
    check(display == &display_object && surface == &surface_object, "opaque handle forwarding");
    return failed ? 0 : 1;
}
void alternative_arrays(GLenum, GLint, GLsizei) {}
void unknown() {}
void* forbidden_active_lookup(void*, const char*) {
    check(false, "passive initializer unexpectedly queried next");
    return nullptr;
}
template <typename T> T bind(const char* name, T next) {
    const auto supplied = reinterpret_cast<EGLFuncPointer>(next);
    const auto wrapped = AndroidGLESLayer_GetProcAddress(name, supplied);
    check(wrapped && wrapped != supplied, "interception was not installed");
    return reinterpret_cast<T>(wrapped);
}
std::uint32_t float_bits(float value) {
    std::uint32_t result;
    std::memcpy(&result, &value, 4);
    return result;
}
void emit_frame(bool omitted = false) {
    viewport(static_cast<int>(sample_frame % 3), 0, 256 + static_cast<int>(sample_frame % 4), 256);
    color((sample_frame % 256) / 256.0f, .25f, .5f, 1);
    if (!omitted) clear(0x4000);
    arrays(4, 0, 3);
    elements(4, 6, 0x1403, nullptr);
    check(swap(&display_object, &surface_object) == (failed ? 0U : 1U), "swap return preserved");
}
void word(std::uint64_t value, unsigned width) {
    for (unsigned byte = 0; byte < width; ++byte) std::cout.put(static_cast<char>((value >> (8 * byte)) & 255));
}
void emit(const capture::Log& log) {
    std::cout.write("NCAP", 4);
    word(1, 4); word(48, 4); word(log.count, 4);
    const auto& s = log.stats;
    for (auto value : {s.calls, s.forwards, s.swaps, s.failed_swaps, s.overflow,
                       s.reentrant, s.unsupported, s.null_lookup, s.conflicts, s.thread_errors}) word(value, 8);
    for (std::size_t index = 0; index < log.count; ++index) {
        const auto& r = log.records[index];
        word(r.sequence, 8); word(r.frame, 8); word(r.op, 4); word(r.argc, 4);
        for (auto arg : r.args) word(arg, 4);
    }
    check(static_cast<bool>(std::cout), "capture output");
}
}  // namespace

int main(int argc, char** argv) {
    const std::string mode = argc == 1 ? "good" : argv[1];
    check(argc <= 2, "arguments");
    check(!capture::begin(), "capture began without loader callbacks");
    const LayerInit init = &AndroidGLESLayer_Initialize;
    const LayerSetup setup = &AndroidGLESLayer_GetProcAddress;
    check(init(nullptr, forbidden_active_lookup) == nullptr, "initializer typed result");
    const auto passthrough = reinterpret_cast<EGLFuncPointer>(&unknown);
    check(setup("eglGetProcAddress", passthrough) == passthrough, "platform GPA passthrough");
    viewport = bind("glViewport", &fake_viewport);
    check(!capture::begin(), "partial callback admission");
    color = bind("glClearColor", &fake_color);
    clear = bind("glClear", &fake_clear);
    arrays = bind("glDrawArrays", &fake_arrays);
    elements = bind("glDrawElements", &fake_elements);
    swap = bind("eglSwapBuffers", &fake_swap);
    check(!capture::begin(0) && !capture::begin(capture::capacity + 1), "invalid capacity");
    check(capture::begin(mode == "overflow" ? 8 : capture::capacity), "callback admission");
    check(!capture::begin(), "active run reset");

    if (mode == "good") {
        for (sample_frame = 0; sample_frame < 600; ++sample_frame) emit_frame();
    } else {
        strict = false;
        if (mode == "reentrant") nested = true;
        else if (mode == "failed-swap") failed = true;
        else if (mode == "thread") { std::thread other([] { viewport(0, 0, 256, 256); }); other.join(); }
        else if (mode == "unsupported") arrays(4, 0, 4);
        else if (mode == "pointer") elements(4, 6, 0x1403, &index_object);
        else if (mode == "lookup") check(setup("unsupportedExtension", passthrough) == passthrough, "unknown forwarding");
        else if (mode == "null-lookup") check(setup("glClear", nullptr) == nullptr, "null lookup passthrough");
        else if (mode == "conflict") {
            const auto other = reinterpret_cast<EGLFuncPointer>(&alternative_arrays);
            check(setup("glDrawArrays", other) == other, "conflicting next passthrough");
        } else check(mode == "overflow" || mode == "omitted", "unknown mode");
        emit_frame(mode == "omitted");
        if (mode == "overflow") { ++sample_frame; emit_frame(); }
    }
    const auto log = capture::finish();
    check(log.stats.calls == invocation && log.stats.forwards == invocation, "exactly once forwarding");
    if (mode == "good") {
        check(log.count == 3600 && log.stats.swaps == 600, "600-frame call count");
        for (auto count : counts) check(count == 600, "per-callback forwarding count");
        for (unsigned i = 0; i < 3600; ++i) {
            const auto& r = log.records[i];
            const unsigned f = i / 6, op = i % 6;
            check(r.sequence == i && r.frame == f && r.op == op + 1, "record ordering");
            const std::array<std::uint32_t, 6> sizes{{4, 4, 1, 3, 3, 1}};
            const std::array<std::array<std::uint32_t, 6>, 6> args{{
                {{f % 3, 0, 256 + f % 4, 256, 0, 0}},
                {{float_bits((f % 256) / 256.0f), float_bits(.25f), float_bits(.5f), float_bits(1), 0, 0}},
                {{0x4000, 0, 0, 0, 0, 0}}, {{4, 0, 3, 0, 0, 0}},
                {{4, 6, 0x1403, 0, 0, 0}}, {{1, 0, 0, 0, 0, 0}}}};
            check(r.argc == sizes[op] && r.args == args[op], "independent record argument oracle");
        }
    } else if (mode == "overflow") check(log.count == 8 && log.stats.overflow == 4 && invocation == 12, "overflow forwarding");
    else if (mode == "omitted") check(log.count == 5 && invocation == 5, "omitted call scenario");
    else if (mode == "failed-swap") check(log.stats.failed_swaps == 1 && log.stats.swaps == 0, "failed swap receipt");
    else if (mode == "reentrant") check(log.stats.reentrant == 1 && invocation == 7, "reentry receipt");
    else if (mode == "thread") check(log.stats.thread_errors == 1 && invocation == 7, "thread receipt");
    else if (mode == "null-lookup") check(log.stats.null_lookup == 1, "null lookup receipt");
    else if (mode == "conflict") check(log.stats.conflicts == 1, "conflict receipt");
    else if (mode == "pointer") check(saw_pointer && log.stats.unsupported == 1, "pointer rejection receipt");
    else check(log.stats.unsupported == 1, "unsupported profile receipt");
    emit(log);
    std::cerr << "PASS_HOST_CALLBACKS " << mode << " calls=" << invocation << " GPU_frames=0\n";
}
