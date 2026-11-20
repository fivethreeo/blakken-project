import SwiftUI

struct ManagementView: View {
    @StateObject private var model = ManagementModel()
    @Environment(\.scenePhase) private var scenePhase
    @State private var email = "maharaja-demo@example.test"
    @State private var password = ""
    @State private var newMenuName = ""

    var body: some View {
        NavigationStack {
            Group {
                if model.accessToken == nil {
                    signIn
                } else if let restaurant = model.selectedRestaurant {
                    restaurantDetails(restaurant)
                } else {
                    restaurantList
                }
            }
            .navigationTitle(Text("management.title"))
            .toolbar {
                if model.accessToken != nil {
                    Button("management.signOut", action: model.signOut)
                }
            }
            .overlay {
                if model.isLoading {
                    ProgressView("management.loading")
                        .padding()
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            .alert("management.error", isPresented: Binding(
                get: { model.errorMessage != nil },
                set: { if !$0 { model.errorMessage = nil } }
            )) {
                Button("management.ok") { model.errorMessage = nil }
            } message: {
                Text(model.errorMessage ?? "")
            }
        }
        .onAppear {
            if scenePhase == .active { model.resumeOrderUpdates() }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.resumeOrderUpdates()
            } else {
                model.pauseOrderUpdates()
            }
        }
        .onDisappear { model.pauseOrderUpdates() }
    }

    private var signIn: some View {
        Form {
            Section {
                Image("BlakkenLogo")
                    .resizable()
                    .scaledToFit()
                    .frame(height: 140)
                    .frame(maxWidth: .infinity)
                    .accessibilityLabel(Text("management.logoDescription"))
            }
            Text("management.demoLoginHint")
            TextField("management.email", text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField("management.password", text: $password)
                .textContentType(.password)
            Button("management.signIn") {
                Task { await model.signIn(email: email, password: password) }
            }
            .disabled(email.isEmpty || password.isEmpty || model.isLoading)
        }
    }

    private var restaurantList: some View {
        List {
            if model.restaurants.isEmpty {
                ContentUnavailableView("management.emptyRestaurants", systemImage: "building.2")
            }
            ForEach(model.restaurants) { restaurant in
                Button {
                    Task { await model.select(restaurant) }
                } label: {
                    HStack {
                        VStack(alignment: .leading) {
                            Text(restaurant.name)
                            Text(roleTitle(restaurant.role))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if !restaurant.active {
                            Text("management.pending")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .disabled(model.isLoading)
            }
        }
    }

    private func restaurantDetails(_ restaurant: ManagementRestaurant) -> some View {
        List {
            Section("management.shop") {
                if let shopStatus = model.shopStatus {
                    HStack {
                        Label {
                            Text(LocalizedStringKey(
                                shopStatus.isOpen ? "management.shopOpen" : "management.shopClosed"
                            ))
                        } icon: {
                            Image(systemName: shopStatus.isOpen ? "door.left.hand.open" : "door.left.hand.closed")
                        }
                        Spacer()
                        Button(shopStatus.isOpen ? "management.closeOrdering" : "management.openOrdering") {
                            Task { await model.toggleShopStatus() }
                        }
                        .disabled(model.isLoading)
                    }
                }
            }

            Section("management.menus") {
                if model.menus.isEmpty {
                    Text("management.emptyMenus")
                        .foregroundStyle(.secondary)
                }
                ForEach(model.menus) { menu in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(menu.name)
                            NavigationLink("management.editMenu") {
                                MenuEditorView(model: model, menu: menu)
                            }
                            .font(.subheadline)
                        }
                        Spacer()
                        if menu.isDefault {
                            Text("management.defaultMenu")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            Button("management.makeDefault") {
                                Task { await model.setDefaultMenu(menu) }
                            }
                            .disabled(model.isLoading)
                        }
                    }
                }
                HStack {
                    TextField("management.newMenuName", text: $newMenuName)
                        .textInputAutocapitalization(.words)
                    Button("management.createMenu") {
                        let name = newMenuName.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !name.isEmpty else { return }
                        Task {
                            await model.createMenu(named: name)
                            newMenuName = ""
                        }
                    }
                    .disabled(newMenuName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                }
            }

            Section("management.orders") {
                Picker("management.orderFilter", selection: Binding(
                    get: { model.orderFilter },
                    set: { filter in Task { await model.filterOrders(filter) } }
                )) {
                    ForEach(ManagementOrderFilter.allCases, id: \.self) { filter in
                        Text(orderFilterTitle(filter)).tag(filter)
                    }
                }
                .pickerStyle(.menu)
                .disabled(model.isLoading)
                Text(String(format: String(localized: "management.orderCount"), model.orderCount))
                    .foregroundStyle(.secondary)
                if model.orderPages > 1 {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(String(format: String(localized: "management.orderPage"),
                                    model.orderPage, model.orderPages))
                        HStack {
                            Button("management.previousPage") {
                                Task { await model.showOrderPage(model.orderPage - 1) }
                            }
                            .disabled(model.isLoading || model.orderPage <= 1)
                            Spacer()
                            Button("management.nextPage") {
                                Task { await model.showOrderPage(model.orderPage + 1) }
                            }
                            .disabled(model.isLoading || model.orderPage >= model.orderPages)
                        }
                        .buttonStyle(.borderless)
                    }
                }
                if model.orders.isEmpty {
                    Text("management.emptyOrders")
                        .foregroundStyle(.secondary)
                }
                ForEach(model.orders) { order in
                    orderCard(order)
                }
            }
        }
        .navigationTitle(restaurant.name)
        .refreshable { await model.refresh() }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("management.restaurants") {
                    model.showRestaurants()
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("management.refresh", systemImage: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
                .disabled(model.isLoading)
            }
        }
    }

    private func orderFilterTitle(_ filter: ManagementOrderFilter) -> String {
        switch filter {
        case .active: String(localized: "management.filterActive")
        case .all: String(localized: "management.filterAll")
        case .new: String(localized: "management.filterNew")
        case .preparing: String(localized: "management.statusPreparing")
        case .ready: String(localized: "management.statusReady")
        case .completed: String(localized: "management.filterCompleted")
        case .cancelled: String(localized: "management.filterCancelled")
        }
    }

    private func orderCard(_ order: ManagementOrder) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(order.customerName)
                    .font(.headline)
                Spacer()
                Text(order.statusLabel)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 4) {
                Text("management.orderNumber")
                Text("#\(order.id)")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Text("\(order.menuName) · \(order.total) \(order.currency)")
            Text(order.phone)
                .font(.subheadline)
            if !order.note.isEmpty {
                Text(order.note)
                    .font(.subheadline)
            }
            ForEach(order.items) { item in
                Text("\(item.quantity) × \(item.name) · \(item.total) \(order.currency)")
                    .font(.subheadline)
            }
            if !order.nextStatuses.isEmpty {
                HStack {
                    ForEach(order.nextStatuses, id: \.self) { status in
                        Button(statusTitle(status)) {
                            Task { await model.updateOrder(order, to: status) }
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isLoading)
                    }
                }
            }
        }
        .padding(.vertical, 6)
    }

    private func statusTitle(_ status: String) -> String {
        switch status {
        case "new": String(localized: "management.statusNew")
        case "preparing": String(localized: "management.statusPreparing")
        case "ready": String(localized: "management.statusReady")
        case "completed": String(localized: "management.statusCompleted")
        case "cancelled": String(localized: "management.statusCancelled")
        default: status
        }
    }

    private func roleTitle(_ role: String) -> String {
        switch role {
        case "owner": String(localized: "management.roleOwner")
        case "manager": String(localized: "management.roleManager")
        case "admin": String(localized: "management.roleAdmin")
        default: role
        }
    }
}
