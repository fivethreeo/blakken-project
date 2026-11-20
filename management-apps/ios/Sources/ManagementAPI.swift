import Combine
import Foundation

struct ManagementRestaurant: Decodable, Identifiable {
    let name: String
    let appid: String
    let active: Bool
    let role: String

    var id: String { appid }
}

struct ManagementMenu: Decodable, Identifiable {
    let id: Int
    let name: String
    let isDefault: Bool
}

struct ManagementMenuContent: Decodable {
    let id: Int
    let name: String
    let categories: [ManagementCategory]
}

struct ManagementCategory: Decodable, Identifiable {
    let id: Int
    let name: String
    let isVisible: Bool
    let dishes: [ManagementDish]
}

struct ManagementDish: Decodable, Identifiable {
    let id: Int
    let pageId: Int
    let name: String
    let description: String
    let price: String?
    let allergens: [String]
    let isVisible: Bool
}

struct ManagementOrderPage: Decodable {
    let results: [ManagementOrder]
}

struct ManagementOrderLine: Decodable, Identifiable {
    let name: String
    let quantity: Int
    let unitPrice: String
    let total: String

    var id: String { "\(name)-\(quantity)" }
}

struct ManagementOrder: Decodable, Identifiable {
    let id: Int
    let customerName: String
    let phone: String
    let note: String
    let menuName: String
    let status: String
    let statusLabel: String
    let nextStatuses: [String]
    let total: String
    let currency: String
    let items: [ManagementOrderLine]
}

struct ManagementShopStatus: Decodable {
    let isOpen: Bool
    let message: String
}

private struct Results<Value: Decodable>: Decodable {
    let results: [Value]
}

private struct Credentials: Encodable {
    let email: String
    let password: String
}

private struct RefreshRequest: Encodable {
    let refresh: String
}

private struct MenuRequest: Encodable {
    let name: String
}

private struct CategoryRequest: Encodable {
    let name: String
}

private struct CategoryUpdateRequest: Encodable {
    let name: String
    let isVisible: Bool
}

private struct DishRequest: Encodable {
    let name: String
    let description: String
    let price: String
    let allergens: [String]
    let isVisible: Bool
}

private struct OrderStatusRequest: Encodable {
    let status: String
    let expectedStatus: String
}

private struct ShopStatusRequest: Encodable {
    let isOpen: Bool
    let expectedIsOpen: Bool
}

struct AccessTokens: Decodable {
    let access: String
    let refresh: String
}

private struct APIErrorBody: Decodable {
    let error: String
}

struct ManagementAPI {
    let baseURL: URL

    init() {
        let configured = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String
        baseURL = URL(string: configured ?? "http://localhost:8000/")!
    }

    func signIn(email: String, password: String) async throws -> AccessTokens {
        try await request(
            "api/v1/auth/token/",
            method: "POST",
            body: Credentials(email: email, password: password),
            token: nil
        )
    }

    func refresh(_ refreshToken: String) async throws -> AccessTokens {
        try await request(
            "api/v1/auth/refresh/",
            method: "POST",
            body: RefreshRequest(refresh: refreshToken),
            token: nil
        )
    }

    func restaurants(token: String) async throws -> [ManagementRestaurant] {
        let response: Results<ManagementRestaurant> = try await request(
            "api/v1/management/restaurants/", token: token
        )
        return response.results
    }

    func menus(for appid: String, token: String) async throws -> [ManagementMenu] {
        let response: Results<ManagementMenu> = try await request(
            "api/v1/management/restaurants/\(appid)/menus/", token: token
        )
        return response.results
    }

    func createMenu(for appid: String, name: String, token: String) async throws {
        let _: ManagementMenu = try await request(
            "api/v1/management/restaurants/\(appid)/menus/create/",
            method: "POST",
            body: MenuRequest(name: name),
            token: token
        )
    }

    func menuContent(for appid: String, menuID: Int, token: String) async throws -> ManagementMenuContent {
        try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/content/",
            token: token
        )
    }

    func createCategory(for appid: String, menuID: Int, name: String, token: String) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/categories/",
            method: "POST",
            body: CategoryRequest(name: name),
            token: token
        )
    }

    func updateCategory(
        for appid: String,
        menuID: Int,
        categoryID: Int,
        name: String,
        isVisible: Bool,
        token: String
    ) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/categories/\(categoryID)/",
            method: "PATCH",
            body: CategoryUpdateRequest(name: name, isVisible: isVisible),
            token: token
        )
    }

    func deleteCategory(
        for appid: String,
        menuID: Int,
        categoryID: Int,
        token: String
    ) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/categories/\(categoryID)/",
            method: "DELETE",
            body: Optional<EmptyBody>.none,
            token: token
        )
    }

    func createDish(
        for appid: String,
        menuID: Int,
        categoryID: Int,
        name: String,
        description: String,
        price: String,
        allergens: [String],
        isVisible: Bool,
        token: String
    ) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/categories/\(categoryID)/dishes/",
            method: "POST",
            body: DishRequest(
                name: name,
                description: description,
                price: price,
                allergens: allergens,
                isVisible: isVisible
            ),
            token: token
        )
    }

    func updateDish(
        for appid: String,
        menuID: Int,
        dishID: Int,
        name: String,
        description: String,
        price: String,
        allergens: [String],
        isVisible: Bool,
        token: String
    ) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/dishes/\(dishID)/",
            method: "PATCH",
            body: DishRequest(
                name: name,
                description: description,
                price: price,
                allergens: allergens,
                isVisible: isVisible
            ),
            token: token
        )
    }

    func deleteDish(for appid: String, menuID: Int, dishID: Int, token: String) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/dishes/\(dishID)/",
            method: "DELETE",
            body: Optional<EmptyBody>.none,
            token: token
        )
    }

    func setDefaultMenu(_ menu: ManagementMenu, for appid: String, token: String) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menu.id)/default/",
            method: "POST",
            body: Optional<EmptyBody>.none,
            token: token
        )
    }

    func orders(for appid: String, token: String) async throws -> [ManagementOrder] {
        let response: ManagementOrderPage = try await request(
            "api/v1/management/restaurants/\(appid)/orders/", token: token
        )
        return response.results
    }

    func updateOrder(
        _ order: ManagementOrder,
        to status: String,
        for appid: String,
        token: String
    ) async throws {
        let _: StatusResponse = try await request(
            "api/v1/management/restaurants/\(appid)/orders/\(order.id)/status/",
            method: "PATCH",
            body: OrderStatusRequest(status: status, expectedStatus: order.status),
            token: token
        )
    }

    func shopStatus(for appid: String, token: String) async throws -> ManagementShopStatus {
        try await request(
            "api/v1/management/restaurants/\(appid)/shop/", token: token
        )
    }

    func setShopStatus(
        isOpen: Bool,
        expectedIsOpen: Bool,
        for appid: String,
        token: String
    ) async throws -> ManagementShopStatus {
        try await request(
            "api/v1/management/restaurants/\(appid)/shop/",
            method: "PATCH",
            body: ShopStatusRequest(isOpen: isOpen, expectedIsOpen: expectedIsOpen),
            token: token
        )
    }

    private struct EmptyBody: Encodable {}
    private struct EmptyResponse: Decodable {}
    private struct StatusResponse: Decodable {
        let status: String
    }

    private func request<Value: Decodable>(
        _ path: String,
        token: String?
    ) async throws -> Value {
        try await request(path, method: "GET", body: Optional<EmptyBody>.none, token: token)
    }

    private func request<Value: Decodable, Body: Encodable>(
        _ path: String,
        method: String = "GET",
        body: Body?,
        token: String?
    ) async throws -> Value {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Locale.preferredLanguages.first ?? "en", forHTTPHeaderField: "Accept-Language")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            request.httpBody = try encoder.encode(body)
        }
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(response.statusCode) else {
            let message = (try? JSONDecoder().decode(APIErrorBody.self, from: data).error)
                ?? URLError(.badServerResponse).localizedDescription
            throw ManagementAPIError(statusCode: response.statusCode, message: message)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Value.self, from: data)
    }
}

struct ManagementAPIError: LocalizedError {
    let statusCode: Int
    let message: String
    var errorDescription: String? { message }
}

@MainActor
final class ManagementModel: ObservableObject {
    @Published private(set) var accessToken: String?
    @Published private(set) var restaurants: [ManagementRestaurant] = []
    @Published private(set) var menus: [ManagementMenu] = []
    @Published private(set) var menuContent: ManagementMenuContent?
    @Published private(set) var orders: [ManagementOrder] = []
    @Published private(set) var shopStatus: ManagementShopStatus?
    @Published private(set) var selectedRestaurant: ManagementRestaurant?
    @Published var errorMessage: String?
    @Published private(set) var isLoading = false

    private var refreshToken: String?
    private let api = ManagementAPI()

    func signIn(email: String, password: String) async {
        await perform {
            let tokens = try await api.signIn(email: email, password: password)
            accessToken = tokens.access
            refreshToken = tokens.refresh
            restaurants = try await api.restaurants(token: tokens.access)
        }
    }

    func select(_ restaurant: ManagementRestaurant) async {
        selectedRestaurant = restaurant
        menus = []
        menuContent = nil
        orders = []
        shopStatus = nil
        await performAuthenticated { token in
            try await loadRestaurant(restaurant, token: token)
        }
    }

    func refresh() async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await loadRestaurant(restaurant, token: token)
        }
    }

    func createMenu(named name: String) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.createMenu(for: restaurant.appid, name: name, token: token)
            try await loadRestaurant(restaurant, token: token)
        }
    }

    func loadMenuContent(menuID: Int) async {
        guard let restaurant = selectedRestaurant else { return }
        menuContent = nil
        await performAuthenticated { token in
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func createCategory(menuID: Int, name: String) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.createCategory(
                for: restaurant.appid,
                menuID: menuID,
                name: name,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func updateCategory(menuID: Int, categoryID: Int, name: String, isVisible: Bool) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.updateCategory(
                for: restaurant.appid,
                menuID: menuID,
                categoryID: categoryID,
                name: name,
                isVisible: isVisible,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func deleteCategory(menuID: Int, categoryID: Int) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.deleteCategory(
                for: restaurant.appid,
                menuID: menuID,
                categoryID: categoryID,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func createDish(
        menuID: Int,
        categoryID: Int,
        name: String,
        description: String,
        price: String,
        isVisible: Bool
    ) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.createDish(
                for: restaurant.appid,
                menuID: menuID,
                categoryID: categoryID,
                name: name,
                description: description,
                price: price,
                allergens: [],
                isVisible: isVisible,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func updateDish(
        menuID: Int,
        dishID: Int,
        name: String,
        description: String,
        price: String,
        allergens: [String],
        isVisible: Bool
    ) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.updateDish(
                for: restaurant.appid,
                menuID: menuID,
                dishID: dishID,
                name: name,
                description: description,
                price: price,
                allergens: allergens,
                isVisible: isVisible,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func deleteDish(menuID: Int, dishID: Int) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.deleteDish(
                for: restaurant.appid,
                menuID: menuID,
                dishID: dishID,
                token: token
            )
            menuContent = try await api.menuContent(
                for: restaurant.appid,
                menuID: menuID,
                token: token
            )
        }
    }

    func setDefaultMenu(_ menu: ManagementMenu) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.setDefaultMenu(menu, for: restaurant.appid, token: token)
            try await loadRestaurant(restaurant, token: token)
        }
    }

    func toggleShopStatus() async {
        guard let restaurant = selectedRestaurant, let shopStatus else { return }
        await performAuthenticated { token in
            self.shopStatus = try await api.setShopStatus(
                isOpen: !shopStatus.isOpen,
                expectedIsOpen: shopStatus.isOpen,
                for: restaurant.appid,
                token: token
            )
        }
    }

    func updateOrder(_ order: ManagementOrder, to status: String) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.updateOrder(order, to: status, for: restaurant.appid, token: token)
            orders = try await api.orders(for: restaurant.appid, token: token)
        }
    }

    func signOut() {
        accessToken = nil
        refreshToken = nil
        restaurants = []
        menus = []
        menuContent = nil
        orders = []
        shopStatus = nil
        selectedRestaurant = nil
        errorMessage = nil
    }

    func showRestaurants() {
        selectedRestaurant = nil
        menus = []
        menuContent = nil
        orders = []
        shopStatus = nil
    }

    private func loadRestaurant(_ restaurant: ManagementRestaurant, token: String) async throws {
        async let loadedMenus = api.menus(for: restaurant.appid, token: token)
        async let loadedOrders = api.orders(for: restaurant.appid, token: token)
        async let loadedShopStatus = api.shopStatus(for: restaurant.appid, token: token)
        menus = try await loadedMenus
        orders = try await loadedOrders
        shopStatus = try await loadedShopStatus
    }

    private func performAuthenticated(
        _ operation: (String) async throws -> Void
    ) async {
        await perform {
            guard let accessToken else {
                throw ManagementAPIError(statusCode: 401, message: "Authentication required.")
            }
            do {
                try await operation(accessToken)
            } catch let error as ManagementAPIError where error.statusCode == 401 {
                guard let refreshToken else {
                    signOut()
                    throw error
                }
                do {
                    let tokens = try await api.refresh(refreshToken)
                    self.accessToken = tokens.access
                    self.refreshToken = tokens.refresh
                    try await operation(tokens.access)
                } catch let refreshError as ManagementAPIError where refreshError.statusCode == 401 {
                    signOut()
                    throw refreshError
                }
            }
        }
    }

    private func perform(_ operation: () async throws -> Void) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await operation()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
