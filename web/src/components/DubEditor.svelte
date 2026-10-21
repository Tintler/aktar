<script>
  // Dublaj duzenleyicisi (F175): oynatici sayfasinda video duzenleyici duzeni. Video ustte, sagda secili satirin /
  // kisma araliginin denetcisi, altta zaman cizelgesi (ozgun sesin dalga bicimi + kisma araliklari, altyazi satirlari,
  // dublaj sesleri). Proje arka uctadir (dub_project.py); degisiklikler kisa gecikmeyle dub_project_save ile yazilir.
  // Kullanici satiri boler/birlestirir, metnini ve Drama 3 etiketini duzeltir, dublaj sesini surukleyerek tasir,
  // istedigi satiri yeniden seslendirir, ozgun sesin kisilacagi yerleri cizer. 'Dublajı dinle' acikken video oynarken
  // satir sesleri yerlerinde calar ve video sesi kisma araliklarinda kisilir (onlevel ile oynaticiya bildirilir).
  import { onDestroy, untrack } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { app, act, toast, savePref } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { subtool, onSubtool, jobText } from '../lib/subtools.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';

  let { path, time = 0, playing = false, duration = 0, volume = 1, muted = false, canSetup = false,
    seek, toggle, pause, onlevel, onsetup, onclose } = $props();

  const EDIT_KEYS = ['id', 'start', 'end', 'text', 'tag', 'voice', 'speaker', 'at', 'gain', 'speed', 'fit'];
  const SOUND_KEYS = ['text', 'tag', 'voice', 'speed', 'fit'];
  const AUDIO_KEYS = ['audio', 'duration', 'sig', 'take', 'tempo', 'ready', 'stale', 'url'];
  const MERGE_GAP = 0.8, DUCK_PAD = 0.2;      // dub.py ile ayni
  const SPEEDS = [0.8, 0.9, 1, 1.1, 1.2, 1.35, 1.5];
  const TEMPOS = [[1, 'Hızlandırma'], [1.2, 'En fazla 1,2×'], [1.35, 'En fazla 1,35×'], [1.5, 'En fazla 1,5×'], [1.75, 'En fazla 1,75×']];

  let project = $state(null);
  let loaded = $state(false);
  let selected = $state(null);                // {kind: 'line', id} | {kind: 'duck', index}
  let tab = $state('edit');                   // 'edit' | 'settings'
  let listen = $state(app.prefs.dub_listen !== false);
  let pps = $state(Math.max(8, Math.min(400, app.prefs.dub_zoom ?? 60)));   // piksel / saniye
  let filter = $state('');
  let wave = $state(null);                    // {duration, peaks}
  let voices = $state([]);
  let tags = $state([]);
  let tmpId = -1;

  // --- yukleme ve kaydetme ----------------------------------------------------------
  async function load() {
    const result = await call('dub_project_get', path);
    project = result?.project ?? null;
    loaded = true;
    if (selected?.kind === 'line' && !project?.lines.some((l) => l.id === selected.id)) selected = null;
  }
  load();
  call('dub_project_wave', path).then((result) => { if (result?.peaks) wave = result; });
  call('tts_voices').then((list) => { if (Array.isArray(list)) voices = list.filter((v) => v.language === 'tr'); });
  call('tts_emotion_catalog').then((result) => { if (result?.tags) tags = result.tags; });

  let rev = 0;
  let saveTimer;
  let saving = $state(false);
  const pick = (line) => Object.fromEntries(EDIT_KEYS.map((k) => [k, k === 'id' && line.id < 0 ? null : $state.snapshot(line[k])]));
  function changed() {
    rev++;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }
  async function save() {
    clearTimeout(saveTimer);
    if (!project) return;
    const sent = rev;
    saving = true;
    const result = await call('dub_project_save', path, {
      lines: project.lines.map(pick), ducks: $state.snapshot(project.ducks), voice: project.voice, options: $state.snapshot(project.options),
    }).finally(() => (saving = false));
    if (result?.error) return toast(result.error, 'error');
    if (sent !== rev || !result?.project) return;   // bu arada yeni degisiklik: sonraki kayit uygular
    const chosen = selected?.kind === 'line' ? project.lines.find((l) => l.id === selected.id) : null;
    project = result.project;
    if (chosen && chosen.id < 0) {   // yeni satir kalici kimligini aldi
      const same = project.lines.find((l) => Math.abs(l.start - chosen.start) < 0.002 && l.text === chosen.text);
      selected = same ? { kind: 'line', id: same.id } : null;
    }
  }

  // Geri al (Ctrl+Z): duzenlemeden once satirlarin ve kisma araliklarinin kopyasi
  let undo = [];
  let lastUndo = 0;
  function remember(force = false) {
    if (!project || (!force && performance.now() - lastUndo < 800)) return;
    lastUndo = performance.now();
    undo.push($state.snapshot({ lines: project.lines, ducks: project.ducks }));
    if (undo.length > 50) undo.shift();
  }
  function undoLast() {
    const last = undo.pop();
    if (!last || !project) return;
    project.lines = last.lines;
    project.ducks = last.ducks;
    changed();
  }

  function edit(line, patch) {
    remember();
    const sound = SOUND_KEYS.some((k) => k in patch && patch[k] !== line[k]);
    Object.assign(line, patch);
    if (sound && line.ready) line.stale = true;
    changed();
  }
  function setOption(key, value) {
    remember(true);
    project.options[key] = value;
    if (['speed', 'normalize', 'overlap', 'max_tempo'].includes(key)) for (const l of project.lines) if (l.ready) l.stale = true;
    changed();
  }
  function setVoice(value) {
    project.voice = value;
    for (const l of project.lines) if (l.ready && !l.voice) l.stale = true;
    changed();
  }

  // --- olaylar ------------------------------------------------------------------------
  const offLine = on('dub_line', (data) => {
    if (data.path !== path || !project) return;
    const line = project.lines.find((l) => l.id === data.line.id);
    if (line) for (const k of AUDIO_KEYS) line[k] = data.line[k];
  });
  const offJob = onSubtool((job) => {
    if (job.path !== path) return;
    if (job.kind === 'dubprep' || job.kind === 'dubgen') load();
  });
  const busy = $derived(!!subtool.job);
  const myJob = $derived(subtool.job?.path === path ? subtool.job : null);

  // --- hesaplar (dub_project.placements / auto_ducks ile ayni) ------------------------
  const opts = $derived(project?.options ?? {});
  const lines = $derived(project?.lines ?? []);
  const placed = $derived.by(() => {
    let cursor = 0;
    return lines.map((l) => {
      const length = l.ready ? l.duration : 0;
      const at = l.at ?? (opts.overlap ? l.start : Math.max(l.start, cursor));
      cursor = at + length;
      return at;
    });
  });
  const autoDucks = $derived.by(() => {
    const items = [];
    lines.forEach((l, i) => { if (l.ready && l.duration > 0) items.push([placed[i], l.duration]); });
    for (const l of lines) items.push([l.start, Math.max(0, l.end - l.start) + DUCK_PAD]);
    items.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [at, length] of items) {
      const end = at + length;
      const last = merged[merged.length - 1];
      if (last && at - last.end < MERGE_GAP) last.end = Math.max(last.end, end);
      else merged.push({ start: at, end, level: null });
    }
    return merged;
  });
  const manualDucks = $derived(project?.ducks != null);
  const ducks = $derived(project?.ducks ?? (opts.duck ? autoDucks : []));
  const pendingCount = $derived(lines.filter((l) => !l.ready || l.stale).length);
  const readyCount = $derived(lines.filter((l) => l.ready).length);
  const end = $derived(Math.max(duration || 0, wave?.duration || 0, ...lines.map((l, i) => Math.max(l.end, placed[i] + (l.duration || 0)))) + 2);

  function levelAt(t) {
    if (!project) return 1;
    if (!manualDucks && !opts.duck) return opts.background;
    for (const d of ducks) if (t >= d.start - 0.1 && t < d.end) return d.level ?? opts.background;
    return 1;
  }

  // --- onizleme: satir sesleri video ile birlikte -------------------------------------
  let stamp = { time: 0, at: 0 };
  $effect(() => { stamp = { time, at: performance.now() }; });
  const playersMap = new Map();     // satir kimligi -> Audio
  let solo = null;
  let soloId = $state(null);
  const gainOf = (l) => Math.min(1, l.gain ?? 1) * (muted ? 0 : volume);
  function stopAll() {
    for (const audio of playersMap.values()) audio.pause();
    playersMap.clear();
  }
  function stopSolo() {
    solo?.pause();
    solo = null;
    soloId = null;
  }
  let raf = requestAnimationFrame(tick);
  function tick() {
    raf = requestAnimationFrame(tick);
    step();
  }
  // Zaman her degistiginde de (rAF arka planda/gizli pencerede durabilir)
  $effect(() => { time; playing; listen; untrack(step); });
  function step() {
    if (!project) return;
    const now = playing ? stamp.time + (performance.now() - stamp.at) / 1000 : time;
    onlevel?.(listen ? levelAt(now) : 1);
    if (!playing || !listen) { if (playersMap.size) stopAll(); return; }
    if (solo) stopSolo();
    lines.forEach((l, i) => {
      if (!l.url) return;
      const start = placed[i], stop = start + l.duration;
      const audio = playersMap.get(l.id);
      if (now >= start && now < stop - 0.05) {
        if (!audio) {
          const next = new Audio(l.url + '#t=' + Math.max(0, now - start).toFixed(2));
          next.volume = gainOf(l);
          next.play().catch(() => {});
          playersMap.set(l.id, next);
        } else {
          audio.volume = gainOf(l);
          if (!audio.paused && audio.readyState > 1 && Math.abs(audio.currentTime - (now - start)) > 0.35) audio.currentTime = now - start;
        }
      } else if (audio && (now < start - 0.1 || now > stop + 0.1)) {
        audio.pause();
        playersMap.delete(l.id);
      }
    });
  }
  function playSolo(line) {
    if (soloId === line.id) return stopSolo();
    stopSolo();
    if (!line.url) return;
    if (playing) pause?.();
    solo = new Audio(line.url);
    solo.volume = gainOf(line);
    solo.onended = stopSolo;
    soloId = line.id;
    solo.play().catch(stopSolo);
  }
  function playFrom(line, index) {
    stopSolo();
    if (!listen) { listen = true; savePref({ dub_listen: true }); }
    seek(Math.max(0, Math.min(line.start, placed[index]) - 0.5), true);
  }

  // --- secim ----------------------------------------------------------------------------
  const selectedIndex = $derived(selected?.kind === 'line' ? lines.findIndex((l) => l.id === selected.id) : -1);
  const line = $derived(selectedIndex >= 0 ? lines[selectedIndex] : null);
  const duck = $derived(selected?.kind === 'duck' ? ducks[selected.index] ?? null : null);
  function selectLine(id, reveal = false) {
    selected = { kind: 'line', id };
    tab = 'edit';
    if (reveal) {
      const i = lines.findIndex((l) => l.id === id);
      if (i >= 0) scrollTo(Math.min(lines[i].start, placed[i]));
    }
  }
  const visibleList = $derived.by(() => {
    const q = filter.trim().toLocaleLowerCase('tr');
    return lines.map((l, i) => ({ l, i })).filter(({ l }) => !q || l.text.toLocaleLowerCase('tr').includes(q));
  });

  // --- satir islemleri ------------------------------------------------------------------
  let textArea = $state();
  let caret = { id: null, at: -1 };   // metindeki son imlec (Bol dugmesine basinca odak metin kutusundan cikar)
  const keepCaret = () => { if (line && textArea) caret = { id: line.id, at: textArea.selectionStart }; };
  function split() {
    if (!line) return;
    const text = line.text;
    let cut = caret.id === line.id ? caret.at : -1;
    if (cut <= 0 || cut >= text.length) {   // imlec yoksa ortaya en yakin bosluk
      const middle = text.length / 2;
      cut = -1;
      for (let i = 0; i < text.length; i++) if (text[i] === ' ' && (cut < 0 || Math.abs(i - middle) < Math.abs(cut - middle))) cut = i;
    }
    const left = text.slice(0, Math.max(0, cut)).trim(), right = text.slice(Math.max(0, cut)).trim();
    if (!left || !right) return toast('Bölmek için metinde imleci bölünecek yere koyun.', 'info');
    const inside = time > line.start + 0.1 && time < line.end - 0.1;
    const at = Math.round((inside ? time : line.start + (line.end - line.start) * (left.length / (left.length + right.length))) * 1000) / 1000;
    remember(true);
    const second = { id: tmpId--, start: at, end: line.end, text: right, tag: '', voice: line.voice, speaker: line.speaker, at: null,
      gain: line.gain, speed: line.speed, fit: line.fit, ready: false, stale: false, duration: 0, url: '' };
    edit(line, { text: left, end: at });
    project.lines.splice(selectedIndex + 1, 0, second);
    changed();
  }
  function mergeNext() {
    if (!line || selectedIndex + 1 >= lines.length) return;
    const next = lines[selectedIndex + 1];
    remember(true);
    edit(line, { text: line.text + ' ' + next.text, end: Math.max(line.end, next.end) });
    project.lines.splice(selectedIndex + 1, 1);
    changed();
  }
  function removeLine() {
    if (!line) return;
    remember(true);
    const index = selectedIndex;
    project.lines.splice(index, 1);
    const next = project.lines[Math.min(index, project.lines.length - 1)];
    selected = next ? { kind: 'line', id: next.id } : null;
    changed();
  }
  function addLine() {
    if (!project) return;
    remember(true);
    const item = { id: tmpId--, start: Math.round(time * 1000) / 1000, end: Math.round((time + 2) * 1000) / 1000, text: 'Yeni satır',
      tag: '', voice: '', speaker: null, at: null, gain: 1, speed: 1, fit: true, ready: false, stale: false, duration: 0, url: '' };
    const index = project.lines.findIndex((l) => l.start > item.start);
    project.lines.splice(index < 0 ? project.lines.length : index, 0, item);
    selectLine(item.id);
    changed();
    setTimeout(() => { textArea?.focus(); textArea?.select(); }, 0);
  }

  async function generate(ids = null, fresh = false) {
    await save();
    stopSolo();
    act('dub_project_generate', path, ids, fresh);
  }
  async function exportDub() {
    await save();
    if (pendingCount && !(await confirm({ title: 'Dışa aktar', ok: 'Yine de aktar',
      message: `${pendingCount} satırın sesi eksik ya da eski. Eksik satırlar dublajda olmaz; eski satırlar önceki sesleriyle girer.` }))) return;
    act('dub_project_export', path);
  }

  // --- kisma araliklari ---------------------------------------------------------------
  function materialize() {   // otomatik araliklar elle duzenlemeye gecerken kopyalanir
    if (project.ducks == null) project.ducks = autoDucks.map((d) => ({ ...d }));
  }
  function editDuck(index, patch) {
    remember();
    materialize();
    Object.assign(project.ducks[index], patch);
    changed();
  }
  function removeDuck() {
    if (!duck) return;
    remember(true);
    materialize();
    project.ducks.splice(selected.index, 1);
    selected = null;
    changed();
  }
  async function resetDucks() {
    if (!(await confirm({ title: 'Otomatik kısma', message: 'Elle çizdiğiniz kısma aralıkları silinir; özgün ses dublajın konuştuğu yerlerde kendiliğinden kısılır.', ok: 'Otomatiğe dön' }))) return;
    remember(true);
    project.ducks = null;
    selected = null;
    changed();
  }

  // --- zaman cizelgesi ----------------------------------------------------------------
  let scroller = $state();
  let inner = $state();
  let canvas = $state();
  let scrollLeft = $state(0);
  let viewWidth = $state(800);
  const fmt = (s) => {
    s = Math.max(0, s || 0);
    const m = Math.floor(s / 60), r = s - m * 60;
    return `${m}:${r < 10 ? '0' : ''}${r.toFixed(1)}`;
  };
  const viewStart = $derived(scrollLeft / pps - 1);
  const viewEnd = $derived((scrollLeft + viewWidth) / pps + 1);
  const shown = $derived(lines.map((l, i) => i).filter((i) => {
    const l = lines[i];
    return Math.max(l.end, placed[i] + (l.duration || 0)) > viewStart && Math.min(l.start, placed[i]) < viewEnd;
  }));
  const tickStep = $derived([0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => s * pps >= 80) ?? 600);
  const ticks = $derived.by(() => {
    const result = [];
    for (let t = Math.max(0, Math.floor(viewStart / tickStep) * tickStep); t <= viewEnd; t += tickStep) result.push(t);
    return result;
  });
  function scrollTo(t) {
    if (!scroller) return;
    const x = t * pps;
    if (x < scroller.scrollLeft + 40 || x > scroller.scrollLeft + viewWidth - 80) scroller.scrollLeft = Math.max(0, x - viewWidth * 0.25);
  }
  $effect(() => {   // oynarken imlec gorunur kalir
    const x = time * pps;
    if (!playing || !scroller) return;
    if (x > scroller.scrollLeft + viewWidth * 0.9 || x < scroller.scrollLeft) scroller.scrollLeft = Math.max(0, x - viewWidth * 0.15);
  });
  function zoom(factor, anchorX = viewWidth / 2) {
    const at = (scroller.scrollLeft + anchorX) / pps;
    pps = Math.max(8, Math.min(400, pps * factor));
    savePref({ dub_zoom: Math.round(pps) });
    requestAnimationFrame(() => { scroller.scrollLeft = Math.max(0, at * pps - anchorX); });
  }
  function wheel(event) {
    if (event.ctrlKey) {
      event.preventDefault();
      zoom(event.deltaY < 0 ? 1.25 : 0.8, event.clientX - scroller.getBoundingClientRect().left);
    } else if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
      event.preventDefault();
      scroller.scrollLeft += event.deltaY;
    }
  }
  $effect(() => {   // dalga bicimi: yalnizca gorunen kisim cizilir
    if (!canvas || !wave) return;
    const dpr = window.devicePixelRatio || 1;
    const width = viewWidth, height = canvas.clientHeight || 60;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = getComputedStyle(canvas).color;
    const perSecond = wave.peaks.length / (wave.duration || 1);
    for (let x = 0; x < width; x++) {
      const a = Math.floor(((scrollLeft + x) / pps) * perSecond), b = Math.max(a + 1, Math.floor(((scrollLeft + x + 1) / pps) * perSecond));
      let peak = 0;
      for (let i = a; i < b && i < wave.peaks.length; i++) peak = Math.max(peak, wave.peaks[i]);
      const h = Math.max(1, peak * (height - 6));
      ctx.fillRect(x, (height - h) / 2, 1, h);
    }
  });
  function measure() {
    if (scroller) viewWidth = scroller.clientWidth;
  }
  $effect(() => {
    if (!scroller) return;
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    return () => observer.disconnect();
  });
  const timeAt = (event) => Math.max(0, (event.clientX - inner.getBoundingClientRect().left) / pps);

  // Surukleme: esik asilmazsa tiklama sayilir
  function drag(event, onmove, onend) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const x0 = event.clientX;
    let moved = false;
    const move = (e) => {
      if (Math.abs(e.clientX - x0) > 3) moved = true;
      if (moved) onmove((e.clientX - x0) / pps, e);
    };
    const up = (e) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      onend?.(moved, e);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }
  const round = (v) => Math.round(Math.max(0, v) * 1000) / 1000;
  function edgeOf(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    return rect.width > 16 && x < 6 ? 'start' : rect.width > 16 && x > rect.width - 6 ? 'end' : 'move';
  }
  function clipDown(event, l, index) {
    const origin = placed[index];
    remember(true);
    drag(event, (dx) => (l.at = round(origin + dx)), (moved) => { selectLine(l.id); if (moved) changed(); });
  }
  function subDown(event, l) {
    const edge = edgeOf(event), s0 = l.start, e0 = l.end;
    remember(true);
    drag(event, (dx) => {
      if (edge !== 'end') l.start = round(Math.min(edge === 'start' ? e0 - 0.1 : Infinity, s0 + dx));
      if (edge !== 'start') l.end = round(Math.max(edge === 'end' ? s0 + 0.1 : 0, e0 + dx));
    }, (moved) => { selectLine(l.id); if (moved) changed(); });
  }
  function duckDown(event, index) {
    const edge = edgeOf(event);
    remember(true);
    materialize();
    const d = project.ducks[index], s0 = d.start, e0 = d.end;
    drag(event, (dx) => {
      if (edge !== 'end') d.start = round(Math.min(edge === 'start' ? e0 - 0.1 : Infinity, s0 + dx));
      if (edge !== 'start') d.end = round(Math.max(edge === 'end' ? s0 + 0.1 : 0, e0 + dx));
    }, (moved) => { selected = { kind: 'duck', index }; tab = 'edit'; if (moved) changed(); });
  }
  function laneDown(event) {   // ozgun ses seridinde bos yerden surukleme: yeni kisma araligi
    if (event.button !== 0 || !project) return;
    const t0 = timeAt(event);
    remember(true);
    materialize();
    const item = { start: round(t0), end: round(t0), level: null };
    project.ducks.push(item);
    drag(event, (dx) => {
      item.start = round(Math.min(t0, t0 + dx));
      item.end = round(Math.max(t0, t0 + dx));
    }, (moved) => {
      if (!moved || item.end - item.start < 0.1) { project.ducks.splice(project.ducks.indexOf(item), 1); seek(t0); return; }
      project.ducks.sort((a, b) => a.start - b.start);
      selected = { kind: 'duck', index: project.ducks.indexOf(item) };
      tab = 'edit';
      changed();
    });
  }
  function rulerDown(event) {
    if (event.button !== 0) return;
    seek(timeAt(event));
    const move = (e) => seek(timeAt(e));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  function keydown(event) {
    if (event.target.closest('input, textarea, select')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undoLast(); }
    else if (event.key === 'Delete') { event.preventDefault(); if (duck) removeDuck(); else removeLine(); }
    else if (event.key === 's' && !event.ctrlKey && line) { event.preventDefault(); split(); }
    else if (event.key === '+' || event.key === '=') zoom(1.25);
    else if (event.key === '-') zoom(0.8);
  }

  const tagLabel = (tag) => tags.find((t) => t.tag === tag)?.label ?? '';
  const voiceLabel = (value) => voices.find((v) => v.value === value)?.label ?? value;
  const speakerName = (id) => (id == null ? '' : 'K' + (Number(id) + 1));
  const lineState = (l) => (!l.ready ? 'missing' : l.stale ? 'stale' : 'ready');
  const STATE_TEXT = { missing: 'Ses yok', stale: 'Ses eski (metin/etiket/ses değişti)', ready: 'Hazır' };
  const voiceGroups = $derived([...new Set(voices.map((v) => v.group))]);

  onDestroy(() => {
    cancelAnimationFrame(raf);
    stopAll();
    stopSolo();
    offLine();
    offJob();
    onlevel?.(1);
    if (rev && saveTimer) save();
    clearTimeout(saveTimer);
  });
</script>

<svelte:window onkeydown={keydown} />

<datalist id="dub-tags">
  {#each tags as t}<option value={t.tag}>{t.label}</option>{/each}
</datalist>

<aside class="dub-inspector card">
  <div class="tabs">
    <button class:on={tab === 'edit'} onclick={() => (tab = 'edit')}>Düzenle</button>
    <button class:on={tab === 'settings'} onclick={() => (tab = 'settings')}>Proje</button>
    <span class="grow"></span>
    {#if saving}<span class="dim small">Kaydediliyor…</span>{/if}
    <button class="icon-btn sm" title="Düzenleyiciyi kapat" onclick={onclose}><Icon name="x" size={16} /></button>
  </div>

  {#if !loaded}
    <div class="empty"><Icon name="loader" size={22} spin /></div>
  {:else if !project}
    <div class="empty">
      {#if myJob?.kind === 'dubprep'}
        <Icon name="loader" size={22} spin /><b>Dublaj projesi hazırlanıyor…</b><span class="dim">{jobText(myJob)}</span>
      {:else}
        <Icon name="waveform" size={28} /><b>Bu video için dublaj projesi yok</b>
        <span class="dim">Altyazının satırları düzenlenebilir bir dublaj projesine dönüşür: her satırı ayrı seslendirir, taşır, bölersiniz.</span>
        <button class="btn primary" disabled={!canSetup || busy} onclick={onsetup}><Icon name="plus" size={15} />Dublaj projesi oluştur</button>
        {#if !canSetup}<span class="dim small">Önce CC menüsünden seslendirilecek (Türkçe) altyazıyı seçin.</span>{/if}
      {/if}
    </div>
  {:else if tab === 'settings'}
    <div class="pane">
      <div class="row-info"><span class="label">Altyazı</span><span class="ellipsis">{project.label || project.source}</span></div>
      <label class="stack"><span class="label">Ana ses</span>
        <select class="field" value={project.voice} onchange={(e) => setVoice(e.currentTarget.value)}>
          <option value="">Sesli okuma sesi (Ayarlar → Ses)</option>
          {#each voiceGroups as group}
            <optgroup label={group}>{#each voices.filter((v) => v.group === group) as v}<option value={v.value}>{v.label}</option>{/each}</optgroup>
          {/each}
        </select>
      </label>
      <div class="grid2">
        <label class="stack"><span class="label">Konuşma hızı</span>
          <select class="field" value={opts.speed} onchange={(e) => setOption('speed', Number(e.currentTarget.value))}>
            {#each [0.9, 1, 1.1, 1.2] as s}<option value={s}>{s.toLocaleString('tr-TR')}×</option>{/each}
          </select></label>
        <label class="stack"><span class="label">Sığmayan satırlar</span>
          <select class="field" value={opts.max_tempo} disabled={opts.overlap} onchange={(e) => setOption('max_tempo', Number(e.currentTarget.value))}>
            {#each TEMPOS as [value, text]}<option {value}>{text}</option>{/each}
          </select></label>
      </div>
      <Toggle checked={opts.overlap} label="Çakışan satırları üst üste koy" onchange={(v) => setOption('overlap', v)} />
      <Toggle checked={opts.normalize} label="Ses düzeyini eşitle" onchange={(v) => setOption('normalize', v)} />
      <div class="stack">
        <span class="label">{opts.separate ? 'Özgün konuşma düzeyi' : 'Özgün ses düzeyi'} (kısma aralıklarında): %{Math.round(opts.background * 100)}</span>
        <input type="range" min="0" max="1" step="0.05" value={opts.background} oninput={(e) => setOption('background', Number(e.currentTarget.value))} />
        {#if manualDucks}
          <span class="hint">Kısma aralıkları elle düzenleniyor ({ducks.length} aralık).</span>
          <button class="btn sm" onclick={resetDucks}><Icon name="refresh" size={14} />Otomatik kısmaya dön</button>
        {:else}
          <Toggle checked={opts.duck} label="Yalnızca dublaj konuşurken kıs" onchange={(v) => setOption('duck', v)} />
        {/if}
      </div>
      <label class="stack"><span class="label">Çıktı</span>
        <select class="field" value={opts.format} onchange={(e) => setOption('format', e.currentTarget.value)}>
          <option value="mkv">Video (.dublaj.mkv)</option>
          <option value="m4a">Yalnızca ses (.dublaj.m4a)</option>
        </select></label>
      <span class="hint">Hız, eşitleme ya da üst üste koyma değişince satırların sesi eski sayılır; "Eksikleri seslendir" yeniden üretir.
        {opts.separate ? ' Müzik ve efektler korunur (yalnızca özgün konuşma kısılır).' : ''}</span>
      <button class="btn" disabled={!canSetup || busy} onclick={onsetup}><Icon name="rotate" size={15} />Projeyi altyazıdan yeniden oluştur…</button>
    </div>
  {:else}
    <div class="pane editor">
      {#if line}
        <div class="head">
          <span class="dot {lineState(line)}" title={STATE_TEXT[lineState(line)]}></span>
          <b>Satır {selectedIndex + 1} / {lines.length}</b>
          {#if line.speaker != null}<span class="chip" title="Konuşmacı">{speakerName(line.speaker)}</span>{/if}
          <span class="grow"></span>
          <button class="icon-btn sm" title="Önceki satır" disabled={selectedIndex <= 0} onclick={() => selectLine(lines[selectedIndex - 1].id, true)}><Icon name="prev" size={15} /></button>
          <button class="icon-btn sm" title="Sonraki satır" disabled={selectedIndex >= lines.length - 1} onclick={() => selectLine(lines[selectedIndex + 1].id, true)}><Icon name="next" size={15} /></button>
        </div>
        <textarea class="field text" rows="3" bind:this={textArea} value={line.text}
          oninput={(e) => { edit(line, { text: e.currentTarget.value }); keepCaret(); }} onkeyup={keepCaret} onclick={keepCaret} onselect={keepCaret} onblur={(e) => edit(line, { text: e.currentTarget.value.replace(/\s+/g, ' ').trim() || line.text })}></textarea>
        <div class="grid2">
          <label class="stack"><span class="label">İfade etiketi (Drama 3)</span>
            <input class="field" list="dub-tags" value={line.tag} placeholder="Etiketsiz" title={tagLabel(line.tag)}
              onchange={(e) => edit(line, { tag: e.currentTarget.value.trim() })} /></label>
          <label class="stack"><span class="label">Ses</span>
            <select class="field" value={line.voice} onchange={(e) => edit(line, { voice: e.currentTarget.value })}>
              <option value="">Ana ses</option>
              {#each voiceGroups as group}
                <optgroup label={group}>{#each voices.filter((v) => v.group === group) as v}<option value={v.value}>{v.label}</option>{/each}</optgroup>
              {/each}
            </select></label>
        </div>
        <div class="grid3">
          <label class="stack"><span class="label">Altyazı başı</span>
            <input class="field mono" type="number" step="0.1" min="0" value={line.start} onchange={(e) => edit(line, { start: round(Number(e.currentTarget.value)) })} /></label>
          <label class="stack"><span class="label">Altyazı sonu</span>
            <input class="field mono" type="number" step="0.1" min="0" value={line.end} onchange={(e) => edit(line, { end: round(Number(e.currentTarget.value)) })} /></label>
          <label class="stack"><span class="label">Hız</span>
            <select class="field" value={line.speed} onchange={(e) => edit(line, { speed: Number(e.currentTarget.value) })}>
              {#each SPEEDS as s}<option value={s}>{s.toLocaleString('tr-TR')}×</option>{/each}
            </select></label>
        </div>
        <div class="buttons">
          <button class="btn sm" title="Altyazı başını oynatma imlecine al" onclick={() => edit(line, { start: round(time) })}>Baş = imleç</button>
          <button class="btn sm" title="Altyazı sonunu oynatma imlecine al" onclick={() => edit(line, { end: round(time) })}>Son = imleç</button>
        </div>
        <div class="stack">
          <span class="label">Dublajın yeri: {line.at == null ? 'otomatik' : 'elle'} · {fmt(placed[selectedIndex])}{line.ready ? ` – ${fmt(placed[selectedIndex] + line.duration)}` : ''}</span>
          <div class="buttons">
            <input class="field mono at" type="number" step="0.1" min="0" value={placed[selectedIndex]} title="Dublaj sesinin başladığı an (sn)"
              onchange={(e) => edit(line, { at: round(Number(e.currentTarget.value)) })} />
            <button class="btn sm" title="Dublaj sesini oynatma imlecine taşı" onclick={() => edit(line, { at: round(time) })}>İmlece taşı</button>
            <button class="btn sm" disabled={line.at == null} title="Altyazının zamanına geri koy" onclick={() => edit(line, { at: null })}>Otomatik</button>
          </div>
        </div>
        <div class="stack">
          <span class="label">Satırın ses düzeyi: %{Math.round((line.gain ?? 1) * 100)}</span>
          <input type="range" min="0" max="2" step="0.05" value={line.gain ?? 1} oninput={(e) => edit(line, { gain: Number(e.currentTarget.value) })} />
          <Toggle checked={line.fit} label="Yerine sığmazsa hızlandır" onchange={(v) => edit(line, { fit: v })} />
        </div>
        <div class="buttons">
          <button class="btn sm" disabled={!line.url} onclick={() => playSolo(line)}><Icon name={soloId === line.id ? 'stop' : 'play'} size={14} />{soloId === line.id ? 'Durdur' : 'Dinle'}</button>
          <button class="btn sm" title="Bu satırdan videoyla birlikte oynat" onclick={() => playFrom(line, selectedIndex)}><Icon name="film" size={14} />Buradan oynat</button>
          <button class="btn sm primary" disabled={busy} title={line.ready ? 'Ses motorundan yeni bir deneme ister (önbellek kullanılmaz)' : 'Bu satırı seslendir'}
            onclick={() => generate([line.id], line.ready && !line.stale)}><Icon name="refresh" size={14} />{line.ready && !line.stale ? 'Yeniden seslendir' : 'Seslendir'}</button>
        </div>
        <div class="buttons">
          <button class="btn sm" title="Metindeki imleçten böl (S); zaman, oynatma imleci satırın içindeyse oradan" onclick={split}><Icon name="scissors" size={14} />Böl</button>
          <button class="btn sm" disabled={selectedIndex >= lines.length - 1} onclick={mergeNext}><Icon name="arrowRight" size={14} />Sonrakiyle birleştir</button>
          <button class="btn sm danger" title="Satırı sil (Delete)" onclick={removeLine}><Icon name="trash" size={14} />Sil</button>
        </div>
        {#if line.ready && line.tempo > 1.01}<span class="hint">Sığması için {line.tempo.toLocaleString('tr-TR', { maximumFractionDigits: 2 })}× hızlandırıldı.</span>{/if}
      {:else if duck}
        <div class="head"><span class="dot duck"></span><b>Kısma aralığı</b></div>
        <div class="grid2">
          <label class="stack"><span class="label">Başlangıç</span>
            <input class="field mono" type="number" step="0.1" min="0" value={duck.start} onchange={(e) => editDuck(selected.index, { start: round(Number(e.currentTarget.value)) })} /></label>
          <label class="stack"><span class="label">Bitiş</span>
            <input class="field mono" type="number" step="0.1" min="0" value={duck.end} onchange={(e) => editDuck(selected.index, { end: round(Number(e.currentTarget.value)) })} /></label>
        </div>
        <div class="stack">
          <span class="label">Özgün ses bu aralıkta: %{Math.round((duck.level ?? opts.background) * 100)}{duck.level == null ? ' (proje düzeyi)' : ''}</span>
          <input type="range" min="0" max="1" step="0.05" value={duck.level ?? opts.background} oninput={(e) => editDuck(selected.index, { level: Number(e.currentTarget.value) })} />
          <div class="buttons">
            <button class="btn sm" onclick={() => editDuck(selected.index, { level: 0 })}>Tamamen sustur</button>
            <button class="btn sm" disabled={duck.level == null} onclick={() => editDuck(selected.index, { level: null })}>Proje düzeyi</button>
            <button class="btn sm danger" onclick={removeDuck}><Icon name="trash" size={14} />Sil</button>
          </div>
        </div>
        {#if !manualDucks}<span class="hint">Bu otomatik bir aralık; değiştirince tüm aralıklar elle düzenlemeye geçer.</span>{/if}
      {:else}
        <p class="hint">Zaman çizelgesinde bir satıra ya da dublaj sesine tıklayın. Dublaj sesini sürükleyerek taşıyın; altyazı
          kutusunun kenarlarından tutup süresini değiştirin. Özgün ses şeridinde boş yerden sürükleyerek o aralıkta sesi kısın.
          Ctrl+Z geri alır, Ctrl+tekerlek yakınlaştırır.</p>
      {/if}
    </div>
    <div class="list-head">
      <input class="field sm" placeholder="Satırlarda ara…" bind:value={filter} />
      <button class="icon-btn sm" title="Oynatma imlecine yeni satır ekle" onclick={addLine}><Icon name="plus" size={16} /></button>
    </div>
    <div class="list">
      {#each visibleList as { l, i } (l.id)}
        <button class="item" class:on={line?.id === l.id} onclick={() => { selectLine(l.id, true); seek(Math.min(l.start, placed[i])); }}>
          <span class="dot {lineState(l)}" title={STATE_TEXT[lineState(l)]}></span>
          <span class="mono t">{fmt(l.start)}</span>
          <span class="ellipsis">{#if l.tag}<i class="tag">{l.tag}</i> {/if}{l.text}</span>
          {#if l.at != null}<Icon name="arrowRight" size={12} />{/if}
        </button>
      {/each}
    </div>
  {/if}
</aside>

<div class="dub-timeline card">
  <div class="toolbar">
    <b class="title"><Icon name="waveform" size={16} />Dublaj düzenleyici</b>
    {#if project}
      <span class="dim small">{readyCount} / {lines.length} satır hazır{pendingCount ? ` · ${pendingCount} bekliyor` : ''}{manualDucks ? ` · ${ducks.length} elle kısma` : ''}</span>
    {/if}
    <span class="grow"></span>
    {#if myJob}
      <span class="badge accent">{jobText(myJob)}</span>
      <button class="btn sm" onclick={() => act('subtool_cancel')}><Icon name="stop" size={14} />Durdur</button>
    {/if}
    <Toggle bind:checked={listen} label="Dublajı dinle" onchange={(v) => savePref({ dub_listen: v })} />
    <button class="icon-btn sm" title="Oynat / duraklat (Boşluk)" onclick={toggle}><Icon name={playing ? 'pause' : 'play'} size={16} /></button>
    <span class="mono small">{fmt(time)}</span>
    <button class="icon-btn sm" title="Uzaklaştır (-)" onclick={() => zoom(0.8)}><Icon name="minus" size={14} /></button>
    <button class="icon-btn sm" title="Yakınlaştır (+)" onclick={() => zoom(1.25)}><Icon name="plus" size={14} /></button>
    <button class="btn sm" disabled={!project || busy || !pendingCount} onclick={() => generate()}><Icon name="volume" size={14} />Eksikleri seslendir{pendingCount ? ` (${pendingCount})` : ''}</button>
    <button class="btn sm primary" disabled={!project || busy || !readyCount} onclick={exportDub}><Icon name="download" size={14} />Dışa aktar</button>
  </div>
  <div class="tracks">
    <div class="heads">
      <span class="h ruler-h"></span>
      <span class="h">Özgün ses</span>
      <span class="h">Altyazı</span>
      <span class="h">Dublaj</span>
    </div>
    <div class="scroller" bind:this={scroller} onscroll={() => (scrollLeft = scroller.scrollLeft)} onwheel={wheel}>
      <div class="inner" bind:this={inner} style:width="{end * pps}px">
        <div class="ruler" role="presentation" onpointerdown={rulerDown}>
          {#each ticks as t}<span class="tick" style:left="{t * pps}px">{fmt(t).replace(/\.0$/, '')}</span>{/each}
        </div>
        <div class="lane wave" role="presentation" onpointerdown={laneDown} title="Boş yerden sürükleyin: bu aralıkta özgün sesi kıs">
          <canvas bind:this={canvas} style:left="{scrollLeft}px" style:width="{viewWidth}px"></canvas>
          {#each ducks as d, index}
            {#if d.end > viewStart && d.start < viewEnd}
              <div class="duck" class:auto={!manualDucks} class:on={selected?.kind === 'duck' && selected.index === index} role="presentation"
                style:left="{d.start * pps}px" style:width="{Math.max(2, (d.end - d.start) * pps)}px"
                style:--depth={1 - (d.level ?? opts.background)}
                title="Özgün ses %{Math.round((d.level ?? opts.background) * 100)} ({fmt(d.start)} – {fmt(d.end)})"
                onpointerdown={(e) => duckDown(e, index)}>
                {#if (d.end - d.start) * pps > 44}<span>%{Math.round((d.level ?? opts.background) * 100)}</span>{/if}
              </div>
            {/if}
          {/each}
        </div>
        <div class="lane subs">
          {#each shown as i (lines[i].id)}
            {@const l = lines[i]}
            <div class="sub" class:on={line?.id === l.id} role="presentation" style:left="{l.start * pps}px" style:width="{Math.max(3, (l.end - l.start) * pps)}px"
              title="{fmt(l.start)} – {fmt(l.end)}: {l.text}" onpointerdown={(e) => subDown(e, l)}>{l.text}</div>
          {/each}
        </div>
        <div class="lane dubs">
          {#each shown as i (lines[i].id)}
            {@const l = lines[i]}
            <div class="clip {lineState(l)}" class:on={line?.id === l.id} class:moved={l.at != null} role="presentation"
              style:left="{placed[i] * pps}px" style:width="{Math.max(6, (l.ready ? l.duration : Math.max(0.4, l.end - l.start)) * pps)}px"
              title="{STATE_TEXT[lineState(l)]}{l.at != null ? ' · elle taşındı' : ''}{l.voice ? ' · ' + voiceLabel(l.voice) : ''} — sürükleyerek taşıyın"
              onpointerdown={(e) => clipDown(e, l, i)} ondblclick={() => playSolo(l)}>
              {#if l.tag}<i class="tag">{l.tag}</i>{/if}<span>{l.text}</span>
            </div>
          {/each}
        </div>
        <div class="playhead" style:left="{time * pps}px"></div>
      </div>
    </div>
  </div>
</div>

<style>
  .dub-inspector { grid-column: 2; grid-row: 1 / span 2; display: flex; flex-direction: column; min-height: 0; overflow: hidden; padding: 0; }
  .dub-timeline { grid-column: 1; grid-row: 2; display: flex; flex-direction: column; min-height: 0; overflow: hidden; padding: 0; }
  .tabs { display: flex; align-items: center; gap: 4px; padding: 8px 10px; border-bottom: 1px solid var(--outline); }
  .tabs > button:not(.icon-btn) { padding: 5px 12px; border-radius: 8px; font-weight: 600; font-size: 13px; color: var(--secondary); }
  .tabs > button.on { background: var(--surface); color: var(--text); }
  .grow { flex: 1; }
  .small { font-size: 12px; }
  .empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 24px; text-align: center; font-size: 13px; }
  .pane { display: flex; flex-direction: column; gap: 10px; padding: 12px; overflow: auto; }
  .pane.editor { flex: 0 1 auto; min-height: 0; border-bottom: 1px solid var(--outline); }
  .tabs + .pane:not(.editor) { flex: 1; }
  .stack { display: flex; flex-direction: column; gap: 5px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
  .grid2 > *, .grid3 > * { min-width: 0; }
  .grid2 .field, .grid3 .field { width: 100%; min-width: 0; box-sizing: border-box; }
  .buttons { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .hint { font-size: 12px; color: var(--dim); line-height: 1.5; margin: 0; }
  .row-info { display: flex; gap: 10px; font-size: 13px; align-items: baseline; }
  .head { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--surface); color: var(--secondary); }
  .text { resize: vertical; min-height: 64px; font-size: 14px; line-height: 1.45; }
  .at { width: 96px; }
  input[type='range'] { width: 100%; accent-color: var(--accent); }
  .btn.danger { color: var(--danger); }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; background: var(--dim); }
  .dot.ready { background: var(--ok); }
  .dot.stale { background: var(--warning); }
  .dot.missing { background: transparent; box-shadow: inset 0 0 0 1.5px var(--dim); }
  .dot.duck { background: var(--danger); }
  .list-head { display: flex; gap: 6px; align-items: center; padding: 8px 10px 4px; }
  .list-head input { flex: 1; }
  .list { flex: 1 0 140px; min-height: 140px; overflow: auto; padding: 0 6px 8px; }
  .item { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; padding: 5px 6px; border-radius: 6px; font-size: 12.5px; color: var(--secondary); }
  .item:hover { background: var(--surface-hover); }
  .item.on { background: var(--surface); color: var(--text); }
  .item .t { font-size: 11px; color: var(--dim); flex: none; width: 48px; }
  .item .ellipsis { flex: 1; min-width: 0; }
  .tag { font-style: normal; color: var(--accent); font-size: 11px; }

  .toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--outline); flex-wrap: wrap; }
  .toolbar .title { display: flex; align-items: center; gap: 6px; font-size: 13.5px; }
  .tracks { flex: 1; min-height: 0; display: flex; }
  .heads { flex: none; width: 82px; display: flex; flex-direction: column; border-right: 1px solid var(--outline); }
  .h { font-size: 11.5px; color: var(--secondary); font-weight: 600; padding: 0 10px; display: flex; align-items: center; }
  .heads .h, .lane { height: 64px; }
  .heads .ruler-h, .ruler { height: 22px; flex: none; }
  .heads .h + .h { border-top: 1px solid var(--outline); }
  .scroller { flex: 1; min-width: 0; overflow-x: auto; overflow-y: hidden; position: relative; }
  .inner { position: relative; min-width: 100%; }
  .ruler { position: relative; cursor: col-resize; background: var(--panel); border-bottom: 1px solid var(--outline); user-select: none; }
  .tick { position: absolute; top: 0; bottom: 0; padding-left: 4px; font-size: 10.5px; color: var(--dim); border-left: 1px solid var(--outline); line-height: 22px; }
  .lane { position: relative; border-bottom: 1px solid var(--outline); overflow: hidden; }
  .lane.wave { cursor: crosshair; }
  canvas { position: absolute; top: 0; height: 100%; color: color-mix(in srgb, var(--secondary) 55%, transparent); pointer-events: none; }
  .duck { position: absolute; top: 0; bottom: 0; cursor: grab; border-radius: 4px;
    background: color-mix(in srgb, var(--danger) calc(10% + var(--depth) * 22%), transparent);
    box-shadow: inset 2px 0 color-mix(in srgb, var(--danger) 70%, transparent), inset -2px 0 color-mix(in srgb, var(--danger) 70%, transparent); }
  .duck.auto { background: color-mix(in srgb, var(--danger) calc(5% + var(--depth) * 12%), transparent); box-shadow: none; border: 1px dashed color-mix(in srgb, var(--danger) 45%, transparent); }
  .duck.on { outline: 2px solid var(--danger); }
  .duck span { position: absolute; top: 3px; left: 6px; font-size: 10.5px; font-weight: 700; color: var(--danger); pointer-events: none; }
  .sub, .clip { position: absolute; top: 8px; bottom: 8px; border-radius: 6px; padding: 3px 7px; font-size: 11.5px; line-height: 1.3; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis; cursor: grab; user-select: none; }
  .sub { background: var(--surface); color: var(--secondary); border: 1px solid var(--outline); cursor: ew-resize; }
  .sub.on { border-color: var(--accent); color: var(--text); }
  .clip { display: flex; flex-direction: column; background: color-mix(in srgb, var(--accent) 22%, var(--panel)); border: 1px solid color-mix(in srgb, var(--accent) 60%, transparent); color: var(--text); }
  .clip span { overflow: hidden; text-overflow: ellipsis; }
  .clip.stale { background: color-mix(in srgb, var(--warning) 20%, var(--panel)); border-color: color-mix(in srgb, var(--warning) 65%, transparent); }
  .clip.missing { background: transparent; border-style: dashed; border-color: var(--outline); color: var(--dim); }
  .clip.moved { box-shadow: inset 0 -3px color-mix(in srgb, var(--accent) 80%, transparent); }
  .clip.on { outline: 2px solid var(--accent); outline-offset: -1px; }
  .playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--accent); pointer-events: none; }
</style>
