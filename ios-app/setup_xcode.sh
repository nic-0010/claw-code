#!/usr/bin/env bash
# setup_xcode.sh — One-shot: build XCFramework + generate Xcode project.
#
# Run this from the ios-app/ directory (or anywhere — it auto-locates the repo):
#   cd ios-app/
#   bash setup_xcode.sh           # debug build
#   bash setup_xcode.sh --release # release/App Store build
#
# What it does:
#   1. Checks prerequisites (Xcode, rustup targets, xcodegen)
#   2. Builds ClawIosSDK.xcframework via rust/scripts/build-ios.sh
#   3. Runs xcodegen to create/refresh ClawApp.xcodeproj
#   4. Opens ClawApp.xcodeproj in Xcode

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
  echo "✗ Xcode not found. Install it from the App Store, then run:"
  echo "    sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer"
  exit 1
fi

echo "✓ Xcode: $(xcodebuild -version | head -1)"

# ── 2. Rust + rustup ─────────────────────────────────────────────────────────

if ! command -v rustup &>/dev/null; then
  echo "✗ Rust not found. Install it with:"
  echo "    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  echo "  Then run:  source ~/.cargo/env"
  echo "  Then re-run this script."
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
  echo "→ Adding missing Rust iOS targets: ${NEED_ADD[*]}"
  rustup target add "${NEED_ADD[@]}"
fi

echo "✓ Rust iOS targets installed"

# ── 3. xcodegen ───────────────────────────────────────────────────────────────

if ! command -v xcodegen &>/dev/null; then
  echo "→ xcodegen not found — installing via Homebrew..."
  if ! command -v brew &>/dev/null; then
    echo "✗ Homebrew not found. Install it from https://brew.sh then re-run."
    exit 1
  fi
  brew install xcodegen
fi

echo "✓ xcodegen: $(xcodegen --version 2>/dev/null | head -1)"

# ── 4. Build XCFramework ──────────────────────────────────────────────────────

echo ""
echo "─── Building XCFramework ────────────────────────────────────────────────"
cd "${RUST_DIR}"
bash scripts/build-ios.sh ${PROFILE_FLAG}

# ── 5. Generate Xcode project ─────────────────────────────────────────────────

echo ""
echo "─── Generating ClawApp.xcodeproj ────────────────────────────────────────"
cd "${IOS_APP_DIR}"
xcodegen generate --spec project.yml

echo ""
echo "✓ ClawApp.xcodeproj ready!"

# ── 6. Open in Xcode ─────────────────────────────────────────────────────────

echo "→ Opening Xcode..."
open "${IOS_APP_DIR}/ClawApp.xcodeproj"

echo ""
echo "=== Done! ==="
echo ""
echo "In Xcode:"
echo "  1. Select your iPhone as the run destination"
echo "  2. Set your Team under Signing & Capabilities"
echo "  3. Hit ▶ Run"
echo ""
echo "API keys — edit ContentView.swift or set env vars before building:"
echo "  ANTHROPIC_API_KEY   — required"
echo "  TAVILY_API_KEY      — for web search (optional)"
echo "  FIRECRAWL_API_KEY   — for JS-rendered pages (optional)"
