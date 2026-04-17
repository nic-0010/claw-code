// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ClawApp",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "ClawSDKWrapper", targets: ["ClawSDKWrapper"]),
    ],
    targets: [
        // The generated Rust static library (built via build-ios.sh).
        // Point this to the XCFramework once built on a Mac.
        .binaryTarget(
            name: "ClawIosSDK",
            path: "../rust/build/ClawIosSDK.xcframework"
        ),
        // Swift wrapper that re-exports the UniFFI bindings with a
        // cleaner async/await API.
        .target(
            name: "ClawSDKWrapper",
            dependencies: ["ClawIosSDK"],
            path: "Sources/ClawSDKWrapper"
        ),
    ]
)
