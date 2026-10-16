<script>
  // Kitap Cevir (Cevirgec ceviri ekrani): EPUB -> bolumler -> sozluk onayi -> (on analiz) -> ceviri.
  // Arka uc bridge_book.py; durum app.books'ta tutulur, sayfa degisince korunur.
  import Icon from '../lib/Icon.svelte';
  import Toggle from '../components/Toggle.svelte';
  import BookGlossaryModal from '../components/BookGlossaryModal.svelte';
  import BookAnalysisModal from '../components/BookAnalysisModal.svelte';
  import { app, act, applyBookSnapshot, onDrop, savePref, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm, notice } from '../lib/confirm.svelte.js';

  const ui = app.books;
  let preview = $state(null);
  let glossary = $state([]);
  let glossaryModal = $state(null);   // {rows, title, onsave, oncancel}
  let analysisModal = $state(null);   // {chapters, resolve}
  let menu = $state(null);            // {x, y, filename}
  let consoleEl = $state();

  const runtime = $derived(ui.status.runtime);
  const idle = $derived(runtime === 'idle');
  const hasBook = $derived(Boolean(ui.book.epub || ui.book.project));
  const progress = $derived(ui.status.progress);

  // ---- secim
  async function chooseEpub(path = null) {
    const r = await act('book_choose_epub', path);
    if (r) { applyBookSnapshot(r); ui.selected = null; preview = null; }
  }
  async function chooseFolder() { const r = await act('book_choose_folder'); if (r) applyBookSnapshot(r); }
  async function openProject(path = null) {
    const r = await act('book_open_project', path);
    if (r) { applyBookSnapshot(r); ui.selected = null; preview = null; loadGlossary(); }
  }

  // Pencereye birakilan EPUB acilir; ceviri klasoru birakilirsa proje surdurulur.
  onDrop('books', (paths) => {
    if (!idle) return toast('Çalışan çeviri tamamlanmadan seçim değiştirilemez.', 'error');
    const path = paths[0];
    if (/\.epub$/i.test(path)) chooseEpub(path);
    else openProject(path);
  });

  async function loadGlossary() {
    const r = ui.book.project ? await call('book_get_glossary') : null;
    glossary = r?.glossary ?? [];
  }

  // ---- baslat / duraklat / devam
  async function control() {
    if (!idle) { ui.status = await call('book_control'); return; }
    const prepared = await act('book_prepare');
    if (!prepared) return;
    if (prepared.glossary_required) {
      const ok = await new Promise((resolve) => {
        glossaryModal = {
          rows: prepared.glossary, title: 'Terim sözlüğü — çeviri öncesi',
          onsave: async (rows) => {
            const r = await call('book_confirm_glossary', rows);
            if (r?.error) return r.error;
            applyBookSnapshot(r); glossaryModal = null; resolve(true);
          },
          oncancel: async () => { glossaryModal = null; applyBookSnapshot(await call('book_cancel_prepare')); resolve(false); },
        };
      });
      if (!ok) return;
      loadGlossary();
    }
    const check = await call('book_model_check');
    if (check.block) { await notice('Model seçilmedi', check.block); return; }
    if (check.warn) await notice('LM Studio bağlantısı doğrulanamadı', check.warn);
    let files = null;
    if (ui.preAnalysis) {
      const candidates = await act('book_analysis_candidates');
      if (!candidates) return;
      files = await new Promise((resolve) => (analysisModal = { chapters: candidates.chapters, resolve }));
      analysisModal = null;
      if (!files) return;
    }
    const status = await act('book_start', files);
    if (status) { ui.status = status; ui.tab = files ? 'analysis' : 'status'; }
  }

  async function stop() {
    const yes = await confirm({
      title: 'Çeviri durdurulsun mu?',
      message: 'Geçerli istek bitince çeviri durur. Kaydedilen parçalar korunur; yeniden başlatınca kaldığı yerden sürer.',
      ok: 'Durdur', danger: true,
    });
    if (yes) ui.status = await call('book_stop');
  }

  function togglePreAnalysis(value) {
    savePref({ book_pre_analysis: value });
  }

  // ---- sozluk duzenleme
  async function editGlossary() {
    const r = await act('book_get_glossary');
    if (!r) return;
    glossaryModal = {
      rows: r.glossary, title: 'Terim sözlüğü',
      oncancel: () => (glossaryModal = null),
      onsave: async (rows) => {
        const result = await call('book_save_glossary', rows);
        if (result?.error) return result.error;
        glossaryModal = null;
        loadGlossary();
        if (!result.changed) { toast('Değişiklik yok; yeniden çeviri gerekmiyor.'); return; }
        if (!result.affected.length) {
          toast('Sözlük kaydedildi. Değişen terimler çevrilmiş bölümlerde geçmiyor; kalan bölümler yeni sözlükle çevrilecek.', 'ok');
          return;
        }
        const yes = await confirm({
          title: 'Sözlük güncellendi',
          message: `Değişen terimlerin geçtiği ${result.affected.length} çevrilmiş bölüm yeniden çevrilsin mi?\n` +
            'Bu bölümler sonraki bölümlerin bağlamı olmadan yeniden çevrilir; yarım kalmış bölümün kaydı korunur.',
          list: result.affected, ok: 'Yeniden çevir', cancel: 'Şimdi değil',
        });
        if (yes) { const s = await act('book_rerun', result.affected); if (s) { ui.status = s; ui.tab = 'status'; } }
      },
    };
  }

  // ---- bolumler
  function select(filename) {
    ui.selected = filename;
    ui.tab = 'preview';
  }

  // Secim degisince ve bolum durumlari degisince (bir bolum bitti) onizleme yenilenir.
  $effect(() => {
    ui.chapters;
    const filename = ui.selected;
    if (filename) call('book_preview', filename).then((p) => { if (ui.selected === filename) preview = p; });
  });

  $effect(() => {
    ui.book.project;
    loadGlossary();
  });

  function contextMenu(event, filename) {
    event.preventDefault();
    menu = { x: event.clientX, y: event.clientY, filename };
  }

  async function rerunChapter(filename) {
    menu = null;
    if (!idle) { toast('Çalışan çeviri tamamlanmadan bölüm yeniden çevrilemez.', 'error'); return; }
    if (!(await act('book_validate_rerun', filename))) return;
    const yes = await confirm({
      title: 'Bölümü yeniden çevir',
      message: `"${filename}" bölümü yeniden çevrilecek. Mevcut çeviri _python_translation/${filename}/recheck-prev-<tarih>.md olarak yedeklenir; ` +
        'sonraki bölümlerin bağlamı (özet/notlar) bu çeviriye verilmez. Bitince TAM-CEVIRI.md (ve kitap tamamsa EPUB) yeniden üretilir.',
      ok: 'Yeniden çevir', cancel: 'Vazgeç',
    });
    if (yes) { const s = await act('book_rerun', [filename]); if (s) { ui.status = s; ui.tab = 'status'; } }
  }

  // ---- onizlemede sozluk terimlerini vurgulama
  const escapeHtml = (text) => text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function highlight(text, terms) {
    const html = escapeHtml(text);
    const list = terms.filter(Boolean).map((t) => escapeHtml(t)).sort((a, b) => b.length - a.length);
    if (!list.length) return html;
    const re = new RegExp(`(?<![\\p{L}\\p{N}])(${list.map(escapeRe).join('|')})`, 'giu');
    return html.replace(re, '<mark>$1</mark>');
  }

  const sourceHtml = $derived(preview ? highlight(preview.source, glossary.map((g) => g.source)) : '');
  const translationHtml = $derived(preview?.translated ? highlight(preview.translation, glossary.map((g) => g.target)) : '');

  // ---- gunluk kendiliginden asagi kayar
  $effect(() => {
    ui.log.length;
    if (consoleEl && ui.tab === 'console') queueMicrotask(() => (consoleEl.scrollTop = consoleEl.scrollHeight));
  });

  const controlLabel = $derived({ idle: 'Çeviriyi başlat', running: 'Duraklat', pausing: 'Duraklatılıyor…', paused: 'Devam et', closing: 'Duruyor…' }[runtime] ?? runtime);
  const badgeClass = { done: 'ok', active: 'accent', partial: 'warning' };
  const fmt = (n) => Number(n || 0).toLocaleString('tr-TR');
</script>

<svelte:window onclick={() => (menu = null)} />

<section class="page">
  <div class="page-head">
    <h1>Kitap Çevir</h1>
    <button class="btn" disabled={!idle} onclick={() => openProject()} title="Daha önce oluşturulmuş {'{'}KitapAdı{'}'}-ceviri klasörünü açar ve kayıtlı kontrol noktalarından devam eder.">
      <Icon name="history" size={16} />Projeyi sürdür</button>
    <button class="btn" disabled={!idle} onclick={() => chooseEpub()}><Icon name="book" size={16} />EPUB aç</button>
  </div>

  <div class="page-body body">
    {#if !hasBook}
      <button class="drop card" onclick={() => chooseEpub()}>
        <span class="tile"><Icon name="book" size={30} /></span>
        <b>EPUB'u buraya bırakın</b>
        <span class="dim">ya da tıklayıp seçin · çeviri klasörü bırakılırsa proje sürdürülür</span>
        <span class="note">DRM içermeyen bir EPUB bölümlerine ayrılır ve LM Studio'daki modelle Türkçeye çevrilir. Terim sözlüğü, isteğe bağlı ön analiz ve
          bölüm notlarıyla tutarlılık korunur; her parça kaydedildiği için çeviri kaldığı yerden sürer. Sonuç Türkçe EPUB olarak yazılır, kaynak dosya değiştirilmez.</span>
      </button>
    {:else}
      <div class="card book">
        <div class="cover">
          {#if ui.book.cover}<img src={ui.book.cover} alt="" />{:else}<span>{ui.book.title}</span>{/if}
        </div>
        <div class="meta">
          <div class="t">{ui.book.title || 'Adsız kitap'}</div>
          <div class="a">{[ui.book.author, progress.total ? `${progress.total} bölüm` : '', ui.book.chars ? `${fmt(ui.book.chars)} karakter` : ''].filter(Boolean).join(' · ')}</div>
          <div class="paths">
            <button class="path" disabled={!idle} onclick={() => chooseEpub()} title="Kaynak EPUB'u değiştir">
              <Icon name="file" size={14} /><span class="selectable">{ui.book.epub || '—'}</span></button>
            <button class="path" disabled={!idle} onclick={chooseFolder} title="Çalışma klasörünü değiştir">
              <Icon name="folder" size={14} /><span class="selectable">{ui.book.folder || 'Çalışma klasörü seçin'}</span></button>
            {#if ui.book.project}
              <button class="path" onclick={() => act('reveal', ui.book.project)} title="Çeviri klasörünü dosya yöneticisinde aç">
                <Icon name="folderOpen" size={14} /><span>Çeviri klasörünü aç</span></button>
            {/if}
          </div>
        </div>
        <div class="stats">
          <div class="stat"><b>{progress.done} / {progress.total || '—'}</b><small>bölüm</small></div>
          <div class="stat"><b>%{progress.percent}</b><small>tamamlandı</small></div>
        </div>
      </div>

      <div class="work">
        <div class="card col">
          <div class="card-h">Bölümler <span class="sp"></span><small>{ui.chapters.filter((c) => c.type === 'chapter').length || ''}</small></div>
          <div class="chapters">
            {#each ui.chapters as item}
              {#if item.type === 'group'}
                <div class="group" style:padding-left="{10 + item.depth * 14}px">{item.label}</div>
              {:else}
                <button class="ch" class:sel={ui.selected === item.filename} style:padding-left="{10 + item.depth * 14}px"
                  onclick={() => select(item.filename)} oncontextmenu={(e) => contextMenu(e, item.filename)} title={item.filename}>
                  <span class="n">{item.title}</span><span class="badge {badgeClass[item.kind] ?? ''}">{item.label}</span>
                </button>
              {/if}
            {:else}
              <div class="empty">Bölümler çeviri başladığında EPUB'dan ayrılır.</div>
            {/each}
          </div>
        </div>

        <div class="card col">
          <div class="tabs">
            {#each [['preview', 'Kaynak / Türkçe'], ['status', 'Durum'], ['analysis', 'Ön analiz'], ['console', 'Günlük']] as [key, label]}
              <button class="chip" class:on={ui.tab === key} onclick={() => (ui.tab = key)}>{label}</button>
            {/each}
          </div>

          {#if ui.tab === 'preview'}
            {#if preview}
              <div class="pv">
                <div><div class="lbl"><span>Kaynak · İngilizce</span><span>{fmt(preview.source_chars)} karakter</span></div>
                  <div class="txt selectable">{@html sourceHtml}</div></div>
                <div><div class="lbl"><span>Çeviri · Türkçe</span><span>{fmt(preview.translation_chars)} karakter</span></div>
                  <div class="txt selectable tr">{#if preview.translated}{@html translationHtml}{:else}<span class="muted">Henüz çevrilmedi.</span>{/if}</div></div>
              </div>
            {:else}
              <div class="empty grow">Kaynak metni ve çeviriyi görmek için soldan bir bölüm seçin.<br />Bir bölümü yeniden çevirmek için sağ tıklayın.</div>
            {/if}
          {:else if ui.tab === 'status'}
            <div class="status">
              <div class="tile-s"><small>Aşama</small><b>{ui.status.phase}</b></div>
              <div class="tile-s wide"><small>Geçerli adım</small><b>{ui.status.current || '—'}</b></div>
              <div class="tile-s"><small>Tamamlanan bölüm</small><b>{progress.done} / {progress.total}</b></div>
              <div class="tile-s"><small>Son kayıt</small><b>{ui.status.last_saved || '—'}</b></div>
              <div class="tile-s"><small>İlerleme</small><b>%{progress.percent}</b></div>
            </div>
          {:else if ui.tab === 'analysis'}
            <div class="mono-box selectable">{ui.analysis || 'Ön analiz seçilirse sonuç burada gösterilir.'}</div>
          {:else}
            <div class="mono-box selectable" bind:this={consoleEl}>
              {#each ui.log as line}<div class:warn={/UYARI|HATA|Traceback/i.test(line)} class:ok={/kaydedildi|tamamlandı/i.test(line)}>{line}</div>{/each}
              {#if !ui.log.length}<span class="muted">Henüz kayıt yok.</span>{/if}
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </div>

  <div class="bar">
    <button class="btn" disabled={!idle || !ui.book.project} onclick={editGlossary}><Icon name="dict" size={16} />Terim sözlüğü</button>
    <span title="İsteğe bağlıdır. Kitap çeviriden önce analiz edilir ve toplam işlem süresi iki kata kadar uzayabilir.">
      <Toggle bind:checked={ui.preAnalysis} disabled={!idle} label="Ön analiz" onchange={togglePreAnalysis} /></span>
    <div class="prog">
      <span>Son kayıt {ui.status.last_saved || '—'}</span>
      <div class="track"><i style:width="{progress.percent}%"></i></div>
      <span>%{progress.percent}</span>
    </div>
    {#if runtime === 'running' || runtime === 'paused' || runtime === 'pausing'}
      <button class="btn" onclick={stop}><Icon name="stop" size={16} />Durdur</button>
    {/if}
    <button class="btn primary lg" disabled={!hasBook || runtime === 'pausing' || runtime === 'closing'} onclick={control}>
      <Icon name={runtime === 'running' ? 'pause' : 'play'} size={16} />{controlLabel}</button>
  </div>
</section>

{#if menu}
  <div class="menu" style:left="{menu.x}px" style:top="{menu.y}px">
    <button onclick={() => rerunChapter(menu.filename)}><Icon name="rotate" size={15} />Bu bölümü yeniden çevir</button>
  </div>
{/if}

{#if glossaryModal}
  <BookGlossaryModal rows={glossaryModal.rows} title={glossaryModal.title} onsave={glossaryModal.onsave} oncancel={glossaryModal.oncancel} />
{/if}
{#if analysisModal}
  <BookAnalysisModal chapters={analysisModal.chapters} onconfirm={(f) => analysisModal.resolve(f)} oncancel={() => analysisModal.resolve(null)} />
{/if}

<style>
  .body { display: flex; flex-direction: column; gap: 16px; overflow: hidden; }

  .drop { flex: 1; min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
    border: 2px dashed var(--outline); background: transparent; color: var(--text); }
  .drop:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 4%, transparent); }
  .drop b { font-size: 20px; }
  .drop .dim { color: var(--dim); }
  .drop .note { color: var(--secondary); font-size: 13px; max-width: 560px; text-align: center; margin-top: 10px; line-height: 1.6; }
  .tile { width: 64px; height: 64px; border-radius: 12px; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }

  .book { display: flex; gap: 18px; align-items: center; padding: 16px; flex: none; }
  .cover { width: 64px; height: 92px; border-radius: 6px; flex: none; overflow: hidden; background: linear-gradient(160deg, #7c3aed, #1e1b4b); display: flex; align-items: flex-end; padding: 6px; color: #fff; font: 600 9px/1.2 var(--sans); box-shadow: 0 6px 18px rgba(0, 0, 0, .35); }
  .cover img { width: calc(100% + 12px); height: calc(100% + 12px); margin: -6px; object-fit: cover; }
  .meta { flex: 1; min-width: 0; }
  .meta .t { font-size: 18px; font-weight: 700; }
  .meta .a { color: var(--secondary); }
  .paths { display: flex; gap: 6px 18px; margin-top: 6px; flex-wrap: wrap; }
  .path { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--dim); max-width: 100%; padding: 2px 6px; margin-left: -6px; border-radius: 6px; }
  .path span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .path:not(:disabled):hover { background: var(--surface-hover); color: var(--text); }
  .stats { display: flex; gap: 22px; padding: 0 8px; }
  .stat b { display: block; font-size: 20px; }
  .stat small { color: var(--dim); font-size: 12px; }

  .work { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(260px, 320px) 1fr; gap: 16px; }
  .col { min-height: 0; display: flex; flex-direction: column; }
  .card-h { display: flex; align-items: center; gap: 8px; padding: 14px 16px 10px; font-weight: 700; }
  .card-h .sp { flex: 1; }
  .card-h small { color: var(--dim); font-weight: 500; }
  .chapters { overflow: auto; padding: 0 8px 8px; }
  .group { font-size: 11px; font-weight: 700; color: var(--dim); text-transform: uppercase; letter-spacing: .05em; padding: 10px 10px 4px; }
  .ch { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 8px; width: 100%; text-align: left; }
  .ch:hover { background: var(--surface-hover); }
  .ch.sel { background: var(--surface-active); }
  .ch .n { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .tabs { display: flex; gap: 6px; padding: 12px 14px 0; }
  .grow { flex: 1; display: grid; place-content: center; }

  .pv { display: grid; grid-template-columns: 1fr 1fr; flex: 1; min-height: 0; gap: 1px; background: var(--outline); margin: 12px 14px 14px; border-radius: 10px; overflow: hidden; }
  .pv > div { background: var(--panel); display: flex; flex-direction: column; min-height: 0; }
  .lbl { display: flex; justify-content: space-between; font-size: 11px; color: var(--dim); padding: 10px 16px; border-bottom: 1px solid var(--outline); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
  .txt { padding: 14px 16px; overflow: auto; color: var(--secondary); line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
  .txt.tr { color: var(--text); }
  .txt :global(mark) { background: none; color: var(--accent); font-weight: 600; }
  .muted { color: var(--dim); }

  .status { flex: 1; padding: 18px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; align-content: start; }
  .tile-s { background: var(--surface); border-radius: 12px; padding: 14px; min-width: 0; }
  .tile-s.wide { grid-column: span 2; }
  .tile-s small { color: var(--dim); font-size: 12px; }
  .tile-s b { display: block; font-size: 16px; margin-top: 4px; overflow-wrap: anywhere; }

  .mono-box { flex: 1; margin: 12px 14px 14px; padding: 12px 14px; border-radius: 10px; background: var(--window); font: 12px/1.7 var(--mono); color: var(--secondary); overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; min-height: 0; }
  .mono-box .ok { color: var(--ok); }
  .mono-box .warn { color: var(--warning); }

  .bar { display: flex; align-items: center; gap: 16px; padding: 14px 32px; border-top: 1px solid var(--outline); background: var(--panel); flex: none; }
  .prog { flex: 1; display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--dim); white-space: nowrap; }

  .menu { position: fixed; z-index: 40; background: var(--overlay); border: 1px solid var(--outline); border-radius: 10px; padding: 4px; box-shadow: 0 8px 28px var(--shadow); }
  .menu button { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 7px; font-size: 13px; width: 100%; }
  .menu button:hover { background: var(--surface-hover); }
</style>
