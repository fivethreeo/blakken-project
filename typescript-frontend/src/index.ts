import { initEveryLayout } from './everylayout/init';
import 'turnpage-book/styles.css';
import './index.scss';
import { initMenuReader } from './menu-reader';
import { initCart } from './cart';
import { initOrders } from './orders';

declare global {
  interface Window {
    menuReader?: Awaited<ReturnType<typeof initMenuReader>>;
  }
}

initEveryLayout();

const cl = document.body.classList;
cl.remove('no-js');
cl.add('with-js');

const cart = document.querySelector<HTMLElement>('[data-cart]');
if (cart) initCart(cart);
const orders = document.querySelector<HTMLElement>('[data-orders]');
if (orders) initOrders(orders);

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
