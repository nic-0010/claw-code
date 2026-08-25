// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ClawApp",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "ClawSDKWrapper", targets: ["ClawSDKWrapper"]),
    ],
    targets: [
        // C/FFI static library built by build-ios.sh.
        // The xcframework's internal module is named ClawIosSDKFFI (see uniffi.toml).
        .binaryTarget(
            name: "ClawIosSDKFFI",
            path: "../rust/build/ClawIosSDK.xcframework"
        ),
        // Generated Swift bindings (produced by uniffi-bindgen, copied by build-ios.sh).
        // This exposes the ClawIosSDK module that ClawSession.swift imports.
        .target(
            name: "ClawIosSDK",
            dependencies: ["ClawIosSDKFFI"],
            path: "Sources/ClawIosSDK"
        ),
        // High-level async/await wrapper used by the SwiftUI app.
        .target(
            name: "ClawSDKWrapper",
            dependencies: ["ClawIosSDK"],
            path: "Sources/ClawSDKWrapper"
        ),
    ]
)
