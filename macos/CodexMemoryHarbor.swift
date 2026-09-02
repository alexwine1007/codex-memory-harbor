import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private let port = 48765

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        startServer()
        let frame = NSRect(x: 0, y: 0, width: 360, height: 250)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Codex Memory Harbor · 记忆港"
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        window.minSize = NSSize(width: 360, height: 250)
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        setWindowChrome(hidden: true)
        if let screen = NSScreen.main {
            let visible = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: visible.maxX - frame.width - 26, y: visible.maxY - frame.height - 26))
        }
        webView = WKWebView(frame: frame)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        loadWhenReady(attempt: 0)
    }

    func applicationWillTerminate(_ notification: Notification) { server?.terminate() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func scriptPath() -> String {
        if let override = ProcessInfo.processInfo.environment["CODEX_HARBOR_SCRIPT"], !override.isEmpty { return override }
        return NSString(string: "~/.codex/skills/codex-memory-harbor/scripts/harbor.py").expandingTildeInPath
    }

    private func startServer() {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [scriptPath(), "serve", "--port", String(port)]
        let log = Pipe(); p.standardOutput = log; p.standardError = log
        do { try p.run(); server = p } catch { showError("无法启动本地仪表盘：\(error.localizedDescription)") }
    }

    private func loadWhenReady(attempt: Int) {
        guard attempt < 35 else { showError("仪表盘未能在本机端口 \(port) 启动。请检查 Skill 是否安装。") ; return }
        let url = URL(string: "http://127.0.0.1:\(port)/widget.html")!
        URLSession.shared.dataTask(with: url) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                if response != nil { self?.webView.load(URLRequest(url: url)) }
                else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { self?.loadWhenReady(attempt: attempt + 1) } }
            }
        }.resume()
    }

    private func setWindowChrome(hidden: Bool) {
        window.titleVisibility = hidden ? .hidden : .visible
        window.titlebarAppearsTransparent = hidden
        window.standardWindowButton(.closeButton)?.isHidden = hidden
        window.standardWindowButton(.miniaturizeButton)?.isHidden = hidden
        window.standardWindowButton(.zoomButton)?.isHidden = hidden
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url, url.scheme == "harbor" else { decisionHandler(.allow); return }
        if url.host == "expand" {
            setWindowChrome(hidden: false)
            window.level = .normal
            let visible = (window.screen ?? NSScreen.main)?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1180, height: 790)
            let width = min(1180, max(620, visible.width - 28))
            let height = min(790, max(560, visible.height - 28))
            window.minSize = NSSize(width: min(760, width), height: min(620, height))
            window.setFrame(NSRect(x: visible.midX - width / 2, y: visible.midY - height / 2, width: width, height: height), display: true, animate: true)
            webView.frame = NSRect(x: 0, y: 0, width: width, height: height)
            webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(port)/")!))
        } else if url.host == "compact" {
            setWindowChrome(hidden: true)
            window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
            window.minSize = NSSize(width: 360, height: 250)
            let visible = (window.screen ?? NSScreen.main)?.visibleFrame ?? NSRect(x: 0, y: 0, width: 800, height: 600)
            window.setFrame(NSRect(x: visible.maxX - 386, y: visible.maxY - 276, width: 360, height: 250), display: true, animate: true)
            webView.frame = NSRect(x: 0, y: 0, width: 360, height: 250)
            webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(port)/widget.html")!))
        }
        decisionHandler(.cancel)
    }

    private func buildMenu() {
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let submenu = NSMenu(); submenu.addItem(withTitle: "关于 Codex Memory Harbor", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        submenu.addItem(NSMenuItem.separator()); submenu.addItem(withTitle: "退出", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = submenu; NSApp.mainMenu = menu
    }

    private func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Codex Memory Harbor"; alert.informativeText = message; alert.alertStyle = .warning; alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
