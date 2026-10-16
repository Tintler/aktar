<script>
  // Altyaziyi disa aktarma (F118): bicim (kaynak / SRT / ASS / VTT; Whisper'da karaoke ve kelime
  // zamanli bicimler), karaoke stili ve uygulanacak zamanlama duzeltmesi. Oynatici ve Altyazi Cevir paylasir.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import { act } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { subtool, onSubtool, jobText, jobPercent, cancelJob, timingText, isIdentity } from '../lib/subtools.svelte.js';
  import { onDestroy } from 'svelte';

  // timing: {scale, offset} ya da null; audio: Whisper'in calisacagi ses akisi (oynatici)
  let { path, source, label = '', timing = null, audio = null, onclose } = $props();

  let info = $state(null);
  let fmt = $state('source');
  let style = $state({ color: '#FFD400', base: '#FFFFFF', size: 64, mode: 'kf' });
  let saving = $state(false);

  async function load() {
    const result = await act('subtitle_info', path, source);
    if (!result) return onclose();
    info = result;
    style = { ...result.style };
    if (!result.formats.some((f) => f.id === fmt)) fmt = result.formats[0].id;
  }
  load();

  const current = $derived(info?.formats.find((f) => f.id === fmt));
  const needsWords = $derived(!!current?.words && !info?.words);
  const styled = $derived(fmt === 'karaoke' || fmt === 'highlight');
  const busy = $derived(subtool.job?.path === path ? subtool.job : null);
  const HINTS = {
    source: 'Kaynağın kendi biçimi; ASS stilleri ve etiketleri korunur.',
    srt: 'En yaygın biçim; hemen her oynatıcı ve kurgu programı açar.',
    ass: 'Stilli altyazı (VLC, mpv, MPC-HC).',
    vtt: 'Web ve tarayıcı oynatıcıları için.',
    karaoke: 'Her kelime söylendiği anda renk değiştirir (\\k etiketleri). VLC, mpv, MPC-HC ve libass kullanan oynatıcılarda çalışır.',
    highlight: 'Her kelime için ayrı satır; o anki kelime renkli (<font color>). Karaoke desteklemeyen oynatıcılar için.',
    vtt_words: 'Satır içinde kelime zaman damgaları (<00:00:01.400>); tarayıcılar ve bazı kurgu araçları okur.',
    words_srt: 'Her kelime ayrı SRT satırı; dikey/kısa video kurgusu için.',
    json: 'Kelime kelime başlangıç-bitiş zamanları; başka araçlarda işlemek için.',
  };

  const off = onSubtool((job) => {
    if (job.kind === 'whisper' && job.path === path && job.state === 'done') load();
  });
  onDestroy(off);

  async function extractWords() {
    await act('whisper_words', path, audio);
  }

  async function save() {
    saving = true;
    const result = await act('subtitle_export', path, source, fmt, timing, style);
    saving = false;
    if (result?.path) {
      onclose();
      if (await confirm({ title: 'Altyazı kaydedildi', message: result.path, ok: 'Konumu aç', cancel: 'Kapat' })) act('reveal', result.path);
    }
  }
</script>

<Modal title="Altyazıyı dışa aktar" width={560} {onclose}>
  {#if !info}
    <div class="empty"><Icon name="loader" spin /> Altyazı okunuyor…</div>
  {:else}
    <div class="row"><span class="label">Kaynak</span><span class="ellipsis">{label || source}</span></div>
    <div class="row">
      <span class="label">Zamanlama</span>
      <span class:accent={!isIdentity(timing)}>{timingText(timing)}{isIdentity(timing) ? '' : ' uygulanacak'}</span>
    </div>
    <label class="stack">
      <span class="label">Biçim</span>
      <select class="field" bind:value={fmt}>
        {#each info.formats as f}<option value={f.id}>{f.label}</option>{/each}
      </select>
      <span class="hint">{HINTS[fmt] ?? ''}</span>
    </label>

    {#if needsWords}
      <div class="warn">
        <Icon name="info" size={16} />
        <div class="grow">Bu transkript kelime zamanları tutulmadan çıkarılmış. Whisper bir kez daha çalıştırılır; sonuç önbelleğe yazılır.</div>
        {#if busy}
          <span class="mono dim">{jobText(busy)}</span>
          <button class="btn sm ghost" onclick={cancelJob}>Durdur</button>
        {:else}
          <button class="btn sm" onclick={extractWords}><Icon name="mic" size={14} />Kelime zamanlarını çıkar</button>
        {/if}
      </div>
      {#if busy}<div class="track"><i style:width="{jobPercent(busy)}%"></i></div>{/if}
    {/if}

    {#if styled}
      <div class="style">
        <label><span class="label">Vurgu rengi</span><input type="color" bind:value={style.color} /></label>
        {#if fmt === 'karaoke'}
          <label><span class="label">Henüz söylenmeyen</span><input type="color" bind:value={style.base} /></label>
          <label><span class="label">Yazı boyutu</span><input class="field num" type="number" min="20" max="160" bind:value={style.size} /></label>
          <label><span class="label">Geçiş</span>
            <select class="field" bind:value={style.mode}><option value="kf">Akarak dolar (\kf)</option><option value="k">Kelime kelime (\k)</option></select></label>
        {/if}
      </div>
      <div class="preview" style:--hi={style.color} style:--base={fmt === 'karaoke' ? style.base : '#ffffff'}>
        <span class="sung">Merhaba</span> <span class="sung">nasıl</span> <span class:half={fmt === 'karaoke' && style.mode === 'kf'} class:now={fmt === 'highlight' || style.mode === 'k'}>gidiyor</span> <span>bugün?</span>
      </div>
    {/if}
  {/if}
  {#snippet footer()}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={!info || needsWords || saving} onclick={save}><Icon name="download" size={16} />Kaydet…</button>
  {/snippet}
</Modal>

<style>
  .row { display: flex; align-items: baseline; gap: 12px; font-size: 13px; }
  .row .label { width: 92px; flex: none; }
  .accent { color: var(--accent); }
  .stack { display: flex; flex-direction: column; gap: 6px; }
  .hint { font-size: 12px; color: var(--dim); line-height: 1.5; }
  .warn { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; font-size: 12.5px; line-height: 1.5;
    background: color-mix(in srgb, var(--warning) 12%, transparent); color: var(--text); }
  .warn :global(svg) { color: var(--warning); flex: none; }
  .grow { flex: 1; }
  .style { display: flex; flex-wrap: wrap; gap: 14px; }
  .style label { display: flex; flex-direction: column; gap: 6px; }
  input[type='color'] { width: 56px; height: 32px; border: 1px solid var(--field-border); border-radius: 8px; background: var(--surface); padding: 2px; cursor: pointer; }
  .num { width: 84px; }
  .preview { padding: 18px 12px; border-radius: 10px; background: #000; text-align: center; font-size: 22px; font-weight: 700; color: var(--base);
    text-shadow: 0 0 3px #000, 0 0 3px #000; }
  .preview .sung, .preview .now { color: var(--hi); }
  .preview .half { background: linear-gradient(90deg, var(--hi) 55%, var(--base) 55%); -webkit-background-clip: text; background-clip: text; color: transparent; text-shadow: none; }
</style>
