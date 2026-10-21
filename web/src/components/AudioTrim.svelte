<script>
  // Klon kaydindan aralik secme (F173): dalga bicimi uzerinde iki tutamac; secim dinlenebilir. Kaydedilince
  // secilen parca onayar klasorune WAV olarak kesilir (voice_presets). `trim`: {start, end} ya da null (tumu).
  import Icon from '../lib/Icon.svelte';
  import { call } from '../lib/api.js';

  // whole: secim kaydin tamamindan baslar (onayarin kayitli kaydi; yeni secilen uzun kayitta ilk `limit` sn)
  let { path, trim = $bindable(), limit = 20, whole = false } = $props();

  let info = $state(null);       // {duration, peaks}
  let error = $state('');
  let start = $state(0);
  let end = $state(0);
  let playing = $state(false);
  let loadingClip = $state(false);
  let player = null;
  let box = $state(null);

  $effect(() => {
    const target = path;
    info = null;
    error = '';
    stop();
    if (!target) return;
    call('tts_reference_peaks', target).then((result) => {
      if (target !== path) return;
      if (!result || result.error) { error = result?.error ?? 'Ses kaydı okunamadı.'; return; }
      info = result;
      start = trim ? Math.min(trim.start, result.duration) : 0;
      end = trim ? Math.min(trim.end, result.duration) : whole ? result.duration : Math.min(result.duration, limit);
      sync();
    });
  });

  const round = (value) => Math.round(value * 10) / 10;
  function sync() {
    if (!info) return;
    const whole = start <= 0.05 && end >= info.duration - 0.05;
    trim = whole ? null : { start: round(start), end: round(end) };
  }
  const length = $derived(Math.max(0, end - start));
  const fmt = (s) => {
    const m = Math.floor(s / 60);
    const rest = (s - m * 60).toFixed(1).replace('.', ',');
    return m ? `${m}:${rest.padStart(4, '0')}` : `${rest} sn`;
  };

  // --- surukleme
  let dragging = null;
  function at(event) {
    const rect = box.getBoundingClientRect();
    return Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) * info.duration;
  }
  function down(event) {
    if (!info) return;
    const time = at(event);
    // yakin tutamac; secimin icinden tutulursa butun secim kayar
    const near = Math.abs(time - start) <= Math.abs(time - end) ? 'start' : 'end';
    const tolerance = info.duration * 0.02;
    if (time > start + tolerance && time < end - tolerance) dragging = { kind: 'move', from: time, start, end };
    else dragging = { kind: near };
    box.setPointerCapture(event.pointerId);
    move(event);
  }
  function move(event) {
    if (!dragging || !info) return;
    const time = at(event);
    if (dragging.kind === 'start') start = Math.min(time, end - 0.5);
    else if (dragging.kind === 'end') end = Math.max(time, start + 0.5);
    else {
      const shift = Math.min(Math.max(time - dragging.from, -dragging.start), info.duration - dragging.end);
      start = dragging.start + shift;
      end = dragging.end + shift;
    }
    start = Math.max(0, start);
    end = Math.min(info.duration, end);
  }
  function up() {
    if (!dragging) return;
    dragging = null;
    sync();
    stop();
  }
  function setStart(value) {
    start = Math.max(0, Math.min(Number(value) || 0, end - 0.5));
    sync();
  }
  function setEnd(value) {
    end = Math.min(info.duration, Math.max(Number(value) || 0, start + 0.5));
    sync();
  }
  function preset(kind) {
    if (kind === 'all') { start = 0; end = info.duration; }
    else { end = Math.min(info.duration, start + limit); }
    sync();
    stop();
  }

  // --- dinleme
  function stop() {
    player?.pause();
    player = null;
    playing = false;
  }
  async function listen() {
    if (playing) return stop();
    loadingClip = true;
    const result = await call('tts_reference_clip', path, start, end);
    loadingClip = false;
    if (!result?.audio) { error = result?.error ?? 'Seçim dinletilemedi.'; return; }
    player = new Audio('data:audio/wav;base64,' + result.audio);
    player.onended = stop;
    playing = true;
    player.play().catch(stop);
  }
  $effect(() => stop);

  const pct = (value) => (info ? (value / info.duration) * 100 : 0);
</script>

{#if error}
  <div class="err"><Icon name="alert" size={14} />{error}</div>
{:else if !info}
  <div class="dim small"><Icon name="loader" size={14} spin />Ses kaydı okunuyor…</div>
{:else}
  <div class="trim">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="wave" bind:this={box} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
      <svg viewBox="0 0 {info.peaks.length} 100" preserveAspectRatio="none" aria-hidden="true">
        {#each info.peaks as value, index}
          <rect x={index} y={50 - Math.max(1, value * 48)} width="0.7" height={Math.max(2, value * 96)} />
        {/each}
      </svg>
      <div class="shade" style="left: 0; width: {pct(start)}%"></div>
      <div class="shade" style="left: {pct(end)}%; right: 0"></div>
      <div class="sel" style="left: {pct(start)}%; width: {pct(end) - pct(start)}%"></div>
      <div class="handle" style="left: {pct(start)}%"></div>
      <div class="handle" style="left: {pct(end)}%"></div>
    </div>
    <div class="controls">
      <button class="icon-btn sm" title={playing ? 'Durdur' : 'Seçimi dinle'} onclick={listen}>
        <Icon name={loadingClip ? 'loader' : playing ? 'stop' : 'play'} size={14} spin={loadingClip} /></button>
      <label>Baş <input class="field num" type="number" min="0" step="0.1" value={round(start)} onchange={(e) => setStart(e.currentTarget.value)} /></label>
      <label>Son <input class="field num" type="number" min="0" step="0.1" value={round(end)} onchange={(e) => setEnd(e.currentTarget.value)} /></label>
      <span class:warnText={length > limit + 0.05}>{fmt(length)} / {fmt(info.duration)}</span>
      <span class="grow"></span>
      <button class="link" onclick={() => preset('limit')}>{limit} sn</button>
      <button class="link" onclick={() => preset('all')}>Tümü</button>
    </div>
    <span class="dim small">{trim ? 'Kaydedince seçilen parça kesilip ses klasörüne WAV olarak yazılır; özgün dosyaya dokunulmaz.' : 'Kaydın tamamı kullanılır.'}
      {length > limit + 0.05 ? `Modeller yaklaşık ilk ${limit} sn'yi kullanır.` : ''} Kaydın metnini yazdıysanız seçilen parçaya göre düzeltin.</span>
  </div>
{/if}

<style>
  .trim { display: flex; flex-direction: column; gap: 6px; }
  .wave { position: relative; height: 64px; border-radius: 8px; background: var(--surface); overflow: hidden; cursor: ew-resize;
    touch-action: none; user-select: none; }
  .wave svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .wave rect { fill: var(--accent); }
  .shade { position: absolute; top: 0; bottom: 0; background: color-mix(in srgb, var(--bg, #000) 60%, transparent); pointer-events: none; }
  .sel { position: absolute; top: 0; bottom: 0; box-shadow: inset 0 0 0 1.5px var(--accent); border-radius: 4px; pointer-events: none; }
  .handle { position: absolute; top: 0; bottom: 0; width: 4px; margin-left: -2px; background: var(--accent); pointer-events: none; }
  .controls { display: flex; align-items: center; gap: 10px; font-size: 12.5px; flex-wrap: wrap; }
  .controls label { display: flex; align-items: center; gap: 4px; color: var(--dim); }
  .num { width: 72px; padding: 4px 6px; }
  .grow { flex: 1; }
  .link { color: var(--accent); font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .dim { color: var(--dim); }
  .small { font-size: 12px; line-height: 1.5; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .warnText { color: var(--warning); }
  .err { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--danger); }
</style>
