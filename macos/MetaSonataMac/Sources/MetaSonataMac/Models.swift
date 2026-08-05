import Foundation

enum AppMode: String, CaseIterable, Identifiable {
    case enrich
    case library

    var id: String { rawValue }

    @MainActor
    func label(using localization: LocalizationModel) -> String {
        switch self {
        case .enrich: localization.text("mode.enrich")
        case .library: localization.text("mode.library")
        }
    }
}

struct FileInfo: Decodable, Sendable {
    let name: String
    let suffix: String
    let size: Int64
    let modified: String?
}

struct AudioInfo: Decodable, Sendable {
    let length: Double?
    let bitrate: Double?
    let sampleRate: Double?
    let channels: Int?
    let bitsPerSample: Int?
}

struct MetadataSummary: Decodable, Sendable {
    let title: String
    let artist: String?
    let album: String?
    let albumArtist: String?
    let date: String?
    let genre: String?
    let trackNumber: String?
    let discNumber: String?
    let source: String?
}

struct LyricsSummary: Decodable, Sendable {
    let hasLyrics: Bool
    let hasSynced: Bool
    let length: Int
    let preview: String
    let text: String?
}

enum EditableMetadataField: String, CaseIterable, Identifiable, Sendable {
    case title
    case artist
    case album
    case albumArtist = "album_artist"
    case date
    case genre
    case trackNumber = "track_number"
    case discNumber = "disc_number"
    case lyrics

    var id: String { rawValue }

    @MainActor
    func label(using localization: LocalizationModel) -> String {
        switch self {
        case .title: localization.text("field.title")
        case .artist: localization.text("field.artist")
        case .album: localization.text("field.album")
        case .albumArtist: localization.text("field.album_artist")
        case .date: localization.text("field.date")
        case .genre: localization.text("field.genre")
        case .trackNumber: localization.text("field.track")
        case .discNumber: localization.text("field.disc")
        case .lyrics: localization.text("field.lyrics")
        }
    }

    func value(in metadata: MetadataSummary) -> String? {
        switch self {
        case .title: metadata.title
        case .artist: metadata.artist
        case .album: metadata.album
        case .albumArtist: metadata.albumArtist
        case .date: metadata.date
        case .genre: metadata.genre
        case .trackNumber: metadata.trackNumber
        case .discNumber: metadata.discNumber
        case .lyrics: nil
        }
    }
}

struct AudioDetail: Decodable, Sendable {
    let path: String
    let file: FileInfo
    let format: String?
    let audio: AudioInfo
    let metadata: MetadataSummary
    let lyrics: LyricsSummary
    let hasArtwork: Bool
    let artworkPath: String?
    let writable: Bool
}

struct TrackMatch: Decodable, Sendable {
    let provider: String
    let sourceId: String
    let score: Double
}

struct BackendPayload: Decodable, Sendable {
    let ok: Bool
    let error: String?
    let errorCode: String?
    let errorArguments: [String: String]?

    // `inspect` returns an AudioDetail at the top level.
    let path: String?
    let file: FileInfo?
    let format: String?
    let audio: AudioInfo?
    let metadata: MetadataSummary?
    let lyrics: LyricsSummary?
    let hasArtwork: Bool?
    let artworkPath: String?
    let writable: Bool?

    // `enrich` wraps the completed file under output.
    let output: AudioDetail?
    let match: TrackMatch?
    let changed: Bool?
    let warnings: [String]?

    func inspectedDetail() throws -> AudioDetail {
        guard
            let path,
            let file,
            let audio,
            let metadata,
            let lyrics,
            let hasArtwork,
            let writable
        else {
            throw AppError.invalidBackendResponse
        }
        return AudioDetail(
            path: path,
            file: file,
            format: format,
            audio: audio,
            metadata: metadata,
            lyrics: lyrics,
            hasArtwork: hasArtwork,
            artworkPath: artworkPath,
            writable: writable
        )
    }
}

enum AppError: Error, Sendable {
    case backendMissing
    case backendFailed(code: String?, arguments: [String: String], detail: String?)
    case invalidBackendResponse
    case unsupportedFile
    case libraryStartFailed
}

extension AudioDetail {
    var fileURL: URL { URL(fileURLWithPath: path) }

    var formatLabel: String {
        file.suffix.replacingOccurrences(of: ".", with: "").uppercased()
    }

    var durationLabel: String {
        guard let length = audio.length else { return "—" }
        let seconds = Int(length.rounded())
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    var sizeLabel: String {
        ByteCountFormatter.string(fromByteCount: file.size, countStyle: .file)
    }
}
