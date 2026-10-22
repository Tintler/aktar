<script>
  // Metinden ses (F178): yazilan metni secilen sesle (kayitli ses, motor sesi ya da Ayarlardaki ses) okutup
  // secilen klasore WAV/MP3 olarak yazar. Secimler ui.json 'speech' altinda kalir; kayit arka planda surer
  // (bridge_tts.tts_speech_create, olay 'tts_speech'). F179: 'Kayitli sesler' sekmesinde sesler eklenir ve siralanir.
  // F184: mikrofondan konusulan Whisper ile metne cevrilip kutuya eklenir; 'Konusma bitince seslendir' aciksa
  // (ui.json speech.mic_convert) metin hemen secili sesle okutulup ayni bicimde (WAV/MP3) klasore yazilir.
  import Icon from '../lib/Icon.svelte';
  import VoicePresetList from '../components/VoicePresetList.svelte';
  import MicButton from '../components/MicButton.svelte';
  import { app, act, savePref, onDrop, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { splitText, QUOTE_DEFAULTS } from '../lib/sentences.js';
  import { resolvePauses, pauseAfter } from '../lib/pauses.js';

  const SPEEDS = [0.8, 0.9, 1, 1.1, 1.25, 1.5];
  const FORMATS = [['wav', 'WAV'], ['mp3', 'MP3']];

  const s = app.speech;
  const prefs = $derived({ voice: '', folder: '', format: 'wav', speed: 1, tab: 'text', mic_convert: false, ...(app.prefs.speech ?? {}) });
  let voices = $state([]);

  const groups = $derived.by(() => {
    const result = {};
    for (const v of voices) if (!v.configurable) (result[v.group] ??= []).push(v);
    return Object.entries(result);
  });
  const known = $derived(!prefs.voice || voices.some((v) => v.value === prefs.voice));
  const split = $derived(splitText(s.text, { ...QUOTE_DEFAULTS, ...(app.ttsPrefs.split ?? {}) }));
  const chars = $derived(s.text.trim().length);
  const ready = $derived(split.sentences.length > 0 && !!prefs.folder && !s.job);

  const loadVoices = () => call('tts_voices').then((list) => { if (Array.isArray(list)) voices = list; });
  loadVoices();

  const save = (values) => savePref({ speech: { ...prefs, ...values } });

  async function chooseFolder() {
    const result = await act('tts_speech_folder');
    if (result?.folder) save({ folder: result.folder });
  }

  async function create() {
    if (!ready) return;
    const pauses = resolvePauses(app.ttsPrefs.pauses);
    const { sentences, breaks } = split;
    const gaps = sentences.map((text, i) => pauseAfter(text, breaks.has(i), pauses, prefs.speed));
    const result = await act('tts_speech_create', sentences, gaps, [...breaks], prefs.voice, prefs.folder, s.name.trim(),
      prefs.speed, prefs.format);
    if (result?.started) { s.last = null; s.job = { done: 0, total: result.total, loading: true }; }
  }

  function spoken() {
    if (!prefs.mic_convert) return;
    if (!prefs.folder) { toast('Metin eklendi; seslendirmek için kayıt klasörünü seçin.', 'error'); return; }
    queueMicrotask(create);
  }

  onDrop('speech', async (paths) => {
    const path = paths?.[0];
    if (!path) return;
    if (s.job) return;
    if (s.text.trim() && !(await confirm({ title: 'Metin değiştirilsin mi?', message: 'Yazdığınız metnin yerine dosyadaki metin gelir.', ok: 'Değiştir', cancel: 'Vazgeç' }))) return;
    const result = await act('tts_speech_read', path);
    if (!result) return;
    s.text = result.text;
    if (!s.name.trim()) s.name = result.name;
    toast('Metin açıldı: ' + path.split(/[\\/]/).pop(), 'ok');
  });

  const minutes = (sec) => {
    const total = Math.round(sec || 0);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  };
  const percent = $derived(s.job && s.job.total && !s.job.loading ? Math.min(100, Math.round((s.job.done * 100) / s.job.total)) : 0);
</script>

<section class="page">
  <div class="page-head">
    <h1>Metinden ses</h1>
    <div class="tabs" role="tablist">
      {#each [['text', 'Metin'], ['presets', 'Kayıtlı sesler']] as [value, label]}
        <button role="tab" aria-selected={prefs.tab === value} class:on={prefs.tab === value} onclick={() => save({ tab: value })}>{label}</button>
      {/each}
    </div>
  </div>
  {#if prefs.tab === 'presets'}
    <div class="page-body list"><VoicePresetList onchange={loadVoices} /></div>
  {:else}
  <div class="page-body body">
    <div class="text card">
      <textarea class="selectable" bind:value={s.text} disabled={!!s.job}
        placeholder="Seslendirilecek metni yazın ya da yapıştırın. Her satır ayrı paragraf sayılır; bir .txt dosyasını buraya bırakarak da açabilirsiniz."></textarea>
      <div class="meta">
        <span>{chars.toLocaleString('tr-TR')} karakter · {split.sentences.length} cümle</span>
        <div class="tools">
          <MicButton bind:value={s.text} disabled={!!s.job} ontext={spoken} always label="Mikrofondan yaz" caption="Mikrofon" />
          {#if s.text}<button class="btn sm" disabled={!!s.job} onclick={() => (s.text = '')}><Icon name="trash" size={14} />Temizle</button>{/if}
        </div>
      </div>
    </div>

    <aside class="opts card">
      <label class="row">
        <span class="label">Ses</span>
        <select class="field" value={prefs.voice} disabled={!!s.job} onchange={(e) => save({ voice: e.currentTarget.value })}>
          <option value="">Ayarlardaki ses</option>
          {#if !known}<option value={prefs.voice}>Bulunamayan ses</option>{/if}
          {#each groups as [group, items]}
            <optgroup label={group}>{#each items as v}<option value={v.value}>{v.label}</option>{/each}</optgroup>
          {/each}
        </select>
      </label>

      <div class="row">
        <span class="label">Hız</span>
        <div class="chips">
          {#each SPEEDS as value}
            <button class="chip" class:on={prefs.speed === value} disabled={!!s.job} onclick={() => save({ speed: value })}>{value.toLocaleString('tr-TR')}×</button>
          {/each}
        </div>
      </div>

      <div class="row">
        <span class="label">Biçim</span>
        <div class="chips">
          {#each FORMATS as [value, label]}
            <button class="chip" class:on={prefs.format === value} disabled={!!s.job} onclick={() => save({ format: value })}>{label}</button>
          {/each}
        </div>
      </div>

      <div class="row">
        <span class="label">Kayıt klasörü</span>
        <div class="folder">
          <input class="field" readonly value={prefs.folder} placeholder="Klasör seçilmedi" title={prefs.folder} />
          <button class="btn sm" disabled={!!s.job} onclick={chooseFolder}><Icon name="folderOpen" size={14} />Seç</button>
        </div>
      </div>

      <label class="row">
        <span class="label">Dosya adı</span>
        <input class="field" bind:value={s.name} disabled={!!s.job} placeholder="Boşsa metnin ilk kelimeleri" />
        <small>Aynı adda dosya varsa sonuna numara eklenir.</small>
      </label>

      <label class="check">
        <input type="checkbox" checked={prefs.mic_convert} disabled={!!s.job} onchange={(e) => save({ mic_convert: e.currentTarget.checked })} />
        <span>Mikrofon kaydı bitince seçili sesle hemen seslendir</span>
      </label>

      {#if s.job}
        <div class="progress">
          <div class="bar"><i style:width="{percent}%" class:wait={s.job.loading}></i></div>
          <span>{s.job.loading ? 'Ses motoru hazırlanıyor…' : `${s.job.done} / ${s.job.total} cümle`}</span>
        </div>
        <button class="btn" onclick={() => call('tts_speech_cancel')}><Icon name="stop" size={15} />Durdur</button>
      {:else}
        <button class="btn primary" disabled={!ready} onclick={create}
          title={!prefs.folder ? 'Önce kayıt klasörünü seçin' : !split.sentences.length ? 'Önce metin yazın' : ''}>
          <Icon name="waveform" size={16} />Sese dönüştür</button>
      {/if}

      {#if s.last}
        <div class="last">
          <div class="nm" title={s.last.path}><Icon name="check" size={14} />{s.last.path.split(/[\\/]/).pop()} · {minutes(s.last.duration)}</div>
          {#if s.last.url}<audio controls src={s.last.url}></audio>{/if}
          <button class="btn sm" onclick={() => act('reveal', s.last.path)}><Icon name="folder" size={14} />Konumu aç</button>
        </div>
      {/if}
    </aside>
  </div>
  {/if}
</section>

<style>
  .tabs { display: flex; gap: 4px; background: var(--surface); border-radius: 999px; padding: 3px; margin-left: 12px; }
  .tabs button { padding: 5px 14px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--secondary); }
  .tabs button.on { background: var(--surface-active); color: var(--text); }
  .list { display: flex; flex-direction: column; max-width: 760px; }
  .body { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; }
  .text { display: flex; flex-direction: column; min-height: 0; }
  .text textarea { flex: 1; min-height: 240px; resize: none; padding: 16px 18px; border: 0; outline: none; background: transparent;
    color: var(--text); font: 15px/1.7 inherit; border-radius: 12px 12px 0 0; }
  .text textarea::placeholder { color: var(--dim); }
  .meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; min-height: 44px;
    border-top: 1px solid var(--outline); font-size: 12px; color: var(--dim); }
  .opts { display: flex; flex-direction: column; gap: 16px; padding: 16px; align-self: start; }
  .row { display: flex; flex-direction: column; gap: 6px; }
  .row small { font-size: 11px; color: var(--dim); }
  .tools { display: flex; align-items: center; gap: 6px; }
  .tools :global(.mic:not(.rec)) { border: 1px solid var(--outline); color: var(--secondary); }
  .check { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: var(--secondary); cursor: pointer; }
  .check input { margin-top: 2px; accent-color: var(--accent); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .folder { display: flex; gap: 6px; }
  .folder .field { flex: 1; min-width: 0; }
  .progress { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--secondary); }
  .bar { height: 6px; border-radius: 999px; background: var(--surface); overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--accent); transition: width .2s; }
  .bar i.wait { width: 30% !important; animation: slide 1.2s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(330%); } }
  .last { display: flex; flex-direction: column; gap: 8px; padding-top: 12px; border-top: 1px solid var(--outline); }
  .last .nm { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
  .last .nm :global(svg) { color: var(--ok); flex: none; }
  .last audio { width: 100%; height: 36px; }
  .last .btn { align-self: flex-start; }
  @media (max-width: 1000px) { .body { grid-template-columns: 1fr; } }
</style>
