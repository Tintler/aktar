<script>
  // F189: tam ekran sesli okuma -- yalnizca o anda okunan parca (Drama 3 TR'de cumle grubu) ekranda. Parca degisince
  // gecis: Kayma (eskisi yukari, yenisi asagidan) ya da Belirme (eskisi soner, yenisi yavasca belirir). Grup icinde
  // okunan cumle vurgulanmaz: vurgu sesle tam ortusmuyordu, butun grup ayni parlaklikta durur.
  // Yazi boyutu, renkler ve gecis Gorunum menusunden secilir (ui.json reader.focus_*); uzun grup ekrana sigmazsa
  // yazi yalnizca o grup icin kuculur. Fare 2,5 sn durunca ust satir, dugmeler ve ilerleme cubugu gizlenir.
  // F197 Gorselli arka plan (ui.json reader.focus_art 'art'): kitabin gorselleri varsa okunan cumlenin sahnesi tam
  // ekran arkada; yazi ortada kalir, gorsel ustte ve altta acik, ortaya dogru sayfa rengine koyulasir (focus_band).
  // Sahne degisince gorsel capraz gecisle degisir; bolumun ilk sahnesine kadar onceki bolumun son gorseli kalir.
  import { onDestroy, onMount, tick } from 'svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut, cubicInOut } from 'svelte/easing';
  import Icon from '../lib/Icon.svelte';
  import { call } from '../lib/api.js';
  import { app, saveReaderPrefs, READER_DEFAULTS } from '../lib/state.svelte.js';
  import { player, step } from '../lib/player.svelte.js';
  import { FOCUS_COLORS } from '../lib/focus.js';

  let { sentences, start = 0, title, subtitle, paper, font, ontoggle, onclose, book = '', section = 0 } = $props();

  const COLORS = FOCUS_COLORS;
  const SIZES = { min: 24, max: 120, step: 4 };

  const colors = $derived(COLORS[app.reader.focus_colors] ?? paper);
  const size = $derived(app.reader.focus_size ?? READER_DEFAULTS.focus_size);
  const motion = $derived(app.reader.focus_motion ?? 'slide');

  // Okuma yokken (ya da bolum gecisinde) ekrandan okunacak cumle gosterilir.
  const range = $derived(player.active && player.from >= 0 ? [player.from, player.to] : [start, start]);
  const text = $derived(sentences.slice(range[0], range[1] + 1).join(' '));
  const progress = $derived(sentences.length ? ((range[1] + 1) / sentences.length) * 100 : 0);

  // F197: bolumun sahne gorselleri; baslangic cumlesi metniyle (anchor) yeniden bulunur, bolme degistiyse kaymasin.
  const hasArt = $derived(Boolean(app.artBooks[book]?.images));
  const artOn = $derived(hasArt && app.reader.focus_art === 'art');
  const band = $derived(app.reader.focus_band ?? READER_DEFAULTS.focus_band);
  let art = $state({ scenes: [], carry: '' });
  $effect(() => {
    const [id, number, on] = [book, section, artOn];
    app.artBooks[book]?.images;   // uretim bitince (sayi degisince) yeniden sorulur
    if (!on || !id) { art = { scenes: [], carry: '' }; return; }
    call('art_section', id, number).then((r) => { if (r && !r.error && id === book && number === section) art = r; });
  });
  const norm = (s) => String(s ?? '').split(/\s+/).filter(Boolean).join(' ');
  // Sahnenin ilk cumlesi (anchor) plandaki sirasinda degilse aranir: once birebir, sonra cumle bolme ayari degistiyse
  // anchor'i iceren (birlesen) ya da anchor'in basi olan (bolunen) cumle; birden fazlaysa plandaki sirasina en yakini.
  const nearest = (scene, test) => {
    let best = -1;
    sentences.forEach((s, i) => {
      if (test(norm(s)) && (best < 0 || Math.abs(i - scene.start) < Math.abs(best - scene.start))) best = i;
    });
    return best;
  };
  const starts = $derived(art.scenes.map((scene) => {
    const anchor = scene.anchor;
    if (!anchor || norm(sentences[scene.start]) === anchor) return { ...scene };
    let found = nearest(scene, (s) => s === anchor);
    if (found < 0) found = nearest(scene, (s) => (anchor.length >= 12 && s.includes(anchor)) || (s.length >= 12 && anchor.startsWith(s)));
    return { ...scene, start: found >= 0 ? found : scene.start };
  }).sort((a, b) => a.start - b.start));
  const image = $derived(artOn ? ([...starts].reverse().find((s) => s.start <= range[0])?.url ?? art.carry) : '');
  // iki katman: yeni gorsel ustteki katmana gelir, yuklenince belirir (capraz gecis)
  let layers = $state([{ url: '', on: false }, { url: '', on: false }]);
  let top = 0;
  $effect(() => {
    const url = image;
    if (url === layers[top].url) return;
    if (!url) { layers[0].on = layers[1].on = false; return; }
    const next = 1 - top;
    const img = new Image();
    img.onload = () => {
      if (image !== url) return;
      layers[next].url = url;
      layers[next].on = true;
      layers[top].on = false;
      top = next;
    };
    img.src = url;
  });

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
<div class="focus" class:idle class:art={artOn} onmousemove={poke} onpointerdown={poke}
  style:--paper={colors ? colors.bg : 'var(--panel)'} style:--ink={colors ? colors.ink : 'var(--text)'} style:font-family={font}
  style:--band={band}>
  {#if artOn}
    {#each layers as layer, i (i)}
      <div class="art-layer" class:on={layer.on} style:background-image={layer.url ? `url("${layer.url}")` : 'none'}></div>
    {/each}
    <div class="veil"></div>
  {/if}
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
      <div class="r">Arka plan
        <div class="seg" title={hasArt ? '' : 'Bu kitabın görseli yok: kitaplıkta kitaba sağ tıklayıp "Kitap görselleri oluştur"'}>
          <button class:on={!artOn} onclick={() => setPref('focus_art', 'plain')}>Düz</button>
          <button class:on={artOn} disabled={!hasArt} onclick={() => setPref('focus_art', 'art')}>Görselli</button>
        </div>
      </div>
      {#if artOn}
        <div class="r">Yazı bandı <span class="val">%{Math.round(band * 100)}</span></div>
        <input type="range" min="0" max="1" step="0.05" value={band} title="Ortadaki yazının arkasındaki koyuluk"
          oninput={(e) => setPref('focus_band', Number(e.currentTarget.value))} />
      {/if}
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
  /* F197: gorsel tam ekran; ust ve alt acik, orta yazi bandi sayfa rengine koyulasir. z-index -1: .focus'un
     yigin baglaminda arka planin ustunde, yazi ve dugmelerin altinda */
  .art-layer { position: absolute; inset: 0; background: center / cover no-repeat; opacity: 0; transition: opacity 1.2s ease; pointer-events: none; z-index: -1; }
  .art-layer.on { opacity: 1; }
  .veil { position: absolute; inset: 0; pointer-events: none; z-index: -1;
    background: linear-gradient(to bottom, transparent 0%,
      color-mix(in srgb, var(--paper) calc(var(--band) * 55%), transparent) 16%,
      color-mix(in srgb, var(--paper) calc(var(--band) * 100%), transparent) 36%,
      color-mix(in srgb, var(--paper) calc(var(--band) * 100%), transparent) 64%,
      color-mix(in srgb, var(--paper) calc(var(--band) * 55%), transparent) 84%, transparent 100%); }
  .focus.art .chunk { text-shadow: 0 0 18px color-mix(in srgb, var(--paper) 90%, transparent), 0 1px 2px color-mix(in srgb, var(--paper) 80%, transparent); }
  .focus.art .top, .focus.art .controls { text-shadow: 0 1px 3px rgba(0, 0, 0, .6); }
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
