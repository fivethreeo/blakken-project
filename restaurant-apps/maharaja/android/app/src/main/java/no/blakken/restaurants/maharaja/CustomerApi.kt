package no.blakken.restaurants.maharaja

import android.content.Context
import android.util.Base64
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.StandardIntegrityManager
import com.google.android.play.core.integrity.StandardIntegrityManager.PrepareIntegrityTokenRequest
import com.google.android.play.core.integrity.StandardIntegrityManager.StandardIntegrityTokenRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.net.CookieHandler
import java.net.CookieManager
import java.net.CookiePolicy
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.Locale
import java.util.UUID

data class Dish(val id: Int, val name: String, val description: String, val price: String?)
data class Category(val id: Int, val name: String, val dishes: List<Dish>)
data class CustomerMenu(val id: Int, val name: String, val categories: List<Category>)
data class ShopStatus(val restaurant: String, val isOpen: Boolean, val message: String)
data class OrderReceipt(val id: Int, val total: String, val currency: String)
data class CustomerOrderStatus(
    val id: Int,
    val statusLabel: String?,
    val total: String?,
    val currency: String?,
)

class CustomerApi(private val context: Context) {
    private val websocketClient = OkHttpClient()
    private val integrityManager by lazy {
        IntegrityManagerFactory.createStandard(context.applicationContext)
    }
    private val integrityProviderMutex = Mutex()
    private var integrityTokenProvider: StandardIntegrityManager.StandardIntegrityTokenProvider? = null

    suspend fun menu(): CustomerMenu {
        val data = request("api/v1/restaurants/${BuildConfig.RESTAURANT_APP_ID}/menus/default/")
        val categories = data.getJSONArray("categories").toCategoryList()
        return CustomerMenu(data.getInt("id"), data.getString("name"), categories)
    }

    suspend fun status(): ShopStatus {
        val data = request("api/v1/restaurants/${BuildConfig.RESTAURANT_APP_ID}/shop-status/")
        return ShopStatus(
            data.getString("restaurant"),
            data.getBoolean("is_open"),
            data.getString("message"),
        )
    }

    suspend fun customerOrders(): List<CustomerOrderStatus> {
        val results = request("orders/mine/").getJSONArray("results")
        return (0 until results.length()).map { index ->
            val order = results.getJSONObject(index)
            CustomerOrderStatus(
                order.getInt("id"), order.getString("status_label"),
                order.optString("total").takeIf { it.isNotBlank() },
                order.optString("currency").takeIf { it.isNotBlank() },
            )
        }
    }

    suspend fun prepareOrderUpdates() {
        request("api/v1/customer/session/")
    }

    fun shopUpdates(): Flow<Unit> {
        val appid = UUID.fromString(BuildConfig.RESTAURANT_APP_ID).toString()
        return updates("shop/?appid=$appid", "shop.changed")
    }

    fun orderUpdates(): Flow<Unit> {
        val cookies = CookieHandler.getDefault()
            .get(URL("${BuildConfig.API_BASE_URL.trimEnd('/')}/orders/mine/").toURI(), emptyMap())
            .entries.firstOrNull { it.key.equals("Cookie", ignoreCase = true) }
            ?.value?.joinToString("; ").orEmpty()
        return updates("orders/", "orders.changed", cookies)
    }

    private fun updates(path: String, eventName: String, cookies: String = ""): Flow<Unit> = callbackFlow {
        val base = URL(BuildConfig.API_BASE_URL)
        val request = Request.Builder()
            .url("${BuildConfig.WS_BASE_URL.trimEnd('/')}/$path")
            .header("Origin", "${base.protocol}://${base.authority}")
            .apply { if (cookies.isNotEmpty()) header("Cookie", cookies) }
            .build()
        val socket = websocketClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                trySend(Unit)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = runCatching { JSONObject(text).optString("event") }.getOrNull()
                if (event == eventName) trySend(Unit)
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

    suspend fun placeOrder(
        menuId: Int,
        submissionId: String,
        customerName: String,
        phone: String,
        note: String,
        items: List<Pair<Int, Int>>,
    ): OrderReceipt {
        val session = request("api/v1/customer/session/")
        val body = JSONObject()
            .put("submission_id", submissionId)
            .put("customer_name", customerName)
            .put("phone", phone)
            .put("note", note)
            .put("items", JSONArray().apply {
                items.forEach { (dishId, quantity) ->
                    put(JSONObject().put("dish_id", dishId).put("quantity", quantity))
                }
            })
        val csrfToken = session.getString("csrf_token")
        val response = if (BuildConfig.PLAY_INTEGRITY_REQUIRED) {
            if (!BuildConfig.API_BASE_URL.startsWith("https://", ignoreCase = true)) {
                throw IllegalStateException("Play Integrity orders require an HTTPS API URL.")
            }
            check(runCatching { UUID.fromString(BuildConfig.APP_REGISTRATION_ID) }.isSuccess) {
                "Play Integrity requires an app registration ID."
            }
            val bodyBytes = body.toString().toByteArray(Charsets.UTF_8)
            val bodyHash = MessageDigest.getInstance("SHA-256").digest(bodyBytes)
            val challenge = request(
                "api/v1/official/android/play-integrity/challenges/",
                method = "POST",
                body = JSONObject().put("request_hash", bodyHash.toHex()),
                csrfToken = csrfToken,
            )
            val challengeId = challenge.getString("challenge_id")
            val challengeBytes = Base64.decode(challenge.getString("challenge"), Base64.DEFAULT)
            check(challengeBytes.size == 32) { "The server returned an invalid integrity challenge." }
            val requestHash = playIntegrityRequestHash(challengeBytes, bodyHash, menuId)
            val token = requestIntegrityToken(requestHash)
            request(
                "api/v1/official/android/restaurants/${BuildConfig.RESTAURANT_APP_ID}/menus/$menuId/orders/",
                method = "POST",
                body = body,
                csrfToken = csrfToken,
                headers = mapOf(
                    "X-Play-Integrity-Challenge-ID" to challengeId,
                    "X-Play-Integrity-Token" to token,
                ),
                bodyBytes = bodyBytes,
            )
        } else {
            request(
                "api/v1/restaurants/${BuildConfig.RESTAURANT_APP_ID}/menus/$menuId/orders/",
                method = "POST",
                body = body,
                csrfToken = csrfToken,
            )
        }
        val order = response.getJSONObject("order")
        return OrderReceipt(
            id = order.getInt("id"),
            total = order.getString("total"),
            currency = order.getString("currency"),
        )
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        csrfToken: String? = null,
        headers: Map<String, String> = emptyMap(),
        bodyBytes: ByteArray? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val connection = URL(BuildConfig.API_BASE_URL.trimEnd('/') + "/" + path)
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Language", Locale.getDefault().toLanguageTag())
            if (BuildConfig.PLAY_INTEGRITY_REQUIRED && path.startsWith("api/v1/official/")) {
                connection.setRequestProperty("X-App-Registration-ID", BuildConfig.APP_REGISTRATION_ID)
            }
            headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                csrfToken?.let {
                    connection.setRequestProperty("X-CSRFToken", it)
                    val base = URL(BuildConfig.API_BASE_URL)
                    connection.setRequestProperty("Origin", "${base.protocol}://${base.authority}")
                }
                connection.outputStream.use {
                    it.write(bodyBytes ?: body.toString().toByteArray(Charsets.UTF_8))
                }
            }
            val responseCode = connection.responseCode
            val stream = if (responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val responseText = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val response = runCatching { JSONObject(responseText) }.getOrElse { JSONObject() }
            if (responseCode !in 200..299) {
                throw IllegalStateException(
                    response.optString("error").ifBlank { context.getString(R.string.request_failed) },
                )
            }
            response
        } finally {
            connection.disconnect()
        }
    }

    private suspend fun requestIntegrityToken(requestHash: String): String {
        val cloudProjectNumber = BuildConfig.PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER.toLongOrNull()
            ?.takeIf { it > 0 }
            ?: throw IllegalStateException("Play Integrity is missing its Google Cloud project number.")
        val provider = integrityProviderMutex.withLock {
            integrityTokenProvider ?: integrityManager.prepareIntegrityToken(
                PrepareIntegrityTokenRequest.builder()
                    .setCloudProjectNumber(cloudProjectNumber)
                    .build(),
            ).await().also { integrityTokenProvider = it }
        }
        return provider.request(
            StandardIntegrityTokenRequest.builder()
                .setRequestHash(requestHash)
                .build(),
        ).await().token()
    }

    private fun playIntegrityRequestHash(
        challenge: ByteArray,
        bodyHash: ByteArray,
        menuId: Int,
    ): String {
        val scope = "POST\n${BuildConfig.APPLICATION_ID}\n"
            .plus("${BuildConfig.RESTAURANT_APP_ID.lowercase(Locale.ROOT)}\n$menuId\n")
            .toByteArray(Charsets.UTF_8)
        val requestData = scope + challenge + bodyHash
        val digest = MessageDigest.getInstance("SHA-256").digest(requestData)
        return Base64.encodeToString(
            digest,
            Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP,
        )
    }

    private fun ByteArray.toHex(): String =
        joinToString("") { "%02x".format(it.toInt() and 0xff) }

    private fun JSONArray.toCategoryList(): List<Category> =
        (0 until length()).map { index ->
            val category = getJSONObject(index)
            Category(
                id = category.getInt("id"),
                name = category.getString("name"),
                dishes = category.getJSONArray("dishes").toDishList(),
            )
        }

    private fun JSONArray.toDishList(): List<Dish> =
        (0 until length()).map { index ->
            val dish = getJSONObject(index)
            Dish(
                id = dish.getInt("id"),
                name = dish.getString("name"),
                description = dish.getString("description"),
                price = if (dish.isNull("price")) null else dish.getString("price"),
            )
        }

    companion object {
        init {
            CookieHandler.setDefault(CookieManager(null, CookiePolicy.ACCEPT_ALL))
        }
    }
}
