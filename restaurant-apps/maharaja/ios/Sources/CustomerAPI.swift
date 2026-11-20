import CryptoKit
import DeviceCheck
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
    let attestationSession: String
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

private struct AppAttestChallengeResponse: Decodable {
    let challengeId: String
    let challenge: String
}

private struct AppAttestChallengeRequest: Encodable {
    let purpose: String
    let requestHash: String?
}

private struct AppAttestRegistrationRequest: Encodable {
    let keyId: String
    let challengeId: String
    let attestationObject: String
}

private struct AppAttestRegistrationResponse: Decodable {
    let registered: Bool
}

private struct AppAttestProof {
    let keyID: String
    let challengeID: String
    let assertion: String
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
    private let appAttestRequired: Bool

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
        appid = (bundle.object(forInfoDictionaryKey: "RESTAURANT_APP_ID") as? String
            ?? "REPLACE_WITH_RESTAURANT_APP_ID"
        ).lowercased()
        let appAttestSetting = bundle.object(forInfoDictionaryKey: "APP_ATTEST_REQUIRED")
        appAttestRequired = (appAttestSetting as? Bool)
            ?? ((appAttestSetting as? String).map {
                ["yes", "true", "1"].contains($0.lowercased())
            } ?? false)
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

    func makeShopUpdatesSocket() throws -> URLSessionWebSocketTask {
        guard let webSocketBaseURL, let origin,
              var components = URLComponents(
                url: webSocketBaseURL.appending(path: "shop/"),
                resolvingAgainstBaseURL: false
              ) else {
            throw CustomerAPIError(message: "Invalid WebSocket configuration.")
        }
        components.queryItems = [URLQueryItem(name: "appid", value: appid)]
        guard let url = components.url else {
            throw CustomerAPIError(message: "Invalid WebSocket configuration.")
        }
        var request = URLRequest(url: url)
        request.setValue(origin, forHTTPHeaderField: "Origin")
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
        let body = try orderBody(
            submissionID: submissionID,
            customerName: customerName,
            phone: phone,
            note: note,
            items: items
        )
        let orderPath = appAttestRequired
            ? "api/v1/official/restaurants/\(appid)/menus/\(menuID)/orders/"
            : "api/v1/restaurants/\(appid)/menus/\(menuID)/orders/"
        var request = makeRequest(orderPath, method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(session.csrfToken, forHTTPHeaderField: "X-CSRFToken")
        request.httpBody = body
        if appAttestRequired {
            guard baseURL.scheme?.lowercased() == "https",
                  let registrationID = Bundle.main.object(forInfoDictionaryKey: "APP_REGISTRATION_ID") as? String,
                  UUID(uuidString: registrationID) != nil else {
                throw CustomerAPIError(message: "App Attest requires HTTPS and an app registration ID.")
            }
            let proof = try await appAttestProof(
                for: body,
                menuID: menuID,
                csrfToken: session.csrfToken,
                attestationSession: session.attestationSession
            )
            request.setValue(proof.keyID, forHTTPHeaderField: "X-App-Attest-Key-ID")
            request.setValue(proof.challengeID, forHTTPHeaderField: "X-App-Attest-Challenge-ID")
            request.setValue(proof.assertion, forHTTPHeaderField: "X-App-Attest-Assertion")
        }
        return try await send(request)
    }

    private func orderBody(
        submissionID: UUID,
        customerName: String,
        phone: String,
        note: String,
        items: [(dishID: Int, quantity: Int)]
    ) throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(OrderRequest(
            submissionId: submissionID.uuidString,
            customerName: customerName,
            phone: phone,
            note: note,
            items: items.map { OrderLine(dishId: $0.dishID, quantity: $0.quantity) }
        ))
    }

    private func appAttestProof(
        for body: Data,
        menuID: Int,
        csrfToken: String,
        attestationSession: String
    ) async throws -> AppAttestProof {
        let service = DCAppAttestService.shared
        guard service.isSupported else {
            throw CustomerAPIError(message: "This device does not support App Attest.")
        }
        let key = try await appAttestKey(
            service: service, csrfToken: csrfToken, attestationSession: attestationSession
        )
        let bodyHash = Data(SHA256.hash(data: body))
        let challenge: AppAttestChallengeResponse = try await postJSON(
            "api/v1/official/app-attest/challenges/",
            body: AppAttestChallengeRequest(
                purpose: "assertion",
                requestHash: bodyHash.map { String(format: "%02x", $0) }.joined()
            ),
            csrfToken: csrfToken
        )
        guard let challengeData = Data(base64Encoded: challenge.challenge) else {
            throw CustomerAPIError(message: "The server returned an invalid App Attest challenge.")
        }
        var clientData = Data("POST\n\(appid)\n\(menuID)\n".utf8)
        clientData.append(challengeData)
        clientData.append(bodyHash)
        let clientDataHash = Data(SHA256.hash(data: clientData))
        let assertion: Data = try await withCheckedThrowingContinuation { continuation in
            service.generateAssertion(key, clientDataHash: clientDataHash) { assertion, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let assertion {
                    continuation.resume(returning: assertion)
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
        }
        return AppAttestProof(
            keyID: key,
            challengeID: challenge.challengeId,
            assertion: assertion.base64EncodedString()
        )
    }

    private func appAttestKey(
        service: DCAppAttestService,
        csrfToken: String,
        attestationSession: String
    ) async throws -> String {
        let keyStore = UserDefaults.standard
        let registrationID = Bundle.main.object(forInfoDictionaryKey: "APP_REGISTRATION_ID") as? String ?? ""
        let scope = "\(baseURL.absoluteString)\n\(registrationID.lowercased())\n\(attestationSession)"
        let scopeHash = SHA256.hash(data: Data(scope.utf8)).map { String(format: "%02x", $0) }.joined()
        let storageKey = "maharaja.app-attest-key-id.\(scopeHash)"
        if let key = keyStore.string(forKey: storageKey) {
            return key
        }
        let key: String = try await withCheckedThrowingContinuation { continuation in
            service.generateKey { key, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let key {
                    continuation.resume(returning: key)
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
        }
        let challenge: AppAttestChallengeResponse = try await postJSON(
            "api/v1/official/app-attest/challenges/",
            body: AppAttestChallengeRequest(purpose: "attestation", requestHash: nil),
            csrfToken: csrfToken
        )
        guard let challengeData = Data(base64Encoded: challenge.challenge) else {
            throw CustomerAPIError(message: "The server returned an invalid App Attest challenge.")
        }
        let clientDataHash = Data(SHA256.hash(data: challengeData))
        let attestation: Data = try await withCheckedThrowingContinuation { continuation in
            service.attestKey(key, clientDataHash: clientDataHash) { object, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let object {
                    continuation.resume(returning: object)
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
        }
        let response: AppAttestRegistrationResponse = try await postJSON(
            "api/v1/official/app-attest/keys/",
            body: AppAttestRegistrationRequest(
                keyId: key,
                challengeId: challenge.challengeId,
                attestationObject: attestation.base64EncodedString()
            ),
            csrfToken: csrfToken
        )
        guard response.registered else {
            throw CustomerAPIError(message: "The server did not register the App Attest key.")
        }
        keyStore.set(key, forKey: storageKey)
        return key
    }

    private func postJSON<Body: Encodable, Value: Decodable>(
        _ path: String,
        body: Body,
        csrfToken: String
    ) async throws -> Value {
        var request = makeRequest(path, method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(csrfToken, forHTTPHeaderField: "X-CSRFToken")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(body)
        return try await send(request)
    }

    private func get<Value: Decodable>(_ path: String) async throws -> Value {
        try await send(makeRequest(path))
    }

    private func makeRequest(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        if appAttestRequired && path.hasPrefix("api/v1/official/") {
            request.setValue(
                Bundle.main.object(forInfoDictionaryKey: "APP_REGISTRATION_ID") as? String,
                forHTTPHeaderField: "X-App-Registration-ID"
            )
        }
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
