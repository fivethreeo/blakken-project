package no.blakken.restaurants.maharaja

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.Image
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { CustomerMenuScreen(lifecycle) }
    }
}

@Composable
private fun CustomerMenuScreen(lifecycle: Lifecycle) {
    val context = LocalContext.current
    val api = remember(context) { CustomerApi(context) }
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf<CustomerMenu?>(null) }
    var status by remember { mutableStateOf<ShopStatus?>(null) }
    var statusRequest by remember { mutableIntStateOf(0) }
    var quantities by remember { mutableStateOf(emptyMap<Int, Int>()) }
    var customerName by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var submissionId by remember { mutableStateOf(UUID.randomUUID().toString()) }
    var receipt by remember { mutableStateOf<OrderReceipt?>(null) }
    var loading by remember { mutableStateOf(true) }
    var submitting by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var showingCheckout by remember { mutableStateOf(false) }
    var shopStatusAlertIsOpen by remember { mutableStateOf<Boolean?>(null) }
    val menuScroll = rememberLazyListState()
    val checkoutScroll = rememberLazyListState()
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current

    BackHandler(enabled = showingCheckout) {
        if (!submitting) showingCheckout = false
    }

    fun changeQuantity(dishId: Int, quantity: Int) {
        if (status?.isOpen != true || submitting) return
        quantities = quantities.toMutableMap().apply {
            if (quantity <= 0) remove(dishId) else put(dishId, quantity.coerceAtMost(99))
        }
        receipt = null
        submissionId = UUID.randomUUID().toString()
    }

    suspend fun refreshStatus() {
        val request = ++statusRequest
        val updated = api.status()
        if (request == statusRequest) {
            if (status != null && status?.isOpen != updated.isOpen) {
                shopStatusAlertIsOpen = updated.isOpen
            }
            status = updated
        }
    }

    fun reload() {
        scope.launch {
            loading = true
            error = null
            try {
                menu = api.menu()
                refreshStatus()
            } catch (failure: Exception) {
                error = failure.localizedMessage ?: context.getString(R.string.request_failed)
            } finally {
                loading = false
            }
        }
    }

    fun submitOrder() {
        val loadedMenu = menu ?: return
        val open = status?.isOpen == true
        val name = customerName.trim()
        val telephone = phone.trim()
        if (!open || quantities.isEmpty() || name.isEmpty() || telephone.isEmpty() || submitting) return
        scope.launch {
            submitting = true
            error = null
            try {
                receipt = api.placeOrder(
                    menuId = loadedMenu.id,
                    submissionId = submissionId,
                    customerName = name,
                    phone = telephone,
                    note = note.trim(),
                    items = quantities.entries.map { it.key to it.value },
                )
                quantities = emptyMap()
                submissionId = UUID.randomUUID().toString()
            } catch (failure: Exception) {
                error = failure.localizedMessage ?: context.getString(R.string.request_failed)
            } finally {
                submitting = false
            }
        }
    }

    LaunchedEffect(Unit) { reload() }
    LaunchedEffect(api, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch {
                while (isActive) {
                    try {
                        refreshStatus()
                    } catch (failure: CancellationException) {
                        throw failure
                    } catch (_: Exception) {
                        // Keep the last known status while disconnected.
                    }
                    delay(30_000)
                }
            }
            launch {
                var retryDelay = 1_000L
                while (isActive) {
                    try {
                        api.shopUpdates().collect {
                            retryDelay = 1_000L
                            try {
                                refreshStatus()
                            } catch (failure: CancellationException) {
                                throw failure
                            } catch (_: Exception) {
                                // The periodic refresh can recover a missed hint.
                            }
                        }
                    } catch (failure: CancellationException) {
                        throw failure
                    } catch (_: Exception) {
                        // Retry the public subscription after connection failure.
                    }
                    delay(retryDelay)
                    retryDelay = (retryDelay * 2).coerceAtMost(15_000L)
                }
            }
        }
    }
    val dishMap = menu?.categories.orEmpty().flatMap { it.dishes }.associateBy { it.id }
    val cartItems = quantities.entries.mapNotNull { (id, quantity) ->
        dishMap[id]?.let { it to quantity }
    }
    val canEditOrder = status?.isOpen == true && !submitting
    val canSubmit = canEditOrder && cartItems.isNotEmpty()
        && customerName.isNotBlank() && phone.isNotBlank()

    LaunchedEffect(canEditOrder) {
        if (!canEditOrder) {
            focusManager.clearFocus()
            keyboard?.hide()
        }
    }

    MaterialTheme {
        if (shopStatusAlertIsOpen != null) {
            AlertDialog(
                onDismissRequest = { shopStatusAlertIsOpen = null },
                title = { Text(stringResource(if (shopStatusAlertIsOpen == true) R.string.open else R.string.closed)) },
                text = {
                    Text(stringResource(
                        if (shopStatusAlertIsOpen == true) R.string.shop_opened_message else R.string.shop_closed_message,
                    ))
                },
                confirmButton = {
                    TextButton(onClick = { shopStatusAlertIsOpen = null }) {
                        Text(stringResource(android.R.string.ok))
                    }
                },
            )
        }
        Column(
            modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (!showingCheckout) {
                Image(
                    painter = painterResource(R.drawable.blakken_logo),
                    contentDescription = stringResource(R.string.blakken_logo_description),
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().height(96.dp),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (showingCheckout) {
                    TextButton(
                        enabled = !submitting,
                        onClick = { showingCheckout = false },
                    ) { Text(stringResource(R.string.back_to_menu)) }
                }
                Text(
                    if (showingCheckout) stringResource(R.string.checkout)
                    else status?.restaurant ?: stringResource(R.string.app_name),
                    style = MaterialTheme.typography.headlineSmall,
                    modifier = Modifier.weight(1f),
                )
                if (!showingCheckout) {
                    Button(enabled = !loading && !submitting, onClick = ::reload) {
                        Text(stringResource(R.string.refresh))
                    }
                }
            }
            status?.let {
                Text(stringResource(if (it.isOpen) R.string.open else R.string.closed))
            }
            if (loading && menu == null) CircularProgressIndicator()
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (menu == null && !loading) {
                Text(stringResource(R.string.unavailable))
                Button(onClick = ::reload) { Text(stringResource(R.string.retry)) }
            }
            menu?.let { loadedMenu ->
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    state = if (showingCheckout) checkoutScroll else menuScroll,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (!showingCheckout) {
                        items(loadedMenu.categories, key = { it.id }) { category ->
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Column(
                                    modifier = Modifier.padding(12.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(category.name, style = MaterialTheme.typography.titleLarge)
                                    category.dishes.forEach { dish ->
                                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Text(
                                                    dish.name,
                                                    style = MaterialTheme.typography.titleMedium,
                                                    modifier = Modifier.weight(1f),
                                                )
                                                dish.price?.let { Text("$it ${stringResource(R.string.currency)}") }
                                                IconButton(
                                                    enabled = canEditOrder && dish.price != null
                                                        && (quantities[dish.id] ?: 0) < 99,
                                                    onClick = { changeQuantity(dish.id, (quantities[dish.id] ?: 0) + 1) },
                                                ) {
                                                    Icon(
                                                        painter = painterResource(R.drawable.add_to_cart),
                                                        contentDescription = stringResource(R.string.add_to_cart, dish.name),
                                                    )
                                                }
                                            }
                                            if (dish.description.isNotBlank()) {
                                                Text(dish.description, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        if (cartItems.isEmpty() && receipt == null) {
                            item { Text(stringResource(R.string.empty_cart)) }
                        }
                        items(cartItems, key = { it.first.id }) { (dish, quantity) ->
                            Card(modifier = Modifier.fillMaxWidth()) {
                                Column(
                                    modifier = Modifier.padding(12.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(dish.name, style = MaterialTheme.typography.titleMedium)
                                    dish.price?.let { Text("$it ${stringResource(R.string.currency)}") }
                                    val decreaseLabel = stringResource(R.string.remove_one)
                                    val increaseLabel = stringResource(R.string.add_one)
                                    Row(
                                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        IconButton(
                                            enabled = canEditOrder && quantity > 1,
                                            onClick = { changeQuantity(dish.id, quantity - 1) },
                                        ) {
                                            Text("-", modifier = Modifier.clearAndSetSemantics {
                                                contentDescription = decreaseLabel
                                            })
                                        }
                                        Text(
                                            stringResource(R.string.quantity_count, quantity),
                                            modifier = Modifier.weight(1f),
                                        )
                                        IconButton(
                                            enabled = canEditOrder && quantity < 99,
                                            onClick = { changeQuantity(dish.id, quantity + 1) },
                                        ) {
                                            Text("+", modifier = Modifier.clearAndSetSemantics {
                                                contentDescription = increaseLabel
                                            })
                                        }
                                    }
                                    TextButton(
                                        enabled = canEditOrder,
                                        onClick = { changeQuantity(dish.id, 0) },
                                    ) { Text(stringResource(R.string.remove_from_cart, dish.name)) }
                                }
                            }
                        }
                        receipt?.let { orderReceipt ->
                            item {
                                Card(modifier = Modifier.fillMaxWidth()) {
                                    Column(Modifier.padding(12.dp)) {
                                        Text(stringResource(R.string.confirmation), style = MaterialTheme.typography.titleMedium)
                                        Text("${stringResource(R.string.order_number)} #${orderReceipt.id}")
                                        Text("${orderReceipt.total} ${orderReceipt.currency}")
                                    }
                                }
                            }
                        }

                        if (cartItems.isNotEmpty()) {
                            item {
                                Card(modifier = Modifier.fillMaxWidth()) {
                                    Column(
                                        modifier = Modifier.padding(12.dp),
                                        verticalArrangement = Arrangement.spacedBy(8.dp),
                                    ) {
                                        Text(stringResource(R.string.checkout), style = MaterialTheme.typography.titleLarge)
                                        if (status?.isOpen != true) {
                                            Text(stringResource(R.string.closed))
                                        }
                                        OutlinedTextField(
                                            enabled = canEditOrder,
                                            value = customerName,
                                            onValueChange = {
                                                customerName = it
                                                submissionId = UUID.randomUUID().toString()
                                            },
                                            label = { Text(stringResource(R.string.customer_name)) },
                                            modifier = Modifier.fillMaxWidth(),
                                        )
                                        OutlinedTextField(
                                            enabled = canEditOrder,
                                            value = phone,
                                            onValueChange = {
                                                phone = it
                                                submissionId = UUID.randomUUID().toString()
                                            },
                                            label = { Text(stringResource(R.string.phone)) },
                                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                                            modifier = Modifier.fillMaxWidth(),
                                        )
                                        OutlinedTextField(
                                            enabled = canEditOrder,
                                            value = note,
                                            onValueChange = {
                                                note = it
                                                submissionId = UUID.randomUUID().toString()
                                            },
                                            label = { Text(stringResource(R.string.order_note)) },
                                            modifier = Modifier.fillMaxWidth(),
                                        )
                                        Button(enabled = canSubmit, onClick = ::submitOrder) {
                                            if (submitting) {
                                                CircularProgressIndicator()
                                            } else {
                                                Text(stringResource(R.string.place_order))
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                if (!showingCheckout) {
                    Button(
                        modifier = Modifier.fillMaxWidth(),
                        onClick = { showingCheckout = true },
                    ) {
                        Text(stringResource(R.string.checkout_count, cartItems.sumOf { it.second }))
                    }
                }
            }
        }
    }
}
