import { initPageTurn } from 'turnpage-book';
import { initDishEditor } from './dish-editor';
import { initPageEditor } from './page-editor';

export async function initMenuReader(root: HTMLElement) {
  const book = await initPageTurn(root, {
    clickToTurn: true, pageMargin: 0.03, animateInitialNavigation: false,
  });
  root.style.setProperty('--book-aspect', root.querySelector('canvas')!.style.getPropertyValue('--book-aspect'));
  const source = root.querySelector<HTMLElement>('[data-book-pages]')!;
  const dishError = root.querySelector<HTMLElement>('[data-dish-error]')!;
  let queue = Promise.resolve();
  let moving = false;

  function enqueue(operation: () => Promise<void>): Promise<void> {
    const result = queue.then(operation);
    queue = result.catch(() => {});
    return result;
  }

  async function replaceContent() {
    const response = await fetch(root.dataset.pagesUrl!, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`Unable to refresh menu (${response.status}).`);
    const document = new DOMParser().parseFromString(await response.text(), 'text/html');
    const incoming = document.querySelector<HTMLElement>('[data-book-pages]');
    if (!incoming) throw new Error('The menu response has no pages.');
    const pages = Array.from(source.querySelectorAll<HTMLElement>(':scope > [data-menu-page]'));
    const replacements = Array.from(incoming.querySelectorAll<HTMLElement>(':scope > [data-menu-page]'));
    const structureAttributes = [
      'data-menu-page', 'data-layout', 'data-panorama', 'data-toc-exclude', 'id', 'aria-labelledby', 'class',
    ];
    if (source.getAttribute('data-toc') !== incoming.getAttribute('data-toc')
      || pages.length !== replacements.length
      || pages.some((page, index) => structureAttributes.some((attribute) =>
        page.getAttribute(attribute) !== replacements[index].getAttribute(attribute)))) {
      throw new Error('Menu structure changed. Reload the page to reinitialize the book.');
    }
    source.dataset.csrfToken = incoming.dataset.csrfToken || '';

    // Turnpage retains the article nodes, including generated contents and blank pages.
    pages.forEach((page, index) => {
      const replacement = replacements[index];
      for (const attribute of Array.from(page.attributes)) {
        page.removeAttribute(attribute.name);
      }
      for (const attribute of Array.from(replacement.attributes)) {
        page.setAttribute(attribute.name, attribute.value);
      }
      page.replaceChildren(...Array.from(replacement.childNodes));
    });
    source.querySelectorAll<HTMLAnchorElement>('.toc-slide .toc-list a').forEach((link) => {
      const heading = Array.from(source.querySelectorAll<HTMLElement>('[data-menu-page] h2'))
        .find((candidate) => link.hash === `#${encodeURIComponent(candidate.id)}`);
      if (heading) link.textContent = heading.textContent;
    });
    await book.rerenderAll();
  }

  const editor = initDishEditor(root, book, () => enqueue(replaceContent));
  const pageEditor = initPageEditor(root, book);

  root.addEventListener('click', (event) => {
    const button = event.target instanceof Element
      ? event.target.closest<HTMLButtonElement>('button[data-dish-action], button[data-page-action]') : null;
    const pageMove = button?.dataset.pageAction === 'left' || button?.dataset.pageAction === 'right';
    const visibilityChange = button?.dataset.pageAction === 'visibility'
      || button?.dataset.dishAction === 'visibility';
    const direction = pageMove ? button?.dataset.pageAction : button?.dataset.dishAction;
    if (!button || (!visibilityChange && (!direction || !['up', 'down', 'left', 'right'].includes(direction)))) return;
    event.preventDefault();
    if (moving || editor.open || pageEditor.open) return;
    const pageKey = button.closest<HTMLElement>('[data-menu-page]')?.dataset.menuPage;
    moving = true;
    let saved = false;
    dishError.hidden = true;
    root.setAttribute('aria-busy', 'true');
    root.querySelectorAll<HTMLButtonElement>('.dish-actions button, .dish-visibility, .page-actions button, .dish-create, .book-links button')
      .forEach((control) => { control.disabled = true; });
    void enqueue(async () => {
      const response = await fetch(visibilityChange ? button.dataset.visibilityUrl! : button.dataset.moveUrl!, {
        method: visibilityChange ? 'PATCH' : 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': source.dataset.csrfToken || '',
          ...(visibilityChange ? { 'Content-Type': 'application/json' } : {}),
        },
        body: visibilityChange
          ? JSON.stringify({ is_visible: button.dataset.isVisible !== 'true' })
          : new URLSearchParams({ direction: direction! }),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error(`Unable to move dish (${response.status}).`);
      saved = true;
      if (pageMove) {
        history.replaceState(null, '', `#${encodeURIComponent(button.dataset.categorySlug!)}`);
        window.location.reload();
        return;
      }
      await replaceContent();
      if (visibilityChange) {
        const replacement = source.querySelector<HTMLButtonElement>(
          `[data-menu-page="${pageKey}"] `
          + `[data-visibility-url="${button.dataset.visibilityUrl}"]`,
        );
        const target = source.hidden
          ? Array.from(root.querySelectorAll<HTMLButtonElement>('.book-links button'))
            .find((control) => control.getAttribute('aria-label') === replacement?.getAttribute('aria-label'))
          : replacement;
        (target ?? root.querySelector<HTMLCanvasElement>('canvas'))?.focus({ preventScroll: true });
      }
    }).catch((error) => {
      if (visibilityChange && saved && error instanceof RangeError) {
        window.location.reload();
        return;
      }
      dishError.textContent = visibilityChange
        ? saved
          ? 'Synligheten er lagret, men menyen kunne ikke oppdateres. Last siden på nytt.'
          : 'Kunne ikke endre synligheten. Last siden på nytt og prøv igjen.'
        : pageMove
        ? 'Kunne ikke flytte siden. Last siden på nytt og prøv igjen.'
        : saved
          ? 'Retten er flyttet, men menyen kunne ikke oppdateres. Last siden på nytt.'
          : 'Kunne ikke flytte retten. Last siden på nytt og prøv igjen.';
      dishError.hidden = false;
    }).finally(() => {
      moving = false;
      root.removeAttribute('aria-busy');
      root.querySelectorAll<HTMLButtonElement>('.dish-actions button, .dish-visibility, .page-actions button, .dish-create, .book-links button')
        .forEach((control) => { control.disabled = false; });
    });
  });

  return {
    book,
    refresh(): Promise<void> {
      return enqueue(replaceContent);
    },
  };
}
