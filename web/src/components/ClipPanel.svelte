<script>
  // Klip kaydetme (F118): giris/cikis noktalari (I / O), satira ve kelimeye hizalama, onizleme ve
  // bicim / kesim / kalite / cozunurluk / altyazi secenekleri. Kayit arka planda FFmpeg ile yapilir.
  import { onDestroy } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { act, app, savePref } from '../lib/state.svelte.js';
  import { subtool, onSubtool, jobText, jobPercent, cancelJob, timingText, isIdentity, clockTenths, parseClock } from '../lib/subtools.svelte.js';

  // clip: {start, end} (bindable); cues: secili altyazinin ozgun zamanli satirlari (words: Whisper)
  let { path, time = 0, duration = 0, clip = $bindable(), source = null, sourceLabel = '', cues = [],
    timing = { scale: 1, offset: 0 }, audio = null, onpreview, onseek, onclose } = $props();

  const saved = app.prefs.clip ?? {};   // son klip secenekleri (ui.json)
  let opts = $state({ format: 'mp4', mode: 'precise', quality: 'high', height: 0, subtitles: 'none', font_size: 64, ...saved.opts });
  let subFormat = $state(saved.subFormat ?? 'source');
  let style = $state({ color: '#FFD400', base: '#FFFFFF', size: 64, mode: 'kf', ...saved.style });
  let saveTimer;
  $effect(() => {
    const value = $state.snapshot({ opts, subFormat, style });
    if (JSON.stringify(value) === JSON.stringify(app.prefs.clip ?? null)) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => savePref({ clip: value }), 500);
  });

  // Altyazi kaynaginin bicimleri (Whisper'da karaoke / kelime vurgulu da var).
  let info = $state(null);
  let refresh = $state(0);
  let infoKey = '';
  $effect(() => {
    const key = source, stamp = `${source}|${refresh}`;
    if (stamp === infoKey) return;
    infoKey = stamp;
    info = null;
    if (key) act('subtitle_info', path, key).then((r) => { if (infoKey === stamp) info = r; });
  });
  const off = onSubtool((job) => {
    if (job.kind === 'whisper' && job.path === path && job.state === 'done') refresh += 1;
  });
  onDestroy(off);
  const subFormats = $derived((info?.formats ?? []).filter((f) => f.id !== 'json'
    && (opts.subtitles === 'file' || ['source', 'srt', 'ass', 'karaoke', 'highlight'].includes(f.id))));
  $effect(() => {
    if (subFormats.length && !subFormats.some((f) => f.id === subFormat)) subFormat = subFormats[0].id;
  });
  const wordFormat = $derived(!!subFormats.find((f) => f.id === subFormat)?.words);
  const needsWords = $derived(opts.subtitles !== 'none' && wordFormat && !info?.words);

  const video = $derived(opts.format !== 'm4a');
  const reencode = $derived(opts.format === 'gif' || opts.format === 'm4a' || opts.subtitles === 'burn' || !!opts.height);
  const mode = $derived(reencode ? 'precise' : opts.mode);
  const length = $derived(Math.max(0, clip.end - clip.start));
  const busy = $derived(subtool.job?.path === path ? subtool.job : null);
  const saving = $derived(busy?.kind === 'clip');
  const HEIGHTS = $derived(opts.format === 'gif' ? [[0, '360p'], [480, '480p'], [240, '240p']] : [[0, 'Özgün'], [1080, '1080p'], [720, '720p'], [480, '480p']]);
  const SUBS = [['none', 'Yok'], ['file', 'Ayrı dosya'], ['embed', 'Gömülü (aç/kapa)'], ['burn', 'Görüntüye yak']];
  const subAllowed = (id) => id === 'none' || (!!source && !(opts.format === 'm4a' && (id === 'embed' || id === 'burn'))
    && !(opts.format === 'gif' && id === 'embed'));

  function set(edge, value) {
    value = Math.max(0, Math.min(duration || value, value));
    if (edge === 'start') clip = { start: value, end: Math.max(clip.end, value + 0.1) };
    else clip = { start: Math.min(clip.start, Math.max(0, value - 0.1)), end: value };
  }

  function typed(edge, event) {
    const value = parseClock(event.currentTarget.value);
    if (value === null) event.currentTarget.value = clockTenths(clip[edge]);
    else set(edge, value);
  }

  // Altyazi zamanlari (duzeltme uygulanmis).
  const mapped = $derived(cues.map((c) => ({ start: c.start * timing.scale + timing.offset, end: c.end * timing.scale + timing.offset, words: c.words })));
  const words = $derived(mapped.flatMap((c) => (c.words ?? []).map((w) => [w[0] * timing.scale + timing.offset, w[1] * timing.scale + timing.offset])));

  function snapLines() {
    if (!mapped.length) return;
    const atStart = mapped.find((c) => c.start <= clip.start && clip.start < c.end)
      ?? mapped.find((c) => c.start >= clip.start - 0.05);
    const atEnd = [...mapped].reverse().find((c) => c.start < clip.end && clip.end <= c.end + 0.05)
      ?? [...mapped].reverse().find((c) => c.end <= clip.end + 0.05);
    const start = atStart ? atStart.start : clip.start;
    const end = atEnd && atEnd.end > start ? atEnd.end : clip.end;
    clip = { start: Math.max(0, start - 0.05), end: Math.min(duration || end, end + 0.15) };
  }

  function snapWords() {
    if (!words.length) return;
    const near = (value, pick) => words.reduce((best, w) => (Math.abs(pick(w) - value) < Math.abs(pick(best) - value) ? w : best));
    const start = near(clip.start, (w) => w[0])[0];
    const end = near(clip.end, (w) => w[1])[1];
    if (end > start) clip = { start: Math.max(0, start - 0.05), end: Math.min(duration || end, end + 0.1) };
  }

  async function save() {
    const options = { ...opts, mode, audio };
    await act('clip_save', path, clip.start, clip.end, options, opts.subtitles === 'none' ? null : source, timing, subFormat, style);
  }
</script>

<div class="clip card">
  <div class="head">
    <Icon name="scissors" size={16} />
    <strong>Klip</strong>
    <span class="dim">I: başlangıç · O: bitiş</span>
    <span class="grow"></span>
    <button class="icon-btn sm" title="Kapat" onclick={onclose}><Icon name="x" size={16} /></button>
  </div>

  <div class="body">
    <div class="col">
      <div class="range">
        {#each [['start', 'Başlangıç'], ['end', 'Bitiş']] as [edge, title]}
          <div class="edge">
            <span class="label">{title}</span>
            <div class="line">
              <button class="icon-btn sm" title="−0,1 sn" onclick={() => set(edge, clip[edge] - 0.1)}><Icon name="back" size={14} /></button>
              <input class="field mono" value={clockTenths(clip[edge])} onchange={(e) => typed(edge, e)} onkeydown={(e) => e.stopPropagation()} />
              <button class="icon-btn sm" title="+0,1 sn" onclick={() => set(edge, clip[edge] + 0.1)}><Icon name="forward" size={14} /></button>
              <button class="btn sm ghost" title="Şu anki konum ({edge === 'start' ? 'I' : 'O'})" onclick={() => set(edge, time)}>Şu an</button>
              <button class="btn sm ghost" title="Bu noktaya git" onclick={() => onseek?.(clip[edge])}><Icon name="eye" size={14} /></button>
            </div>
          </div>
        {/each}
      </div>
      <div class="line">
        <span class="badge accent mono">Süre {clockTenths(length)}</span>
        <button class="btn sm" onclick={() => onpreview?.(clip.start, clip.end)}><Icon name="play" size={12} />Önizle</button>
        <button class="btn sm ghost" disabled={!mapped.length} onclick={snapLines} title="Başlangıç ve bitişi altyazı satırlarının sınırlarına genişletir">
          <Icon name="subtitles" size={14} />Satıra hizala</button>
        <button class="btn sm ghost" disabled={!words.length} onclick={snapWords} title={words.length ? 'En yakın kelime sınırlarına hizalar (Whisper kelime zamanları)' : 'Kelime zamanları için CC menüsünden Whisper altyazısını seçin'}>
          <Icon name="mic" size={14} />Kelimeye hizala</button>
      </div>
      {#if saving}
        <div class="line progress">
          <Icon name="loader" spin size={16} />
          <span class="grow">{jobText(busy)}</span>
          <button class="btn sm ghost" onclick={cancelJob}>Durdur</button>
        </div>
        <div class="track"><i style:width="{jobPercent(busy)}%"></i></div>
      {/if}
    </div>

    <div class="col opts">
      <div class="opt">
        <span class="label">Biçim</span>
        <div class="chips">
          {#each [['mp4', 'MP4'], ['mkv', 'MKV'], ['gif', 'GIF'], ['m4a', 'Yalnız ses']] as [id, text]}
            <button class="chip" class:on={opts.format === id} onclick={() => { opts.format = id; opts.height = 0; }}>{text}</button>
          {/each}
        </div>
      </div>
      {#if video}
        <div class="opt">
          <span class="label">Kesim</span>
          <div class="chips">
            <button class="chip" class:on={mode === 'fast'} disabled={reencode} onclick={() => (opts.mode = 'fast')}
              title="Yeniden kodlamadan, saniyeler içinde; başlangıç bir önceki anahtar kareye kayabilir">Hızlı</button>
            <button class="chip" class:on={mode === 'precise'} onclick={() => (opts.mode = 'precise')}
              title="H.264 ile yeniden kodlanır; kare hassasiyetinde">Hassas</button>
          </div>
          {#if mode === 'precise' && opts.format !== 'gif'}
            <select class="field" bind:value={opts.quality} title="Kalite (CRF 18 / 23 / 28)">
              <option value="high">Yüksek kalite</option><option value="medium">Orta</option><option value="small">Küçük dosya</option>
            </select>
          {/if}
          <select class="field" value={String(opts.height)} onchange={(e) => (opts.height = Number(e.currentTarget.value))} title="Çözünürlük (yalnızca küçültür)">
            {#each HEIGHTS as [value, text]}<option value={String(value)}>{text}</option>{/each}
          </select>
        </div>
      {/if}
      <div class="opt">
        <span class="label">Altyazı</span>
        <div class="chips">
          {#each SUBS as [id, text]}
            <button class="chip" class:on={opts.subtitles === id} disabled={!subAllowed(id)} onclick={() => (opts.subtitles = id)}>{text}</button>
          {/each}
        </div>
      </div>
      {#if opts.subtitles !== 'none'}
        <div class="opt">
          <span class="label"></span>
          <span class="dim ellipsis srcname" title={sourceLabel}>{sourceLabel}</span>
          <select class="field" bind:value={subFormat} disabled={!info}>
            {#each subFormats as f}<option value={f.id}>{f.id === 'source' ? 'Kaynağın biçimi' : f.label}</option>{/each}
          </select>
          {#if subFormat === 'karaoke' || subFormat === 'highlight'}
            <input type="color" bind:value={style.color} title="Vurgu rengi" />
          {/if}
        </div>
        {#if opts.subtitles === 'burn'}
          <div class="opt">
            <span class="label"></span>
            <label class="size" title="1080p görüntüdeki piksel yüksekliği; klip küçültülürse orantılı küçülür">Yazı boyutu
              <input type="range" min="24" max="140" step="2" bind:value={opts.font_size} />
              <span class="mono">{opts.font_size}</span></label>
            {#if subFormat !== 'highlight'}
              <label class="size" title={subFormat === 'karaoke' ? 'Henüz söylenmeyen kelimelerin rengi' : 'Yazı rengi'}>Yazı rengi
                <input type="color" bind:value={style.base} /></label>
            {/if}
          </div>
          {#if subFormat === 'source' && /(\.|· )(ass|ssa)$/i.test(sourceLabel)}
            <p class="note">Kaynağın biçimi seçiliyse ASS dosyasının kendi stili kullanılır; boyut için “ASS”i seçin.</p>
          {/if}
        {/if}
        <p class="note">
          {#if !isIdentity(timing)}Zamanlama düzeltmesi ({timingText(timing)}) klibe de uygulanır. {/if}
          {#if opts.subtitles === 'embed' && opts.format === 'mp4'}MP4'te gömülü altyazı düz metindir; karaoke renkleri için MKV seçin ya da görüntüye yakın.{/if}
          {#if opts.subtitles === 'burn'}Yakılan altyazı her oynatıcıda görünür, kapatılamaz.{/if}
        </p>
        {#if needsWords}
          <div class="opt">
            <span class="label"></span>
            <span class="note inline">Bu biçim kelime zamanları ister.</span>
            <button class="btn sm" disabled={!!busy} onclick={() => act('whisper_words', path, audio)}><Icon name="mic" size={14} />Kelime zamanlarını çıkar</button>
          </div>
        {/if}
      {:else if !source}
        <p class="note">Altyazı eklemek için önce CC menüsünden bir altyazı seçin.</p>
      {/if}
    </div>
  </div>

  <div class="foot">
    <span class="dim">{mode === 'fast' ? 'Hızlı kesim: saniyeler sürer.' : 'Hassas kesim: video yeniden kodlanır, süreye göre biraz zaman alır.'}</span>
    <span class="grow"></span>
    <button class="btn primary" disabled={length < 0.1 || saving || !!(busy && !saving) || needsWords} onclick={save}>
      <Icon name="scissors" size={16} />Klibi kaydet…</button>
  </div>
</div>

<style>
  .clip { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 14px; border-bottom: 1px solid var(--outline); color: var(--secondary); }
  .head strong { color: var(--text); }
  .head .dim { font-size: 12px; }
  .grow { flex: 1; }
  .body { display: grid; grid-template-columns: minmax(310px, 1fr) minmax(330px, 1.2fr); gap: 18px; padding: 12px 14px; overflow: auto; min-height: 0; flex: 1; }
  .col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .range { display: flex; flex-direction: column; gap: 8px; }
  .edge { display: flex; align-items: center; gap: 6px; }
  .edge .label { width: 70px; flex: none; }
  .edge .line { flex-wrap: nowrap; gap: 2px; }
  .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .edge input { width: 84px; height: 30px; text-align: center; }
  .progress { font-size: 13px; }
  .opt { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .opt .label { width: 64px; flex: none; }
  .chips { display: flex; gap: 4px; flex-wrap: wrap; }
  .chips .chip { height: 28px; padding: 0 11px; font-size: 12.5px; }
  .chip:disabled { opacity: .4; }
  select.field { height: 30px; }
  .srcname { font-size: 12px; max-width: 160px; }
  input[type='color'] { width: 40px; height: 28px; border: 1px solid var(--field-border); border-radius: 8px; background: var(--surface); padding: 2px; cursor: pointer; }
  .note { font-size: 11.5px; color: var(--dim); line-height: 1.5; margin: 0 0 0 72px; }
  .note:empty { display: none; }
  .size { display: inline-flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--secondary); }
  .size input[type='range'] { width: 120px; accent-color: var(--accent); }
  .size .mono { width: 28px; color: var(--text); }
  .note.inline { margin: 0; }
  .foot { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-top: 1px solid var(--outline); font-size: 12px; }
</style>
