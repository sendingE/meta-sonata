import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var mode: AppMode = .enrich
    @Published var input: AudioDetail?
    @Published var output: AudioDetail?
    @Published var match: TrackMatch?
    @Published var warnings: [String] = []
    @Published var isInspecting = false
    @Published var isEnriching = false
    @Published var revertingField: EditableMetadataField?
    @Published var errorMessage: String?
    @Published var libraryRoot: URL?
    @Published var libraryURL: URL?
    @Published var isStartingLibrary = false

    private var libraryServer: LibraryServer?
    private var libraryStartToken: UUID?
    private let localization: LocalizationModel

    private let supportedExtensions = [
        "flac", "mp3", "m4a", "mp4", "aac", "ogg", "opus", "wav", "wave", "aiff", "aif", "ape",
    ]

    init(localization: LocalizationModel) {
        self.localization = localization
    }

    func receive(_ urls: [URL]) -> Bool {
        guard let url = urls.first, url.isFileURL else { return false }
        guard supportedExtensions.contains(url.pathExtension.lowercased()) else {
            errorMessage = localization.message(for: AppError.unsupportedFile)
            return false
        }
        Task { await inspect(url) }
        return true
    }

    func inspect(_ url: URL) async {
        isInspecting = true
        errorMessage = nil
        output = nil
        match = nil
        warnings = []
        do {
            let preview = try makeCacheDirectory(group: "Previews")
            input = try await Backend.inspect(url, artworkDirectory: preview)
        } catch {
            input = nil
            present(error)
        }
        isInspecting = false
    }

    func enrich() async {
        guard let input else { return }
        isEnriching = true
        errorMessage = nil
        output = nil
        warnings = []
        do {
            let directory = try makeCacheDirectory(group: "Outputs")
            let payload = try await Backend.enrich(input.fileURL, outputDirectory: directory)
            guard let completed = payload.output else {
                throw AppError.invalidBackendResponse
            }
            output = completed
            match = payload.match
            warnings = payload.warnings ?? []
        } catch {
            present(error)
        }
        isEnriching = false
    }

    func revert(_ field: EditableMetadataField) async {
        guard let input, let output else { return }
        revertingField = field
        errorMessage = nil
        do {
            let preview = output.fileURL.deletingLastPathComponent()
                .appendingPathComponent(".preview", isDirectory: true)
            let payload = try await Backend.revert(
                output.fileURL,
                original: input.fileURL,
                field: field,
                artworkDirectory: preview
            )
            guard let restored = payload.output else {
                throw AppError.invalidBackendResponse
            }
            self.output = restored
        } catch {
            present(error)
        }
        revertingField = nil
    }

    func reset() {
        input = nil
        output = nil
        match = nil
        warnings = []
        errorMessage = nil
        revertingField = nil
    }

    func openLibrary(_ root: URL, locale: String) async {
        let token = UUID()
        libraryStartToken = token
        libraryServer?.stop()
        libraryServer = nil
        libraryRoot = root
        libraryURL = nil
        isStartingLibrary = true
        errorMessage = nil

        do {
            let launch = try await LibraryServer.start(root: root)
            guard libraryStartToken == token else {
                launch.server.stop()
                return
            }
            var components = URLComponents(url: launch.url, resolvingAgainstBaseURL: false)
            components?.queryItems = [
                URLQueryItem(name: "embedded", value: "1"),
                URLQueryItem(name: "lang", value: locale),
            ]
            libraryServer = launch.server
            libraryURL = components?.url ?? launch.url
        } catch {
            guard libraryStartToken == token else { return }
            libraryRoot = nil
            present(error)
        }
        if libraryStartToken == token {
            isStartingLibrary = false
        }
    }

    func stopLibrary() {
        libraryStartToken = nil
        libraryServer?.stop()
        libraryServer = nil
        libraryURL = nil
        isStartingLibrary = false
    }

    func updateLibraryLocale(_ locale: String) {
        guard let libraryURL, var components = URLComponents(url: libraryURL, resolvingAgainstBaseURL: false) else {
            return
        }
        components.queryItems = [
            URLQueryItem(name: "embedded", value: "1"),
            URLQueryItem(name: "lang", value: locale),
        ]
        self.libraryURL = components.url
    }

    func present(_ error: Error) {
        errorMessage = localization.message(for: error)
    }

    func changed(_ field: EditableMetadataField) -> Bool {
        guard let input, let output else { return false }
        if field == .lyrics {
            return (input.lyrics.text ?? "") != (output.lyrics.text ?? "")
        }
        return normalized(field.value(in: input.metadata)) != normalized(field.value(in: output.metadata))
    }

    private func normalized(_ value: String?) -> String {
        (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func makeCacheDirectory(group: String) throws -> URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("com.sendinge.meta-sonata", isDirectory: true)
            .appendingPathComponent(group, isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base
    }
}
