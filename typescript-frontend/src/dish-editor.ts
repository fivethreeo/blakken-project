import type { PageTurnController } from 'turnpage-book';

type DishResponse = {
  dish: { id: number; name: string; description: string; price: string | null; allergens: string[] };
  allergen_choices: [string, string][];
  create_url: string;
  category_slug: string;
};

export function initDishEditor(
  root: HTMLElement, book: PageTurnController, refresh: () => Promise<void>,
) {
  const dialog = root.ownerDocument.querySelector<HTMLDialogElement>('[data-dish-editor]')!;
  const form = dialog.querySelector<HTMLFormElement>('[data-dish-form]')!;
  const name = form.querySelector<HTMLInputElement>('[name="name"]')!;
  const description = form.querySelector<HTMLTextAreaElement>('[name="description"]')!;
  const price = form.querySelector<HTMLInputElement>('[name="price"]')!;
  const allergens = form.querySelector<HTMLElement>('[data-dish-allergens]')!;
  const loading = dialog.querySelector<HTMLElement>('[data-dish-editor-loading]')!;
  const errorMessage = dialog.querySelector<HTMLElement>('[data-dish-editor-error]')!;
  const title = dialog.querySelector<HTMLElement>('#dish-editor-title')!;
  const saveButton = dialog.querySelector<HTMLButtonElement>('[data-dish-save]')!;
  const addButton = dialog.querySelector<HTMLButtonElement>('[data-dish-add]')!;
  const deleteButton = dialog.querySelector<HTMLButtonElement>('[data-dish-delete]')!;
  const deletePrompt = dialog.querySelector<HTMLElement>('[data-dish-delete-prompt]')!;
  const source = root.querySelector<HTMLElement>('[data-book-pages]')!;
  let loadController: AbortController | undefined;
  let url = '';
  let dishId = '';
  let createUrl = '';
  let categorySlug = '';
  let creating = false;
  let saving = false;

  function showError(message: string) {
    errorMessage.textContent = message;
    errorMessage.hidden = false;
  }

  function clearErrors() {
    errorMessage.hidden = true;
    form.querySelectorAll('[aria-invalid]').forEach((input) => {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    });
  }

  function setBusy(busy: boolean) {
    saving = busy;
    dialog.toggleAttribute('aria-busy', busy);
    if (busy) dialog.setAttribute('aria-busy', 'true');
    dialog.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLButtonElement>(
      'input, textarea, button',
    ).forEach((control) => { control.disabled = busy; });
    if (!busy) {
      addButton.disabled = creating || Boolean(form.hidden);
      deleteButton.disabled = creating || Boolean(form.hidden);
    }
  }

  function reloadCategory() {
    history.replaceState(null, '', `#${encodeURIComponent(categorySlug)}`);
    window.location.reload();
  }

  async function open(button: HTMLButtonElement) {
    url = button.dataset.editUrl!;
    dishId = button.dataset.dishId!;
    creating = false;
    createUrl = '';
    categorySlug = '';
    title.textContent = 'Rediger rett';
    saveButton.textContent = 'Lagre endringer';
    form.reset();
    form.hidden = true;
    deletePrompt.hidden = true;
    clearErrors();
    setBusy(false);
    loading.hidden = false;
    const controller = new AbortController();
    loadController = controller;
    book.setClickToTurn(false);
    dialog.showModal();
    try {
      const response = await fetch(url, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) throw new Error('Unable to load dish.');
      const data: DishResponse = await response.json();
      if (controller.signal.aborted) return;
      createUrl = data.create_url;
      categorySlug = data.category_slug;
      name.value = data.dish.name;
      description.value = data.dish.description;
      price.value = data.dish.price ?? '';
      allergens.replaceChildren(...data.allergen_choices.map(([value, text]) => {
        const label = document.createElement('label');
        label.className = 'cluster align-items:center';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.name = 'allergens';
        checkbox.value = value;
        checkbox.checked = data.dish.allergens.includes(value);
        label.append(checkbox, document.createTextNode(text));
        return label;
      }));
      form.hidden = false;
      setBusy(false);
      name.focus();
    } catch {
      if (!controller.signal.aborted) {
        showError('Kunne ikke hente retten. Last siden på nytt og prøv igjen.');
      }
    } finally {
      if (!controller.signal.aborted) loading.hidden = true;
    }
  }

  root.addEventListener('click', (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>('button[data-dish-action="edit"]') : null;
    if (!button) return;
    event.preventDefault();
    if (!dialog.open && root.getAttribute('aria-busy') !== 'true') void open(button);
  });

  dialog.querySelectorAll('[data-dish-editor-close]').forEach((button) => {
    button.addEventListener('click', () => { if (!saving) dialog.close(); });
  });
  dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    loadController?.abort();
    book.setClickToTurn(true);
    const original = source.querySelector<HTMLButtonElement>(
      `[data-dish-action="edit"][data-dish-id="${dishId}"]`,
    );
    const focusTarget = source.hidden
      ? Array.from(root.querySelectorAll<HTMLButtonElement>('.book-links button'))
        .find((button) => button.getAttribute('aria-label') === original?.getAttribute('aria-label'))
      : original;
    (focusTarget ?? root.querySelector<HTMLCanvasElement>('canvas'))?.focus({ preventScroll: true });
  });

  addButton.addEventListener('click', () => {
    if (saving || !createUrl) return;
    creating = true;
    form.reset();
    clearErrors();
    deletePrompt.hidden = true;
    form.hidden = false;
    title.textContent = 'Legg til rett';
    saveButton.textContent = 'Legg til rett';
    setBusy(false);
    name.focus();
  });
  deleteButton.addEventListener('click', () => {
    if (saving || creating) return;
    clearErrors();
    form.hidden = true;
    deletePrompt.hidden = false;
    setBusy(false);
    dialog.querySelector<HTMLButtonElement>('[data-dish-confirm-delete]')!.focus();
  });
  dialog.querySelector('[data-dish-cancel-delete]')!.addEventListener('click', () => {
    if (saving) return;
    deletePrompt.hidden = true;
    form.hidden = false;
    setBusy(false);
    deleteButton.focus();
  });
  dialog.querySelector('[data-dish-confirm-delete]')!.addEventListener('click', () => {
    if (!saving) void remove();
  });

  async function remove() {
    clearErrors();
    setBusy(true);
    try {
      const response = await fetch(url, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': source.dataset.csrfToken || '' },
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error('Unable to delete dish.');
      reloadCategory();
    } catch {
      showError('Kunne ikke slette retten. Prøv igjen.');
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!saving) void save();
  });

  async function save() {
    setBusy(true);
    let saved = false;
    clearErrors();
    const data = {
      name: name.value,
      description: description.value,
      price: price.value || null,
      allergens: Array.from(form.querySelectorAll<HTMLInputElement>('[name="allergens"]:checked'))
        .map((input) => input.value),
    };
    try {
      const response = await fetch(creating ? createUrl : url, {
        method: creating ? 'POST' : 'PATCH',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': source.dataset.csrfToken || '',
        },
        body: JSON.stringify(data),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) {
        if (response.status === 400) {
          const result: { errors?: Record<string, string[]> } = await response.json();
          if (result.errors) {
            showError(Object.values(result.errors).flat().join(' '));
            for (const field of Object.keys(result.errors)) {
              Array.from(form.elements).filter((input) => input.getAttribute('name') === field)
                .forEach((input) => {
                  input.setAttribute('aria-invalid', 'true');
                  input.setAttribute('aria-describedby', 'dish-editor-error');
                });
            }
            return;
          }
        }
        throw new Error('Unable to save dish.');
      }
      saved = true;
      if (creating) {
        reloadCategory();
        return;
      }
      await refresh();
      dialog.close();
    } catch (error) {
      if (saved && error instanceof RangeError) {
        window.location.reload();
      } else {
        showError(saved
          ? 'Retten er lagret, men menyen kunne ikke oppdateres. Last siden på nytt.'
          : 'Kunne ikke lagre retten. Prøv igjen.');
      }
    } finally {
      setBusy(false);
      form.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }

  return dialog;
}
