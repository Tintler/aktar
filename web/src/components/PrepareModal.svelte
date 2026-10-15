<script>
  // 'Hepsini hazirla' onayi (eski PrepareDialog): dosyalari yoklar, gruplara gore sayar, Whisper iznini sorar.
  import Modal from './Modal.svelte';
  import Toggle from './Toggle.svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, setLibrary } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';

  let { onclose } = $props();
  let summaries = $state(true);
  let vision = $state(true);
  let whisper = $state(false);
  let ocr = $state('');   // bos: Ayarlardaki motor (F85: yalnizca bu hazirlik icin degistirilebilir)
  const ENGINES = { tesseract: 'Tesseract (yerel)', model: 'OCR modeli (LM Studio)', vision: 'Görü modeli' };

  app.prepare = { loading: true };
  act('prepare_plan').then((info) => {
    if (!info) { app.prepare = null; onclose(); return; }
    app.prepare = { ...app.prepare, ...info, loading: false };
    whisper = info.whisper;
  });

  const p = $derived(app.prepare ?? {});
  const counts = $derived(p.counts);
  const rows = [
    ['ready', 'check', '', 'Zaten hazır', 'Önbellekten gelir, tekrar işlenmez'],
    ['summary', 'sparkles', '', 'Özeti ya da tarihi eksik', 'Transkript ve indeks hazır; özet (belgelerde belge tarihi) çıkarılır, özet seçeneği kapalıysa atlanır'],
    ['index', 'database', '', 'Yalnızca indekslenecek', 'Transkript hazır; embedding ile aranabilir yapılır'],
    ['document', 'fileText', '', 'Belgelerden metin', 'PDF metin katmanı, Word, Excel, EPUB ve metin dosyaları'],
    ['subtitle', 'subtitles', '', 'Gömülü altyazıdan', 'Hızlı · şarkı/yazı izleri atlanır, en uygun akış seçilir'],
    ['vision', 'image', 'warn', 'Taranmış PDF / görsel → OCR', 'Metni olmayan sayfalar ve görseller; yalnızca bu seçenek açıksa'],
    ['whisper', 'mic', 'warn', 'Altyazı yok → Whisper', 'Konuşma sesten metne çevrilir; yalnızca Whisper seçeneği açıksa'],
  ];
  const readyCount = $derived(counts ? counts.ready + (summaries ? 0 : counts.summary) : 0);
  const queued = $derived(counts ? (summaries ? counts.summary : 0) + counts.index + counts.document + counts.subtitle
    + (vision ? counts.vision : 0) + (whisper && p.whisper ? counts.whisper : 0) : 0);

  function close() {
    call('prepare_cancel');
    app.prepare = null;
    onclose();
  }

  async function start() {
    const state = await act('prepare_start', summaries, vision, whisper && p.whisper, ocr);
    app.prepare = null;
    if (state) setLibrary(state);
    onclose();
  }
</script>

<Modal title={p.files ? `${p.files} dosyayı hazırla` : 'Toplu hazırlık'} width={600} onclose={close}>
  <div class="counts">
    {#each rows as [key, icon, tone, label, hint]}
      <div class="count" title={hint}>
        <span class="ic {tone}" class:accent={key === 'ready'}><Icon name={icon} size={16} /></span>
        <span class="lbl">{label}<small>{key === 'whisper' && p.whisper_seconds ? `Toplam ${p.whisper_seconds} ses` : key === 'vision' && p.vision_pages ? `${p.vision_pages} sayfa/görsel` : hint}</small></span>
        <b class="mono">{counts ? (key === 'ready' ? readyCount : counts[key]) : '…'}</b>
      </div>
    {/each}
  </div>
  {#if !counts}
    <div class="probe">
      <div class="track"><i style:width="{p.total ? (p.done * 100) / p.total : 0}%"></i></div>
      <span class="dim">Dosyalar yoklanıyor{p.total ? ` ${p.done}/${p.total}` : ''}…</span>
    </div>
  {/if}
  {#if p.failed?.length}<p class="warn">{p.failed.length} dosya okunamadı ve atlanacak: {p.failed.slice(0, 3).join(', ')}</p>{/if}
  <div class="opts">
    <Toggle bind:checked={summaries} label="Dosya özetleri ve koleksiyon özeti çıkar" />
    <Toggle bind:checked={vision} label={`Taranmış PDF'leri ${ENGINES[ocr || p.ocr_engine] ?? 'OCR'} ile, görselleri görü modeliyle oku`} />
    <Toggle bind:checked={whisper} disabled={!p.whisper} label="Altyazısız videolarda Whisper kullan" />
    {#if vision && counts?.vision}
      <label class="engine">
        <span>Taranmış sayfalar için OCR motoru<small>Görseller her zaman görü modeliyle tarif edilir</small></span>
        <select class="field" bind:value={ocr}>
          <option value="">Ayarlardaki ({ENGINES[p.ocr_engine] ?? p.ocr_engine ?? 'otomatik'})</option>
          {#each Object.entries(ENGINES) as [id, label]}<option value={id}>{label}</option>{/each}
        </select>
      </label>
    {/if}
  </div>
  {#each p.warnings ?? [] as message}<p class="warn"><Icon name="alert" size={14} />{message}</p>{/each}
  {#snippet footer()}
    <button class="btn" onclick={close}>İptal</button>
    <button class="btn primary" disabled={!counts || (!queued && !summaries)} onclick={start}>
      <Icon name="sparkles" size={16} />Hazırlamayı başlat{counts ? ` (${queued} dosya)` : ''}</button>
  {/snippet}
</Modal>

<style>
  .counts { border: 1px solid var(--outline); border-radius: 10px; overflow: hidden; }
  .count { display: flex; align-items: center; gap: 12px; padding: 10px 14px; }
  .count + .count { border-top: 1px solid var(--outline); }
  .ic { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--surface); color: var(--secondary); flex: none; }
  .ic.accent { color: var(--accent); }
  .ic.warn { color: var(--warning); }
  .lbl { flex: 1; min-width: 0; font-size: 13px; font-weight: 500; }
  .lbl small { display: block; color: var(--dim); font-size: 11.5px; font-weight: 400; }
  .count b { font-size: 15px; min-width: 32px; text-align: right; }
  .probe { display: flex; flex-direction: column; gap: 6px; font-size: 12px; }
  .opts { display: flex; flex-direction: column; gap: 12px; }
  .engine { display: flex; align-items: center; gap: 12px; font-size: 13px; }
  .engine span { flex: 1; min-width: 0; }
  .engine small { display: block; color: var(--dim); font-size: 11.5px; }
  .engine select { width: 220px; }
  .warn { display: flex; gap: 8px; align-items: center; color: var(--warning); font-size: 12px; }
</style>
