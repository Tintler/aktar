// Gelistirme: arka uca pywebview yerine HTTP ile baglanir (Vite + tarayici; ?rpc=http://127.0.0.1:8765).
export function createRpc(base, emit) {
  const events = new EventSource(base + '/events');
  events.onmessage = (message) => {
    const { event, data } = JSON.parse(message.data);
    emit(event, data);
  };
  const api = {};
  return new Proxy(api, {
    get: (_target, name) => (name === 'then' ? undefined : async (...args) => {
      const response = await fetch(base + '/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ method: name, args }) });
      return response.json();
    }),
  });
}
