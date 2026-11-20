import SwiftUI

private struct OrderUpdateNotification: Decodable {
    let event: String
}

@MainActor
final class CustomerMenuModel: ObservableObject {
    @Published private(set) var menu: CustomerMenu?
    @Published private(set) var status: RestaurantStatus?
    @Published private(set) var orderReceipt: OrderReceipt?
    @Published private(set) var orderStatus: CustomerOrderStatus?
    @Published private(set) var orderStatusUnavailable = false
    @Published private(set) var liveUpdatesConnected = false
    @Published private(set) var isLoading = false
    @Published private(set) var isSubmitting = false
    @Published var errorMessage: String?
    @Published var shopStatusAlertIsOpen: Bool?
    @Published var quantities: [Int: Int] = [:]
    @Published var customerName = ""
    @Published var phone = ""
    @Published var note = ""

    private let api = CustomerAPI()
    private var pendingSubmissionID: UUID?
    private var pendingSignature: String?
    private var orderUpdatesSocket: URLSessionWebSocketTask?
    private var socketListener: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    private var reconnectDelay: UInt64 = 1_000_000_000
    private var shopUpdatesSocket: URLSessionWebSocketTask?
    private var shopSocketListener: Task<Void, Never>?
    private var shopReconnectTask: Task<Void, Never>?
    private var shopReconnectDelay: UInt64 = 1_000_000_000
    private var shopUpdatesActive = false
    private var shopStatusRequest = 0

    var cartIsEmpty: Bool { quantities.values.allSatisfy { $0 == 0 } }
    var cartCount: Int { quantities.values.reduce(0, +) }
    var cartDishes: [MenuDish] {
        (menu?.categories ?? []).flatMap(\.dishes).filter { (quantities[$0.id] ?? 0) > 0 }
    }
    var canEditOrder: Bool { status?.isOpen == true && !isSubmitting }
    var canSubmit: Bool {
        canEditOrder && !cartIsEmpty && !customerName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !phone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        shopUpdatesActive = true
        shopStatusRequest += 1
        let statusRequest = shopStatusRequest
        connectShopUpdates()
        defer { isLoading = false }
        do {
            async let loadedMenu = api.loadMenu()
            async let loadedStatus = api.loadStatus()
            menu = try await loadedMenu
            let newStatus = try await loadedStatus
            if statusRequest == shopStatusRequest {
                applyShopStatus(newStatus)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        await connectOrderUpdates()
    }

    func setQuantity(_ quantity: Int, for dishID: Int) {
        guard canEditOrder else { return }
        quantities[dishID] = min(max(quantity, 0), 99)
        if quantities[dishID] == 0 {
            quantities.removeValue(forKey: dishID)
        }
        orderReceipt = nil
        orderStatus = nil
        orderStatusUnavailable = false
    }

    func resumeLiveUpdates() async {
        shopUpdatesActive = true
        connectShopUpdates()
        await refreshShopStatus()
        await connectOrderUpdates()
        await refreshOrderStatus()
    }

    func stopShopUpdates() {
        shopUpdatesActive = false
        shopReconnectTask?.cancel()
        shopReconnectTask = nil
        shopSocketListener?.cancel()
        shopSocketListener = nil
        shopUpdatesSocket?.cancel(with: .goingAway, reason: nil)
        shopUpdatesSocket = nil
    }

    func placeOrder() async {
        guard let menu, canSubmit else { return }
        let items = quantities.keys.sorted().compactMap { dishID -> (dishID: Int, quantity: Int)? in
            guard let quantity = quantities[dishID], quantity > 0 else { return nil }
            return (dishID, quantity)
        }
        let cleanedName = customerName.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanedPhone = phone.trimmingCharacters(in: .whitespacesAndNewlines)
        let signature = "\(cleanedName)|\(cleanedPhone)|\(note)|"
            + items.map { "\($0.dishID):\($0.quantity)" }.joined(separator: ",")
        let submissionID: UUID
        if pendingSignature == signature, let existingID = pendingSubmissionID {
            submissionID = existingID
        } else {
            submissionID = UUID()
            pendingSignature = signature
            pendingSubmissionID = submissionID
        }

        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            orderReceipt = try await api.placeOrder(
                menuID: menu.id,
                submissionID: submissionID,
                customerName: cleanedName,
                phone: cleanedPhone,
                note: note.trimmingCharacters(in: .whitespacesAndNewlines),
                items: items
            )
            orderStatus = nil
            orderStatusUnavailable = false
            quantities = [:]
            pendingSubmissionID = nil
            pendingSignature = nil
            await refreshOrderStatus()
        } catch {
            errorMessage = error.localizedDescription
            await refreshShopStatus()
        }
    }

    private func refreshShopStatus() async {
        shopStatusRequest += 1
        let request = shopStatusRequest
        do {
            let newStatus = try await api.loadStatus()
            if request == shopStatusRequest {
                applyShopStatus(newStatus)
            }
        } catch {
            // Keep the last known state; the server also checks availability at checkout.
        }
    }

    private func applyShopStatus(_ newStatus: RestaurantStatus) {
        if let status, status.isOpen != newStatus.isOpen {
            shopStatusAlertIsOpen = newStatus.isOpen
        }
        status = newStatus
    }

    private func connectShopUpdates() {
        guard shopUpdatesActive, shopUpdatesSocket == nil, shopReconnectTask == nil else { return }
        do {
            let socket = try api.makeShopUpdatesSocket()
            shopUpdatesSocket = socket
            socket.resume()
            shopSocketListener = Task { [weak self] in
                do {
                    while !Task.isCancelled {
                        let message = try await socket.receive()
                        guard let self, self.shopUpdatesSocket === socket else { return }
                        guard case .string(let text) = message,
                              let data = text.data(using: .utf8),
                              let notification = try? JSONDecoder().decode(OrderUpdateNotification.self, from: data),
                              notification.event == "shop.changed" else {
                            continue
                        }
                        await self.refreshShopStatus()
                    }
                } catch {
                    guard let self, self.shopUpdatesSocket === socket else { return }
                    socket.cancel(with: .goingAway, reason: nil)
                    self.shopUpdatesSocket = nil
                    self.shopSocketListener = nil
                    self.reconnectShopUpdates()
                }
            }
            socket.sendPing { [weak self] error in
                Task { @MainActor in
                    guard let self, self.shopUpdatesSocket === socket, error == nil else { return }
                    self.shopReconnectDelay = 1_000_000_000
                    await self.refreshShopStatus()
                }
            }
        } catch {
            reconnectShopUpdates()
        }
    }

    private func reconnectShopUpdates() {
        guard shopUpdatesActive, shopReconnectTask == nil else { return }
        let delay = shopReconnectDelay
        shopReconnectDelay = min(shopReconnectDelay * 2, 15_000_000_000)
        shopReconnectTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: delay)
            } catch {
                return
            }
            guard let self else { return }
            self.shopReconnectTask = nil
            self.connectShopUpdates()
        }
    }

    private func connectOrderUpdates() async {
        guard orderUpdatesSocket == nil, reconnectTask == nil else { return }
        do {
            try await api.prepareOrderUpdates()
            let socket = try api.makeOrderUpdatesSocket()
            orderUpdatesSocket = socket
            socket.resume()
            socketListener = Task { [weak self] in
                await self?.receiveOrderUpdates(from: socket)
            }
            socket.sendPing { [weak self] error in
                Task { @MainActor in
                    guard let self, self.orderUpdatesSocket === socket else { return }
                    if error == nil {
                        self.liveUpdatesConnected = true
                        self.reconnectDelay = 1_000_000_000
                        await self.refreshOrderStatus()
                    } else {
                        self.disconnectOrderUpdates(socket)
                        self.reconnectOrderUpdates()
                    }
                }
            }
        } catch {
            liveUpdatesConnected = false
            reconnectOrderUpdates()
        }
    }

    private func receiveOrderUpdates(from socket: URLSessionWebSocketTask) async {
        do {
            while !Task.isCancelled {
                let message = try await socket.receive()
                guard orderUpdatesSocket === socket else { return }
                guard case .string(let text) = message,
                      let data = text.data(using: .utf8),
                      let notification = try? JSONDecoder().decode(OrderUpdateNotification.self, from: data),
                      notification.event == "orders.changed" else {
                    continue
                }
                await refreshOrderStatus()
            }
        } catch {
            guard orderUpdatesSocket === socket else { return }
            disconnectOrderUpdates(socket)
            reconnectOrderUpdates()
        }
    }

    private func disconnectOrderUpdates(_ socket: URLSessionWebSocketTask) {
        socket.cancel(with: .goingAway, reason: nil)
        orderUpdatesSocket = nil
        socketListener = nil
        liveUpdatesConnected = false
    }

    private func reconnectOrderUpdates() {
        guard reconnectTask == nil else { return }
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, 15_000_000_000)
        reconnectTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: delay)
            } catch {
                return
            }
            guard let self else { return }
            self.reconnectTask = nil
            await self.connectOrderUpdates()
        }
    }

    private func refreshOrderStatus() async {
        guard let orderID = orderReceipt?.order.id else { return }
        do {
            let orders = try await api.loadCustomerOrders()
            guard orderReceipt?.order.id == orderID else { return }
            orderStatus = orders.first { $0.id == orderID }
            orderStatusUnavailable = orderStatus == nil
        } catch {
            orderStatusUnavailable = true
        }
    }
}

struct CustomerMenuView: View {
    @StateObject private var model = CustomerMenuModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.menu == nil {
                    ProgressView("customer.loading")
                } else if let menu = model.menu {
                    menuContent(menu)
                } else {
                    ContentUnavailableView {
                        Label("customer.unavailable", systemImage: "wifi.exclamationmark")
                    } actions: {
                        Button("customer.retry") {
                            Task { await model.load() }
                        }
                    }
                }
            }
            .navigationTitle(model.status?.restaurant ?? String(localized: "customer.title"))
            .toolbar {
                if let status = model.status {
                    ToolbarItem(placement: .topBarLeading) {
                        Text(LocalizedStringKey(status.isOpen ? "customer.open" : "customer.closed"))
                            .font(.caption)
                            .foregroundStyle(status.isOpen ? .green : .secondary)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("customer.refresh", systemImage: "arrow.clockwise") {
                        Task { await model.load() }
                    }
                    .disabled(model.isLoading || model.isSubmitting)
                }
                ToolbarItem(placement: .bottomBar) {
                    NavigationLink {
                        CustomerCheckoutView(model: model)
                    } label: {
                        HStack {
                            Image(systemName: "cart")
                            Text("customer.checkout")
                            Text("(\(model.cartCount))")
                        }
                    }
                    .disabled(model.menu == nil)
                }
            }
            .refreshable { await model.load() }
        }
        .task { await model.load() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Task { await model.resumeLiveUpdates() }
            } else {
                model.stopShopUpdates()
            }
        }
        .onDisappear { model.stopShopUpdates() }
        .alert(LocalizedStringKey(
            model.shopStatusAlertIsOpen.map { $0 ? "customer.open" : "customer.closed" } ?? "customer.error"
        ), isPresented: Binding(
            get: { model.shopStatusAlertIsOpen != nil || model.errorMessage != nil },
            set: {
                if !$0 {
                    model.shopStatusAlertIsOpen = nil
                    model.errorMessage = nil
                }
            }
        )) {
            Button("customer.ok") {
                model.shopStatusAlertIsOpen = nil
                model.errorMessage = nil
            }
        } message: {
            if let isOpen = model.shopStatusAlertIsOpen {
                Text(LocalizedStringKey(isOpen ? "customer.shopOpenedMessage" : "customer.shopClosedMessage"))
            } else {
                Text(model.errorMessage ?? "")
            }
        }
    }

    private func menuContent(_ menu: CustomerMenu) -> some View {
        List {
            Section {
                HStack(spacing: 16) {
                    Image("BlakkenLogo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 64, height: 96)
                        .accessibilityLabel(Text("customer.brandLogoDescription"))
                    VStack(alignment: .leading) {
                        Text(menu.name).font(.title2)
                        Text(model.status?.restaurant ?? String(localized: "customer.title"))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            ForEach(menu.categories) { category in
                Section(category.name) {
                    ForEach(category.dishes) { dish in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(dish.name).font(.headline)
                                Spacer()
                                if let price = dish.price {
                                    Text("\(price) \(String(localized: "customer.currency"))")
                                        .monospacedDigit()
                                }
                                Button {
                                    model.setQuantity((model.quantities[dish.id] ?? 0) + 1, for: dish.id)
                                } label: {
                                    Image(systemName: "cart.badge.plus")
                                        .frame(minWidth: 44, minHeight: 44)
                                }
                                .buttonStyle(.borderless)
                                .accessibilityLabel(Text("customer.addToCart \(dish.name)"))
                                .disabled(!model.canEditOrder || dish.price == nil || (model.quantities[dish.id] ?? 0) >= 99)
                            }
                            if !dish.description.isEmpty {
                                Text(dish.description).foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }
}

private struct CustomerCheckoutView: View {
    @ObservedObject var model: CustomerMenuModel

    var body: some View {
        Form {
            Section("customer.cart") {
                if model.cartIsEmpty {
                    Text("customer.emptyCart")
                        .foregroundStyle(.secondary)
                }
                ForEach(model.cartDishes) { dish in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(dish.name).font(.headline)
                        if let price = dish.price {
                            Text("\(price) \(String(localized: "customer.currency"))")
                                .monospacedDigit()
                        }
                        Stepper(value: Binding(
                            get: { model.quantities[dish.id] ?? 1 },
                            set: { model.setQuantity($0, for: dish.id) }
                        ), in: 1...99) {
                            HStack {
                                Text("customer.quantity")
                                Text("\(model.quantities[dish.id] ?? 0)")
                            }
                        }
                        Button(role: .destructive) {
                            model.setQuantity(0, for: dish.id)
                        } label: {
                            Text("customer.removeFromCart \(dish.name)")
                        }
                        .buttonStyle(.borderless)
                    }
                }
            }
            .disabled(!model.canEditOrder)
            if let receipt = model.orderReceipt {
                Section("customer.confirmation") {
                    HStack {
                        Text("customer.orderNumber")
                        Text("#\(receipt.order.id)")
                    }
                    Text("\(receipt.order.total) \(receipt.order.currency)")
                }
                Section("customer.orderStatus") {
                    if let orderStatus = model.orderStatus {
                        Text(orderStatus.statusLabel)
                    } else if model.orderStatusUnavailable {
                        Text("customer.orderStatusUnavailable")
                    } else {
                        ProgressView()
                    }
                    Text(model.liveUpdatesConnected ? "customer.liveConnected" : "customer.liveReconnecting")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }

            if !model.cartIsEmpty {
                Section("customer.checkout") {
                    if model.status?.isOpen != true {
                        Text("customer.closed")
                            .foregroundStyle(.secondary)
                    }
                    TextField("customer.name", text: $model.customerName)
                        .textContentType(.name)
                        .textInputAutocapitalization(.words)
                    TextField("customer.phone", text: $model.phone)
                        .textContentType(.telephoneNumber)
                        .keyboardType(.phonePad)
                    TextField("customer.note", text: $model.note, axis: .vertical)
                        .lineLimit(2...5)
                    Button {
                        Task { await model.placeOrder() }
                    } label: {
                        if model.isSubmitting {
                            ProgressView()
                        } else {
                            Text("customer.placeOrder")
                        }
                    }
                    .disabled(!model.canSubmit)
                }
                .disabled(!model.canEditOrder)
            }
        }
        .navigationTitle(Text("customer.checkout"))
        .navigationBarBackButtonHidden(model.isSubmitting)
        .disabled(model.isSubmitting)
    }
}
