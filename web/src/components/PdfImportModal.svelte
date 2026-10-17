<script>
  // PDF'den kitap (F138): taranmis PDF okunur, EPUB yapilir; Okuma'da acilir ya da Kitap Cevir'e gider.
  // Durum app.pdfImport'ta (pencere kapansa da is surer, bitince bildirim gelir).
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, closePdfImport, finishPdfImport, openPdfReview, openSettings } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';

  const job = app.pdfImport;
  const info = $derived(job.info);
  const percent = $derived(job.progress?.total ? Math.round((job.progress.done * 100) / job.progress.total) : 0);

  async function start() {
    const result = await act('pdf_convert', info.path, job.title, job.author, job.target);
    if (result?.started) { job.running = true; job.progress = { stage: 'Başlıyor…', done: 0, total: info.pages }; }
  }
</script>

<Modal title="PDF'den kitap" width={600} onclose={closePdfImport}>
  <div class="file"><Icon name="fileText" size={20} /><div><b class="selectable">{info.name}</b>
    <small>{info.pages} sayfa{#if info.read} · {info.read} sayfası daha önce okunmuş, kaldığı yerden sürer{/if}</small></div></div>

  {#if job.result}
    {#if job.result.error}
      <div class="err"><Icon name="alert" size={16} /><span class="selectable">{job.result.error}</span></div>
    {:else}
      <div class="ok"><Icon name="check" size={16} />Kitap hazır: {job.result.chapters.length} bölüm · dil {job.result.language === 'tr' ? 'Türkçe' : 'İngilizce'}</div>
      <div class="chapters">{#each job.result.chapters as title, i}<span>{i + 1}. {title}</span>{/each}</div>
      {#if job.result.warnings?.length}
        <div class="warn-box">
          <b><Icon name="alert" size={14} />Kontrol edilecek sayfalar</b>
          {#each job.result.warnings as w}<span>{w.page}. sayfa — {w.reason}</span>{/each}
        </div>
      {/if}
      <small class="dim selectable">EPUB: {job.result.epub}</small>
    {/if}
  {:else if job.running}
    <div class="progress">
      <div class="row"><span>{job.progress?.stage}</span><span>{job.progress?.total ? `${job.progress.done} / ${job.progress.total}` : ''}</span></div>
      <div class="track"><i style:width="{percent}%"></i></div>
      <small class="dim">Pencereyi kapatabilirsiniz; okuma sürer, bitince haber verilir. Durdurursanız okunan sayfalar saklanır.</small>
    </div>
  {:else}
    <label class="fr"><span>Kitap adı</span><input class="field" bind:value={job.title} /></label>
    <label class="fr"><span>Yazar</span><input class="field" bind:value={job.author} /></label>
    <div class="fr"><span>Sonra</span>
      <div class="seg">
        <button class:on={job.target === 'reading'} onclick={() => (job.target = 'reading')}><Icon name="book" size={14} />Okuma'ya ekle</button>
        <button class:on={job.target === 'books'} onclick={() => (job.target = 'books')}><Icon name="bookA" size={14} />Kitap Çevir'de aç</button>
      </div>
    </div>
    <p class="hint">Sayfalar <b>{info.engine}</b> ile okunur; motoru <button class="link" onclick={() => { closePdfImport(); openSettings('library'); }}>Ayarlar → Kütüphane ve belgeler</button>
      bölümünden değiştirebilirsiniz. OCR modeli (ör. glm-ocr) daha doğru, Tesseract çok daha hızlıdır. Üst/alt bilgiler, sayfa numaraları ve bölünmüş kelimeler temizlenir;
      bölümler kitabın içindekilerinden ya da bölüm başlıklarından bulunur.</p>
  {/if}

  {#snippet footer()}
    {#if job.result}
      <button class="btn" onclick={closePdfImport}>Kapat</button>
      {#if !job.result.error}<button class="btn" onclick={() => openPdfReview(info.path, job.target)} title="Bölümleri ve sayfa metinlerini düzelt"><Icon name="pencil" size={15} />Gözden geçir</button>{/if}
      {#if !job.result.error}<button class="btn primary" onclick={finishPdfImport}>{job.result.target === 'books' ? "Kitap Çevir'de aç" : 'Okumaya başla'}</button>{/if}
    {:else if job.running}
      <button class="btn" onclick={() => call('pdf_cancel')}><Icon name="stop" size={15} />Durdur</button>
      <button class="btn primary" onclick={closePdfImport}>Arka planda sürsün</button>
    {:else}
      <button class="btn" onclick={closePdfImport}>İptal</button>
      {#if info.read >= info.pages}<button class="btn" onclick={() => openPdfReview(info.path, job.target)} title="Sayfalar okunmuş; bölümleri ve metni düzeltin"><Icon name="pencil" size={15} />Gözden geçir</button>{/if}
      <button class="btn primary" disabled={!job.title.trim()} onclick={start}>{info.read >= info.pages ? 'Kitabı yeniden oluştur' : 'Başlat'}</button>
    {/if}
  {/snippet}
</Modal>

<style>
  .file { display: flex; gap: 12px; align-items: center; }
  .file b, .file small { display: block; }
  .file small, .dim { color: var(--dim); font-size: 12px; }
  .fr { display: flex; align-items: center; gap: 14px; }
  .fr > span { width: 80px; flex: none; color: var(--secondary); font-size: 13px; }
  .fr .field { flex: 1; }
  .seg { display: flex; background: var(--surface); border-radius: 999px; padding: 3px; }
  .seg button { display: inline-flex; gap: 6px; align-items: center; padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; color: var(--secondary); }
  .seg button.on { background: var(--surface-active); color: var(--text); }
  .hint { color: var(--dim); font-size: 12px; line-height: 1.55; }
  .link { color: var(--accent); font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .progress .row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; }
  .progress .track { margin-bottom: 8px; }
  .ok, .err { display: flex; gap: 8px; align-items: center; font-size: 13px; font-weight: 600; }
  .ok { color: var(--ok); }
  .err { color: var(--danger); }
  .chapters { max-height: 180px; overflow: auto; display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--secondary);
    border: 1px solid var(--outline); border-radius: 10px; padding: 8px 12px; }
  .warn-box { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--secondary); max-height: 140px; overflow: auto;
    background: color-mix(in srgb, var(--warning) 8%, transparent); border-radius: 10px; padding: 8px 12px; }
  .warn-box b { display: flex; gap: 6px; align-items: center; color: var(--warning); }
</style>
