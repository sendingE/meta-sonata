import SwiftUI
import WebKit

struct LibraryWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsMagnification = true
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        guard webView.url?.absoluteString != url.absoluteString else { return }
        webView.load(URLRequest(url: url))
    }
}

struct LibraryEmptyState: View {
    @EnvironmentObject private var localization: LocalizationModel
    let onChoose: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color.accentColor.opacity(0.10))
                Image(systemName: "music.note.list")
                    .font(.system(size: 42, weight: .medium))
                    .foregroundStyle(Color.accentColor)
            }
            .frame(width: 86, height: 86)

            VStack(spacing: 6) {
                Text(localization.text("library.choose_title"))
                    .font(.title2.weight(.semibold))
                Text(localization.text("library.choose_hint"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Button(localization.text("library.choose_button"), action: onChoose)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }
}
