<script>
  // Sesle soru (F112): tikla konus, tekrar tikla bitir (Esc vazgecer). Ses yerelde Whisper ile
  // metne cevrilir ve kutuya eklenir; gondermek kullanicida. Whisper yoksa aciklamali devre disi.
  // F142: Ayarlar → Ses'ten kapatilabilir (ui.json mic_button: false); kapaliyken hic cizilmez.
  import Icon from '../lib/Icon.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { voiceStatus, startRecording, appendText } from '../lib/voice.js';

  let { value = $bindable(''), disabled = false, ontext = null } = $props();

  let info = $state(null);
  let mode = $state('idle'); // idle | recording | working
  let seconds = $state(0);
  let level = $state(0);
  let recorder = null;
  let timer = null;

  voiceStatus().then((s) => (info = s));

  const title = $derived(
    !info ? 'Sesle sor' :
    !info.available ? `Sesle sor kullanılamıyor: ${info.hint}` :
    mode === 'recording' ? 'Kaydı bitir ve metne çevir (Esc: vazgeç)' :
    mode === 'working' ? 'Konuşma metne çevriliyor…' :
    'Sesle sor: konuşun, metin kutuya yazılır (ses bilgisayardan çıkmaz)'
  );

  function micError(error) {
    const name = error?.name ?? '';
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'Mikrofon izni verilmedi.';
    if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'Mikrofon bulunamadı.';
    if (name === 'NotReadableError') return 'Mikrofon başka bir uygulama tarafından kullanılıyor olabilir.';
    return 'Mikrofon açılamadı: ' + String(error?.message ?? error);
  }

  function clearTimer() {
    clearInterval(timer);
    timer = null;
    window.removeEventListener('keydown', onKey, true);
  }

  function onKey(event) {
    if (event.key === 'Escape' && mode === 'recording') {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
  }

  async function start() {
    try {
      recorder = await startRecording();
    } catch (error) {
      toast(micError(error), 'error');
      return;
    }
    mode = 'recording';
    seconds = 0;
    const began = Date.now();
    const limit = info?.max_seconds ?? 120;
    timer = setInterval(() => {
      seconds = Math.floor((Date.now() - began) / 1000);
      level = recorder?.level() ?? 0;
      if (seconds >= limit) finish();
    }, 200);
    window.addEventListener('keydown', onKey, true);
  }

  function cancel() {
    clearTimer();
    recorder?.cancel();
    recorder = null;
    mode = 'idle';
  }

  async function finish() {
    if (mode !== 'recording') return;
    clearTimer();
    mode = 'working';
    const current = recorder;
    recorder = null;
    try {
      const wav = await current.stop();
      const result = await act('voice_transcribe', wav);
      if (result?.text) {
        value = appendText(value, result.text);
        ontext?.(value);
      }
    } finally {
      mode = 'idle';
    }
  }

  function click() {
    if (mode === 'recording') finish();
    else if (mode === 'idle') start();
  }

  $effect(() => () => {
    // bilesen kapanirken (panel kapandi, sayfa degisti) mikrofon acik kalmasin
    clearTimer();
    recorder?.cancel();
  });
</script>

{#if app.prefs.mic_button !== false}
<button type="button" class="mic" class:rec={mode === 'recording'} {title} aria-label={title} aria-pressed={mode === 'recording'}
  disabled={!info?.available || mode === 'working' || (disabled && mode === 'idle')} onclick={click}
  style:--level={Math.min(1, level * 3)}>
  {#if mode === 'working'}
    <Icon name="loader" size={16} spin />
  {:else if mode === 'recording'}
    <Icon name="stop" size={12} /><span class="time">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</span>
  {:else}
    <Icon name="mic" size={16} />
  {/if}
</button>
{/if}

<style>
  .mic { flex: none; height: 30px; min-width: 30px; padding: 0 7px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; gap: 5px;
    color: var(--dim); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; border: 1px solid transparent; transition: color .15s, background .15s, box-shadow .1s; }
  .mic:not(:disabled):hover { color: var(--text); background: var(--surface-active); }
  .mic.rec { color: #fff; background: var(--danger, #d64545); padding: 0 9px;
    box-shadow: 0 0 0 calc(var(--level, 0) * 5px) color-mix(in srgb, var(--danger, #d64545) 35%, transparent); }
  .mic.rec:hover { color: #fff; background: var(--danger, #d64545); }
  .time { min-width: 26px; }
</style>
