<script>
  // F189: tam ekran sesli okuma -- yalnizca o anda okunan parca (Drama 3 TR'de cumle grubu) ekranda. Parca degisince
  // gecis: Kayma (eskisi yukari, yenisi asagidan) ya da Belirme (eskisi soner, yenisi yavasca belirir). Grup icinde
  // okunan cumle vurgulanmaz: vurgu sesle tam ortusmuyordu, butun grup ayni parlaklikta durur.
  // Yazi boyutu, renkler ve gecis Gorunum menusunden secilir (ui.json reader.focus_*); uzun grup ekrana sigmazsa
  // yazi yalnizca o grup icin kuculur. Fare 2,5 sn durunca ust satir, dugmeler ve ilerleme cubugu gizlenir.
  import { onDestroy, onMount, tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut, cubicInOut } from 'svelte/easing';
  import Icon from '../lib/Icon.svelte';
  import { call } from '../lib/api.js';
  import { app, saveReaderPrefs, READER_DEFAULTS } from '../lib/state.svelte.js';
  import { player, step } from '../lib/player.svelte.js';

  let { sentences, start = 0, title, subtitle, paper, font, ontoggle, onclose } = $props();

  // paper: okuyucunun sayfa rengi; digerleri uzaktan okumaya uygun sabit ciftler.
  const COLORS = {
    paper: null,
    night: { bg: '#000000', ink: '#f2f2f2', label: 'Gece' },
    amber: { bg: '#000000', ink: '#ffd34d', label: 'Siyah üstüne sarı' },
    warm: { bg: '#1b1612', ink: '#f1d9b0', label: 'Sıcak koyu' },
    navy: { bg: '#0f1b2d', ink: '#e4ecf7', label: 'Lacivert' },
    green: { bg: '#0d1f17', ink: '#cfeedd', label: 'Yeşil' },
    sepia: { bg: '#f4ecd8', ink: '#3b2f1e', label: 'Sepya' },
    light: { bg: '#ffffff', ink: '#111111', label: 'Beyaz' },
    contrast: { bg: '#ffff00', ink: '#000000', label: 'Sarı üstüne siyah' },
  };
  const SIZES = { min: 24, max: 120, step: 4 };

  const colors = $derived(COLORS[app.reader.focus_colors] ?? paper);
  const size = $derived(app.reader.focus_size ?? READER_DEFAULTS.focus_size);
  const motion = $derived(app.reader.focus_motion ?? 'slide');

  // Okuma yokken (ya da bolum gecisinde) ekrandan okunacak cumle gosterilir.
  const range = $derived(player.active && player.from >= 0 ? [player.from, player.to] : [start, start]);
  const text = $derived(sentences.slice(range[0], range[1] + 1).join(' '));
  const progress = $derived(sentences.length ? ((range[1] + 1) / sentences.length) * 100 : 0);

  function setPref(key, value) {
    app.reader[key] = value;
    saveReaderPrefs();
  }
  const resize = (delta) => setPref('focus_size', Math.max(SIZES.min, Math.min(SIZES.max, size + delta)));

  // Belirme: hafif buyukten yerine oturarak belirir, giderken biraz kuculup soner.
  function appear(node, { delay = 0, duration = 900, from = 1.03 }) {
    return { delay, duration, easing: cubicOut, css: (t) => `opacity: ${t}; transform: scale(${from + (1 - from) * t})` };
  }
  const enter = (node) => (motion === 'fade' ? appear(node, { delay: 250 }) : fly(node, { y: 60, duration: 650, delay: 120, easing: cubicOut }));
  const leave = (node) => (motion === 'fade' ? appear(node, { duration: 550, from: 0.96 }) : fly(node, { y: -60, duration: 550, easing: cubicInOut }));

  // Secilen boyut ust sinirdir: grup sahneye sigmazsa yazi sigana kadar kuculur.
  let stage = $state();
  function fit(node, _key) {
    const run = async () => {
      node.style.fontSize = `${size}px`;
      await tick();
      let current = size;
      while (current > 16 && stage && node.scrollHeight > stage.clientHeight - 16) {
        current -= 2;
        node.style.fontSize = `${current}px`;
      }
    };
    run();
    return { update: run };
  }

  let idle = $state(false);
  let menu = $state(false);
  let idleTimer;
  function poke() {
    idle = false;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => (idle = !menu), 2500);
  }

  function keydown(event) {
    if (event.target.closest('input, textarea, select')) return;
    if (event.key === '+' || event.key === '=') resize(SIZES.step);
    else if (event.key === '-') resize(-SIZES.step);
    else return;
    event.preventDefault();
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

<svelte:window onkeydown={keydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="focus" class:idle onmousemove={poke} onpointerdown={poke}
  style:--paper={colors ? colors.bg : 'var(--panel)'} style:--ink={colors ? colors.ink : 'var(--text)'} style:font-family={font}>
  <div class="top">
    <div class="ttl"><b>{title}</b><small>{subtitle}</small></div>
    <span class="count">{#if player.waiting}hazırlanıyor… · {/if}Cümle {range[0] + 1} / {sentences.length}</span>
    <button class="icon-btn" class:on={menu} title="Görünüm: yazı boyutu, renk, geçiş" onclick={() => { menu = !menu; poke(); }}>
      <Icon name="type" /></button>
    <button class="icon-btn" title="Tam ekrandan çık (Esc)" onclick={onclose}><Icon name="shrink" /></button>
  </div>

  {#if menu}
    <div class="menu">
      <div class="r">Yazı boyutu
        <div class="seg">
          <button title="Küçült (−)" onclick={() => resize(-SIZES.step)}><Icon name="minus" size={14} /></button>
          <span class="val">{size}</span>
          <button title="Büyüt (+)" onclick={() => resize(SIZES.step)}><Icon name="plus" size={14} /></button>
        </div>
      </div>
      <input type="range" min={SIZES.min} max={SIZES.max} step={SIZES.step} value={size}
        oninput={(e) => setPref('focus_size', Number(e.currentTarget.value))} />
      <div class="r col">Renk
        <div class="swatches">
          {#each Object.entries(COLORS) as [key, value]}
            {@const shown = value ?? paper}
            <button class="swatch" class:on={(app.reader.focus_colors ?? 'paper') === key} title={value ? value.label : 'Okuyucunun sayfa rengi'}
              style:background={shown ? shown.bg : 'var(--panel)'} style:color={shown ? shown.ink : 'var(--text)'}
              onclick={() => setPref('focus_colors', key)}>A</button>
          {/each}
        </div>
      </div>
      <div class="r">Geçiş
        <div class="seg">
          <button class:on={motion === 'slide'} onclick={() => setPref('focus_motion', 'slide')}>Kayma</button>
          <button class:on={motion === 'fade'} onclick={() => setPref('focus_motion', 'fade')}>Belirme</button>
        </div>
      </div>
    </div>
  {/if}

  <div class="stage" bind:this={stage}>
    {#key `${range[0]}:${text}`}
      <p class="chunk" use:fit={size} in:enter out:leave>{text}</p>
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
  .focus { position: fixed; inset: 0; z-index: 45; background: var(--paper); color: var(--ink); display: flex; flex-direction: column; transition: background .4s, color .4s; }
  .focus.idle { cursor: none; }
  .top, .controls, .track { transition: opacity .4s; }
  .focus.idle .top, .focus.idle .controls, .focus.idle .track { opacity: 0; pointer-events: none; }
  .top { display: flex; align-items: center; gap: 10px; padding: 14px 20px; font-family: var(--sans); }
  .ttl { flex: 1; min-width: 0; }
  .ttl b, .ttl small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: .7; font-size: 13px; }
  .ttl small { opacity: .5; font-size: 12px; }
  .count { font-size: 12px; opacity: .55; white-space: nowrap; margin-right: 4px; }
  .icon-btn { color: var(--ink); }
  .icon-btn.on { color: var(--accent); }

  .menu { position: absolute; right: 20px; top: 58px; width: 300px; z-index: 2; font-family: var(--sans); color: var(--text);
    background: var(--overlay); border: 1px solid var(--outline); border-radius: 14px; padding: 10px 14px 14px; box-shadow: 0 8px 28px var(--shadow); }
  .r { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; font-size: 13px; color: var(--secondary); gap: 10px; }
  .r.col { flex-direction: column; align-items: stretch; }
  .menu input[type='range'] { width: 100%; accent-color: var(--accent); }
  .seg { display: flex; align-items: center; background: var(--surface); border-radius: 999px; padding: 3px; }
  .seg button { padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; color: var(--secondary); display: grid; place-items: center; }
  .seg button.on { background: var(--surface-active); color: var(--text); }
  .seg button:hover { color: var(--text); }
  .val { min-width: 30px; text-align: center; font-weight: 700; font-size: 12px; color: var(--text); }
  .swatches { display: flex; flex-wrap: wrap; gap: 8px; }
  .swatch { width: 30px; height: 30px; border-radius: 50%; border: 2px solid var(--outline); font: 600 12px var(--serif); }
  .swatch.on { border-color: var(--accent); }

  .stage { flex: 1; min-height: 0; display: grid; place-items: center; padding: 0 6vw; overflow: hidden; }
  /* Giden ve gelen parca ayni hucrede ust uste biner, gecis birbirinin icinden olur. */
  .chunk { grid-area: 1 / 1; max-width: min(1400px, 100%); margin: 0; text-align: center; line-height: 1.45; overflow-wrap: break-word; }
  .controls { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 0 0 28px; }
  .play { width: 48px; height: 48px; border-radius: 50%; background: var(--ink); color: var(--paper); display: grid; place-items: center; }
  .play:hover { transform: scale(1.05); }
  .track { flex: none; height: 3px; border-radius: 0; background: color-mix(in srgb, var(--ink) 10%, transparent); }
  .track i { border-radius: 0; transition: width .6s; }
</style>
