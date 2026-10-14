<script>
  // Belge goruntuleyici (eski doc_view): PDF sayfalari goruntu olarak (yalnizca gorunenler yuklenir),
  // diger belgeler sayfa basliklariyla duz metin, gorseller sigdirilarak. Sayfa gezinme ve atiflar.
  import Icon from '../lib/Icon.svelte';
  import { app, act } from '../lib/state.svelte.js';

  const d = $derived(app.document);
  let scroller = $state();
  let current = $state(1);
  let visible = $state(new Set([1, 2]));
  let zoom = $state(1);

  function pageNode(n) {
    return scroller?.querySelector(`[data-page="${n}"]`);
  }

  function goTo(n) {
    if (!d) return;
    n = Math.max(1, Math.min(Number(n) || 1, d.pages));
    const node = pageNode(n);
    if (node) scroller.scrollTo({ top: node.offsetTop - 12 });
    current = n;
  }

  // Atif ya da arama sonucu: istenen sayfaya git (sayfalar cizildikten sonra).
  $effect(() => {
    const seek = app.docSeek;
    if (!seek || !d || !scroller) return;
    app.docSeek = null;
    requestAnimationFrame(() => goTo(seek.page));
  });

  // Gorunen sayfalar: kaydirdikca yalnizca ekrandakiler (ve komsulari) yuklenir.
  function scrolled() {
    if (!scroller || !d) return;
    const top = scroller.scrollTop, bottom = top + scroller.clientHeight;
    const shown = new Set();
    let first = null;
    for (const node of scroller.querySelectorAll('[data-page]')) {
      const start = node.offsetTop, end = start + node.offsetHeight;
      if (end >= top - 400 && start <= bottom + 400) shown.add(Number(node.dataset.page));
      if (first === null && end > top + 40) first = Number(node.dataset.page);
    }
    visible = new Set([...visible, ...shown]);
    current = first ?? current;
  }
  $effect(() => {
    d; zoom;
    queueMicrotask(scrolled);
  });

  let pageInput = $state('');
  function jump(event) {
    event.preventDefault();
    goTo(pageInput);
    pageInput = '';
  }
</script>

<section class="page">
  {#if d}
    <div class="page-head">
      <h1 class="ellipsis title" title={d.path}>{d.name}</h1>
      {#if d.kind !== 'image'}
        <div class="nav">
          <button class="icon-btn filled sm" title="Önceki sayfa" disabled={current <= 1} onclick={() => goTo(current - 1)}><Icon name="back" size={16} /></button>
          <form onsubmit={jump}><input class="field pageno mono" bind:value={pageInput} placeholder={String(current)} title="Sayfaya git" /></form>
          <span class="mono dim">/ {d.pages}</span>
          <button class="icon-btn filled sm" title="Sonraki sayfa" disabled={current >= d.pages} onclick={() => goTo(current + 1)}><Icon name="forward" size={16} /></button>
        </div>
      {/if}
      {#if d.kind === 'pdf'}
        <div class="nav">
          <button class="icon-btn sm" title="Küçült" disabled={zoom <= 0.5} onclick={() => (zoom = Math.max(0.5, zoom - 0.15))}><Icon name="minus" size={16} /></button>
          <span class="mono dim zoom">%{Math.round(zoom * 100)}</span>
          <button class="icon-btn sm" title="Büyüt" disabled={zoom >= 2} onclick={() => (zoom = Math.min(2, zoom + 0.15))}><Icon name="plus" size={16} /></button>
        </div>
      {/if}
      <button class="btn sm" onclick={() => act('open_external', d.path)}><Icon name="external" size={14} />Varsayılan uygulamada aç</button>
    </div>
    <div class="viewer" bind:this={scroller} onscroll={scrolled}>
      {#if d.kind === 'pdf'}
        <div class="pages" style:width="{zoom * 100}%">
          {#each d.sizes as ratio, i}
            <div class="sheet" data-page={i + 1} style:aspect-ratio="1 / {ratio}">
              {#if visible.has(i + 1)}<img src="{d.page_url}/{i + 1}?w={Math.round(1600 * zoom)}" alt="Sayfa {i + 1}" draggable="false" />{/if}
              <span class="num">{i + 1}</span>
            </div>
          {/each}
        </div>
      {:else if d.kind === 'image'}
        <div class="image" data-page="1"><img src={d.image} alt={d.name} /></div>
      {:else}
        <div class="text selectable">
          {#each d.texts as text, i}
            <div class="tpage" data-page={i + 1}><div class="thead">— s. {i + 1} —</div><div class="tbody">{text}</div></div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .title { font-size: 24px !important; }
  .nav { display: flex; align-items: center; gap: 6px; }
  .pageno { width: 56px; height: 30px; text-align: center; padding: 0 6px; }
  .zoom { min-width: 44px; text-align: center; font-size: 12px; }
  .viewer { flex: 1; min-height: 0; overflow: auto; margin: 0 32px 20px; border-radius: 12px; background: var(--panel); border: 1px solid var(--outline); }
  .pages { margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; max-width: none; min-width: 300px; }
  .sheet { position: relative; width: 100%; background: #fff; border-radius: 4px; box-shadow: 0 2px 10px var(--shadow); overflow: hidden; }
  .sheet img { width: 100%; height: 100%; display: block; user-select: none; }
  .num { position: absolute; right: 8px; bottom: 6px; font-size: 11px; color: #555; background: rgba(255, 255, 255, .85); padding: 1px 6px; border-radius: 999px; }
  .image { padding: 16px; display: grid; place-items: center; }
  .image img { max-width: 100%; border-radius: 6px; }
  .text { padding: 20px 28px; max-width: 900px; margin: 0 auto; }
  .tpage + .tpage { margin-top: 28px; }
  .thead { color: var(--dim); font-weight: 700; font-size: 12px; margin-bottom: 10px; }
  .tbody { white-space: pre-wrap; line-height: 1.65; font-size: 14px; overflow-wrap: anywhere; }
</style>
