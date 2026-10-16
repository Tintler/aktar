<script>
  // Oynatici (eski qa_panel'in sol karti): HTML5 video, bolum isaretli arama cubugu, ses parcasi,
  // altyazi (CC) menusu. Tarayicinin calamadigi dosyalar arka uctan ffmpeg akisi olarak gelir:
  // akis `offset` anindan baslar, gosterilen zaman offset + video.currentTime'dir.
  import { onDestroy } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { openMenu, menu } from '../lib/menu.svelte.js';
  import { pending as dialog } from '../lib/confirm.svelte.js';
  import { StreamFeed, mseSupported } from '../lib/streamfeed.js';
  import NotesPanel from '../components/NotesPanel.svelte';
  import SyncPanel from '../components/SyncPanel.svelte';
  import ClipPanel from '../components/ClipPanel.svelte';
  import SubtitleExportModal from '../components/SubtitleExportModal.svelte';
  import { notes, loadNotes, startNote, NOTE_COLORS } from '../lib/notes.svelte.js';
  import { subtool, onSubtool, IDENTITY, signed, jobText } from '../lib/subtools.svelte.js';

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
  // Ses duzeyi ve sessiz durumu hatirlanir (tarayici deposu; yoksa varsayilan).
  const saved = (() => { try { return JSON.parse(localStorage.getItem('aktar.volume') || '{}'); } catch { return {}; } })();
  let volume = $state(typeof saved.volume === 'number' ? Math.max(0, Math.min(1, saved.volume)) : 0.8);
  let muted = $state(!!saved.muted);
  $effect(() => {
    const value = JSON.stringify({ volume, muted });
    try { localStorage.setItem('aktar.volume', value); } catch { /* depo yok */ }
  });
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

  let transcode = false;             // kopyalanan goruntu cozulemedi: H.264'e yeniden kodlanir
  let software = false;              // GPU kodlamasi basarisiz: islemci (x264) kullanilir (F120)
  let encoder = $state('');          // akisin GPU kodlayicisi ('' islemci)
  let encoderLabel = $state('');
  let codec = $state('');            // kaynak goruntu kodu (rozet)

  // --- gomulu mpv (F122) ---------------------------------------------------------
  // engine 'mpv': video WebView'de degil, pencereye gomulu mpv'de oynar. Arayuz video alaninin
  // dikdortgenini bildirir; mpv durumu 'mpv' olayiyla gelir. Videonun ustune HTML cizilemediginden
  // menu ya da pencere acikken video gizlenir.
  const native = $derived(p?.engine === 'mpv');
  let hwdec = $state('');
  let surface = $state();
  let lastRect = '';
  let rafId = 0;
  const covered = $derived(!!menu.current || exporting || !!dialog.current || !!app.review);
  function placeLoop() {
    rafId = requestAnimationFrame(placeLoop);
    if (!native || !surface) return;
    const r = surface.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const visible = !covered && app.view === 'player' && r.width > 2 && r.height > 2;
    const key = [r.left, r.top, r.width, r.height, dpr, visible].map((v) => (typeof v === 'number' ? Math.round(v * 100) : v)).join(',');
    if (key === lastRect) return;
    lastRect = key;
    call('mpv_place', r.left * dpr, r.top * dpr, r.width * dpr, r.height * dpr, visible);
  }
  rafId = requestAnimationFrame(placeLoop);
  const offMpv = on('mpv', (s) => {
    if (!native || !s.ready || s.path !== p?.path) return;
    if (!dragging) time = s.time;
    playing = !s.paused;
    loading = s.buffering;
    hwdec = s.hwdec;
    if (previewEnd !== null && time >= previewEnd) {
      previewEnd = null;
      call('mpv_command', 'pause');
    }
  });
  const offKeys = on('mpv_key', ({ key }) => {
    if (!native || app.view !== 'player') return;
    poke();   // her etkilesim (tiklama, tus, fare) tam ekranda kontrolleri geri getirir
    if (key === 'MBTN_LEFT_DBL' && justOpened()) return;
    const actions = {
      MOUSE_MOVE: poke, MBTN_LEFT: toggle, MBTN_LEFT_DBL: toggleFullscreen, SPACE: toggle, f: toggleFullscreen, n: noteHere,
      LEFT: () => seekTo(time - STEP), RIGHT: () => seekTo(time + STEP),
      g: () => ccKey && shiftSubtitle(-0.1), h: () => ccKey && shiftSubtitle(0.1),
      G: () => ccKey && shiftSubtitle(-1), H: () => ccKey && shiftSubtitle(1),
      i: () => markClip('start'), o: () => markClip('end'),
      ESC: () => setFullscreen(false),
    };
    actions[key]?.();
  });

  // Takilma tanisi (F121): oynatma beklemeye gecince onde ne kadar veri oldugu Konsol'a yazilir.
  // Onde veri varken takiliyorsa cozucu yetismiyor; yoksa veri gec geliyor.
  let waitStart = null, waitAhead = 0, lastNote = 0;
  function bufferedAhead() {
    const ranges = videoEl?.buffered;
    const now = videoEl?.currentTime ?? 0;
    for (let i = 0; i < (ranges?.length ?? 0); i++) if (now >= ranges.start(i) - 0.5 && now <= ranges.end(i)) return ranges.end(i) - now;
    return 0;
  }
  function stalled() {
    loading = true;
    if (!playing || pending) return;   // ilk yukleme ve sarma sayilmaz
    waitStart = performance.now();
    waitAhead = bufferedAhead();
  }
  function resumed() {
    loading = false;
    if (waitStart === null) return;
    const seconds = (performance.now() - waitStart) / 1000;
    waitStart = null;
    if (seconds < 0.4 || performance.now() - lastNote < 5000) return;
    lastNote = performance.now();
    const how = mode === 'direct' ? 'doğrudan' : encoderLabel ? 'dönüştürülerek · ' + encoderLabel : 'paketlenerek';
    const cause = waitAhead > 1.5 ? 'önde veri vardı: çözücü yetişmiyor' : 'önde veri yoktu: veri geç geliyor';
    call('player_note', `Takılma ${seconds.toFixed(1)} sn (${fmt(time)}, ${(codec || '?').toUpperCase()} ${how}; önde ${waitAhead.toFixed(1)} sn, ${cause})`);
  }
  // WebView'in kendi cozebildigi ek kodlar (HEVC yalnizca donanim cozucusu/eklentisi varsa):
  // varsa arka uc o goruntuyu donusturmeden (dogrudan ya da yalnizca paketleyerek) verir.
  const hevcType = (c) => document.createElement('video').canPlayType(`video/mp4; codecs="${c}"`) !== '' || mseSupported(`video/mp4; codecs="${c}"`);
  const codecs = [['hevc', 'hvc1.1.6.L120.B0'], ['hevc10', 'hvc1.2.4.L120.B0']].filter(([, c]) => hevcType(c)).map(([name]) => name);
  async function load(audioIndex, at, play, force = false) {
    if (native) {
      mode = 'native';
      error = '';
      if (audioIndex !== null && audioIndex !== undefined && audio !== null && opened === p.path && audioIndex !== audio) {
        audio = audioIndex;
        await act('mpv_command', 'audio', audioIndex);
        return;
      }
      audio = audioIndex;
      app.busy = 'Video açılıyor…';   // ilk acilista libmpv yuklenir; ikinci tiklama olmasin
      const state = await act('mpv_open', p.path, at, play).finally(() => (app.busy = ''));
      lastRect = '';   // panel bu acilista olusmus olabilir: konum yeniden bildirilsin
      if (state) { time = at; codec = (state.codec || '').split(' ')[0].toLowerCase(); }
      return;
    }
    const result = await act('player_source', audioIndex, at, force || transcode, transcode, codecs, software);
    if (!result || !videoEl) return;
    encoder = result.encoder ?? '';
    encoderLabel = result.encoder_label ?? '';
    codec = result.codec ?? '';
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
    openedAt = performance.now();
    transcode = false;
    software = false;
    timings = {};          // zamanlama ve klip videoya ozeldir
    clipRange = null;
    panel = '';
    const seek = app.playerSeek;
    const start = seek ? seek.time : app.playerPositions[path] ?? 0;
    if (seek) app.playerSeek = null;
    load(null, start, !!seek?.play);
  });

  // Atif / arama sonucu: o ana git.
  $effect(() => {
    const seek = app.playerSeek;
    if (!seek || p?.path !== opened || (!native && (!videoEl || !src))) return;
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
    if (native) {
      time = target;
      call('mpv_command', 'seek', target);
      if (play !== null) call('mpv_command', play ? 'play' : 'pause');
      return;
    }
    if (mode === 'direct' || (mode === 'mse' && feed?.has(target))) {
      videoEl.currentTime = target;              // dosyada ya da indirilmis kisimda
      if (resume) videoEl.play().catch(() => {});
    } else {
      time = target;
      load(audio, target, resume);              // akisi o andan yeniden baslat
    }
  }

  function toggle() {
    if (native) return call('mpv_command', 'toggle');
    if (!videoEl) return;
    if (videoEl.paused) videoEl.play().catch(() => {});
    else videoEl.pause();
  }

  function keydown(event) {
    if (app.view !== 'player' || event.target.closest('input, textarea, select') || (!videoEl && !native)) return;
    if (event.key === ' ') { event.preventDefault(); toggle(); }
    else if (event.key === 'ArrowLeft') { event.preventDefault(); seekTo(time - STEP); }
    else if (event.key === 'ArrowRight') { event.preventDefault(); seekTo(time + STEP); }
    else if (event.key === 'f') toggleFullscreen();
    else if (event.key === 'Escape' && fullscreen) setFullscreen(false);
    else if (event.key === 'n' && !event.ctrlKey && !event.metaKey) { event.preventDefault(); noteHere(); }
    else if ((event.key === 'g' || event.key === 'G' || event.key === 'h' || event.key === 'H') && ccKey && !event.ctrlKey) {
      event.preventDefault();
      shiftSubtitle((event.key.toLowerCase() === 'g' ? -1 : 1) * (event.shiftKey ? 1 : 0.1));
    } else if ((event.key === 'i' || event.key === 'o') && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      markClip(event.key === 'i' ? 'start' : 'end');
    }
  }

  // --- altyazi zamanlamasi ve klip (F118) ------------------------------------------
  let panel = $state('');            // alt panel: '' | 'sync' | 'clip' (notlar: notes.open)
  let timings = $state({});          // altyazi anahtari -> {scale, offset}
  const timing = $derived(timings[ccKey] ?? IDENTITY);
  let clipRange = $state(null);      // {start, end}
  let previewEnd = null;             // onizleme bu anda durur
  let exporting = $state(false);
  let osd = $state('');
  let osdTimer;

  function openPanel(name) {
    panel = panel === name ? '' : name;
    if (panel) notes.open = false;
    if (panel === 'clip' && !clipRange) clipRange = { start: time, end: Math.min(duration || time + 10, time + 10) };
  }
  $effect(() => {
    if (notes.open) panel = '';
  });

  function flash(text) {
    if (native) return call('mpv_osd', text);   // HTML videonun ustunde gorunmez
    osd = text;
    clearTimeout(osdTimer);
    osdTimer = setTimeout(() => (osd = ''), 1500);
  }

  function shiftSubtitle(delta) {
    const current = timings[ccKey] ?? IDENTITY;
    timings[ccKey] = { ...current, offset: Math.round((current.offset + delta) * 1000) / 1000 };
    flash('Altyazı ' + signed(timings[ccKey].offset));
  }

  function markClip(edge) {
    if (!duration) return;
    const range = clipRange ?? { start: time, end: Math.min(duration, time + 10) };
    if (edge === 'start') clipRange = { start: time, end: range.end > time + 0.1 ? range.end : Math.min(duration, time + 10) };
    else clipRange = { start: range.start < time - 0.1 ? range.start : Math.max(0, time - 10), end: time };
    if (panel !== 'clip') { panel = 'clip'; notes.open = false; }
    flash((edge === 'start' ? 'Başlangıç ' : 'Bitiş ') + fmt(time));
  }

  function preview(start, end) {
    previewEnd = end;
    seekTo(start, true);
  }

  const offSubtool = onSubtool((job) => {
    if (job.path !== p?.path || job.state !== 'done') return;
    if (job.kind === 'ocr') selectSubtitle(job.result.key);
    else if (job.kind === 'whisper' && ccKey === 'whisper') selectSubtitle('whisper');
  });

  // --- notlar (F113) -----------------------------------------------------------
  $effect(() => {
    if (p?.path) loadNotes(p.path);
  });

  function noteHere() {
    if (native) call('mpv_command', 'pause');
    else videoEl?.pause();
    setFullscreen(false);
    startNote(Math.round(time * 10) / 10);
  }

  function mediaError() {
    loading = false;
    const code = videoEl?.error?.code;
    if (code) fail('Video oynatılamadı.');
  }

  // Yedek zinciri: dogrudan -> goruntuyu kopyalayan akis -> GPU ile yeniden kodlanan akis ->
  // islemciyle (x264) yeniden kodlanan akis.
  function fail(message) {
    loading = false;
    if (mode === 'direct') return load(audio, time, playing, true);
    if (!transcode) {
      transcode = true;
      return load(audio, time, playing, true);
    }
    if (encoder && !software) {
      software = true;
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
    if (previewEnd !== null && time >= previewEnd) {
      previewEnd = null;
      videoEl?.pause();
    }
  }

  // --- altyazi ----------------------------------------------------------------
  let ccKey = $state(null);
  let cues = $state([]);
  let cueStarts = [];
  const ccLabel = $derived(ccKey === 'whisper' ? (p?.whisper || 'Whisper') : (p?.subtitles?.find((s) => s.key === ccKey)?.label ?? ''));
  let wordHighlight = $state((() => { try { return localStorage.getItem('aktar.karaoke') !== '0'; } catch { return true; } })());
  // Ekrandaki satirlar; zamanlama duzeltmesi icin video zamani altyazinin kendi zamanina cevrilir.
  // Kelime zamanli (Whisper) satirlarda soylenmis kelimeler vurgulanir.
  const subtitle = $derived.by(() => {
    if (!ccKey || !cues.length) return [];
    const src = (time - timing.offset) / timing.scale;
    let lo = 0, hi = cueStarts.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cueStarts[mid] <= src) lo = mid + 1; else hi = mid; }
    const active = [];
    for (let i = lo - 1; i >= 0; i--) {
      if (cues[i].start < src - 60) break;
      if (src < cues[i].end && !active.some((c) => c.text === cues[i].text)) active.unshift(cues[i]);
    }
    return active.map((cue) => lineTokens(cue, wordHighlight ? src : null));
  });

  function lineTokens(cue, src) {
    const lines = cue.text.split('\n');
    if (src === null || !cue.words?.length) return lines.map((line) => [{ text: line, sung: false }]);
    const starts = cue.words.flatMap((w) => String(w[2]).split(/\s+/).filter(Boolean).map(() => w[0]));
    let k = 0;
    return lines.map((line) => line.split(' ').filter(Boolean).map((text) => ({ text, sung: (starts[k++] ?? Infinity) <= src })));
  }

  async function selectSubtitle(key) {
    if (key?.startsWith('ocr:') && !p?.subtitles?.find((s) => s.key === key)?.ready) {
      if (await act('subtitle_ocr', p.path, Number(key.slice(4)))) toast('Görüntü tabanlı altyazı OCR ile okunuyor; bitince açılır.', 'info');
      return;
    }
    ccKey = key;
    cues = [];
    if (!key) return;
    const result = await act('subtitle_load', key);
    if (!Array.isArray(result) || ccKey !== key) { if (!Array.isArray(result)) ccKey = null; return; }
    cues = result;
    cueStarts = result.map((c) => c.start);
  }

  // mpv: secili altyazi (zamanlama duzeltmesi ve karaoke vurgusuyla) mpv'ye verilir; kisa beklemeyle.
  let subTimer;
  $effect(() => {
    if (!native || !p?.path) return;
    const args = [p.path, ccKey, $state.snapshot(timing), wordHighlight];
    clearTimeout(subTimer);
    subTimer = setTimeout(() => act('mpv_subtitle', ...args), ccKey ? 250 : 0);
  });

  const offWhisper = on('whisper_ready', ({ path }) => {
    if (path === p?.path) selectSubtitle('whisper');
  });

  function ccMenu(event) {
    const items = [{ label: 'Kapalı', icon: ccKey ? null : 'check', action: () => selectSubtitle(null) }];
    const subs = p?.subtitles;
    const streams = (subs ?? []).filter((s) => s.kind === 'stream');
    const images = (subs ?? []).filter((s) => s.kind === 'image');
    const files = (subs ?? []).filter((s) => s.kind === 'file');
    for (const [title, list] of [['Videodaki altyazılar', streams], ['Video klasöründeki dosyalar', files]]) {
      if (!list.length) continue;
      items.push('sep', { label: title, disabled: true });
      for (const s of list) items.push({ label: s.label, icon: ccKey === s.key ? 'check' : null, action: () => selectSubtitle(s.key) });
    }
    if (images.length) {
      const reading = subtool.job?.kind === 'ocr' && subtool.job.path === p?.path;
      items.push('sep', { label: 'Görüntü tabanlı (PGS/VobSub)', disabled: true });
      for (const s of images) {
        items.push(s.ready ? { label: s.label, icon: ccKey === s.key ? 'check' : null, action: () => selectSubtitle(s.key) }
          : { label: s.label + (reading ? ' · okunuyor…' : ' · OCR ile oku'), icon: 'image', disabled: reading || !!subtool.job, action: () => selectSubtitle(s.key) });
      }
    }
    items.push('sep', { label: 'Sesten (Whisper)', disabled: true });
    if (p?.whisper) items.push({ label: p.whisper, icon: ccKey === 'whisper' ? 'check' : null, action: () => selectSubtitle('whisper') });
    if (p?.whisper && !p.whisper_words && !subtool.job) items.push({ label: 'Kelime zamanlarını çıkar (karaoke için)', icon: 'mic', action: () => act('whisper_words', p.path, audio) });
    if (p?.transcribing) items.push({ label: 'Konuşmadan metin çıkarılıyor…', disabled: true });
    else if ((p?.audio ?? []).length > 1) {
      for (const track of p.audio) items.push({ label: 'Sesten oluştur · ' + track.label, icon: 'mic', action: () => act('whisper_generate', track.index) });
    } else if (!p?.whisper) items.push({ label: 'Sesten oluştur…', icon: 'mic', action: () => act('whisper_generate', null) });
    if (subs === null) items.push('sep', { label: 'Altyazı akışları okunuyor…', disabled: true });
    if (ccKey) {
      items.push('sep', { label: 'Zamanlama ve dışa aktarma…', icon: 'timer', action: () => { if (panel !== 'sync') openPanel('sync'); } });
      if (cues.some((c) => c.words?.length)) {
        items.push({ label: 'Söylenen kelimeyi vurgula', icon: wordHighlight ? 'check' : null, action: () => {
          wordHighlight = !wordHighlight;
          try { localStorage.setItem('aktar.karaoke', wordHighlight ? '1' : '0'); } catch { /* depo yok */ }
        } });
      }
    }
    openMenu(event, items);
  }

  function audioMenu(event) {
    openMenu(event, [{ label: 'Ses parçası', disabled: true },
      ...p.audio.map((track) => ({ label: track.label, icon: (audio ?? p.audio[0].index) === track.index ? 'check' : null,
        action: () => load(track.index, time, playing) }))]);
  }

  // --- tam ekran ---------------------------------------------------------------
  // Tam ekran (F126/F127): tarayicinin tam ekran API'si kullanici tiklamasi ister; mpv penceresindeki
  // cift tiklama ve tuslar arka uctan geldigi icin reddedilir. Bunun yerine oynatici CSS ile pencereyi
  // kaplar ve pencere ekrana yayilir. Fare durunca kontroller ve imlec gizlenir.
  let idle = $state(false);
  let overControls = false;
  let idleTimer;
  function setFullscreen(on) {
    if (on === fullscreen) return;
    fullscreen = on;
    call('window_fullscreen', on);
    if (native) call('mpv_command', 'cursor', on ? 1500 : 'no');
    if (on) {
      const hint = 'Tam ekrandan çıkmak için Esc tuşuna basın ya da videoya çift tıklayın';
      if (native) call('mpv_osd', hint);
      else flash(hint);
    }
    poke();
  }
  // Dosya incele listesi tek tiklamayla acar: cift tiklamanin ikinci tiklamasi acilan videoya
  // denk gelip tam ekrani tetiklemesin.
  let openedAt = 0;
  const justOpened = () => performance.now() - openedAt < 1200;
  function toggleFullscreen() {
    setFullscreen(!fullscreen);
  }
  function poke() {
    idle = false;
    clearTimeout(idleTimer);
    if (fullscreen) idleTimer = setTimeout(() => { idle = fullscreen && !overControls && !menu.current; }, 2500);
  }

  $effect(() => {
    if (native) { call('mpv_command', 'volume', volume); call('mpv_command', 'mute', muted); }
    else if (videoEl) { videoEl.volume = volume; videoEl.muted = muted; }
  });

  onDestroy(() => {
    clearTimeout(idleTimer);
    if (fullscreen) call('window_fullscreen', false);
    cancelAnimationFrame(rafId);
    clearTimeout(subTimer);
    offMpv();
    offKeys();
    if (native) call('mpv_hide');
    feed?.stop();
    if (p?.path) app.playerPositions[p.path] = time;
    offWhisper();
    offSubtool();
    clearTimeout(osdTimer);
  });
</script>

<svelte:window onkeydown={keydown} />


<section class="page">
  {#if p}
    <div class="page-head">
      <h1 class="ellipsis title" title={p.path}>{p.name}</h1>
      <button class="btn sm" onclick={() => act('reveal', p.path)}><Icon name="folderOpen" size={14} />Konumu aç</button>
    </div>
    <div class="page-body body">
      <div class="player card" class:full={fullscreen} class:idle={fullscreen && idle} bind:this={shell} role="presentation" onmousemove={poke}>
        <div class="surface" role="presentation" bind:this={surface} onclick={toggle} ondblclick={() => !justOpened() && toggleFullscreen()}>
          <!-- svelte-ignore a11y_media_has_caption -->
          <video class:hidden={native} bind:this={videoEl} preload="auto" onloadedmetadata={metadata} ontimeupdate={timeupdate}
            onplay={() => (playing = true)} onpause={() => (playing = false)} onwaiting={stalled}
            onplaying={resumed} oncanplay={() => (loading = false)} onerror={mediaError}></video>
          {#if subtitle.length && !native}
            <div class="subtitle">
              {#each subtitle as lines, c}
                {#each lines as tokens, l}{#if c || l}<br />{/if}{#each tokens as token, t}{t ? ' ' : ''}<span class:sung={token.sung}>{token.text}</span>{/each}{/each}
              {/each}
            </div>
          {/if}
          {#if osd}<div class="osd mono">{osd}</div>{/if}
          {#if native && covered}<div class="covered">Video, açık menü ya da pencere kapanınca görünür</div>{/if}
          {#if loading && !error && !native}<div class="spinner"><Icon name="loader" size={34} spin /></div>{/if}
          {#if error}<div class="error">{error}</div>{/if}
        </div>
        <div class="controls" role="presentation" onmouseenter={() => (overControls = true)} onmouseleave={() => { overControls = false; poke(); }}>
          <div class="bar" bind:this={bar} role="slider" tabindex="-1" aria-valuenow={time} aria-valuemin="0" aria-valuemax={duration}
            onmousedown={barDown} onmousemove={barMove} onmouseleave={() => (hover = null)}>
            {#each segments as seg}
              <div class="seg" style:left="{(seg.start / (duration || 1)) * 100}%" style:width="calc({((seg.end - seg.start) / (duration || 1)) * 100}% - 3px)">
                <i class="hov" style:width="{hover ? Math.max(0, Math.min(1, (hover.time - seg.start) / (seg.end - seg.start))) * 100 : 0}%"></i>
                <i class="done" style:width="{Math.max(0, Math.min(1, (time - seg.start) / (seg.end - seg.start))) * 100}%"></i>
              </div>
            {/each}
            {#if notes.path === p.path}
              {#each notes.items as note (note.id)}
                <span class="pin" style:left="{(note.at / (duration || 1)) * 100}%" style:background={NOTE_COLORS[note.color]}></span>
              {/each}
            {/if}
            {#if clipRange && panel === 'clip'}
              <span class="range" style:left="{(clipRange.start / (duration || 1)) * 100}%"
                style:width="{((clipRange.end - clipRange.start) / (duration || 1)) * 100}%"></span>
            {/if}
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
            {#if native}<span class="badge" class:ok={hwdec && hwdec !== 'no'} title={hwdec && hwdec !== 'no'
              ? `Gömülü mpv oynatıcı; görüntü ekran kartında çözülüyor (${hwdec}).`
              : 'Gömülü mpv oynatıcı; görüntü işlemcide çözülüyor (donanım çözücüsü kullanılamadı).'}>mpv · {hwdec && hwdec !== 'no' ? 'donanım' : 'işlemci'}{codec ? ' · ' + codec.toUpperCase() : ''}</span>
            {:else if mode === 'direct'}<span class="badge" title={`Video dönüştürülmeden oynatılıyor; görüntüyü WebView kendisi çözüyor${codec === 'hevc'
              ? " (Windows'un HEVC çözücüsüyle). Takılıyorsa Ayarlar → Video oynatma → \"HEVC'yi WebView ile doğrudan oynat\"ı kapatın" : ''}.`}>doğrudan{codec ? ' · ' + codec.toUpperCase() : ''}</span>
            {:else}<span class="badge" title={encoderLabel
              ? `Video tarayıcının çözemediği bir biçimde; ffmpeg ile anında H.264'e dönüştürülüyor (${encoderLabel}). Ayarlar → Video oynatma'dan değiştirilebilir.`
              : 'Video tarayıcının doğrudan çalamadığı bir kapta; görüntü dönüştürülmeden ffmpeg ile paketleniyor.'}>{encoderLabel ? (encoder ? 'GPU ile dönüştürülerek' : 'işlemciyle dönüştürülerek') : 'paketlenerek'}</span>{/if}
            {#if subtool.job?.path === p.path}
              <span class="badge accent job" title="Altyazı/klip işi sürüyor">{jobText(subtool.job)}</span>
            {/if}
            <button class="icon-btn sm" class:on={panel === 'clip'} title="Klip (I / O: başlangıç / bitiş)" onclick={() => openPanel('clip')}><Icon name="scissors" size={16} /></button>
            <button class="icon-btn sm" class:on={panel === 'sync'} disabled={!ccKey} title={ccKey ? 'Altyazı zamanlaması ve dışa aktarma (G / H: ±0,1 sn)' : 'Önce bir altyazı seçin'}
              onclick={() => openPanel('sync')}><Icon name="timer" size={16} /></button>
            <button class="icon-btn sm" title="Bu ana not ekle (N)" onclick={noteHere}><Icon name="squarePen" size={16} /></button>
            <button class="icon-btn sm" class:on={notes.open} title="Notlar" onclick={() => (notes.open = !notes.open)}><Icon name="list" size={18} /></button>
            {#if (p.audio ?? []).length > 1}
              <button class="icon-btn sm" title="Ses parçası" onclick={audioMenu}><Icon name="headphones" size={18} /></button>
            {/if}
            <button class="icon-btn sm" class:on={ccKey} title="Altyazılar" onclick={ccMenu}><Icon name="subtitles" size={18} /></button>
            <button class="icon-btn sm" title="Tam ekran (F)" onclick={toggleFullscreen}><Icon name={fullscreen ? 'shrink' : 'expand'} size={16} /></button>
          </div>
        </div>
      </div>
      {#if notes.open && notes.path === p.path}
        <div class="notes-wrap"><NotesPanel path={p.path} current={time} onjump={(at) => seekTo(at)} /></div>
      {:else if panel === 'sync' && ccKey}
        <div class="notes-wrap tools">
          <SyncPanel path={p.path} source={ccKey} label={ccLabel} {cues} {time} whisper={ccKey === 'whisper'} {audio}
            bind:timing={() => timing, (value) => (timings[ccKey] = value)}
            onjump={(at) => seekTo(at)} onexport={() => (exporting = true)} onclose={() => (panel = '')} />
        </div>
      {:else if panel === 'clip' && clipRange}
        <div class="notes-wrap tools">
          <ClipPanel path={p.path} {time} {duration} bind:clip={clipRange} source={ccKey} sourceLabel={ccLabel} {cues} {timing} {audio}
            onpreview={preview} onseek={(at) => seekTo(at)} onclose={() => (panel = '')} />
        </div>
      {/if}
    </div>
  {/if}
</section>

{#if exporting && p && ccKey}
  <SubtitleExportModal path={p.path} source={ccKey} label={ccLabel} {timing} {audio} onclose={() => (exporting = false)} />
{/if}

<style>
  .title { font-size: 24px !important; }
  .body { display: flex; flex-direction: column; gap: 10px; }
  .player { overflow: hidden; display: flex; flex-direction: column; flex: 1; min-height: 0; background: #000; border-color: var(--outline); }
  .player.full { position: fixed; inset: 0; z-index: 45; border: 0; border-radius: 0; }
  .player.full.idle { cursor: none; }
  .player.full.idle .controls { display: none; }
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
  /* Ipucu cubugun altinda: ustunde kalsa gomulu video (mpv) penceresinin arkasinda kalir. */
  .tip { position: absolute; top: 20px; transform: translateX(-50%); white-space: nowrap; font-size: 12px; background: var(--overlay); color: var(--text);
    border: 1px solid var(--outline); padding: 3px 8px; border-radius: 6px; pointer-events: none; box-shadow: 0 4px 14px var(--shadow); }
  .row { display: flex; align-items: center; gap: 6px; }
  .play { width: 36px; height: 36px; border-radius: 50%; background: var(--text); color: var(--window); display: grid; place-items: center; }
  .play:hover { transform: scale(1.05); }
  .volume { width: 90px; accent-color: var(--accent); }
  .time { font-size: 12px; color: var(--secondary); margin-left: 8px; }
  .chapter { font-size: 12px; color: var(--secondary); background: var(--surface); padding: 3px 10px; border-radius: 999px; max-width: 260px; }
  .grow { flex: 1; }
  .icon-btn.on { color: var(--accent); }
  .pin { position: absolute; top: 2px; width: 4px; height: 14px; margin-left: -2px; border-radius: 2px; pointer-events: none; box-shadow: 0 0 0 1px var(--panel); }
  .notes-wrap { flex: none; height: 34%; min-height: 150px; display: flex; flex-direction: column; }
  .notes-wrap > :global(.notes) { flex: 1; }
  video.hidden { display: none; }
  .covered { position: absolute; color: rgba(255, 255, 255, .6); font-size: 13px; pointer-events: none; }
  .notes-wrap.tools { height: auto; max-height: 46%; min-height: 0; }
  .notes-wrap.tools > :global(.card) { flex: 1; }
  .subtitle .sung { color: #ffd400; }
  .osd { position: absolute; top: 14px; right: 16px; padding: 4px 10px; border-radius: 6px; background: rgba(0, 0, 0, .65); color: #fff; font-size: 13px; pointer-events: none; }
  .range { position: absolute; top: 4px; height: 10px; border-radius: 3px; pointer-events: none;
    background: color-mix(in srgb, var(--accent) 30%, transparent); box-shadow: inset 2px 0 var(--accent), inset -2px 0 var(--accent); }
  .job { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
</style>
