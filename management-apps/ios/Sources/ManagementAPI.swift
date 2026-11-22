import Combine
import CryptoKit
import DeviceCheck
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
    let count: Int
    let page: Int
    let pages: Int
}

enum ManagementOrderFilter: String, CaseIterable {
    case active, all, new, preparing, ready, completed, cancelled
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

private struct AttestationSession: Decodable {
    let csrfToken: String
    let attestationSession: String
}

private struct AppAttestChallenge: Decodable {
    let challengeId: String
    let challenge: String

    func decoded() throws -> Data {
        guard let data = Data(base64Encoded: challenge), data.count == 32 else {
            throw ManagementAPIError(statusCode: 0, message: "Invalid App Attest challenge.")
        }
        return data
    }
}

private struct AppAttestChallengeRequest: Encodable {
    let purpose: String
    let requestHash: String?
}

private struct AppAttestRegistration: Encodable {
    let keyId: String
    let challengeId: String
    let attestationObject: String
}

private struct AppAttestRegistrationResult: Decodable {
    let registered: Bool
}

struct ManagementAPI {
    let baseURL: URL

    init() {
        let configured = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String
        baseURL = URL(string: configured ?? "http://localhost:8000/")!
    }

    func orderUpdatesRequest(token: String) throws -> URLRequest {
        let configured = Bundle.main.object(forInfoDictionaryKey: "TS_WS_BACKEND_URL") as? String
            ?? "ws://localhost:8002/"
        guard let websocketBaseURL = URL(string: configured),
              let url = URL(string: "management/", relativeTo: websocketBaseURL)?.absoluteURL,
              let scheme = baseURL.scheme,
              let host = baseURL.host else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let port = baseURL.port.map { ":\($0)" } ?? ""
        request.setValue("\(scheme)://\(host)\(port)", forHTTPHeaderField: "Origin")
        return request
    }

    func signIn(email: String, password: String) async throws -> AccessTokens {
        try await authenticate(
            operation: "token",
            body: Credentials(email: email, password: password)
        )
    }

    func refresh(_ refreshToken: String) async throws -> AccessTokens {
        try await authenticate(
            operation: "refresh",
            body: RefreshRequest(refresh: refreshToken)
        )
    }

    private var appAttestRequired: Bool {
        let value = Bundle.main.object(forInfoDictionaryKey: "APP_ATTEST_REQUIRED")
        return (value as? Bool)
            ?? ((value as? String).map { ["yes", "true", "1"].contains($0.lowercased()) } ?? false)
    }

    private func authenticate<Body: Encodable>(
        operation: String,
        body: Body
    ) async throws -> AccessTokens {
        let bodyData = try encode(body)
        guard appAttestRequired else {
            var request = makeRequest("api/v1/auth/\(operation)/", method: "POST")
            request.httpBody = bodyData
            return try await send(request)
        }
        guard baseURL.scheme?.lowercased() == "https",
              let host = baseURL.host, !host.isEmpty, baseURL.user == nil,
              let configured = Bundle.main.object(forInfoDictionaryKey: "APP_REGISTRATION_ID") as? String,
              let uuid = UUID(uuidString: configured),
              uuid.uuidString.lowercased() == configured.lowercased() else {
            throw ManagementAPIError(
                statusCode: 0,
                message: "App Attest authentication requires HTTPS and a valid app registration UUID."
            )
        }
        let registrationID = uuid.uuidString.lowercased()
        var sessionRequest = makeRequest("api/v1/customer/session/")
        sessionRequest.setValue(registrationID, forHTTPHeaderField: "X-App-Registration-ID")
        let session: AttestationSession = try await send(sessionRequest)
        guard !session.csrfToken.isEmpty, !session.attestationSession.isEmpty else {
            throw ManagementAPIError(statusCode: 0, message: "The attestation session is unavailable.")
        }
        let service = DCAppAttestService.shared
        guard service.isSupported else {
            throw ManagementAPIError(statusCode: 0, message: "This device does not support App Attest.")
        }
        let cacheScope = try encode([baseURL.absoluteString, registrationID, session.attestationSession])
        let storageKey = "management.app-attest-key." + hex(Data(SHA256.hash(data: cacheScope)))
        let key = try await appAttestKey(
            service: service, storageKey: storageKey, session: session, registrationID: registrationID
        )
        let bodyHash = Data(SHA256.hash(data: bodyData))
        let challenge: AppAttestChallenge = try await attestationPost(
            "api/v1/official/app-attest/challenges/",
            body: AppAttestChallengeRequest(purpose: "assertion", requestHash: hex(bodyHash)),
            session: session,
            registrationID: registrationID
        )
        var clientData = Data("POST\nmanagement\n\(registrationID)\n\(operation)\n".utf8)
        clientData.append(try challenge.decoded())
        clientData.append(bodyHash)
        let clientDataHash = Data(SHA256.hash(data: clientData))
        try Task.checkCancellation()
        let assertion: Data
        do {
            assertion = try await withCheckedThrowingContinuation { continuation in
                service.generateAssertion(key, clientDataHash: clientDataHash) { value, error in
                    if let error {
                        continuation.resume(throwing: error)
                    } else if let value {
                        continuation.resume(returning: value)
                    } else {
                        continuation.resume(throwing: URLError(.badServerResponse))
                    }
                }
            }
        } catch {
            UserDefaults.standard.removeObject(forKey: storageKey)
            throw error
        }
        var request = attestationRequest(
            "api/v1/official/management/ios/auth/\(operation)/",
            session: session,
            registrationID: registrationID
        )
        request.httpBody = bodyData
        request.setValue(key, forHTTPHeaderField: "X-App-Attest-Key-ID")
        request.setValue(challenge.challengeId, forHTTPHeaderField: "X-App-Attest-Challenge-ID")
        request.setValue(assertion.base64EncodedString(), forHTTPHeaderField: "X-App-Attest-Assertion")
        return try await send(request)
    }

    private func appAttestKey(
        service: DCAppAttestService,
        storageKey: String,
        session: AttestationSession,
        registrationID: String
    ) async throws -> String {
        if let key = UserDefaults.standard.string(forKey: storageKey) {
            return key
        }
        try Task.checkCancellation()
        let key: String = try await withCheckedThrowingContinuation { continuation in
            service.generateKey { value, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let value {
                    continuation.resume(returning: value)
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
        }
        let challenge: AppAttestChallenge = try await attestationPost(
            "api/v1/official/app-attest/challenges/",
            body: AppAttestChallengeRequest(purpose: "attestation", requestHash: nil),
            session: session,
            registrationID: registrationID
        )
        let clientDataHash = Data(SHA256.hash(data: try challenge.decoded()))
        try Task.checkCancellation()
        let object: Data = try await withCheckedThrowingContinuation { continuation in
            service.attestKey(key, clientDataHash: clientDataHash) { value, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let value {
                    continuation.resume(returning: value)
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
        }
        let result: AppAttestRegistrationResult = try await attestationPost(
            "api/v1/official/app-attest/keys/",
            body: AppAttestRegistration(
                keyId: key,
                challengeId: challenge.challengeId,
                attestationObject: object.base64EncodedString()
            ),
            session: session,
            registrationID: registrationID
        )
        guard result.registered else {
            throw ManagementAPIError(statusCode: 0, message: "The server did not register the App Attest key.")
        }
        UserDefaults.standard.set(key, forKey: storageKey)
        return key
    }

    private func attestationPost<Body: Encodable, Value: Decodable>(
        _ path: String,
        body: Body,
        session: AttestationSession,
        registrationID: String
    ) async throws -> Value {
        var request = attestationRequest(path, session: session, registrationID: registrationID)
        request.httpBody = try encode(body)
        return try await send(request)
    }

    private func attestationRequest(
        _ path: String,
        session: AttestationSession,
        registrationID: String
    ) -> URLRequest {
        var request = makeRequest(path, method: "POST")
        request.setValue(session.csrfToken, forHTTPHeaderField: "X-CSRFToken")
        request.setValue(registrationID, forHTTPHeaderField: "X-App-Registration-ID")
        let port = baseURL.port.map { ":\($0)" } ?? ""
        request.setValue("https://\(baseURL.host!)\(port)", forHTTPHeaderField: "Origin")
        return request
    }

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02x", $0) }.joined()
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

    func deleteMenu(for appid: String, menuID: Int, token: String) async throws {
        let _: EmptyResponse = try await request(
            "api/v1/management/restaurants/\(appid)/menus/\(menuID)/",
            method: "DELETE",
            body: Optional<EmptyBody>.none,
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

    func orders(
        for appid: String, token: String, filter: ManagementOrderFilter, page: Int
    ) async throws -> ManagementOrderPage {
        var request = makeRequest("api/v1/management/restaurants/\(appid)/orders/")
        request.url = request.url?.appending(queryItems: [
            URLQueryItem(name: "status", value: filter.rawValue),
            URLQueryItem(name: "page", value: String(page))
        ])
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        return try await send(request)
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
        var request = makeRequest(path, method: method)
        if let body {
            request.httpBody = try encode(body)
        }
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return try await send(request)
    }

    private func encode<Body: Encodable>(_ body: Body) throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(body)
    }

    private func makeRequest(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Locale.preferredLanguages.first ?? "en", forHTTPHeaderField: "Accept-Language")
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func send<Value: Decodable>(_ request: URLRequest) async throws -> Value {
        try Task.checkCancellation()
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
    @Published private(set) var orderFilter: ManagementOrderFilter = .active
    @Published private(set) var orderPage = 1
    @Published private(set) var orderPages = 1
    @Published private(set) var orderCount = 0
    @Published private(set) var shopStatus: ManagementShopStatus?
    @Published private(set) var selectedRestaurant: ManagementRestaurant?
    @Published var errorMessage: String?
    @Published private(set) var isLoading = false

    private var refreshToken: String?
    private let api = ManagementAPI()
    private var orderUpdatesSocket: URLSessionWebSocketTask?
    private var orderUpdatesTask: Task<Void, Never>?
    private var orderPollingTask: Task<Void, Never>?
    private var orderUpdatesActive = true
    private var isRefreshingOrders = false
    private var refreshOrdersAgain = false
    private var ordersRequest = 0

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
        resetOrderSelection()
        shopStatus = nil
        await performAuthenticated { token in
            try await loadRestaurant(restaurant, token: token)
        }
        startOrderUpdates()
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

    func deleteMenu(menuID: Int) async {
        guard let restaurant = selectedRestaurant else { return }
        await performAuthenticated { token in
            try await api.deleteMenu(for: restaurant.appid, menuID: menuID, token: token)
            menuContent = nil
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
            try await loadOrders(for: restaurant, token: token)
        }
    }

    func filterOrders(_ filter: ManagementOrderFilter) async {
        guard filter != orderFilter, let restaurant = selectedRestaurant else { return }
        resetOrderSelection(filter: filter)
        await performAuthenticated { token in
            try await loadOrders(for: restaurant, token: token)
        }
    }

    func showOrderPage(_ page: Int) async {
        guard page != orderPage, (1...orderPages).contains(page),
              let restaurant = selectedRestaurant else { return }
        ordersRequest += 1
        orderPage = page
        orders = []
        await performAuthenticated { token in
            try await loadOrders(for: restaurant, token: token)
        }
    }

    private func resetOrderSelection(filter: ManagementOrderFilter = .active) {
        ordersRequest += 1
        orderFilter = filter
        orderPage = 1
        orderPages = 1
        orderCount = 0
        orders = []
    }

    func signOut() {
        stopOrderUpdates()
        accessToken = nil
        refreshToken = nil
        restaurants = []
        menus = []
        menuContent = nil
        resetOrderSelection()
        shopStatus = nil
        selectedRestaurant = nil
        errorMessage = nil
    }

    func showRestaurants() {
        stopOrderUpdates()
        selectedRestaurant = nil
        menus = []
        menuContent = nil
        resetOrderSelection()
        shopStatus = nil
    }

    func resumeOrderUpdates() {
        orderUpdatesActive = true
        startOrderUpdates()
    }

    func pauseOrderUpdates() {
        orderUpdatesActive = false
        stopOrderUpdates()
    }

    private func loadRestaurant(_ restaurant: ManagementRestaurant, token: String) async throws {
        async let loadedMenus = api.menus(for: restaurant.appid, token: token)
        async let loadedOrders: Void = loadOrders(for: restaurant, token: token)
        async let loadedShopStatus = api.shopStatus(for: restaurant.appid, token: token)
        let newMenus = try await loadedMenus
        try await loadedOrders
        let newShopStatus = try await loadedShopStatus
        guard !Task.isCancelled, selectedRestaurant?.appid == restaurant.appid else { return }
        menus = newMenus
        shopStatus = newShopStatus
    }

    private func loadOrders(for restaurant: ManagementRestaurant, token: String) async throws {
        ordersRequest += 1
        let request = ordersRequest
        let filter = orderFilter
        let page = orderPage
        let loadedOrders: ManagementOrderPage
        do {
            loadedOrders = try await api.orders(
                for: restaurant.appid, token: token, filter: filter, page: page
            )
        } catch let error as ManagementAPIError where error.statusCode == 400 && page > 1 {
            loadedOrders = try await api.orders(
                for: restaurant.appid, token: token, filter: filter, page: 1
            )
        }
        guard !Task.isCancelled, request == ordersRequest,
              selectedRestaurant?.appid == restaurant.appid,
              orderFilter == filter, orderPage == page else { return }
        orders = loadedOrders.results
        orderCount = loadedOrders.count
        orderPages = loadedOrders.pages
        orderPage = loadedOrders.page
    }

    private func startOrderUpdates() {
        stopOrderUpdates()
        guard orderUpdatesActive, let restaurant = selectedRestaurant, accessToken != nil else { return }
        orderUpdatesTask = Task { [weak self] in
            guard let self else { return }
            var retryDelay: UInt64 = 2
            while !Task.isCancelled {
                guard selectedRestaurant?.appid == restaurant.appid else { return }
                await refreshOrders(for: restaurant)
                guard !Task.isCancelled, selectedRestaurant?.appid == restaurant.appid,
                      let accessToken else { return }
                do {
                    let request = try api.orderUpdatesRequest(token: accessToken)
                    let socket = URLSession.shared.webSocketTask(with: request)
                    orderUpdatesSocket = socket
                    defer {
                        socket.cancel(with: .goingAway, reason: nil)
                        if orderUpdatesSocket === socket {
                            orderUpdatesSocket = nil
                        }
                    }
                    socket.resume()
                    try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                        socket.sendPing { error in
                            if let error {
                                continuation.resume(throwing: error)
                            } else {
                                continuation.resume(returning: ())
                            }
                        }
                    }
                    retryDelay = 2
                    await refreshOrders(for: restaurant)
                    while !Task.isCancelled {
                        let message = try await socket.receive()
                        guard case let .string(text) = message,
                              let data = text.data(using: .utf8),
                              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                              payload["event"] as? String == "orders.changed" else {
                            continue
                        }
                        await refreshOrders(for: restaurant)
                    }
                } catch {}
                guard !Task.isCancelled, selectedRestaurant?.appid == restaurant.appid else { return }
                do {
                    try await Task.sleep(for: .seconds(retryDelay))
                } catch {
                    return
                }
                retryDelay = min(retryDelay * 2, 30)
            }
        }
        orderPollingTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: .seconds(30))
                } catch {
                    return
                }
                guard let self, selectedRestaurant?.appid == restaurant.appid else { return }
                await refreshOrders(for: restaurant)
            }
        }
    }

    private func stopOrderUpdates() {
        orderUpdatesTask?.cancel()
        orderUpdatesTask = nil
        orderPollingTask?.cancel()
        orderPollingTask = nil
        orderUpdatesSocket?.cancel(with: .goingAway, reason: nil)
        orderUpdatesSocket = nil
    }

    private func refreshOrders(for restaurant: ManagementRestaurant) async {
        guard selectedRestaurant?.appid == restaurant.appid else { return }
        refreshOrdersAgain = true
        guard !isRefreshingOrders else { return }
        isRefreshingOrders = true
        defer { isRefreshingOrders = false }
        repeat {
            refreshOrdersAgain = false
            await performAuthenticated(background: true) { token in
                try await loadOrders(for: restaurant, token: token)
            }
        } while refreshOrdersAgain && !Task.isCancelled && selectedRestaurant?.appid == restaurant.appid
    }

    private func performAuthenticated(
        background: Bool = false,
        _ operation: (String) async throws -> Void
    ) async {
        await perform(background: background) {
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

    private func perform(background: Bool = false, _ operation: () async throws -> Void) async {
        if !background {
            isLoading = true
            errorMessage = nil
        }
        defer { if !background { isLoading = false } }
        do {
            try await operation()
        } catch {
            if !Task.isCancelled && !background {
                errorMessage = error.localizedDescription
            }
        }
    }
}
