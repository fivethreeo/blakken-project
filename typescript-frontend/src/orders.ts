import { initShopStatus, type ShopState } from './shop';

interface Order {
  id: number;
  customer_name: string;
  phone: string;
  note: string;
  status: string;
  status_label: string;
  next_statuses: string[];
  total: string;
  created_at: string;
  status_url: string;
  items: { name: string; quantity: number; total: string }[];
}

interface OrderPage {
  results: Order[];
  page: number;
  pages: number;
  count: number;
}

const language = document.documentElement.lang.startsWith('en') ? 'en' : 'nb';
const locale = language === 'nb' ? 'nb-NO' : 'en-GB';
const messages = {
  nb: {
    preparing: 'Start tilberedning', ready: 'Merk som klar', completed: 'Fullfør', cancelled: 'Avbryt',
    open: 'Åpent for bestillinger', closed: 'Stengt for bestillinger',
    closeShop: 'Steng butikken', openShop: 'Åpne butikken',
    shopConflict: 'Butikkstatusen ble endret av noen andre. Kontroller statusen og prøv igjen.',
    shopUpdateFailed: 'Kunne ikke endre butikkstatus. Kontroller statusen og prøv igjen.',
    shopUpdateFailedShort: 'Kunne ikke endre butikkstatus.',
    accessEnded: 'Tilgangen er avsluttet. Logg inn på nytt.',
    ordersAuth: 'Du må være logget inn som ansatt for å se bestillinger.',
    ordersFetch: 'Kunne ikke hente bestillinger.',
    ordersRetry: 'Kunne ikke hente bestillinger. Prøver igjen automatisk.',
    page: 'Side {page} av {pages} · {count} bestillinger',
    cancelConfirm: 'Vil du avbryte bestilling #{id}? Dette kan ikke angres.',
    orderConflict: 'Bestillingen ble endret av noen andre. Listen oppdateres.',
    orderUpdateFailed: 'Kunne ikke endre status. Listen oppdateres; kontroller statusen og prøv igjen.',
    orderUpdateFailedShort: 'Kunne ikke endre status.',
  },
  en: {
    preparing: 'Start preparing', ready: 'Mark ready', completed: 'Complete', cancelled: 'Cancel',
    open: 'Open for orders', closed: 'Closed for orders',
    closeShop: 'Close ordering', openShop: 'Open ordering',
    shopConflict: 'Someone else changed the shop status. Check the status and try again.',
    shopUpdateFailed: 'Could not change the shop status. Check the status and try again.',
    shopUpdateFailedShort: 'Could not change the shop status.',
    accessEnded: 'Access has ended. Sign in again.',
    ordersAuth: 'You must be signed in as staff to view orders.',
    ordersFetch: 'Could not load orders.',
    ordersRetry: 'Could not load orders. Retrying automatically.',
    page: 'Page {page} of {pages} · {count} orders',
    cancelConfirm: 'Cancel order #{id}? This cannot be undone.',
    orderConflict: 'Someone else changed this order. The list is refreshing.',
    orderUpdateFailed: 'Could not update the status. The list is refreshing; check the status and try again.',
    orderUpdateFailedShort: 'Could not update the status.',
  },
} as const;
const t = (key: keyof typeof messages.en) => messages[language][key];
const labels: Record<string, string> = {
  preparing: t('preparing'), ready: t('ready'), completed: t('completed'), cancelled: t('cancelled'),
};
const money = (value: string) => new Intl.NumberFormat(locale, {
  style: 'currency', currency: 'NOK',
}).format(Number(value));

export function initOrders(root: HTMLElement) {
  const list = root.querySelector<HTMLElement>('[data-orders-list]')!;
  const error = root.querySelector<HTMLElement>('[data-orders-error]')!;
  const connection = root.querySelector<HTMLElement>('[data-orders-connection]')!;
  const filter = root.querySelector<HTMLSelectElement>('[data-orders-filter]')!;
  const template = root.querySelector<HTMLTemplateElement>('[data-order-card]')!;
  const previous = root.querySelector<HTMLButtonElement>('[data-orders-previous]')!;
  const next = root.querySelector<HTMLButtonElement>('[data-orders-next]')!;
  const cancelDialog = root.querySelector<HTMLDialogElement>('[data-order-cancel-dialog]')!;
  const cancelClose = cancelDialog.querySelector<HTMLButtonElement>('[data-order-cancel-close]')!;
  let cancellation: { order: Order; element: HTMLElement } | undefined;
  let readingPosition = { x: 0, y: 0 };
  let currentPage = 1;
  let request = 0;
  let updating = false;
  let stopped = false;
  let socket: WebSocket | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let retryDelay = 1000;
  const shopToggle = root.querySelector<HTMLButtonElement>('[data-shop-toggle]')!;
  const restaurantFilter = root.querySelector<HTMLSelectElement>('[data-restaurant-filter]');
  restaurantFilter?.addEventListener('change', () => {
    const url = new URL(location.href);
    if (restaurantFilter.value === 'all') url.searchParams.set('appid', 'all');
    else url.searchParams.set('appid', restaurantFilter.value);
    location.assign(url);
  });
  let shopOpen = true;
  let changingShop = false;
  function renderShop(status: ShopState) {
    shopOpen = status.is_open;
    root.querySelector('[data-shop-status]')!.textContent = shopOpen ? t('open') : t('closed');
    shopToggle.textContent = shopOpen ? t('closeShop') : t('openShop');
    shopToggle.disabled = changingShop || stopped;
  }
  const shop = root.dataset.shopUrl
    ? initShopStatus(root, renderShop)
    : { refresh: async () => {} };
  if (!root.dataset.shopUrl) shopToggle.hidden = true;

  shopToggle.addEventListener('click', () => {
    if (changingShop || stopped) return;
    changingShop = true;
    shopToggle.disabled = true;
    void (async () => {
      try {
        const response = await fetch(root.dataset.shopUrl!, {
          method: 'PATCH', credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': root.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')!.value,
          },
          body: JSON.stringify({ is_open: !shopOpen, expected_is_open: shopOpen }),
          signal: AbortSignal.timeout(15000),
        });
        if (response.status === 401 || response.status === 403) denied();
        if (!response.ok) throw new Error(response.status === 409
          ? t('shopConflict')
          : t('shopUpdateFailed'));
        renderShop(await response.json());
      } catch (reason) {
        error.textContent = reason instanceof Error ? reason.message : t('shopUpdateFailedShort');
        error.hidden = false;
      } finally {
        changingShop = false;
        await shop.refresh();
        shopToggle.disabled = stopped;
      }
    })();
  });

  function denied() {
    stopped = true;
    shopToggle.disabled = true;
    if (cancelDialog.open) closeCancellation();
    clearTimeout(retry);
    socket?.close();
    list.replaceChildren();
    connection.textContent = t('accessEnded');
  }

  async function refresh() {
    if (stopped) return;
    if (updating) return;
    const version = ++request;
    const url = new URL(root.dataset.ordersUrl!, location.href);
    url.searchParams.set('page', String(currentPage));
    url.searchParams.set('status', filter.value);
    if (root.dataset.restaurantAppid) {
      url.searchParams.set('appid', root.dataset.restaurantAppid);
    }
    try {
      const response = await fetch(url, {
        credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000),
      });
      if (response.status === 401 || response.status === 403) {
        denied();
        throw new Error(t('ordersAuth'));
      }
      if (response.status === 400 && currentPage > 1) {
        if (version !== request) return;
        currentPage = 1;
        return refresh();
      }
      if (!response.ok) throw new Error(t('ordersFetch'));
      const data: OrderPage = await response.json();
      if (version !== request || stopped) return;
      list.replaceChildren(...data.results.map(card));
      root.querySelector<HTMLElement>('[data-orders-empty]')!.hidden = data.results.length > 0;
      root.querySelector('[data-orders-page]')!.textContent = t('page')
        .replace('{page}', String(data.page))
        .replace('{pages}', String(data.pages))
        .replace('{count}', String(data.count));
      previous.disabled = data.page <= 1;
      next.disabled = data.page >= data.pages;
      error.hidden = true;
    } catch (reason) {
      if (version !== request) return;
      error.textContent = reason instanceof Error && reason.name === 'Error'
        ? reason.message : t('ordersRetry');
      error.hidden = false;
    }
  }

  function card(order: Order): HTMLElement {
    const element = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
    element.dataset.orderId = String(order.id);
    element.querySelector('[data-order-title]')!.textContent = `#${order.id}`;
    element.querySelector('[data-order-status]')!.textContent = order.status_label;
    const time = element.querySelector<HTMLTimeElement>('[data-order-created]')!;
    time.dateTime = order.created_at;
    time.textContent = new Date(order.created_at).toLocaleString(locale);
    element.querySelector('[data-order-customer]')!.textContent = order.customer_name;
    element.querySelector('[data-order-phone]')!.textContent = order.phone;
    const note = element.querySelector<HTMLElement>('[data-order-note]')!;
    note.textContent = order.note;
    note.hidden = !order.note;
    element.querySelector('[data-order-total]')!.textContent = money(order.total);
    for (const item of order.items) {
      const row = document.createElement('li');
      row.textContent = `${item.quantity} × ${item.name} — ${money(item.total)}`;
      element.querySelector('[data-order-items]')!.append(row);
    }
    for (const status of order.next_statuses) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = labels[status];
      button.dataset.orderNextStatus = status;
      button.addEventListener('click', () => {
        if (status === 'cancelled') {
          if (updating || stopped || cancelDialog.open) return;
          cancellation = { order, element };
          cancelDialog.querySelector('[data-order-cancel-message]')!.textContent =
            t('cancelConfirm').replace('{id}', String(order.id));
          readingPosition = { x: window.scrollX, y: window.scrollY };
          cancelDialog.showModal();
          cancelDialog.scrollTop = 0;
          cancelClose.focus({ preventScroll: true });
          window.scrollTo(readingPosition.x, readingPosition.y);
        } else {
          void update(order, status, element);
        }
      });
      element.querySelector('[data-order-actions]')!.append(button);
    }
    return element;
  }

  async function update(order: Order, status: string, element: HTMLElement) {
    if (updating || stopped) return;
    updating = true;
    ++request;
    error.hidden = true;
    element.setAttribute('aria-busy', 'true');
    list.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = true; });
    try {
      const response = await fetch(order.status_url, {
        method: 'PATCH', credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': root.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')!.value,
        },
        body: JSON.stringify({ status, expected_status: order.status }),
        signal: AbortSignal.timeout(15000),
      });
      if (response.status === 401 || response.status === 403) denied();
      if (!response.ok) throw new Error(response.status === 409
        ? t('orderConflict')
        : t('orderUpdateFailed'));
    } catch (reason) {
      error.textContent = reason instanceof Error ? reason.message : t('orderUpdateFailedShort');
      error.hidden = false;
    } finally {
      updating = false;
      element.removeAttribute('aria-busy');
      list.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = false; });
      const message = error.hidden ? '' : error.textContent;
      await refresh();
      if (message) { error.textContent = message; error.hidden = false; }
    }
  }

  function closeCancellation() {
    const pending = cancellation;
    cancellation = undefined;
    cancelDialog.close();
    const target = pending && list.querySelector<HTMLButtonElement>(
      `[data-order-id="${pending.order.id}"] [data-order-next-status="cancelled"]`,
    );
    (target || root.querySelector<HTMLButtonElement>('[data-orders-refresh]'))?.focus({ preventScroll: true });
    window.scrollTo(readingPosition.x, readingPosition.y);
  }

  cancelClose.addEventListener('click', closeCancellation);
  cancelDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeCancellation();
  });
  cancelDialog.querySelector('[data-order-cancel-confirm]')!.addEventListener('click', () => {
    const pending = cancellation;
    if (!pending || updating || stopped) return;
    closeCancellation();
    const element = list.querySelector<HTMLElement>(`[data-order-id="${pending.order.id}"]`) || pending.element;
    void update(pending.order, 'cancelled', element);
  });

  function connect() {
    const url = document.body.dataset.tsWsBackendUrl;
    if (stopped || !url) {
      if (!stopped) connection.textContent = 'Sanntid er ikke konfigurert. Listen oppdateres hvert 30. sekund.';
      return;
    }
    try {
      socket = new WebSocket(url);
    } catch {
      reconnect();
      return;
    }
    socket.addEventListener('open', () => {
      retryDelay = 1000;
      connection.textContent = 'Tilkoblet sanntidsoppdateringer.';
      void refresh();
    });
    socket.addEventListener('message', (event) => {
      try {
        if (JSON.parse(event.data).event === 'orders.changed') {
          void refresh();
        }
      } catch {}
    });
    socket.addEventListener('close', reconnect);
    socket.addEventListener('error', () => socket?.close());
  }

  function reconnect() {
    if (stopped) return;
    connection.textContent = 'Sanntidsforbindelsen er brutt. Kobler til igjen; listen oppdateres automatisk.';
    clearTimeout(retry);
    retry = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  }

  filter.addEventListener('change', () => { currentPage = 1; void refresh(); });
  previous.addEventListener('click', () => { currentPage = Math.max(1, currentPage - 1); void refresh(); });
  next.addEventListener('click', () => { currentPage++; void refresh(); });
  root.querySelector('[data-orders-refresh]')!.addEventListener('click', () => { void refresh(); void shop.refresh(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  const interval = setInterval(() => {
    if (!document.hidden) void refresh();
  }, 30000);
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearInterval(interval);
    clearTimeout(retry);
    socket?.close();
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) window.location.reload();
  });
  void refresh();
  connect();
}
