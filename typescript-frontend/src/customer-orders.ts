interface CustomerOrder {
  id: number;
  status: string;
  status_label: string;
  updated_at: string;
}

export function initCustomerOrders(root: HTMLElement) {
  const dialog = root.querySelector<HTMLDialogElement>('[data-order-status-dialog]')!;
  const panel = root.querySelector<HTMLElement>('[data-customer-orders]')!;
  const list = root.querySelector<HTMLElement>('[data-customer-order-list]')!;
  const template = root.querySelector<HTMLTemplateElement>('[data-customer-order-card]')!;
  const receipt = root.querySelector<HTMLElement>('[data-cart-receipt]')!;
  const connection = root.querySelector<HTMLElement>('[data-customer-order-connection]')!;
  const openButton = root.querySelector<HTMLButtonElement>('[data-order-status-open]')!;
  let orders = new Map<number, CustomerOrder>();
  const finished = new Map<number, CustomerOrder>();
  const highlighted = new Set<number>();
  const incomplete = (order: CustomerOrder) => !['completed', 'cancelled'].includes(order.status);
  let socket: WebSocket | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let retryDelay = 1000;
  let stopped = false;
  let fetching = false;
  let pending = false;
  let readingPosition = { x: 0, y: 0 };

  function show() {
    if (dialog.open) return;
    readingPosition = { x: window.scrollX, y: window.scrollY };
    dialog.showModal();
    dialog.scrollTop = 0;
    dialog.querySelector<HTMLButtonElement>('[data-order-status-close]')!.focus({ preventScroll: true });
    window.scrollTo(readingPosition.x, readingPosition.y);
  }

  function close() {
    dialog.close();
    finished.clear();
    highlighted.clear();
    render();
    window.scrollTo(readingPosition.x, readingPosition.y);
  }

  function render() {
    const visible = [...orders.values()].filter(incomplete).concat([...finished.values()]);
    visible.sort((a, b) => Number(highlighted.has(b.id)) - Number(highlighted.has(a.id)));
    list.replaceChildren(...visible.map((order) => {
      const card = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
      card.dataset.customerOrderId = String(order.id);
      card.querySelector('[data-customer-order-number]')!.textContent = `Bestilling #${order.id}`;
      card.querySelector('[data-customer-order-status]')!.textContent = order.status === 'new' ? 'Mottatt' : order.status_label;
      const descriptions: Record<string, string> = {
        new: 'Vi har mottatt bestillingen din.',
        preparing: 'Vi tilbereder maten din.',
        ready: 'Bestillingen din er klar.',
        completed: 'Bestillingen din er fullført.',
        cancelled: 'Bestillingen din er kansellert.',
      };
      card.querySelector('[data-customer-order-description]')!.textContent = descriptions[order.status] || '';
      return card;
    }));
    receipt.hidden = !visible.some((order) => String(order.id) === receipt.dataset.orderId);
    panel.hidden = !visible.length;
    openButton.hidden = !visible.length;
  }

  dialog.querySelector('[data-order-status-close]')!.addEventListener('click', close);
  openButton.addEventListener('click', show);
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener('close', () => window.scrollTo(readingPosition.x, readingPosition.y));

  function connect() {
    const base = document.body.dataset.tsWsBackendUrl;
    if (stopped || !Array.from(orders.values()).some(incomplete) || socket) return;
    if (!base) {
      connection.textContent = 'Status oppdateres automatisk hvert 30. sekund.';
      return;
    }
    try {
      const url = new URL(base.endsWith('/') ? base : `${base}/`, location.href);
      if (url.protocol === 'https:') url.protocol = 'wss:';
      else if (url.protocol === 'http:') url.protocol = 'ws:';
      url.pathname += 'orders/';
      const client = new WebSocket(url);
      socket = client;
      client.addEventListener('open', () => {
        retryDelay = 1000;
        connection.textContent = 'Status oppdateres live. Hold nettsiden åpen for statusoppdateringer.';
        void refresh();
      });
      client.addEventListener('message', (event) => {
        try {
          if (JSON.parse(event.data).event === 'orders.changed') void refresh();
        } catch {}
      });
      client.addEventListener('error', () => client.close());
      client.addEventListener('close', () => {
        if (socket === client) socket = undefined;
        reconnect();
      });
    } catch {
      reconnect();
    }
  }

  function reconnect() {
    if (stopped || !Array.from(orders.values()).some(incomplete)) return;
    connection.textContent = 'Forbindelsen er brutt. Kobler til igjen; status oppdateres automatisk.';
    clearTimeout(retry);
    retry = setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 15000);
  }

  async function refresh(): Promise<void> {
    if (stopped) return;
    if (fetching) { pending = true; return; }
    fetching = true;
    try {
      const response = await fetch(root.dataset.statusUrl!, {
        credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error('Unable to fetch customer orders.');
      const data: { results: CustomerOrder[] } = await response.json();
      if (stopped) return;
      const changed = data.results.filter((order) => {
        const previous = orders.get(order.id);
        return previous && incomplete(previous) && previous.status !== order.status;
      });
      for (const order of changed) {
        highlighted.add(order.id);
        if (!incomplete(order)) finished.set(order.id, order);
      }
      orders = new Map(data.results.map((order) => [order.id, order]));
      render();
      if (changed.length) {
        show();
      }
      if (data.results.some(incomplete)) connect();
      else {
        clearTimeout(retry);
        socket?.close();
      }
    } catch {
      connection.textContent = 'Kunne ikke hente status. Prøver igjen automatisk.';
    } finally {
      fetching = false;
      if (pending) {
        pending = false;
        void refresh();
      }
    }
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  const interval = setInterval(() => { if (!document.hidden) void refresh(); }, 30000);
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
  return { refresh, show };
}
