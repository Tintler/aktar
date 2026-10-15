<script>
  // Sohbet kayitlari: kullanici balonu, atifli model cevabi, notlar. Koleksiyon, belge ve
  // video sohbeti ortak kullanir. oncite({path, start, document}) atfa tiklaninca.
  // F98: cevap blok Markdown olarak cizilir (tablo, baslik, liste); atiflar yer tutucuyla
  // Markdown'u bolmeden dugmeye donusur (genel sohbetteki answerHtml ile ayni yol).
  // F103: ```chart bloklari grafik olarak cizilir (use:charts).
  import { richHtml, escapeHtml } from '../lib/markdown.js';
  import { charts } from '../lib/chart.js';
  import Thought from './Thought.svelte';
  import Icon from '../lib/Icon.svelte';

  let { entries = [], oncite, single = false } = $props();
  const label = (item) => (single ? item.label.split(' ').slice(1).join(' ') || item.label : item.label);

  let cites = [];
  function answerHtml(entry) {
    const tokens = [];
    let source = '';
    for (const part of entry.parts) {
      if (part.type === 'cite') {
        source += `\u0001${tokens.length}\u0001`;
        tokens.push(part.items.map((item) => {
          const key = cites.push(item) - 1;
          return `<button class="cite" data-cite="${key}" title="${escapeHtml(item.title)}">${escapeHtml(label(item))}</button>`;
        }).join(' '));
      } else source += part.text;
    }
    return richHtml(source, tokens);
  }
  const rendered = $derived.by(() => {
    cites = [];
    return entries.map((entry) => (entry.kind === 'assistant' ? answerHtml(entry) : null));
  });

  function clickAnswer(event) {
    const button = event.target.closest('button.cite[data-cite]');
    const item = button && cites[Number(button.dataset.cite)];
    if (item) oncite?.(item);
  }
</script>

{#each entries as entry, index}
  {#if entry.kind === 'user'}
    <div class="user selectable">{entry.text}</div>
  {:else if entry.kind === 'assistant'}
    <Thought text={entry.thinking} think={entry.think} />
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="answer md selectable" onclick={clickAnswer} use:charts>{@html rendered[index]}</div>
    {#if entry.template}<div class="tpl-tag" title="Bu cevap bu sohbet şablonuyla üretildi"><Icon name="scroll" size={12} />{entry.template}</div>{/if}
    {#if entry.sources?.length && !single}
      <div class="sources">
        <span>Kaynaklar</span>
        {#each entry.sources as source}
          <button class="source" title={source.title} onclick={() => oncite?.(source)}>
            <span class="cite">{source.label}</span><span class="ellipsis">{source.title}</span><span class="dim">{source.count}</span>
          </button>
        {/each}
      </div>
    {/if}
  {:else if entry.kind === 'error'}
    <div class="error selectable">{entry.text}</div>
  {:else if entry.kind === 'pending'}
    {#if entry.thinking}
      <!-- F102: uretim sirasinda dusunce kucuk alanda canli akar -->
      <Thought text={entry.thinking} live />
    {:else}
      <div class="note pending"><span class="dots"><i></i><i></i><i></i></span>{entry.text}</div>
    {/if}
  {:else}
    <div class="note">{entry.text}</div>
  {/if}
{/each}

<style>
  .user { align-self: flex-end; max-width: 85%; background: var(--surface-active); padding: 9px 14px; border-radius: 16px 16px 4px 16px; font-size: 13.5px; white-space: pre-wrap; }
  .answer { font-size: 13.5px; line-height: 1.6; color: var(--text); overflow-wrap: anywhere; min-width: 0; }
  .md :global(p) { margin: 0 0 .7em; }
  .md :global(p:last-child), .md :global(ul:last-child), .md :global(ol:last-child) { margin-bottom: 0; }
  .md :global(h3), .md :global(h4), .md :global(h5), .md :global(h6) { margin: 1em 0 .4em; font-size: 1.05em; font-weight: 700; line-height: 1.35; }
  .md :global(:first-child) { margin-top: 0; }
  .md :global(ul), .md :global(ol) { margin: 0 0 .7em; padding-left: 1.4em; }
  .md :global(li) { margin: .15em 0; }
  .md :global(li::marker) { color: var(--secondary); }
  .md :global(code) { font: .88em/1.5 var(--mono); padding: .1em .35em; border-radius: 5px; background: var(--surface); }
  .md :global(pre) { margin: .3em 0 .8em; padding: 10px 12px; border-radius: 10px; background: var(--surface); overflow: auto; }
  .md :global(pre code) { padding: 0; background: none; font-size: 12px; white-space: pre; }
  .md :global(blockquote) { margin: 0 0 .7em; padding: 2px 0 2px 12px; border-left: 3px solid var(--outline); color: var(--secondary); }
  .md :global(hr) { border: 0; border-top: 1px solid var(--outline); margin: 1em 0; }
  .md :global(.table-wrap) { overflow-x: auto; margin: 0 0 .8em; }
  .md :global(table) { border-collapse: collapse; font-size: .95em; overflow-wrap: normal; }
  .md :global(th), .md :global(td) { border: 1px solid var(--outline); padding: 5px 9px; text-align: left; vertical-align: top; }
  .md :global(th) { background: var(--surface); font-weight: 600; }
  .md :global(.link) { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .md :global(.cite.raw) { opacity: .7; }
  .cite, .md :global(.cite) { display: inline-block; padding: 0 7px; margin: 0 1px; border-radius: 999px; font-size: 11.5px; font-weight: 700; line-height: 19px;
    color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); vertical-align: 1px; white-space: nowrap; }
  .md :global(button.cite:hover) { background: var(--accent); color: var(--on-accent); }
  .sources { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; color: var(--dim); margin-top: -4px; }
  .sources > span { font-weight: 600; text-transform: uppercase; letter-spacing: .05em; font-size: 10.5px; }
  .source { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 3px 8px 3px 3px; border-radius: 999px; background: var(--surface); font-size: 12px; color: var(--secondary); }
  .source:hover { background: var(--surface-hover); color: var(--text); }
  .source .ellipsis { max-width: 180px; }
  .error { color: var(--danger); font-size: 13px; }
  .note { color: var(--dim); font-size: 12.5px; font-style: italic; }
  .pending { display: flex; align-items: center; gap: 8px; font-style: normal; }
  .dots { display: inline-flex; gap: 3px; }
  .dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); animation: blink 1.2s infinite; }
  .dots i:nth-child(2) { animation-delay: .2s; }
  .dots i:nth-child(3) { animation-delay: .4s; }
  @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
</style>
