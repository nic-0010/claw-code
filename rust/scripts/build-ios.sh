#!/usr/bin/env bash
# build-ios.sh — Build claw-ios-sdk as an XCFramework for iPhone and Simulator.
#
# Prerequisites (run on macOS with Xcode installed):
#   rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
#   cargo install uniffi-bindgen-swift  (or: cargo install uniffi-bindgen)
#
# Output:
#   ./build/ClawIosSDK.xcframework    — drop into Xcode
#   ./build/ClawIosSDK/               — generated Swift bindings
#
# Usage:
#   cd rust/
#   ./scripts/build-ios.sh [--release]

set -euo pipefail

CRATE="claw-ios-sdk"
LIB_NAME="claw_ios_sdk"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${WORKSPACE}/build"
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

echo "→ Building claw-ios-sdk (profile: ${PROFILE})"
echo "  Workspace: ${WORKSPACE}"
echo "  Output:    ${BUILD_DIR}"

# ── 1. Compile for all iOS targets ─────────────────────────────────────────

TARGETS=(
  "aarch64-apple-ios"          # physical iPhone/iPad
  "aarch64-apple-ios-sim"      # Simulator on Apple Silicon
  "x86_64-apple-ios"           # Simulator on Intel Mac
)

for TARGET in "${TARGETS[@]}"; do
  echo "→ cargo build --target ${TARGET} ${CARGO_PROFILE_FLAG}"
  cargo build -p "${CRATE}" --target "${TARGET}" ${CARGO_PROFILE_FLAG}
done

# ── 2. Create fat library for simulator (arm64 + x86_64) ──────────────────

SIM_ARM="${WORKSPACE}/target/aarch64-apple-ios-sim/${PROFILE}/lib${LIB_NAME}.a"
SIM_X86="${WORKSPACE}/target/x86_64-apple-ios/${PROFILE}/lib${LIB_NAME}.a"
SIM_FAT="${BUILD_DIR}/sim-fat/lib${LIB_NAME}.a"
DEVICE_LIB="${WORKSPACE}/target/aarch64-apple-ios/${PROFILE}/lib${LIB_NAME}.a"

mkdir -p "${BUILD_DIR}/sim-fat"
echo "→ lipo: creating fat simulator library"
lipo -create "${SIM_ARM}" "${SIM_X86}" -output "${SIM_FAT}"

# ── 3. Generate Swift bindings ─────────────────────────────────────────────

SWIFT_OUT="${BUILD_DIR}/ClawIosSDK"
mkdir -p "${SWIFT_OUT}"

echo "→ Generating Swift bindings with uniffi-bindgen"
# uniffi-bindgen-swift uses the library itself to extract the interface.
# If you installed uniffi-bindgen instead, use:
#   uniffi-bindgen generate --library "${DEVICE_LIB}" --language swift --out-dir "${SWIFT_OUT}"
if command -v uniffi-bindgen-swift &>/dev/null; then
  uniffi-bindgen-swift "${DEVICE_LIB}" --out-dir "${SWIFT_OUT}"
else
  cargo run --manifest-path "${WORKSPACE}/Cargo.toml" \
    -p uniffi-bindgen -- generate \
    --library "${DEVICE_LIB}" \
    --language swift \
    --out-dir "${SWIFT_OUT}" 2>/dev/null \
  || (
    echo "⚠  uniffi-bindgen not found. Install with:"
    echo "     cargo install uniffi-bindgen"
    echo "   Then re-run this script."
    echo "   Swift bindings will NOT be included in the XCFramework headers."
  )
fi

# ── 4. Compile .modulemap + headers for XCFramework ───────────────────────

HEADERS_DIR="${BUILD_DIR}/headers"
mkdir -p "${HEADERS_DIR}"

# Copy the generated .h and modulemap from uniffi output, if present.
if ls "${SWIFT_OUT}"/*.h &>/dev/null; then
  cp "${SWIFT_OUT}"/*.h "${HEADERS_DIR}/"
fi

cat > "${HEADERS_DIR}/module.modulemap" <<'MODULEMAP'
framework module ClawIosSDK {
  umbrella header "claw_ios_sdk.h"
  export *
  module * { export * }
}
MODULEMAP

# ── 5. Build XCFramework ───────────────────────────────────────────────────

XCFW="${BUILD_DIR}/ClawIosSDK.xcframework"
rm -rf "${XCFW}"

echo "→ Creating ${XCFW}"
xcodebuild -create-xcframework \
  -library "${DEVICE_LIB}"  -headers "${HEADERS_DIR}" \
  -library "${SIM_FAT}"     -headers "${HEADERS_DIR}" \
  -output "${XCFW}"

echo ""
echo "✓ Done!"
echo ""
echo "  XCFramework : ${XCFW}"
echo "  Swift files : ${SWIFT_OUT}/*.swift"
echo ""
echo "Next steps in Xcode:"
echo "  1. Drag ClawIosSDK.xcframework into your project (Frameworks, Libraries)"
echo "  2. Add the generated .swift files in ${SWIFT_OUT}/ to your target"
echo "  3. Set ANTHROPIC_API_KEY in your app or pass it to ClawIosConfig"
