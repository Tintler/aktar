<script>
  // F239: okuyucunun sag panelinde "Simdiye kadar" ozeti ve "Kim kimdir" listesi. Yalnizca okunan yere (acik bolum,
  // ekranin alt kenari) kadarki kisim modele gider. Bitmis bolumlerin ozetleri saklanir; Guncelle yalnizca yeni
  // okunani ozetler. Metindeki (s.N) atfi kitabi N. bolume goturur.
  import Icon from '../lib/Icon.svelte';
  import { on } from '../lib/api.js';
  import { act } from '../lib/state.svelte.js';

  let { book, section = 0, fraction = 1, ongo } = $props();

  let state = $state(null);
  const recap = $derived(state?.recap ?? null);
  let tab = $state('story');

  $effect(() => {
    const bookId = book.id;
    state = null;
    let active = true;
    const unsubscribe = on('reader_recap', (value) => {
      if (value.book === bookId) state = value;
    });
    act('reader_recap_get', bookId).then((value) => {
      if (active && !state && value) state = value;
    });
    return () => {
      active = false;
      unsubscribe();
    };
  });

  // Ozet okunan yerin gerisinde mi (okuma ilerledi)?
  const behind = $derived(!!recap && (recap.until < section || (recap.until === section && recap.fraction + 0.02 < fraction)));

  function run() {
    return act('reader_recap_run', book.id, section, fraction);
  }

  function where(item) {
    return item.fraction >= 0.999 ? `${item.until + 1}. bölümün sonuna kadar` : `${item.until + 1}. bölüm, %${Math.round(item.fraction * 100)} kadar`;
  }

  // "(s.3)", "(s.3, s.4)" ve yalin s.3 -> tiklanir atif
  function parts(text) {
    const result = [];
    let last = 0;
    for (const match of text.matchAll(/\(?\bs\.(\d{1,4})\b\)?/g)) {
      if (match.index > last) result.push({ text: text.slice(last, match.index) });
      result.push({ cite: Number(match[1]) });
      last = match.index + match[0].length;
    }
    if (last < text.length) result.push({ text: text.slice(last) });
    return result;
  }
  const paragraphs = $derived((recap?.text ?? '').split(/\n\s*\n|\n/).map((p) => p.trim()).filter(Boolean));
</script>

<div class="recap">
  <div class="tabs">
    <button class:on={tab === 'story'} onclick={() => (tab = 'story')}>Şimdiye kadar</button>
    <button class:on={tab === 'people'} onclick={() => (tab = 'people')} disabled={!recap?.people?.length}>Kim kimdir{recap?.people?.length ? ` (${recap.people.length})` : ''}</button>
  </div>

  <div class="body">
    {#if state?.running}
      <div class="note"><Icon name="loader" size={13} spin />{state.note || 'Hazırlanıyor…'}</div>
      {#if state.total}<div class="bar"><span style:width={`${Math.round((100 * state.done) / state.total)}%`}></span></div>{/if}
    {/if}
    {#if state?.job_error}<div class="error">{state.job_error}</div>{/if}
    {#if !state?.running && state?.note}<div class="note">{state.note}</div>{/if}

    {#if recap}
      <div class="meta">{where(recap)}{#if behind} · okuduğunuz yerin gerisinde{/if}</div>
      {#if tab === 'story'}
        {#each paragraphs as paragraph}
          <p>{#each parts(paragraph) as part}{#if part.cite}<button class="cite" title={`${part.cite}. bölüme git`} onclick={() => ongo?.(part.cite - 1)}>s.{part.cite}</button>{:else}{part.text}{/if}{/each}</p>
        {/each}
      {:else}
        <ul class="people">
          {#each recap.people as person}
            <li>
              <div class="name">{person.name}{#if person.first}<button class="cite" title={`İlk göründüğü yer: ${person.first}. bölüm`} onclick={() => ongo?.(person.first - 1)}>s.{person.first}</button>{/if}</div>
              <div class="about">{person.about}</div>
            </li>
          {/each}
        </ul>
      {/if}
    {:else if !state?.running}
      <div class="empty">
        Okuduğunuz yere kadar ({section + 1}. bölüm, %{Math.round(fraction * 100)}) olanların özetini ve kişilerin listesini çıkarır.
        Sonrası modele gönderilmez. Bölüm özetleri saklanır; okumaya devam edince yalnızca yeni kısım özetlenir.
      </div>
    {/if}
  </div>

  <div class="actions">
    {#if state?.running}
      <button class="btn" onclick={() => act('reader_recap_cancel')}><Icon name="x" size={14} />Durdur</button>
    {:else}
      <button class="btn primary" onclick={run}><Icon name="refresh" size={14} />{recap ? 'Okuduğum yere kadar güncelle' : 'Özeti çıkar'}</button>
    {/if}
  </div>
</div>

<style>
  .recap { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
  .tabs { display: flex; gap: 6px; }
  .tabs button { font-size: 12.5px; padding: 5px 11px; border-radius: 999px; background: var(--surface); border: 1px solid var(--outline); color: var(--secondary); }
  .tabs button.on { border-color: var(--accent); color: var(--text); }
  .body { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 10px; padding-right: 4px; }
  .body p { margin: 0; font-size: 14px; line-height: 1.55; }
  .meta { font-size: 12px; color: var(--dim); }
  .note { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--dim); }
  .error { font-size: 12.5px; color: var(--danger); }
  .empty { font-size: 12.5px; color: var(--dim); font-style: italic; line-height: 1.5; }
  .bar { height: 4px; border-radius: 2px; background: var(--surface-active); overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); transition: width 0.3s; }
  .cite { font-size: 11.5px; padding: 0 5px; margin: 0 2px; border-radius: 6px; background: var(--surface); border: 1px solid var(--outline); color: var(--accent); }
  .cite:hover { border-color: var(--accent); }
  .people { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  .name { font-weight: 600; font-size: 13.5px; display: flex; align-items: center; gap: 4px; }
  .about { font-size: 13px; color: var(--secondary); line-height: 1.45; }
  .actions { display: flex; justify-content: flex-end; }
  .btn { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 7px 14px; border-radius: 999px; background: var(--surface); border: 1px solid var(--outline); }
  .btn.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
</style>
