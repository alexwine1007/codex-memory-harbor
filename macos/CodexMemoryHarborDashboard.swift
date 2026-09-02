import Cocoa
import WebKit

final class DashboardDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private var workspaceObservers: [NSObjectProtocol] = []
    private let port = 48765

    func applicationDidFinishLaunching(_ notification: Notification) {
        startServer()
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1180, height: 790)
        let width = min(1180, max(760, visible.width - 28))
        let height = min(790, max(620, visible.height - 28))
        let frame = NSRect(x: visible.midX - width / 2, y: visible.midY - height / 2, width: width, height: height)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Memory Harbor"
        window.minSize = NSSize(width: min(760, width), height: min(620, height))
        window.titlebarAppearsTransparent = true
        window.isOpaque = false
        window.backgroundColor = .clear
        webView = WKWebView(frame: NSRect(origin: .zero, size: frame.size))
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        window.contentView = webView
        installVolumeObservers()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        loadWhenReady(attempt: 0)
    }

    func applicationWillTerminate(_ notification: Notification) {
        let center = NSWorkspace.shared.notificationCenter
        workspaceObservers.forEach { center.removeObserver($0) }
        server?.terminate()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func scriptPath() -> String {
        if let override = ProcessInfo.processInfo.environment["CODEX_HARBOR_SCRIPT"], !override.isEmpty { return override }
        return NSString(string: "~/.codex/skills/codex-memory-harbor/scripts/harbor.py").expandingTildeInPath
    }

    private func startServer() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [scriptPath(), "serve", "--port", String(port)]
        let log = Pipe()
        process.standardOutput = log
        process.standardError = log
        do { try process.run(); server = process }
        catch { showError("无法启动本地仪表盘：\(error.localizedDescription)") }
    }

    private func loadWhenReady(attempt: Int) {
        guard attempt < 35 else { showError("仪表盘未能在本机端口 \(port) 启动。请检查 Skill 是否安装。"); return }
        let url = URL(string: "http://127.0.0.1:\(port)/")!
        URLSession.shared.dataTask(with: url) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                if response != nil { self?.webView.load(URLRequest(url: url)) }
                else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { self?.loadWhenReady(attempt: attempt + 1) } }
            }
        }.resume()
    }

    private func installVolumeObservers() {
        let center = NSWorkspace.shared.notificationCenter
        let names: [Notification.Name] = [
            NSWorkspace.didMountNotification,
            NSWorkspace.didUnmountNotification,
            NSWorkspace.didRenameVolumeNotification,
            NSWorkspace.didWakeNotification,
        ]
        workspaceObservers = names.map { name in
            center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                self?.webView.evaluateJavaScript("if (window.harborVolumeChanged) window.harborVolumeChanged();")
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.allow); return }
        if url.scheme == "codex" { openCodex(url); decisionHandler(.cancel); return }
        if url.scheme == "harbor", url.host == "compact" { decisionHandler(.cancel); NSApp.terminate(nil); return }
        decisionHandler(.allow)
    }

    private func openCodex(_ url: URL) {
        guard let applicationURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.openai.codex") else { showError("未找到 Codex 桌面应用。"); return }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.open([url], withApplicationAt: applicationURL, configuration: configuration) { [weak self] _, error in
            guard let error else { return }
            DispatchQueue.main.async { self?.showError("无法打开 Codex 任务：\(error.localizedDescription)") }
        }
    }

    private func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Memory Harbor"; alert.informativeText = message; alert.alertStyle = .warning; alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = DashboardDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
