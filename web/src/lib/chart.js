// F103: Sohbet cevabindaki ```chart bloklarini Chart.js ile cizer. Model kucuk bir JSON yazar:
// {"type":"bar","title":"...","unit":"TL","labels":[...],"series":[{"name":"2025","values":[...]}]}
// Turler: bar, hbar, stacked, line, area, pie, doughnut, radar, scatter. Yerel modeller sema
// disina tasabildigi icin bicim hosgorulu okunur (Chart.js'in kendi data/datasets bicimi de olur).
import Chart from 'chart.js/auto';

const TYPES = {
  bar: 'bar', column: 'bar', hbar: 'hbar', horizontalbar: 'hbar', horizontal_bar: 'hbar',
  stacked: 'stacked', stackedbar: 'stacked', stacked_bar: 'stacked',
  line: 'line', area: 'area', pie: 'pie', doughnut: 'doughnut', donut: 'doughnut',
  radar: 'radar', spider: 'radar', scatter: 'scatter',
  polar: 'polarArea', polararea: 'polarArea',
};
const ROUND = new Set(['pie', 'doughnut', 'polarArea']);

// Kategorik sira sabit (dataviz referans paleti); koyu temada koyu yuzeye gore adimlanmis hali.
const PALETTE = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
};

// "1.234,5" / "1,234.5" / "%12" / "12 TL" -> sayi; okunamazsa null.
export function toNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (value == null) return null;
  let text = String(value).replace(/[^\d.,-]/g, '');
  if (!/\d/.test(text)) return null;
  const comma = text.lastIndexOf(','), dot = text.lastIndexOf('.');
  if (comma > dot) text = text.replace(/\./g, '').replace(',', '.');
  else if (dot > comma && comma >= 0) text = text.replace(/,/g, '');
  else if (dot >= 0 && /^-?\d{1,3}(\.\d{3})+$/.test(text)) text = text.replace(/\./g, '');
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function point(value) {
  if (Array.isArray(value)) return { x: toNumber(value[0]), y: toNumber(value[1]) };
  if (value && typeof value === 'object') return { x: toNumber(value.x), y: toNumber(value.y) };
  return null;
}

// Model JSON'u -> {type, title, unit, x, y, labels, series:[{name, values}]}; gecersizse hata.
export function parseSpec(text) {
  let spec;
  try {
    spec = JSON.parse(String(text).trim().replace(/,\s*([}\]])/g, '$1'));
  } catch {
    throw new Error('Grafik verisi okunamadı (geçersiz JSON).');
  }
  if (!spec || typeof spec !== 'object') throw new Error('Grafik verisi boş.');
  const type = TYPES[String(spec.type ?? 'bar').toLowerCase().replace(/[\s-]/g, '')];
  if (!type) throw new Error(`Bilinmeyen grafik türü: ${spec.type}`);
  const data = spec.data && typeof spec.data === 'object' && !Array.isArray(spec.data) ? spec.data : spec;
  let labels = Array.isArray(data.labels) ? data.labels.map((l) => String(l)) : [];
  let raw = data.series ?? data.datasets;
  if (!Array.isArray(raw)) raw = Array.isArray(data.values ?? data.data) ? [{ values: data.values ?? data.data }] : [];
  if (raw.length && !raw.some((s) => s && typeof s === 'object' && !Array.isArray(s))) raw = [{ values: raw }];
  const series = raw.filter((s) => s && typeof s === 'object').map((s, i) => {
    const values = Array.isArray(s.values ?? s.data) ? (s.values ?? s.data) : [];
    return {
      name: String(s.name ?? s.label ?? (raw.length > 1 ? `Seri ${i + 1}` : spec.title ?? '')),
      values: type === 'scatter' ? values.map(point).filter((p) => p && p.x != null && p.y != null) : values.map(toNumber),
    };
  }).filter((s) => s.values.length);
  // {"labels":..., "values":{"A":1,"B":2}} gibi nesne bicimi
  if (!series.length && data.values && typeof data.values === 'object') {
    labels = Object.keys(data.values);
    series.push({ name: String(spec.title ?? ''), values: Object.values(data.values).map(toNumber) });
  }
  if (!series.length) throw new Error('Grafikte çizilecek sayı yok.');
  if (type !== 'scatter' && !labels.length) labels = series[0].values.map((_v, i) => String(i + 1));
  return {
    type, labels, series: series.slice(0, 8),
    title: spec.title ? String(spec.title) : '',
    unit: spec.unit ? String(spec.unit) : '',
    x: String(spec.x_label ?? spec.xLabel ?? spec.x ?? ''),
    y: String(spec.y_label ?? spec.yLabel ?? spec.y ?? ''),
  };
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const format = (value, unit) => {
  const text = typeof value === 'number' ? value.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) : String(value);
  return unit ? (unit === '%' ? `%${text}` : `${text} ${unit}`) : text;
};

function config(spec) {
  const dark = document.documentElement.dataset.base !== 'light';
  const colors = PALETTE[dark ? 'dark' : 'light'];
  const surface = css('--panel') || css('--window') || (dark ? '#111' : '#fff');
  const text = css('--secondary') || '#888';
  const grid = css('--outline') || '#8884';
  const round = ROUND.has(spec.type);
  const kind = { hbar: 'bar', stacked: 'bar', area: 'line' }[spec.type] ?? spec.type;
  const datasets = spec.series.map((s, i) => {
    const color = colors[i % colors.length];
    const base = { label: s.name, data: s.values };
    if (round) {
      return { ...base, backgroundColor: s.values.map((_v, j) => colors[j % colors.length]), borderColor: surface, borderWidth: 2 };
    }
    if (kind === 'bar') return { ...base, backgroundColor: color, borderRadius: 4, borderSkipped: 'start', maxBarThickness: 48 };
    if (kind === 'scatter') return { ...base, backgroundColor: color, pointRadius: 4, pointHoverRadius: 6 };
    if (kind === 'radar') {
      return { ...base, borderColor: color, backgroundColor: color + '33', borderWidth: 2, pointRadius: 3, pointBackgroundColor: color };
    }
    return { ...base, borderColor: color, backgroundColor: color + (spec.type === 'area' ? '40' : ''), borderWidth: 2,
      fill: spec.type === 'area' ? (spec.series.length > 1 ? 'stack' : 'origin') : false,
      tension: 0.25, pointRadius: s.values.length > 24 ? 0 : 3, pointHoverRadius: 5 };
  });
  const tick = { color: text, font: { size: 11 } };
  const axis = (title) => ({ grid: { color: grid }, border: { color: grid }, ticks: tick, title: { display: !!title, text: title, color: text } });
  const valueAxis = (title) => ({ ...axis(title), ticks: { ...tick, callback: (v) => format(v, spec.unit) } });
  let scales = {};
  if (kind === 'bar' || kind === 'line' || kind === 'scatter') {
    const horizontal = spec.type === 'hbar';
    const category = { ...axis(horizontal ? spec.y : spec.x), grid: { display: kind === 'scatter', color: grid } };
    const value = valueAxis(horizontal ? spec.x : spec.y);
    if (spec.type === 'stacked' || (spec.type === 'area' && spec.series.length > 1)) category.stacked = value.stacked = true;
    if (kind === 'scatter') scales = { x: valueAxis(spec.x), y: value };
    else scales = horizontal ? { x: value, y: category } : { x: category, y: value };
  } else if (kind === 'radar' || kind === 'polarArea') {
    scales = { r: { grid: { color: grid }, angleLines: { color: grid }, pointLabels: { color: text, font: { size: 11 } },
      ticks: { color: text, backdropColor: 'transparent', maxTicksLimit: 4, font: { size: 9 }, callback: (v) => format(v, spec.unit) } } };
  }
  const legend = round || spec.series.length > 1;
  return {
    type: kind,
    data: { labels: spec.type === 'scatter' ? undefined : spec.labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      indexAxis: spec.type === 'hbar' ? 'y' : 'x',
      interaction: round ? { mode: 'nearest', intersect: true } : { mode: kind === 'scatter' ? 'nearest' : 'index', intersect: false },
      scales,
      plugins: {
        title: { display: !!spec.title, text: spec.title, color: css('--text') || text, font: { size: 13, weight: '600' }, padding: { bottom: 10 } },
        legend: { display: legend, position: 'bottom', labels: { color: text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2 } },
        tooltip: {
          callbacks: {
            label(item) {
              const name = round ? item.label : item.dataset.label;
              const value = kind === 'scatter' ? `${format(item.parsed.x)}; ${format(item.parsed.y, spec.unit)}`
                : format(round || kind === 'radar' ? item.parsed.r ?? item.raw : (spec.type === 'hbar' ? item.parsed.x : item.parsed.y), spec.unit);
              return name ? `${name}: ${value}` : value;
            },
          },
        },
      },
    },
  };
}

// Svelte eylemi: dugumdeki .chart[data-spec] yer tutucularini cizer. {@html} icerigi her
// degistiginde (akis dahil) yeni yer tutucular gelir; tema degisince hepsi yeniden cizilir.
export function charts(node) {
  const live = new Map();
  function render(holder) {
    live.get(holder)?.destroy();
    try {
      const spec = parseSpec(holder.dataset.spec);
      if (!holder.firstChild) {
        holder.style.height = ROUND.has(spec.type) || spec.type === 'radar' ? '300px'
          : spec.type === 'hbar' ? `${Math.min(520, 90 + spec.labels.length * (18 + 8 * spec.series.length))}px` : '280px';
        holder.append(document.createElement('canvas'));
      }
      live.set(holder, new Chart(holder.firstChild, config(spec)));
    } catch (error) {
      live.delete(holder);
      holder.className = 'chart-error';
      holder.textContent = `${error.message}\n\n${holder.dataset.spec}`;
    }
  }
  function scan() {
    for (const [holder, chart] of live) if (!holder.isConnected) { chart.destroy(); live.delete(holder); }
    for (const holder of node.querySelectorAll('.chart[data-spec]')) if (!live.has(holder)) render(holder);
  }
  const observer = new MutationObserver(scan);
  observer.observe(node, { childList: true, subtree: true });
  const retheme = () => { for (const holder of live.keys()) render(holder); };
  window.addEventListener('aktar-theme', retheme);
  scan();
  return {
    destroy() {
      observer.disconnect();
      window.removeEventListener('aktar-theme', retheme);
      for (const chart of live.values()) chart.destroy();
    },
  };
}
