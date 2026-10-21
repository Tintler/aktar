<script module>
  // Pencere acikken pencereye birakilan gorsel ses resmi olur (Reading'in birakma isleyicisi buraya yollar).
  export const presetDrop = { handler: null };
</script>

<script>
  // Ses onayari olusturma/duzenleme (F137): ad, resim, motor sesi ve sesin secenekleri.
  // F173: klon kaydinin bir araligi secilebilir (AudioTrim); kaydedince o parca onayar klasorune WAV olarak kesilir.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import AudioTrim from './AudioTrim.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';

  // preset: duzenlenecek kayit (yeni icin null). onsave(sonuc), ondelete(sonuc), onclose().
  let { preset = null, onsave, ondelete, onclose } = $props();

  const usable = $derived(app.engines.filter((e) => e.mode));
  const voices = $derived(usable.flatMap((engine) => engine.voices.map((voice) => ({
    value: `${engine.id}/${voice.id}`, spec: voice, engine,
    label: engine.voices.length > 1 ? `${engine.name} · ${voice.name}` : engine.name,
  }))));

  // svelte-ignore state_referenced_locally
  let form = $state({ id: preset?.id ?? '', name: preset?.name ?? '', voice: preset?.voice ?? '',
    options: { ...(preset?.options ?? {}) }, image: preset?.image ?? '' });
  let trims = $state({});         // F173: {secenek: {start, end}} (yoksa kaydin tamami)
  let spoken = $state('');        // F174: secilen parcanin metni (Whisper) -> 'Kaydin metni' kutusuna yazilabilir
  let imageChanged = $state(false);
  let saving = $state(false);
  let error = $state('');

  $effect(() => {
    if (!form.voice && voices.length) form.voice = voices[0].value;
  });
  const spec = $derived(voices.find((v) => v.value === form.voice)?.spec ?? null);
  const engine = $derived(voices.find((v) => v.value === form.voice)?.engine ?? null);
  const initial = $derived((form.name.trim()[0] ?? '').toLocaleUpperCase('tr'));

  function setImage(value) {
    form.image = value;
    imageChanged = true;
  }

  async function pickImage(path = null) {
    const result = await act('tts_preset_image', path);
    if (result?.image) setImage(result.image);
  }

  // Panodan yapistirilan gorsel (Ctrl+V); metin kutusuna metin yapistirilirken dokunulmaz.
  function paste(event) {
    const file = [...(event.clipboardData?.items ?? [])].find((entry) => entry.type.startsWith('image/'))?.getAsFile();
    if (!file) return;
    if (event.target?.matches?.('input, textarea') && event.clipboardData.types.includes('text/plain')) return;
    event.preventDefault();
    if (file.size > 15 * 1024 * 1024) return toast('Görsel çok büyük (en fazla 15 MB).', 'error');
    const reader = new FileReader();
    reader.onload = () => setImage(String(reader.result));
    reader.readAsDataURL(file);
  }

  $effect(() => {
    presetDrop.handler = (paths) => pickImage(paths[0]);
    return () => { presetDrop.handler = null; };
  });

  async function pickRecording(key) {
    const path = await call('tts_choose_reference');
    if (path) {
      form.options[key] = path;
      trims[key] = null;
    }
  }

  const fileName = (path) => String(path ?? '').split(/[\\/]/).pop();

  async function save() {
    if (saving) return;
    saving = true;
    error = '';
    const values = $state.snapshot(form);
    // Yalnizca secili sesin secenekleri gider; resim degismediyse dokunulmaz.
    values.options = Object.fromEntries((spec?.options ?? []).map((o) => [o.key, values.options[o.key] ?? '']));
    if (!imageChanged) delete values.image;
    values.trim = Object.fromEntries(Object.entries($state.snapshot(trims)).filter(([key, value]) => value && values.options[key]));
    const result = await call('tts_preset_save', values);
    saving = false;
    if (result?.error) { error = result.error; return; }
    onsave(result);
  }

  async function remove() {
    const yes = await confirm({ title: 'Sesi sil', message: `"${preset.name}" silinsin mi? Kopyalanan ses kaydı ve resmi de silinir.`, ok: 'Sil', danger: true });
    if (!yes) return;
    const result = await act('tts_preset_delete', preset.id);
    if (result) ondelete(result);
  }
</script>

<svelte:window onpaste={paste} />

<Modal title={preset ? 'Sesi düzenle' : 'Yeni ses'} width={560} {onclose}>
  <div class="top">
    <button class="avatar" title="Resim seç" onclick={() => pickImage()}>
      {#if form.image}<img src={form.image} alt="" />{:else if initial}<span>{initial}</span>{:else}<Icon name="image" size={22} />{/if}
    </button>
    <div class="grow">
      <input class="field name" bind:value={form.name} maxlength="60" placeholder="Ses adı (ör. Anlatıcı, Ece, Sakin erkek)" />
      <div class="hint">
        <button class="link" onclick={() => pickImage()}>Resim seç</button>
        {#if form.image}<span>·</span><button class="link" onclick={() => setImage('')}>Kaldır</button>{/if}
        <span class="dim">· Ctrl+V ile yapıştırın ya da pencereye bırakın</span>
      </div>
    </div>
  </div>

  {#if !voices.length}
    <div class="warn"><Icon name="alert" size={16} />Kurulu ses motoru yok. Ayarlar → Ses bölümünden kurun.</div>
  {:else}
    <label class="fr">
      <span class="l">Ses</span>
      <select class="field w" bind:value={form.voice}>
        {#each voices as v (v.value)}<option value={v.value}>{v.label}</option>{/each}
      </select>
    </label>
    {#if engine?.attribution || engine?.notice}
      <div class="notice">{#if engine.attribution}<b>{engine.attribution}</b>{/if}{#if engine.notice}<span>{engine.notice}</span>{/if}</div>
    {/if}
    {#each spec?.options ?? [] as option (form.voice + option.key)}
      <div class="fr col">
        <span class="l">{option.label}{#if option.hint}<small>{option.hint}</small>{/if}</span>
        {#if option.type === 'file'}
          <div class="pick">
            <span class="path selectable" title={form.options[option.key] ?? ''}>{fileName(form.options[option.key]) || 'Seçilmedi'}</span>
            <button class="btn sm" onclick={() => pickRecording(option.key)}>Seç…</button>
          </div>
          {#if form.options[option.key]}
            {#key form.options[option.key]}<AudioTrim path={form.options[option.key]} bind:trim={trims[option.key]} bind:text={spoken}
              whole={form.options[option.key] === preset?.options?.[option.key]} />{/key}
          {/if}
        {:else}
          <textarea class="field" rows="2" bind:value={form.options[option.key]} placeholder={option.default ?? ''}></textarea>
          {#if option.key === 'reference_text' && spoken && spoken !== (form.options[option.key] ?? '').trim()}
            <div class="hint"><button class="link" onclick={() => (form.options[option.key] = spoken)}>Seçilen parçanın metnini yaz</button>
              <span class="dim ellipsis" title={spoken}>{spoken}</span></div>
          {/if}
        {/if}
      </div>
    {/each}
  {/if}
  {#if error}<div class="err"><Icon name="alert" size={16} />{error}</div>{/if}

  {#snippet footer()}
    {#if preset}<button class="btn ghost danger-text" onclick={remove}><Icon name="trash" size={15} />Sil</button>{/if}
    <span class="grow"></span>
    <button class="btn" onclick={onclose}>İptal</button>
    <button class="btn primary" disabled={saving || !form.name.trim() || !voices.length} onclick={save}>Kaydet</button>
  {/snippet}
</Modal>

<style>
  .top { display: flex; gap: 16px; align-items: center; }
  .grow { flex: 1; min-width: 0; }
  .avatar { width: 72px; height: 72px; border-radius: 50%; flex: none; overflow: hidden; display: grid; place-items: center;
    background: var(--surface); color: var(--dim); font-size: 28px; font-weight: 700; }
  .avatar:hover { box-shadow: 0 0 0 2px var(--accent); }
  .avatar img { width: 100%; height: 100%; object-fit: cover; }
  .name { width: 100%; }
  .hint { display: flex; gap: 6px; align-items: center; margin-top: 6px; font-size: 12px; flex-wrap: wrap; }
  .link { color: var(--accent); font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .dim { color: var(--dim); }
  .fr { display: flex; align-items: center; gap: 16px; padding: 10px 0; border-top: 1px solid var(--outline); }
  .fr.col { flex-direction: column; align-items: stretch; gap: 8px; }
  .l { flex: 1; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  .field.w { width: 300px; }
  textarea.field { width: 100%; resize: vertical; }
  .pick { display: flex; align-items: center; gap: 10px; }
  .path { flex: 1; min-width: 0; color: var(--secondary); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .warn, .err { display: flex; gap: 8px; align-items: center; font-size: 13px; }
  .warn { color: var(--warning); }
  .err { color: var(--danger); }
  .danger-text { color: var(--danger); }
  .notice { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--warning); padding: 0 0 10px; }
  .notice b { color: var(--secondary); font-weight: 600; }
</style>
