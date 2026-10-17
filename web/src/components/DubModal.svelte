<script>
  // Videoya dublaj (F141): secili (cevrilmis) altyazi sesli okuma motoruyla seslendirilir ve videoya
  // varsayilan ses parcasi olarak eklenir. Is arka planda (altyazi araclari yuvasi, 'dub') calisir;
  // ilerleme oynaticidaki rozette ve sag ustteki is listesinde gorunur. Secenekler ui.json 'dub'da.
  // F146: 'separate' muzik ve efektleri korur (yalniz ozgun konusma kisilir); 'speakers' konusmaci basina ses.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { app, act, savePref } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { subtool, timingText, isIdentity, onSubtool } from '../lib/subtools.svelte.js';

  let { path, source, label = '', timing = null, audio = null, onclose } = $props();

  const saved = app.prefs.dub ?? {};
  let voice = $state(saved.voice ?? '');
  let opts = $state({ background: 0.25, duck: true, max_tempo: 1.35, format: 'mkv', speed: 1, separate: false, speakers: false,
    ...(saved.opts ?? {}) });
  // Konusmacilar (F146): {available, message, ready, speakers: [{id, name, seconds, lines, sample}]}
  let speakerInfo = $state(null);
  let speakerVoices = $state({});      // {'0': '' (otomatik) | '=' (ana ses) | ses}
  let speakerCount = $state(0);
  async function loadSpeakers() {
    const info = await call('dub_speakers', path, source, timing);
    if (info && !info.error) {
      speakerInfo = info;
      for (const s of info.speakers) speakerVoices[String(s.id)] ??= '';
    }
  }
  loadSpeakers();
  const stopListening = onSubtool((job) => { if (job.kind === 'diarize' && job.path === path) loadSpeakers(); });
  $effect(() => stopListening);
  async function findSpeakers() {
    await act('speakers_find', path, audio, speakerCount);
  }
  async function rename(id, name) {
    const result = await call('speakers_rename', path, { ...Object.fromEntries((speakerInfo?.speakers ?? []).map((s) => [String(s.id), s.name])), [String(id)]: name });
    if (result && !result.error) loadSpeakers();
  }
  const fmtSeconds = (s) => (s >= 60 ? `${Math.floor(s / 60)} dk ${Math.round(s % 60)} sn` : `${Math.round(s)} sn`);
  let voices = $state([]);
  call('tts_voices').then((list) => { if (Array.isArray(list)) voices = list.filter((v) => v.language === 'tr'); });
  const groups = $derived([...new Set(voices.map((v) => v.group))]);
  const busy = $derived(!!subtool.job);
  const noEngine = $derived(!app.engines.some((e) => e.mode && e.voices.some((v) => v.language === 'tr')));

  const TEMPOS = [[1, 'Hızlandırma (satır kayabilir)'], [1.2, 'En fazla 1,2×'], [1.35, 'En fazla 1,35×'], [1.5, 'En fazla 1,5×'], [1.75, 'En fazla 1,75×']];
  const SPEEDS = [0.9, 1, 1.1, 1.2];

  async function start() {
    savePref({ dub: { voice, opts: $state.snapshot(opts) } });
    const result = await act('dub_create', path, source, { ...$state.snapshot(opts), audio }, timing, voice,
      opts.speakers ? $state.snapshot(speakerVoices) : null);
    if (result?.started) onclose();
  }
</script>

<Modal title="Türkçe dublaj" width={560} {onclose}>
  <div class="row"><span class="label">Altyazı</span><span class="ellipsis">{label || source}</span></div>
  <div class="row">
    <span class="label">Zamanlama</span>
    <span class:accent={!isIdentity(timing)}>{timingText(timing)}{isIdentity(timing) ? '' : ' uygulanacak'}</span>
  </div>
  <p class="hint">Seçili altyazının her satırı sesli okuma motoruyla seslendirilir ve satırın zamanına yerleştirilir.
    Altyazı Türkçe olmalı (önce Altyazı Çevir ile çevirin). Hazır satırlar saklanır; iş durdurulup yeniden başlatılınca baştan üretilmez.</p>

  {#if noEngine}
    <div class="warn"><Icon name="alert" size={16} /><span>Türkçe ses motoru kurulu değil. Ayarlar → Ses → Sesli okuma bölümünden kurun.</span></div>
  {/if}

  <label class="stack">
    <span class="label">Ses</span>
    <select class="field" bind:value={voice}>
      <option value="">Sesli okuma sesi (Ayarlar → Ses)</option>
      {#each groups as group}
        <optgroup label={group}>
          {#each voices.filter((v) => v.group === group) as v}<option value={v.value}>{v.label}</option>{/each}
        </optgroup>
      {/each}
    </select>
  </label>

  <div class="grid">
    <label class="stack">
      <span class="label">Konuşma hızı</span>
      <select class="field" bind:value={opts.speed}>
        {#each SPEEDS as s}<option value={s}>{s.toLocaleString('tr-TR')}×</option>{/each}
      </select>
    </label>
    <label class="stack">
      <span class="label">Sığmayan satırlar</span>
      <select class="field" bind:value={opts.max_tempo}>
        {#each TEMPOS as [value, text]}<option {value}>{text}</option>{/each}
      </select>
    </label>
  </div>

  <div class="stack">
    <Toggle bind:checked={opts.separate} disabled={speakerInfo && !speakerInfo.available}
      label="Müziği ve efektleri koru (yalnızca özgün konuşma kısılır)" />
    <span class="hint">{#if speakerInfo && !speakerInfo.available}{speakerInfo.message}{:else}Videonun sesi önce konuşma ve müzik/efekt olarak ayrılır
      (ilk kullanımda ~65 MB model indirilir; işlemcide videonun yarısı kadar sürer, sonuç saklanır).{/if}</span>
  </div>

  <div class="stack">
    <span class="label">{opts.separate ? 'Özgün konuşma düzeyi' : 'Özgün ses düzeyi'}: %{Math.round(opts.background * 100)}</span>
    <input type="range" min="0" max="1" step="0.05" bind:value={opts.background} />
    <Toggle bind:checked={opts.duck} label="Yalnızca dublaj konuşurken kıs (aralarda özgün ses tam düzeyde)" />
  </div>

  <div class="stack">
    <Toggle bind:checked={opts.speakers} disabled={speakerInfo && !speakerInfo.available} label="Konuşmacılara farklı ses ver" />
    {#if opts.speakers}
      {#if speakerInfo?.ready && speakerInfo.speakers.length}
        <div class="speakers">
          {#each speakerInfo.speakers as s (s.id)}
            <div class="speaker">
              <input class="field name" value={s.name} maxlength="40" title="Konuşmacının adı (transkriptte ve soru-cevapta da görünür)"
                onchange={(e) => rename(s.id, e.currentTarget.value)} />
              <select class="field" bind:value={speakerVoices[String(s.id)]}>
                <option value="">Otomatik</option>
                <option value="=">Ana ses</option>
                {#each groups as group}
                  <optgroup label={group}>
                    {#each voices.filter((v) => v.group === group) as v}<option value={v.value}>{v.label}</option>{/each}
                  </optgroup>
                {/each}
              </select>
              <span class="dim meta" title={s.sample}>{s.lines} satır · {fmtSeconds(s.seconds)}{s.sample ? ' · ' + s.sample : ''}</span>
            </div>
          {/each}
        </div>
        <span class="hint">Otomatik: en çok konuşan ana sesi alır, diğerlerine sırayla başka sesler verilir.</span>
      {:else}
        <span class="hint">Konuşmacılar dublaj başlarken bulunur ve sesler otomatik dağıtılır. Sesleri kendiniz seçmek için önce bulun.</span>
      {/if}
      <div class="find">
        <select class="field count" bind:value={speakerCount} title="Konuşmacı sayısı">
          <option value={0}>Sayı: otomatik</option>
          {#each [2, 3, 4, 5, 6, 8] as n}<option value={n}>{n} konuşmacı</option>{/each}
        </select>
        <button class="btn" disabled={busy} onclick={findSpeakers}><Icon name="users" size={15} />{speakerInfo?.ready ? 'Yeniden ayır' : 'Konuşmacıları bul'}</button>
      </div>
    {/if}
  </div>

  <label class="stack">
    <span class="label">Çıktı</span>
    <select class="field" bind:value={opts.format}>
      <option value="mkv">Video (.dublaj.mkv)</option>
      <option value="m4a">Yalnızca ses (.dublaj.m4a)</option>
    </select>
    <span class="hint">{opts.format === 'mkv' ? 'Dublaj varsayılan ses parçası olur; özgün sesler ve altyazılar korunur. ' : ''}Videonun yanına yazılır; özgün dosyaya dokunulmaz.</span>
  </label>

  {#snippet footer()}
    {#if busy}<span class="dim grow">Önceki altyazı/klip işi sürüyor.</span>{/if}
    <button class="btn" onclick={onclose}>Vazgeç</button>
    <button class="btn primary" disabled={busy || noEngine} onclick={start}><Icon name="volume" size={16} />Dublajı başlat</button>
  {/snippet}
</Modal>

<style>
  .row { display: flex; align-items: baseline; gap: 12px; font-size: 13px; }
  .row .label { width: 92px; flex: none; }
  .accent { color: var(--accent); }
  .stack { display: flex; flex-direction: column; gap: 6px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .hint { font-size: 12px; color: var(--dim); line-height: 1.5; }
  .warn { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; font-size: 12.5px; line-height: 1.5;
    background: color-mix(in srgb, var(--warning) 12%, transparent); }
  .warn :global(svg) { color: var(--warning); flex: none; }
  .grow { flex: 1; font-size: 12.5px; }
  input[type='range'] { width: 100%; }
  .speakers { display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow: auto; }
  .speaker { display: grid; grid-template-columns: 120px 1fr; gap: 4px 8px; align-items: center; }
  .speaker .meta { grid-column: 2; font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .find { display: flex; gap: 8px; align-items: center; }
  .find .count { width: auto; }
</style>
