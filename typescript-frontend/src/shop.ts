export interface ShopState {
  is_open: boolean;
  message: string;
}

export function initShopStatus(root: HTMLElement, onChange: (status: ShopState) => void) {
  let stopped = false;
  let request = 0;
  let socket: WebSocket | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let retryDelay = 1000;
  if (root.dataset.shopOpen === 'true' || root.dataset.shopOpen === 'false') {
    onChange({ is_open: root.dataset.shopOpen === 'true', message: root.dataset.shopMessage || '' });
  }

  async function refresh() {
    if (stopped) return;
    const version = ++request;
    try {
      const response = await fetch(root.dataset.shopUrl!, {
        credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) return;
      const status: ShopState = await response.json();
      if (!stopped && version === request) onChange(status);
    } catch {
      // Keep the last known state; checkout also enforces availability server-side.
    }
  }

  function connect() {
    const base = document.body.dataset.tsWsBackendUrl;
    const appid = root.dataset.restaurantAppid;
    if (stopped || !base || !appid || socket) return;
    try {
      const url = new URL(base.endsWith('/') ? base : `${base}/`, location.href);
      if (url.protocol === 'https:') url.protocol = 'wss:';
      else if (url.protocol === 'http:') url.protocol = 'ws:';
      url.pathname += 'shop/';
      url.searchParams.set('appid', appid);
      const client = new WebSocket(url);
      socket = client;
      client.addEventListener('open', () => {
        retryDelay = 1000;
        if (!document.hidden) void refresh();
      });
      client.addEventListener('message', (event) => {
        try {
          if (!document.hidden && JSON.parse(event.data).event === 'shop.changed') void refresh();
        } catch {}
      });
      client.addEventListener('error', () => client.close());
      client.addEventListener('close', () => {
        if (socket === client) socket = undefined;
        if (stopped) return;
        clearTimeout(retry);
        retry = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      });
    } catch {
      clearTimeout(retry);
      retry = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    }
  }

  const interval = setInterval(() => { if (!document.hidden) void refresh(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearInterval(interval);
    clearTimeout(retry);
    socket?.close();
  });
  void refresh();
  connect();
  return { refresh };
}
