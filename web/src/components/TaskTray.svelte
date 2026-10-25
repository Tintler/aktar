<script>
  // Arka plan isleri (F139): sag ustte, Ayarlar'in solunda. Calisan isler (altyazi ve kitap cevirisi, toplu hazirlik:
  // analiz/ozet/indeks, PDF'den kitap, altyazi araclari, ses hazirlama/kaydi) ilerlemeleriyle listelenir; tiklayinca
  // isin sayfasina gidilir. Isler arayuzdeki mevcut durumlardan okunur (her biri kendi olayiyla guncellenir).
  import Icon from '../lib/Icon.svelte';
  import { app, act, go, setLibrary } from '../lib/state.svelte.js';
  import { subtool, jobText, jobPercent, KIND_NAMES } from '../lib/subtools.svelte.js';

  let open = $state(false);
  const pct = (done, total) => (total ? Math.min(100, Math.round((done * 100) / total)) : null);

  const tasks = $derived.by(() => {
    const list = [];
    const t = app.translate;
    if (t.running) {
      list.push({ id: 'translate', icon: 'languages', title: t.job === 'whisper' ? 'Altyazı oluşturuluyor (Whisper)' : 'Altyazı çevirisi',
        detail: [t.video?.name, t.paused ? 'duraklatıldı' : ''].filter(Boolean).join(' · '),
        percent: pct(t.progress?.done, t.progress?.total), count: t.progress?.total ? `${t.progress.done} / ${t.progress.total}` : '',
        go: () => go('translate') });
    }
    const b = app.books.status;
    if (b.runtime && b.runtime !== 'idle') {
      list.push({ id: 'books', icon: 'bookA', title: 'Kitap çevirisi', detail: [app.books.book.title, b.phase].filter(Boolean).join(' · '),
        sub: b.current, percent: b.progress?.percent ?? null, count: b.progress?.total ? `${b.progress.done} / ${b.progress.total} bölüm` : '',
        go: () => go('books') });
    }
    const q = app.library.queue;
    if (q) {
      list.push({ id: 'library', icon: 'library', title: 'Toplu hazırlık' + (q.title ? ': ' + q.title : ''),
        detail: [q.label, q.paused ? 'duraklatıldı' : ''].filter(Boolean).join(' · '),
        percent: pct(q.done + (q.percent ?? 0) / 100, q.total), count: `${q.done} / ${q.total} dosya`,
        items: q.items ?? [], remaining: Math.max(1, q.total - q.done),
        go: async () => {
          app.libraryView.home = false;
          go('library');
          if (q.slug && q.slug !== app.library.slug) setLibrary(await act('library_open', q.slug));
        } });
    }
    const p = app.pdfImport;
    if (p?.running) {
      list.push({ id: 'pdf', icon: 'fileText', title: "PDF'den kitap", detail: [p.info.name, p.progress?.stage].filter(Boolean).join(' · '),
        percent: pct(p.progress?.done, p.progress?.total), count: p.progress?.total ? `${p.progress.done} / ${p.progress.total} sayfa` : '',
        go: () => (p.open = true) });
    }
    const s = subtool.job;
    if (s) {
      list.push({ id: 'subtool', icon: 'subtitles', title: KIND_NAMES[s.kind] ?? 'Altyazı aracı', detail: [s.path?.split(/[\\/]/).pop(), jobText(s)].filter(Boolean).join(' · '),
        percent: jobPercent(s), count: '', go: () => go(app.player ? 'player' : 'library') });
    }
    if (app.ttsPrepare) {
      list.push({ id: 'ttsprepare', icon: 'headphones', title: 'Ses hazırlanıyor', detail: app.reading.book?.title ?? '',
        percent: pct(app.ttsPrepare.done, app.ttsPrepare.total), count: `${app.ttsPrepare.done} / ${app.ttsPrepare.total} cümle`, go: () => go('reading') });
    }
    if (app.ttsExport) {
      list.push({ id: 'ttsexport', icon: 'download', title: 'Ses kaydediliyor', detail: app.reading.book?.title ?? '',
        percent: pct(app.ttsExport.done, app.ttsExport.total), count: `${app.ttsExport.done} / ${app.ttsExport.total} cümle`, go: () => go('reading') });
    }
    const a = app.ttsAudiobook;
    if (a) {
      list.push({ id: 'audiobook', icon: 'headphones', title: 'Sesli kitap kaydediliyor', detail: [a.title, a.chapters ? `Bölüm ${a.chapter} / ${a.chapters}` : 'bölümler okunuyor'].filter(Boolean).join(' · '),
        percent: a.total ? pct(a.done, a.total) : null, count: a.total ? `${a.done} / ${a.total} cümle` : '', go: () => go('reading') });
    }
    const sp = app.speech.job;
    if (sp) {
      list.push({ id: 'speech', icon: 'waveform', title: 'Metinden ses kaydediliyor', detail: sp.loading ? 'ses motoru hazırlanıyor' : '',
        percent: sp.loading ? null : pct(sp.done, sp.total), count: sp.total ? `${sp.done} / ${sp.total} cümle` : '', go: () => go('speech') });
    }
    if (app.game.status.running) {
      const last = app.game.status.recent?.[0];
      list.push({ id: 'game', icon: 'gamepad', title: 'Oyun çevirisi açık', detail: last ? last.translation.slice(0, 60) : 'ekran izleniyor',
        percent: null, count: '', go: () => go('game') });
    }
    const e = app.emotionJob;
    if (e) {
      list.push({ id: 'emotions', icon: 'sparkles', title: 'Duygu etiketleri oluşturuluyor', detail: [e.title, e.reading ? 'bölümler okunuyor' : ''].filter(Boolean).join(' · '),
        percent: e.total ? pct(e.done, e.total) : null, count: e.total ? `${e.done} / ${e.total} cümle` : '',
        go: () => go('reading') });
    }
    return list;
  });

  // Rozet: kalan is birimi (kuyrukta bekleyen dosyalar dahil); digerleri birer is.
  const remaining = $derived(tasks.reduce((sum, task) => sum + (task.remaining ?? 1), 0));
  // 'Kare 11/57', 'Whisper %40' gibi adim ilerlemesinden yuzde
  function stepPercent(detail) {
    const ratio = /(\d+)\s*\/\s*(\d+)/.exec(detail ?? '');
    if (ratio) return pct(Number(ratio[1]), Number(ratio[2]));
    const percent = /%\s*(\d+)/.exec(detail ?? '');
    return percent ? Number(percent[1]) : null;
  }

  function choose(task) {
    open = false;
    task.go();
  }
</script>

<svelte:window onclick={(e) => { if (open && !e.target.closest('.task-tray')) open = false; }} />

<div class="task-tray">
  <button class="icon-btn" class:on={open} class:busy={tasks.length}
    title={tasks.length ? `Arka planda ${tasks.length} iş · ${remaining} birim kaldı (kuyruktaki dosyalar dahil)` : 'Arka planda iş yok'}
    onclick={() => (open = !open)}>
    <Icon name={tasks.length ? 'loader' : 'list'} size={20} spin={tasks.length > 0} />
    {#if tasks.length}<i class="count">{remaining}</i>{/if}
  </button>
  {#if open}
    <div class="pop" role="dialog" aria-label="Arka plan işleri">
      <div class="head">Arka plan işleri</div>
      {#each tasks as task (task.id)}
        <button class="task" onclick={() => choose(task)}>
          <span class="ic"><Icon name={task.icon} size={18} /></span>
          <span class="body">
            <b>{task.title}</b>
            {#if task.detail}<small>{task.detail}</small>{/if}
            {#if task.sub}<small class="sub">{task.sub}</small>{/if}
            <span class="bar"><span class="track" class:wait={task.percent === null}><i style:width="{task.percent ?? 30}%"></i></span>
              <small class="num">{task.count || (task.percent !== null ? `%${task.percent}` : '')}</small></span>
            {#if task.items?.length}
              {@const active = task.items.filter((item) => item.state === 'active')}
              {@const waiting = task.items.filter((item) => item.state === 'waiting')}
              {@const failed = task.items.filter((item) => item.state === 'failed')}
              {@const finished = task.items.filter((item) => item.state === 'done').length}
              <span class="items">
                {#each active as item (item.path)}
                  {@const step = stepPercent(item.detail)}
                  <span class="item active"><Icon name="loader" size={12} spin /><span class="iname">{item.name}</span><small>{item.detail}</small></span>
                  {#if step !== null}<span class="track mini"><i style:width="{step}%"></i></span>{/if}
                {/each}
                {#each waiting.slice(0, 8) as item (item.path)}
                  <span class="item"><Icon name="timer" size={12} /><span class="iname">{item.name}</span><small>Sırada</small></span>
                {/each}
                {#if waiting.length > 8}<span class="item more">+{waiting.length - 8} dosya daha sırada</span>{/if}
                {#each failed as item (item.path)}
                  <span class="item failed" title={item.detail}><Icon name="alert" size={12} /><span class="iname">{item.name}</span><small>Hata</small></span>
                {/each}
                {#if finished}<span class="item more"><Icon name="check" size={12} />{finished} dosya hazır</span>{/if}
              </span>
            {/if}
          </span>
        </button>
      {:else}
        <div class="empty">Şu an arka planda çalışan bir iş yok. Çeviri, toplu hazırlık (analiz, özet, indeks), PDF'den kitap ve ses
          hazırlama gibi işler başlayınca burada görünür.</div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .task-tray { position: relative; }
  .icon-btn { position: relative; }
  .icon-btn.on, .icon-btn.busy { color: var(--accent); }
  .count { position: absolute; top: 2px; right: 0; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 999px; font: 700 10px/16px var(--sans);
    font-style: normal; background: var(--accent); color: var(--on-accent); }
  .pop { position: absolute; right: 0; top: 44px; width: 380px; max-height: 70vh; overflow: auto; z-index: 40; padding: 6px;
    background: var(--overlay); border: 1px solid var(--outline); border-radius: 14px; box-shadow: 0 8px 28px var(--shadow); }
  .head { font-size: 11px; font-weight: 700; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; padding: 8px 10px 6px; }
  .task { display: flex; gap: 12px; width: 100%; text-align: left; padding: 10px; border-radius: 10px; }
  .task:hover { background: var(--surface-hover); }
  .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .body b { font-size: 13px; }
  .body small { color: var(--secondary); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .body small.sub { color: var(--dim); }
  .bar { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
  .bar .track { flex: 1; }
  .track.wait i { animation: slide 1.4s ease-in-out infinite; }
  @keyframes slide { from { margin-left: -30%; } to { margin-left: 100%; } }
  .num { flex: none; color: var(--dim); font-size: 11px; }
  .items { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--outline); }
  .item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--secondary); min-width: 0; }
  .item :global(svg) { flex: none; color: var(--dim); }
  .item .iname { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item small { flex: none; color: var(--dim); font-size: 11px; max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item.active { color: var(--text); font-weight: 600; }
  .item.active :global(svg) { color: var(--accent); }
  .item.active small { color: var(--accent); font-weight: 500; }
  .item.failed, .item.failed :global(svg) { color: var(--danger); }
  .item.more { color: var(--dim); font-size: 11px; padding-left: 18px; }
  .track.mini { height: 3px; margin: 1px 0 3px 18px; }
  .empty { padding: 12px; color: var(--dim); font-size: 12px; line-height: 1.5; }
</style>
