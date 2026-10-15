<script>
  // Modelin dusunce metni (F100): cevabin ustunde katlanir blok. Dusunme istenip model
  // dusunmediyse bunu da soyler; boylece dugmenin calistigi arayuzden gorulur.
  // F101: uretim sirasinda (live) genisletilmediyse birkac satirlik alanda kayarak akar.
  let { text = '', think = null, live = false } = $props();
  const words = $derived(text ? text.trim().split(/\s+/).length : 0);
  let expanded = $state(false);
  let body = $state();
  let follow = true;

  // Yeni metin gelince sona kay; genisletilmis alanda kullanici yukari kaydirdiysa birakir.
  $effect(() => {
    text;
    if (!body || !(live || expanded)) return;
    if (!expanded || follow) queueMicrotask(() => body && (body.scrollTop = body.scrollHeight));
  });

  function scrolled() {
    if (expanded) follow = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
  }
</script>

{#if text}
  <div class="thought" class:live class:open={expanded}>
    <button type="button" class="head" aria-expanded={expanded} onclick={() => { expanded = !expanded; follow = true; }}>
      <span class="arrow">&#9656;</span>{#if live}<span class="shine">Düşünüyor…</span>{:else}Düşündü{/if} <span class="count">· {words} kelime</span>
    </button>
    {#if live || expanded}
      <div class="body selectable" class:compact={!expanded} bind:this={body} onscroll={scrolled}>{text}</div>
    {/if}
  </div>
{:else if think === true && !live}
  <div class="thought none">Düşünme açıktı ama model düşünmeden cevapladı.</div>
{/if}

<style>
  .thought { font-size: 12.5px; color: var(--dim); border-left: 2px solid var(--outline); padding: 2px 0 2px 10px; }
  .head { display: inline-flex; align-items: center; gap: 4px; font-size: inherit; font-weight: 600; color: var(--secondary); padding: 0; background: none; }
  .head:hover { color: var(--text); }
  .arrow { display: inline-block; width: 1em; transition: transform .15s; }
  .open .arrow { transform: rotate(90deg); }
  .count { font-weight: 400; color: var(--dim); }
  .body { margin-top: 6px; white-space: pre-wrap; line-height: 1.55; max-height: 280px; overflow: auto; overflow-wrap: anywhere; }
  /* Uretim sirasinda: ~3 satirlik pencere, ust kenari solarak; metin alttan akar. */
  .body.compact { max-height: calc(1.55em * 3); overflow: hidden;
    -webkit-mask-image: linear-gradient(to bottom, transparent, #000 45%); mask-image: linear-gradient(to bottom, transparent, #000 45%); }
  .shine { background: linear-gradient(90deg, var(--secondary) 30%, var(--text) 50%, var(--secondary) 70%) 0 0 / 200% 100%;
    -webkit-background-clip: text; background-clip: text; color: transparent; animation: shine 1.8s linear infinite; }
  @keyframes shine { to { background-position: -200% 0; } }
  .thought.none { font-style: italic; }
</style>
