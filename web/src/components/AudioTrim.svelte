<script>
  // Klon kaydindan aralik secme (F173): dalga bicimi uzerinde iki tutamac; kaydedilince secilen parca onayar
  // klasorune WAV olarak kesilir (voice_presets). `trim`: {start, end} ya da undefined/null (tumu).
  // F174: zaman cetveli, oynatma imleci ve Whisper'in kelime zamanli metni; kelimeye tiklamak secimin basini,
  // Shift ile tiklamak sonunu o kelimeye getirir. `text`: secimin metni (Kaydin metni kutusu icin).
  import Icon from '../lib/Icon.svelte';
  import { call } from '../lib/api.js';

  // whole: secim kaydin tamamindan baslar (onayarin kayitli kaydi; yeni secilen uzun kayitta ilk `limit` sn)
  let { path, trim = $bindable(), text = $bindable(''), limit = 20, whole = false } = $props();

  let info = $state(null);       // {duration, peaks}
  let error = $state('');
  let start = $state(0);
  let end = $state(0);
  let words = $state(null);      // [[bas, son, kelime]] | null (yukleniyor)
  let wordsError = $state('');
  let box = $state(null);
  let hover = $state(null);      // fare altindaki zaman
  // oynatma: kaydin tamami bir kez alinir; secim ve kelimeler bu ses icinde aranir
  let audio = null;
  let audioLoading = $state(false);
  let playing = $state(false);
  let selection = $state(false); // secimi mi dinliyor (yoksa tumunu)
  let now = $state(null);        // oynatma imleci (sn)
  let stopAt = null;             // secimi dinlerken burada durur
  let frame = 0;

  $effect(() => {
    const target = path;
    info = null;
    error = '';
    words = null;
    wordsError = '';
    stop();
    audio = null;
    if (!target) return;
    call('tts_reference_peaks', target).then((result) => {
      if (target !== path) return;
      if (!result || result.error) { error = result?.error ?? 'Ses kaydı okunamadı.'; return; }
      info = result;
      start = trim ? Math.min(trim.start, result.duration) : 0;
      end = trim ? Math.min(trim.end, result.duration) : whole ? result.duration : Math.min(result.duration, limit);
      sync();
    });
    call('tts_reference_transcript', target).then((result) => {
      if (target !== path) return;
      if (!result || result.error) { wordsError = result?.error ?? 'Kaydın metni çıkarılamadı.'; words = []; return; }
      words = result.words ?? [];
      sync();
    });
  });

  const round = (value) => Math.round(value * 10) / 10;
  function sync() {
    if (!info) return;
    const all = start <= 0.05 && end >= info.duration - 0.05;
    trim = all ? null : { start: round(start), end: round(end) };
    text = (words ?? []).filter(inside).map((word) => word[2]).join(' ');
  }
  const length = $derived(Math.max(0, end - start));
  const fmt = (s) => {
    const m = Math.floor(s / 60);
    const rest = (s - m * 60).toFixed(1).replace('.', ',');
    return m ? `${m}:${rest.padStart(4, '0')}` : `${rest} sn`;
  };
  const tickLabel = (s) => (s >= 60 ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : String(s).replace('.', ','));
  // cetvel: en fazla ~12 isaret
  const ticks = $derived.by(() => {
    if (!info) return [];
    const step = [0.5, 1, 2, 5, 10, 15, 30, 60, 120].find((s) => info.duration / s <= 12) ?? 300;
    const list = [];
    for (let t = 0; t <= info.duration + 1e-6; t += step) list.push(Math.round(t * 10) / 10);
    return list;
  });

  // --- surukleme
  let dragging = null;
  function at(event) {
    const rect = box.getBoundingClientRect();
    return Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) * info.duration;
  }
  function down(event) {
    if (!info) return;
    const time = at(event);
    const near = Math.abs(time - start) <= Math.abs(time - end) ? 'start' : 'end';
    const tolerance = info.duration * 0.02;
    // secimin icinden tutulursa butun secim kayar
    if (time > start + tolerance && time < end - tolerance) dragging = { kind: 'move', from: time, start, end };
    else dragging = { kind: near };
    box.setPointerCapture(event.pointerId);
    move(event);
  }
  function move(event) {
    if (!info) return;
    hover = at(event);
    if (!dragging) return;
    const time = hover;
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
    if (selection) stop();
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
  }
  // kelimeye tiklama: basi o kelimeye (son geride kaldiysa `limit` sn sonrasina); Shift ile sonu
  function pickWord(word, event) {
    if (event.shiftKey) {
      end = Math.min(info.duration, Math.max(word[1] + 0.05, start + 0.5));
    } else {
      start = Math.max(0, word[0] - 0.05);
      if (end < start + 0.5) end = Math.min(info.duration, start + limit);
    }
    sync();
  }

  // --- dinleme
  async function ensureAudio() {
    if (audio) return audio;
    audioLoading = true;
    const result = await call('tts_reference_audio', path);
    audioLoading = false;
    if (!result?.audio) { error = result?.error ?? 'Ses kaydı dinletilemedi.'; return null; }
    audio = new Audio(`data:${result.mime};base64,${result.audio}`);
    audio.onended = stop;
    return audio;
  }
  function tick() {
    if (!audio || !playing) return;
    now = audio.currentTime;
    if (stopAt !== null && now >= stopAt) { stop(); return; }
    frame = requestAnimationFrame(tick);
  }
  function stop() {
    cancelAnimationFrame(frame);
    audio?.pause();
    playing = false;
    selection = false;
    stopAt = null;
    now = null;
  }
  // from: baslangic (sn), until: durma yeri (null: sonuna kadar)
  async function play(from, until = null) {
    const player = await ensureAudio();
    if (!player) return;
    stop();
    player.currentTime = from;
    stopAt = until;
    selection = until !== null;
    try {
      await player.play();
      playing = true;
      frame = requestAnimationFrame(tick);
    } catch {
      stop();
    }
  }
  const toggleSelection = () => (playing && selection ? stop() : play(start, end));
  const toggleAll = () => (playing && !selection ? stop() : play(0));
  $effect(() => stop);

  const pct = (value) => (info ? (value / info.duration) * 100 : 0);
  function inside(word) {
    const middle = (word[0] + word[1]) / 2;
    return middle >= start && middle <= end;
  }
  const current = (word) => now !== null && now >= word[0] && now < word[1] + 0.05;
</script>

{#if error}
  <div class="err"><Icon name="alert" size={14} />{error}</div>
{:else if !info}
  <div class="dim small"><Icon name="loader" size={14} spin />Ses kaydı okunuyor…</div>
{:else}
  <div class="trim">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="wave" bind:this={box} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}
      onpointerleave={() => { if (!dragging) hover = null; }}>
      <svg viewBox="0 0 {info.peaks.length} 100" preserveAspectRatio="none" aria-hidden="true">
        {#each info.peaks as value, index}
          <rect x={index} y={50 - Math.max(1, value * 48)} width="0.7" height={Math.max(2, value * 96)} />
        {/each}
      </svg>
      <div class="shade" style="left: 0; width: {pct(start)}%"></div>
      <div class="shade" style="left: {pct(end)}%; right: 0"></div>
      <div class="sel" style="left: {pct(start)}%; width: {pct(end) - pct(start)}%"></div>
      <div class="handle" style="left: {pct(start)}%"><span>{fmt(start)}</span></div>
      <div class="handle end" style="left: {pct(end)}%"><span>{fmt(end)}</span></div>
      {#if now !== null}<div class="playhead" style="left: {pct(now)}%"></div>{/if}
      {#if hover !== null && !dragging}<div class="cursor" style="left: {pct(hover)}%"><span>{fmt(hover)}</span></div>{/if}
    </div>
    <div class="ruler" aria-hidden="true">
      {#each ticks as t}<span style="left: {pct(t)}%">{tickLabel(t)}</span>{/each}
    </div>
    <div class="controls">
      <button class="btn sm" onclick={toggleSelection}>
        <Icon name={audioLoading ? 'loader' : playing && selection ? 'stop' : 'play'} size={13} spin={audioLoading} />Seçimi dinle</button>
      <button class="btn sm ghost" title="Kaydı baştan dinle; imleç nerede olduğunu gösterir" onclick={toggleAll}>
        <Icon name={playing && !selection ? 'stop' : 'play'} size={13} />Tümünü dinle</button>
      {#if now !== null}<span class="now">{fmt(now)}</span>{/if}
      <span class="grow"></span>
      <label>Baş <input class="field num" type="number" min="0" step="0.1" value={round(start)} onchange={(e) => setStart(e.currentTarget.value)} /></label>
      <label>Son <input class="field num" type="number" min="0" step="0.1" value={round(end)} onchange={(e) => setEnd(e.currentTarget.value)} /></label>
    </div>
    <div class="controls">
      <span class:warnText={length > limit + 0.05}>Seçim: {fmt(length)} / {fmt(info.duration)}</span>
      <span class="grow"></span>
      <button class="link" onclick={() => preset('limit')}>Baştan {limit} sn</button>
      <button class="link" onclick={() => preset('all')}>Tümü</button>
    </div>

    <div class="words">
      {#if words === null}
        <span class="dim small"><Icon name="loader" size={13} spin />Konuşma yazıya dökülüyor (Whisper)…</span>
      {:else if wordsError}
        <span class="dim small">{wordsError}</span>
      {:else if !words.length}
        <span class="dim small">Kayıtta konuşma bulunamadı.</span>
      {:else}
        {#each words as word, index (index)}
          {#if index && word[0] - words[index - 1][1] >= 0.6}<span class="gap" title="{fmt(words[index - 1][1])} – {fmt(word[0])} sessizlik">·</span>{/if}
          <button class="word" class:in={inside(word)} class:now={current(word)} title="{fmt(word[0])} · tıkla: buradan başla, Shift+tıkla: burada bitir"
            onclick={(e) => pickWord(word, e)}>{word[2]}</button>
        {/each}
      {/if}
    </div>
    <span class="dim small">{trim ? 'Kaydedince seçilen parça kesilip ses klasörüne WAV olarak yazılır; özgün dosyaya dokunulmaz.' : 'Kaydın tamamı kullanılır.'}
      {length > limit + 0.05 ? `Modeller yaklaşık ilk ${limit} sn'yi kullanır.` : ''}
      Kelimeye tıklayınca seçim oradan başlar, Shift ile tıklayınca orada biter; parçayı cümle sonunda bitirin.</span>
  </div>
{/if}

<style>
  .trim { display: flex; flex-direction: column; gap: 6px; }
  .wave { position: relative; height: 72px; border-radius: 8px; background: var(--surface); overflow: hidden; cursor: ew-resize;
    touch-action: none; user-select: none; }
  .wave svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .wave rect { fill: var(--accent); }
  .shade { position: absolute; top: 0; bottom: 0; background: color-mix(in srgb, var(--bg, #000) 60%, transparent); pointer-events: none; }
  .sel { position: absolute; top: 0; bottom: 0; box-shadow: inset 0 0 0 1.5px var(--accent); border-radius: 4px; pointer-events: none; }
  .handle, .playhead, .cursor { position: absolute; top: 0; bottom: 0; pointer-events: none; }
  .handle { width: 4px; margin-left: -2px; background: var(--accent); }
  .handle span, .cursor span { position: absolute; top: 2px; left: 6px; font-size: 10.5px; padding: 0 4px; border-radius: 4px; white-space: nowrap;
    background: color-mix(in srgb, var(--bg, #000) 75%, transparent); color: var(--text, #fff); }
  .handle.end span { left: auto; right: 6px; top: auto; bottom: 2px; }
  .playhead { width: 2px; margin-left: -1px; background: var(--text, #fff); box-shadow: 0 0 4px rgba(0, 0, 0, 0.6); }
  .cursor { width: 1px; background: color-mix(in srgb, var(--text, #fff) 50%, transparent); }
  .cursor span { top: auto; bottom: 2px; }
  .ruler { position: relative; height: 14px; font-size: 10.5px; color: var(--dim); }
  .ruler span { position: absolute; transform: translateX(-50%); }
  .ruler span:first-child { transform: none; }
  .controls { display: flex; align-items: center; gap: 8px; font-size: 12.5px; flex-wrap: wrap; }
  .controls label { display: flex; align-items: center; gap: 4px; color: var(--dim); }
  .now { font-variant-numeric: tabular-nums; color: var(--accent); }
  .num { width: 70px; padding: 4px 6px; }
  .grow { flex: 1; }
  .link { color: var(--accent); font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .words { max-height: 140px; overflow: auto; padding: 8px 10px; border-radius: 8px; background: var(--surface); line-height: 1.9; font-size: 13px; }
  .word { padding: 1px 2px; border-radius: 4px; color: var(--dim); }
  .word.in { color: var(--text, inherit); }
  .word:hover { background: color-mix(in srgb, var(--accent) 22%, transparent); }
  .word.now { background: var(--accent); color: var(--on-accent, #000); }
  .gap { color: var(--dim); padding: 0 4px; }
  .dim { color: var(--dim); }
  .small { font-size: 12px; line-height: 1.5; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .warnText { color: var(--warning); }
  .err { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--danger); }
</style>
