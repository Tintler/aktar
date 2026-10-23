<script>
  // F189: tam ekran sesli okuma -- yalnizca o anda okunan parca (Drama 3 TR'de cumle grubu) ekranda; parca
  // degisince eskisi yukari kayip kaybolur, yenisi asagidan gelir. Grup icinde okunan cumle parlak, digerleri soluk.
  // Fare 2,5 sn durunca ust satir ve dugmeler gizlenir.
  import { onDestroy, onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut, cubicInOut } from 'svelte/easing';
  import Icon from '../lib/Icon.svelte';
  import { call } from '../lib/api.js';
  import { player, step } from '../lib/player.svelte.js';

  let { sentences, start = 0, title, subtitle, paper, font, ontoggle, onclose } = $props();

  // Okuma yokken (ya da bolum gecisinde) ekrandan okunacak cumle gosterilir.
  const range = $derived(player.active && player.from >= 0 ? [player.from, player.to] : [start, start]);
  const parts = $derived(sentences.slice(range[0], range[1] + 1).map((text, i) => ({ text, i: range[0] + i })));
  const length = $derived(parts.reduce((n, p) => n + p.text.length, 0));
  // Uzun grup ekrana sigsin: karakter sayisi arttikca yazi kuculur.
  const size = $derived(length > 420 ? 24 : length > 260 ? 28 : length > 140 ? 32 : 38);
  const progress = $derived(sentences.length ? ((range[1] + 1) / sentences.length) * 100 : 0);

  let idle = $state(false);
  let idleTimer;
  function poke() {
    idle = false;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => (idle = true), 2500);
  }

  onMount(() => {
    call('window_fullscreen', true);
    poke();
  });
  onDestroy(() => {
    clearTimeout(idleTimer);
    call('window_fullscreen', false);
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="focus" class:idle onmousemove={poke} onpointerdown={poke}
  style:--paper={paper ? paper.bg : 'var(--panel)'} style:--ink={paper ? paper.ink : 'var(--text)'} style:font-family={font}>
  <div class="top">
    <div class="ttl"><b>{title}</b><small>{subtitle}</small></div>
    <span class="count">{#if player.waiting}hazırlanıyor… · {/if}Cümle {range[0] + 1} / {sentences.length}</span>
    <button class="icon-btn" title="Tam ekrandan çık (Esc)" onclick={onclose}><Icon name="shrink" /></button>
  </div>

  <div class="stage">
    {#key `${range[0]}:${sentences[range[0]]}`}
      <p class="chunk" style:font-size="{size}px"
        in:fly={{ y: 60, duration: 650, delay: 120, easing: cubicOut }} out:fly={{ y: -60, duration: 550, easing: cubicInOut }}>
        {#each parts as part (part.i)}<span class="s" class:on={parts.length === 1 || part.i === player.index}>{part.text}{' '}</span>{/each}
      </p>
    {/key}
  </div>

  <div class="controls">
    <button class="icon-btn" title="Önceki cümle" disabled={!player.active} onclick={() => step(-1)}><Icon name="prev" /></button>
    <button class="play" title={player.playing ? 'Duraklat (Boşluk)' : 'Sesli oku'} onclick={ontoggle}>
      <Icon name={player.playing ? 'pause' : 'play'} size={20} /></button>
    <button class="icon-btn" title="Sonraki cümle" disabled={!player.active} onclick={() => step(1)}><Icon name="next" /></button>
  </div>
  <div class="track"><i style:width="{progress}%"></i></div>
</div>

<style>
  .focus { position: fixed; inset: 0; z-index: 45; background: var(--paper); color: var(--ink); display: flex; flex-direction: column; }
  .focus.idle { cursor: none; }
  .top, .controls { transition: opacity .4s; }
  .focus.idle .top, .focus.idle .controls { opacity: 0; pointer-events: none; }
  .top { display: flex; align-items: center; gap: 14px; padding: 14px 20px; font-family: var(--sans); }
  .ttl { flex: 1; min-width: 0; }
  .ttl b, .ttl small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: .7; font-size: 13px; }
  .ttl small { opacity: .5; font-size: 12px; }
  .count { font-size: 12px; opacity: .55; white-space: nowrap; }
  .icon-btn { color: var(--ink); }
  .stage { flex: 1; min-height: 0; display: grid; place-items: center; padding: 0 8vw; overflow: hidden; }
  /* Giden ve gelen parca ayni hucrede ust uste biner, kayma birbirinin icinden gecer. */
  .chunk { grid-area: 1 / 1; max-width: 1100px; margin: 0; text-align: center; line-height: 1.55; overflow-wrap: break-word; }
  .s { color: color-mix(in srgb, var(--ink) 45%, transparent); transition: color .5s; }
  .s.on { color: var(--ink); }
  .controls { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 0 0 28px; }
  .play { width: 48px; height: 48px; border-radius: 50%; background: var(--ink); color: var(--paper); display: grid; place-items: center; }
  .play:hover { transform: scale(1.05); }
  .track { flex: none; height: 3px; border-radius: 0; background: color-mix(in srgb, var(--ink) 10%, transparent); }
  .track i { border-radius: 0; transition: width .6s; }
</style>
