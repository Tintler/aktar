<script>
  // Sesli mod (F141): elleri serbest sohbet. Acikken mikrofon dinler; konusma bitip kisa bir sessizlik olunca
  // kayit yerel Whisper ile metne cevrilip gonderilir, cevap sohbet sesiyle okunur, sonra yeniden dinlenir.
  // Okurken tiklamak sozu keser ve dinlemeye gecer; Esc ya da dugme sesli modu kapatir. Ses bilgisayardan cikmaz.
  import { onDestroy } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { voiceStatus, startRecording } from '../lib/voice.js';
  import { speaker, ensureVoice, speak, stopSpeaking, entryText } from '../lib/speaker.svelte.js';

  // entries: sohbet kayitlari; busy: cevap hazirlaniyor; onsend(text): soruyu gonderir
  let { entries = [], busy = false, disabled = false, onsend } = $props();

  const SPEECH = 0.045;       // bu tepe duzeyinin ustu konusma sayilir
  const SILENCE_MS = 1300;    // konusmadan sonra bu kadar sessizlik: soru bitti
  const IDLE_MS = 45000;      // hic konusulmazsa kayit yenilenir (bellek birikmesin)
  const MAX_MS = 90000;

  let mode = $state('off');   // off | starting | listening | transcribing | waiting | speaking
  let level = $state(0);
  let recorder = null;
  let timer = null;
  let mark = 0;
  let sentAt = 0;

  const on = $derived(mode !== 'off');
  const TITLES = {
    off: 'Sesli mod: konuşarak sorun, cevap sesli okunsun (Esc: kapat)',
    starting: 'Sesli mod hazırlanıyor…',
    listening: 'Dinliyorum… Sözünüz bitince kısa bir sessizlikten sonra gönderilir. (Esc: kapat)',
    transcribing: 'Konuşma metne çevriliyor…',
    waiting: 'Cevap hazırlanıyor…',
    speaking: 'Cevap okunuyor; sözü kesip konuşmak için tıklayın',
  };
  const LABELS = { starting: 'Hazırlanıyor', listening: 'Dinliyor', transcribing: 'Yazıya dökülüyor', waiting: 'Düşünüyor', speaking: 'Konuşuyor' };

  function clearTimer() {
    clearInterval(timer);
    timer = null;
  }

  async function begin() {
    const status = await voiceStatus();
    if (!status.available) { toast('Sesli mod kullanılamıyor: ' + status.hint, 'error'); return; }
    mode = 'starting';
    window.addEventListener('keydown', onKey, true);
    if (!(await ensureVoice())) {
      toast(speaker.message || 'Sohbet sesi hazırlanamadı. Ayarlar → Ses bölümünden bir ses motoru kurun.', 'error');
      end();
      return;
    }
    if (mode === 'starting') listen();
  }

  function end() {
    clearTimer();
    recorder?.cancel();
    recorder = null;
    stopSpeaking();
    mode = 'off';
    level = 0;
    window.removeEventListener('keydown', onKey, true);
  }

  function onKey(event) {
    if (event.key === 'Escape' && on) {
      event.preventDefault();
      event.stopPropagation();
      end();
    }
  }

  async function listen() {
    clearTimer();
    try {
      recorder = await startRecording();
    } catch (error) {
      toast('Mikrofon açılamadı: ' + String(error?.message ?? error), 'error');
      end();
      return;
    }
    if (mode === 'off') { recorder.cancel(); recorder = null; return; }
    mode = 'listening';
    const began = Date.now();
    let heard = false, quietSince = 0;
    timer = setInterval(() => {
      if (!recorder) return;
      level = recorder.level();
      const now = Date.now();
      if (level > SPEECH) { heard = true; quietSince = 0; }
      else if (heard) quietSince ||= now;
      if (heard && quietSince && now - quietSince > SILENCE_MS) finish();
      else if (now - began > MAX_MS) finish();
      else if (!heard && now - began > IDLE_MS) { recorder.cancel(); recorder = null; listen(); }
    }, 100);
  }

  async function finish() {
    clearTimer();
    const current = recorder;
    recorder = null;
    if (!current || mode !== 'listening') return;
    mode = 'transcribing';
    level = 0;
    const result = await call('voice_transcribe', await current.stop());
    if (mode !== 'transcribing') return;
    const text = (result?.text ?? '').trim();
    if (result?.error) toast(result.error, 'error');
    if (!text) { listen(); return; }
    mark = entries.length;
    sentAt = Date.now();
    mode = 'waiting';
    onsend?.(text);
  }

  // Cevap geldi: son kayit cevap (ya da hata) ve sohbet bos. Sonra okunur, ardindan yeniden dinlenir.
  $effect(() => {
    const count = entries.length, working = busy, last = entries.at(-1);
    if (mode !== 'waiting') return;
    if (!working && count > mark && (last?.kind === 'assistant' || last?.kind === 'error')) {
      reply(last);
      return;
    }
    // Soru gonderilemediyse (sohbet kilitli vb.) yeniden dinlenir.
    if (!working && count === mark) {
      const wait = setTimeout(() => { if (mode === 'waiting' && entries.length === mark && !busy && Date.now() - sentAt > 3500) listen(); }, 4000);
      return () => clearTimeout(wait);
    }
  });

  async function reply(entry) {
    mode = 'speaking';
    const done = await speak(entryText(entry));
    if (!done && speaker.message && mode === 'speaking') toast(speaker.message, 'error');
    if (mode === 'speaking') listen();
  }

  function click() {
    if (mode === 'off') begin();
    else if (mode === 'speaking') { stopSpeaking(); listen(); }
    else if (mode === 'listening') finish();
    else end();
  }

  onDestroy(end);
</script>

<span class="vm" class:on>
  <button type="button" class="voice" class:on class:speaking={mode === 'speaking'} class:listening={mode === 'listening'}
    title={TITLES[mode]} aria-label={TITLES[mode]} aria-pressed={on} disabled={disabled && !on} onclick={click}
    style:--level={Math.min(1, level * 4)}>
    {#if mode === 'starting' || mode === 'transcribing' || mode === 'waiting'}
      <Icon name="loader" size={15} spin />
    {:else}
      <Icon name={mode === 'speaking' ? 'volume' : 'headphones'} size={15} />
    {/if}
    {#if on}<span class="txt">{LABELS[mode]}</span>{/if}
  </button>
  {#if on}
    <button type="button" class="close" title="Sesli modu kapat (Esc)" aria-label="Sesli modu kapat" onclick={end}><Icon name="x" size={12} /></button>
  {/if}
</span>

<style>
  .vm { display: inline-flex; align-items: center; flex: none; }
  .vm.on { background: color-mix(in srgb, var(--accent) 14%, transparent); border-radius: 999px; padding-right: 2px; }
  .voice { flex: none; height: 30px; min-width: 30px; padding: 0 7px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    color: var(--dim); font-size: 12px; font-weight: 600; transition: color .15s, background .15s, box-shadow .1s; }
  .voice:not(:disabled):hover { color: var(--text); background: var(--surface-active); }
  .voice.on, .voice.on:hover { color: var(--accent); background: none; padding: 0 8px 0 9px; }
  .voice.listening { box-shadow: 0 0 0 calc(var(--level, 0) * 5px) color-mix(in srgb, var(--accent) 35%, transparent); }
  .voice.speaking :global(svg) { animation: pulse 1.1s ease-in-out infinite; }
  .txt { white-space: nowrap; }
  .close { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; color: var(--dim); }
  .close:hover { color: var(--text); background: var(--surface-active); }
  @keyframes pulse { 50% { opacity: .45; } }
</style>
