// Abonelik takibi (F106): etiketler ve bicimlendirme (veri subscriptions.py'de).
export const CURRENCIES = ['TRY', 'USD', 'EUR', 'GBP'];

export const CYCLES = {
  weekly: 'Haftalık', monthly: 'Aylık', quarterly: '3 ayda bir', semiannual: '6 ayda bir', yearly: 'Yıllık',
};

export const STATUSES = {
  active: { label: 'Aktif', tone: 'ok' },
  trial: { label: 'Deneme', tone: 'accent' },
  paused: { label: 'Durduruldu', tone: 'warning' },
  cancelled: { label: 'İptal edildi', tone: '' },
};

export const METHODS = {
  credit: { label: 'Kredi kartı', icon: 'creditCard' },
  debit: { label: 'Banka kartı', icon: 'creditCard' },
  transfer: { label: 'Havale / otomatik ödeme', icon: 'landmark' },
  cash: { label: 'Nakit', icon: 'wallet' },
  other: { label: 'Diğer', icon: 'wallet' },
};

const formats = new Map();

export function money(value, currency = 'TRY') {
  if (!formats.has(currency)) {
    formats.set(currency, new Intl.NumberFormat('tr-TR', { style: 'currency', currency, maximumFractionDigits: 2 }));
  }
  return formats.get(currency).format(value || 0);
}

export function shortDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function daysText(days) {
  if (days === null || days === undefined) return '';
  if (days === 0) return 'Bugün';
  if (days === 1) return 'Yarın';
  return `${days} gün sonra`;
}

// Pencereye birakilan gorsel: duzenleme penceresi aciksa logosu olur (handler'i pencere atar).
export const logoDrop = { handler: null };
