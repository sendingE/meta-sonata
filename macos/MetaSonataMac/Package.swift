// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "MetaSonataMac",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "MetaSonataMac", targets: ["MetaSonataMac"]),
    ],
    targets: [
        .executableTarget(
            name: "MetaSonataMac",
            path: "Sources/MetaSonataMac"
        ),
    ]
)
