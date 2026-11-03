<script>
  // F242: temizlik (bridge_cleanup.py). Kaynagi artik olmayan kayitlar listelenir; hicbir sey kendiliginden silinmez,
  // yalnizca isaretlenenler onaydan sonra silinir.
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast, refreshEmotionBooks, refreshCastBooks } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';

  let scan = $state(null);
  let loading = $state(false);
  let picked = $state({});   // id -> true

  async function load() {
    loading = true;
    const result = await act('cleanup_scan');
    loading = false;
    if (result) { scan = result; picked = {}; }
  }

  const GROUPS = [
    { key: 'books', title: 'Kitaplıkta olmayan kitapların kayıtları',
      hint: 'Kitaplıktan kaldırılmış kitapların hazırlanmış sesleri, duygu etiketleri, karakter sesleri, özetleri ve görselleri. Aynı dosya yeniden eklenirse geri gelirdi.' },
    { key: 'missing', title: 'Dosyası bulunamayan kitaplar',
      hint: 'Kitaplıkta duran ama dosyası yerinde olmayan kitaplar. Silinince kitaplıktan da kaldırılır. Harici diskteyse ya da taşındıysa önce Yedekleme → "Bulunamayan dosyaları bul"u deneyin.' },
    { key: 'caches', title: 'Kaynağı bulunamayan transkript ve arama önbellekleri',
      hint: 'Silinmiş ya da taşınmış video ve belgelerin transkriptleri ve arama indeksleri. Harici disk takılı değilse de burada görünür.' },
    { key: 'ebooks', title: 'Kullanılmayan dönüştürülmüş e-kitaplar',
      hint: 'MOBI/AZW3/FB2\'den dönüştürülmüş, artık hiçbir kitabın kullanmadığı EPUB kopyaları.' },
  ];

  const size = (bytes) => (bytes >= 1e9 ? `${(bytes / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} GB`
    : `${Math.max(0.1, (bytes || 0) / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} MB`);
  const items = $derived(scan ? GROUPS.flatMap((g) => scan[g.key] ?? []) : []);
  const chosen = $derived(items.filter((item) => picked[item.id]));
  const chosenBytes = $derived(chosen.reduce((sum, item) => sum + (item.bytes || 0), 0));

  function label(group, item) {
    if (group === 'books') return item.title || `Bilinmeyen kitap (${item.book})`;
    return item.title || item.path || item.id;
  }
  function detail(group, item) {
    if (group === 'books' || group === 'missing') {
      const parts = (item.parts ?? []).map((p) => p.label).join(', ');
      return [group === 'missing' ? item.path : '', parts || (group === 'missing' ? 'kayıt yok' : '')].filter(Boolean).join(' · ');
    }
    if (group === 'caches') return `${item.path} · ${item.files} dosya`;
    return '';
  }

  function toggleGroup(key, on) {
    const next = { ...picked };
    for (const item of scan?.[key] ?? []) next[item.id] = on;
    picked = next;
  }

  async function remove() {
    const paid = chosen.some((item) => (item.parts ?? []).some((p) => p.kind === 'audio'));
    const yes = await confirm({
      title: 'Seçilenleri sil',
      message: `${chosen.length} kayıt (${size(chosenBytes)}) geri alınamaz biçimde silinsin mi?` +
        (paid ? ' Hazırlanmış sesler arasında ücretli bulut sesleri de olabilir.' : ''),
      list: chosen.slice(0, 30).map((item) => label(GROUPS.find((g) => (scan[g.key] ?? []).includes(item)).key, item)),
      ok: 'Sil', cancel: 'Vazgeç', danger: true,
    });
    if (!yes) return;
    const result = await act('cleanup_remove', chosen.map((item) => item.id));
    if (!result) return;
    if (result.scan && !result.scan.error) scan = result.scan;
    if (Array.isArray(result.shelf)) app.shelf = result.shelf;
    picked = {};
    refreshEmotionBooks();
    refreshCastBooks();
    toast(`${result.removed} kayıt silindi (${result.files} dosya, ${size(result.bytes)}).`, 'ok');
  }
</script>

<section>
  <h2>Temizlik</h2>
  <div class="fr">
    <div class="l">Artık kullanılmayan kayıtları bul<small>Silinmiş ya da kitaplıktan kaldırılmış kitapların ve videoların ardında kalan
      kayıtlar listelenir. Hiçbir şey kendiliğinden silinmez; yalnızca işaretlediklerinizi silebilirsiniz.</small></div>
    <button class="btn sm" disabled={loading} onclick={load}>
      <Icon name={loading ? 'loader' : 'search'} size={14} spin={loading} />{scan ? 'Yeniden tara' : 'Tara'}</button>
  </div>
  {#if scan}
    {#if !items.length}
      <div class="empty">Temizlenecek bir şey bulunamadı.</div>
    {:else}
      {#each GROUPS as group}
        {@const list = scan[group.key] ?? []}
        {#if list.length}
          {@const all = list.every((item) => picked[item.id])}
          <div class="group">
            <label class="head">
              <input type="checkbox" checked={all} onchange={(e) => toggleGroup(group.key, e.currentTarget.checked)} />
              <b>{group.title}</b><span class="dim">{list.length} · {size(list.reduce((s, i) => s + (i.bytes || 0), 0))}</span>
            </label>
            <small class="hint">{group.hint}</small>
            <div class="items">
              {#each list as item (item.id)}
                <label class="item">
                  <input type="checkbox" checked={Boolean(picked[item.id])} onchange={(e) => (picked = { ...picked, [item.id]: e.currentTarget.checked })} />
                  <span class="txt"><span class="name">{label(group.key, item)}</span>{#if detail(group.key, item)}<small>{detail(group.key, item)}</small>{/if}</span>
                  <span class="dim">{size(item.bytes)}</span>
                </label>
              {/each}
            </div>
          </div>
        {/if}
      {/each}
      <div class="actions">
        <span class="dim">{chosen.length ? `${chosen.length} kayıt seçildi · ${size(chosenBytes)}` : 'Silmek istediklerinizi işaretleyin.'}</span>
        <button class="btn sm primary danger" disabled={!chosen.length} onclick={remove}><Icon name="trash" size={14} />Seçilenleri sil</button>
      </div>
    {/if}
  {/if}
</section>

<style>
  h2 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; margin-bottom: 6px; }
  .fr { display: flex; align-items: center; gap: 20px; padding: 12px 0; }
  .l { flex: 1; min-width: 0; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  .empty { color: var(--dim); font-size: 13px; padding: 4px 0 12px; }
  .group { border-top: 1px solid var(--outline); padding: 12px 0; }
  .head { display: flex; align-items: center; gap: 8px; font-size: 13.5px; cursor: pointer; }
  .head .dim { margin-left: auto; }
  .hint { display: block; color: var(--dim); font-size: 12px; line-height: 1.5; margin: 4px 0 8px 24px; }
  .items { display: flex; flex-direction: column; gap: 2px; max-height: 260px; overflow: auto; margin-left: 16px; }
  .item { display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  .item:hover { background: var(--surface-hover); }
  .txt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .txt small { color: var(--dim); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dim { color: var(--dim); font-size: 12px; flex: none; }
  .actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid var(--outline); padding-top: 12px; }
</style>
