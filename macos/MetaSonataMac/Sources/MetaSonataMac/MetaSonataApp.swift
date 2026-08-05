import SwiftUI

@main
@MainActor
struct MetaSonataApp: App {
    @StateObject private var localization: LocalizationModel
    @StateObject private var model: AppModel

    init() {
        let localization = LocalizationModel()
        _localization = StateObject(wrappedValue: localization)
        _model = StateObject(wrappedValue: AppModel(localization: localization))
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .environmentObject(localization)
                .environment(\.locale, localization.locale)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 980, height: 680)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}
