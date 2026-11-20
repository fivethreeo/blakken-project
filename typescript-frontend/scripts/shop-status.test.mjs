import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setImmediate } from 'node:timers/promises';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/shop.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const appid = 'ca7a0000-0000-4000-8000-000000000001';

function setup(t, base, href) {
  const document = Object.assign(new EventTarget(), {
    hidden: false, body: { dataset: { tsWsBackendUrl: base } },
  });
  const window = new EventTarget();
  const sockets = [];
  const states = [];
  let open = true;
  let fetches = 0;
  class Socket extends EventTarget {
    constructor(url) {
      super();
      this.url = String(url);
      sockets.push(this);
    }
    close() { this.dispatchEvent(new Event('close')); }
  }
  const context = {
    exports: {}, URL, AbortSignal, document, window, location: new URL(href),
    WebSocket: Socket,
    fetch: async () => {
      fetches++;
      return { ok: true, json: async () => ({ is_open: open, message: '' }) };
    },
    setInterval() {}, clearInterval() {}, setTimeout() {}, clearTimeout() {},
  };
  runInNewContext(outputText, context);
  context.exports.initShopStatus(
    { dataset: { shopUrl: '/shop/status/', shopOpen: 'true', restaurantAppid: appid } },
    (status) => states.push(status),
  );
  t.after(() => window.dispatchEvent(new Event('pagehide')));
  return {
    document, sockets, states,
    get fetches() { return fetches; },
    closeShop() { open = false; },
  };
}

for (const [base, href, expected] of [
  ['/ws/', 'https://menu.example/orders/', 'wss://menu.example/ws/shop/'],
  ['/ws', 'http://menu.example/', 'ws://menu.example/ws/shop/'],
  ['/menu/ws/', 'https://menu.example/menu/', 'wss://menu.example/menu/ws/shop/'],
  ['ws://127.0.0.1:8002/', 'http://localhost:3000/', 'ws://127.0.0.1:8002/shop/'],
]) {
  test(`connects to ${expected} from ${base}`, (t) => {
    const { sockets } = setup(t, base, href);
    assert.equal(sockets.length, 1);
    assert.equal(sockets[0].url, `${expected}?appid=${appid}`);
  });
}

test('a live close hint refreshes availability without waiting for polling', async (t) => {
  const client = setup(t, '/ws/', 'https://menu.example/');
  await setImmediate();
  assert.equal(client.fetches, 1);
  client.closeShop();
  client.sockets[0].dispatchEvent(new MessageEvent('message', {
    data: JSON.stringify({ event: 'shop.changed' }),
  }));
  await setImmediate();
  assert.equal(client.fetches, 2);
  assert.equal(client.states.at(-1).is_open, false);
});
