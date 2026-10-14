<script>
  // Yan cubuktaki koleksiyon listesi (Deeverse'teki kitaplik listesi gibi): tikla ac, sag tik menu.
  import Icon from '../lib/Icon.svelte';
  import { app, act, setLibrary, go, toast } from '../lib/state.svelte.js';
  import { prompt, confirm } from '../lib/confirm.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';

  const lib = $derived(app.library);

  async function open(slug) {
    app.libraryView.home = false;
    go('library');
    if (slug !== lib.slug) setLibrary(await act('library_open', slug));
  }

  async function create() {
    const title = await prompt({ title: 'Yeni koleksiyon', message: 'Koleksiyon adı:', ok: 'Oluştur' });
    if (title?.trim()) {
      setLibrary(await act('new_collection', title.trim()));
      app.libraryView.home = false;
      go('library');
    }
  }

  async function rename(c) {
    const title = await prompt({ title: 'Yeniden adlandır', message: 'Koleksiyon adı:', value: c.title, ok: 'Kaydet' });
    if (title?.trim() && title.trim() !== c.title) setLibrary(await act('rename_collection', c.slug, title.trim()));
  }

  async function remove(c) {
    const ok = await confirm({
      title: 'Koleksiyonu sil', message: `"${c.title}" koleksiyonu silinsin mi?\nYalnızca koleksiyon kaydı silinir; dosyalarınız diskte kalır.`,
      ok: 'Sil', danger: true,
    });
    if (ok) setLibrary(await act('delete_collection', c.slug));
  }

  async function exportCollection() {
    const result = await act('export_collection');
    if (result?.path) toast('Koleksiyon dışa aktarıldı: ' + result.path, 'ok');
  }

  function menu(event, c) {
    const current = c.slug === lib.slug;
    const hasText = current && lib.rows.some((r) => r.status === 'ready' || r.status === 'transcript');
    openMenu(event, [
      { label: 'Yeniden adlandır', icon: 'pencil', action: () => rename(c) },
      { label: 'Yeniden tara', icon: 'refresh', action: async () => { await open(c.slug); setLibrary(await act('library_rescan')); } },
      { label: 'Koleksiyonu dışa aktar (Markdown)…', icon: 'download', disabled: !hasText, action: exportCollection },
      'sep',
      { label: 'Koleksiyonu sil', icon: 'trash', danger: true, action: () => remove(c) },
    ]);
  }
</script>

<div class="head">
  <Icon name="library" size={20} /><b>Koleksiyonlar</b>
  <button class="icon-btn sm" title="Yeni koleksiyon" onclick={create}><Icon name="plus" size={18} /></button>
</div>
<div class="list">
  {#each lib.collections as c (c.slug)}
    <button class="item" class:on={c.slug === lib.slug && app.view === 'library' && !app.libraryView.home} onclick={() => open(c.slug)}
      oncontextmenu={(e) => menu(e, c)}>
      <span class="cover"><Icon name="folder" size={20} /></span>
      <span class="text">
        <span class="title ellipsis">{c.title}</span>
        <span class="sub ellipsis">Koleksiyon · {c.folders} klasör{c.files ? ` · ${c.files} dosya` : ''}</span>
      </span>
    </button>
  {:else}
    <p class="hint">Henüz koleksiyon yok. Bir klasörü pencereye bırakın ya da + ile oluşturun.</p>
  {/each}
</div>

<style>
  .head { display: flex; align-items: center; gap: 12px; padding: 4px 8px 10px 14px; color: var(--secondary); }
  .head b { color: var(--text); font-size: 16px; flex: 1; }
  .list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 6px 8px; border-radius: 6px; text-align: left; width: 100%; }
  .item:hover { background: var(--surface-hover); }
  .item.on { background: var(--surface-active); }
  .cover { width: 48px; height: 48px; border-radius: 4px; background: var(--surface); display: grid; place-items: center; color: var(--secondary); flex: none; }
  .item.on .cover { color: var(--accent); }
  .text { display: flex; flex-direction: column; min-width: 0; }
  .title { font-size: 14px; font-weight: 500; }
  .item.on .title { color: var(--accent); }
  .sub { font-size: 12.5px; color: var(--secondary); }
  .hint { color: var(--dim); font-size: 12px; padding: 4px 14px; }
</style>
