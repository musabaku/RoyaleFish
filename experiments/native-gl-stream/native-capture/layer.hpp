// Copyright 2026 RoyaleFish contributors
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <type_traits>
#if defined(NGS_HOST_TEST)
// Original host ABI doubles, never a substitute for Android header validation.
using GLenum = unsigned int;
using GLbitfield = unsigned int;
using GLint = int;
using GLsizei = int;
using GLfloat = float;
using EGLBoolean = unsigned int;
using EGLDisplay = void*;
using EGLSurface = void*;
using EGLFuncPointer = void (*)();
#define GL_APIENTRY
#define EGLAPIENTRY
#else
#include <EGL/egl.h>
#include <GLES2/gl2.h>
using EGLFuncPointer = __eglMustCastToProperFunctionPointerType;
#endif

// Match the pinned Android 12 LayerLoader typedefs, not the guide's examples.
using NextLayerProc = void* (*)(void*, const char*);
using LayerInit = EGLFuncPointer (*)(const void*, NextLayerProc);
using LayerSetup = EGLFuncPointer (*)(const char*, EGLFuncPointer);
extern "C" {
__attribute__((visibility("default"))) EGLFuncPointer AndroidGLESLayer_Initialize(
    const void* layer_id, NextLayerProc get_next);
__attribute__((visibility("default"))) EGLFuncPointer AndroidGLESLayer_GetProcAddress(
    const char* name, EGLFuncPointer next);
}
static_assert(std::is_same<decltype(&AndroidGLESLayer_Initialize), LayerInit>::value, "init ABI");
static_assert(std::is_same<decltype(&AndroidGLESLayer_GetProcAddress), LayerSetup>::value, "setup ABI");

namespace capture {
constexpr std::size_t capacity = 4096;
enum Op : std::uint32_t { viewport = 1, color, clear, arrays, elements, swap };
struct Record {
    std::uint64_t sequence = 0, frame = 0;
    std::uint32_t op = 0, argc = 0;
    std::array<std::uint32_t, 6> args{};
};
struct Stats {
    std::uint64_t calls = 0, forwards = 0, swaps = 0, failed_swaps = 0;
    std::uint64_t overflow = 0, reentrant = 0, unsupported = 0;
    std::uint64_t null_lookup = 0, conflicts = 0, thread_errors = 0;
};
struct Log {
    Stats stats;
    std::size_t count = 0;
    std::array<Record, capacity> records{};
};
// Control/read only with application calls quiescent; one owner thread per run.
// Begin fails unless Initialize and all six non-null next callbacks are present.
bool begin(std::size_t limit = capacity);
Log finish();
}  // namespace capture
