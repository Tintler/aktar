<script>
  // Altyazi zamanlamasi (F118): kaydirma, kare hizi duzeltmesi, iki noktadan esitleme ve Whisper ile
  // otomatik hizalama. Duzeltme oynaticida aninda gorunur; disa aktarma ve klip ayni duzeltmeyi kullanir.
  import { onDestroy } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { act, toast } from '../lib/state.svelte.js';
  import { subtool, onSubtool, jobText, jobPercent, cancelJob, RATIOS, signed, timingText, twoPoint, isIdentity } from '../lib/subtools.svelte.js';

  // cues: kaynak altyazinin ozgun zamanlari; timing: {scale, offset} (bindable)
  let { path, source, label = '', cues = [], time = 0, whisper = false, audio = null,
    timing = $bindable({ scale: 1, offset: 0 }), onjump, onexport, onclose } = $props();

  let anchors = $state([]);      // [{src, at, text}] iki noktadan esitleme
  let aligned = $state(null);    // son otomatik hizalamanin sonucu
  let lastSource = '';
  $effect(() => {
    if (source !== lastSource) { lastSource = source; anchors = []; aligned = null; }
  });

  const busy = $derived(subtool.job?.path === path ? subtool.job : null);
  const aligning = $derived(busy?.kind === 'align' || (busy?.kind === 'whisper' && busy?.stage === 'whisper'));
  const src = $derived((time - timing.offset) / timing.scale);
  const fmt = (s) => {
    s = Math.max(0, s || 0);
    const m = Math.floor(s / 60), r = (s % 60).toFixed(1).padStart(4, '0').replace('.', ',');
    return `${m}:${r}`;
  };
  // Su anki konumun cevresindeki satirlar (ozgun zamanlariyla): "Bu satir simdi" icin.
  const nearby = $derived.by(() => {
    const list = cues.filter((c) => c.start >= src - 15 && c.start <= src + 6);
    return list.slice(Math.max(0, list.length - 6));
  });
  const ratio = $derived.by(() => {
    const hit = RATIOS.find(([value]) => Math.abs(value - timing.scale) < 1e-6);
    return hit ? String(hit[0]) : 'custom';
  });

  function nudge(delta) {
    timing = { ...timing, offset: Math.round((timing.offset + delta) * 1000) / 1000 };
  }

  function setOffset(event) {
    const value = Number(String(event.currentTarget.value).replace(',', '.'));
    if (Number.isFinite(value)) timing = { ...timing, offset: value };
  }

  function setRatio(event) {
    const value = Number(event.currentTarget.value);
    if (!Number.isFinite(value)) return;
    // Su an ekrandaki an yerinde kalsin: yeni kaydirma o ani sabitler.
    timing = { scale: value, offset: Math.round((time - src * value) * 1000) / 1000 };
  }

  function anchor(cue) {
    const next = [...anchors.filter((a) => Math.abs(a.src - cue.start) > 0.01), { src: cue.start, at: time, text: cue.text }].slice(-2);
    if (next.length === 2) {
      const solved = twoPoint([next[0].src, next[0].at], [next[1].src, next[1].at]);
      if (!solved) return toast('İki satır birbirine çok yakın ya da hız oranı mantıksız; daha uzak iki satır seçin.', 'error');
      timing = { scale: Math.round(solved.scale * 1e6) / 1e6, offset: Math.round(solved.offset * 1000) / 1000 };
    } else {
      timing = { ...timing, offset: Math.round((time - cue.start * timing.scale) * 1000) / 1000 };
    }
    anchors = next;
  }

  async function autoAlign() {
    aligned = null;
    await act('subtitle_align', path, source, audio);
  }

  const off = onSubtool((job) => {
    if (job.kind !== 'align' || job.path !== path || job.state !== 'done') return;
    const r = job.result;
    timing = { scale: r.scale, offset: r.offset };
    aligned = r;
    anchors = [];
    toast(`Otomatik hizalandı: ${timingText(timing)}`, r.confidence === 'low' ? 'warning' : 'ok');
  });
  onDestroy(off);

  const CONFIDENCE = { high: ['yüksek', 'ok'], medium: ['orta', 'warning'], low: ['düşük — elle kontrol edin', 'danger'] };
</script>

<div class="sync card">
  <div class="head">
    <Icon name="timer" size={16} />
    <strong>Altyazı zamanlaması</strong>
    <span class="dim ellipsis src">{label}</span>
    <span class="grow"></span>
    <button class="btn sm" onclick={onexport} title="Altyazıyı bu düzeltmeyle dosyaya kaydet"><Icon name="download" size={14} />Dışa aktar…</button>
    <button class="icon-btn sm" title="Kapat" onclick={onclose}><Icon name="x" size={16} /></button>
  </div>

  <div class="body">
    <div class="col">
      <div class="line">
        <span class="label">Kaydırma</span>
        <button class="btn sm ghost" onclick={() => nudge(-1)}>−1</button>
        <button class="btn sm ghost" onclick={() => nudge(-0.1)} title="G">−0,1</button>
        <input class="field offset mono" value={timing.offset.toFixed(3).replace('.', ',')} onchange={setOffset}
          onkeydown={(e) => e.stopPropagation()} title="Saniye; artı: altyazı daha geç görünür" />
        <button class="btn sm ghost" onclick={() => nudge(0.1)} title="H">+0,1</button>
        <button class="btn sm ghost" onclick={() => nudge(1)}>+1</button>
      </div>
      <div class="line">
        <span class="label">Kare hızı</span>
        <select class="field" value={ratio} onchange={setRatio}>
          {#each RATIOS as [value, text]}<option value={String(value)}>{text}</option>{/each}
          {#if ratio === 'custom'}<option value="custom" disabled>Özel ×{timing.scale.toFixed(5).replace('.', ',')}</option>{/if}
        </select>
        <button class="btn sm ghost" disabled={isIdentity(timing)} onclick={() => { timing = { scale: 1, offset: 0 }; anchors = []; aligned = null; }}>
          <Icon name="rotate" size={14} />Sıfırla</button>
      </div>
      <div class="line state">
        <span class="badge" class:accent={!isIdentity(timing)}>{timingText(timing)}</span>
        <span class="dim hint">G / H: ±0,1 sn · Shift ile ±1 sn</span>
      </div>

      <div class="auto">
        {#if whisper}
          <span class="dim hint">Whisper transkripti sesten çıkarıldığı için zaten hizalı; yine de elle kaydırabilirsiniz.</span>
        {:else if aligning}
          <Icon name="loader" spin size={16} />
          <span class="grow">{jobText(busy)}</span>
          <button class="btn sm ghost" onclick={cancelJob}>Durdur</button>
        {:else}
          <button class="btn sm" onclick={autoAlign} disabled={!!busy} title="Konuşma Whisper ile çıkarılır (önbellekte varsa kullanılır) ve altyazı satırları konuşmaya oturtulur. Çeviri altyazılarda da çalışır.">
            <Icon name="sparkles" size={14} />Whisper ile otomatik hizala</button>
          {#if aligned}
            {@const [text, tone] = CONFIDENCE[aligned.confidence]}
            <span class="badge {tone}" title="Altyazı ile konuşmanın örtüşmesi: {aligned.before} → {aligned.score}">güven {text}</span>
          {/if}
        {/if}
      </div>
      {#if aligning}<div class="track"><i style:width="{jobPercent(busy)}%"></i></div>{/if}
    </div>

    <div class="col anchors">
      <div class="line">
        <span class="label">Elle eşitle</span>
        <span class="dim hint grow">Satırı duyduğunuz anda “Şimdi”ye basın; iki satır işaretlerseniz hız da düzeltilir.</span>
      </div>
      <div class="list">
        {#each nearby as cue (cue.start)}
          {@const marked = anchors.some((a) => Math.abs(a.src - cue.start) < 0.01)}
          <div class="cue" class:marked>
            <button class="mono when" onclick={() => onjump?.(cue.start * timing.scale + timing.offset)} title="Bu satıra git">{fmt(cue.start * timing.scale + timing.offset)}</button>
            <span class="text ellipsis" title={cue.text}>{cue.text.replace(/\n/g, ' ')}</span>
            <button class="btn sm" class:primary={!marked} onclick={() => anchor(cue)}>{marked ? 'Yeniden' : 'Şimdi'}</button>
          </div>
        {:else}
          <p class="dim hint">Bu konumun yakınında altyazı satırı yok.</p>
        {/each}
      </div>
      {#if anchors.length}
        <div class="line">
          {#each anchors as a, i}
            <span class="badge accent ellipsis" title={a.text}>{i + 1}. {a.text.slice(0, 18)}… → {fmt(a.at)}</span>
          {/each}
          <button class="btn sm ghost" onclick={() => (anchors = [])}>Temizle</button>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .sync { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 14px; border-bottom: 1px solid var(--outline); color: var(--secondary); }
  .head strong { color: var(--text); }
  .src { font-size: 12px; max-width: 280px; }
  .grow { flex: 1; }
  .body { display: grid; grid-template-columns: minmax(390px, 1fr) minmax(300px, 1.2fr); gap: 18px; padding: 12px 14px; overflow: auto; min-height: 0; }
  .col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .line { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .line .label { min-width: 76px; flex: none; white-space: nowrap; margin-right: 4px; }
  .offset { width: 84px; text-align: center; height: 30px; }
  select.field { height: 30px; }
  .state { gap: 10px; }
  .hint { font-size: 11.5px; line-height: 1.45; }
  .auto { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 4px; border-top: 1px solid var(--outline); padding-top: 10px; }
  .list { display: flex; flex-direction: column; gap: 2px; }
  .cue { display: flex; align-items: center; gap: 10px; padding: 3px 4px 3px 0; border-radius: 6px; }
  .cue:hover { background: var(--surface-hover); }
  .cue.marked .text { color: var(--accent); }
  .when { font-size: 12px; color: var(--accent); width: 58px; text-align: right; flex: none; }
  .text { flex: 1; font-size: 13px; }
  .anchors .badge { max-width: 220px; }
</style>
