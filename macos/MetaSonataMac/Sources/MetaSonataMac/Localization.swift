import Combine
import Foundation

enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case english = "en"
    case simplifiedChinese = "zh-Hans"
    case traditionalChinese = "zh-Hant"
    case japanese = "ja"
    case korean = "ko"
    case french = "fr"
    case german = "de"
    case spanish = "es"
    case brazilianPortuguese = "pt-BR"

    var id: String { rawValue }

    @MainActor
    func displayName(using localization: LocalizationModel) -> String {
        switch self {
        case .system: localization.text("language.system")
        case .english: "English"
        case .simplifiedChinese: "简体中文"
        case .traditionalChinese: "繁體中文"
        case .japanese: "日本語"
        case .korean: "한국어"
        case .french: "Français"
        case .german: "Deutsch"
        case .spanish: "Español"
        case .brazilianPortuguese: "Português (Brasil)"
        }
    }
}

@MainActor
final class LocalizationModel: ObservableObject {
    private static let preferenceKey = "MetaSonataLanguage"

    @Published var selection: AppLanguage {
        didSet {
            UserDefaults.standard.set(selection.rawValue, forKey: Self.preferenceKey)
            reload()
        }
    }

    @Published private(set) var localeCode: String
    private var messages: [String: String]
    private let fallbackMessages: [String: String]

    init() {
        let saved = UserDefaults.standard.string(forKey: Self.preferenceKey)
        let selected = saved.flatMap(AppLanguage.init(rawValue:)) ?? .system
        let resolved = Self.resolve(selected)
        let fallback = Self.loadMessages(for: "en")
        selection = selected
        localeCode = resolved
        fallbackMessages = fallback
        messages = fallback.merging(Self.loadMessages(for: resolved)) { _, translated in translated }
    }

    var locale: Locale { Locale(identifier: localeCode) }

    func text(_ key: String, _ values: [String: String] = [:]) -> String {
        var result = messages[key] ?? fallbackMessages[key] ?? key
        for (name, value) in values {
            result = result.replacingOccurrences(of: "{\(name)}", with: value)
        }
        return result
    }

    func message(for error: Error) -> String {
        guard let appError = error as? AppError else {
            return error.localizedDescription
        }
        switch appError {
        case .backendMissing:
            return text("error.backend_missing")
        case .invalidBackendResponse:
            return text("error.invalid_response")
        case .unsupportedFile:
            return text("error.unsupported_file")
        case .libraryStartFailed:
            return text("error.library_start_failed")
        case .backendFailed(let code, let arguments, _):
            let key: String
            switch code {
            case "file_not_found": key = "error.file_not_found"
            case "unsupported_file": key = "error.unsupported_file"
            case "unsupported_write_format": key = "error.unsupported_write_format"
            case "unsupported_revert_field": key = "error.revert_unsupported"
            case "write_failed": key = "error.write_failed"
            case "library_start_failed": key = "error.library_start_failed"
            case "invalid_backend_response": key = "error.backend_invalid"
            default: key = "error.processing_failed"
            }
            return text(key, arguments)
        }
    }

    private func reload() {
        let resolved = Self.resolve(selection)
        localeCode = resolved
        messages = fallbackMessages.merging(Self.loadMessages(for: resolved)) { _, translated in translated }
    }

    private static func resolve(_ selection: AppLanguage) -> String {
        guard selection == .system else { return selection.rawValue }
        return canonicalLocale(Locale.preferredLanguages.first ?? Locale.current.identifier)
    }

    private static func canonicalLocale(_ identifier: String) -> String {
        let value = identifier.replacingOccurrences(of: "_", with: "-").lowercased()
        if value.hasPrefix("zh") {
            if value.contains("hant") || value.contains("-tw") || value.contains("-hk") || value.contains("-mo") {
                return "zh-Hant"
            }
            return "zh-Hans"
        }
        let supported: [(prefix: String, code: String)] = [
            ("pt", "pt-BR"), ("ja", "ja"), ("ko", "ko"), ("fr", "fr"),
            ("de", "de"), ("es", "es"), ("en", "en"),
        ]
        return supported.first(where: { value == $0.prefix || value.hasPrefix("\($0.prefix)-") })?.code ?? "en"
    }

    private static func loadMessages(for code: String) -> [String: String] {
        let fileName = "\(code).json"
        let bundled = Bundle.main.resourceURL?
            .appendingPathComponent("Localizations", isDirectory: true)
            .appendingPathComponent(fileName)
        if let bundled, let messages = decodeMessages(at: bundled) {
            return messages
        }

        let development = URL(
            fileURLWithPath: FileManager.default.currentDirectoryPath,
            isDirectory: true
        )
            .appendingPathComponent("src/meta_sonata/assets/locales", isDirectory: true)
            .appendingPathComponent(fileName)
        return decodeMessages(at: development) ?? [:]
    }

    private static func decodeMessages(at url: URL) -> [String: String]? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode([String: String].self, from: data)
    }
}
