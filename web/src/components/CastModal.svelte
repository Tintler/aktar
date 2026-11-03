<script>
  // F239 (deneysel): cok sesli sesli kitap. Kitapliktan yapilan karakter atamasinin karakterlerine ses secilir;
  // "Cok sesli okuma" acikken okuyucu, Hazirla ve Kaydet konusmalari karakterin sesiyle okur (secilmeyenler ve
  // konusani bilinmeyenler anlaticinin sesiyle). Sesler okuyucunun sesiyle ayni motordan secilir.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { call } from '../lib/api.js';
  import { act, toast } from '../lib/state.svelte.js';

  let { book, title = '', language = 'tr', onclose } = $props();

  let data = $state(null);
  let error = $state('');
  let filter = $state('');
  const SHOWN = 40;

  async function load() {
    const result = await call('tts_cast_info', book, language).catch((e) => ({ error: String(e) }));
    if (result?.error) error = result.error;
    else data = result;
  }
  load();

  const info = $derived(data?.info ?? null);
  const characters = $derived((info?.characters ?? []).filter((c) => !filter.trim() || c.name.toLocaleLowerCase('tr').includes(filter.trim().toLocaleLowerCase('tr'))));
  const assigned = $derived(Object.keys(info?.voices ?? {}).length);
  const GENDER = { female: 'kadın', male: 'erkek', unknown: '' };

  async function update(values) {
    const result = await act('tts_cast_set', book, values.voices ?? null, values.enabled ?? null, values.rename ?? null);
    if (result?.info && data) data.info = result.info;
  }

  function setVoice(name, value) {
    update({ voices: { [name]: value } });
  }

  function rename(name, value) {
    const next = value.trim();
    if (next && next !== name) update({ rename: { [name]: next } });
  }

  // Ses onizlemesi (DubModal ile ayni yol: tts_preview; klon kayitli seste kaydin basi)
  let sample = $state({ id: null, loading: false });
  let audio = null;
  function stopSample() {
    audio?.pause();
    audio = null;
    sample = { id: null, loading: false };
  }
  async function preview(name, ref) {
    const same = sample.id === name;
    stopSample();
    if (same || !ref) return;
    sample = { id: name, loading: true };
    const result = await act('tts_preview', ref, '');
    if (sample.id !== name) return;
    if (!result?.audio) { stopSample(); if (result?.error) toast(result.error, 'error'); return; }
    audio = new Audio('data:audio/wav;base64,' + result.audio);
    audio.onended = stopSample;
    sample = { id: name, loading: false };
    audio.play().catch(stopSample);
  }
  $effect(() => stopSample);
</script>

<Modal title={`Karakter sesleri${title ? ' · ' + title : ''}`} width={640} {onclose}>
  {#if error}
    <div class="error">{error}</div>
  {:else if !data}
    <div class="note"><Icon name="loader" size={14} spin />Yükleniyor…</div>
  {:else if !info}
    <div class="note">Bu kitap için karakter ataması yok. Kitaplıkta kitaba sağ tıklayıp "Karakter seslerini belirle" ile başlatın.</div>
  {:else}
    <div class="lead">
      <b>Deneysel.</b> Dil modeli {info.speech} konuşmanın {info.assigned} tanesinin kime ait olduğunu tahmin etti; yanılabilir.
      Ses seçilmeyen karakterler ve konuşanı bilinmeyen satırlar anlatıcının sesiyle okunur.
    </div>
    <div class="row-top">
      <Toggle checked={info.enabled} label="Çok sesli okuma" onchange={(value) => update({ enabled: value })} />
      <span class="grow"></span>
      <span class="dim">Anlatıcı: <b>{data.narrator || '—'}</b>{data.engine ? ` · ${data.engine}` : ''}</span>
    </div>
    {#if info.enabled && !assigned}<div class="warn">Henüz hiçbir karaktere ses seçilmedi; okuma tek sesle sürer.</div>{/if}
    {#if !data.voices.length}
      <div class="warn">Okuyucunun ses motorunda seçilebilecek başka ses yok. Klon kayıtlı motorlarda (Drama 3 TR) önce
        Metinden ses → Kayıtlı sesler'den birkaç ses kaydedin.</div>
    {/if}
    {#if (info.characters?.length ?? 0) > 8}
      <input class="field search" placeholder="Karakter ara…" bind:value={filter} />
    {/if}
    <div class="list">
      {#each characters.slice(0, filter ? undefined : SHOWN) as person (person.name)}
        <div class="person">
          <div class="who">
            <input class="name" value={person.name} title="Adı değiştir (aynı adı yazınca iki karakter birleşir)"
              onchange={(e) => rename(person.name, e.currentTarget.value)} />
            <small>{person.lines} konuşma{GENDER[person.gender] ? ' · ' + GENDER[person.gender] : ''}</small>
          </div>
          <select class="field" value={info.voices?.[person.name] ?? ''} onchange={(e) => setVoice(person.name, e.currentTarget.value)}>
            <option value="">Anlatıcının sesi</option>
            {#each data.voices as voice}<option value={voice.value}>{voice.label}</option>{/each}
          </select>
          <button class="icon-btn sm" title="Sesi dinle" disabled={!info.voices?.[person.name]}
            onclick={() => preview(person.name, info.voices?.[person.name])}>
            <Icon name={sample.id === person.name ? (sample.loading ? 'loader' : 'stop') : 'play'} size={14} spin={sample.id === person.name && sample.loading} /></button>
        </div>
      {/each}
      {#if !filter && characters.length > SHOWN}<div class="dim">… {characters.length - SHOWN} karakter daha (arayarak bulun).</div>{/if}
    </div>
    <div class="hint">
      <b>Okurken:</b> konuşmanın sesine geçmek motorda ses değiştirmek demektir; ilk geçişler yavaş olabilir.
      <b>Hazırla</b> önce anlatıcının, sonra her karakterin cümlelerini sırayla üretir; hazır bölümler beklemeden okunur.
      <b>Kaydet</b> (bölüm ya da sesli kitap) aynı sesleri kullanır. Çok sesli okumayı kapatınca karakter cümleleri
      anlatıcının sesiyle yeniden hazırlanmalıdır; iki sürüm de saklanır.
    </div>
  {/if}
</Modal>

<style>
  .lead { font-size: 13px; color: var(--secondary); line-height: 1.5; margin-bottom: 12px; }
  .row-top { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; font-size: 13px; }
  .grow { flex: 1; }
  .dim { color: var(--dim); font-size: 12.5px; }
  .note { display: flex; gap: 8px; align-items: center; color: var(--dim); font-size: 13px; }
  .error { color: var(--danger); font-size: 13px; }
  .warn { font-size: 12.5px; color: var(--secondary); background: var(--surface); border: 1px solid var(--outline); border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
  .search { width: 100%; margin-bottom: 8px; }
  .list { display: flex; flex-direction: column; gap: 6px; max-height: 46vh; overflow: auto; padding-right: 4px; }
  .person { display: grid; grid-template-columns: 1fr 230px auto; gap: 8px; align-items: center; }
  .who { display: flex; flex-direction: column; min-width: 0; }
  .name { background: none; border: 1px solid transparent; border-radius: 6px; padding: 2px 4px; font-weight: 600; font-size: 13.5px; color: var(--text); }
  .name:hover, .name:focus { border-color: var(--outline); outline: none; }
  .who small { color: var(--dim); font-size: 12px; padding-left: 5px; }
  .hint { margin-top: 14px; font-size: 12px; color: var(--dim); line-height: 1.55; }
</style>
