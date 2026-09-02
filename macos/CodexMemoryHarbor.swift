import Cocoa

final class CompactCardView: NSView {
    private let statusLabel = CompactCardView.label("检查中", size: 13, color: NSColor(calibratedWhite: 0.67, alpha: 1))
    private let eligibleLabel = CompactCardView.label("—", size: 52, weight: .bold)
    private let driveLabel = CompactCardView.label("正在读取本机状态", size: 12, color: NSColor(calibratedWhite: 0.67, alpha: 1))
    private let driveDot = NSView()

    init(target: AnyObject, action: Selector) {
        super.init(frame: NSRect(x: 0, y: 0, width: 360, height: 250))
        wantsLayer = true
        let logo = NSImageView(frame: NSRect(x: 21, y: 186, width: 40, height: 40))
        logo.image = NSApplication.shared.applicationIconImage
        logo.imageScaling = .scaleProportionallyUpOrDown
        addSubview(logo)
        let title = CompactCardView.label("记忆港", size: 16, weight: .semibold)
        title.frame = NSRect(x: 72, y: 203, width: 180, height: 23)
        addSubview(title)
        statusLabel.frame = NSRect(x: 72, y: 184, width: 210, height: 20)
        addSubview(statusLabel)
        let heading = CompactCardView.label("可安全释放", size: 12, color: NSColor(calibratedWhite: 0.67, alpha: 1))
        heading.frame = NSRect(x: 21, y: 150, width: 150, height: 19)
        addSubview(heading)
        eligibleLabel.frame = NSRect(x: 18, y: 87, width: 320, height: 62)
        addSubview(eligibleLabel)
        let note = CompactCardView.label("不碰主任务，不读取正文", size: 12, color: NSColor(calibratedWhite: 0.67, alpha: 1))
        note.frame = NSRect(x: 21, y: 66, width: 230, height: 19)
        addSubview(note)
        driveDot.frame = NSRect(x: 23, y: 32, width: 8, height: 8)
        driveDot.wantsLayer = true
        driveDot.layer?.cornerRadius = 4
        driveDot.layer?.backgroundColor = NSColor.systemTeal.cgColor
        addSubview(driveDot)
        driveLabel.frame = NSRect(x: 39, y: 24, width: 190, height: 23)
        addSubview(driveLabel)
        let button = NSButton(title: "整理空间", target: target, action: action)
        button.frame = NSRect(x: 247, y: 18, width: 92, height: 38)
        button.isBordered = false
        button.font = .systemFont(ofSize: 13, weight: .semibold)
        button.contentTintColor = .white
        button.wantsLayer = true
        button.layer?.cornerRadius = 12
        button.layer?.backgroundColor = NSColor(calibratedRed: 0.39, green: 0.43, blue: 1.0, alpha: 1).cgColor
        addSubview(button)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 28, yRadius: 28)
        path.addClip()
        let colors = [
            NSColor(calibratedRed: 0.10, green: 0.09, blue: 0.19, alpha: 1).cgColor,
            NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.095, alpha: 1).cgColor,
        ] as CFArray
        if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1]) {
            NSGraphicsContext.current?.cgContext.drawLinearGradient(
                gradient,
                start: CGPoint(x: bounds.maxX, y: bounds.maxY),
                end: CGPoint(x: bounds.minX, y: bounds.minY),
                options: []
            )
        }
        NSColor(calibratedWhite: 1, alpha: 0.10).setStroke()
        path.lineWidth = 1
        path.stroke()
    }

    func showLoading() { statusLabel.stringValue = "正在更新" }

    func update(summary: [String: Any]) {
        let available = summary["volume_available"] as? Bool ?? false
        eligibleLabel.stringValue = summary["eligible_h"] as? String ?? "—"
        statusLabel.stringValue = available ? "工作正常" : "外挂盘未连接"
        if available {
            let name = summary["volume_name"] as? String ?? "外置盘"
            let free = summary["volume_free_h"] as? String ?? ""
            driveLabel.stringValue = "\(name) · \(free) 可用"
            driveDot.layer?.backgroundColor = NSColor.systemTeal.cgColor
        } else {
            driveLabel.stringValue = "连接硬盘后可整理"
            driveDot.layer?.backgroundColor = NSColor.systemOrange.cgColor
        }
    }

    func showFailure() {
        statusLabel.stringValue = "状态暂不可用"
        driveLabel.stringValue = "打开详情后可重新扫描"
        driveDot.layer?.backgroundColor = NSColor.systemOrange.cgColor
    }

    private static func label(_ value: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = .white) -> NSTextField {
        let field = NSTextField(labelWithString: value)
        field.font = .systemFont(ofSize: size, weight: weight)
        field.textColor = color
        field.backgroundColor = .clear
        field.isSelectable = false
        field.lineBreakMode = .byTruncatingTail
        return field
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private var compactView: CompactCardView!
    private var statusProcess: Process?
    private var dashboardProcess: Process?
    private var pendingStatusRefresh = false
    private var workspaceObservers: [NSObjectProtocol] = []
    private let compactFrameKey = "CodexMemoryHarborCompactFrame"

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        let frame = NSRect(x: 0, y: 0, width: 360, height: 250)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Codex Memory Harbor · 记忆港"
        window.isMovableByWindowBackground = true
        window.minSize = frame.size
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        window.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        window.isOpaque = false
        window.backgroundColor = .clear
        window.delegate = self
        setWindowChrome(hidden: true)
        window.setFrame(restoredCompactFrame(fallback: frame), display: false)
        compactView = CompactCardView(target: self, action: #selector(expandDashboard))
        window.contentView = compactView
        installVolumeObservers()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        refreshCompactStatus(repairLinks: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        let center = NSWorkspace.shared.notificationCenter
        workspaceObservers.forEach { center.removeObserver($0) }
        statusProcess?.terminate()
        dashboardProcess?.terminate()
    }
    // The compact window is temporarily hidden while the isolated dashboard helper runs.
    // Keeping the owner alive lets it restore the exact desktop position when the helper exits.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func windowDidMove(_ notification: Notification) { saveCompactFrame() }
    func windowDidEndLiveResize(_ notification: Notification) { saveCompactFrame() }

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
                self?.refreshCompactStatus(repairLinks: true)
            }
        }
    }

    private func defaultCompactFrame(size: NSSize) -> NSRect {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 800, height: 600)
        return NSRect(x: visible.maxX - size.width - 26, y: visible.maxY - size.height - 26, width: size.width, height: size.height)
    }

    private func restoredCompactFrame(fallback: NSRect) -> NSRect {
        guard let value = UserDefaults.standard.string(forKey: compactFrameKey) else { return defaultCompactFrame(size: fallback.size) }
        var saved = NSRectFromString(value)
        saved.size = fallback.size
        if NSScreen.screens.contains(where: { $0.visibleFrame.intersects(saved) }) { return saved }
        return defaultCompactFrame(size: fallback.size)
    }

    private func saveCompactFrame() { UserDefaults.standard.set(NSStringFromRect(window.frame), forKey: compactFrameKey) }

    private func scriptPath() -> String {
        if let override = ProcessInfo.processInfo.environment["CODEX_HARBOR_SCRIPT"], !override.isEmpty { return override }
        return NSString(string: "~/.codex/skills/codex-memory-harbor/scripts/harbor.py").expandingTildeInPath
    }

    private func runStatusCommand(_ arguments: [String], completion: @escaping (Data?) -> Void) {
        if statusProcess != nil { pendingStatusRefresh = true; return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [scriptPath()] + arguments
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        statusProcess = process
        process.terminationHandler = { [weak self] finished in
            let data = output.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {
                self?.statusProcess = nil
                completion(finished.terminationStatus == 0 ? data : nil)
                if self?.pendingStatusRefresh == true {
                    self?.pendingStatusRefresh = false
                    self?.refreshCompactStatus(repairLinks: false)
                }
            }
        }
        do { try process.run() } catch { statusProcess = nil; completion(nil) }
    }

    private func refreshCompactStatus(repairLinks: Bool) {
        guard dashboardProcess == nil else { return }
        compactView.showLoading()
        let arguments = repairLinks ? ["compact-status", "--repair-links"] : ["compact-status"]
        runStatusCommand(arguments) { [weak self] data in
            guard let self else { return }
            guard let data, let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.compactView.showFailure(); return
            }
            self.compactView.update(summary: value)
        }
    }

    private func setWindowChrome(hidden: Bool) {
        window.titleVisibility = hidden ? .hidden : .visible
        window.titlebarAppearsTransparent = hidden
        window.hasShadow = !hidden
        window.standardWindowButton(.closeButton)?.isHidden = hidden
        window.standardWindowButton(.miniaturizeButton)?.isHidden = hidden
        window.standardWindowButton(.zoomButton)?.isHidden = hidden
    }

    @objc private func expandDashboard() {
        guard dashboardProcess == nil else { return }
        saveCompactFrame()
        statusProcess?.terminate()
        statusProcess = nil
        let helper = Bundle.main.bundleURL.appendingPathComponent(
            "Contents/Helpers/Codex Memory Harbor Dashboard.app/Contents/MacOS/CodexMemoryHarborDashboard"
        ).path
        let process = Process()
        process.executableURL = URL(fileURLWithPath: helper)
        process.environment = ProcessInfo.processInfo.environment
        dashboardProcess = process
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.dashboardProcess = nil
                self?.window.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
                self?.refreshCompactStatus(repairLinks: false)
            }
        }
        do {
            try process.run()
            window.orderOut(nil)
        } catch {
            dashboardProcess = nil
            showError("无法打开详情页：\(error.localizedDescription)")
        }
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
