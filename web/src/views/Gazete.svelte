<script>
  // F225 Gazete: gunluk sayiyi makalelere ayirma ve duzeltme (bridge_gazete). Solda sayfalar, ortada sayfa
  // goruntusu ve makale kutulari (SVG, sayfa pikseli koordinatlari), sagda secili makalenin basligi ve metni.
  // Kutular surukleyerek cizilir: 'Yeni makale' kipinde yeni makale, 'Kutu ekle' kipinde secili makaleye
  // govde kutusu, 'Başlık kutusu' kipinde secili makalenin baslik kutusu. Kutular degisince makale yeniden okunur.
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { confirm, prompt } from '../lib/confirm.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';

  const COLORS = ['#e5484d', '#30a46c', '#3e63dd', '#f76b15', '#8e4ec6', '#12a594', '#d6409f', '#978365'];

  let issues = $state([]);
  let current = $state(null);       // telefonun gordugu sayi
  let server = $state(null);
  let issue = $state(null);         // gazete_open sonucu
  let page = $state(1);
  let selected = $state(null);      // makale kimligi
  let mode = $state('select');      // 'select' | 'new' | 'box' | 'head' | 'merge'
  let draft = $state(null);         // cizilen kutu [x1, y1, x2, y2]
  let busy = $state(false);
  let title = $state('');
  let text = $state('');
  let svg = $state(null);
  let audio = $state(null);
  let showPhone = $state(false);

  const pageInfo = $derived(issue?.pages.find((p) => p.page === page) ?? null);
  const pageArticles = $derived((issue?.articles ?? []).filter((a) => a.page === page)
    .sort((a, b) => top(a) - top(b) || left(a) - left(b)));
  const article = $derived(issue?.articles.find((a) => a.id === selected) ?? null);
  const shownText = $derived(article ? (article.edited ?? article.text ?? '') : '');
  const dirty = $derived(!!article && (title !== (article.title ?? '') || text !== shownText));
  const job = $derived(app.gazete.job);

  function top(a) { return (a.head ?? a.boxes[0] ?? [0, 0])[1]; }
  function left(a) { return (a.head ?? a.boxes[0] ?? [0, 0])[0]; }
  const colorOf = (a) => COLORS[pageArticles.indexOf(a) % COLORS.length];
  const pageCounts = (p) => {
    const list = (issue?.articles ?? []).filter((a) => a.page === p);
    return { all: list.length, reviewed: list.filter((a) => a.reviewed).length };
  };

  async function refresh() {
    const result = await act('gazete_list');
    if (!result) return;
    issues = result.issues;
    current = result.current;
    server = result.server;
    if (!issue && issues.length) await open(current ?? issues[0].name);
  }
  refresh();

  async function open(name, keep = false) {
    const result = await act('gazete_open', name);
    if (!result) return;
    apply(result);
    if (!keep) { page = 1; selected = null; }
  }

  function apply(result) {
    issue = result;
    if (selected && !result.articles.some((a) => a.id === selected)) selected = null;
    syncFields();
  }

  function syncFields() {
    const a = issue?.articles.find((item) => item.id === selected);
    title = a?.title ?? '';
    text = a ? (a.edited ?? a.text ?? '') : '';
    audio = null;
  }

  // Arka plandaki is bir sayfayi/makaleyi bitirince ya da is bitince acik sayi yenilenir.
  let seen = 0;
  $effect(() => {
    const count = app.gazete.pageDone;
    const done = app.gazete.finished;
    if (!issue || (count === seen && !done)) return;
    seen = count;
    if (done) { app.gazete.finished = null; refreshKeep(); return; }
    if (!dirty) refreshKeep();
  });
  async function refreshKeep() {
    if (issue) await open(issue.name, true);
    const result = await act('gazete_list');
    if (result) { issues = result.issues; current = result.current; server = result.server; }
  }

  async function select(id) {
    if (id === selected) return;
    if (dirty && !(await confirm({ title: 'Değişiklik kaydedilmedi', message: 'Makaledeki düzeltme kaydedilmeden başka makaleye geçilsin mi?', ok: 'Kaydetmeden geç' }))) return;
    selected = id;
    syncFields();
  }

  async function goPage(next) {
    next = Math.max(1, Math.min(issue?.pages.length ?? 1, next));
    if (next === page) return;
    if (dirty && !(await confirm({ title: 'Değişiklik kaydedilmedi', message: 'Kaydedilmeden başka sayfaya geçilsin mi?', ok: 'Kaydetmeden geç' }))) return;
    page = next;
    selected = null;
    mode = 'select';
    syncFields();
  }

  // ---- iceri aktarma
  function addMenu(event) {
    openMenu(event, [
      { label: 'Sayfa görüntüleri klasörü…', icon: 'folderOpen', action: () => addIssue('folder') },
      { label: 'E-gazete PDF…', icon: 'file', action: () => addIssue('pdf') },
    ]);
  }

  async function addIssue(kind) {
    const chosen = await act('gazete_choose', kind);
    if (!chosen) return;
    const today = new Date().toISOString().slice(0, 10);
    const name = await prompt({ title: 'Yeni sayı', message: 'Sayının adı (telefonda da görünür):', value: today, ok: 'Hazırla' });
    if (name === null) return;
    const result = await act('gazete_import', chosen.path, name.trim() || today, name.trim() || today);
    if (result) {
      app.gazete.job = { stage: 'Başlıyor…', done: 0, total: 0 };
      setTimeout(async () => { await refresh(); if (issues.length) await open(issues[0].name, true); }, 1500);
    }
  }

  // ---- cizim
  function point(event) {
    const rect = svg.getBoundingClientRect();
    return [(event.clientX - rect.left) / rect.width * pageInfo.width, (event.clientY - rect.top) / rect.height * pageInfo.height];
  }
  let anchor = null;
  function down(event) {
    if (mode === 'select' || mode === 'merge' || busy || event.button !== 0) return;
    if ((mode === 'box' || mode === 'head') && !article) { toast('Önce bir makale seçin.'); return; }
    anchor = point(event);
    draft = [...anchor, ...anchor];
    svg.setPointerCapture(event.pointerId);
  }
  function move(event) {
    if (!anchor) return;
    const [x, y] = point(event);
    draft = [Math.min(anchor[0], x), Math.min(anchor[1], y), Math.max(anchor[0], x), Math.max(anchor[1], y)];
  }
  async function up() {
    if (!anchor) return;
    anchor = null;
    const box = draft;
    draft = null;
    if (!box || box[2] - box[0] < 20 || box[3] - box[1] < 20) return;
    busy = true;
    let result = null;
    if (mode === 'new') {
      const before = new Set(issue.articles.map((a) => a.id));
      result = await act('gazete_add_article', issue.name, page, box);
      if (result) {
        apply(result);
        selected = result.articles.find((a) => !before.has(a.id))?.id ?? null;
        syncFields();
        mode = 'box';
      }
    } else if (mode === 'box') {
      result = await act('gazete_set_boxes', issue.name, article.id, article.head, [...article.boxes, box]);
    } else if (mode === 'head') {
      result = await act('gazete_set_boxes', issue.name, article.id, box, article.boxes);
      mode = 'box';
    }
    if (result && mode !== 'new') { apply(result); syncFields(); }
    busy = false;
  }

  async function clickArticle(event, a) {
    if (mode === 'merge' && article && a.id !== article.id) {
      event.stopPropagation();
      busy = true;
      const result = await act('gazete_merge', issue.name, a.id, article.id);
      busy = false;
      mode = 'select';
      if (result) apply(result);
      return;
    }
    if (mode === 'select' || mode === 'merge') select(a.id);
  }

  // ---- makale islemleri
  async function save(values = {}) {
    if (!article) return;
    busy = true;
    const payload = { ...values };
    if (title !== (article.title ?? '')) payload.title = title;
    if (text !== shownText) payload.edited = text;
    const result = await act('gazete_save_article', issue.name, article.id, payload);
    busy = false;
    if (result) { apply(result); return true; }
    return false;
  }

  async function toggleReviewed() {
    const next = !article.reviewed;
    if (await save({ reviewed: next }) && next) {
      // sonraki gozden gecirilmemis makaleye gec
      const nextOne = pageArticles.find((a) => !a.reviewed);
      if (nextOne) { selected = nextOne.id; syncFields(); }
    }
  }

  async function removeBox(index, head = false) {
    const boxes = head ? article.boxes : article.boxes.filter((_, i) => i !== index);
    const headBox = head ? null : article.head;
    if (!boxes.length && !headBox) return removeArticle();
    busy = true;
    const result = await act('gazete_set_boxes', issue.name, article.id, headBox, boxes);
    busy = false;
    if (result) { apply(result); syncFields(); }
  }

  async function moveBox(index, delta) {
    const boxes = [...article.boxes];
    const target = index + delta;
    if (target < 0 || target >= boxes.length) return;
    [boxes[index], boxes[target]] = [boxes[target], boxes[index]];
    busy = true;
    const result = await act('gazete_set_boxes', issue.name, article.id, article.head, boxes);
    busy = false;
    if (result) { apply(result); syncFields(); }
  }

  async function removeArticle() {
    if (!(await confirm({ title: 'Makaleyi sil', message: `"${article.title || 'Başlıksız'}" sayıdan çıkarılsın mı?`, ok: 'Sil', danger: true }))) return;
    const result = await act('gazete_delete_article', issue.name, article.id);
    if (result) { selected = null; apply(result); }
  }

  async function reread() {
    busy = true;
    const result = await act('gazete_reread', issue.name, article.id);
    busy = false;
    if (result) { apply(result); syncFields(); }
  }

  async function revertText() {
    busy = true;
    const result = await act('gazete_save_article', issue.name, article.id, { edited: null });
    busy = false;
    if (result) { apply(result); syncFields(); }
  }

  async function repropose() {
    const kept = pageArticles.filter((a) => a.reviewed).length;
    const ok = await confirm({ title: 'Sayfayı yeniden böl', message: `Bu sayfanın makaleleri yeniden önerilir.${kept ? ` Gözden geçirilmiş ${kept} makale korunur;` : ''} diğer düzeltmeler silinir.`, ok: 'Yeniden böl', danger: true });
    if (!ok) return;
    const result = await act('gazete_propose', issue.name, page);
    if (result) app.gazete.job = { stage: 'Sayfa bölünüyor…', done: 0, total: 1 };
  }

  async function listen() {
    const result = await act('gazete_audio_url', issue.name, article.id);
    if (result?.url) audio = result.url; else toast('Bu makalenin sesi henüz üretilmedi.');
  }

  // ---- sayi islemleri
  async function voice() {
    const result = await act('gazete_voice', issue.name, false);
    if (result) app.gazete.job = { stage: 'Ses motoru yükleniyor', done: 0, total: 0 };
  }

  async function makeCurrent() {
    const result = await act('gazete_set_current', issue.name);
    if (result) { current = result.current; issue.current = true; toast('Telefon artık bu sayıyı görüyor.', 'ok'); }
  }

  async function rename() {
    const value = await prompt({ title: 'Sayının adı', value: issue.title, ok: 'Kaydet' });
    if (value === null) return;
    const result = await act('gazete_rename', issue.name, value);
    if (result) { apply(result); refreshKeep(); }
  }

  async function removeIssue() {
    if (!(await confirm({ title: 'Sayıyı sil', message: `"${issue.title}" sayısı, sayfaları, düzeltmeleri ve sesleriyle silinsin mi?`, ok: 'Sil', danger: true }))) return;
    const result = await act('gazete_delete', issue.name);
    if (!result) return;
    issues = result.issues; current = result.current; issue = null; selected = null;
    if (issues.length) open(issues[0].name);
  }

  function issueMenu(event) {
    openMenu(event, [
      { label: 'Adını değiştir', icon: 'pencil', action: rename },
      { label: 'Sayıyı sil', icon: 'trash', danger: true, action: removeIssue },
    ]);
  }

  // ---- telefon sunucusu
  async function toggleServer() {
    const result = await act(server?.running ? 'gazete_server_stop' : 'gazete_server_start');
    if (result) server = result;
  }
  async function removePhone(id) {
    const result = await act('gazete_phone_remove', id);
    if (result) server = result;
  }

  function keydown(event) {
    if (event.target.closest?.('input, textarea, select')) return;
    if (event.key === 'Escape') { mode = 'select'; draft = null; anchor = null; }
    else if (event.key === 'PageDown' || (event.key === 'ArrowRight' && event.altKey)) goPage(page + 1);
    else if (event.key === 'PageUp' || (event.key === 'ArrowLeft' && event.altKey)) goPage(page - 1);
    else if (event.key === 'n') mode = 'new';
    else if (event.key === 'b' && article) mode = 'box';
    else if (event.key === 'Delete' && article) removeArticle();
  }
</script>

<svelte:window onkeydown={keydown} />

<section class="page">
  <div class="page-head">
    <h1>Gazete</h1>
    {#if issues.length}
      <select class="field issue" value={issue?.name ?? ''} onchange={(e) => open(e.currentTarget.value)} title="Sayı">
        {#each issues as item}<option value={item.name}>{item.title}{item.name === current ? ' • telefonda' : ''}</option>{/each}
      </select>
      {#if issue}<button class="icon-btn sm" title="Sayı işlemleri" onclick={issueMenu}><Icon name="more" size={16} /></button>{/if}
    {/if}
    <span class="grow"></span>
    {#if job}
      <span class="job"><Icon name="loader" size={15} spin />{job.stage}{job.total ? ` ${job.done}/${job.total}` : ''}</span>
      <button class="btn sm ghost" onclick={() => act('gazete_cancel')}>Durdur</button>
    {/if}
    <button class="btn" onclick={addMenu} disabled={!!job}><Icon name="plus" size={16} />Sayı ekle</button>
    {#if issue}
      {#if !issue.current}<button class="btn" onclick={makeCurrent} title="Telefon bu sayıyı görsün"><Icon name="smartphone" size={16} />Telefona ver</button>{/if}
      <button class="btn" onclick={voice} disabled={!!job} title="Sesi olmayan ya da metni değişen makaleleri seslendir"><Icon name="waveform" size={16} />Seslendir</button>
    {/if}
    <button class="btn" class:primary={server?.running} onclick={() => (showPhone = !showPhone)}>
      <Icon name="smartphone" size={16} />Telefon{server?.running ? ': açık' : ''}</button>
  </div>

  {#if showPhone && server}
    <div class="phone card">
      <div class="row">
        <b>Telefon sunucusu</b>
        <span class="dim">{server.running ? 'Yerel ağdaki telefon bağlanabilir.' : 'Kapalı. Açınca yalnızca yerel ağdan erişilir; Aktar kapanınca durur.'}</span>
        <span class="grow"></span>
        <button class="btn sm" class:primary={!server.running} onclick={toggleServer}>{server.running ? 'Kapat' : 'Aç'}</button>
      </div>
      {#if server.running}
        <div class="row pair">
          <div><small>Telefona yazılacak adres</small>{#each server.addresses as address}<code class="selectable">{address}</code>{:else}<span class="dim">Yerel ağ adresi bulunamadı</span>{/each}</div>
          <div><small>Eşleme kodu</small><code class="code selectable">{server.code}</code></div>
        </div>
      {/if}
      {#if server.phones.length}
        <div class="phones">
          <small>Eşlenen telefonlar</small>
          {#each server.phones as phone}
            <div class="row"><span>{phone.ad}</span><span class="dim">{phone.eslesme}</span><span class="grow"></span>
              <button class="icon-btn sm" title="Eşlemeyi kaldır" onclick={() => removePhone(phone.id)}><Icon name="x" size={14} /></button></div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  {#if !issue}
    <div class="empty card">
      <Icon name="newspaper" size={40} />
      <b>Henüz sayı yok</b>
      <span>E-gazetenin sayfa görüntülerini ya da PDF'ini ekleyin. Aktar sayfaları makalelere ayırmayı önerir ve okur; siz kutuları düzeltirsiniz, sonra makaleler seslendirilir.</span>
      <button class="btn primary" onclick={addMenu}><Icon name="plus" size={16} />Sayı ekle</button>
    </div>
  {:else}
    <div class="work">
      <aside class="pages card">
        <div class="head">Sayfalar <small>{issue.pages.length}</small></div>
        <div class="list">
          {#each issue.pages as p}
            {@const count = pageCounts(p.page)}
            <button class="pg" class:on={p.page === page} onclick={() => goPage(p.page)}>
              <b>{p.page}</b>
              <span class="dim">{count.all} makale</span>
              {#if count.all}<span class="badge" class:ok={count.reviewed === count.all}>{count.reviewed}/{count.all}</span>{/if}
            </button>
          {/each}
        </div>
      </aside>

      <div class="viewer card">
        <div class="tools">
          <button class="icon-btn sm" title="Önceki sayfa (PageUp)" disabled={page <= 1} onclick={() => goPage(page - 1)}><Icon name="back" size={15} /></button>
          <span class="dim">{page} / {issue.pages.length}</span>
          <button class="icon-btn sm" title="Sonraki sayfa (PageDown)" disabled={page >= issue.pages.length} onclick={() => goPage(page + 1)}><Icon name="forward" size={15} /></button>
          <span class="sep"></span>
          <button class="btn sm" class:on={mode === 'select'} onclick={() => (mode = 'select')}>Seç</button>
          <button class="btn sm" class:on={mode === 'new'} title="Makalenin tamamını çerçeveleyin; sütunlar kendiliğinden okunur (N)" onclick={() => (mode = 'new')}><Icon name="plus" size={13} />Yeni makale</button>
          <button class="btn sm" class:on={mode === 'box'} disabled={!article} title="Seçili makaleye kutu ekle: başka sütun ya da devam (B)" onclick={() => (mode = 'box')}>Kutu ekle</button>
          <button class="btn sm" class:on={mode === 'head'} disabled={!article} onclick={() => (mode = 'head')}>Başlık kutusu</button>
          <button class="btn sm" class:on={mode === 'merge'} disabled={!article} title="Tıklanan makale seçili makaleye katılır" onclick={() => (mode = 'merge')}>Birleştir</button>
          <span class="grow"></span>
          {#if busy}<Icon name="loader" size={15} spin />{/if}
          <button class="btn sm ghost" disabled={!!job} onclick={repropose} title="Bu sayfanın makalelerini yeniden öner"><Icon name="refresh" size={13} />Yeniden böl</button>
        </div>
        {#if mode !== 'select'}
          <div class="hint">{mode === 'new' ? 'Yeni makalenin tamamını (başlık ve sütunlar) sürükleyerek çerçeveleyin.'
            : mode === 'box' ? 'Seçili makaleye eklenecek bölgeyi çizin.'
            : mode === 'head' ? 'Seçili makalenin başlığını çerçeveleyin.'
            : 'Seçili makaleye katılacak makaleye tıklayın.'} <kbd>Esc</kbd> ile çıkın.</div>
        {/if}
        <div class="image">
          {#if pageInfo}
            <div class="sheet">
              <img src={pageInfo.url} alt="{page}. sayfa" draggable="false" />
              <svg bind:this={svg} viewBox="0 0 {pageInfo.width} {pageInfo.height}" class:draw={mode === 'new' || mode === 'box' || mode === 'head'}
                onpointerdown={down} onpointermove={move} onpointerup={up} role="presentation">
                {#each pageArticles as a (a.id)}
                  {@const color = colorOf(a)}
                  <g class="art" class:on={a.id === selected} class:dim={selected && a.id !== selected} onclick={(e) => clickArticle(e, a)} role="presentation">
                    {#if a.head}<rect x={a.head[0]} y={a.head[1]} width={a.head[2] - a.head[0]} height={a.head[3] - a.head[1]} stroke={color} fill={color} class="headbox" />{/if}
                    {#each a.boxes as b, i}
                      <rect x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]} stroke={color} fill={color} />
                      {#if a.boxes.length > 1}<text x={b[0] + 12} y={b[1] + 60} fill={color}>{i + 1}</text>{/if}
                    {/each}
                    {#if a.reviewed}{@const at = a.head ?? a.boxes[0]}<circle cx={at[2] - 30} cy={at[1] + 30} r="22" fill={color} /><text class="tick" x={at[2] - 30} y={at[1] + 42}>✓</text>{/if}
                  </g>
                {/each}
                {#if draft}<rect class="draft" x={draft[0]} y={draft[1]} width={draft[2] - draft[0]} height={draft[3] - draft[1]} />{/if}
              </svg>
            </div>
          {/if}
        </div>
      </div>

      <div class="editor card">
        {#if article}
          <div class="head">
            <span class="swatch" style:background={colorOf(article)}></span>Makale
            <span class="grow"></span>
            {#if article.audio}<button class="btn sm ghost" onclick={listen}><Icon name="headphones" size={13} />Dinle</button>{/if}
            <button class="icon-btn sm" title="Makaleyi sil (Delete)" onclick={removeArticle}><Icon name="trash" size={14} /></button>
          </div>
          {#if audio}<audio class="player" src={audio} controls autoplay></audio>{/if}
          <input class="field title" bind:value={title} placeholder="Başlık" />
          <textarea class="field text selectable" bind:value={text} spellcheck="false"></textarea>
          <div class="actions">
            {#if article.edited != null}<button class="btn sm ghost" onclick={revertText} title="Düzeltmeyi sil, OCR metnine dön">OCR'a dön</button>{/if}
            <button class="btn sm ghost" disabled={busy} onclick={reread} title="Kutuları yeniden okut"><Icon name="refresh" size={13} />Yeniden oku</button>
            <span class="grow"></span>
            <button class="btn sm" disabled={!dirty || busy} onclick={() => save()}>Kaydet</button>
            <button class="btn sm" class:primary={!article.reviewed} disabled={busy} onclick={toggleReviewed}>
              <Icon name="check" size={13} />{article.reviewed ? 'Gözden geçirildi' : 'Tamam, sonraki'}</button>
          </div>
          <div class="head">Kutular <small>okuma sırası</small></div>
          <div class="boxes">
            {#if article.head}<div class="bx"><span>Başlık</span><span class="grow"></span><button class="icon-btn sm" title="Başlık kutusunu kaldır" onclick={() => removeBox(0, true)}><Icon name="x" size={13} /></button></div>{/if}
            {#each article.boxes as _box, i}
              <div class="bx"><span>{i + 1}. bölge</span><span class="grow"></span>
                <button class="icon-btn sm" title="Yukarı" disabled={i === 0} onclick={() => moveBox(i, -1)}><Icon name="up" size={13} /></button>
                <button class="icon-btn sm" title="Aşağı" disabled={i === article.boxes.length - 1} onclick={() => moveBox(i, 1)}><Icon name="down" size={13} /></button>
                <button class="icon-btn sm" title="Kutuyu kaldır" onclick={() => removeBox(i)}><Icon name="x" size={13} /></button></div>
            {/each}
          </div>
        {:else}
          <div class="head">Bu sayfadaki makaleler <small>{pageArticles.length}</small></div>
          <div class="arts">
            {#each pageArticles as a (a.id)}
              <button class="ar" onclick={() => select(a.id)}>
                <span class="swatch" style:background={colorOf(a)}></span>
                <span class="ellipsis">{a.title || 'Başlıksız'}</span>
                {#if a.reviewed}<Icon name="check" size={13} />{/if}
                {#if a.audio}<Icon name="headphones" size={13} />{/if}
              </button>
            {:else}
              <div class="dim pad">Bu sayfada makale yok. "Yeni makale" ile çerçeveleyin.</div>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .grow { flex: 1; }
  .issue { width: 260px; }
  .dim { color: var(--dim); font-size: 13px; }
  .job { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--secondary); }
  .card { min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 12px 14px 8px; font-weight: 700; font-size: 13px; }
  .head small { color: var(--dim); font-weight: 500; }
  .phone { margin: 0 32px 14px; padding: 12px 16px; gap: 10px; }
  .phone .row { display: flex; align-items: center; gap: 10px; }
  .phone small { display: block; color: var(--dim); font-size: 11px; margin-bottom: 2px; }
  .pair { gap: 32px !important; }
  .pair code { display: block; font-size: 16px; }
  .pair .code { font-size: 26px; letter-spacing: .2em; font-weight: 700; }
  .phones .row { font-size: 13px; }
  .empty { margin: 0 32px; padding: 48px; align-items: center; text-align: center; gap: 12px; color: var(--secondary); }
  .empty span { max-width: 520px; }
  .work { flex: 1; min-height: 0; display: grid; grid-template-columns: 170px minmax(0, 1fr) 420px; gap: 14px; padding: 0 32px 24px; }
  .list { overflow: auto; padding: 0 8px 8px; }
  .pg { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; border-radius: 8px; text-align: left; }
  .pg b { width: 22px; text-align: right; }
  .pg:hover { background: var(--surface-hover); }
  .pg.on { background: var(--surface); }
  .pg .badge { margin-left: auto; font-size: 11px; }
  .pg .badge.ok { color: var(--success, #30a46c); }
  .tools { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-bottom: 1px solid var(--outline); flex-wrap: wrap; }
  .tools .sep { width: 1px; height: 20px; background: var(--outline); margin: 0 4px; }
  .tools .btn.on { background: var(--accent); color: var(--on-accent, #fff); border-color: var(--accent); }
  .viewer { position: relative; }
  /* ipucu sayfanin ustune biner: cizim kipine girince goruntu imlecin altindan kaymasin */
  .hint { position: absolute; left: 12px; right: 12px; bottom: 12px; z-index: 2; padding: 8px 12px; border-radius: 8px;
    font-size: 12px; color: var(--text); background: var(--surface); box-shadow: 0 4px 18px var(--shadow); pointer-events: none; }
  .hint kbd { font: inherit; font-weight: 700; }
  .image { flex: 1; overflow: auto; background: var(--window); padding: 12px; }
  .sheet { position: relative; width: 100%; max-width: 1100px; margin: 0 auto; }
  .sheet img { width: 100%; height: auto; display: block; box-shadow: 0 4px 18px var(--shadow); user-select: none; }
  .sheet svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .sheet svg.draw { cursor: crosshair; }
  .art rect { fill-opacity: .08; stroke-width: 6; cursor: pointer; }
  .art rect.headbox { fill-opacity: .18; stroke-dasharray: 18 10; }
  .art.on rect { fill-opacity: .2; stroke-width: 10; }
  .art.dim { opacity: .45; }
  .art text { font: 700 52px var(--sans); pointer-events: none; }
  .art text.tick { fill: #fff; text-anchor: middle; font-size: 34px; }
  svg.draw .art { pointer-events: none; }
  .draft { fill: var(--accent); fill-opacity: .15; stroke: var(--accent); stroke-width: 6; stroke-dasharray: 16 10; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  .player { margin: 0 12px 8px; width: calc(100% - 24px); }
  .title { margin: 0 12px 8px; font-weight: 700; }
  .text { flex: 1; min-height: 200px; margin: 0 12px; resize: none; font: 14px/1.6 var(--sans); }
  .actions { display: flex; align-items: center; gap: 6px; padding: 8px 12px; }
  .boxes, .arts { overflow: auto; padding: 0 12px 12px; display: flex; flex-direction: column; gap: 4px; max-height: 32%; }
  .arts { max-height: none; flex: 1; }
  .bx { display: flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 8px; background: var(--surface); font-size: 12px; }
  .ar { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: 8px; text-align: left; font-size: 13px; }
  .ar:hover { background: var(--surface-hover); }
  .ellipsis { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pad { padding: 8px; }
  @media (max-width: 1300px) { .work { grid-template-columns: 130px minmax(0, 1fr) 340px; } }
</style>
