import AppKit
import Foundation

// Native presentation only. Downloads and their launchd worker remain independent.
final class WindowContentView: NSView {
    override var isOpaque: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.windowBackgroundColor.setFill()
        dirtyRect.fill()
        super.draw(dirtyRect)
    }
}

final class CardView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        let shape = NSBezierPath(roundedRect: bounds.insetBy(dx: 0.5, dy: 0.5), xRadius: 11, yRadius: 11)
        NSColor.controlBackgroundColor.withAlphaComponent(0.7).setFill()
        shape.fill()
        NSColor.separatorColor.withAlphaComponent(0.45).setStroke()
        shape.lineWidth = 1
        shape.stroke()
    }
}

final class ProgressBar: NSView {
    let activity = NSProgressIndicator()
    var minValue = 0.0
    var maxValue = 100.0
    var doubleValue = 0.0 { didSet { needsDisplay = true; setAccessibilityValue(doubleValue) } }
    var isIndeterminate = true {
        didSet { activity.isHidden = !isIndeterminate; needsDisplay = true }
    }
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        activity.style = .bar
        activity.isIndeterminate = true
        activity.translatesAutoresizingMaskIntoConstraints = false
        addSubview(activity)
        NSLayoutConstraint.activate([
            activity.leadingAnchor.constraint(equalTo: leadingAnchor), activity.trailingAnchor.constraint(equalTo: trailingAnchor),
            activity.centerYAnchor.constraint(equalTo: centerYAnchor)
        ])
        setAccessibilityRole(.progressIndicator)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func startAnimation(_ sender: Any?) { activity.isHidden = !isIndeterminate; if isIndeterminate { activity.startAnimation(sender) } }
    func stopAnimation(_ sender: Any?) { activity.stopAnimation(sender); activity.isHidden = true }
    override func draw(_ dirtyRect: NSRect) {
        guard !isIndeterminate else { return }
        let track = NSRect(x: 0, y: (bounds.height - 8) / 2, width: bounds.width, height: 8)
        NSColor.separatorColor.withAlphaComponent(0.4).setFill()
        NSBezierPath(roundedRect: track, xRadius: 4, yRadius: 4).fill()
        let fraction = maxValue > minValue ? min(1, max(0, (doubleValue - minValue) / (maxValue - minValue))) : 0
        if fraction > 0 {
            NSColor.controlAccentColor.setFill()
            NSBezierPath(roundedRect: NSRect(x: track.minX, y: track.minY, width: track.width * fraction, height: track.height), xRadius: 4, yRadius: 4).fill()
        }
    }
}

final class OpaqueTableHeaderView: NSTableHeaderView {
    override var isOpaque: Bool { true }
    override var allowsVibrancy: Bool { false }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.controlBackgroundColor.setFill()
        dirtyRect.fill()
        super.draw(dirtyRect)
    }
}

func header(_ title: String, subtitle: String, symbol: String) -> NSStackView {
    let image = NSImageView()
    image.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)?
        .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 29, weight: .medium))
    image.contentTintColor = .controlAccentColor
    image.widthAnchor.constraint(equalToConstant: 40).isActive = true
    image.heightAnchor.constraint(equalToConstant: 40).isActive = true
    let text = NSStackView()
    text.orientation = .vertical
    text.alignment = .leading
    text.spacing = 3
    text.addArrangedSubview(label(title, size: 23, bold: true))
    let caption = label(subtitle, size: 12)
    caption.textColor = .secondaryLabelColor
    text.addArrangedSubview(caption)
    let row = NSStackView(views: [image, text])
    row.orientation = .horizontal
    row.alignment = .centerY
    row.spacing = 12
    return row
}

func card(_ views: [NSView]) -> NSView {
    let container = CardView()
    let stack = NSStackView(views: views)
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = 6
    stack.translatesAutoresizingMaskIntoConstraints = false
    container.addSubview(stack)
    NSLayoutConstraint.activate([
        stack.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 12),
        stack.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -12),
        stack.topAnchor.constraint(equalTo: container.topAnchor, constant: 9),
        stack.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -9)
    ])
    for view in views { view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
    return container
}

func emitJSON(_ value: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) {
        print(text)
        fflush(stdout)
    }
}

func option(_ name: String, in arguments: [String]) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else { return nil }
    return arguments[index + 1]
}

func configureEditingMenu(_ app: NSApplication) {
    let menu = NSMenu()
    let applicationItem = NSMenuItem()
    let applicationMenu = NSMenu(title: "youtube downloader")
    applicationMenu.addItem(withTitle: "結束 youtube downloader", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    applicationItem.submenu = applicationMenu
    menu.addItem(applicationItem)
    let editItem = NSMenuItem(title: "編輯", action: nil, keyEquivalent: "")
    let edit = NSMenu(title: "編輯")
    for (title, action, key) in [("還原", "undo:", "z"), ("剪下", "cut:", "x"),
                                 ("拷貝", "copy:", "c"), ("貼上", "paste:", "v"), ("全選", "selectAll:", "a")] {
        edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
    }
    editItem.submenu = edit
    menu.addItem(editItem)
    app.mainMenu = menu
}

func mixRetryCount(_ text: String) -> Int? {
    let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !value.isEmpty, value.range(of: "^[0-9]+$", options: .regularExpression) != nil,
          let count = Int(value), (1...500).contains(count) else { return nil }
    return count
}

func label(_ text: String, size: CGFloat = 14, bold: Bool = false) -> NSTextField {
    let field = NSTextField(wrappingLabelWithString: text)
    field.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
    field.isSelectable = true
    field.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    return field
}

func scrollingText(_ text: String) -> NSScrollView {
    let view = NSTextView()
    view.string = text
    view.font = .systemFont(ofSize: 15)
    view.isEditable = false
    view.isSelectable = true
    view.drawsBackground = false
    view.textContainerInset = NSSize(width: 10, height: 10)
    view.autoresizingMask = [.width]
    view.isVerticallyResizable = true
    view.isHorizontallyResizable = false
    view.textContainer?.widthTracksTextView = true
    let scroll = NSScrollView()
    scroll.documentView = view
    scroll.hasVerticalScroller = true
    scroll.autohidesScrollers = true
    scroll.borderType = .bezelBorder
    return scroll
}

func makeWindow(title: String, size: NSSize, minimum: NSSize) -> NSWindow {
    let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable]
    let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1280, height: 900)
    let available = visible.insetBy(dx: 12, dy: 12).size
    let desired = NSWindow.frameRect(forContentRect: NSRect(origin: .zero, size: size), styleMask: style).size
    let frame = NSRect(origin: .zero, size: NSSize(width: min(desired.width, available.width),
                                                height: min(desired.height, available.height)))
    let content = NSWindow.contentRect(forFrameRect: frame, styleMask: style)
    let window = NSWindow(contentRect: content,
                          styleMask: style,
                          backing: .buffered, defer: false)
    window.title = title
    window.contentView = WindowContentView(frame: NSRect(origin: .zero, size: content.size))
    window.minSize = NSSize(width: min(minimum.width, available.width), height: min(minimum.height, available.height))
    window.isReleasedWhenClosed = false
    window.center()
    return window
}

func attach(_ stack: NSStackView, to content: NSView) {
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = 12
    stack.translatesAutoresizingMaskIntoConstraints = false
    content.addSubview(stack)
    NSLayoutConstraint.activate([
        stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 22),
        stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -22),
        stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
        stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20)
    ])
}

func fillWidth(_ view: NSView, in stack: NSStackView) {
    view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
}

func snapshot(_ window: NSWindow, to path: String) throws {
    guard path.hasPrefix("/"), let view = window.contentView else {
        throw NSError(domain: "MusicDownloaderUI", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Snapshot requires an absolute path."])
    }
    view.layoutSubtreeIfNeeded()
    window.displayIfNeeded()
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
        throw NSError(domain: "MusicDownloaderUI", code: 2)
    }
    view.effectiveAppearance.performAsCurrentDrawingAppearance {
        func invalidate(_ target: NSView) {
            target.needsDisplay = true
            for child in target.subviews { invalidate(child) }
        }
        invalidate(view)
        view.display()
        view.cacheDisplay(in: view.bounds, to: bitmap)
    }
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "MusicDownloaderUI", code: 3)
    }
    try data.write(to: URL(fileURLWithPath: path), options: .atomic)
}

final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

final class DialogController: NSObject, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate {
    let window: NSWindow
    let kind: String
    let choices: [String]
    let table = NSTableView()
    let input = NSTextField(string: "")
    var acceptButton: NSButton!
    var cancelButton: NSButton?
    var finished = false
    var exerciseCompletion: ((String, Bool) -> Void)?

    init(request: [String: Any]) {
        kind = request["kind"] as? String ?? "message"
        choices = request["choices"] as? [String] ?? []
        window = makeWindow(title: request["title"] as? String ?? "youtube downloader",
                            size: NSSize(width: 780, height: kind == "ask" ? 420 : 520),
                            minimum: NSSize(width: 640, height: kind == "ask" ? 340 : 400))
        super.init()
        window.delegate = self
        let stack = NSStackView()
        attach(stack, to: window.contentView!)
        let subtitle = kind == "choose" ? "選擇項目後按 Enter 繼續" : (kind == "ask" ? "輸入內容後按 Enter 繼續" : "操作說明")
        let heading = header(request["title"] as? String ?? "youtube downloader", subtitle: subtitle,
                             symbol: kind == "message" ? "info.circle.fill" : "music.note.list")
        stack.addArrangedSubview(heading)
        fillWidth(heading, in: stack)
        let promptText = request["prompt"] as? String ?? ""
        let prompt = scrollingText(promptText)
        stack.addArrangedSubview(prompt)
        fillWidth(prompt, in: stack)
        let measured = (promptText as NSString).boundingRect(with: NSSize(width: 700, height: 2000),
                            options: [.usesLineFragmentOrigin, .usesFontLeading],
                            attributes: [.font: NSFont.systemFont(ofSize: 15)]).height + 26
        if kind != "message" {
            let desired = min(kind == "choose" ? 175 : 185, max(66, measured))
            let height = prompt.heightAnchor.constraint(equalToConstant: desired)
            height.priority = .defaultHigh
            height.isActive = true
        }
        prompt.heightAnchor.constraint(greaterThanOrEqualToConstant: 55).isActive = true

        if kind == "choose" {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("choice"))
            column.title = "選項"
            column.width = 700
            table.addTableColumn(column)
            table.headerView = nil
            table.rowHeight = 37
            table.usesAlternatingRowBackgroundColors = true
            table.allowsEmptySelection = true
            table.dataSource = self
            table.delegate = self
            table.target = self
            table.doubleAction = #selector(accept(_:))
            table.columnAutoresizingStyle = .lastColumnOnlyAutoresizingStyle
            let scroll = NSScrollView()
            scroll.documentView = table
            scroll.hasVerticalScroller = true
            scroll.autohidesScrollers = true
            scroll.borderType = .bezelBorder
            stack.addArrangedSubview(scroll)
            fillWidth(scroll, in: stack)
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 145).isActive = true
            prompt.setContentHuggingPriority(.defaultHigh, for: .vertical)
            scroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        } else if kind == "ask" {
            let caption = label("輸入內容", size: 13, bold: true)
            stack.addArrangedSubview(caption)
            input.stringValue = request["default"] as? String ?? ""
            input.font = .systemFont(ofSize: 17)
            input.cell?.isScrollable = true
            input.cell?.usesSingleLineMode = true
            input.placeholderString = "請在此輸入"
            stack.addArrangedSubview(input)
            fillWidth(input, in: stack)
            input.heightAnchor.constraint(equalToConstant: 36).isActive = true
            prompt.setContentHuggingPriority(.defaultHigh, for: .vertical)
            let spacer = NSView()
            spacer.setContentHuggingPriority(.defaultLow, for: .vertical)
            stack.addArrangedSubview(spacer)
        } else {
            prompt.setContentHuggingPriority(.defaultLow, for: .vertical)
        }
        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 10
        buttons.addArrangedSubview(NSView())
        if kind != "message" {
            let cancel = NSButton(title: "取消", target: self, action: #selector(cancel(_:)))
            cancel.keyEquivalent = "\u{1b}"
            cancelButton = cancel
            buttons.addArrangedSubview(cancel)
        }
        acceptButton = NSButton(title: kind == "message" ? "好" : (kind == "choose" ? "選擇" : "繼續"),
                                target: self, action: #selector(accept(_:)))
        acceptButton.keyEquivalent = "\r"
        acceptButton.bezelStyle = .rounded
        acceptButton.isEnabled = kind != "choose" || !choices.isEmpty
        buttons.addArrangedSubview(acceptButton)
        stack.addArrangedSubview(buttons)
        fillWidth(buttons, in: stack)
        if kind == "choose", !choices.isEmpty {
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        }
    }

    func show() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if kind == "ask" {
            window.makeFirstResponder(input)
            input.selectText(nil)
        } else if kind == "choose" {
            window.makeFirstResponder(table)
        }
    }

    func numberOfRows(in tableView: NSTableView) -> Int { choices.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard choices.indices.contains(row) else { return nil }
        let text = NSTextField(labelWithString: choices[row])
        text.font = .systemFont(ofSize: 16)
        text.lineBreakMode = .byTruncatingTail
        text.toolTip = choices[row]
        return text
    }
    func tableViewSelectionDidChange(_ notification: Notification) {
        acceptButton?.isEnabled = table.selectedRow >= 0
    }
    @objc func accept(_ sender: Any?) {
        if kind == "choose" {
            guard choices.indices.contains(table.selectedRow) else { return }
            finish(value: choices[table.selectedRow])
        } else {
            finish(value: kind == "ask" ? input.stringValue : "")
        }
    }
    @objc func cancel(_ sender: Any?) { finish(cancelled: true) }
    func finish(value: String = "", cancelled: Bool = false) {
        guard !finished else { return }
        finished = true
        exerciseCompletion?(value, cancelled)
        emitJSON(["value": value, "cancelled": cancelled])
        NSApp.terminate(nil)
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        finish(cancelled: true)
        return false
    }
}

struct BackendFailure: Error { let message: String }

final class ProgressController: NSObject, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate, NSSearchFieldDelegate, NSMenuDelegate {
    let window = makeWindow(title: "youtube downloader — 下載進度",
                            size: NSSize(width: 960, height: 730), minimum: NSSize(width: 780, height: 660))
    let home: String
    let python: String
    let engine: String
    var jobID: String?
    var job: [String: Any] = [:]
    var items: [[String: Any]] = []
    var visibleItems: [[String: Any]] = []
    var latestJobs: [[String: Any]] = []
    var isPickerOpen = false
    var cancelAlert: NSAlert?
    var retryAlert: NSAlert?
    var retryInput: NSTextField?
    var retryValidation: NSTextField?
    var timer: Timer?
    var polling = false
    var commandRunning = false
    var ticks = 0
    let picker = NSPopUpButton()
    let phase = label("正在讀取下載進度…", size: 19, bold: true)
    let overallText = label("整份清單：等待資料", bold: true)
    let overallBar = ProgressBar()
    let counts = label("下載 0　跳過 0　失敗 0", size: 13)
    let trackText = label("目前歌曲：—", bold: true)
    let trackBar = ProgressBar()
    let transfer = label("當首：等待資料", size: 13)
    let banner = label(" ", size: 12)
    let details = NSTextView()
    let detailsScroll = NSScrollView()
    let searchField = NSSearchField()
    let failedOnlyButton = NSButton(checkboxWithTitle: "只看失敗", target: nil, action: nil)
    let filteredCount = label("", size: 12)
    let table = NSTableView()
    let tableScroll = NSScrollView()
    var cancelButton: NSButton!
    var retryButton: NSButton!
    var reportButton: NSButton!
    var folderButton: NSButton!
    var refreshButton: NSButton!
    var closeButton: NSButton!
    var exerciseClosed: (() -> Void)?

    init(home: String, python: String, engine: String, jobID: String?) {
        self.home = home
        self.python = python
        self.engine = engine
        self.jobID = jobID
        super.init()
        window.delegate = self
        let stack = NSStackView()
        attach(stack, to: window.contentView!)
        stack.spacing = 8
        let heading = header("下載進度", subtitle: "即時更新 · 關閉視窗後仍會在背景下載", symbol: "arrow.down.circle.fill")
        stack.addArrangedSubview(heading)
        fillWidth(heading, in: stack)
        picker.target = self
        picker.action = #selector(selectJob(_:))
        picker.addItem(withTitle: "正在讀取任務…")
        picker.menu?.delegate = self
        stack.addArrangedSubview(picker)
        fillWidth(picker, in: stack)
        stack.addArrangedSubview(phase)
        fillWidth(phase, in: stack)
        configureBar(overallBar)
        let overallCard = card([overallText, overallBar, counts])
        stack.addArrangedSubview(overallCard)
        fillWidth(overallCard, in: stack)
        trackText.maximumNumberOfLines = 2
        configureBar(trackBar)
        let trackCard = card([trackText, trackBar, transfer])
        stack.addArrangedSubview(trackCard)
        fillWidth(trackCard, in: stack)
        searchField.placeholderString = "搜尋歌曲、分類或原因"
        searchField.delegate = self
        searchField.target = self
        searchField.action = #selector(filterChanged(_:))
        searchField.sendsSearchStringImmediately = true
        failedOnlyButton.target = self
        failedOnlyButton.action = #selector(filterChanged(_:))
        filteredCount.textColor = .secondaryLabelColor
        let filters = NSStackView(views: [searchField, failedOnlyButton, filteredCount])
        filters.orientation = .horizontal
        filters.spacing = 12
        searchField.setContentHuggingPriority(.defaultLow, for: .horizontal)
        stack.addArrangedSubview(filters)
        fillWidth(filters, in: stack)
        for (identifier, title, width) in [("position", "序號", 48.0), ("title", "歌曲標題", 390.0),
                                            ("state", "結果", 85.0), ("category", "分類", 120.0), ("reason", "分類原因", 200.0)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(identifier))
            column.title = title
            column.width = width
            column.minWidth = identifier == "title" ? 200 : 45
            table.addTableColumn(column)
        }
        table.rowHeight = 34
        table.headerView = OpaqueTableHeaderView()
        table.usesAlternatingRowBackgroundColors = true
        table.columnAutoresizingStyle = .noColumnAutoresizing
        table.dataSource = self
        table.delegate = self
        table.target = self
        table.doubleAction = #selector(revealSelectedFile(_:))
        let scroll = tableScroll
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.autohidesScrollers = true
        scroll.borderType = .bezelBorder
        scroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        stack.addArrangedSubview(scroll)
        fillWidth(scroll, in: stack)
        let tableMinimum = scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 120)
        tableMinimum.priority = .defaultHigh
        tableMinimum.isActive = true
        details.isEditable = false
        details.isSelectable = true
        details.drawsBackground = false
        details.font = .systemFont(ofSize: 12)
        details.textColor = .secondaryLabelColor
        details.textContainerInset = NSSize(width: 7, height: 5)
        details.isVerticallyResizable = true
        details.isHorizontallyResizable = false
        details.autoresizingMask = [.width]
        details.textContainer?.widthTracksTextView = true
        details.string = "選擇歌曲查看完整標題、分類原因及位置；按兩下可在 Finder 顯示既有檔案。"
        detailsScroll.documentView = details
        detailsScroll.hasVerticalScroller = true
        detailsScroll.autohidesScrollers = true
        detailsScroll.borderType = .bezelBorder
        stack.addArrangedSubview(detailsScroll)
        fillWidth(detailsScroll, in: stack)
        detailsScroll.heightAnchor.constraint(equalToConstant: 67).isActive = true
        banner.maximumNumberOfLines = 2
        banner.textColor = .secondaryLabelColor
        stack.addArrangedSubview(banner)
        fillWidth(banner, in: stack)
        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 9
        cancelButton = NSButton(title: "取消任務", target: self, action: #selector(cancelJob(_:)))
        cancelButton.contentTintColor = .systemRed
        retryButton = NSButton(title: "重試任務", target: self, action: #selector(retryJob(_:)))
        reportButton = NSButton(title: "完整結果", target: self, action: #selector(openReport(_:)))
        folderButton = NSButton(title: "開啟音樂資料夾", target: self, action: #selector(openLibrary(_:)))
        refreshButton = NSButton(title: "重新整理", target: self, action: #selector(refreshClick(_:)))
        closeButton = NSButton(title: "關閉視窗", target: self, action: #selector(closeWindow(_:)))
        closeButton.keyEquivalent = "\u{1b}"
        for button in [reportButton!, folderButton!, refreshButton!] {
            buttons.addArrangedSubview(button)
            button.bezelStyle = .rounded
        }
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        buttons.addArrangedSubview(spacer)
        for button in [cancelButton!, retryButton!, closeButton!] {
            buttons.addArrangedSubview(button)
            button.bezelStyle = .rounded
        }
        stack.addArrangedSubview(buttons)
        fillWidth(buttons, in: stack)
        let footnote = label("關閉視窗後，背景下載仍會繼續。整體進度是已處理首數，包含跳過與失敗。", size: 11)
        footnote.textColor = .secondaryLabelColor
        stack.addArrangedSubview(footnote)
        fillWidth(footnote, in: stack)
        updateButtons()
    }

    func configureBar(_ bar: ProgressBar) {
        bar.minValue = 0
        bar.maxValue = 100
        bar.isIndeterminate = true
        bar.startAnimation(nil)
        bar.heightAnchor.constraint(equalToConstant: 16).isActive = true
    }

    func show() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func backend(_ arguments: [String], completion: @escaping (Result<Any, BackendFailure>) -> Void) {
        let executable = python
        let args = [engine, "--home", home] + arguments
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = args
            let output = Pipe()
            let errors = Pipe()
            process.standardOutput = output
            process.standardError = errors
            let timeout = DispatchWorkItem { if process.isRunning { process.terminate() } }
            let result: Result<Any, BackendFailure>
            do {
                try process.run()
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 12, execute: timeout)
                let bytes = output.fileHandleForReading.readDataToEndOfFile()
                _ = errors.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                timeout.cancel()
                let parsed = try JSONSerialization.jsonObject(with: bytes)
                if process.terminationStatus == 0 {
                    result = .success(parsed)
                } else {
                    let error = (parsed as? [String: Any])?["error"] as? String
                    result = .failure(BackendFailure(message: error ?? "暫時無法讀取進度，請按重新整理。"))
                }
            } catch {
                timeout.cancel()
                result = .failure(BackendFailure(message: "暫時無法讀取進度，請確認安裝完整後重新整理。"))
            }
            DispatchQueue.main.async { completion(result) }
        }
    }

    func refresh() {
        guard !polling, !commandRunning else { return }
        polling = true
        ticks += 1
        if jobID == nil || ticks % 5 == 1 {
            backend(["jobs"]) { [weak self] result in
                guard let self = self else { return }
                switch result {
                case .success(let value):
                    let jobs = value as? [[String: Any]] ?? (value as? [String: Any])?["jobs"] as? [[String: Any]] ?? []
                    self.loadJobs(jobs)
                    if self.jobID == nil {
                        self.polling = false
                        self.phase.stringValue = "目前沒有下載任務"
                        self.overallText.stringValue = "執行捷徑即可開始下載。"
                        self.overallBar.stopAnimation(nil)
                        self.trackBar.stopAnimation(nil)
                        self.updateButtons()
                        return
                    }
                    self.loadStatus()
                case .failure(let error): self.polling = false; self.showError(error.message)
                }
            }
        } else {
            loadStatus()
        }
    }

    func loadJobs(_ jobs: [[String: Any]]) {
        latestJobs = jobs
        if jobID == nil {
            let selected = jobs.first { ["queued", "running"].contains($0["state"] as? String ?? "") } ?? jobs.first
            jobID = selected?["id"] as? String
        }
        guard !isPickerOpen else { return }
        let titles = jobs.map { entry -> String in
            let state = stateText(entry["state"] as? String ?? "")
            let category = entry["category"] as? String ?? ""
            let isPlaylist = entry["mode"] as? String == "playlist"
            let url = URLComponents(string: entry["url"] as? String ?? "")
            let mix = url?.queryItems?.contains { $0.name == "list" && ($0.value ?? "").hasPrefix("RD") } ?? false
            var mode = isPlaylist ? (mix ? "Mix" : "清單") : "單首"
            if isPlaylist {
                mode += (numeric(entry["playlist_limit"]).map { " 前\(Int($0))首" } ?? (mix ? " 待設定首數" : " 全部"))
            }
            let formatter = DateFormatter()
            formatter.dateFormat = "MM/dd HH:mm"
            let date = numeric(entry["created"]).map { formatter.string(from: Date(timeIntervalSince1970: $0)) } ?? ""
            return [date, mode, category, state].filter { !$0.isEmpty }.joined(separator: " · ")
        }
        let ids = jobs.map { $0["id"] as? String ?? "" }
        let sameItems = titles == picker.itemTitles && ids == picker.itemArray.map { $0.representedObject as? String ?? "" }
        if sameItems { return }
        picker.removeAllItems()
        for (index, entry) in jobs.enumerated() {
            let id = entry["id"] as? String ?? ""
            picker.addItem(withTitle: titles[index])
            picker.lastItem?.representedObject = id
            picker.lastItem?.toolTip = "任務 \(id)"
            if id == jobID { picker.select(picker.lastItem) }
        }
        if jobs.isEmpty { picker.addItem(withTitle: "目前沒有下載任務") }
    }

    func menuWillOpen(_ menu: NSMenu) { isPickerOpen = true }
    func menuDidClose(_ menu: NSMenu) {
        isPickerOpen = false
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.loadJobs(self.latestJobs)
        }
    }

    func loadStatus() {
        guard let id = jobID else { polling = false; return }
        backend(["status", id]) { [weak self] result in
            guard let self = self else { return }
            self.polling = false
            guard self.jobID == id else { self.refresh(); return }
            switch result {
            case .success(let value):
                if let data = value as? [String: Any], data["id"] as? String == id { self.apply(data) }
                else { self.showError("進度資料格式不完整，稍後會自動再試。") }
            case .failure(let error): self.showError(error.message)
            }
        }
    }

    func numeric(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber else { return nil }
        let result = number.doubleValue
        return result.isFinite ? result : nil
    }

    func setBar(_ bar: ProgressBar, percent: Double?, active: Bool) {
        if let percent = percent {
            bar.stopAnimation(nil)
            bar.isIndeterminate = false
            bar.doubleValue = min(100, max(0, percent))
        } else if active {
            bar.isIndeterminate = true
            bar.startAnimation(nil)
        } else {
            bar.stopAnimation(nil)
            bar.isIndeterminate = false
            bar.doubleValue = 0
        }
    }

    func apply(_ data: [String: Any]) {
        job = data
        items = data["items"] as? [[String: Any]] ?? []
        let state = data["state"] as? String ?? ""
        let active = ["queued", "running"].contains(state)
        phase.stringValue = data["phase_text"] as? String ?? stateText(state)
        phase.textColor = active ? .controlAccentColor : .labelColor
        let total = numeric(data["total"])
        let completed = Int(numeric(data["completed_items"]) ?? 0)
        var overall = numeric(data["overall_percent"])
        let settled = total.map { completed >= Int($0) } ?? false
        if !settled, let percent = overall, percent >= 100 { overall = 99 }
        if let total = total {
            overallText.stringValue = "整份清單：已處理 \(completed) / \(Int(total)) 首" + (overall.map { "（\(Int(floor($0)))%）" } ?? "")
        } else {
            overallText.stringValue = active ? "整份清單：正在取得歌曲數量" : "尚未取得歌曲清單；尚未開始下載"
        }
        setBar(overallBar, percent: overall, active: active)
        let failures = Int(numeric(data["failed"]) ?? 0)
        let statistics = NSMutableAttributedString(string: "")
        for (key, title, color) in [("downloaded", "下載", NSColor.systemGreen), ("skipped", "跳過", NSColor.secondaryLabelColor), ("failed", "失敗", failures > 0 ? NSColor.systemRed : NSColor.secondaryLabelColor)] {
            statistics.append(NSAttributedString(string: "\(title) \(Int(numeric(data[key]) ?? 0))    ",
                attributes: [.foregroundColor: color, .font: NSFont.systemFont(ofSize: 13, weight: .semibold)]))
        }
        counts.attributedStringValue = statistics
        failedOnlyButton.title = failures > 0 ? "只看失敗（\(failures)）" : "只看失敗"
        if !active && failures > 0 {
            phase.stringValue = "\(stateText(state)) · \(failures) 首失敗，請查看原因後重試"
            phase.textColor = .systemOrange
        } else if state == "completed" {
            phase.textColor = .systemGreen
        }
        let title = data["current_title"] as? String ?? ""
        trackText.stringValue = title.isEmpty ? "目前歌曲：—" : "目前歌曲：\(title)"
        let trackPercent = numeric(data["track_percent"])
        setBar(trackBar, percent: trackPercent, active: active && !title.isEmpty)
        var components = [String]()
        if let number = trackPercent { components.append("當首下載 \(String(format: "%.1f", number))%") }
        else { components.append(active ? "當首：\(phase.stringValue)" : "當首：—") }
        if let speed = data["speed_text"] as? String, !speed.isEmpty { components.append("速度 \(speed)") }
        if let eta = data["eta_text"] as? String, !eta.isEmpty { components.append("當首下載剩餘 \(eta)") }
        transfer.stringValue = components.joined(separator: "　｜　")
        updateVisibleItems()
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        banner.textColor = .secondaryLabelColor
        banner.stringValue = "最後更新 \(formatter.string(from: Date()))　｜　任務 \(data["id"] as? String ?? "")"
        updateButtons()
    }

    func updateButtons() {
        let active = ["queued", "running"].contains(job["state"] as? String ?? "")
        let matchesSelection = jobID != nil && job["id"] as? String == jobID
        cancelButton?.isEnabled = matchesSelection && active && !commandRunning && !(job["cancel_requested"] as? Bool ?? false)
        retryButton?.isEnabled = matchesSelection && !active && !job.isEmpty && !commandRunning
        reportButton?.isEnabled = (job["report"] as? String).map { FileManager.default.fileExists(atPath: $0) } ?? false
        folderButton?.isEnabled = (job["library"] as? String).map { !$0.isEmpty } ?? false
    }

    func showError(_ text: String) {
        banner.textColor = .systemOrange
        banner.stringValue = text + " 背景下載不受影響，視窗會自動重試。"
    }

    func stateText(_ value: String) -> String {
        ["queued": "等候中", "running": "下載中", "pending": "等待中", "downloaded": "已下載", "skipped": "已跳過",
         "completed": "完成", "partial": "部分完成", "failed": "失敗", "cancelled": "已取消"][value] ?? value
    }

    func itemKey(_ item: [String: Any]) -> String {
        "\(item["position"] ?? "")|\(item["video_id"] ?? "")"
    }

    func updateVisibleItems() {
        let selectedKey = visibleItems.indices.contains(table.selectedRow) ? itemKey(visibleItems[table.selectedRow]) : nil
        let scrollPosition = tableScroll.contentView.bounds.origin
        let query = searchField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let filtered = items.filter { item in
            if failedOnlyButton.state == .on && item["state"] as? String != "failed" { return false }
            if query.isEmpty { return true }
            let text = ["title", "category", "reason", "error", "video_id"].compactMap { item[$0] as? String }.joined(separator: " ")
            return text.localizedCaseInsensitiveContains(query)
        }
        filteredCount.stringValue = filtered.count == items.count ? "\(items.count) 首" : "\(filtered.count) / \(items.count) 首"
        let sameOrder = visibleItems.map(itemKey) == filtered.map(itemKey)
        var changed = IndexSet()
        if sameOrder {
            for index in filtered.indices where !NSDictionary(dictionary: filtered[index]).isEqual(to: visibleItems[index]) {
                changed.insert(index)
            }
        }
        visibleItems = filtered
        if sameOrder {
            if !changed.isEmpty {
                table.reloadData(forRowIndexes: changed, columnIndexes: IndexSet(integersIn: 0..<table.numberOfColumns))
            }
        } else {
            table.reloadData()
            let selected = selectedKey.flatMap { key in visibleItems.firstIndex { itemKey($0) == key } }
                ?? visibleItems.firstIndex { $0["state"] as? String == "running" }
                ?? (visibleItems.isEmpty ? nil : 0)
            if let selected = selected { table.selectRowIndexes(IndexSet(integer: selected), byExtendingSelection: false) }
            if selectedKey != nil {
                tableScroll.contentView.scroll(to: scrollPosition)
                tableScroll.reflectScrolledClipView(tableScroll.contentView)
            } else if let selected = selected {
                table.scrollRowToVisible(selected)
            }
        }
        tableViewSelectionDidChange(Notification(name: NSTableView.selectionDidChangeNotification))
    }

    @objc func filterChanged(_ sender: Any?) { updateVisibleItems() }
    func controlTextDidChange(_ obj: Notification) {
        if let field = obj.object as? NSTextField, field === retryInput { validateLegacyRetryInput() }
        else { updateVisibleItems() }
    }

    func numberOfRows(in tableView: NSTableView) -> Int { visibleItems.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard visibleItems.indices.contains(row), let key = tableColumn?.identifier.rawValue else { return nil }
        let item = visibleItems[row]
        var value = item[key].map { String(describing: $0) } ?? ""
        if key == "state" { value = stateText(value) }
        let text = NSTextField(labelWithString: value)
        text.font = .systemFont(ofSize: 13)
        text.lineBreakMode = .byTruncatingTail
        text.toolTip = value
        if key == "state" {
            let state = item["state"] as? String ?? ""
            let tint: NSColor = state == "failed" ? .systemRed : (state == "downloaded" ? .systemGreen : (state == "running" ? .controlAccentColor : .secondaryLabelColor))
            text.textColor = tint
            text.font = .systemFont(ofSize: 12, weight: .semibold)
            text.alignment = .center
            text.wantsLayer = true
            text.layer?.cornerRadius = 5
            text.layer?.masksToBounds = true
            text.drawsBackground = true
            text.backgroundColor = tint.withAlphaComponent(0.12)
        }
        let cell = NSTableCellView()
        text.translatesAutoresizingMaskIntoConstraints = false
        cell.addSubview(text)
        NSLayoutConstraint.activate([
            text.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 4),
            text.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -4),
            text.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
            text.heightAnchor.constraint(equalToConstant: key == "state" ? 22 : 19)
        ])
        return cell
    }
    func tableViewSelectionDidChange(_ notification: Notification) {
        guard visibleItems.indices.contains(table.selectedRow) else {
            if items.isEmpty, let error = job["error"] as? String, !error.isEmpty {
                details.string = "任務錯誤：\n" + error
            } else {
                details.string = visibleItems.isEmpty && !items.isEmpty ? "沒有符合條件的歌曲。可清除搜尋或取消「只看失敗」。" : "選擇歌曲查看完整標題、分類原因及位置；按兩下可在 Finder 顯示既有檔案。"
            }
            return
        }
        let item = visibleItems[table.selectedRow]
        let parts = [item["title"] as? String, (item["category"] as? String).map { "分類：\($0)" }, item["reason"] as? String, item["error"] as? String, item["path"] as? String]
        let text = parts.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: "\n")
        if details.string != text { details.string = text; details.scrollToBeginningOfDocument(nil) }
    }

    @objc func revealSelectedFile(_ sender: Any?) {
        guard visibleItems.indices.contains(table.selectedRow),
              let path = visibleItems[table.selectedRow]["path"] as? String, FileManager.default.fileExists(atPath: path) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    @objc func selectJob(_ sender: Any?) {
        guard let id = picker.selectedItem?.representedObject as? String else { return }
        jobID = id
        job = [:]
        items = []
        visibleItems = []
        table.reloadData()
        table.deselectAll(nil)
        phase.stringValue = "正在讀取選取任務…"
        trackText.stringValue = "目前歌曲：—"
        details.string = " "
        updateButtons()
        refresh()
    }
    @objc func refreshClick(_ sender: Any?) { refresh() }
    @objc func cancelJob(_ sender: Any?) {
        guard cancelButton.isEnabled, cancelAlert == nil, let requestedID = jobID else { return }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "要取消這個下載任務嗎？"
        alert.informativeText = "已完成的歌曲會保留。若只是想收起視窗，請選「繼續下載」，再關閉進度視窗。"
        alert.addButton(withTitle: "繼續下載")
        alert.addButton(withTitle: "取消任務")
        alert.buttons[1].contentTintColor = .systemRed
        cancelAlert = alert
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            self.cancelAlert = nil
            if response == .alertSecondButtonReturn, self.jobID == requestedID, self.cancelButton.isEnabled {
                self.command("cancel")
            }
        }
    }
    @objc func retryJob(_ sender: Any?) {
        if job["mode"] as? String == "playlist", numeric(job["playlist_limit"]) == nil,
           let url = job["url"] as? String,
           URLComponents(string: url)?.queryItems?.contains(where: { $0.name == "list" && ($0.value ?? "").hasPrefix("RD") }) == true {
            showLegacyMixRetry()
            return
        }
        command("retry")
    }
    func showLegacyMixRetry() {
        guard retryAlert == nil, let requestedID = jobID, retryButton.isEnabled else { return }
        let alert = NSAlert()
        alert.messageText = "重試這個 Mix：要下載前幾首？"
        alert.informativeText = "輸入 1–500 首。這會保留原任務與分類設定，已完成的歌曲會跳過。"
        alert.addButton(withTitle: "取消")
        alert.addButton(withTitle: "加入重試")
        alert.buttons[0].keyEquivalent = "\u{1b}"
        alert.buttons[1].keyEquivalent = "\r"
        let accessory = NSView(frame: NSRect(x: 0, y: 0, width: 360, height: 76))
        let input = NSTextField(frame: NSRect(x: 0, y: 39, width: 360, height: 29))
        input.stringValue = "50"
        input.font = .systemFont(ofSize: 16)
        input.delegate = self
        input.target = self
        input.action = #selector(legacyRetryCountChanged(_:))
        let validation = label("1–500 首；按取消不會開始下載。", size: 12)
        validation.frame = NSRect(x: 0, y: 0, width: 360, height: 30)
        accessory.addSubview(input)
        accessory.addSubview(validation)
        alert.accessoryView = accessory
        retryAlert = alert
        retryInput = input
        retryValidation = validation
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            let count = self.retryInput.flatMap { mixRetryCount($0.stringValue) }
            self.retryAlert = nil
            self.retryInput = nil
            self.retryValidation = nil
            if response == .alertSecondButtonReturn, let count = count, self.jobID == requestedID,
               self.job["id"] as? String == requestedID {
                self.command("retry", extra: ["--playlist-limit", String(count)])
            }
        }
        alert.window.makeFirstResponder(input)
        input.selectText(nil)
    }
    @objc func legacyRetryCountChanged(_ sender: Any?) { validateLegacyRetryInput() }
    func validateLegacyRetryInput() {
        let valid = retryInput.flatMap { mixRetryCount($0.stringValue) } != nil
        retryAlert?.buttons.last?.isEnabled = valid
        retryValidation?.stringValue = valid ? "1–500 首；按取消不會開始下載。" : "請輸入 1 到 500 之間的整數。"
        retryValidation?.textColor = valid ? .secondaryLabelColor : .systemRed
    }
    func command(_ name: String, extra: [String] = []) {
        guard let id = jobID, !commandRunning else { return }
        commandRunning = true
        updateButtons()
        backend([name, id] + extra) { [weak self] result in
            guard let self = self else { return }
            self.commandRunning = false
            switch result {
            case .success: self.banner.stringValue = name == "cancel" ? "已送出取消要求；已完成的歌曲會保留。" : "已加入重試佇列。"
            case .failure(let error): self.showError(error.message)
            }
            self.updateButtons()
            self.refresh()
        }
    }
    @objc func openReport(_ sender: Any?) {
        if let path = job["report"] as? String { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
    }
    @objc func openLibrary(_ sender: Any?) {
        if let path = job["library"] as? String { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
    }
    @objc func closeWindow(_ sender: Any?) { window.close() }
    func windowWillClose(_ notification: Notification) {
        timer?.invalidate()
        exerciseClosed?()
    }
}

// Internal, isolated control exercise. It cannot target the user's real library.
struct ExerciseConfiguration {
    let home: URL
    let result: URL
    let screenshot: URL
}

func exerciseConfiguration(_ arguments: [String]) throws -> ExerciseConfiguration {
    func rejected() -> NSError {
        NSError(domain: "MusicDownloaderUIFixture", code: 2,
                userInfo: [NSLocalizedDescriptionKey: "UI exercise requires the isolated work fixture and explicit environment marker."])
    }
    guard ProcessInfo.processInfo.environment["MUSIC_DOWNLOADER_UI_EXERCISE"] == "1",
          let homePath = option("--home", in: arguments), homePath.hasPrefix("/"),
          let enginePath = option("--engine", in: arguments), enginePath.hasPrefix("/"),
          let resultPath = option("--exercise-result", in: arguments), resultPath.hasPrefix("/"),
          let screenshotPath = option("--exercise-screenshot", in: arguments), screenshotPath.hasPrefix("/") else { throw rejected() }
    let home = URL(fileURLWithPath: homePath).standardizedFileURL.resolvingSymlinksInPath()
    let production = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MusicDownloader").resolvingSymlinksInPath()
    guard home.pathComponents.contains("work"), home.lastPathComponent == "fixture-home",
          home.path != production.path, !home.path.hasPrefix(production.path + "/") else { throw rejected() }
    let engine = URL(fileURLWithPath: enginePath).standardizedFileURL.resolvingSymlinksInPath()
    guard engine == home.appendingPathComponent("fixture_backend.py"),
          let source = try? String(contentsOf: engine, encoding: .utf8),
          source.components(separatedBy: .newlines).first?.contains("MusicDownloaderUIFixture") == true,
          let bytes = try? Data(contentsOf: home.appendingPathComponent(".musicdownloader-ui-fixture.json")),
          let sentinel = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
          sentinel["kind"] as? String == "MusicDownloaderUIFixture", sentinel["version"] as? Int == 1 else { throw rejected() }
    let result = URL(fileURLWithPath: resultPath).standardizedFileURL.resolvingSymlinksInPath()
    let screenshot = URL(fileURLWithPath: screenshotPath).standardizedFileURL.resolvingSymlinksInPath()
    guard result.path.hasPrefix(home.path + "/"), screenshot.path.hasPrefix(home.path + "/"),
          result.pathExtension == "json", screenshot.pathExtension == "png" else { throw rejected() }
    return ExerciseConfiguration(home: home, result: result, screenshot: screenshot)
}

final class UIExercise {
    let configuration: ExerciseConfiguration
    var events: [[String: Any]] = []
    var selectedKey = ""
    var scrollPosition = NSPoint.zero
    var ended = false

    init(_ configuration: ExerciseConfiguration) { self.configuration = configuration }

    @discardableResult func record(_ name: String, _ passed: Bool, _ detail: String = "") -> Bool {
        events.append(["name": name, "passed": passed, "detail": detail])
        return passed
    }
    func report(error: String? = nil) {
        var result: [String: Any] = ["ok": error == nil && events.allSatisfy { $0["passed"] as? Bool == true }, "events": events]
        if let error = error { result["error"] = error }
        if let bytes = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
            try? bytes.write(to: configuration.result, options: .atomic)
        }
    }
    func fail(_ reason: String) {
        guard !ended else { return }
        ended = true
        report(error: reason)
        emitJSON(["ok": false, "error": reason, "events": events])
        NSApp.terminate(nil)
    }
    func later(_ delay: Double = 0.2, _ block: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: block)
    }
    func capture(_ window: NSWindow, suffix: String = "") {
        let target = suffix.isEmpty ? configuration.screenshot : configuration.screenshot.deletingPathExtension().appendingPathExtension(suffix + ".png")
        do { try snapshot(window, to: target.path); record("snapshot" + suffix, true, target.path) }
        catch { record("snapshot" + suffix, false, error.localizedDescription) }
    }

    func dialog(_ controller: DialogController, arguments: [String]) {
        later {
            let cancelled = arguments.contains("--exercise-cancel")
            let expected = option("--exercise-value", in: arguments) ?? "中文 空白 URL"
            let row = Int(option("--exercise-choice", in: arguments) ?? "2") ?? 2
            controller.exerciseCompletion = { [weak self] value, didCancel in
                guard let self = self else { return }
                self.record("dialog_control_action", didCancel == cancelled && (cancelled || controller.kind == "message" || value == (controller.kind == "choose" ? controller.choices[row] : expected)))
                self.report()
            }
            if controller.kind == "ask" {
                controller.input.stringValue = expected
                self.record("dialog_input", controller.input.stringValue == expected)
            } else if controller.kind == "choose", !cancelled {
                guard controller.choices.indices.contains(row) else { self.fail("Fixture choice index is invalid."); return }
                controller.table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
                self.record("dialog_selection", controller.table.selectedRow == row)
            }
            self.capture(controller.window)
            if cancelled { controller.cancelButton?.performClick(nil) }
            else { controller.acceptButton.performClick(nil) }
        }
    }

    func progress(_ controller: ProgressController, attempts: Int = 0) {
        guard !ended else { return }
        guard controller.job["id"] as? String == "fixture-running", controller.visibleItems.count == 30 else {
            if attempts >= 80 { fail("Timed out waiting for the fixture job.") }
            else { later(0.1) { self.progress(controller, attempts: attempts + 1) } }
            return
        }
        record("fixture_loaded", true)
        record("bar_model_values", abs(controller.overallBar.doubleValue - 40) < 0.01 && abs(controller.trackBar.doubleValue - 37.2) < 0.01,
               "overall=\(controller.overallBar.doubleValue), track=\(controller.trackBar.doubleValue), indeterminate=\(controller.overallBar.isIndeterminate)/\(controller.trackBar.isIndeterminate)")
        record("mix_count_validator", mixRetryCount("1") == 1 && mixRetryCount("500") == 500 && mixRetryCount(" 25 ") == 25 && ["0", "501", "-1", "1.5", "abc"].allSatisfy { mixRetryCount($0) == nil })
        let actual = controller.job
        var nearlyDone = actual
        nearlyDone["total"] = 1000
        nearlyDone["completed_items"] = 996
        nearlyDone["overall_percent"] = 99.6
        controller.apply(nearlyDone)
        record("no_early_100_percent", controller.overallText.stringValue.contains("99%") && !controller.overallText.stringValue.contains("100%"))
        controller.apply(actual)
        let original = controller.window.frame
        controller.window.setFrame(NSRect(origin: original.origin, size: controller.window.minSize), display: true)
        controller.window.contentView?.layoutSubtreeIfNeeded()
        let buttons = [controller.cancelButton!, controller.retryButton!, controller.reportButton!, controller.folderButton!, controller.refreshButton!, controller.closeButton!]
        let bounds = controller.window.contentView!.bounds
        record("minimum_controls_visible", buttons.allSatisfy { bounds.contains(controller.window.contentView!.convert($0.bounds, from: $0)) })
        capture(controller.window, suffix: "minimum")
        controller.window.setFrame(original, display: true)
        controller.table.selectRowIndexes(IndexSet(integer: 20), byExtendingSelection: false)
        controller.table.scrollRowToVisible(20)
        selectedKey = controller.itemKey(controller.visibleItems[20])
        scrollPosition = controller.tableScroll.contentView.bounds.origin
        controller.refreshButton.performClick(nil)
        later(0.8) { self.progressFilters(controller) }
    }

    func send(_ field: NSControl) { if let action = field.action { _ = field.sendAction(action, to: field.target) } }

    func progressFilters(_ controller: ProgressController) {
        let row = controller.table.selectedRow
        record("refresh_preserves_selection", controller.visibleItems.indices.contains(row) && controller.itemKey(controller.visibleItems[row]) == selectedKey,
               "row before=20 after=\(row), key=\(selectedKey)")
        record("refresh_preserves_scroll", abs(controller.tableScroll.contentView.bounds.origin.y - scrollPosition.y) < 1,
               "y before=\(scrollPosition.y) after=\(controller.tableScroll.contentView.bounds.origin.y)")
        controller.searchField.stringValue = "鋼琴"
        send(controller.searchField)
        record("search_filters", controller.visibleItems.count == 16, "\(controller.visibleItems.count) rows")
        controller.searchField.stringValue = ""
        send(controller.searchField)
        controller.failedOnlyButton.performClick(nil)
        record("failed_filter", controller.visibleItems.count == 1 && controller.visibleItems.first?["state"] as? String == "failed")
        capture(controller.window, suffix: "failed-filter")
        controller.failedOnlyButton.performClick(nil)
        record("clear_filter", controller.visibleItems.count == 30)
        guard let second = controller.picker.itemArray.first(where: { $0.representedObject as? String == "fixture-failed" }) else { fail("Missing second fixture job."); return }
        controller.picker.select(second)
        send(controller.picker)
        later(0.9) { self.progressSecondJob(controller) }
    }

    func progressSecondJob(_ controller: ProgressController) {
        record("switch_job", controller.job["id"] as? String == "fixture-failed" && controller.visibleItems.count == 6)
        record("terminal_failure_visible", controller.phase.stringValue.contains("失敗") && controller.retryButton.isEnabled && !controller.cancelButton.isEnabled)
        capture(controller.window, suffix: "terminal")
        guard let first = controller.picker.itemArray.first(where: { $0.representedObject as? String == "fixture-running" }) else { fail("Missing active fixture job."); return }
        controller.picker.select(first)
        send(controller.picker)
        later(0.9) {
            self.record("switch_back", controller.job["id"] as? String == "fixture-running")
            controller.cancelButton.performClick(nil)
            self.later(0.25) {
                guard let alert = controller.cancelAlert, alert.buttons.first?.title == "繼續下載" else { self.fail("Cancellation confirmation was not shown."); return }
                self.record("cancel_confirmation", true)
                alert.buttons[0].performClick(nil)
                self.later(0.25) {
                    self.record("keep_downloading", controller.cancelAlert == nil && controller.cancelButton.isEnabled)
                    self.capture(controller.window)
                    controller.exerciseClosed = {
                        self.record("close_stops_only_viewer_timer", controller.timer?.isValid == false)
                        self.report()
                        emitJSON(["ok": self.events.allSatisfy { $0["passed"] as? Bool == true }, "events": self.events])
                    }
                    controller.closeButton.performClick(nil)
                }
            }
        }
    }

    func legacyRetry(_ controller: ProgressController, attempts: Int = 0) {
        guard !ended else { return }
        guard controller.job["id"] as? String == "fixture-legacy-mix", controller.retryButton.isEnabled else {
            if attempts >= 80 { fail("Timed out waiting for the legacy Mix fixture.") }
            else { later(0.1) { self.legacyRetry(controller, attempts: attempts + 1) } }
            return
        }
        record("legacy_mix_loaded", true)
        controller.retryButton.performClick(nil)
        later {
            guard let alert = controller.retryAlert else { self.fail("Missing legacy Mix count sheet."); return }
            self.record("legacy_default_50", controller.retryInput?.stringValue == "50")
            alert.buttons[0].performClick(nil)
            self.later {
                self.record("legacy_cancel_dismisses", controller.retryAlert == nil && !controller.commandRunning)
                controller.retryButton.performClick(nil)
                self.later {
                    guard let alert = controller.retryAlert, let input = controller.retryInput else { self.fail("Cannot reopen legacy Mix count sheet."); return }
                    for value in ["0", "501"] {
                        input.stringValue = value
                        self.send(input)
                        self.record("legacy_reject_" + value, alert.buttons[1].isEnabled == false && controller.retryValidation?.stringValue.contains("1 到 500") == true)
                    }
                    self.capture(alert.window, suffix: "count-invalid")
                    input.stringValue = "25"
                    self.send(input)
                    self.record("legacy_accept_25", alert.buttons[1].isEnabled && mixRetryCount(input.stringValue) == 25)
                    self.capture(alert.window, suffix: "count-valid")
                    alert.buttons[1].performClick(nil)
                    self.later(0.8) {
                        self.record("legacy_retry_same_job", controller.jobID == "fixture-legacy-mix" && controller.retryAlert == nil && !controller.commandRunning)
                        self.capture(controller.window)
                        controller.exerciseClosed = {
                            self.record("legacy_viewer_close", controller.timer?.isValid == false)
                            self.report()
                            emitJSON(["ok": self.events.allSatisfy { $0["passed"] as? Bool == true }, "events": self.events])
                        }
                        controller.closeButton.performClick(nil)
                    }
                }
            }
        }
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
if arguments.first == "--self-test" {
    emitJSON(["ok": true, "modes": ["dialog", "progress"], "protocol": 1])
    exit(0)
}
var exerciseConfig: ExerciseConfiguration?
if arguments.contains("--exercise-ui") {
    do { exerciseConfig = try exerciseConfiguration(arguments) }
    catch { emitJSON(["ok": false, "error": error.localizedDescription]); exit(2) }
}
let app = NSApplication.shared
let applicationDelegate = ApplicationDelegate()
app.delegate = applicationDelegate
app.setActivationPolicy(.accessory)
configureEditingMenu(app)
var retainedController: AnyObject?
var primaryWindow: NSWindow?
var retainedExercise: UIExercise?
if arguments.first == "dialog" {
    let bytes = FileHandle.standardInput.readDataToEndOfFile()
    guard let request = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
          let kind = request["kind"] as? String, ["ask", "choose", "message"].contains(kind) else {
        emitJSON(["value": "", "cancelled": false, "error": "視窗要求格式不正確。"])
        exit(2)
    }
    let controller = DialogController(request: request)
    retainedController = controller
    primaryWindow = controller.window
    controller.show()
    if let config = exerciseConfig {
        let exercise = UIExercise(config)
        retainedExercise = exercise
        exercise.dialog(controller, arguments: arguments)
    }
} else if arguments.first == "progress", let home = option("--home", in: arguments),
          let python = option("--python", in: arguments), let engine = option("--engine", in: arguments) {
    let controller = ProgressController(home: home, python: python, engine: engine,
                                        jobID: option("--job", in: arguments))
    retainedController = controller
    primaryWindow = controller.window
    controller.show()
    if let config = exerciseConfig {
        let exercise = UIExercise(config)
        retainedExercise = exercise
        if arguments.contains("--exercise-legacy-retry") { exercise.legacyRetry(controller) }
        else { exercise.progress(controller) }
    }
} else {
    emitJSON(["error": "Usage: MusicDownloaderUI dialog | progress --home PATH --python PATH --engine PATH [--job ID]"])
    exit(2)
}
if let path = option("--snapshot", in: arguments) {
    if arguments.contains("--snapshot-minimum"), let window = primaryWindow {
        window.setFrame(NSRect(origin: window.frame.origin, size: window.minSize), display: true)
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
        do {
            if let window = primaryWindow { try snapshot(window, to: path) }
            if let dialog = retainedController as? DialogController { dialog.finish(cancelled: true) }
            else { emitJSON(["snapshot": path]); NSApp.terminate(nil) }
        } catch {
            emitJSON(["error": "Unable to render snapshot."])
            NSApp.terminate(nil)
        }
    }
}
app.run()
