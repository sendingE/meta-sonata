import Foundation

enum Backend {
    static func inspect(_ url: URL, artworkDirectory: URL) async throws -> AudioDetail {
        let payload = try await run([
            "inspect",
            url.path,
            "--artwork-dir",
            artworkDirectory.path,
        ])
        return try payload.inspectedDetail()
    }

    static func enrich(_ url: URL, outputDirectory: URL) async throws -> BackendPayload {
        try await run([
            "enrich",
            url.path,
            "--output-dir",
            outputDirectory.path,
        ])
    }

    static func revert(
        _ output: URL,
        original: URL,
        field: EditableMetadataField,
        artworkDirectory: URL
    ) async throws -> BackendPayload {
        try await run([
            "revert-field",
            output.path,
            "--original",
            original.path,
            "--field",
            field.rawValue,
            "--artwork-dir",
            artworkDirectory.path,
        ])
    }

    private static func run(_ arguments: [String]) async throws -> BackendPayload {
        try await Task.detached(priority: .userInitiated) {
            guard
                let resources = Bundle.main.resourceURL,
                let executable = executable(in: resources)
            else {
                throw AppError.backendMissing
            }

            let process = Process()
            let stdout = Pipe()
            let stderr = Pipe()
            process.executableURL = executable
            process.arguments = arguments
            process.standardOutput = stdout
            process.standardError = stderr

            try process.run()
            process.waitUntilExit()

            let outputData = stdout.fileHandleForReading.readDataToEndOfFile()
            let errorData = stderr.fileHandleForReading.readDataToEndOfFile()
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase

            guard let payload = try? decoder.decode(BackendPayload.self, from: outputData) else {
                let message = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
                throw AppError.backendFailed(
                    code: "invalid_backend_response",
                    arguments: [:],
                    detail: message?.isEmpty == false ? message : nil
                )
            }
            if !payload.ok {
                throw AppError.backendFailed(
                    code: payload.errorCode,
                    arguments: payload.errorArguments ?? [:],
                    detail: payload.error
                )
            }
            if process.terminationStatus != 0 {
                throw AppError.backendFailed(
                    code: payload.errorCode,
                    arguments: payload.errorArguments ?? [:],
                    detail: payload.error
                )
            }
            return payload
        }.value
    }

    static func executable(in resources: URL) -> URL? {
        let bundled = resources
            .appendingPathComponent("AppBackend", isDirectory: true)
            .appendingPathComponent("meta-sonata-mac", isDirectory: false)
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            return bundled
        }
        return nil
    }
}
