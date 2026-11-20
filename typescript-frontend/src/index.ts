import { initEveryLayout } from './everylayout/init';
import './orders.scss';
import { initOrders } from './orders';

initEveryLayout();

const cl = document.body.classList;
cl.remove('no-js');
cl.add('with-js');

const orders = document.querySelector<HTMLElement>('[data-orders]');
if (orders) initOrders(orders);
