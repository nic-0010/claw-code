#!/usr/bin/env bash
# build-ios.sh — Build claw-ios-sdk as an XCFramework for iPhone and Simulator.
#
# Usage:
#   cd rust/
#   ./scripts/build-ios.sh           # debug build
#   ./scripts/build-ios.sh --release # release build (use for App Store / TestFlight)
#
# Prerequisites (macOS with Xcode installed):
#   rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
#   cargo build  (first run compiles uniffi-bindgen from the workspace)
#
# Output:
#   build/ClawIosSDK.xcframework       — drop into Xcode or referenced by Package.swift
#   ios-app/Sources/ClawIosSDK/        — generated Swift bindings (auto-copied)

set -euo pipefail

CRATE="claw-ios-sdk"
LIB_NAME="claw_ios_sdk"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${WORKSPACE}/.." && pwd)"
BUILD_DIR="${WORKSPACE}/build"
IOS_SDK_SWIFT_DIR="${REPO_ROOT}/ios-app/Sources/ClawIosSDK"
PROFILE="debug"
CARGO_PROFILE_FLAG=""

for arg in "$@"; do
  case "$arg" in
    --release)
      PROFILE="release"
      CARGO_PROFILE_FLAG="--release"
      ;;
  esac
done

echo "=== claw-ios-sdk xcframework build (${PROFILE}) ==="
echo "  Workspace : ${WORKSPACE}"
echo "  Output    : ${BUILD_DIR}"
echo ""

# ── 0. Prerequisite check ──────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
  echo "✗ This script must run on macOS."
  exit 1
fi

if ! command -v xcodebuild &>/dev/null; then
  echo "✗ xcodebuild not found. Install Xcode from the App Store."
  exit 1
fi

MISSING_TARGETS=()
for t in aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios; do
  rustup target list --installed 2>/dev/null | grep -q "^${t}" || MISSING_TARGETS+=("$t")
done
if [[ ${#MISSING_TARGETS[@]} -gt 0 ]]; then
  echo "✗ Missing Rust targets. Run:"
  for t in "${MISSING_TARGETS[@]}"; do echo "    rustup target add ${t}"; done
  exit 1
fi

echo "✓ Prerequisites OK"
echo ""

# ── 1. Compile for all iOS targets ────────────────────────────────────────────

TARGETS=(
  "aarch64-apple-ios"        # physical iPhone/iPad
  "aarch64-apple-ios-sim"    # Simulator on Apple Silicon Mac
  "x86_64-apple-ios"         # Simulator on Intel Mac
)

for TARGET in "${TARGETS[@]}"; do
  echo "→ cargo build --target ${TARGET} ${CARGO_PROFILE_FLAG}"
  cargo build -p "${CRATE}" --target "${TARGET}" ${CARGO_PROFILE_FLAG}
done

echo ""

# ── 2. Fat simulator library (arm64-sim + x86_64-sim) ─────────────────────────

SIM_ARM="${WORKSPACE}/target/aarch64-apple-ios-sim/${PROFILE}/lib${LIB_NAME}.a"
SIM_X86="${WORKSPACE}/target/x86_64-apple-ios/${PROFILE}/lib${LIB_NAME}.a"
SIM_FAT="${BUILD_DIR}/sim-fat/lib${LIB_NAME}.a"
DEVICE_LIB="${WORKSPACE}/target/aarch64-apple-ios/${PROFILE}/lib${LIB_NAME}.a"

mkdir -p "${BUILD_DIR}/sim-fat"
echo "→ lipo: fat simulator library"
lipo -create "${SIM_ARM}" "${SIM_X86}" -output "${SIM_FAT}"

# ── 3. Generate Swift bindings ─────────────────────────────────────────────────

SWIFT_OUT="${BUILD_DIR}/ClawIosSDK"
mkdir -p "${SWIFT_OUT}"

echo "→ Generating Swift bindings (uniffi-bindgen)"
cargo run -p uniffi-bindgen -- generate \
  --library "${DEVICE_LIB}" \
  --language swift \
  --out-dir "${SWIFT_OUT}"

# Copy generated .swift file(s) into the ios-app source tree so Package.swift
# picks them up automatically (ClawIosSDK target path = Sources/ClawIosSDK/).
mkdir -p "${IOS_SDK_SWIFT_DIR}"
if ls "${SWIFT_OUT}"/*.swift &>/dev/null; then
  cp "${SWIFT_OUT}"/*.swift "${IOS_SDK_SWIFT_DIR}/"
  echo "→ Swift bindings copied to ${IOS_SDK_SWIFT_DIR}/"
fi

echo ""

# ── 4. Headers directory for XCFramework ──────────────────────────────────────

HEADERS_DIR="${BUILD_DIR}/headers"
mkdir -p "${HEADERS_DIR}"

# Copy uniffi-generated C header(s)
if ls "${SWIFT_OUT}"/*.h &>/dev/null; then
  cp "${SWIFT_OUT}"/*.h "${HEADERS_DIR}/"
fi

# Use uniffi's generated modulemap; fall back to a hand-written one.
if ls "${SWIFT_OUT}"/*.modulemap &>/dev/null; then
  # Rename to the conventional module.modulemap expected by xcodebuild.
  FIRST_MM="$(ls "${SWIFT_OUT}"/*.modulemap | head -1)"
  cp "${FIRST_MM}" "${HEADERS_DIR}/module.modulemap"
else
  # Fallback: write a modulemap that matches the ffi_module_name in uniffi.toml.
  cat > "${HEADERS_DIR}/module.modulemap" <<'MODULEMAP'
module ClawIosSDKFFI {
  header "ClawIosSDKFFI.h"
  export *
}
MODULEMAP
fi

# ── 5. Assemble XCFramework ────────────────────────────────────────────────────

XCFW="${BUILD_DIR}/ClawIosSDK.xcframework"
rm -rf "${XCFW}"

echo "→ xcodebuild -create-xcframework → ${XCFW}"
xcodebuild -create-xcframework \
  -library "${DEVICE_LIB}" -headers "${HEADERS_DIR}" \
  -library "${SIM_FAT}"    -headers "${HEADERS_DIR}" \
  -output  "${XCFW}"

echo ""
echo "✓ Build complete!"
echo ""
echo "  XCFramework : ${XCFW}"
echo "  Swift files : ${IOS_SDK_SWIFT_DIR}/"
echo ""
echo "Next: run ios-app/setup_xcode.sh to generate the Xcode project."
