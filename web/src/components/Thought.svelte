<script>
  // Modelin dusunce metni (F100): cevabin ustunde katlanir blok. Dusunme istenip model
  // dusunmediyse bunu da soyler; boylece dugmenin calistigi arayuzden gorulur.
  let { text = '', think = null, live = false } = $props();
  const words = $derived(text ? text.trim().split(/\s+/).length : 0);
</script>

{#if text}
  <details class="thought" open={live}>
    <summary>{live ? 'Düşünüyor…' : 'Düşündü'} <span>· {words} kelime</span></summary>
    <div class="body selectable">{text}</div>
  </details>
{:else if think === true && !live}
  <div class="thought none">Düşünme açıktı ama model düşünmeden cevapladı.</div>
{/if}

<style>
  .thought { font-size: 12.5px; color: var(--dim); border-left: 2px solid var(--outline); padding: 2px 0 2px 10px; }
  .thought summary { cursor: pointer; font-weight: 600; color: var(--secondary); list-style: none; user-select: none; }
  .thought summary::-webkit-details-marker { display: none; }
  .thought summary::before { content: '\25B8'; display: inline-block; width: 1em; transition: transform .15s; }
  .thought[open] summary::before { transform: rotate(90deg); }
  .thought summary span { font-weight: 400; color: var(--dim); }
  .thought .body { margin-top: 6px; white-space: pre-wrap; line-height: 1.55; max-height: 280px; overflow: auto; overflow-wrap: anywhere; }
  .thought.none { font-style: italic; }
</style>
