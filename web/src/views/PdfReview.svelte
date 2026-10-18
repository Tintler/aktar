<script>
  // PDF'den kitap: gozden gecirme (F139). Solda bolumler (ad, birlestirme, kisim/bolum), ortada sayfa goruntusu,
  // sagda sayfa metni (duzeltme) ve sayfadaki paragraflar ('Burada bolum baslat'). Bolumler kitap.json'a,
  // sayfa duzeltmeleri <PDF>-pdf/duzeltme altina yazilir; OCR ciktisi bozulmaz. Bitince kitap yeniden yazilir.
  import Icon from '../lib/Icon.svelte';
  import { app, act, finishPdfReview, toast } from '../lib/state.svelte.js';
  import { confirm, prompt } from '../lib/confirm.svelte.js';

  const review = app.pdfReview;
  let summary = $state(review.summary);
  let chapters = $state(summary.chapters.map((c) => ({ ...c })));
  let meta = $state({ title: summary.title, author: summary.author, language: summary.language });
  // F153: kitap dili listesi (ceviri dilleriyle ayni); liste gelene kadar mevcut dil gorunur.
  let languageChoices = $state([{ code: summary.language, label: summary.language }]);
  act('translation_languages').then((r) => { if (r) languageChoices = r.choices; });
  let saved = $state(snapshot());
  let view = $state(null);          // pdf_page sonucu
  let text = $state('');
  let busy = $state(false);
  let pageInput = $state(1);

  function snapshot() {
    return JSON.stringify({ chapters: chapters.map(({ title, page, ordinal, skip, level }) => ({ title, page, ordinal, skip, level })), meta });
  }
  const dirty = $derived(snapshot() !== saved);
  const textDirty = $derived(view !== null && text !== view.text);
  const warnings = $derived(summary.warnings ?? []);
  const currentChapter = $derived(view ? chapters.reduce((found, c, i) => (c.page <= view.page ? i : found), 0) : 0);

  async function openPage(page) {
    if (textDirty && !(await confirm({ title: 'Sayfa metni kaydedilmedi', message: 'Bu sayfadaki düzeltme kaydedilmeden başka sayfaya geçilsin mi?', ok: 'Kaydetmeden geç' }))) return;
    page = Math.max(1, Math.min(summary.pages, Math.round(Number(page) || 1)));
    const result = await act('pdf_page', review.path, page);
    if (!result) return;
    view = result;
    text = result.text;
    pageInput = page;
  }
  openPage(chapters[0]?.page ?? 1);

  async function savePage() {
    const result = await act('pdf_save_page', review.path, view.page, text);
    if (result) { view = result; text = result.text; markEdited(result); toast('Sayfa düzeltmesi kaydedildi.', 'ok'); }
  }

  async function revertPage() {
    const result = await act('pdf_revert_page', review.path, view.page);
    if (result) { view = result; text = result.text; markEdited(result); }
  }

  function markEdited(result) {
    const set = new Set(summary.edited);
    if (result.edited) set.add(result.page); else set.delete(result.page);
    summary.edited = [...set].sort((a, b) => a - b);
  }

  // ---- bolumler
  const boundaryAt = (ordinal) => chapters.findIndex((c) => c.page === view?.page && c.ordinal === ordinal);

  async function splitHere(paragraph) {
    if (boundaryAt(paragraph.ordinal) >= 0) return;
    const title = await prompt({ title: 'Yeni bölüm', message: `${view.page}. sayfadaki bu paragraftan yeni bölüm başlar. Bölüm adı:`,
      value: paragraph.text.length <= 60 ? paragraph.text : '', ok: 'Bölüm başlat', placeholder: 'ör. 7 ya da Chapter 3' });
    if (title === null || !title.trim()) return;
    // Paragraf baslik olarak kullanildiysa bolum metnine tekrar girmesin
    const skip = title.trim() === paragraph.text.trim() ? 1 : 0;
    const level = chapters[currentChapter]?.level ?? 0;
    chapters.push({ title: title.trim(), page: view.page, ordinal: paragraph.ordinal, skip, level, count: null, first: paragraph.text });
    chapters.sort((a, b) => a.page - b.page || a.ordinal - b.ordinal);
  }

  async function mergeUp(index) {
    if (index === 0) return;
    const ok = await confirm({ title: 'Önceki bölümle birleştir', message: `"${chapters[index].title}" bölümü "${chapters[index - 1].title}" bölümüne katılsın mı?`
      + (chapters[index].skip ? ' Başlık satırı metin olarak kalır.' : ''), ok: 'Birleştir' });
    if (ok) chapters.splice(index, 1);
  }

  const toggleLevel = (chapter) => (chapter.level = chapter.level ? 0 : 1);

  async function redetect() {
    const ok = await confirm({ title: 'Otomatik bölümle', message: 'Bölümler yeniden otomatik bulunur; bölüm adı ve sınırlarındaki düzenlemeleriniz silinir. Sayfa düzeltmeleri korunur.', ok: 'Yeniden bul', danger: true });
    if (!ok) return;
    busy = true;
    const result = await act('pdf_review', review.path, true);
    busy = false;
    if (result) reset(result);
  }

  function reset(result) {
    summary = result;
    chapters = result.chapters.map((c) => ({ ...c }));
    meta = { title: result.title, author: result.author, language: result.language };
    saved = snapshot();
  }

  async function saveStructure() {
    const data = { ...meta, chapters: chapters.map(({ title, page, ordinal, skip, level }) => ({ title, page, ordinal, skip, level })) };
    const result = await act('pdf_save_structure', review.path, data);
    if (result) { reset(result); return true; }
    return false;
  }

  async function build() {
    if (textDirty) await savePage();
    if (dirty && !(await saveStructure())) return;
    busy = true;
    const result = await act('pdf_rebuild', review.path, review.target);
    busy = false;
    if (result) finishPdfReview(result);
  }
</script>

<section class="page">
  <div class="page-head">
    <h1 class="ellipsis" title={summary.name}>Gözden geçir</h1>
    <input class="field meta" bind:value={meta.title} placeholder="Kitap adı" title="Kitap adı" />
    <input class="field meta small" bind:value={meta.author} placeholder="Yazar" title="Yazar" />
    <select class="field lang" bind:value={meta.language} title="Kitabın dili">
      {#each languageChoices as l}<option value={l.code}>{l.label}</option>{/each}
    </select>
    <span class="grow"></span>
    {#if dirty}<span class="unsaved">Kaydedilmemiş değişiklik</span>{/if}
    <button class="btn" disabled={busy} onclick={redetect} title="Bölümleri yeniden otomatik bul"><Icon name="refresh" size={16} />Otomatik bölümle</button>
    <button class="btn" disabled={busy || !dirty} onclick={saveStructure}><Icon name="check" size={16} />Kaydet</button>
    <button class="btn primary" disabled={busy} onclick={build}><Icon name={busy ? 'loader' : 'book'} size={16} spin={busy} />
      {review.target === 'books' ? "Kitabı oluştur ve Kitap Çevir'de aç" : 'Kitabı oluştur ve oku'}</button>
  </div>

  <div class="review">
    <aside class="chapters card">
      <div class="head">Bölümler <small>{chapters.length}</small></div>
      <div class="list">
        {#each chapters as chapter, index (chapter.page + ':' + chapter.ordinal)}
          <div class="ch" class:on={index === currentChapter} class:sub={chapter.level === 1}>
            <button class="go" title="{chapter.page}. sayfaya git" onclick={() => openPage(chapter.page)}>{chapter.page}</button>
            <input class="name" bind:value={chapter.title} aria-label="Bölüm adı" />
            <button class="icon-btn sm" title={chapter.level ? 'Üst düzeye al (kısım)' : 'Önceki kısmın altına al'} onclick={() => toggleLevel(chapter)}>
              <Icon name={chapter.level ? 'back' : 'forward'} size={13} /></button>
            <button class="icon-btn sm" title="Önceki bölümle birleştir" disabled={index === 0} onclick={() => mergeUp(index)}><Icon name="up" size={13} /></button>
          </div>
        {/each}
      </div>
      {#if warnings.length || summary.edited.length}
        <div class="head">Kontrol edilecek sayfalar <small>{warnings.length}</small></div>
        <div class="list warn-list">
          {#each warnings as w}<button class="w" onclick={() => openPage(w.page)}><b>{w.page}</b><span>{w.reason}</span></button>{/each}
          {#if summary.edited.length}<div class="edited">Düzeltilen sayfalar: {summary.edited.join(', ')}</div>{/if}
        </div>
      {/if}
    </aside>

    <div class="viewer card">
      <div class="nav">
        <button class="icon-btn sm" title="Önceki sayfa" disabled={!view || view.page <= 1} onclick={() => openPage(view.page - 1)}><Icon name="back" size={15} /></button>
        <input class="field num" type="number" min="1" max={summary.pages} bind:value={pageInput} onchange={() => openPage(pageInput)} />
        <span class="dim">/ {summary.pages}</span>
        <button class="icon-btn sm" title="Sonraki sayfa" disabled={!view || view.page >= summary.pages} onclick={() => openPage(view.page + 1)}><Icon name="forward" size={15} /></button>
        {#if view?.edited}<span class="badge warning">Düzeltildi</span>{/if}
      </div>
      <div class="image">{#if view}<img src={view.image} alt="{view.page}. sayfa" />{/if}</div>
    </div>

    <div class="editor card">
      {#if view}
        <div class="head">Sayfa metni
          <span class="grow"></span>
          {#if view.edited}<button class="btn sm ghost" onclick={revertPage} title="Düzeltmeyi sil, OCR metnine dön">OCR'a dön</button>{/if}
          <button class="btn sm" disabled={!textDirty} onclick={savePage}>Sayfayı kaydet</button>
        </div>
        <textarea class="field text selectable" bind:value={text} spellcheck="false"></textarea>
        <div class="head">Bu sayfadaki paragraflar <small>bölüm başlatmak için</small></div>
        <div class="paras">
          {#each view.paragraphs as paragraph}
            {@const start = boundaryAt(paragraph.ordinal)}
            <div class="para" class:start={start >= 0}>
              <span class="ptext">{paragraph.text}</span>
              {#if start >= 0}<span class="badge accent" title="Bölüm burada başlıyor">{chapters[start].title}</span>
              {:else}<button class="btn sm ghost" onclick={() => splitHere(paragraph)}><Icon name="plus" size={13} />Bölüm başlat</button>{/if}
            </div>
          {:else}
            <div class="empty">Bu sayfada metin yok.</div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</section>

<style>
  .page-head h1 { margin-right: 6px; flex: none; }
  .meta { width: 260px; }
  .meta.small { width: 180px; }
  .lang { width: 120px; }
  .grow { flex: 1; }
  .unsaved { color: var(--accent); font-size: 12px; font-weight: 600; }
  .review { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr) minmax(0, 1fr); gap: 14px; padding: 0 32px 24px; }
  .card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 12px 14px 8px; font-weight: 700; font-size: 13px; }
  .head small { color: var(--dim); font-weight: 500; }
  .list { overflow: auto; padding: 0 8px 8px; min-height: 0; }
  .chapters .list:first-of-type { flex: 1; }
  .ch { display: flex; align-items: center; gap: 4px; padding: 2px 4px; border-radius: 8px; }
  .ch.sub { padding-left: 20px; }
  .ch.on { background: var(--surface); }
  .ch .go { width: 34px; flex: none; font-size: 11px; color: var(--dim); text-align: right; padding: 4px; border-radius: 6px; }
  .ch .go:hover { color: var(--accent); }
  .name { flex: 1; min-width: 0; background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px 6px; color: var(--text); font: inherit; font-size: 13px; }
  .name:hover { border-color: var(--outline); }
  .name:focus { outline: 0; border-color: var(--accent); background: var(--window); }
  .warn-list { max-height: 30%; border-top: 1px solid var(--outline); padding-top: 6px; }
  .w { display: flex; gap: 8px; width: 100%; text-align: left; padding: 5px 6px; border-radius: 6px; font-size: 12px; color: var(--secondary); }
  .w:hover { background: var(--surface-hover); }
  .w b { color: var(--warning); min-width: 28px; }
  .edited { font-size: 12px; color: var(--dim); padding: 6px; }
  .viewer .nav { display: flex; align-items: center; gap: 6px; padding: 10px 12px; border-bottom: 1px solid var(--outline); }
  .num { width: 76px; height: 30px; }
  .dim { color: var(--dim); font-size: 13px; }
  .image { flex: 1; overflow: auto; background: var(--window); display: flex; justify-content: center; padding: 12px; }
  .image img { max-width: 100%; height: auto; align-self: flex-start; box-shadow: 0 4px 18px var(--shadow); }
  .text { flex: 1.3; min-height: 160px; margin: 0 12px; resize: none; font: 13px/1.6 var(--sans); }
  .paras { flex: 1; overflow: auto; padding: 0 12px 12px; display: flex; flex-direction: column; gap: 4px; min-height: 0; }
  .para { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 8px; background: var(--surface); font-size: 12px; }
  .para.start { box-shadow: inset 3px 0 0 var(--accent); }
  .ptext { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--secondary); }
  .para .btn { flex: none; }
  @media (max-width: 1300px) { .review { grid-template-columns: 240px minmax(0, 1fr); } .editor { grid-column: 1 / -1; min-height: 360px; } }
</style>
