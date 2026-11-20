import SwiftUI

@MainActor
final class CustomerMenuModel: ObservableObject {
    @Published private(set) var menu: CustomerMenu?
    @Published private(set) var status: RestaurantStatus?
    @Published private(set) var orderReceipt: OrderReceipt?
    @Published private(set) var isLoading = false
    @Published private(set) var isSubmitting = false
    @Published var errorMessage: String?
    @Published var quantities: [Int: Int] = [:]
    @Published var customerName = ""
    @Published var phone = ""
    @Published var note = ""

    private let api = CustomerAPI()
    private var pendingSubmissionID: UUID?
    private var pendingSignature: String?

    var cartIsEmpty: Bool { quantities.values.allSatisfy { $0 == 0 } }
    var cartCount: Int { quantities.values.reduce(0, +) }
    var cartDishes: [MenuDish] {
        (menu?.categories ?? []).flatMap(\.dishes).filter { (quantities[$0.id] ?? 0) > 0 }
    }
    var canSubmit: Bool {
        status?.isOpen == true && !cartIsEmpty && !customerName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !phone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isSubmitting
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            async let loadedMenu = api.loadMenu()
            async let loadedStatus = api.loadStatus()
            menu = try await loadedMenu
            status = try await loadedStatus
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setQuantity(_ quantity: Int, for dishID: Int) {
        quantities[dishID] = min(max(quantity, 0), 99)
        if quantities[dishID] == 0 {
            quantities.removeValue(forKey: dishID)
        }
        orderReceipt = nil
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
            quantities = [:]
            pendingSubmissionID = nil
            pendingSignature = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct CustomerMenuView: View {
    @StateObject private var model = CustomerMenuModel()

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
            .task { await model.load() }
            .refreshable { await model.load() }
        }
        .alert("customer.error", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("customer.ok") { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? "")
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
                                .disabled(dish.price == nil || (model.quantities[dish.id] ?? 0) >= 99 || model.isSubmitting)
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
            if let receipt = model.orderReceipt {
                Section("customer.confirmation") {
                    HStack {
                        Text("customer.orderNumber")
                        Text("#\(receipt.order.id)")
                    }
                    Text("\(receipt.order.total) \(receipt.order.currency)")
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
            }
        }
        .navigationTitle(Text("customer.checkout"))
        .navigationBarBackButtonHidden(model.isSubmitting)
        .disabled(model.isSubmitting)
    }
}
