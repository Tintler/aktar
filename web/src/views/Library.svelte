<script>
  import Icon from '../lib/Icon.svelte';
  import PrepareModal from '../components/PrepareModal.svelte';
  import MailModal from '../components/MailModal.svelte';
  import { app, act, setLibrary, onDrop, toast, runSearch, refreshChat, openInTranslate, openFile } from '../lib/state.svelte.js';
  import { choose, prompt, confirm } from '../lib/confirm.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';

  const lib = $derived(app.library);
  const view = app.libraryView;
  const KIND_ICON = { video: 'film', document: 'fileText', image: 'image' };

  // Ana sayfada birakilan klasor yeni koleksiyon olur; koleksiyon icindeyken ona eklenir.
  onDrop('library', async (paths) => {
    const state = await act('library_add_paths', paths, view.home);
    if (!state) return;
    setLibrary(state);
    view.home = false;
  });

  // --- ana sayfa: tum koleksiyonlar ---
  let cards = $state(null);
  $effect(() => {
    lib.collections;
    if (view.home) act('library_overview').then((list) => (cards = list ?? []));
  });

  async function openCollection(slug) {
    view.home = false;
    if (slug !== lib.slug) setLibrary(await act('library_open', slug));
  }

  async function createCollection() {
    const title = await prompt({ title: 'Yeni koleksiyon', message: 'Koleksiyon adı:', ok: 'Oluştur' });
    if (!title?.trim()) return;
    const state = await act('new_collection', title.trim());
    if (!state) return;
    setLibrary(state);
    view.home = false;
  }

  async function folderAsCollection() {
    const state = await act('library_choose_folder', true);
    if (!state) return;
    setLibrary(state);
    view.home = false;
  }

  // Arama: her tusta degil, kisa beklemeden sonra (yuzlerce transkript taranir).
  let timer;
  function typed() {
    clearTimeout(timer);
    timer = setTimeout(runSearch, 250);
  }

  const kinds = $derived.by(() => {
    const counts = {};
    for (const row of lib.rows) counts[row.kind] = (counts[row.kind] ?? 0) + 1;
    return [['', 'Tümü', lib.rows.length], ...Object.entries(counts).map(([k, n]) => [k, { video: 'Videolar', document: 'Belgeler', image: 'Görseller' }[k] ?? k, n])];
  });
  const visible = $derived.by(() => {
    const keys = view.search ? new Set(view.search.keys) : null;
    const rows = lib.rows.filter((r) => (!view.kind || r.kind === view.kind) && (!keys || keys.has(r.key)));
    const [column, direction] = (view.sort || '').split('-');
    const spec = COLUMNS[column];
    if (!spec) return rows;
    // F93: bos degerler her iki yonde de sonda; esitlerde koleksiyon sirasi korunur
    const dir = direction === 'asc' ? 1 : -1;
    return rows.map((r, i) => [r, spec.value(r), i]).sort(([, a, i], [, b, j]) => {
      const empty = (a === '' || a === null) - (b === '' || b === null);
      if (empty) return empty;
      if (a === '' || a === null) return i - j;
      // Uzunluk [tur, sayi]: tur grubu (video, belge, diger) her yonde ayni sirada kalir
      const group = Array.isArray(a) ? a[0] - b[0] : 0;
      if (group) return group;
      const order = Array.isArray(a) ? compare(a.slice(1), b.slice(1)) : compare(a, b);
      return order ? order * dir : i - j;
    }).map(([r]) => r);
  });
  const collator = new Intl.Collator('tr', { numeric: true, sensitivity: 'base' });
  function compare(a, b) {
    if (Array.isArray(a)) {
      for (let k = 0; k < a.length; k++) { const c = compare(a[k], b[k]); if (c) return c; }
      return 0;
    }
    return typeof a === 'number' ? a - b : collator.compare(String(a), String(b));
  }
  const STATUS_ORDER = { ready: 0, transcript: 1, pending: 2, no_subtitle: 3, no_text: 4, missing: 5 };
  // Ilk tiklama: tarihte yeniden eskiye, digerlerinde A'dan Z'ye / kucukten buyuge; ikinci tersi; ucuncu kapatir.
  const COLUMNS = {
    name: { label: 'Dosya', first: 'asc', value: (r) => r.name },
    where: { label: 'Klasör', first: 'asc', value: (r) => r.where || '' },
    date: { label: 'Tarih', first: 'desc', value: (r) => r.date || '' },
    length: { label: 'Uzunluk', first: 'desc', value: (r) => r.length_sort ?? '' },
    source: { label: 'Metin kaynağı', first: 'asc', value: (r) => r.source || '' },
    status: { label: 'Durum', first: 'asc', value: (r) => STATUS_ORDER[r.status] ?? 9 },
  };
  const WORDS = { name: ['A → Z', 'Z → A'], where: ['A → Z', 'Z → A'], date: ['eskiden yeniye', 'yeniden eskiye'],
    length: ['kısadan uzuna', 'uzundan kısaya'], source: ['A → Z', 'Z → A'], status: ['hazırdan bekleyene', 'bekleyenden hazıra'] };
  function sortBy(column) {
    const [current, direction] = (view.sort || '').split('-');
    const first = COLUMNS[column].first;
    const other = first === 'asc' ? 'desc' : 'asc';
    view.sort = current !== column ? `${column}-${first}` : direction === first ? `${column}-${other}` : '';
  }
  function sortTitle(column) {
    const [current, direction] = (view.sort || '').split('-');
    const next = current !== column ? COLUMNS[column].first : direction === COLUMNS[column].first
      ? (direction === 'asc' ? 'desc' : 'asc') : '';
    return next ? `${COLUMNS[column].label}: ${WORDS[column][next === 'asc' ? 0 : 1]} sırala` : 'Koleksiyon sırasına dön';
  }
  const sortColumn = $derived((view.sort || '').split('-')[0]);
  const sortDirection = $derived((view.sort || '').split('-')[1]);
  const selected = $derived(new Set(view.selected));

  let anchor = null;   // shift ile aralik secimi icin son tiklanan satir
  function click(event, row) {
    const keys = visible.map((r) => r.key);
    if (event.shiftKey && anchor !== null && keys.includes(anchor)) {
      const [a, b] = [keys.indexOf(anchor), keys.indexOf(row.key)].sort((x, y) => x - y);
      view.selected = keys.slice(a, b + 1);
    } else if (event.ctrlKey || event.metaKey) {
      view.selected = selected.has(row.key) ? view.selected.filter((k) => k !== row.key) : [...view.selected, row.key];
      anchor = row.key;
    } else {
      view.selected = [row.key];
      anchor = row.key;
    }
    if (view.scope === 'selected') refreshChat();
  }

  function keydown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && !event.target.closest('input, textarea')) {
      event.preventDefault();
      view.selected = visible.map((r) => r.key);
    }
  }

  async function exportRows(rows) {
    if (rows.length === 1) {
      const result = await act('export_transcript', rows[0].path);
      if (result?.path) toast('Transkript dışa aktarıldı: ' + result.path, 'ok');
      return;
    }
    const formats = await act('export_formats');
    const fmt = await choose({ title: 'Transkriptleri dışa aktar', message: `${rows.length} dosya · biçim:`, options: formats.map((f) => ({ value: f.id, label: f.label })) });
    if (!fmt) return;
    const result = await act('export_transcripts', rows.map((r) => r.path), fmt);
    if (result?.message) toast(result.message, 'ok');
  }

  function rowMenu(event, row) {
    if (!selected.has(row.key)) view.selected = [row.key];
    const rows = lib.rows.filter((r) => view.selected.includes(r.key));
    const single = rows.length === 1 && !row.missing;
    const withText = rows.filter((r) => r.status === 'ready' || r.status === 'transcript');
    openMenu(event, [
      { label: row.kind === 'video' ? 'Oynat ve soru sor' : 'Aç', icon: row.kind === 'video' ? 'play' : 'eye', disabled: !single, action: () => openFile(row) },
      { label: 'Altyazıyı çevir…', icon: 'languages', disabled: !(single && row.kind === 'video'), action: () => openInTranslate(row.path) },
      { label: 'Dosya konumunu aç', icon: 'folderOpen', action: () => act('reveal', row.path) },
      { label: 'Tarihi düzenle…' + (rows.length > 1 ? ` (${rows.length} dosya)` : ''), icon: 'calendar', action: () => editDate(rows) },
      { label: 'Transkripti dışa aktar…' + (withText.length > 1 ? ` (${withText.length} dosya)` : ''), icon: 'download', disabled: !withText.length, action: () => exportRows(withText) },
      { label: 'Yeniden işle…' + (rows.length > 1 ? ` (${rows.length} dosya)` : ''), icon: 'refresh', disabled: !!queue || !rows.some((r) => !r.missing),
        action: () => resetRows(rows.filter((r) => !r.missing)) },
      'sep',
      { label: 'Koleksiyondan çıkar' + (rows.length > 1 ? ` (${rows.length} dosya)` : ''), icon: 'x', danger: true,
        action: async () => setLibrary(await act('library_exclude', rows.map((r) => r.path))) },
    ]);
  }

  // F88: ekstre/fon raporu gibi belgelerin kendi tarihi; bos birakilirsa icerikten cikarilana doner.
  async function editDate(rows) {
    const current = rows.length === 1 ? rows[0] : null;
    const value = await prompt({
      title: rows.length > 1 ? `${rows.length} dosyanın tarihi` : 'Belge tarihi',
      message: 'Belgenin kendi tarihi (ekstre kesim tarihi, rapor dönemi…). Gün/ay/yıl, ay/yıl ya da yalnızca yıl yazın.'
        + ' Boş bırakırsanız tarih içerikten çıkarılır ("Hepsini hazırla" sırasında).',
      value: current?.date ? current.date.split('-').reverse().join('.') : '',
      placeholder: '15.09.2026 · 09.2026 · 2026', ok: 'Kaydet',
    });
    if (value === null || value === undefined) return;
    const state = await act('library_set_date', rows.map((r) => r.path), value.trim());
    if (state) setLibrary(state);
  }

  function folderMenu(event, folder) {
    openMenu(event, [
      { label: 'Klasörü aç', icon: 'folderOpen', action: () => act('reveal', folder.path) },
      { label: 'Koleksiyondan kaldır', icon: 'x', danger: true, action: async () => setLibrary(await act('library_remove_folder', folder.path)) },
    ]);
  }

  async function add(method) {
    const state = await act(method);
    if (state) setLibrary(state);
  }

  // F85: OCR/transkript, ozet ve indeks kayitlari silinir; ardindan 'Hepsini hazirla' acilir.
  async function resetRows(rows) {
    const ok = await confirm({
      title: rows.length > 1 ? `${rows.length} dosyayı yeniden işle` : 'Dosyayı yeniden işle',
      message: "Aktar'ın bu dosyalar için çıkardığı metin (OCR, altyazı, Whisper), özet ve arama indeksi silinir; "
        + 'ardından "Hepsini hazırla" ile yeniden çıkarılır. Kaynak dosyalarınıza dokunulmaz.',
      list: rows.map((r) => r.name), ok: 'Sil ve yeniden işle', danger: true,
    });
    if (!ok) return;
    const state = await act('library_reset', rows.map((r) => r.path));
    if (!state) return;
    setLibrary(state);
    view.preparing = true;
  }

  async function resetCollection() {
    const ok = await confirm({
      title: 'Koleksiyonu sıfırla',
      message: `"${lib.title}" koleksiyonundaki ${lib.rows.length} dosyanın metinleri (OCR, altyazı, Whisper), özetleri, `
        + 'arama indeksi ve koleksiyon özeti silinir; ardından "Hepsini hazırla" ile yeniden üretilir.\n'
        + 'Kaynak dosyalarınıza ve sohbet geçmişine dokunulmaz.',
      ok: 'Sıfırla', danger: true,
    });
    if (!ok) return;
    const state = await act('library_reset_collection', lib.slug);
    if (!state) return;
    setLibrary(state);
    view.preparing = true;
  }

  function statusClass(row) {
    if (row.busy_text) return 'badge ' + (row.busy_tone === 'danger' ? 'danger' : row.busy_tone === 'dim' ? '' : 'accent');
    return { ready: 'badge ok', transcript: 'badge', no_subtitle: 'badge warning', no_text: 'badge warning', missing: 'badge danger' }[row.status] ?? 'plain';
  }
  let mailOpen = $state(false);
  const queue = $derived(lib.queue);
  const queuePercent = $derived(queue ? Math.round(((queue.done + (queue.percent ?? 0) / 100) * 100) / Math.max(1, queue.total)) : 0);
</script>

<svelte:window onkeydown={keydown} />

<section class="page">
  {#if view.home && lib.collections.length}
    <div class="page-head">
      <h1>Kütüphane</h1>
      <button class="btn" onclick={folderAsCollection}><Icon name="folderPlus" size={16} />Klasörden koleksiyon</button>
      <button class="btn primary" onclick={createCollection}><Icon name="plus" size={16} />Yeni koleksiyon</button>
    </div>
    <div class="page-body">
      <p class="lead dim">{lib.collections.length} koleksiyon · bir koleksiyonu açmak için tıklayın. Pencereye bırakılan klasör yeni koleksiyon olur.</p>
      <div class="grid">
        {#each cards ?? lib.collections as c (c.slug)}
          <button class="ccard" onclick={() => openCollection(c.slug)}>
            <span class="ctop">
              <span class="cicon"><Icon name="library" size={20} /></span>
              <span class="ctitle ellipsis" title={c.title}>{c.title}</span>
            </span>
            <span class="cmeta">{c.count ?? c.files} dosya · {c.folders} klasör</span>
            {#if c.summary}
              <span class="csum">{c.summary}</span>
            {:else}
              <span class="csum empty">Henüz özet yok. Koleksiyonu açıp "Hepsini hazırla" ile hazırlayınca burada özeti görünür.</span>
            {/if}
            {#if c.topics?.length}
              <span class="ctopics">{#each c.topics as topic}<span class="badge ellipsis" title={topic}>{topic}</span>{/each}</span>
            {/if}
          </button>
        {/each}
        <button class="ccard add" onclick={createCollection}>
          <span class="cicon"><Icon name="plus" size={22} /></span>
          <b>Yeni koleksiyon</b>
          <span class="dim">ya da bir klasörü pencereye bırakın</span>
        </button>
      </div>
    </div>
  {:else if !lib.slug}
    <div class="page-body center">
      <div class="drop card">
        <span class="tile"><Icon name="folderPlus" size={32} /></span>
        <b>Klasör veya dosya bırakın</b>
        <span class="dim">Videolar · belgeler (PDF, Word, Excel, EPUB…) · görseller</span>
        <div class="row">
          <button class="btn primary lg" onclick={() => add('library_choose_folder')}><Icon name="folderOpen" />Klasör seç</button>
          <button class="btn lg" onclick={() => add('library_choose_files')}><Icon name="file" />Dosya seç</button>
        </div>
        <span class="note">Klasörün adıyla bir koleksiyon oluşur. Transkriptler çıkarılıp aranabilir yapılır; sonra bütün koleksiyona soru sorabilirsiniz.</span>
      </div>
    </div>
  {:else}
    <div class="page-body">
      <header class="hero">
        <div class="titles">
          <span class="label">Koleksiyon</span>
          <h1 class="ellipsis" title={lib.title}>{lib.title}</h1>
          <span class="meta">{#if lib.scanning}<Icon name="loader" size={14} spin /> Taranıyor…{:else}{lib.meta}{/if}</span>
        </div>
      </header>
      <div class="actions">
          <button class="btn" onclick={() => add('library_choose_folder')}><Icon name="folderPlus" size={16} />Klasör ekle</button>
          <button class="btn" onclick={() => add('library_choose_files')}><Icon name="filePlus" size={16} />Dosya ekle</button>
          <button class="btn" onclick={() => (mailOpen = true)} title="Gmail'deki ekstre ve raporları kurallara göre bu koleksiyona indirir"><Icon name="mail" size={16} />E-postadan al</button>
          <button class="btn" class:watching={lib.watch} onclick={async () => setLibrary(await act('library_set_watch', !lib.watch))}
            title={lib.watch ? 'Klasörler izleniyor: yeni dosyalar (ve e-posta kurallarıyla gelenler) uygulama açıkken kendiliğinden hazırlanır. Kapatmak için tıklayın.' : 'Klasörlere yeni dosya düşünce uygulama açıkken kendiliğinden hazırlansın'}>
            <Icon name="eye" size={16} />{lib.watch ? 'İzleniyor' : 'Klasörü izle'}</button>
          <button class="btn primary lg" disabled={!!queue || !lib.rows.some((r) => !r.missing)} onclick={() => (view.preparing = true)}
            title="Transkriptleri çıkarır, indeksler ve özetler"><Icon name="sparkles" size={16} />Hepsini hazırla</button>
          <button class="btn" disabled={!!queue || !lib.rows.length} onclick={resetCollection}
            title="Koleksiyonun OCR/transkript, özet ve indeks kayıtlarını silip yeniden hazırlar"><Icon name="rotate" size={16} />Sıfırla…</button>
        <span class="grow"></span>
        {#each lib.folders as folder}
          <button class="chip folder" title={folder.path + ' · sağ tık: kaldır'} onclick={() => act('reveal', folder.path)} oncontextmenu={(e) => folderMenu(e, folder)}>
            <Icon name="folder" size={14} />{folder.name}<span class="dim">{folder.count}</span>
          </button>
        {/each}
      </div>


      {#if queue}
        <div class="queue card">
          <div class="qtext">
            <span class="ellipsis">{queue.label}</span>
            <div class="qbar"><div class="track"><i style:width="{queuePercent}%"></i></div><span class="mono dim">{queue.done} / {queue.total}{queue.percent !== null ? ` · %${queue.percent}` : ''}</span></div>
          </div>
          <button class="icon-btn filled" title={queue.paused ? 'Devam' : 'Duraklat (sıradaki dosyadan önce)'} onclick={async () => (app.library.queue = (await act('queue_pause')) ?? queue)}>
            <Icon name={queue.paused ? 'play' : 'pause'} size={16} /></button>
          <button class="icon-btn filled" title="Durdur" onclick={() => act('queue_stop')}><Icon name="stop" size={16} /></button>
        </div>
      {/if}

      <div class="tools">
        <label class="search">
          <Icon name="search" size={18} />
          <input bind:value={view.query} oninput={typed} placeholder="Dosya adında ve içerikte ara…"
            title="Model kullanmadan anında arar; büyük/küçük harf ve Türkçe karakter farkı yok sayılır (asiri = aşırı)." />
          {#if view.query}<button class="icon-btn sm" title="Temizle" onclick={() => { view.query = ''; view.search = null; }}><Icon name="x" size={14} /></button>{/if}
        </label>
        {#each kinds as [kind, label, count]}
          <button class="chip" class:on={view.kind === kind} onclick={() => (view.kind = kind)}>{label} <span class="count">{count}</span></button>
        {/each}
      </div>

      {#if view.search?.searched}
        <div class="hits">
          {#if view.search.hits.length}
            <div class="hits-head dim">İçerikte {view.search.hits.length} eşleşme · {view.search.files} dosya{view.search.limited ? ' (ilk 200 gösteriliyor)' : ''} — tıklayınca o anda / o sayfada açılır</div>
            <div class="hit-list">
              {#each view.search.hits as hit}
                <button class="hit" onclick={() => openFile({ path: hit.path }, hit.start)} title={hit.text}>
                  <span class="hname ellipsis">{hit.name}</span>{#if hit.date}<span class="badge">{hit.date}</span>{/if}<span class="badge accent">{hit.where}</span><span class="htext ellipsis">{hit.text}</span>
                </button>
              {/each}
            </div>
          {:else}
            <div class="hits-head dim">İçerikte eşleşme yok.</div>
          {/if}
        </div>
      {/if}

      <table class="table files">
        <thead><tr><th class="ic"></th>
          {#each Object.entries(COLUMNS) as [column, spec]}
            <th class={column === 'date' ? 'date' : ''}><button class="sort" class:on={sortColumn === column} title={sortTitle(column)} onclick={() => sortBy(column)}>
              {spec.label}{#if sortColumn === column}<Icon name={sortDirection === 'asc' ? 'up' : 'down'} size={14} />{/if}</button></th>
          {/each}</tr></thead>
        <tbody>
          {#each visible as row (row.key)}
            <tr class:on={selected.has(row.key)} class:missing={row.missing} onclick={(e) => click(e, row)} ondblclick={() => openFile(row)}
              oncontextmenu={(e) => rowMenu(e, row)}>
              <td class="ic"><span class="kind"><Icon name={KIND_ICON[row.kind] ?? 'file'} size={16} /></span></td>
              <td class="name"><span class="ellipsis" title={row.path}>{row.name}</span>{#if row.new}<span class="badge accent">yeni</span>{/if}</td>
              <td class="dim ellipsis where" title={row.folder}>{row.where}</td>
              <td class="secondary nowrap date" class:dim={row.date_mail} title={row.date ? (row.date_manual ? 'Elle girildi' : row.date_mail ? 'E-postanın geliş tarihi (içerikten tarih henüz çıkarılmadı)' : 'İçerikten çıkarıldı') + ' · sağ tık: Tarihi düzenle' : 'Tarih yok · sağ tık: Tarihi düzenle'}>
                {#if row.date}{row.date_text}{#if row.date_manual}<Icon name="pencil" size={11} />{/if}{:else}<span class="dim">—</span>{/if}</td>
              <td class:dim={!row.measured} class="secondary nowrap">{row.length}</td>
              <td class:dim={!row.source} class="secondary ellipsis src">{row.source || '—'}</td>
              <td class="nowrap"><span class={statusClass(row)}>{row.busy_text ?? row.status_text}</span></td>
            </tr>
          {:else}
            <tr><td colspan="7" class="empty">{lib.scanning ? 'Taranıyor…' : view.search ? 'Aramayla eşleşen dosya yok.' : 'Bu koleksiyonda dosya yok. Klasör ya da dosya ekleyin.'}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

{#if view.preparing}<PrepareModal onclose={() => (view.preparing = false)} />{/if}
{#if mailOpen}<MailModal onclose={() => (mailOpen = false)} />{/if}

<style>
  .center { display: grid; place-items: center; }
  .drop { width: min(720px, 100%); padding: 48px 32px; display: flex; flex-direction: column; align-items: center; gap: 14px;
    border: 2px dashed var(--outline); background: transparent; text-align: center; }
  .drop b { font-size: 22px; }
  .drop .row { display: flex; gap: 12px; margin-top: 8px; }
  .drop .note { color: var(--secondary); font-size: 13px; max-width: 520px; line-height: 1.6; margin-top: 8px; }
  .tile { width: 72px; height: 72px; border-radius: 16px; display: grid; place-items: center; background: var(--surface); color: var(--accent); }

  .lead { font-size: 13px; margin: 0 0 18px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
  .ccard { display: flex; flex-direction: column; align-items: stretch; gap: 10px; text-align: left; padding: 18px; min-height: 190px; min-width: 0; overflow: hidden;
    border-radius: 14px; background: var(--panel); border: 1px solid var(--outline); color: var(--text);
    transition: border-color .15s, transform .15s, box-shadow .15s; }
  .ccard:hover { border-color: color-mix(in srgb, var(--accent) 55%, var(--outline)); transform: translateY(-2px);
    box-shadow: 0 10px 28px color-mix(in srgb, var(--shadow) 70%, transparent); }
  .ctop { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .cicon { width: 40px; height: 40px; border-radius: 10px; flex: none; display: grid; place-items: center; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, var(--surface)); }
  .ctitle { font-size: 17px; font-weight: 700; letter-spacing: -.01em; min-width: 0; }
  .cmeta { font-size: 12.5px; color: var(--secondary); }
  .csum { width: 100%; text-align: left; font-size: 13px; line-height: 1.55; color: var(--secondary); display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4;
    -webkit-box-orient: vertical; overflow: hidden; }
  .csum.empty { color: var(--dim); font-style: italic; }
  .ctopics { display: flex; flex-wrap: wrap; gap: 4px; margin-top: auto; min-width: 0; }
  .ctopics .badge { max-width: 100%; min-width: 0; display: block; }
  .ccard.add { align-items: center; justify-content: center; gap: 8px; border-style: dashed; background: transparent; color: var(--secondary); }
  .ccard.add:hover { color: var(--text); }
  .ccard.add b { font-size: 15px; color: var(--text); }
  .ccard.add .dim { font-size: 12.5px; }
  .hero { display: flex; align-items: flex-end; gap: 24px; padding: 4px 0 20px; }
  .titles { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .titles h1 { font-size: clamp(28px, 3.4vw, 44px); font-weight: 800; letter-spacing: -.03em; line-height: 1.15; }
  .meta { color: var(--secondary); font-size: 13px; display: flex; align-items: center; gap: 6px; }
  .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
  .actions .grow { flex: 1; }
  .btn.watching { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, transparent); }
  .folder { display: inline-flex; align-items: center; gap: 6px; height: 30px; font-size: 12.5px; }
  .folder :global(svg) { color: var(--secondary); }

  .queue { display: flex; align-items: center; gap: 12px; padding: 12px 16px; margin-bottom: 16px; border-color: color-mix(in srgb, var(--accent) 35%, var(--outline)); }
  .qtext { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
  .qbar { display: flex; align-items: center; gap: 12px; font-size: 12px; }

  .tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .search { flex: 1; min-width: 260px; max-width: 460px; height: 40px; display: flex; align-items: center; gap: 10px; padding: 0 6px 0 14px;
    border-radius: 999px; background: var(--surface); color: var(--secondary); border: 1px solid var(--field-border); transition: border-color .15s, box-shadow .15s; }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .search input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; color: var(--text); }
  .search input::placeholder { color: var(--dim); }
  .count { color: var(--dim); margin-left: 4px; }
  .chip.on .count { color: inherit; opacity: .7; }

  .hits { margin-bottom: 12px; }
  .hits-head { font-size: 12px; padding: 0 4px 6px; }
  .hit-list { max-height: 200px; overflow: auto; border-radius: 10px; background: var(--panel); border: 1px solid var(--outline); padding: 4px; }
  .hit { display: flex; align-items: center; gap: 10px; width: 100%; padding: 7px 10px; border-radius: 6px; text-align: left; font-size: 13px; }
  .hit:hover { background: var(--surface-hover); }
  .hname { max-width: 260px; font-weight: 600; flex: none; }
  .htext { flex: 1; color: var(--secondary); }

  .page-body { container-type: inline-size; }
  .files { table-layout: fixed; }
  @container (max-width: 860px) { .files .where, .files th:nth-child(3) { display: none; } }
  @container (max-width: 700px) { .files .src, .files th:nth-child(6) { display: none; } }
  .files th { background: var(--window); }
  .files th.ic, .files td.ic { width: 52px; }
  .files th:nth-child(3) { width: 18%; }
  .files th.date { width: 104px; }
  .files th:nth-child(5) { width: 96px; }
  .files th:nth-child(6) { width: 18%; }
  .files th:nth-child(7) { width: 190px; }
  .sort { display: inline-flex; align-items: center; gap: 4px; font: inherit; color: inherit; padding: 0; }
  .sort.on { color: var(--accent); }
  td.date :global(svg) { margin-left: 4px; vertical-align: -1px; color: var(--dim); }
  .files tr { cursor: default; }
  .files td { padding: 8px 12px; }
  .kind { width: 32px; height: 32px; border-radius: 4px; background: var(--surface); display: grid; place-items: center; color: var(--secondary); }
  tr.on .kind { color: var(--accent); }
  .name { display: flex; align-items: center; gap: 8px; min-width: 0; height: 48px; font-weight: 500; }
  .name > span:first-child { min-width: 0; }
  tr.missing .name { color: var(--dim); text-decoration: line-through; }
  .nowrap { white-space: nowrap; }
  .plain { color: var(--dim); font-size: 12px; }
</style>
