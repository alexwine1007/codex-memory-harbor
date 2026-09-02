import Cocoa
import WebKit

final class DashboardDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private var serverOutput: Pipe?
    private var workspaceObservers: [NSObjectProtocol] = []
    private var startupSucceeded = false
    private var startupFailed = false
    private var isTerminating = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1180, height: 790)
        let width = min(1180, max(760, visible.width - 28))
        let height = min(790, max(620, visible.height - 28))
        let frame = NSRect(x: visible.midX - width / 2, y: visible.midY - height / 2, width: width, height: height)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Memory Harbor"
        window.minSize = NSSize(width: min(760, width), height: min(620, height))
        window.titlebarAppearsTransparent = true
        window.isOpaque = true
        window.backgroundColor = NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.095, alpha: 1)
        webView = WKWebView(frame: NSRect(origin: .zero, size: frame.size))
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.isHidden = true
        let container = NSView(frame: NSRect(origin: .zero, size: frame.size))
        container.wantsLayer = true
        container.layer?.backgroundColor = window.backgroundColor.cgColor
        container.addSubview(webView)
        let progress = NSProgressIndicator(frame: NSRect(x: frame.width / 2 - 10, y: frame.height / 2 + 7, width: 20, height: 20))
        progress.style = .spinning
        progress.startAnimation(nil)
        progress.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        container.addSubview(progress)
        let loading = NSTextField(labelWithString: "正在打开 Memory Harbor…")
        loading.textColor = NSColor(calibratedWhite: 0.72, alpha: 1)
        loading.alignment = .center
        loading.frame = NSRect(x: frame.width / 2 - 150, y: frame.height / 2 - 30, width: 300, height: 22)
        loading.autoresizingMask = [.minXMargin, .maxXMargin, .minYMargin, .maxYMargin]
        container.addSubview(loading)
        window.contentView = container
        installVolumeObservers()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServer()
    }

    func applicationWillTerminate(_ notification: Notification) {
        isTerminating = true
        let center = NSWorkspace.shared.notificationCenter
        workspaceObservers.forEach { center.removeObserver($0) }
        serverOutput?.fileHandleForReading.readabilityHandler = nil
        server?.terminate()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func scriptPath() -> String {
        if let override = ProcessInfo.processInfo.environment["CODEX_HARBOR_SCRIPT"], !override.isEmpty { return override }
        return NSString(string: "~/.codex/skills/codex-memory-harbor/scripts/harbor.py").expandingTildeInPath
    }

    private func startServer() {
        let path = scriptPath()
        guard FileManager.default.isReadableFile(atPath: path) else {
            failStartup("未找到已安装的 Memory Harbor Skill。")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [path, "serve", "--port", "0", "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        server = process
        serverOutput = output
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self, self.server === finished else { return }
                self.server = nil
                if !self.isTerminating {
                    let message = self.startupSucceeded
                        ? "本地仪表盘服务已停止，请重新打开详情页。"
                        : "本地仪表盘服务提前退出（状态 \(finished.terminationStatus)）。"
                    self.failStartup(message)
                }
            }
        }
        do {
            try process.run()
            readServerAddress(from: output, process: process)
        } catch {
            server = nil
            failStartup("无法启动本地仪表盘：\(error.localizedDescription)")
        }
    }

    private func readServerAddress(from output: Pipe, process: Process) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var data = Data()
            while process.isRunning && data.firstIndex(of: 0x0A) == nil && data.count < 65_536 {
                let chunk = output.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                data.append(chunk)
            }
            let lineData = data.firstIndex(of: 0x0A).map { data.prefix(upTo: $0) } ?? data[...]
            guard
                !lineData.isEmpty,
                let payload = try? JSONSerialization.jsonObject(with: Data(lineData)) as? [String: Any],
                let value = payload["url"] as? String,
                let url = URL(string: value)
            else {
                DispatchQueue.main.async { self?.failStartup("本地仪表盘没有返回有效的启动地址。") }
                return
            }
            DispatchQueue.main.async {
                guard self?.server === process, process.isRunning else { return }
                self?.loadWhenReady(url: url, attempt: 0)
            }
        }
    }

    private func loadWhenReady(url: URL, attempt: Int) {
        guard attempt < 35 else { failStartup("本地仪表盘服务启动超时。"); return }
        URLSession.shared.dataTask(with: url) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                if response != nil {
                    self?.startupSucceeded = true
                    self?.webView.load(URLRequest(url: url))
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) {
                        self?.loadWhenReady(url: url, attempt: attempt + 1)
                    }
                }
            }
        }.resume()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.isHidden = false
        webView.superview?.subviews.filter { $0 !== webView }.forEach { $0.isHidden = true }
    }

    private func failStartup(_ message: String) {
        guard !startupFailed && !isTerminating else { return }
        startupFailed = true
        serverOutput?.fileHandleForReading.readabilityHandler = nil
        server?.terminate()
        window?.orderOut(nil)
        showError(message)
        NSApp.terminate(nil)
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
