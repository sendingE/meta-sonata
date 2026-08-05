import Foundation

private struct LibraryServerResponse: Decodable {
    let ok: Bool
    let url: String?
    let error: String?
    let errorCode: String?
    let errorArguments: [String: String]?
}

struct LibraryServerLaunch: Sendable {
    let server: LibraryServer
    let url: URL
}

final class LibraryServer: @unchecked Sendable {
    private let process: Process
    private let input: Pipe

    private init(process: Process, input: Pipe) {
        self.process = process
        self.input = input
    }

    static func start(root: URL) async throws -> LibraryServerLaunch {
        try await Task.detached(priority: .userInitiated) {
            guard
                let resources = Bundle.main.resourceURL,
                let executable = Backend.executable(in: resources)
            else {
                throw AppError.backendMissing
            }

            let process = Process()
            let input = Pipe()
            let stdout = Pipe()
            let stderr = Pipe()
            process.executableURL = executable
            process.arguments = ["library-server", root.path]
            process.standardInput = input
            process.standardOutput = stdout
            process.standardError = stderr

            try process.run()
            let responseData = readFirstLine(from: stdout.fileHandleForReading)
            let response = try? JSONDecoder().decode(LibraryServerResponse.self, from: responseData)

            guard let response else {
                if process.isRunning { process.terminate() }
                throw AppError.libraryStartFailed
            }
            guard response.ok, let value = response.url, let url = URL(string: value) else {
                if process.isRunning { process.terminate() }
                throw AppError.backendFailed(
                    code: response.errorCode ?? "library_start_failed",
                    arguments: response.errorArguments ?? [:],
                    detail: response.error
                )
            }

            let server = LibraryServer(process: process, input: input)
            return LibraryServerLaunch(server: server, url: url)
        }.value
    }

    func stop() {
        try? input.fileHandleForWriting.close()
    }

    deinit {
        stop()
    }

    private static func readFirstLine(from handle: FileHandle) -> Data {
        var result = Data()
        while true {
            let chunk = handle.availableData
            guard !chunk.isEmpty else { break }
            if let newline = chunk.firstIndex(of: 0x0A) {
                result.append(chunk.prefix(upTo: newline))
                break
            }
            result.append(chunk)
        }
        return result
    }
}
