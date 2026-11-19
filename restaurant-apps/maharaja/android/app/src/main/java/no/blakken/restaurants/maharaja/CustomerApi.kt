package no.blakken.restaurants.maharaja

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.CookieHandler
import java.net.CookieManager
import java.net.CookiePolicy
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

data class Dish(val id: Int, val name: String, val description: String, val price: String?)
data class Category(val id: Int, val name: String, val dishes: List<Dish>)
data class CustomerMenu(val id: Int, val name: String, val categories: List<Category>)
data class ShopStatus(val restaurant: String, val isOpen: Boolean, val message: String)

class CustomerApi(private val context: Context) {
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

    suspend fun placeOrder(
        menuId: Int,
        submissionId: String,
        customerName: String,
        phone: String,
        note: String,
        items: List<Pair<Int, Int>>,
    ): JSONObject {
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
        return request(
            "api/v1/restaurants/${BuildConfig.RESTAURANT_APP_ID}/menus/$menuId/orders/",
            method = "POST",
            body = body,
            csrfToken = session.getString("csrf_token"),
        )
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: JSONObject? = null,
        csrfToken: String? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val connection = URL(BuildConfig.API_BASE_URL.trimEnd('/') + "/" + path)
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Language", Locale.getDefault().toLanguageTag())
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                csrfToken?.let { connection.setRequestProperty("X-CSRFToken", it) }
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
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
