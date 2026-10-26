<script>
  // F208 Sesli kitabi kaydet: bicim (MP4 video / M4B / MP3), hangi sesle (her sesle kitabin ne kadari hazir) ve
  // videoda tam ekran okuyucunun gorunumu (arka plan, yazi, gecisler, renk, boyut). Onizleme Python'un cizdigi
  // gercek kareden (tts_video_preview): videoda ne gorunecekse o. Secimler ui.json reader.audiobook'ta kalir.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { app, saveReaderPrefs, READER_DEFAULTS } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { FOCUS_COLORS, resolvePaper } from '../lib/focus.js';

  // collect(): kitabin bolumleri (okuyucunun bolmesiyle); onsave({fmt, voice, video, chapters}): kaydi baslatir.
  let { book, paper = null, section = 0, sample = '', collect, onsave, onclose } = $props();

  const hasArt = Boolean(app.artBooks[book.id]?.images);
  const saved = app.reader.audiobook ?? {};
  const focus = {
    background: hasArt ? 'art' : 'plain',
    text: true,
    motion: app.reader.focus_motion ?? 'slide',
    art_motion: 'fade',
    size: app.reader.focus_size ?? READER_DEFAULTS.focus_size,
    colors: app.reader.focus_colors ?? 'paper',
    band: app.reader.focus_band ?? READER_DEFAULTS.focus_band,
    font: app.reader.font === 'sans' ? 'sans' : 'serif',
    height: 1080,
  };
  let fmt = $state(saved.fmt ?? 'mp4');
  let video = $state({ ...focus, ...(saved.video ?? {}) });
  if (!hasArt && video.background === 'art') video.background = 'plain';

  let chapters = $state(null);
  let voices = $state(null);
  let voice = $state(undefined);     // secilen sesin anahtari (null: okuyucunun sesi)
  let failed = $state('');
  let starting = $state(false);

  async function load() {
    try {
      chapters = await collect();
      if (!chapters.length) { failed = 'Kitapta seslendirilecek metin yok.'; return; }
      const list = await call('tts_audiobook_voices', chapters, app.ttsPrefs.speed, book.id, book.language || 'tr');
      if (!Array.isArray(list)) { failed = list?.error || 'Sesler okunamadı.'; return; }
      voices = list;
      // en cok hazirlanmis ses one cikar; esitse okuyucunun sesi
      const best = list.reduce((a, b) => (b.count > a.count ? b : a), list[0]);
      voice = best.count > list[0].count ? best.key : list[0].key;
    } catch (error) {
      failed = String(error?.message ?? error);
    }
  }
  load();

  const chosen = $derived(voices?.find((v) => v.key === voice) ?? null);
  const pct = (v) => (v.total ? Math.floor((v.count * 100) / v.total) : 0);

  const resolved = $derived({ ...video, colors: FOCUS_COLORS[video.colors] ?? resolvePaper(paper) });
  let preview = $state('');
  let previewTimer;
  $effect(() => {
    if (fmt !== 'mp4') return;
    const options = $state.snapshot(resolved);
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const result = await call('tts_video_preview', book.id, options, section, sample).catch(() => null);
      if (result?.image) preview = result.image;
    }, 250);
  });

  function remember() {
    app.reader.audiobook = { fmt, video: $state.snapshot(video) };
    saveReaderPrefs();
  }

  async function save() {
    if (!chosen || !chapters) return;
    starting = true;
    remember();
    try {
      await onsave({ fmt, voice: $state.snapshot(chosen), video: fmt === 'mp4' ? $state.snapshot(resolved) : null,
        chapters: $state.snapshot(chapters) });
    } catch (error) {
      failed = 'Kayıt başlatılamadı: ' + (error?.message ?? error);
    } finally {
      starting = false;
    }
  }

  const FORMATS = [
    { id: 'mp4', label: 'Video (MP4)', hint: 'Ses + tam ekran okuyucu: okunan parça ortada, arkada kitap görselleri ya da düz renk.' },
    { id: 'm4b', label: 'M4B', hint: 'Tek dosya, bölümlü ve kapaklı; sesli kitap uygulamaları bölümleri ayrı gösterir.' },
    { id: 'mp3', label: 'MP3 (klasör)', hint: 'Seçilen klasöre bölüm başına bir MP3.' },
  ];
  const SIZE = { min: 24, max: 120, step: 4 };
</script>

<Modal title="Sesli kitabı kaydet" width={fmt === 'mp4' ? 760 : 520} {onclose}>
  <div class="seg wide">
    {#each FORMATS as f}<button class:on={fmt === f.id} onclick={() => (fmt = f.id)}>{f.label}</button>{/each}
  </div>
  <span class="hint">{FORMATS.find((f) => f.id === fmt).hint}</span>

  <div class="block">
    <span class="label">Ses</span>
    {#if failed}
      <div class="warn"><Icon name="alert" size={16} />{failed}</div>
    {:else if !voices}
      <div class="empty"><Icon name="loader" spin /> Kitap okunuyor, hangi sesle ne kadarının hazır olduğuna bakılıyor…</div>
    {:else}
      <div class="voices">
        {#each voices as v (v.key)}
          <button class="voice" class:on={voice === v.key} onclick={() => (voice = v.key)}>
            <span class="dot"></span>
            <span class="name">{v.label}</span>
            <span class="ready" class:full={v.count === v.total} class:none={!v.count}>
              {v.count === v.total ? 'Tamamı hazır' : v.count ? `%${pct(v)} hazır` : 'Hazır değil'}</span>
          </button>
        {/each}
      </div>
      {#if chosen && chosen.count < chosen.total}
        <span class="hint">Eksik {chosen.total - chosen.count} cümle kayıt sırasında bu sesle üretilir (ses motoru
          yüklenir){#if !chosen.current}; okuyucu kayıt bitene kadar bu sesi kullanır, sonra önceki sesine döner{/if}.</span>
      {:else if chosen}
        <span class="hint">Bütün ses hazır: ses motoru yüklenmeden yazılır{#if !chosen.current}, okuyucunun sesi değişmez{/if}.</span>
      {/if}
    {/if}
  </div>

  {#if fmt === 'mp4'}
    <div class="video">
      <div class="shot">
        {#if preview}<img src={preview} alt="Önizleme" />{:else}<div class="empty"><Icon name="loader" spin /></div>{/if}
        <span class="hint">Önizleme: videonun bir karesi. Okunan parça değişince yazı {video.motion === 'slide' ? 'kayar' : video.motion === 'fade' ? 'belirir' : 'birden değişir'}{#if video.background === 'art'}, sahne değişince görsel {video.art_motion === 'fade' ? 'yumuşakça geçer' : 'birden değişir'}{/if}.</span>
      </div>
      <div class="opts">
        <div class="r">Arka plan
          <div class="seg" title={hasArt ? '' : 'Bu kitabın görseli yok: kitaplıkta kitaba sağ tıklayıp "Kitap görselleri oluştur"'}>
            <button class:on={video.background === 'plain'} onclick={() => (video.background = 'plain')}>Düz</button>
            <button class:on={video.background === 'art'} disabled={!hasArt} onclick={() => (video.background = 'art')}>Görselli</button>
          </div>
        </div>
        <div class="r">Yazı <Toggle bind:checked={video.text} /></div>
        {#if video.text}
          <div class="r">Yazı geçişi
            <div class="seg">
              <button class:on={video.motion === 'slide'} onclick={() => (video.motion = 'slide')}>Kayma</button>
              <button class:on={video.motion === 'fade'} onclick={() => (video.motion = 'fade')}>Belirme</button>
              <button class:on={video.motion === 'none'} onclick={() => (video.motion = 'none')}>Yok</button>
            </div>
          </div>
          <div class="r">Yazı boyutu <span class="val">{video.size}</span></div>
          <input type="range" min={SIZE.min} max={SIZE.max} step={SIZE.step} bind:value={video.size} />
          <div class="r">Yazı tipi
            <div class="seg">
              <button class:on={video.font === 'serif'} onclick={() => (video.font = 'serif')}>Serif</button>
              <button class:on={video.font === 'sans'} onclick={() => (video.font = 'sans')}>Sans</button>
            </div>
          </div>
        {/if}
        {#if video.background === 'art'}
          <div class="r">Görsel geçişi
            <div class="seg">
              <button class:on={video.art_motion === 'fade'} onclick={() => (video.art_motion = 'fade')}>Yumuşak</button>
              <button class:on={video.art_motion === 'cut'} onclick={() => (video.art_motion = 'cut')}>Kesme</button>
            </div>
          </div>
          <div class="r">Yazı bandı <span class="val">%{Math.round(video.band * 100)}</span></div>
          <input type="range" min="0" max="1" step="0.05" bind:value={video.band} title="Ortadaki yazının arkasındaki koyuluk" />
        {/if}
        <div class="r col">Renk
          <div class="swatches">
            {#each Object.entries(FOCUS_COLORS) as [key, value]}
              {@const shown = value ?? resolvePaper(paper)}
              <button class="swatch" class:on={video.colors === key} title={value ? value.label : 'Okuyucunun sayfa rengi'}
                style:background={shown.bg} style:color={shown.ink} onclick={() => (video.colors = key)}>A</button>
            {/each}
          </div>
        </div>
        <div class="r">Çözünürlük
          <div class="seg">
            <button class:on={video.height === 1080} onclick={() => (video.height = 1080)}>1080p</button>
            <button class:on={video.height === 720} onclick={() => (video.height = 720)}>720p</button>
          </div>
        </div>
      </div>
    </div>
    {#if (video.text && video.motion !== 'none') || (video.background === 'art' && video.art_motion === 'fade')}
      <span class="hint">Geçişli video saniyede 25 kare çizilir; uzun bir kitapta görüntü sesten uzun sürebilir (720p yaklaşık iki kat hızlı). Geçişler kapalıyken çok daha hızlıdır.</span>
    {/if}
  {/if}

  {#snippet footer()}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={!chosen || starting} onclick={save}>
      <Icon name={starting ? 'loader' : 'download'} spin={starting} size={16} />Kaydet…</button>
  {/snippet}
</Modal>

<style>
  .label { font-size: 12px; font-weight: 600; color: var(--secondary); }
  .hint { font-size: 12px; color: var(--dim); line-height: 1.5; }
  .block { display: flex; flex-direction: column; gap: 8px; }
  .empty { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--secondary); padding: 8px 0; }
  .warn { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 10px; font-size: 12.5px;
    background: color-mix(in srgb, var(--warning) 12%, transparent); }
  .seg { display: flex; align-items: center; background: var(--surface); border-radius: 999px; padding: 3px; }
  .seg button { padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; color: var(--secondary); }
  .seg button.on { background: var(--surface-active); color: var(--text); }
  .seg button:disabled { opacity: .4; }
  .seg.wide { align-self: flex-start; }
  .seg.wide button { padding: 6px 14px; font-size: 13px; }
  .voices { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow: auto; }
  .voice { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 10px; text-align: left; font-size: 13px; color: var(--secondary); }
  .voice:hover { background: var(--surface); }
  .voice.on { background: var(--surface-active); color: var(--text); }
  .dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--outline); flex: none; }
  .voice.on .dot { border-color: var(--accent); background: var(--accent); }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ready { font-size: 11.5px; font-weight: 600; color: var(--warning); white-space: nowrap; }
  .ready.full { color: var(--accent); }
  .ready.none { color: var(--dim); }
  .video { display: grid; grid-template-columns: 1fr 250px; gap: 16px; align-items: start; }
  .shot { display: flex; flex-direction: column; gap: 6px; }
  .shot img, .shot .empty { width: 100%; aspect-ratio: 16 / 9; border-radius: 8px; background: #000; object-fit: cover; justify-content: center; }
  .opts { display: flex; flex-direction: column; }
  .r { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; font-size: 13px; color: var(--secondary); gap: 10px; }
  .r.col { flex-direction: column; align-items: stretch; }
  .opts input[type='range'] { width: 100%; accent-color: var(--accent); }
  .val { min-width: 30px; text-align: center; font-weight: 700; font-size: 12px; color: var(--text); }
  .swatches { display: flex; flex-wrap: wrap; gap: 6px; }
  .swatch { width: 26px; height: 26px; border-radius: 50%; border: 2px solid var(--outline); font: 600 11px var(--serif); }
  .swatch.on { border-color: var(--accent); }
  @media (max-width: 820px) { .video { grid-template-columns: 1fr; } }
</style>
