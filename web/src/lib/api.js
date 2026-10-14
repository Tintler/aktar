// Python arka ucuyla (bridge.py) pywebview uzerinden konusma.
// Duz tarayicida (pywebview olmadan `npm run dev`) gelistirme icin sahte bir arka uc kullanilir.

const listeners = new Map();

window.__aktarEmit = (event, data) => {
  for (const fn of listeners.get(event) ?? []) fn(data);
};

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

let backend;

function ready() {
  if (backend) return backend;
  backend = new Promise((resolve) => {
    if (window.pywebview?.api) return resolve(window.pywebview.api);
    let settled = false;
    window.addEventListener('pywebviewready', () => {
      settled = true;
      resolve(window.pywebview.api);
    });
    // pywebview disinda: ?rpc=<adres> verildiyse gelistirme koprusu, yoksa sahte arka uc.
    setTimeout(async () => {
      if (settled || window.pywebview) return;
      const rpc = new URLSearchParams(location.search).get('rpc');
      if (rpc) {
        const { createRpc } = await import('./rpc.js');
        resolve(createRpc(rpc, window.__aktarEmit));
        return;
      }
      const { createMock } = await import('./mock.js');
      resolve(createMock(window.__aktarEmit));
    }, 600);
  });
  return backend;
}

export async function call(method, ...args) {
  const api = await ready();
  return api[method](...args);
}
