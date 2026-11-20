import Foundation

struct CustomerMenu: Decodable {
    let id: Int
    let name: String
    let categories: [MenuCategory]
}

struct MenuCategory: Decodable, Identifiable {
    let id: Int
    let name: String
    let dishes: [MenuDish]
}

struct MenuDish: Decodable, Identifiable {
    let id: Int
    let name: String
    let description: String
    let price: String?
    let allergens: [String]
}

struct RestaurantStatus: Decodable {
    let restaurant: String
    let isOpen: Bool
    let message: String
}

private struct CustomerSession: Decodable {
    let csrfToken: String
}

struct OrderReceipt: Decodable {
    let order: OrderSummary
}

struct OrderSummary: Decodable {
    let id: Int
    let total: String
    let currency: String
}

struct CustomerOrderStatus: Decodable, Identifiable {
    let id: Int
    let statusLabel: String
}

private struct CustomerOrders: Decodable {
    let results: [CustomerOrderStatus]
}

private struct APIErrorBody: Decodable {
    let error: String
}

private struct OrderRequest: Encodable {
    let submissionId: String
    let customerName: String
    let phone: String
    let note: String
    let items: [OrderLine]
}

private struct OrderLine: Encodable {
    let dishId: Int
    let quantity: Int
}

struct CustomerAPI {
    private let baseURL: URL
    private let webSocketBaseURL: URL?
    private let appid: String

    init() {
        let bundle = Bundle.main
        baseURL = URL(
            string: bundle.object(forInfoDictionaryKey: "API_BASE_URL") as? String
                ?? "http://localhost:8000/"
        )!
        webSocketBaseURL = URL(
            string: bundle.object(forInfoDictionaryKey: "TS_WS_BACKEND_URL") as? String
                ?? "ws://localhost:8002/"
        )
        appid = bundle.object(forInfoDictionaryKey: "RESTAURANT_APP_ID") as? String
            ?? "REPLACE_WITH_RESTAURANT_APP_ID"
    }

    func loadMenu() async throws -> CustomerMenu {
        try await get("api/v1/restaurants/\(appid)/menus/default/")
    }

    func loadStatus() async throws -> RestaurantStatus {
        try await get("api/v1/restaurants/\(appid)/shop-status/")
    }

    func prepareOrderUpdates() async throws {
        let _: CustomerSession = try await get("api/v1/customer/session/")
    }

    func loadCustomerOrders() async throws -> [CustomerOrderStatus] {
        let response: CustomerOrders = try await get("orders/mine/")
        return response.results
    }

    func makeOrderUpdatesSocket() throws -> URLSessionWebSocketTask {
        guard let webSocketBaseURL, let origin else {
            throw CustomerAPIError(message: "Invalid WebSocket configuration.")
        }
        let cookies = HTTPCookieStorage.shared.cookies(for: baseURL) ?? []
        guard let cookieHeader = HTTPCookie.requestHeaderFields(with: cookies)["Cookie"] else {
            throw CustomerAPIError(message: "Customer session is unavailable.")
        }
        var request = URLRequest(url: webSocketBaseURL.appending(path: "orders/"))
        request.setValue(origin, forHTTPHeaderField: "Origin")
        request.setValue(cookieHeader, forHTTPHeaderField: "Cookie")
        return URLSession.shared.webSocketTask(with: request)
    }

    func placeOrder(
        menuID: Int,
        submissionID: UUID,
        customerName: String,
        phone: String,
        note: String,
        items: [(dishID: Int, quantity: Int)]
    ) async throws -> OrderReceipt {
        let session: CustomerSession = try await get("api/v1/customer/session/")
        var request = makeRequest(
            "api/v1/restaurants/\(appid)/menus/\(menuID)/orders/",
            method: "POST"
        )
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(session.csrfToken, forHTTPHeaderField: "X-CSRFToken")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(OrderRequest(
            submissionId: submissionID.uuidString,
            customerName: customerName,
            phone: phone,
            note: note,
            items: items.map { OrderLine(dishId: $0.dishID, quantity: $0.quantity) }
        ))
        return try await send(request)
    }

    private func get<Value: Decodable>(_ path: String) async throws -> Value {
        try await send(makeRequest(path))
    }

    private func makeRequest(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(Locale.preferredLanguages.first ?? "en", forHTTPHeaderField: "Accept-Language")
        if method == "POST", let origin {
            request.setValue(origin, forHTTPHeaderField: "Origin")
        }
        return request
    }

    private var origin: String? {
        guard let scheme = baseURL.scheme, let host = baseURL.host else { return nil }
        let portSuffix: String
        if let port = baseURL.port,
           !((scheme == "https" && port == 443) || (scheme == "http" && port == 80)) {
            portSuffix = ":\(port)"
        } else {
            portSuffix = ""
        }
        return "\(scheme)://\(host)\(portSuffix)"
    }

    private func send<Value: Decodable>(_ request: URLRequest) async throws -> Value {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(response.statusCode) else {
            if let error = try? JSONDecoder().decode(APIErrorBody.self, from: data) {
                throw CustomerAPIError(message: error.error)
            }
            throw URLError(.badServerResponse)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Value.self, from: data)
    }
}

private struct CustomerAPIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}
