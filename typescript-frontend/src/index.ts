import { initEveryLayout } from './everylayout/init';
import 'turnpage-book/styles.css';
import './index.scss';
import { initMenuReader } from './menu-reader';

declare global {
  interface Window {
    menuReader?: Awaited<ReturnType<typeof initMenuReader>>;
  }
}

initEveryLayout();

const cl = document.body.classList;
cl.remove('no-js');
cl.add('with-js');

const book = document.querySelector<HTMLElement>('[data-page-turn]');
if (book) void initMenuReader(book).then((reader) => { window.menuReader = reader; });

const mainNavToggle = document.querySelector<HTMLElement>('.main-nav-toggle');
const mainNav = document.querySelector<HTMLElement>('.main-nav');

if (mainNavToggle && mainNav) {
  mainNavToggle.hidden = false;
  mainNav.hidden = mainNavToggle.getAttribute('aria-expanded') !== 'true';
  mainNavToggle.addEventListener('click', () => {
    const expanded = mainNavToggle.getAttribute('aria-expanded') === 'true';
    mainNavToggle.setAttribute('aria-expanded', String(!expanded));
    mainNav.hidden = expanded;
  });
}
