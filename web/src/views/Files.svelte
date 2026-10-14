<script>
  // Dosya incele: koleksiyona eklemeden tek dosya acip soru sorma; son incelenenler listesi.
  import Icon from '../lib/Icon.svelte';
  import { app, act, onDrop, toast, refreshFiles, inspectFile, setLibrary, go, openInTranslate } from '../lib/state.svelte.js';
  import { choose, confirm, prompt } from '../lib/confirm.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';

  const KIND_ICON = { video: 'film', document: 'fileText', image: 'image' };
  const KIND_LABEL = { video: 'Video', document: 'Belge', image: 'Görsel' };

  refreshFiles();

  onDrop('files', async (paths) => {
    // Birden cok dosya birakilirsa hepsi listeye girer, ilki acilir.
    for (const path of paths.slice(1).reverse()) await act('files_touch', path);
    if (paths.length) await inspectFile(paths[0]);
  });

  async function pick() {
    const path = await act('files_choose');
    if (path) await inspectFile(path);
  }

  function when(stamp) {
    const date = new Date(stamp);
    if (Number.isNaN(date.getTime())) return '';
    const days = Math.floor((Date.now() - date.getTime()) / 86400000);
    const time = date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    if (days < 1 && new Date().getDate() === date.getDate()) return 'Bugün ' + time;
    if (days < 2) return 'Dün ' + time;
    if (days < 7) return date.toLocaleDateString('tr-TR', { weekday: 'long' });
    return date.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  async function forget(item) {
    const ok = await confirm({ title: 'Listeden kaldır', message: `"${item.name}" listeden kaldırılsın mı?\nKayıtlı sohbeti de silinir; dosyanın kendisine dokunulmaz.`, ok: 'Kaldır', danger: true });
    if (!ok) return;
    const result = await act('files_forget', item.path);
    if (result) app.files = result.items;
  }

  async function addToCollection(item) {
    const collections = app.library.collections;
    const options = [...collections.map((c) => ({ value: c.slug, label: c.title })), { value: '__new', label: '+ Yeni koleksiyon' }];
    const slug = await choose({ title: 'Koleksiyona ekle', message: item.name, options, ok: 'Ekle' });
    if (!slug) return;
    if (slug === '__new') {
      const title = await prompt({ title: 'Yeni koleksiyon', message: 'Koleksiyon adı:', ok: 'Oluştur' });
      if (!title?.trim()) return;
      const state = await act('new_collection', title.trim());
      if (!state) return;
      setLibrary(state);
    } else {
      const state = await act('library_open', slug);
      if (!state) return;
      setLibrary(state);
    }
    const state = await act('library_add_paths', [item.path]);
    if (!state) return;
    setLibrary(state);
    toast(`${item.name} koleksiyona eklendi.`, 'ok');
    go('library');
  }

  function menu(event, item) {
    openMenu(event, [
      { label: item.kind === 'video' ? 'Oynat ve soru sor' : 'Aç ve soru sor', icon: item.kind === 'video' ? 'play' : 'eye', disabled: item.missing, action: () => inspectFile(item.path) },
      { label: 'Altyazıyı çevir…', icon: 'languages', disabled: item.missing || item.kind !== 'video', action: () => openInTranslate(item.path) },
      { label: 'Koleksiyona ekle…', icon: 'folderPlus', disabled: item.missing, action: () => addToCollection(item) },
      { label: 'Dosya konumunu aç', icon: 'folderOpen', disabled: item.missing, action: () => act('reveal', item.path) },
      'sep',
      { label: 'Listeden kaldır', icon: 'x', danger: true, action: () => forget(item) },
    ]);
  }
</script>

<section class="page">
  <div class="page-head">
    <h1>Dosya incele</h1>
    <button class="btn primary" onclick={pick}><Icon name="file" size={16} />Dosya seç</button>
  </div>
  <div class="page-body">
    <button class="drop" class:compact={app.files.length} onclick={pick}>
      <span class="tile"><Icon name="fileSearch" size={app.files.length ? 22 : 30} /></span>
      <span class="text">
        <b>Bir dosya bırakın ya da seçin</b>
        <span class="dim">Koleksiyona eklenmeden açılır: videoyu izleyip soru sorun, belgeyi okuyup sorun.</span>
      </span>
    </button>

    {#if app.files.length}
      <div class="label head">Son incelenenler</div>
      <div class="list">
        {#each app.files as item (item.path)}
          <div class="item" class:missing={item.missing} role="button" tabindex="0" title={item.path}
            onclick={() => (item.missing ? toast('Dosya bulunamadı: ' + item.path, 'error') : inspectFile(item.path))}
            onkeydown={(e) => e.key === 'Enter' && !item.missing && inspectFile(item.path)}
            oncontextmenu={(e) => menu(e, item)}>
            <span class="kind"><Icon name={KIND_ICON[item.kind] ?? 'file'} size={18} /></span>
            <span class="info">
              <span class="name ellipsis">{item.name}</span>
              <span class="sub ellipsis">{item.missing ? 'Dosya bulunamadı · ' : ''}{KIND_LABEL[item.kind] ?? 'Dosya'} · {item.folder}</span>
            </span>
            <span class="when dim">{when(item.opened)}</span>
            <button class="icon-btn sm more" title="Diğer" onclick={(e) => { e.stopPropagation(); menu(e, item); }}><Icon name="more" size={16} /></button>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</section>

<style>
  .drop { width: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; text-align: center;
    padding: 56px 24px; border: 2px dashed var(--outline); border-radius: 16px; color: var(--text); transition: border-color .15s, background .15s; }
  .drop:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 4%, transparent); }
  .drop .text { display: flex; flex-direction: column; gap: 6px; }
  .drop b { font-size: 20px; }
  .drop .dim { font-size: 13px; }
  .drop.compact { flex-direction: row; justify-content: flex-start; text-align: left; padding: 16px 20px; gap: 16px; }
  .drop.compact b { font-size: 15px; }
  .tile { width: 64px; height: 64px; border-radius: 14px; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }
  .compact .tile { width: 44px; height: 44px; border-radius: 10px; }

  .head { padding: 26px 4px 10px; }
  .list { display: flex; flex-direction: column; gap: 2px; }
  .item { display: flex; align-items: center; gap: 14px; padding: 8px 10px; border-radius: 8px; cursor: default; }
  .item:hover { background: var(--surface-hover); }
  .item:focus-visible { outline: 2px solid var(--accent); }
  .kind { width: 40px; height: 40px; border-radius: 6px; background: var(--surface); display: grid; place-items: center; color: var(--secondary); flex: none; }
  .item:hover .kind { color: var(--accent); }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .name { font-size: 14px; font-weight: 500; }
  .sub { font-size: 12.5px; color: var(--secondary); }
  .item.missing .name { color: var(--dim); text-decoration: line-through; }
  .when { font-size: 12.5px; white-space: nowrap; }
  .more { opacity: 0; }
  .item:hover .more, .more:focus-visible { opacity: 1; }
</style>
