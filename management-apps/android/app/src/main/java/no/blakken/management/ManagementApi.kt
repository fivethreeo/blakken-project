package no.blakken.management

import android.content.Context
import android.util.Base64
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager.PrepareIntegrityTokenRequest
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.IOException
import java.net.CookieHandler
import java.net.CookieManager
import java.net.CookiePolicy
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.security.MessageDigest
import java.util.Locale
import java.util.UUID

data class Restaurant(val name: String, val appid: String, val active: Boolean, val role: String)
data class MenuItem(val id: Int, val name: String, val isDefault: Boolean)
data class MenuDish(
    val id: Int,
    val pageId: Int,
    val name: String,
    val description: String,
    val price: String?,
    val allergens: List<String>,
    val isVisible: Boolean,
)
data class MenuCategory(
    val id: Int,
    val name: String,
    val isVisible: Boolean,
    val dishes: List<MenuDish>,
)
data class MenuContent(val id: Int, val name: String, val categories: List<MenuCategory>)
data class OrderLine(val name: String, val quantity: Int, val total: String)
data class OrderItem(
    val id: Int,
    val customer: String,
    val phone: String,
    val note: String,
    val menu: String,
    val status: String,
    val statusLabel: String,
    val nextStatuses: List<String>,
    val total: String,
    val currency: String,
    val items: List<OrderLine>,
)
data class ShopStatus(val isOpen: Boolean)
data class Tokens(val access: String, val refresh: String)
enum class OrderFilter(val value: String) {
    ACTIVE("active"), ALL("all"), NEW("new"), PREPARING("preparing"),
    READY("ready"), COMPLETED("completed"), CANCELLED("cancelled"),
}
data class OrderPage(val results: List<OrderItem>, val count: Int, val page: Int, val pages: Int)

class ManagementApi(private val context: Context) {
    private val websocketClient = OkHttpClient()
    private val integrityManager by lazy {
        IntegrityManagerFactory.createStandard(context.applicationContext)
    }

    suspend fun signIn(email: String, password: String): Tokens =
        authenticate(
            "token",
            JSONObject().put("email", email).put("password", password),
        ).toTokens()

    suspend fun refresh(refresh: String): Tokens =
        authenticate(
            "refresh",
            JSONObject().put("refresh", refresh),
        ).toTokens()

    private suspend fun authenticate(operation: String, body: JSONObject): JSONObject {
        val bodyBytes = body.toString().toByteArray(Charsets.UTF_8)
        if (!BuildConfig.PLAY_INTEGRITY_REQUIRED) {
            return request("api/v1/auth/$operation/", "POST", bodyBytes = bodyBytes)
        }
        val base = URI(BuildConfig.API_BASE_URL)
        check(base.scheme.equals("https", ignoreCase = true) && !base.host.isNullOrBlank()
            && base.rawUserInfo == null) { "Play Integrity authentication requires an HTTPS API URL." }
        val registrationId = BuildConfig.APP_REGISTRATION_ID.lowercase(Locale.ROOT)
        check(runCatching { UUID.fromString(registrationId).toString() }.getOrNull() == registrationId) {
            "Play Integrity authentication requires a valid app registration UUID."
        }
        val projectNumber = BuildConfig.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER
        check(projectNumber > 0) { "Play Integrity requires a linked Google Cloud project number." }
        val headers = mapOf("X-App-Registration-ID" to registrationId)
        val session = request("api/v1/customer/session/", headers = headers)
        val csrfToken = session.getString("csrf_token")
        check(csrfToken.isNotBlank() && session.getString("attestation_session").isNotBlank()) {
            "The attestation session is unavailable."
        }
        val bodyHash = MessageDigest.getInstance("SHA-256").digest(bodyBytes)
        val challenge = request(
            "api/v1/official/android/play-integrity/challenges/",
            method = "POST",
            body = JSONObject().put("request_hash", bodyHash.toHex()),
            csrfToken = csrfToken,
            headers = headers,
        )
        val challengeBytes = Base64.decode(challenge.getString("challenge"), Base64.DEFAULT)
        check(challengeBytes.size == 32) { "The server returned an invalid integrity challenge." }
        val scope = "POST\nmanagement\n$registrationId\n$operation\n".toByteArray(Charsets.UTF_8)
        val requestHash = Base64.encodeToString(
            MessageDigest.getInstance("SHA-256").digest(scope + challengeBytes + bodyHash),
            Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP,
        )
        // A fresh provider avoids retaining invalid or expired providers across auth requests.
        val provider = integrityManager.prepareIntegrityToken(
            PrepareIntegrityTokenRequest.builder().setCloudProjectNumber(projectNumber).build(),
        ).await()
        val integrityToken = provider.request(
            StandardIntegrityTokenRequest.builder().setRequestHash(requestHash).build(),
        ).await().token()
        currentCoroutineContext().ensureActive()
        return request(
            "api/v1/official/management/android/auth/$operation/",
            method = "POST",
            bodyBytes = bodyBytes,
            csrfToken = csrfToken,
            headers = headers + mapOf(
                "X-Play-Integrity-Challenge-ID" to challenge.getString("challenge_id"),
                "X-Play-Integrity-Token" to integrityToken,
            ),
        )
    }

    suspend fun restaurants(token: String): List<Restaurant> =
        request("api/v1/management/restaurants/", token = token)
            .getJSONArray("results").let { rows ->
                (0 until rows.length()).map { index ->
                    val row = rows.getJSONObject(index)
                    Restaurant(
                        name = row.getString("name"),
                        appid = row.getString("appid"),
                        active = row.getBoolean("active"),
                        role = row.getString("role"),
                    )
                }
            }

    suspend fun menus(appid: String, token: String): List<MenuItem> =
        request("api/v1/management/restaurants/$appid/menus/", token = token)
            .getJSONArray("results").let { rows ->
                (0 until rows.length()).map { index ->
                    val row = rows.getJSONObject(index)
                    MenuItem(row.getInt("id"), row.getString("name"), row.getBoolean("is_default"))
                }
            }

    suspend fun createMenu(appid: String, name: String, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/create/",
            method = "POST",
            body = JSONObject().put("name", name),
            token = token,
        )
    }

    suspend fun deleteMenu(appid: String, menuId: Int, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/",
            method = "DELETE",
            token = token,
        )
    }

    suspend fun menuContent(appid: String, menuId: Int, token: String): MenuContent {
        val data = request("api/v1/management/restaurants/$appid/menus/$menuId/content/", token = token)
        val rows = data.getJSONArray("categories")
        val categories = (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            val dishes = row.getJSONArray("dishes")
            MenuCategory(
                id = row.getInt("id"),
                name = row.getString("name"),
                isVisible = row.getBoolean("is_visible"),
                dishes = (0 until dishes.length()).map { dishIndex ->
                    val dish = dishes.getJSONObject(dishIndex)
                    MenuDish(
                        id = dish.getInt("id"),
                        pageId = dish.getInt("page_id"),
                        name = dish.getString("name"),
                        description = dish.getString("description"),
                        price = if (dish.isNull("price")) null else dish.getString("price"),
                        allergens = dish.getJSONArray("allergens").toStringList(),
                        isVisible = dish.getBoolean("is_visible"),
                    )
                },
            )
        }
        return MenuContent(data.getInt("id"), data.getString("name"), categories)
    }

    suspend fun createCategory(appid: String, menuId: Int, name: String, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/categories/",
            method = "POST",
            body = JSONObject().put("name", name),
            token = token,
        )
    }

    suspend fun updateCategory(
        appid: String,
        menuId: Int,
        categoryId: Int,
        name: String,
        isVisible: Boolean,
        token: String,
    ) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/categories/$categoryId/",
            method = "PATCH",
            body = JSONObject().put("name", name).put("is_visible", isVisible),
            token = token,
        )
    }

    suspend fun deleteCategory(appid: String, menuId: Int, categoryId: Int, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/categories/$categoryId/",
            method = "DELETE",
            token = token,
        )
    }

    suspend fun createDish(
        appid: String,
        menuId: Int,
        categoryId: Int,
        name: String,
        description: String,
        price: String,
        isVisible: Boolean,
        token: String,
    ) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/categories/$categoryId/dishes/",
            method = "POST",
            body = dishBody(name, description, price, emptyList(), isVisible),
            token = token,
        )
    }

    suspend fun updateDish(
        appid: String,
        menuId: Int,
        dishId: Int,
        name: String,
        description: String,
        price: String,
        allergens: List<String>,
        isVisible: Boolean,
        token: String,
    ) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/dishes/$dishId/",
            method = "PATCH",
            body = dishBody(name, description, price, allergens, isVisible),
            token = token,
        )
    }

    suspend fun deleteDish(appid: String, menuId: Int, dishId: Int, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/dishes/$dishId/",
            method = "DELETE",
            token = token,
        )
    }

    suspend fun setDefaultMenu(appid: String, menuId: Int, token: String) {
        request(
            "api/v1/management/restaurants/$appid/menus/$menuId/default/",
            method = "POST",
            token = token,
        )
    }

    suspend fun orders(appid: String, token: String, filter: OrderFilter, page: Int): OrderPage {
        val response = request(
            "api/v1/management/restaurants/$appid/orders/?status=${filter.value}&page=$page",
            token = token,
        )
        val results = response.getJSONArray("results").let { rows ->
                (0 until rows.length()).map { index ->
                    val row = rows.getJSONObject(index)
                    val orderItems = row.getJSONArray("items")
                    OrderItem(
                        id = row.getInt("id"),
                        customer = row.getString("customer_name"),
                        phone = row.getString("phone"),
                        note = row.getString("note"),
                        menu = row.getString("menu_name"),
                        status = row.getString("status"),
                        statusLabel = row.getString("status_label"),
                        nextStatuses = row.getJSONArray("next_statuses").toStringList(),
                        total = row.getString("total"),
                        currency = row.getString("currency"),
                        items = (0 until orderItems.length()).map { itemIndex ->
                            val item = orderItems.getJSONObject(itemIndex)
                            OrderLine(
                                name = item.getString("name"),
                                quantity = item.getInt("quantity"),
                                total = item.getString("total"),
                            )
                        },
                    )
                }
            }
        return OrderPage(
            results, response.getInt("count"), response.getInt("page"), response.getInt("pages"),
        )
    }

    suspend fun updateOrder(appid: String, order: OrderItem, status: String, token: String) {
        request(
            "api/v1/management/restaurants/$appid/orders/${order.id}/status/",
            method = "PATCH",
            body = JSONObject()
                .put("status", status)
                .put("expected_status", order.status),
            token = token,
        )
    }

    fun orderUpdates(token: String): Flow<Unit> = callbackFlow {
        val apiUri = URI(BuildConfig.API_BASE_URL)
        val originPort = if (apiUri.port == -1) "" else ":${apiUri.port}"
        val origin = "${apiUri.scheme}://${apiUri.host}$originPort"
        val request = Request.Builder()
            .url("${BuildConfig.WS_BASE_URL.trimEnd('/')}/management/")
            .header("Authorization", "Bearer $token")
            .header("Origin", origin)
            .build()
        val socket = websocketClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                trySend(Unit)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = runCatching { JSONObject(text).optString("event") }.getOrNull()
                if (event == "orders.changed") {
                    trySend(Unit)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                close()
            }

            override fun onFailure(webSocket: WebSocket, throwable: Throwable, response: Response?) {
                close(throwable)
            }
        })
        awaitClose { socket.cancel() }
    }.conflate()

    suspend fun shopStatus(appid: String, token: String): ShopStatus =
        request("api/v1/management/restaurants/$appid/shop/", token = token)
            .let { ShopStatus(it.getBoolean("is_open")) }

    suspend fun setShopStatus(
        appid: String,
        isOpen: Boolean,
        expectedIsOpen: Boolean,
        token: String,
    ): ShopStatus =
        request(
            "api/v1/management/restaurants/$appid/shop/",
            method = "PATCH",
            body = JSONObject().put("is_open", isOpen).put("expected_is_open", expectedIsOpen),
            token = token,
        ).let { ShopStatus(it.getBoolean("is_open")) }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        token: String? = null,
        bodyBytes: ByteArray? = null,
        csrfToken: String? = null,
        headers: Map<String, String> = emptyMap(),
    ): JSONObject = withContext(Dispatchers.IO) {
        currentCoroutineContext().ensureActive()
        val connection = URL(BuildConfig.API_BASE_URL.trimEnd('/') + "/" + path)
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Language", Locale.getDefault().toLanguageTag())
            token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
            headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
            if (csrfToken != null) {
                connection.instanceFollowRedirects = false
                connection.setRequestProperty("X-CSRFToken", csrfToken)
                val base = URL(BuildConfig.API_BASE_URL)
                connection.setRequestProperty("Origin", "${base.protocol}://${base.authority}")
            }
            val encodedBody = bodyBytes ?: body?.toString()?.toByteArray(Charsets.UTF_8)
            if (encodedBody != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(encodedBody) }
            }
            val responseCode = connection.responseCode
            val stream = if (responseCode in 200..299) connection.inputStream else connection.errorStream
            val responseText = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            currentCoroutineContext().ensureActive()
            val response = runCatching { JSONObject(responseText) }.getOrElse { JSONObject() }
            if (responseCode !in 200..299) {
                throw ManagementApiError(
                    responseCode,
                    response.optString("error").ifBlank { context.getString(R.string.request_failed) },
                )
            }
            response
        } finally {
            connection.disconnect()
        }
    }

    private fun JSONObject.toTokens() = Tokens(getString("access"), getString("refresh"))

    private fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it.toInt() and 0xff) }

    private fun dishBody(
        name: String,
        description: String,
        price: String,
        allergens: List<String>,
        isVisible: Boolean,
    ) = JSONObject()
        .put("name", name)
        .put("description", description)
        .put("price", price)
        .put("allergens", org.json.JSONArray(allergens))
        .put("is_visible", isVisible)

    private fun org.json.JSONArray.toStringList() =
        (0 until length()).map { getString(it) }

    companion object {
        init {
            if (CookieHandler.getDefault() !is CookieManager) {
                CookieHandler.setDefault(CookieManager(null, CookiePolicy.ACCEPT_ORIGINAL_SERVER))
            }
        }
    }
}

class ManagementApiError(val statusCode: Int, message: String) : IOException(message)
