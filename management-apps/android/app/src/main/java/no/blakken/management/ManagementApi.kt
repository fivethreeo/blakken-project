package no.blakken.management

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

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

class ManagementApi(private val context: Context) {
    suspend fun signIn(email: String, password: String): Tokens =
        request(
            "api/v1/auth/token/",
            method = "POST",
            body = JSONObject().put("email", email).put("password", password),
        ).toTokens()

    suspend fun refresh(refresh: String): Tokens =
        request(
            "api/v1/auth/refresh/",
            method = "POST",
            body = JSONObject().put("refresh", refresh),
        ).toTokens()

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

    suspend fun orders(appid: String, token: String): List<OrderItem> =
        request("api/v1/management/restaurants/$appid/orders/", token = token)
            .getJSONArray("results").let { rows ->
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
    ): JSONObject = withContext(Dispatchers.IO) {
        val connection = URL(BuildConfig.API_BASE_URL.trimEnd('/') + "/" + path)
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 10_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Language", Locale.getDefault().toLanguageTag())
            token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val responseCode = connection.responseCode
            val stream = if (responseCode in 200..299) connection.inputStream else connection.errorStream
            val responseText = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
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
}

class ManagementApiError(val statusCode: Int, message: String) : IOException(message)
