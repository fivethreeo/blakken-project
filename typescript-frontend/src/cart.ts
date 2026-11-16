import { initCustomerOrders } from './customer-orders';
import { initShopStatus } from './shop';

interface CartItem {
  dish_id: number;
  name: string;
  price: string;
  quantity: number;
}

interface Basket {
  submission_id: string;
  items: CartItem[];
}

const money = (value: number) => new Intl.NumberFormat('nb-NO', {
  style: 'currency', currency: 'NOK',
}).format(value / 100);

function submissionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function initCart(root: HTMLElement) {
  const notice = root.querySelector<HTMLElement>('[data-cart-flash]')!;
  const noticeMessage = notice.querySelector<HTMLElement>('[data-cart-flash-message]')!;
  let flashTimer: ReturnType<typeof setTimeout>;

  function flash(message: string, duration = 8000) {
    const host = Array.from(document.querySelectorAll<HTMLDialogElement>('dialog[open]')).pop()
      || document.body;
    if (notice.parentElement !== host) {
      notice.hidePopover();
      host.append(notice);
    }
    noticeMessage.textContent = message;
    if (!notice.matches(':popover-open')) notice.showPopover();
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => notice.hidePopover(), duration);
  }

  notice.querySelector('[data-cart-flash-close]')!.addEventListener('click', () => {
    clearTimeout(flashTimer);
    notice.hidePopover();
  });
  const tracking = initCustomerOrders(root);
  const dialog = root.querySelector<HTMLDialogElement>('[data-cart-dialog]')!;
  const form = root.querySelector<HTMLFormElement>('[data-cart-form]')!;
  const list = root.querySelector<HTMLElement>('[data-cart-items]')!;
  const error = root.querySelector<HTMLElement>('[data-cart-error]')!;
  const receipt = root.querySelector<HTMLElement>('[data-cart-receipt]')!;
  const submit = root.querySelector<HTMLButtonElement>('[data-cart-submit]')!;
  const closed = root.querySelector<HTMLElement>('[data-shop-closed]')!;
  let shopOpen = root.dataset.shopOpen !== 'false';
  const template = root.querySelector<HTMLTemplateElement>('[data-cart-row]')!;
  const key = `meny-basket-${root.dataset.menuId}`;
  const openButton = root.querySelector<HTMLButtonElement>('[data-cart-open]')!;
  let saving = false;
  let readingPosition = { x: 0, y: 0 };
  let basket: Basket = { submission_id: submissionId(), items: [] };

  try {
    const stored: Basket | null = JSON.parse(localStorage.getItem(key) || 'null');
    if (stored && typeof stored.submission_id === 'string'
      && /^[0-9a-f-]{36}$/i.test(stored.submission_id)
      && Array.isArray(stored.items) && stored.items.length <= 50
      && new Set(stored.items.map((item) => item?.dish_id)).size === stored.items.length
      && stored.items.every((item) => item && Number.isSafeInteger(item.dish_id) && item.dish_id > 0
        && Number.isInteger(item.quantity) && item.quantity > 0 && item.quantity <= 99
        && typeof item.name === 'string' && item.name.length <= 150
        && typeof item.price === 'string' && /^\d{1,6}\.\d{2}$/.test(item.price))) {
      basket = stored;
    }
  } catch {
    // Ordering still works when browser storage is unavailable.
  }

  function persist() {
    try { localStorage.setItem(key, JSON.stringify(basket)); } catch {}
  }

  function render() {
    list.replaceChildren();
    let total = 0;
    for (const item of basket.items) {
      const row = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
      row.dataset.cartDishId = String(item.dish_id);
      const price = Math.round(Number(item.price) * 100);
      row.querySelector('[data-cart-name]')!.textContent = item.name;
      row.querySelector('[data-cart-price]')!.textContent = `${money(price)} × ${item.quantity}`;
      const quantity = row.querySelector<HTMLOutputElement>('[data-cart-quantity]')!;
      quantity.textContent = String(item.quantity);
      quantity.setAttribute('aria-label', `Antall ${item.name}`);
      row.querySelectorAll<HTMLButtonElement>('[data-cart-row-action]').forEach((button) => {
        const action = button.dataset.cartRowAction!;
        const label = action === 'add' ? `Øk antall ${item.name}`
          : action === 'subtract' ? `Reduser antall ${item.name}` : `Fjern ${item.name} fra handlekurven`;
        button.setAttribute('aria-label', label);
        button.title = label;
        button.disabled = saving || (action === 'add' && item.quantity >= 99);
        button.addEventListener('click', () => {
          if (saving) return;
          item.quantity = action === 'delete' ? 0 : item.quantity + (action === 'add' ? 1 : -1);
          basket.items = basket.items.filter((entry) => entry.quantity > 0);
          basket.submission_id = submissionId();
          persist();
          render();
          const replacement = list.querySelector<HTMLButtonElement>(
            `[data-cart-dish-id="${item.dish_id}"] [data-cart-row-action="${action}"]`,
          );
          (replacement || list.querySelector<HTMLButtonElement>('button')
            || dialog.querySelector<HTMLButtonElement>('[data-cart-close]')!).focus({ preventScroll: true });
          flash(item.quantity
            ? `${item.name}: ${item.quantity} i handlekurven.`
            : `${item.name} er fjernet fra handlekurven.`);
        });
      });
      list.append(row);
      total += price * item.quantity;
    }
    const count = basket.items.reduce((sum, item) => sum + item.quantity, 0);
    const badge = root.querySelector<HTMLElement>('[data-cart-count]')!;
    badge.textContent = String(count);
    badge.hidden = count === 0;
    openButton.setAttribute('aria-label', `Åpne handlekurven (${count})`);
    openButton.title = `Åpne handlekurven (${count})`;
    root.querySelector('[data-cart-total]')!.textContent = money(total);
    root.querySelector<HTMLElement>('[data-cart-empty]')!.hidden = basket.items.length > 0;
    root.querySelector<HTMLElement>('[data-cart-summary]')!.hidden = !basket.items.length;
    list.hidden = !basket.items.length;
    form.hidden = !basket.items.length;
    submit.disabled = saving || basket.items.length === 0 || !shopOpen;
    submit.textContent = shopOpen ? 'Send bestilling' : 'Stengt for bestillinger';
    closed.hidden = shopOpen;
  }

  openButton.hidden = false;
  function openCart() {
    if (dialog.open) return;
    if (!saving) {
      error.hidden = true;
      render();
    }
    notice.hidePopover();
    readingPosition = { x: window.scrollX, y: window.scrollY };
    dialog.showModal();
    dialog.scrollTop = 0;
    dialog.querySelector<HTMLButtonElement>('[data-cart-close]')!.focus({ preventScroll: true });
    window.scrollTo(readingPosition.x, readingPosition.y);
  }
  openButton.addEventListener('click', openCart);
  function closeCart() {
    if (notice.parentElement === dialog) notice.hidePopover();
    dialog.close();
    window.scrollTo(readingPosition.x, readingPosition.y);
  }

  root.querySelector('[data-cart-close]')!.addEventListener('click', () => {
    if (!saving) closeCart();
  });
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    if (!saving) closeCart();
  });
  dialog.addEventListener('close', () => {
    if (notice.parentElement === dialog) notice.hidePopover();
    window.scrollTo(readingPosition.x, readingPosition.y);
  });

  document.addEventListener('click', (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>('button[data-cart-action="add"]') : null;
    if (!button || button.disabled || saving) return;
    event.preventDefault();
    const id = Number(button.dataset.dishId);
    const item = basket.items.find((entry) => entry.dish_id === id);
    if ((item && item.quantity >= 99) || (!item && basket.items.length >= 50)) {
      flash('Handlekurven har nådd maksimalt antall.');
      return;
    }
    if (item) item.quantity++;
    else basket.items.push({
      dish_id: id, quantity: 1, name: button.dataset.dishName!, price: button.dataset.dishPrice!,
    });
    basket.submission_id = submissionId();
    persist();
    render();
    flash(`${button.dataset.dishName} er lagt til. ${shopOpen
      ? 'Åpne handlekurven nederst til høyre for å bestille.'
      : 'Vi har stengt for bestillinger. Du kan endre handlekurven, men ikke sende bestillingen nå.'}`);
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!shopOpen) {
      flash('Vi har stengt for bestillinger. Prøv igjen når vi åpner.', 30000);
      return;
    }
    if (saving || !basket.items.length || !form.reportValidity()) return;
    const data = new FormData(form);
    const payload = {
      submission_id: basket.submission_id,
      customer_name: String(data.get('customer_name') || '').trim(),
      phone: String(data.get('phone') || '').trim(),
      note: String(data.get('note') || '').trim(),
      items: basket.items.map(({ dish_id, quantity }) => ({ dish_id, quantity })),
    };
    saving = true;
    error.hidden = true;
    dialog.setAttribute('aria-busy', 'true');
    form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea')
      .forEach((input) => { input.disabled = true; });
    render();
    void (async () => {
      try {
        const response = await fetch(root.dataset.orderUrl!, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': String(data.get('csrfmiddlewaretoken')) },
          body: JSON.stringify(payload), signal: AbortSignal.timeout(15000),
        });
        const result = await response.json();
        if (!response.ok) {
          if (result.error === 'shop_closed') {
            shopOpen = false;
            flash(result.message, 30000);
            throw new Error(result.message);
          }
          const messages = result.errors ? Object.values(result.errors).join(' ') : '';
          throw new Error(messages || (response.status === 409
            ? 'Denne bestillingen er allerede sendt med andre opplysninger.'
            : 'Kunne ikke sende bestillingen. Prøv igjen.'));
        }
        basket = { submission_id: submissionId(), items: [] };
        persist();
        form.reset();
        receipt.textContent = `Totalt: ${money(Math.round(Number(result.order.total) * 100))}`;
        receipt.dataset.orderId = String(result.order.id);
        receipt.hidden = false;
        closeCart();
        tracking.show();
        void tracking.refresh();
      } catch (reason) {
        error.textContent = reason instanceof Error && reason.name !== 'TimeoutError' && reason.name !== 'TypeError'
          ? reason.message
          : 'Kunne ikke bekrefte at bestillingen er mottatt. Prøv å sende igjen; samme bestilling lagres bare én gang.';
        error.hidden = false;
      } finally {
        saving = false;
        dialog.removeAttribute('aria-busy');
        form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input, textarea')
          .forEach((input) => { input.disabled = false; });
        render();
      }
    })();
  });
  render();
  let announced = false;
  initShopStatus(root, (status) => {
    const changed = shopOpen !== status.is_open;
    shopOpen = status.is_open;
    render();
    if (!announced || changed) flash(status.message, 30000);
    announced = true;
  });
}
