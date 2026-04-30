#!/usr/bin/env bash
# setup_xcode.sh — Build XCFramework + open Xcode project.
#
# Usage:
#   cd claw-code/
#   bash ios-app/setup_xcode.sh           # debug build
#   bash ios-app/setup_xcode.sh --release # release build

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUST_DIR="${REPO_ROOT}/rust"
IOS_APP_DIR="${SCRIPT_DIR}"

PROFILE_FLAG=""
for arg in "$@"; do
  case "$arg" in --release) PROFILE_FLAG="--release" ;; esac
done

echo "=== Claw iOS — full setup ==="
echo "  Repo: ${REPO_ROOT}"
echo ""

# ── 1. Platform check ─────────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
  echo "✗ macOS required."
  exit 1
fi

if ! command -v xcodebuild &>/dev/null; then
  echo "✗ Xcode not found."
  echo "  sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer"
  exit 1
fi

echo "✓ Xcode: $(xcodebuild -version | head -1)"

# ── 2. Rust + iOS targets ─────────────────────────────────────────────────────

if ! command -v rustup &>/dev/null; then
  echo "✗ Rust not found. Install with:"
  echo "    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  echo "  Then: source ~/.cargo/env  and re-run."
  exit 1
fi

echo "✓ Rust: $(rustc --version)"

TARGETS=(aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios)
INSTALLED="$(rustup target list --installed 2>/dev/null)" || INSTALLED=""
NEED_ADD=()
for t in "${TARGETS[@]}"; do
  echo "${INSTALLED}" | grep -q "^${t}" || NEED_ADD+=("$t")
done
if [[ ${#NEED_ADD[@]} -gt 0 ]]; then
  echo "→ Adding Rust iOS targets: ${NEED_ADD[*]}"
  rustup target add "${NEED_ADD[@]}"
fi
echo "✓ Rust iOS targets installed"

# ── 3. Build XCFramework ──────────────────────────────────────────────────────

echo ""
echo "─── Building ClawIosSDK.xcframework ─────────────────────────────────────"
cd "${RUST_DIR}"
bash scripts/build-ios.sh ${PROFILE_FLAG}

# ── 4. Open Xcode project ─────────────────────────────────────────────────────

echo ""
echo "✓ XCFramework built!"
echo ""

XCPROJ="${IOS_APP_DIR}/ClawApp.xcodeproj"
if [[ -d "${XCPROJ}" ]]; then
  echo "→ Opening ${XCPROJ} in Xcode..."
  open "${XCPROJ}"
else
  echo "→ Opening Xcode (create project manually — see instructions below)..."
  open /Applications/Xcode.app
fi

echo ""
echo "=== Done! ==="
echo ""
echo "If Xcode opens without a project, create it once:"
echo "  1. File → New → Project → iOS → App → Next"
echo "  2. Product Name: ClawApp  |  Interface: SwiftUI  |  Language: Swift"
echo "  3. Save inside:  ${IOS_APP_DIR}/"
echo "  4. File → Add Package Dependencies → Add Local → select ${IOS_APP_DIR}/"
echo "     then add product: ClawSDKWrapper"
echo "  5. Delete the auto-generated ContentView.swift and ClawApp.swift"
echo "  6. Add existing files from ${IOS_APP_DIR}/Sources/ClawApp/"
echo ""
echo "Then: select your iPhone → set Team → ▶ Run"
