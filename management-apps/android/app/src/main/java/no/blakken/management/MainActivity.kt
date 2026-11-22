package no.blakken.management

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.background
import androidx.compose.foundation.Image
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ManagementScreen(lifecycle) }
    }
}

@Composable
private fun ManagementScreen(lifecycle: Lifecycle) {
    val context = LocalContext.current
    val api = remember(context) { ManagementApi(context) }
    val scope = rememberCoroutineScope()
    val orderRefreshMutex = remember { Mutex() }
    var email by remember { mutableStateOf("maharaja-demo@example.test") }
    var password by remember { mutableStateOf("") }
    var accessToken by remember { mutableStateOf<String?>(null) }
    var refreshToken by remember { mutableStateOf<String?>(null) }
    var restaurants by remember { mutableStateOf(emptyList<Restaurant>()) }
    var selected by remember { mutableStateOf<Restaurant?>(null) }
    var menus by remember { mutableStateOf(emptyList<MenuItem>()) }
    var orders by remember { mutableStateOf(emptyList<OrderItem>()) }
    var orderFilter by remember { mutableStateOf(OrderFilter.ACTIVE) }
    var orderPage by remember { mutableStateOf(1) }
    var orderPages by remember { mutableStateOf(1) }
    var orderCount by remember { mutableStateOf(0) }
    var orderSelection by remember { mutableStateOf(0) }
    var editingMenu by remember { mutableStateOf<MenuItem?>(null) }
    var menuContent by remember { mutableStateOf<MenuContent?>(null) }
    var shopStatus by remember { mutableStateOf<ShopStatus?>(null) }
    var newMenuName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    suspend fun <T> authenticated(action: suspend (String) -> T): T {
        val currentAccess = accessToken
            ?: throw ManagementApiError(401, context.getString(R.string.authentication_required))
        return try {
            action(currentAccess)
        } catch (failure: ManagementApiError) {
            if (failure.statusCode != 401) throw failure
            val currentRefresh = refreshToken ?: run {
                accessToken = null
                throw failure
            }
            val tokens = try {
                api.refresh(currentRefresh)
            } catch (failure: ManagementApiError) {
                if (failure.statusCode == 401) {
                    accessToken = null
                    refreshToken = null
                }
                throw failure
            }
            accessToken = tokens.access
            refreshToken = tokens.refresh
            try {
                action(tokens.access)
            } catch (retryFailure: ManagementApiError) {
                if (retryFailure.statusCode == 401) {
                    accessToken = null
                    refreshToken = null
                }
                throw retryFailure
            }
        }
    }

    fun resetOrders(filter: OrderFilter = OrderFilter.ACTIVE, page: Int = 1) {
        orderSelection += 1
        orderFilter = filter
        orderPage = page
        orders = emptyList()
        if (page == 1) {
            orderPages = 1
            orderCount = 0
        }
    }

    suspend fun fetchOrders(
        restaurant: Restaurant, token: String, filter: OrderFilter, page: Int,
    ): OrderPage = try {
        api.orders(restaurant.appid, token, filter, page)
    } catch (failure: ManagementApiError) {
        if (failure.statusCode != 400 || page <= 1) throw failure
        api.orders(restaurant.appid, token, filter, 1)
    }

    fun applyOrders(loaded: OrderPage) {
        orders = loaded.results
        orderPage = loaded.page
        orderPages = loaded.pages
        orderCount = loaded.count
    }

    suspend fun loadRestaurant(restaurant: Restaurant, token: String) {
        val filter = orderFilter
        val page = orderPage
        val selection = orderSelection
        val loadedMenus = api.menus(restaurant.appid, token)
        val loadedShopStatus = api.shopStatus(restaurant.appid, token)
        orderRefreshMutex.withLock {
            val loadedOrders = fetchOrders(restaurant, token, filter, page)
            currentCoroutineContext().ensureActive()
            if (selected?.appid == restaurant.appid) {
                menus = loadedMenus
                if (orderSelection == selection) applyOrders(loadedOrders)
                shopStatus = loadedShopStatus
            }
        }
    }

    suspend fun refreshRestaurant() {
        val restaurant = selected ?: return
        authenticated { token -> loadRestaurant(restaurant, token) }
    }

    fun launchAction(action: suspend () -> Unit) {
        scope.launch {
            loading = true
            error = null
            try {
                action()
            } catch (failure: Exception) {
                error = failure.localizedMessage ?: context.getString(R.string.request_failed)
            } finally {
                loading = false
            }
        }
    }

    suspend fun refreshOrders(restaurant: Restaurant) {
        val filter = orderFilter
        val page = orderPage
        val selection = orderSelection
        orderRefreshMutex.withLock {
            if (selected?.appid != restaurant.appid || accessToken == null ||
                orderSelection != selection || orderPage != page) return@withLock
            val loadedOrders = authenticated { token -> fetchOrders(restaurant, token, filter, page) }
            currentCoroutineContext().ensureActive()
            if (selected?.appid == restaurant.appid && orderSelection == selection &&
                orderPage == page) applyOrders(loadedOrders)
        }
    }

    LaunchedEffect(selected?.appid, accessToken, lifecycle) {
        val restaurant = selected ?: return@LaunchedEffect
        val token = accessToken ?: return@LaunchedEffect
        suspend fun updateOrders() {
            try {
                refreshOrders(restaurant)
            } catch (failure: CancellationException) {
                throw failure
            } catch (_: Exception) {
                // Preserve displayed orders until a reconnect or polling refresh succeeds.
            }
        }
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch {
                while (isActive) {
                    updateOrders()
                    delay(30_000)
                }
            }
            launch {
                var retryDelay = 1_000L
                while (isActive) {
                    try {
                        api.orderUpdates(token).collect {
                            retryDelay = 1_000L
                            updateOrders()
                        }
                    } catch (failure: CancellationException) {
                        throw failure
                    } catch (_: Exception) {
                        // Refresh on reconnect and poll while live updates are unavailable.
                    }
                    delay(retryDelay)
                    retryDelay = (retryDelay * 2).coerceAtMost(30_000L)
                }
            }
        }
    }

    MaterialTheme {
        Column(
            modifier = Modifier.fillMaxSize().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Image(
                painter = painterResource(R.drawable.blakken_logo),
                contentDescription = stringResource(R.string.blakken_logo_description),
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxWidth().height(104.dp),
            )
            Text(stringResource(R.string.title), style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(R.string.demo_login_hint))
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (loading) CircularProgressIndicator()

            when {
                accessToken == null -> {
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        label = { Text(stringResource(R.string.email)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = password,
                        onValueChange = { password = it },
                        label = { Text(stringResource(R.string.password)) },
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        enabled = email.isNotBlank() && password.isNotBlank() && !loading,
                        onClick = {
                            launchAction {
                                val tokens = api.signIn(email.trim(), password)
                                accessToken = tokens.access
                                refreshToken = tokens.refresh
                                restaurants = api.restaurants(tokens.access)
                            }
                        },
                    ) { Text(stringResource(R.string.sign_in)) }
                }

                selected == null -> {
                    Text(stringResource(R.string.restaurants), style = MaterialTheme.typography.titleLarge)
                    if (restaurants.isEmpty()) Text(stringResource(R.string.empty_restaurants))
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(restaurants, key = { it.appid }) { restaurant ->
                            Button(
                                modifier = Modifier.fillMaxWidth(),
                                enabled = !loading,
                                onClick = {
                                    selected = restaurant
                                    menus = emptyList()
                                    resetOrders()
                                    shopStatus = null
                                    launchAction {
                                        authenticated { token -> loadRestaurant(restaurant, token) }
                                    }
                                },
                            ) {
                                Row(modifier = Modifier.fillMaxWidth()) {
                                    Column {
                                        Text(restaurant.name)
                                        Text(roleTitle(restaurant.role), style = MaterialTheme.typography.labelSmall)
                                    }
                                    Spacer(Modifier.weight(1f))
                                    if (!restaurant.active) Text(stringResource(R.string.pending))
                                }
                            }
                        }
                    }
                    Button(
                        enabled = !loading,
                        onClick = {
                            accessToken = null
                            refreshToken = null
                            restaurants = emptyList()
                        },
                    ) { Text(stringResource(R.string.sign_out)) }
                }

                editingMenu != null -> {
                    val menu = editingMenu!!
                    val appid = selected!!.appid
                    MenuEditorScreen(
                        menu = menu,
                        content = menuContent,
                        loading = loading,
                        modifier = Modifier.weight(1f),
                        onBack = {
                            editingMenu = null
                            menuContent = null
                        },
                        onRefresh = {
                            launchAction {
                                menuContent = authenticated { token ->
                                    api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onCreateCategory = { name ->
                            launchAction {
                                authenticated { token ->
                                    api.createCategory(appid, menu.id, name, token)
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onUpdateCategory = { categoryId, name, isVisible ->
                            launchAction {
                                authenticated { token ->
                                    api.updateCategory(appid, menu.id, categoryId, name, isVisible, token)
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onDeleteCategory = { categoryId ->
                            launchAction {
                                authenticated { token ->
                                    api.deleteCategory(appid, menu.id, categoryId, token)
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onCreateDish = { categoryId, name, description, price, isVisible ->
                            launchAction {
                                authenticated { token ->
                                    api.createDish(
                                        appid, menu.id, categoryId, name, description, price, isVisible, token,
                                    )
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onUpdateDish = { dish, name, description, price, isVisible ->
                            launchAction {
                                authenticated { token ->
                                    api.updateDish(
                                        appid,
                                        menu.id,
                                        dish.id,
                                        name,
                                        description,
                                        price,
                                        dish.allergens,
                                        isVisible,
                                        token,
                                    )
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                        onDeleteDish = { dishId ->
                            launchAction {
                                authenticated { token ->
                                    api.deleteDish(appid, menu.id, dishId, token)
                                    menuContent = api.menuContent(appid, menu.id, token)
                                }
                            }
                        },
                    )
                }

                else -> {
                    val restaurant = selected!!
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { selected = null }) {
                            Text(stringResource(R.string.restaurants))
                        }
                        Button(enabled = !loading, onClick = { launchAction { refreshRestaurant() } }) {
                            Text(stringResource(R.string.refresh))
                        }
                        Spacer(Modifier.weight(1f))
                        Button(onClick = {
                            accessToken = null
                            refreshToken = null
                            restaurants = emptyList()
                            selected = null
                        }) { Text(stringResource(R.string.sign_out)) }
                    }
                    Text(restaurant.name, style = MaterialTheme.typography.titleLarge)
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        item {
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Column(
                                    modifier = Modifier.padding(12.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(stringResource(R.string.ordering), style = MaterialTheme.typography.titleMedium)
                                    shopStatus?.let { status ->
                                        Text(stringResource(if (status.isOpen) R.string.shop_open else R.string.shop_closed))
                                        Button(
                                            enabled = !loading,
                                            onClick = {
                                                launchAction {
                                                    shopStatus = authenticated { token ->
                                                        api.setShopStatus(
                                                            restaurant.appid,
                                                            !status.isOpen,
                                                            status.isOpen,
                                                            token,
                                                        )
                                                    }
                                                }
                                            },
                                        ) {
                                            Text(stringResource(if (status.isOpen) R.string.close_ordering else R.string.open_ordering))
                                        }
                                    }
                                }
                            }
                        }

                        item {
                            Text(stringResource(R.string.menus), style = MaterialTheme.typography.titleMedium)
                        }
                        if (menus.isEmpty()) {
                            item { Text(stringResource(R.string.empty_menus)) }
                        }
                        items(menus, key = { it.id }) { menu ->
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Row(
                                    modifier = Modifier.padding(12.dp).fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(menu.name, modifier = Modifier.weight(1f))
                                    if (menu.isDefault) {
                                        Text(stringResource(R.string.default_menu))
                                    } else {
                                        Button(
                                            enabled = !loading,
                                            onClick = {
                                                launchAction {
                                                    authenticated { token ->
                                                        api.setDefaultMenu(restaurant.appid, menu.id, token)
                                                        loadRestaurant(restaurant, token)
                                                    }
                                                }
                                            },
                                        ) { Text(stringResource(R.string.make_default)) }
                                    }
                                }
                                Button(
                                    enabled = !loading,
                                    onClick = {
                                        editingMenu = menu
                                        menuContent = null
                                        launchAction {
                                            menuContent = authenticated { token ->
                                                api.menuContent(restaurant.appid, menu.id, token)
                                            }
                                        }
                                    },
                                ) { Text(stringResource(R.string.edit_menu)) }
                            }
                        }
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedTextField(
                                    value = newMenuName,
                                    onValueChange = { newMenuName = it },
                                    label = { Text(stringResource(R.string.new_menu_name)) },
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                Button(
                                    enabled = newMenuName.isNotBlank() && !loading,
                                    onClick = {
                                        val name = newMenuName.trim()
                                        launchAction {
                                            authenticated { token ->
                                                api.createMenu(restaurant.appid, name, token)
                                                loadRestaurant(restaurant, token)
                                            }
                                            newMenuName = ""
                                        }
                                    },
                                ) { Text(stringResource(R.string.create_menu)) }
                            }
                        }

                        item {
                            Text(stringResource(R.string.orders), style = MaterialTheme.typography.titleMedium)
                            OrderFilterPicker(
                                selected = orderFilter,
                                enabled = !loading,
                                onSelect = { filter ->
                                    resetOrders(filter)
                                    launchAction { refreshOrders(restaurant) }
                                },
                            )
                            Text(stringResource(R.string.order_count, orderCount))
                            if (orderPages > 1) {
                                Text(stringResource(R.string.order_page, orderPage, orderPages))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(
                                        enabled = !loading && orderPage > 1,
                                        onClick = {
                                            resetOrders(orderFilter, orderPage - 1)
                                            launchAction { refreshOrders(restaurant) }
                                        },
                                    ) { Text(stringResource(R.string.previous_page)) }
                                    Button(
                                        enabled = !loading && orderPage < orderPages,
                                        onClick = {
                                            resetOrders(orderFilter, orderPage + 1)
                                            launchAction { refreshOrders(restaurant) }
                                        },
                                    ) { Text(stringResource(R.string.next_page)) }
                                }
                            }
                        }
                        if (orders.isEmpty()) {
                            item { Text(stringResource(R.string.empty_orders)) }
                        }
                        items(orders, key = { it.id }) { order ->
                            OrderCard(
                                order = order,
                                enabled = !loading,
                                onStatus = { status ->
                                    launchAction {
                                        authenticated { token ->
                                            api.updateOrder(restaurant.appid, order, status, token)
                                        }
                                        refreshOrders(restaurant)
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun OrderFilterPicker(
    selected: OrderFilter,
    enabled: Boolean,
    onSelect: (OrderFilter) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(enabled = enabled, onClick = { expanded = true }) {
            Text("${stringResource(R.string.order_filter)}: ${orderFilterTitle(selected)}")
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            OrderFilter.entries.forEach { filter ->
                DropdownMenuItem(
                    text = { Text(orderFilterTitle(filter)) },
                    onClick = {
                        expanded = false
                        if (filter != selected) onSelect(filter)
                    },
                )
            }
        }
    }
}

@Composable
private fun orderFilterTitle(filter: OrderFilter): String = stringResource(when (filter) {
    OrderFilter.ACTIVE -> R.string.filter_active
    OrderFilter.ALL -> R.string.filter_all
    OrderFilter.NEW -> R.string.filter_new
    OrderFilter.PREPARING -> R.string.status_preparing
    OrderFilter.READY -> R.string.status_ready
    OrderFilter.COMPLETED -> R.string.filter_completed
    OrderFilter.CANCELLED -> R.string.filter_cancelled
})

@Composable
private fun MenuEditorScreen(
    menu: MenuItem,
    content: MenuContent?,
    loading: Boolean,
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onCreateCategory: (String) -> Unit,
    onUpdateCategory: (Int, String, Boolean) -> Unit,
    onDeleteCategory: (Int) -> Unit,
    onCreateDish: (Int, String, String, String, Boolean) -> Unit,
    onUpdateDish: (MenuDish, String, String, String, Boolean) -> Unit,
    onDeleteDish: (Int) -> Unit,
) {
    var categoryName by remember(menu.id) { mutableStateOf("") }
    var selectedCategoryId by remember(menu.id) { mutableStateOf<Int?>(null) }
    var categoryToDelete by remember(menu.id) { mutableStateOf<MenuCategory?>(null) }
    val scope = rememberCoroutineScope()
    val selectedCategory = content?.categories?.firstOrNull { it.id == selectedCategoryId }
    BackHandler {
        if (selectedCategoryId != null) {
            selectedCategoryId = null
        } else {
            onBack()
        }
    }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onBack) { Text(stringResource(R.string.back)) }
            Text(menu.name, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Button(enabled = !loading, onClick = onRefresh) { Text(stringResource(R.string.refresh)) }
        }
        when {
            selectedCategoryId == null -> {
                OutlinedTextField(
                    value = categoryName,
                    onValueChange = { categoryName = it },
                    label = { Text(stringResource(R.string.category_name)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    enabled = categoryName.isNotBlank() && !loading,
                    onClick = {
                        onCreateCategory(categoryName.trim())
                        categoryName = ""
                    },
                ) { Text(stringResource(R.string.add_category)) }
                if (content == null && loading) {
                    CircularProgressIndicator()
                } else if (content?.categories.isNullOrEmpty()) {
                    Text(stringResource(R.string.empty_categories))
                }
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item {
                        Text(
                            stringResource(R.string.swipe_actions_hint),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    items(content?.categories.orEmpty(), key = { it.id }) { category ->
                        val dismissState = rememberSwipeToDismissBoxState()
                        SwipeToDismissBox(
                            state = dismissState,
                            modifier = Modifier.fillMaxWidth(),
                            enableDismissFromStartToEnd = false,
                            gesturesEnabled = !loading,
                            backgroundContent = {
                                Row(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .background(MaterialTheme.colorScheme.surfaceVariant),
                                    horizontalArrangement = Arrangement.End,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    TextButton(
                                        enabled = !loading,
                                        onClick = {
                                            onUpdateCategory(category.id, category.name, !category.isVisible)
                                            scope.launch { dismissState.reset() }
                                        },
                                    ) {
                                        Text(stringResource(
                                            if (category.isVisible) R.string.hide_item else R.string.show_item,
                                        ))
                                    }
                                    TextButton(
                                        enabled = !loading,
                                        onClick = {
                                            categoryToDelete = category
                                            scope.launch { dismissState.reset() }
                                        },
                                    ) {
                                        Text(
                                            stringResource(R.string.delete_category),
                                            color = MaterialTheme.colorScheme.error,
                                        )
                                    }
                                }
                            }
                        ) {
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                onClick = { selectedCategoryId = category.id },
                                enabled = !loading,
                            ) {
                                Row(
                                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(category.name, style = MaterialTheme.typography.titleMedium)
                                        Text(
                                            stringResource(R.string.category_dish_count, category.dishes.size),
                                        )
                                        if (!category.isVisible) {
                                            Text(stringResource(R.string.category_hidden))
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            selectedCategory != null -> CategoryEditorScreen(
                category = selectedCategory,
                loading = loading,
                onBack = { selectedCategoryId = null },
                onUpdate = onUpdateCategory,
                onCreateDish = onCreateDish,
                onUpdateDish = onUpdateDish,
                onDeleteDish = onDeleteDish,
            )

            else -> {
                TextButton(onClick = { selectedCategoryId = null }) {
                    Text(stringResource(R.string.back_to_categories))
                }
                if (loading) CircularProgressIndicator()
                else Text(stringResource(R.string.empty_categories))
            }
        }
    }
    categoryToDelete?.let { category ->
        AlertDialog(
            onDismissRequest = { categoryToDelete = null },
            title = { Text(stringResource(R.string.delete_category_confirmation)) },
            confirmButton = {
                TextButton(onClick = {
                    categoryToDelete = null
                    onDeleteCategory(category.id)
                }) {
                    Text(stringResource(R.string.delete_category), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { categoryToDelete = null }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
private fun CategoryEditorScreen(
    category: MenuCategory,
    loading: Boolean,
    onBack: () -> Unit,
    onUpdate: (Int, String, Boolean) -> Unit,
    onCreateDish: (Int, String, String, String, Boolean) -> Unit,
    onUpdateDish: (MenuDish, String, String, String, Boolean) -> Unit,
    onDeleteDish: (Int) -> Unit,
) {
    var name by remember(category.id) { mutableStateOf(category.name) }
    var isVisible by remember(category.id, category.isVisible) { mutableStateOf(category.isVisible) }
    var newDishName by remember(category.id) { mutableStateOf("") }
    var newDishDescription by remember(category.id) { mutableStateOf("") }
    var newDishPrice by remember(category.id) { mutableStateOf("") }
    var dishToDelete by remember(category.id) { mutableStateOf<MenuDish?>(null) }
    val scope = rememberCoroutineScope()
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        TextButton(onClick = onBack) { Text(stringResource(R.string.back_to_categories)) }
        Text(category.name, style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = name,
            onValueChange = { name = it },
            label = { Text(stringResource(R.string.category_name)) },
            modifier = Modifier.fillMaxWidth(),
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(R.string.category_visible),
                modifier = Modifier.weight(1f),
            )
            Switch(
                checked = isVisible,
                onCheckedChange = { isVisible = it },
                enabled = !loading,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = !loading && name.isNotBlank(),
                onClick = { onUpdate(category.id, name.trim(), isVisible) },
            ) {
                Text(stringResource(R.string.save_category))
            }
        }
        Text(stringResource(R.string.dishes), style = MaterialTheme.typography.titleMedium)
        Text(
            stringResource(R.string.swipe_actions_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(category.dishes, key = { it.id }) { dish ->
                val dismissState = rememberSwipeToDismissBoxState()
                SwipeToDismissBox(
                    state = dismissState,
                    modifier = Modifier.fillMaxWidth(),
                    enableDismissFromStartToEnd = false,
                    gesturesEnabled = !loading,
                    backgroundContent = {
                        Row(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(MaterialTheme.colorScheme.surfaceVariant),
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            TextButton(
                                enabled = !loading,
                                onClick = {
                                    onUpdateDish(
                                        dish,
                                        dish.name,
                                        dish.description,
                                        dish.price.orEmpty(),
                                        !dish.isVisible,
                                    )
                                    scope.launch { dismissState.reset() }
                                },
                            ) {
                                Text(stringResource(
                                    if (dish.isVisible) R.string.hide_item else R.string.show_item,
                                ))
                            }
                            TextButton(
                                enabled = !loading,
                                onClick = {
                                    dishToDelete = dish
                                    scope.launch { dismissState.reset() }
                                },
                            ) {
                                Text(
                                    stringResource(R.string.delete_dish),
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                    },
                ) {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            DishEditorCard(
                                dish = dish,
                                enabled = !loading,
                                onSave = onUpdateDish,
                            )
                        }
                    }
                }
            }
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedTextField(
                            value = newDishName,
                            onValueChange = { newDishName = it },
                            label = { Text(stringResource(R.string.dish_name)) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = newDishDescription,
                            onValueChange = { newDishDescription = it },
                            label = { Text(stringResource(R.string.dish_description)) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = newDishPrice,
                            onValueChange = { newDishPrice = it },
                            label = { Text(stringResource(R.string.dish_price)) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Button(
                            enabled = !loading && newDishName.isNotBlank(),
                            onClick = {
                                onCreateDish(category.id, newDishName.trim(), newDishDescription, newDishPrice, true)
                                newDishName = ""
                                newDishDescription = ""
                                newDishPrice = ""
                            },
                        ) { Text(stringResource(R.string.add_dish)) }
                    }
                }
            }
        }
    }
    dishToDelete?.let { dish ->
        AlertDialog(
            onDismissRequest = { dishToDelete = null },
            title = { Text(stringResource(R.string.delete_dish_confirmation)) },
            confirmButton = {
                TextButton(onClick = {
                    dishToDelete = null
                    onDeleteDish(dish.id)
                }) {
                    Text(stringResource(R.string.delete_dish), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { dishToDelete = null }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
private fun DishEditorCard(
    dish: MenuDish,
    enabled: Boolean,
    onSave: (MenuDish, String, String, String, Boolean) -> Unit,
) {
    var name by remember(dish.id) { mutableStateOf(dish.name) }
    var description by remember(dish.id) { mutableStateOf(dish.description) }
    var price by remember(dish.id) { mutableStateOf(dish.price.orEmpty()) }
    var isVisible by remember(dish.id, dish.isVisible) { mutableStateOf(dish.isVisible) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        OutlinedTextField(
            value = name,
            onValueChange = { name = it },
            label = { Text(stringResource(R.string.dish_name)) },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = description,
            onValueChange = { description = it },
            label = { Text(stringResource(R.string.dish_description)) },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = price,
            onValueChange = { price = it },
            label = { Text(stringResource(R.string.dish_price)) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        Row {
            Text(stringResource(R.string.dish_visible), modifier = Modifier.weight(1f))
            Switch(checked = isVisible, onCheckedChange = { isVisible = it }, enabled = enabled)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = enabled && name.isNotBlank(), onClick = {
                onSave(dish, name.trim(), description, price, isVisible)
            }) { Text(stringResource(R.string.save_dish)) }
        }
    }
}

@Composable
private fun OrderCard(order: OrderItem, enabled: Boolean, onStatus: (String) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row {
                Text(order.customer, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.weight(1f))
                Text(order.statusLabel)
            }
            Text("#${order.id} · ${order.menu} · ${order.total} ${order.currency}")
            Text(order.phone)
            if (order.note.isNotBlank()) Text(order.note)
            order.items.forEach { item ->
                Text("${item.quantity} × ${item.name} · ${item.total} ${order.currency}")
            }
            if (order.nextStatuses.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    order.nextStatuses.forEach { status ->
                        Button(enabled = enabled, onClick = { onStatus(status) }) {
                            Text(stringResource(statusTitle(status)))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun roleTitle(role: String): String = stringResource(
    when (role) {
        "owner" -> R.string.role_owner
        "manager" -> R.string.role_manager
        "admin" -> R.string.role_admin
        else -> R.string.role_unknown
    },
)

private fun statusTitle(status: String): Int = when (status) {
    "new" -> R.string.status_new
    "preparing" -> R.string.status_preparing
    "ready" -> R.string.status_ready
    "completed" -> R.string.status_completed
    "cancelled" -> R.string.status_cancelled
    else -> R.string.status_unknown
}
