import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var localization: LocalizationModel
    @State private var inputTargeted = false
    @State private var lyricsPresentation: LyricsPresentation?
    @State private var showingFileImporter = false
    @State private var showingFolderImporter = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if model.mode == .enrich {
                enrichmentWorkspace
            } else {
                libraryWorkspace
            }
        }
        .frame(minWidth: 920, idealWidth: 980, minHeight: 680, idealHeight: 760)
        .background(Color(nsColor: .windowBackgroundColor))
        .alert("Meta Sonata", isPresented: errorPresented) {
            Button(localization.text("action.dismiss"), role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
        }
        .sheet(item: $lyricsPresentation) { presentation in
            LyricsSheet(presentation: presentation)
        }
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: [.audio],
            allowsMultipleSelection: false
        ) { result in
            do {
                _ = model.receive(try result.get())
            } catch {
                model.present(error)
            }
        }
        .fileImporter(
            isPresented: $showingFolderImporter,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            do {
                guard let root = try result.get().first else { return }
                Task { await model.openLibrary(root, locale: localization.localeCode) }
            } catch {
                model.present(error)
            }
        }
        .onDisappear {
            model.stopLibrary()
        }
        .onChange(of: localization.localeCode) { locale in
            model.updateLibraryLocale(locale)
        }
    }

    private var header: some View {
        HStack(spacing: 16) {
            HStack(spacing: 12) {
                LogoMark()
                    .frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Meta Sonata")
                        .font(.headline)
                    Text(localization.text(model.mode == .enrich ? "app.subtitle.enrich" : "app.subtitle.library"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Picker(localization.text("mode.selector"), selection: $model.mode) {
                ForEach(AppMode.allCases) { mode in
                    Text(mode.label(using: localization)).tag(mode)
                }
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            .frame(width: 220)

            HStack(spacing: 12) {
                if model.mode == .enrich, model.input != nil {
                    Button(localization.text("action.restart")) { model.reset() }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                } else if model.mode == .library, model.libraryRoot != nil {
                    Button(localization.text("action.change_folder")) { showingFolderImporter = true }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                }
                languageMenu
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.horizontal, 24)
        .frame(height: 64)
    }

    private var languageMenu: some View {
        Menu {
            ForEach(AppLanguage.allCases) { language in
                Button {
                    localization.selection = language
                } label: {
                    if localization.selection == language {
                        Label(language.displayName(using: localization), systemImage: "checkmark")
                    } else {
                        Text(language.displayName(using: localization))
                    }
                }
            }
        } label: {
            Image(systemName: "globe")
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(localization.text("language.menu"))
        .accessibilityLabel(localization.text("language.menu"))
    }

    private var enrichmentWorkspace: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 18) {
                filePanel(
                    title: localization.text("panel.input"),
                    detail: model.input,
                    emptyTitle: localization.text(model.isInspecting ? "status.reading" : "drop.music_file"),
                    emptyHint: localization.text("hint.one_file"),
                    accent: .indigo,
                    isDropTarget: inputTargeted,
                    isOutput: false
                )
                .dropDestination(for: URL.self) { urls, _ in
                    model.receive(urls)
                } isTargeted: { targeted in
                    inputTargeted = targeted
                }

                actionColumn

                filePanel(
                    title: localization.text("panel.output"),
                    detail: model.output,
                    emptyTitle: localization.text(model.isEnriching ? "status.enriching" : "status.waiting"),
                    emptyHint: localization.text("hint.drag_from_output"),
                    accent: .green,
                    isDropTarget: false,
                    isOutput: true
                )
            }
            .padding(24)
            footer
        }
    }

    @ViewBuilder
    private var libraryWorkspace: some View {
        VStack(spacing: 0) {
            if let root = model.libraryRoot {
                HStack(spacing: 9) {
                    Image(systemName: "folder.fill")
                        .foregroundStyle(.secondary)
                    Text(root.path)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                    Spacer()
                    Label(localization.text("status.read_only"), systemImage: "lock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 18)
                .frame(height: 42)
                .background(.bar)
                Divider()
            }

            if let url = model.libraryURL {
                LibraryWebView(url: url)
            } else if model.isStartingLibrary {
                VStack(spacing: 12) {
                    ProgressView()
                        .controlSize(.large)
                    Text(localization.text("library.opening"))
                        .font(.headline)
                    Text(localization.text("library.opening_hint"))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                LibraryEmptyState {
                    showingFolderImporter = true
                }
            }

            HStack {
                Label(localization.text("library.readonly_browse"), systemImage: "lock.shield")
                Spacer()
                Text(localization.text("library.local_only"))
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 24)
            .frame(height: 38)
            .background(.bar)
        }
    }

    private var actionColumn: some View {
        VStack(spacing: 14) {
            Image(systemName: model.output == nil ? "arrow.right" : "checkmark")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(model.output == nil ? Color.secondary : Color.green)
                .frame(width: 38, height: 38)
                .background(.quaternary, in: Circle())
            Button {
                Task { await model.enrich() }
            } label: {
                if model.isEnriching {
                    ProgressView()
                        .controlSize(.small)
                        .frame(width: 86)
                } else {
                    Text(localization.text("action.enrich"))
                        .frame(width: 86)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(model.input == nil || model.input?.writable == false || model.isEnriching)
        }
        .frame(width: 112)
    }

    @ViewBuilder
    private func filePanel(
        title: String,
        detail: AudioDetail?,
        emptyTitle: String,
        emptyHint: String,
        accent: Color,
        isDropTarget: Bool,
        isOutput: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                if isOutput, detail != nil {
                    Label(localization.text("file.drag_out"), systemImage: "hand.draw")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 18)
            .frame(height: 52)
            Divider()
            Group {
                if let detail {
                    populatedPanel(detail, accent: accent, isOutput: isOutput)
                } else {
                    emptyPanel(
                        title: emptyTitle,
                        hint: emptyHint,
                        accent: accent,
                        loading: model.isInspecting || model.isEnriching,
                        isOutput: isOutput
                    )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(isDropTarget ? accent : Color(nsColor: .separatorColor), lineWidth: isDropTarget ? 2 : 1)
        }
        .shadow(color: .black.opacity(0.04), radius: 12, y: 4)
        .scaleEffect(isDropTarget ? 1.01 : 1)
        .animation(.easeOut(duration: 0.15), value: isDropTarget)
    }

    private func emptyPanel(
        title: String,
        hint: String,
        accent: Color,
        loading: Bool,
        isOutput: Bool
    ) -> some View {
        VStack(spacing: 0) {
            FileStageHeader(
                trailingText: localization.text(isOutput ? "hint.output_drag" : "hint.drop_or_choose")
            )
            EmptyFileStage(
                title: title,
                hint: hint,
                accent: accent,
                loading: loading,
                isOutput: isOutput,
                isDropTarget: inputTargeted && !isOutput
            )
            .contentShape(Rectangle())
            .onTapGesture {
                if !isOutput && !loading {
                    showingFileImporter = true
                }
            }
            Divider()
            MetadataSectionHeader()
            Divider()
            VStack(spacing: 10) {
                Image(systemName: "list.bullet.rectangle")
                    .font(.system(size: 24))
                Text(localization.text(isOutput ? "metadata.output_pending" : "metadata.input_pending"))
                    .font(.callout)
            }
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func populatedPanel(_ detail: AudioDetail, accent: Color, isOutput: Bool) -> some View {
        let titleChanged = isOutput && model.changed(.title)
        let artistChanged = isOutput && model.changed(.artist)
        return VStack(spacing: 0) {
            FileStageHeader(
                trailingText: localization.text(isOutput ? "file.output_save" : "file.input_readonly")
            )
            FileDesktopItem(detail: detail, accent: accent, isOutput: isOutput)
                .frame(height: 148)
            Divider()
            MetadataSectionHeader()
            Divider()
            HStack(spacing: 14) {
                artwork(detail, accent: accent)
                VStack(alignment: .leading, spacing: 5) {
                    Text(detail.metadata.title)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(titleChanged ? Color.red : Color.primary)
                        .lineLimit(2)
                    Text(detail.metadata.artist ?? localization.text("artist.unknown"))
                        .foregroundStyle(artistChanged ? Color.red : Color.secondary)
                        .lineLimit(1)
                    HStack(spacing: 6) {
                        badge(detail.formatLabel)
                        badge(detail.durationLabel)
                        if detail.hasArtwork { badge(localization.text("badge.cover")) }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(18)
            Divider()
            ScrollView {
                MetadataRows(
                    detail: detail,
                    original: isOutput ? model.input : nil,
                    revertingField: model.revertingField
                ) { field in
                    Task { await model.revert(field) }
                }
                    .padding(18)
            }
            Divider()
            LyricsAction(
                detail: detail,
                changed: isOutput && model.changed(.lyrics),
                isReverting: model.revertingField == .lyrics,
                accent: accent,
                onOpen: {
                    lyricsPresentation = LyricsPresentation(detail: detail)
                },
                onRevert: {
                    Task { await model.revert(.lyrics) }
                }
            )
        }
    }

    private func artwork(_ detail: AudioDetail, accent: Color) -> some View {
        Group {
            if let path = detail.artworkPath, let image = NSImage(contentsOfFile: path) {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                ZStack {
                    accent.opacity(0.12)
                    Image(systemName: "music.note")
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(accent)
                }
            }
        }
        .frame(width: 64, height: 64)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func badge(_ value: String) -> some View {
        Text(value)
            .font(.caption2.weight(.medium))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(.quaternary, in: Capsule())
    }

    private var footer: some View {
        HStack {
            Label(localization.text("footer.original_safe"), systemImage: "lock.shield")
            Spacer()
            if let match = model.match {
                Text(localization.text("footer.match", [
                    "provider": match.provider,
                    "score": String(Int(match.score * 100)),
                ]))
            } else if !model.warnings.isEmpty {
                Text(localization.text("footer.partial"))
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 24)
        .frame(height: 44)
        .background(.bar)
    }

    private var errorPresented: Binding<Bool> {
        Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )
    }
}

private struct FileStageHeader: View {
    @EnvironmentObject private var localization: LocalizationModel
    let trailingText: String

    var body: some View {
        HStack(spacing: 8) {
            Label(localization.text("section.file"), systemImage: "doc")
                .font(.callout.weight(.semibold))
            Spacer()
            Text(trailingText)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 16)
        .frame(height: 38)
        .background(Color(nsColor: .underPageBackgroundColor).opacity(0.45))
    }
}

private struct MetadataSectionHeader: View {
    @EnvironmentObject private var localization: LocalizationModel

    var body: some View {
        HStack {
            Label(localization.text("section.metadata"), systemImage: "list.bullet.rectangle")
                .font(.callout.weight(.semibold))
            Spacer()
        }
        .padding(.horizontal, 16)
        .frame(height: 38)
        .background(Color(nsColor: .underPageBackgroundColor).opacity(0.45))
    }
}

private struct EmptyFileStage: View {
    let title: String
    let hint: String
    let accent: Color
    let loading: Bool
    let isOutput: Bool
    let isDropTarget: Bool

    var body: some View {
        VStack(spacing: 7) {
            if loading {
                ProgressView()
                    .controlSize(.large)
                    .frame(height: 48)
            } else {
                Image(systemName: isOutput ? "doc.badge.clock" : "arrow.down.doc")
                    .font(.system(size: 38, weight: .medium))
                    .foregroundStyle(accent)
                    .frame(height: 48)
            }
            Text(title)
                .font(.callout.weight(.semibold))
            Text(hint)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 148)
        .background((isDropTarget ? accent : Color.primary).opacity(isDropTarget ? 0.10 : 0.025))
        .overlay {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(
                    isDropTarget ? accent : Color.clear,
                    style: StrokeStyle(lineWidth: 2, dash: [7, 5])
                )
                .padding(8)
        }
    }
}

private struct FileDesktopItem: View {
    @EnvironmentObject private var localization: LocalizationModel
    let detail: AudioDetail
    let accent: Color
    let isOutput: Bool

    @State private var isHovered = false

    var body: some View {
        Group {
            if isOutput {
                item
                    .onDrag {
                        NSItemProvider(contentsOf: detail.fileURL)
                            ?? NSItemProvider(object: detail.fileURL as NSURL)
                    }
                    .help(localization.text("drag.save_help"))
            } else {
                item
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(accent.opacity(isOutput ? 0.035 : 0.02))
    }

    private var item: some View {
        VStack(spacing: 4) {
            ZStack(alignment: .bottomTrailing) {
                Image(nsImage: NSWorkspace.shared.icon(forFile: detail.fileURL.path))
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: 78, height: 78)
                    .shadow(color: .black.opacity(0.18), radius: 3, y: 2)

                if isOutput {
                    Image(systemName: "arrow.up.forward")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(width: 22, height: 22)
                        .background(accent, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 2))
                }
            }
            Text(detail.file.name)
                .font(.caption)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .truncationMode(.middle)
                .frame(maxWidth: 190)
                .padding(.horizontal, 5)
                .padding(.vertical, 2)
                .background(
                    isHovered && isOutput ? accent.opacity(0.18) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 4, style: .continuous)
                )
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 7)
        .contentShape(Rectangle())
        .scaleEffect(isHovered && isOutput ? 1.025 : 1)
        .animation(.easeOut(duration: 0.12), value: isHovered)
        .onHover { hovering in
            isHovered = hovering
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            localization.text(
                isOutput ? "accessibility.output_file" : "accessibility.input_file",
                ["name": detail.file.name]
            )
        )
    }
}

private struct MetadataRows: View {
    @EnvironmentObject private var localization: LocalizationModel
    let detail: AudioDetail
    let original: AudioDetail?
    let revertingField: EditableMetadataField?
    let onRevert: (EditableMetadataField) -> Void

    private var fields: [EditableMetadataField] {
        [.title, .artist, .album, .albumArtist, .date, .genre, .trackNumber, .discNumber]
    }

    private var technicalRows: [(String, String)] {
        [
            (localization.text("field.file"), detail.file.name),
            (localization.text("field.size"), detail.sizeLabel),
            (localization.text("field.sample_rate"), detail.audio.sampleRate.map { "\(Int($0)) Hz" } ?? "—"),
            (localization.text("field.source"), detail.metadata.source ?? "—"),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 10) {
                ForEach(fields) { field in
                    let value = field.value(in: detail.metadata) ?? "—"
                    let originalValue = original.flatMap { field.value(in: $0.metadata) } ?? ""
                    let changed = original != nil && normalized(value) != normalized(originalValue)
                    GridRow {
                        Text(field.label(using: localization))
                            .foregroundStyle(.secondary)
                            .frame(width: 74, alignment: .leading)
                        Text(value)
                            .foregroundStyle(changed ? Color.red : Color.primary)
                            .textSelection(.enabled)
                            .lineLimit(2)
                        if changed {
                            Button {
                                onRevert(field)
                            } label: {
                                if revertingField == field {
                                    ProgressView()
                                        .controlSize(.small)
                                } else {
                                    Image(systemName: "arrow.uturn.backward.circle")
                                }
                            }
                            .buttonStyle(.borderless)
                            .foregroundStyle(.red)
                            .help(localization.text("revert.field_help"))
                            .disabled(revertingField != nil)
                        } else {
                            Color.clear.frame(width: 18, height: 18)
                        }
                    }
                }
            }
            Divider()
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 10) {
                ForEach(Array(technicalRows.enumerated()), id: \.offset) { _, row in
                    GridRow {
                        Text(row.0)
                            .foregroundStyle(.secondary)
                            .frame(width: 74, alignment: .leading)
                        Text(row.1)
                            .textSelection(.enabled)
                            .lineLimit(2)
                        Color.clear.frame(width: 18, height: 18)
                    }
                }
            }
        }
        .font(.callout)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func normalized(_ value: String) -> String {
        value == "—" ? "" : value.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private struct LogoMark: View {
    var body: some View {
        Image(nsImage: NSApplication.shared.applicationIconImage)
            .resizable()
            .interpolation(.high)
            .scaledToFit()
    }
}

private struct LyricsAction: View {
    @EnvironmentObject private var localization: LocalizationModel
    let detail: AudioDetail
    let changed: Bool
    let isReverting: Bool
    let accent: Color
    let onOpen: () -> Void
    let onRevert: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Button(action: onOpen) {
                HStack(spacing: 10) {
                    Image(systemName: detail.lyrics.hasSynced ? "quote.bubble.fill" : "quote.bubble")
                        .font(.title3)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(localization.text(
                            detail.lyrics.hasLyrics
                                ? (detail.lyrics.hasSynced ? "lyrics.view_synced" : "lyrics.view")
                                : "lyrics.not_found"
                        ))
                            .font(.callout.weight(.semibold))
                        Text(
                            detail.lyrics.hasLyrics
                                ? localization.text("lyrics.expand", ["count": String(detail.lyrics.length)])
                                : localization.text("lyrics.none")
                        )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if detail.lyrics.hasLyrics {
                        Image(systemName: "chevron.right")
                            .font(.caption.weight(.semibold))
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!detail.lyrics.hasLyrics)

            if changed {
                Button(action: onRevert) {
                    if isReverting {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.uturn.backward.circle")
                    }
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.red)
                .help(localization.text("lyrics.revert_help"))
            }
        }
        .foregroundStyle(changed ? Color.red : (detail.lyrics.hasLyrics ? accent : Color.secondary))
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background((changed ? Color.red : accent).opacity(0.08))
    }
}

private struct LyricsPresentation: Identifiable {
    let id = UUID()
    let title: String
    let artist: String?
    let text: String
    let synced: Bool

    init(detail: AudioDetail) {
        title = detail.metadata.title
        artist = detail.metadata.artist
        text = detail.lyrics.text ?? detail.lyrics.preview
        synced = detail.lyrics.hasSynced
    }
}

private struct LyricsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var localization: LocalizationModel
    let presentation: LyricsPresentation

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(presentation.title)
                        .font(.title3.weight(.semibold))
                    Text("\(presentation.artist ?? localization.text("artist.unknown")) · \(localization.text(presentation.synced ? "lyrics.synced" : "lyrics.plain"))")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(localization.text("action.done")) { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
            .padding(20)
            Divider()
            ScrollView {
                Text(presentation.text)
                    .font(.system(.body, design: presentation.synced ? .monospaced : .default))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(22)
            }
        }
        .frame(minWidth: 560, minHeight: 480)
    }
}
