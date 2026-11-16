import type { PageTurnController } from 'turnpage-book';

export function initPageEditor(root: HTMLElement, book: PageTurnController) {
  const dialog = root.ownerDocument.querySelector<HTMLDialogElement>('[data-page-editor]')!;
  const form = dialog.querySelector<HTMLFormElement>('[data-page-form]')!;
  const errorMessage = dialog.querySelector<HTMLElement>('[data-page-editor-error]')!;
  const title = dialog.querySelector<HTMLElement>('#page-editor-title')!;
  const label = dialog.querySelector<HTMLElement>('[data-page-editor-label]')!;
  const deletePrompt = dialog.querySelector<HTMLElement>('[data-page-delete-prompt]')!;
  const source = root.querySelector<HTMLElement>('[data-book-pages]')!;
  let opener: HTMLButtonElement | undefined;
  let saving = false;
  let deleting = false;

  function setBusy(busy: boolean) {
    saving = busy;
    if (busy) dialog.setAttribute('aria-busy', 'true');
    else dialog.removeAttribute('aria-busy');
    dialog.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLButtonElement>(
      'input, textarea, button',
    ).forEach((control) => { control.disabled = busy; });
  }

  function clearErrors() {
    errorMessage.hidden = true;
    form.querySelectorAll('[aria-invalid]').forEach((input) => {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    });
  }

  root.addEventListener('click', (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>('button[data-page-action="add"], button[data-page-action="delete"]') : null;
    if (!button) return;
    event.preventDefault();
    if (dialog.open || root.getAttribute('aria-busy') === 'true') return;
    opener = button;
    deleting = button.dataset.pageAction === 'delete';
    title.textContent = deleting ? 'Slett side' : 'Legg til side';
    label.textContent = deleting ? 'En endring i menyen' : 'Plass til flere gode smaker';
    form.hidden = deleting;
    deletePrompt.hidden = !deleting;
    if (deleting) {
      dialog.querySelector<HTMLElement>('[data-page-delete-message]')!.textContent =
        `Slett ${button.dataset.categoryName} med alle retter og fortsettelsessider? Dette kan ikke angres.`;
    }
    form.reset();
    clearErrors();
    setBusy(false);
    book.setClickToTurn(false);
    dialog.showModal();
    if (deleting) dialog.querySelector<HTMLButtonElement>('[data-page-delete-confirm]')!.focus();
    else form.querySelector<HTMLInputElement>('[name="name"]')!.focus();
  });

  dialog.querySelectorAll('[data-page-editor-close]').forEach((button) => {
    button.addEventListener('click', () => { if (!saving) dialog.close(); });
  });
  dialog.addEventListener('cancel', (event) => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    book.setClickToTurn(true);
    const target = source.hidden
      ? Array.from(root.querySelectorAll<HTMLButtonElement>('.book-links button'))
        .find((button) => button.getAttribute('aria-label') === opener?.getAttribute('aria-label'))
      : opener;
    (target ?? root.querySelector<HTMLCanvasElement>('canvas'))?.focus({ preventScroll: true });
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!saving && !deleting) void save();
  });

  dialog.querySelector('[data-page-delete-confirm]')!.addEventListener('click', () => {
    if (!saving && deleting) void remove();
  });

  async function remove() {
    if (!opener) return;
    clearErrors();
    setBusy(true);
    try {
      const response = await fetch(opener.dataset.deleteUrl!, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': source.dataset.csrfToken || '' },
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error('Unable to delete page.');
      const result: { category_slug: string } = await response.json();
      history.replaceState(null, '', `#${encodeURIComponent(result.category_slug)}`);
      window.location.reload();
    } catch {
      errorMessage.textContent = 'Kunne ikke slette siden. Last siden på nytt og prøv igjen.';
      errorMessage.hidden = false;
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!opener) return;
    setBusy(true);
    clearErrors();
    const data: Record<string, string | number> = {
      after_page_id: Number(opener.dataset.afterPageId),
    };
    form.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input[name], textarea[name]')
      .forEach((input) => { data[input.name] = input.value; });
    try {
      const response = await fetch(opener.dataset.createUrl!, {
        method: 'POST',
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
            errorMessage.textContent = Object.values(result.errors).flat().join(' ');
            errorMessage.hidden = false;
            for (const field of Object.keys(result.errors)) {
              Array.from(form.elements).filter((input) => input.getAttribute('name') === field)
                .forEach((input) => {
                  input.setAttribute('aria-invalid', 'true');
                  input.setAttribute('aria-describedby', 'page-editor-error');
                });
            }
            return;
          }
        }
        throw new Error('Unable to create page.');
      }
      const result: { page: { slug: string } } = await response.json();
      history.replaceState(null, '', `#${encodeURIComponent(result.page.slug)}`);
      window.location.reload();
    } catch {
      errorMessage.textContent = 'Kunne ikke legge til siden. Last siden på nytt før du prøver igjen.';
      errorMessage.hidden = false;
    } finally {
      setBusy(false);
      form.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }

  return dialog;
}
