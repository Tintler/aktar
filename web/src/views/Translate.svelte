<script>
  import Icon from '../lib/Icon.svelte';
  import Toggle from '../components/Toggle.svelte';
  import GlossaryModal from '../components/GlossaryModal.svelte';
  import SubtitleExportModal from '../components/SubtitleExportModal.svelte';
  import { subtool, jobText, cancelJob } from '../lib/subtools.svelte.js';
  import { app, act, setTranslate, onDrop, toast, go } from '../lib/state.svelte.js';
  import { prompt, choose, confirm } from '../lib/confirm.svelte.js';
  import { call } from '../lib/api.js';

  const t = $derived(app.translate);
  const view = app.translateView;
  const VIDEO = ['.mkv', '.mp4', '.m4v', '.avi', '.mov', '.webm', '.ts', '.wmv', '.flv'];

  const supported = $derived(t.streams.filter((s) => s.supported).length);
  const whisperJob = $derived(t.running && t.job === 'whisper');
  const hasWhisper = $derived(t.streams.some((s) => s.whisper));
  const percent = $derived(t.progress.total ? Math.round((t.progress.done * 100) / t.progress.total) : 0);
  let glossary = $state(null);   // {title, items, save(rows)}
  let exporting = $state(null);  // {key, label}: disa aktarma penceresi (F118)
  const ocrJob = $derived(subtool.job?.kind === 'ocr' && subtool.job.path === t.video?.path ? subtool.job : null);
  const streamKey = (s) => (s.whisper ? 'whisper' : `stream:${s.index}`);
  const selected = $derived(t.streams.find((s) => s.index === view.stream && s.supported));

  async function readImage(s) {
    await act('subtitle_ocr', t.video.path, s.index);
  }

  async function openVideo(path) {
    const state = await act('open_video', path);
    if (!state) return;
    view.stream = null;
    setTranslate(state);
    if (state.series_choices?.length) {
      const slug = await choose({
        title: 'Seri seç', message: 'Bu video birden fazla seriyle eşleşti:',
        options: state.series_choices.map((s) => ({ value: s.slug, label: s.title })),
      });
      if (slug) setTranslate(await act('set_series', slug));
    }
  }

  async function chooseVideo() {
    const state = await act('choose_video');
    if (state) {
      view.stream = null;
      setTranslate(state);
      if (state.series_choices?.length) {
        const slug = await choose({
          title: 'Seri seç', message: 'Bu video birden fazla seriyle eşleşti:',
          options: state.series_choices.map((s) => ({ value: s.slug, label: s.title })),
        });
        if (slug) setTranslate(await act('set_series', slug));
      }
    }
  }

  $effect(() => {
    const path = app.pendingVideo;
    if (!path) return;
    app.pendingVideo = null;
    if (t.running) toast('Çeviri sürerken başka video açılamaz.', 'error');
    else openVideo(path);
  });

  onDrop('translate', (paths) => {
    const video = paths.find((p) => VIDEO.some((ext) => p.toLowerCase().endsWith(ext)));
    if (!video) return toast('Bırakılan dosyalar arasında video yok.', 'error');
    if (t.running) return toast('Çeviri sürerken başka video açılamaz.', 'error');
    openVideo(video);
  });

  async function changeSeries(event) {
    const value = event.currentTarget.value;
    if (value !== '__new') {
      setTranslate(await act('set_series', value));
      return;
    }
    event.currentTarget.value = t.series_slug;
    const title = await prompt({ title: 'Yeni seri', message: 'Seri başlığı:', value: await call('guess_series_title'), ok: 'Oluştur' });
    if (title?.trim()) setTranslate(await act('create_series', title.trim()));
  }

  async function editSeriesGlossary() {
    const data = await act('series_data');
    if (!data) return;
    glossary = {
      title: 'Seri terimleri · ' + data.title, items: data.glossary,
      save: async (rows) => { if (await act('save_series_glossary', rows, data.slug)) { glossary = null; toast('Seri terimleri kaydedildi.', 'ok'); } },
    };
  }

  async function editSeriesDecisions() {
    const data = await act('series_data');
    if (!data) return;
    const text = await prompt({
      title: 'Süreklilik kararları · ' + data.title, multiline: true, value: data.decisions.join('\n'), ok: 'Kaydet',
      message: 'Her satıra bir kalıcı karar yazın (sen/siz, isim yazımı, ses, tekrar eden kalıp):',
    });
    if (text !== null && (await act('save_series_decisions', text, data.slug))) toast('Süreklilik kararları kaydedildi.', 'ok');
  }

  function editChapterGlossary() {
    glossary = {
      title: 'Bölüme özel terimler', items: t.chapter_glossary,
      save: async (rows) => { const state = await act('set_chapter_glossary', rows); if (state) { setTranslate(state); glossary = null; } },
    };
  }

  async function start() {
    if (t.running) {
      const ok = whisperJob
        ? await confirm({ title: 'Altyazı oluşturma iptal edilsin mi?', message: 'Konuşmadan metin çıkarma durdurulur.', ok: 'İptal et', cancel: 'Sürdür', danger: true })
        : await confirm({ title: 'Çeviri iptal edilsin mi?', message: 'Kaydedilen partiler korunur; aynı videoyu yeniden çevirdiğinizde kaldığı yerden devam eder.', ok: 'İptal et', cancel: 'Sürdür', danger: true });
      if (ok) setTranslate(await act('cancel_translation'));
      return;
    }
    if (view.stream === null) return toast('Önce bir altyazı akışı işaretleyin.', 'error');
    const state = await act('start_translation', view.stream, view.analysis);
    if (state) setTranslate(state);
  }


  async function generateSubtitle() {
    const state = await act('generate_subtitle');
    if (state) setTranslate(state);
  }

  const clock = (sec) => { const s = Math.max(0, Math.round(sec)); const m = Math.floor(s / 60); return m + ':' + String(s % 60).padStart(2, '0'); };
  const statusOf = (s) => s.whisper ? ['Whisper · SRT', 'ok'] : s.ocr ? ['OCR · SRT', 'ok'] : s.image ? ['Görüntü tabanlı', 'warning'] : s.supported ? [s.extension.toUpperCase(), 'ok'] : ['Desteklenmiyor', ''];
</script>

<section class="page">
  <div class="page-head">
    <h1>Altyazı Çevir</h1>
    <div class="series">
      <span class="label">Seri</span>
      <select class="field pill" value={t.series_slug} onchange={changeSeries} disabled={t.running}>
        <option value="">Seri yok</option>
        {#each t.series as s}<option value={s.slug}>{s.title}</option>{/each}
        <option value="__new">+ Yeni seri…</option>
      </select>
      <button class="btn ghost" disabled={!t.series_slug} onclick={editSeriesGlossary} title="Seri terim sözlüğü"><Icon name="dict" size={16} />Terimler</button>
      <button class="btn ghost" disabled={!t.series_slug} onclick={editSeriesDecisions} title="Seri süreklilik kararları"><Icon name="continuity" size={16} />Süreklilik</button>
    </div>
    <button class="btn" onclick={chooseVideo} disabled={t.running}><Icon name="upload" size={16} />Video seç</button>
  </div>

  <div class="page-body body">
    {#if !t.video}
      <button class="drop card" onclick={chooseVideo}>
        <span class="tile"><Icon name="film" size={30} /></span>
        <b>Videoyu buraya bırakın</b>
        <span class="dim">ya da tıklayıp seçin · {VIDEO.join(' ')}</span>
        <span class="note">Seçilen metin altyazı LM Studio'daki modelle Türkçeye çevrilir ve videonun yanına <span class="mono">_TR</span> ekiyle yazılır. Altyazısı olmayan videoda önce Whisper ile altyazı oluşturulabilir. Kaynak video değiştirilmez.</span>
      </button>
    {:else}
      <div class="hero card">
        <span class="tile"><Icon name="film" size={26} /></span>
        <div class="info">
          <div class="name selectable ellipsis" title={t.video.name}>{t.video.name}</div>
          <button class="path ellipsis" title="Klasörü aç" onclick={() => act('reveal', t.video.path)}><Icon name="folder" size={14} />{t.video.folder}</button>
        </div>
        <div class="stat"><b>{t.streams.length}</b><span>akış</span></div>
        <div class="stat"><b>{supported}</b><span>metin tabanlı</span></div>
      </div>

      <div class="grid">
        <div class="card list">
          <div class="card-head"><b>Altyazı akışları</b><span class="dim">{supported > 1 ? 'Tek akış işaretlenebilir' : ''}</span>
            <button class="btn ghost sm" disabled={!selected || t.running} onclick={() => (exporting = { key: streamKey(selected), label: selected.title || selected.codec })}
              title="İşaretli altyazıyı başka biçimde kaydet (Whisper'da kelime zamanlı / karaoke)"><Icon name="download" size={14} />Dışa aktar…</button></div>
          {#if t.probing}
            <div class="empty"><Icon name="loader" spin /> Akışlar okunuyor…</div>
          {:else}
            {#each t.streams as s}
              {@const [status, kind] = statusOf(s)}
              <label class="stream" class:on={view.stream === s.index} class:off={!s.supported}>
                <input type="radio" name="stream" value={s.index} disabled={!s.supported || t.running}
                  checked={view.stream === s.index} onchange={() => (view.stream = s.index)} />
                <span class="codec mono">{s.codec}</span>
                <span class="lang">{s.language || '—'}</span>
                <span class="title ellipsis">{s.title || ''}</span>
                <span class="badge {kind}">{status}</span>
                {#if s.image && !s.ocr}
                  {#if ocrJob}
                    <span class="mono dim ocr">{jobText(ocrJob)}</span>
                    <button class="btn sm ghost" onclick={(e) => { e.preventDefault(); cancelJob(); }}>Durdur</button>
                  {:else}
                    <button class="btn sm" disabled={t.running || !!subtool.job} onclick={(e) => { e.preventDefault(); readImage(s); }}
                      title="Altyazı görüntüleri Ayarlar'daki OCR motoruyla (Tesseract, OCR modeli ya da görü modeli) okunur; videonun yanına .srt yazılır ve çevrilebilir."><Icon name="image" size={14} />OCR ile oku</button>
                  {/if}
                {/if}
              </label>
            {:else}
              <div class="empty">Bu videoda altyazı akışı yok. Konuşmadan altyazı oluşturabilirsiniz.</div>
            {/each}
            {#if whisperJob}
              <div class="whisper busy"><Icon name="loader" spin size={16} /><span class="title">Whisper ile altyazı oluşturuluyor…</span>
                <span class="mono dim">%{percent}</span></div>
            {:else if !hasWhisper}
              <button class="whisper" onclick={generateSubtitle} disabled={t.running || !t.whisper_available}
                title={t.whisper_available ? 'Konuşmayı Whisper ile yazıya döker; videonun yanına .srt olarak kaydeder ve çeviri için listeye ekler.' : 'Whisper kurulu değil (KULLANIM.md 1.5).'}>
                <Icon name="mic" size={16} /><span class="title">Whisper ile altyazı oluştur</span>
                <span class="dim">{t.whisper_available ? 'sesten SRT' : 'kurulu değil'}</span>
              </button>
            {/if}
          {/if}
        </div>

        <div class="card side">
          <div class="card-head">
            <b>Ön analiz</b>
            <button class="btn ghost sm" onclick={() => go('console')} title="Çevirinin ayrıntılı günlüğü"><Icon name="terminal" size={14} />Konsol</button>
          </div>
          <pre class="console selectable">{t.analysis || 'Ön analiz sonuçları burada görünür. Çevirinin ayrıntılı günlüğü Konsol sayfasındadır.'}</pre>
        </div>
      </div>
    {/if}
  </div>

  <footer class="bar">
    <button class="btn ghost" onclick={editChapterGlossary} disabled={t.running}>
      <Icon name="dict" size={16} />Bölüm terimleri{t.chapter_glossary.length ? ' · ' + t.chapter_glossary.length : ''}</button>
    <Toggle bind:checked={view.analysis} disabled={t.running} label="Ön analiz yap" />
    <div class="progress">
      <span class="mono count">{whisperJob ? clock(t.progress.done) + ' / ' + clock(t.progress.total) : t.progress.done + ' / ' + t.progress.total}</span>
      <div class="track"><i style:width="{percent}%"></i></div>
      <span class="mono pct">%{percent}</span>
    </div>
    <button class="icon-btn filled" title={t.paused ? 'Devam' : 'Duraklat'} disabled={!t.running || whisperJob}
      onclick={async () => setTranslate(await act('toggle_pause'))}><Icon name={t.paused ? 'play' : 'pause'} size={16} /></button>
    <button class="btn primary lg go" class:danger={t.running} disabled={!t.video || (!t.running && view.stream === null)} onclick={start}>
      {#if t.running}<Icon name="stop" size={16} />İptal{:else}<Icon name="languages" size={18} />Çevir{/if}
    </button>
  </footer>
</section>

{#if exporting && t.video}
  <SubtitleExportModal path={t.video.path} source={exporting.key} label={exporting.label} onclose={() => (exporting = null)} />
{/if}

{#if glossary}
  <GlossaryModal title={glossary.title} items={glossary.items} onsave={glossary.save} onclose={() => (glossary = null)} />
{/if}

<style>
  .series { display: flex; align-items: center; gap: 6px; }
  .series .label { margin-right: 4px; }
  .pill { border-radius: 999px; width: 220px; }
  .body { display: flex; flex-direction: column; gap: 16px; }

  .drop { flex: 1; min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
    border: 2px dashed var(--outline); background: transparent; color: var(--text); }
  .drop:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 4%, transparent); }
  .drop b { font-size: 20px; }
  .drop .note { color: var(--secondary); font-size: 13px; max-width: 520px; text-align: center; margin-top: 10px; line-height: 1.6; }
  .tile { width: 64px; height: 64px; border-radius: 12px; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }

  .hero { display: flex; align-items: center; gap: 18px; padding: 18px 22px; }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .name { font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
  .path { display: flex; align-items: center; gap: 6px; color: var(--dim); font-size: 13px; text-align: left; max-width: 100%; }
  .path:hover { color: var(--text); }
  .stat { display: flex; flex-direction: column; align-items: center; min-width: 84px; }
  .stat b { font-size: 26px; font-weight: 700; line-height: 1.1; }
  .stat span { color: var(--dim); font-size: 12px; }

  .grid { flex: 1; min-height: 300px; display: grid; grid-template-columns: minmax(340px, 5fr) 7fr; gap: 16px; }
  .list, .side { display: flex; flex-direction: column; min-height: 0; padding: 6px; }
  .card-head { display: flex; align-items: center; gap: 8px; padding: 8px 10px 10px; }
  .card-head b { font-size: 15px; flex: 1; }
  .card-head .dim { font-size: 12px; }

  .stream { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 6px; cursor: pointer; }
  .stream:hover { background: var(--surface-hover); }
  .stream.on { background: var(--surface-active); }
  .stream.off { cursor: default; }
  .stream.off .codec, .stream.off .lang, .stream.off .title { opacity: .5; }
  .ocr { font-size: 12px; }
  .codec { font-size: 12px; color: var(--accent); min-width: 64px; }
  .stream.off .codec { color: var(--dim); }
  .lang { color: var(--secondary); min-width: 34px; }
  .title { flex: 1; }
  .whisper { display: flex; align-items: center; gap: 12px; padding: 10px 12px; margin-top: 4px; border-radius: 6px; text-align: left;
    border: 1px dashed var(--outline); color: var(--accent); }
  .whisper .title { color: var(--text); }
  .whisper .dim { font-size: 12px; }
  .whisper:not(.busy):not(:disabled):hover { background: var(--surface-hover); border-color: var(--accent); }
  .whisper:disabled { opacity: .5; cursor: default; }
  .console { flex: 1; min-height: 0; overflow: auto; margin: 0 4px 4px; padding: 10px 12px; background: var(--window); border-radius: 8px;
    font: 12px/1.6 var(--mono); color: var(--secondary); white-space: pre-wrap; overflow-wrap: anywhere; }

  .bar { flex: none; display: flex; align-items: center; gap: 16px; padding: 14px 32px; border-top: 1px solid var(--outline); background: var(--panel); }
  .progress { flex: 1; display: flex; align-items: center; gap: 12px; min-width: 0; }
  .count { color: var(--secondary); font-size: 12px; min-width: 76px; text-align: right; }
  .pct { color: var(--dim); font-size: 12px; min-width: 40px; }
  .go { min-width: 120px; }
</style>
