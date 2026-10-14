<script>
  // Oynatici (eski qa_panel'in sol karti): HTML5 video, bolum isaretli arama cubugu, ses parcasi,
  // altyazi (CC) menusu. Tarayicinin calamadigi dosyalar arka uctan ffmpeg akisi olarak gelir:
  // akis `offset` anindan baslar, gosterilen zaman offset + video.currentTime'dir.
  import { onDestroy } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { openMenu } from '../lib/menu.svelte.js';
  import { StreamFeed, mseSupported } from '../lib/streamfeed.js';

  const p = $derived(app.player);
  const STEP = 5;

  let videoEl = $state();
  let shell = $state();
  let src = $state('');
  let offset = $state(0);
  let mode = $state('direct');       // 'direct' | 'mse' (akis, tam sarma) | 'stream' (duz akis)
  let feed = null;
  let audio = $state(null);          // secili ses akisi (global index)
  let time = $state(0);
  let playing = $state(false);
  let volume = $state(0.8);
  let muted = $state(false);
  let loading = $state(true);
  let error = $state('');
  let pending = null;                // {time, play}: kaynak yuklenince gidilecek an
  let fullscreen = $state(false);

  const duration = $derived(p?.duration || 0);
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
  };

  let transcode = false;             // kopyalanan goruntu cozulemedi: x264 ile yeniden kodlanir
  async function load(audioIndex, at, play, force = false) {
    const result = await act('player_source', audioIndex, at, force || transcode, transcode);
    if (!result || !videoEl) return;
    error = '';
    loading = true;
    audio = result.audio;
    pending = { time: at, play };
    feed?.stop();
    if (result.mode === 'stream' && mseSupported(result.mime)) {
      // Media Source: zaman gercek zaman (offset 0), indirilmis kisimda serbest sarma.
      mode = 'mse';
      offset = 0;
      src = result.url;
      feed ??= new StreamFeed(videoEl);
      feed.onerror = (failure) => fail('Video akışı oynatılamadı: ' + (failure?.message ?? failure));
      feed.start(result);
      return;
    }
    mode = result.mode;
    offset = result.offset;
    src = result.url;
    videoEl.src = result.url;   // kaynak elle verilir: MSE ile ayni ogeyi paylasir
  }

  // Ilk acilis: onceki konumdan (ya da bekleyen atiftan) basla.
  let opened = '';
  $effect(() => {
    const path = p?.path;
    if (!path || path === opened) return;
    opened = path;
    transcode = false;
    const seek = app.playerSeek;
    const start = seek ? seek.time : app.playerPositions[path] ?? 0;
    if (seek) app.playerSeek = null;
    load(null, start, !!seek?.play);
  });

  // Atif / arama sonucu: o ana git.
  $effect(() => {
    const seek = app.playerSeek;
    if (!seek || !videoEl || !src || p?.path !== opened) return;
    app.playerSeek = null;
    seekTo(seek.time, seek.play);
  });

  function metadata() {
    loading = false;
    if (pending) {
      // Duz akista sarilamaz (akis zaten o andan baslar); dogrudan ve MSE'de tam ana gidilir.
      const target = Math.max(0, pending.time - offset);
      if (mode !== 'stream' && target > 0.05) videoEl.currentTime = target;
      if (pending.play) videoEl.play().catch(() => {});
      pending = null;
    }
  }

  function seekTo(target, play = null) {
    target = Math.max(0, Math.min(target, duration || target));
    const resume = play ?? playing;
    if (mode === 'direct' || (mode === 'mse' && feed?.has(target))) {
      videoEl.currentTime = target;              // dosyada ya da indirilmis kisimda
      if (resume) videoEl.play().catch(() => {});
    } else {
      time = target;
      load(audio, target, resume);              // akisi o andan yeniden baslat
    }
  }

  function toggle() {
    if (!videoEl) return;
    if (videoEl.paused) videoEl.play().catch(() => {});
    else videoEl.pause();
  }

  function keydown(event) {
    if (app.view !== 'player' || event.target.closest('input, textarea, select') || !videoEl) return;
    if (event.key === ' ') { event.preventDefault(); toggle(); }
    else if (event.key === 'ArrowLeft') { event.preventDefault(); seekTo(time - STEP); }
    else if (event.key === 'ArrowRight') { event.preventDefault(); seekTo(time + STEP); }
    else if (event.key === 'f') toggleFullscreen();
  }

  function mediaError() {
    loading = false;
    const code = videoEl?.error?.code;
    if (code) fail('Video oynatılamadı.');
  }

  // Yedek zinciri: dogrudan -> goruntuyu kopyalayan akis -> x264 ile yeniden kodlanan akis.
  function fail(message) {
    loading = false;
    if (mode === 'direct') return load(audio, time, playing, true);
    if (!transcode) {
      transcode = true;
      return load(audio, time, playing, true);
    }
    error = message;
  }

  // --- arama cubugu ---------------------------------------------------------
  let bar = $state();
  let hover = $state(null);   // {x, time}
  let dragging = false;
  const cuts = $derived((p?.marks ?? []).filter((m) => m.start > 0 && m.start < duration).map((m) => m.start));
  const segments = $derived.by(() => {
    const edges = [0, ...cuts, duration || 1];
    return edges.slice(0, -1).map((start, i) => ({ start, end: edges[i + 1] }));
  });
  const chapterAt = (t) => {
    let title = '';
    for (const mark of p?.marks ?? []) if (mark.start <= t + 0.25) title = mark.title;
    return title;
  };
  const timeAtX = (x) => {
    const rect = bar.getBoundingClientRect();
    return Math.max(0, Math.min(1, (x - rect.left) / rect.width)) * duration;
  };
  function barDown(event) {
    if (!duration || event.button !== 0) return;
    dragging = true;
    time = timeAtX(event.clientX);
    const up = (e) => {
      dragging = false;
      window.removeEventListener('mouseup', up);
      window.removeEventListener('mousemove', move);
      seekTo(timeAtX(e.clientX));
    };
    const move = (e) => (time = timeAtX(e.clientX));
    window.addEventListener('mouseup', up);
    window.addEventListener('mousemove', move);
  }
  function barMove(event) {
    if (!duration) return;
    const rect = bar.getBoundingClientRect();
    hover = { x: event.clientX - rect.left, time: timeAtX(event.clientX) };
  }

  function timeupdate() {
    if (!dragging && videoEl) time = offset + videoEl.currentTime;
  }

  // --- altyazi ----------------------------------------------------------------
  let ccKey = $state(null);
  let cues = $state([]);
  let cueStarts = [];
  const subtitle = $derived.by(() => {
    if (!ccKey || !cues.length) return '';
    let lo = 0, hi = cueStarts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cueStarts[mid] <= time) lo = mid + 1; else hi = mid; }
    const active = [];
    for (let i = lo - 1; i >= 0; i--) {
      if (cues[i].start < time - 60) break;
      if (time < cues[i].end) active.unshift(cues[i].text);
    }
    return [...new Set(active)].join('\n');
  });

  async function selectSubtitle(key) {
    ccKey = key;
    cues = [];
    if (!key) return;
    const result = await act('subtitle_load', key);
    if (!Array.isArray(result) || ccKey !== key) { if (!Array.isArray(result)) ccKey = null; return; }
    cues = result;
    cueStarts = result.map((c) => c.start);
  }

  const offWhisper = on('whisper_ready', ({ path }) => {
    if (path === p?.path) selectSubtitle('whisper');
  });

  function ccMenu(event) {
    const items = [{ label: 'Kapalı', icon: ccKey ? null : 'check', action: () => selectSubtitle(null) }];
    const subs = p?.subtitles;
    const streams = (subs ?? []).filter((s) => s.kind === 'stream');
    const files = (subs ?? []).filter((s) => s.kind === 'file');
    for (const [title, list] of [['Videodaki altyazılar', streams], ['Video klasöründeki dosyalar', files]]) {
      if (!list.length) continue;
      items.push('sep', { label: title, disabled: true });
      for (const s of list) items.push({ label: s.label, icon: ccKey === s.key ? 'check' : null, action: () => selectSubtitle(s.key) });
    }
    items.push('sep', { label: 'Sesten (Whisper)', disabled: true });
    if (p?.whisper) items.push({ label: p.whisper, icon: ccKey === 'whisper' ? 'check' : null, action: () => selectSubtitle('whisper') });
    if (p?.transcribing) items.push({ label: 'Konuşmadan metin çıkarılıyor…', disabled: true });
    else if ((p?.audio ?? []).length > 1) {
      for (const track of p.audio) items.push({ label: 'Sesten oluştur · ' + track.label, icon: 'mic', action: () => act('whisper_generate', track.index) });
    } else if (!p?.whisper) items.push({ label: 'Sesten oluştur…', icon: 'mic', action: () => act('whisper_generate', null) });
    if (subs === null) items.push('sep', { label: 'Altyazı akışları okunuyor…', disabled: true });
    openMenu(event, items);
  }

  function audioMenu(event) {
    openMenu(event, [{ label: 'Ses parçası', disabled: true },
      ...p.audio.map((track) => ({ label: track.label, icon: (audio ?? p.audio[0].index) === track.index ? 'check' : null,
        action: () => load(track.index, time, playing) }))]);
  }

  // --- tam ekran ---------------------------------------------------------------
  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else shell?.requestFullscreen?.();
  }

  $effect(() => {
    if (videoEl) { videoEl.volume = volume; videoEl.muted = muted; }
  });

  onDestroy(() => {
    feed?.stop();
    if (p?.path) app.playerPositions[p.path] = time;
    offWhisper();
  });
</script>

<svelte:window onkeydown={keydown} />
<svelte:document onfullscreenchange={() => (fullscreen = !!document.fullscreenElement)} />

<section class="page">
  {#if p}
    <div class="page-head">
      <h1 class="ellipsis title" title={p.path}>{p.name}</h1>
      <button class="btn sm" onclick={() => act('reveal', p.path)}><Icon name="folderOpen" size={14} />Konumu aç</button>
    </div>
    <div class="page-body body">
      <div class="player card" class:full={fullscreen} bind:this={shell}>
        <div class="surface" role="presentation" onclick={toggle} ondblclick={toggleFullscreen}>
          <!-- svelte-ignore a11y_media_has_caption -->
          <video bind:this={videoEl} preload="auto" onloadedmetadata={metadata} ontimeupdate={timeupdate}
            onplay={() => (playing = true)} onpause={() => (playing = false)} onwaiting={() => (loading = true)}
            onplaying={() => (loading = false)} oncanplay={() => (loading = false)} onerror={mediaError}></video>
          {#if subtitle}<div class="subtitle">{subtitle}</div>{/if}
          {#if loading && !error}<div class="spinner"><Icon name="loader" size={34} spin /></div>{/if}
          {#if error}<div class="error">{error}</div>{/if}
        </div>
        <div class="controls">
          <div class="bar" bind:this={bar} role="slider" tabindex="-1" aria-valuenow={time} aria-valuemin="0" aria-valuemax={duration}
            onmousedown={barDown} onmousemove={barMove} onmouseleave={() => (hover = null)}>
            {#each segments as seg}
              <div class="seg" style:left="{(seg.start / (duration || 1)) * 100}%" style:width="calc({((seg.end - seg.start) / (duration || 1)) * 100}% - 3px)">
                <i class="hov" style:width="{hover ? Math.max(0, Math.min(1, (hover.time - seg.start) / (seg.end - seg.start))) * 100 : 0}%"></i>
                <i class="done" style:width="{Math.max(0, Math.min(1, (time - seg.start) / (seg.end - seg.start))) * 100}%"></i>
              </div>
            {/each}
            <span class="knob" style:left="{(time / (duration || 1)) * 100}%"></span>
            {#if hover}<span class="tip" style:left="{hover.x}px">{fmt(hover.time)}{chapterAt(hover.time) ? ' · ' + chapterAt(hover.time) : ''}</span>{/if}
          </div>
          <div class="row">
            <button class="play" title={(playing ? 'Duraklat' : 'Oynat') + ' (Boşluk)'} onclick={toggle}><Icon name={playing ? 'pause' : 'play'} size={18} /></button>
            <button class="icon-btn sm" title="5 sn geri (←)" onclick={() => seekTo(time - STEP)}><Icon name="rotate" size={16} /></button>
            <button class="icon-btn sm" title={muted || !volume ? 'Sesi aç' : 'Sesi kapat'} onclick={() => (muted = !muted)}>
              <Icon name={muted || !volume ? 'mute' : 'volume'} size={18} /></button>
            <input class="volume" type="range" min="0" max="1" step="0.01" bind:value={volume} oninput={() => (muted = false)} title="Ses düzeyi" />
            <span class="mono time">{fmt(time)} / {fmt(duration)}</span>
            {#if chapterAt(time)}<span class="chapter ellipsis">{chapterAt(time)} ›</span>{/if}
            <span class="grow"></span>
            {#if mode !== 'direct'}<span class="badge" title="Video tarayıcının doğrudan çalamadığı bir biçimde; ffmpeg ile anında dönüştürülüyor.">dönüştürülerek</span>{/if}
            {#if (p.audio ?? []).length > 1}
              <button class="icon-btn sm" title="Ses parçası" onclick={audioMenu}><Icon name="headphones" size={18} /></button>
            {/if}
            <button class="icon-btn sm" class:on={ccKey} title="Altyazılar" onclick={ccMenu}><Icon name="subtitles" size={18} /></button>
            <button class="icon-btn sm" title="Tam ekran (F)" onclick={toggleFullscreen}><Icon name={fullscreen ? 'shrink' : 'expand'} size={16} /></button>
          </div>
        </div>
      </div>
    </div>
  {/if}
</section>

<style>
  .title { font-size: 24px !important; }
  .body { display: flex; flex-direction: column; gap: 10px; }
  .player { overflow: hidden; display: flex; flex-direction: column; flex: 1; min-height: 0; background: #000; border-color: var(--outline); }
  .player.full { border: 0; border-radius: 0; }
  .surface { position: relative; flex: 1; min-height: 240px; container-type: size; display: grid; place-items: center; background: #000; cursor: pointer; overflow: hidden; }
  video { width: 100%; height: 100%; object-fit: contain; display: block; position: absolute; inset: 0; }
  .subtitle { position: absolute; left: 50%; bottom: 6%; transform: translateX(-50%); max-width: 86%; text-align: center; white-space: pre-line;
    font-size: clamp(14px, 5cqh, 34px); font-weight: 600; line-height: 1.3; color: #fff; padding: 2px 10px; border-radius: 4px;
    background: rgba(0, 0, 0, .55); text-shadow: 0 1px 2px #000; pointer-events: none; }
  .spinner { position: absolute; color: rgba(255, 255, 255, .8); pointer-events: none; }
  .error { position: absolute; bottom: 16px; left: 16px; right: 16px; color: #fff; background: rgba(200, 40, 50, .8); padding: 8px 12px; border-radius: 8px; font-size: 13px; }

  .controls { background: var(--panel); padding: 8px 14px 10px; display: flex; flex-direction: column; gap: 4px; }
  .bar { position: relative; height: 18px; cursor: pointer; }
  .seg { position: absolute; top: 7px; height: 4px; border-radius: 2px; background: var(--surface-active); overflow: hidden; transition: top .1s, height .1s; }
  .bar:hover .seg { top: 6px; height: 6px; }
  .seg i { position: absolute; left: 0; top: 0; bottom: 0; }
  .seg .hov { background: var(--dim); }
  .seg .done { background: var(--accent); }
  .knob { position: absolute; top: 3px; width: 12px; height: 12px; margin-left: -6px; border-radius: 50%; background: var(--accent); opacity: 0; transition: opacity .1s; }
  .bar:hover .knob { opacity: 1; }
  .tip { position: absolute; bottom: 22px; transform: translateX(-50%); white-space: nowrap; font-size: 12px; background: var(--overlay); color: var(--text);
    border: 1px solid var(--outline); padding: 3px 8px; border-radius: 6px; pointer-events: none; box-shadow: 0 4px 14px var(--shadow); }
  .row { display: flex; align-items: center; gap: 6px; }
  .play { width: 36px; height: 36px; border-radius: 50%; background: var(--text); color: var(--window); display: grid; place-items: center; }
  .play:hover { transform: scale(1.05); }
  .volume { width: 90px; accent-color: var(--accent); }
  .time { font-size: 12px; color: var(--secondary); margin-left: 8px; }
  .chapter { font-size: 12px; color: var(--secondary); background: var(--surface); padding: 3px 10px; border-radius: 999px; max-width: 260px; }
  .grow { flex: 1; }
  .icon-btn.on { color: var(--accent); }
</style>
