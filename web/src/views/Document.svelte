<script>
  // Belge goruntuleyici (eski doc_view): PDF sayfalari goruntu olarak (yalnizca gorunenler yuklenir),
  // diger belgeler sayfa basliklariyla duz metin, gorseller sigdirilarak. Sayfa gezinme ve atiflar.
  import Icon from '../lib/Icon.svelte';
  import { app, act } from '../lib/state.svelte.js';
  import NotesPanel from '../components/NotesPanel.svelte';
  import { notes, loadNotes, startNote, addNote, NOTE_COLORS } from '../lib/notes.svelte.js';

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

  // --- not ve vurgu (F113) ----------------------------------------------------
  $effect(() => {
    if (d?.path) loadNotes(d.path);
  });
  const mine = $derived(notes.path === d?.path ? notes.items : []);
  const pageNotes = (n) => mine.filter((note) => Math.round(note.at) === n);
  const canHighlight = $derived(d && d.kind !== 'pdf' && d.kind !== 'image');

  // Vurgulanan alintilar sayfa metninde: bosluk farklari (satir sonu vb.) onemsenmez.
  const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  function segments(text, n) {
    const found = [];
    for (const note of pageNotes(n)) {
      if (!note.quote) continue;
      const words = note.quote.split(/\s+/).filter(Boolean).map(escape);
      if (!words.length) continue;
      const match = new RegExp(words.join('\\s+')).exec(text);
      if (match) found.push({ start: match.index, end: match.index + match[0].length, note });
    }
    found.sort((a, b) => a.start - b.start);
    const parts = [];
    let position = 0;
    for (const item of found) {
      if (item.start < position) continue;   // ust uste binen vurgu: ilki kalir
      if (item.start > position) parts.push({ text: text.slice(position, item.start) });
      parts.push({ text: text.slice(item.start, item.end), note: item.note });
      position = item.end;
    }
    if (position < text.length) parts.push({ text: text.slice(position) });
    return parts;
  }

  // Metin secilince kucuk arac cubugu: Vurgula / Not ekle.
  let picked = $state(null);   // {page, quote, x, y}
  function selected() {
    const selection = window.getSelection();
    const textValue = selection?.toString().replace(/\s+/g, ' ').trim();
    if (!selection || selection.isCollapsed || !textValue || !scroller) { picked = null; return; }
    const start = selection.anchorNode?.parentElement?.closest('[data-page]');
    const end = selection.focusNode?.parentElement?.closest('[data-page]');
    if (!start || start !== end || !scroller.contains(start)) { picked = null; return; }
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const box = scroller.getBoundingClientRect();
    picked = { page: Number(start.dataset.page), quote: textValue.slice(0, 1000),
      x: rect.left + rect.width / 2 - box.left, y: rect.top - box.top + scroller.scrollTop };
  }
  async function highlight() {
    if (!picked) return;
    await addNote(d.path, picked.page, '', picked.quote);
    window.getSelection()?.removeAllRanges();
    picked = null;
  }
  function noteSelection() {
    if (!picked) return;
    startNote(picked.page, picked.quote);
    window.getSelection()?.removeAllRanges();
    picked = null;
  }

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
      <button class="btn sm" title={canHighlight ? 'Bu sayfaya not ekle (metin seçerek vurgulayabilirsiniz)' : 'Bu sayfaya not ekle'}
        onclick={() => startNote(current)}><Icon name="squarePen" size={14} />Not ekle</button>
      <button class="btn sm" class:on={notes.open} onclick={() => (notes.open = !notes.open)}><Icon name="list" size={14} />Notlar{mine.length ? ` (${mine.length})` : ''}</button>
      <button class="btn sm" onclick={() => act('open_external', d.path)}><Icon name="external" size={14} />Varsayılan uygulamada aç</button>
    </div>
    <div class="doc-body">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="viewer" bind:this={scroller} onscroll={() => { scrolled(); picked = null; }} onmouseup={() => canHighlight && setTimeout(selected)}>
      {#if d.kind === 'pdf'}
        <div class="pages" style:width="{zoom * 100}%">
          {#each d.sizes as ratio, i}
            <div class="sheet" data-page={i + 1} style:aspect-ratio="1 / {ratio}">
              {#if visible.has(i + 1)}<img src="{d.page_url}/{i + 1}?w={Math.round(1600 * zoom)}" alt="Sayfa {i + 1}" draggable="false" />{/if}
              <span class="num">{i + 1}</span>
              {#if pageNotes(i + 1).length}
                <button class="flag" title={pageNotes(i + 1).map((n) => n.text || n.quote).join('\n')} onclick={() => (notes.open = true)}
                  style:background={NOTE_COLORS[pageNotes(i + 1)[0].color]}><Icon name="squarePen" size={12} />{pageNotes(i + 1).length}</button>
              {/if}
            </div>
          {/each}
        </div>
      {:else if d.kind === 'image'}
        <div class="image" data-page="1"><img src={d.image} alt={d.name} /></div>
      {:else}
        <div class="text selectable">
          {#each d.texts as text, i}
            <div class="tpage" data-page={i + 1}><div class="thead">— s. {i + 1} —{#if pageNotes(i + 1).length}<span class="tnotes"> · {pageNotes(i + 1).length} not</span>{/if}</div><div class="tbody">{#each segments(text, i + 1) as part}{#if part.note}<mark style:--mark={NOTE_COLORS[part.note.color]} title={part.note.text || 'Vurgu'}>{part.text}</mark>{:else}{part.text}{/if}{/each}</div></div>
          {/each}
          {#if picked}
            <div class="picker" style:left="{picked.x}px" style:top="{picked.y}px">
              <button class="btn sm" onmousedown={(e) => e.preventDefault()} onclick={highlight}>Vurgula</button>
              <button class="btn sm" onmousedown={(e) => e.preventDefault()} onclick={noteSelection}><Icon name="squarePen" size={14} />Not ekle</button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
    {#if notes.open && notes.path === d.path}
      <div class="side"><NotesPanel path={d.path} doc={d.kind} current={current} onjump={(at) => goTo(at)} /></div>
    {/if}
    </div>
  {/if}
</section>

<style>
  .title { font-size: 24px !important; }
  .nav { display: flex; align-items: center; gap: 6px; }
  .pageno { width: 56px; height: 30px; text-align: center; padding: 0 6px; }
  .zoom { min-width: 44px; text-align: center; font-size: 12px; }
  .doc-body { flex: 1; min-height: 0; display: flex; gap: 12px; margin: 0 32px 20px; }
  .viewer { position: relative; flex: 1; min-width: 0; min-height: 0; overflow: auto; border-radius: 12px; background: var(--panel); border: 1px solid var(--outline); }
  .side { width: clamp(220px, 32%, 320px); flex: none; display: flex; min-height: 0; }
  .side > :global(.notes) { flex: 1; }
  .btn.on { color: var(--accent); }
  .flag { position: absolute; right: 8px; top: 8px; display: flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 700; color: #222; padding: 2px 8px; border-radius: 999px; box-shadow: 0 1px 4px rgba(0, 0, 0, .3); }
  .tnotes { color: var(--accent); }
  mark { background: color-mix(in srgb, var(--mark) 45%, transparent); color: inherit; border-radius: 2px; padding: 0 1px; }
  .picker { position: absolute; transform: translate(-50%, calc(-100% - 8px)); display: flex; gap: 4px; padding: 4px; border-radius: 10px; background: var(--overlay); border: 1px solid var(--outline); box-shadow: 0 4px 14px var(--shadow); z-index: 5; }
  .picker .btn { white-space: nowrap; }
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
