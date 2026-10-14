<script>
  // Sohbet kayitlari: kullanici balonu, atifli model cevabi, notlar. Koleksiyon, belge ve
  // video sohbeti ortak kullanir. oncite({path, start, document}) atfa tiklaninca.
  import { inlineHtml } from '../lib/markdown.js';

  let { entries = [], oncite, single = false } = $props();
  const label = (item) => (single ? item.label.split(' ').slice(1).join(' ') || item.label : item.label);
</script>

{#each entries as entry}
  {#if entry.kind === 'user'}
    <div class="user selectable">{entry.text}</div>
  {:else if entry.kind === 'assistant'}
    <div class="answer selectable">
      {#each entry.parts as part}
        {#if part.type === 'cite'}
          {#each part.items as item}
            <button class="cite" title={item.title} onclick={() => oncite?.(item)}>{label(item)}</button>{' '}
          {/each}
        {:else}{@html inlineHtml(part.text)}{/if}
      {/each}
    </div>
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
    <div class="note pending"><span class="dots"><i></i><i></i><i></i></span>{entry.text}</div>
  {:else}
    <div class="note">{entry.text}</div>
  {/if}
{/each}

<style>
  .user { align-self: flex-end; max-width: 85%; background: var(--surface-active); padding: 9px 14px; border-radius: 16px 16px 4px 16px; font-size: 13.5px; white-space: pre-wrap; }
  .answer { font-size: 13.5px; line-height: 1.6; color: var(--text); }
  .cite { display: inline-block; padding: 0 7px; margin: 0 1px; border-radius: 999px; font-size: 11.5px; font-weight: 700; line-height: 19px;
    color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); vertical-align: 1px; white-space: nowrap; }
  button.cite:hover { background: var(--accent); color: var(--on-accent); }
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
