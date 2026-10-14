// Soz veren onay / bildirim / metin sorma pencereleri (components/ConfirmHost.svelte cizer).
export const pending = $state({ current: null });

export function confirm({ title, message, ok = 'Evet', cancel = 'Vazgeç', danger = false, list = null }) {
  return new Promise((resolve) => {
    pending.current = { kind: 'confirm', title, message, ok, cancel, danger, list, resolve };
  });
}

export function notice(title, message, list = null) {
  return confirm({ title, message, ok: 'Tamam', cancel: null, list });
}

// Tek satir (ya da `multiline`) metin ister; vazgecilirse null.
export function prompt({ title, message = '', value = '', ok = 'Tamam', placeholder = '', multiline = false }) {
  return new Promise((resolve) => {
    pending.current = { kind: 'prompt', title, message, value, ok, cancel: 'Vazgeç', placeholder, multiline, resolve };
  });
}

// Secenekler arasindan birini sectirir: options [{value, label}]; vazgecilirse null.
export function choose({ title, message = '', options, ok = 'Seç' }) {
  return new Promise((resolve) => {
    pending.current = { kind: 'choose', title, message, options, value: options[0]?.value, ok, cancel: 'Vazgeç', resolve };
  });
}
