<script>
  // F229: Sesli Haber telefon uygulamasina yerel agda Aktar'in sesini veren sunucu (bridge_phone.py).
  // F230: Dokun Oku resim betimleme ayari (describe, vision_model).
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { act, app, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';

  let { searching = false } = $props();
  let state = $state(null);
  let voices = $state([]);
  let busy = $state(false);

  call('phone_state').then((value) => { if (value && !value.error) state = value; });
  call('tts_voices').then((list) => {
    if (Array.isArray(list)) voices = list.filter((v) => v.language === 'tr' && !v.configurable);
  });
  const groups = $derived([...new Set(voices.map((v) => v.group))]);
  // Model sunucusundaki modeller (embedding haric); secili model listede yoksa (LM Studio kapali) yine gorunur
  const visionNames = $derived.by(() => {
    const list = (app.models.names ?? []).filter((n) => !n.toLowerCase().includes('embed'));
    const current = state?.vision_model;
    return current && !list.includes(current) ? [current, ...list] : list;
  });

  async function run(method, ...args) {
    busy = true;
    const value = await act(method, ...args);
    busy = false;
    if (value) state = value;
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Adres kopyalandı.');
    } catch {
      // pano kapali: adres ekranda gorunuyor
    }
  }
</script>

<section>
  <h2>Telefon sesi (Sesli Haber, Dokun Oku)</h2>
  {#if state}
    <div class="fr">
      <div class="l">Sunucu
        <small>Telefondaki Sesli Haber uygulaması haberleri bu bilgisayarın sesiyle okur. Yalnızca aynı Wi-Fi'deki
          telefonlar bağlanabilir; Aktar kapalıyken telefon kendi sesini kullanır.</small>
        {#if state.running}<small class="okc">Açık · kapı {state.port}</small>{/if}
      </div>
      {#if state.running}
        <button class="btn sm" disabled={busy} onclick={() => run('phone_stop')}><Icon name="stop" size={14} />Kapat</button>
      {:else}
        <button class="btn sm" disabled={busy} onclick={() => run('phone_start')}><Icon name="power" size={14} />Aç</button>
      {/if}
    </div>
    {#if state.running}
      <div class="fr">
        <div class="l">Telefonda girilecek adres ve kod<small>Uygulamada üstteki başlığa uzun basınca açılan Ayarlar'a yazın. Kod Aktar her açıldığında değişir; eşlenen telefon yeniden kod istemez.</small></div>
        <div class="pair">
          {#each state.addresses.slice(0, 2) as address}
            <button class="addr" title="Kopyala" onclick={() => copy(address)}>{address}</button>
          {:else}
            <span class="dim-text">Yerel ağ adresi bulunamadı</span>
          {/each}
          <span class="code">{state.code.slice(0, 3)} {state.code.slice(3)}</span>
        </div>
      </div>
    {/if}
    <div class="fr">
      <div class="l">Aktar açılınca sunucuyu aç<small>Aktar kapanınca sunucu da kapanır.</small></div>
      <Toggle checked={state.autostart} onchange={(value) => run('phone_set', null, value)} />
    </div>
    <div class="fr">
      <div class="l">Ses<small>Haberler bu sesle okunur. Aktar'da başka bir sesle kitap okunurken ya da sesli kitap, dublaj kaydedilirken telefon kendi sesine geçer.</small></div>
      <select class="field" value={state.voice} onchange={(event) => run('phone_set', event.currentTarget.value, null)}>
        {#if !voices.some((v) => v.value === state.voice)}<option value={state.voice}>{state.voice}</option>{/if}
        {#each groups as group}
          <optgroup label={group}>
            {#each voices.filter((v) => v.group === group) as voice}<option value={voice.value}>{voice.label}</option>{/each}
          </optgroup>
        {/each}
      </select>
    </div>
    <div class="fr">
      <div class="l">Resim betimleme (Dokun Oku)<small>Telefondaki Dokun Oku uygulaması dokunulan resmi gönderir, görsel model ne gösterdiğini Türkçe anlatır. Resim yalnızca bu bilgisayardaki model sunucusuna gider.</small></div>
      <Toggle checked={state.describe} onchange={(value) => run('phone_set', null, null, value, null)} />
    </div>
    {#if state.describe}
      <div class="fr">
        <div class="l">Betimleme modeli<small>Model sunucusundaki modellerden; resim okuyabilen (görsel destekli) bir model seçin. Seçilmezse Kütüphane ve belgeler'deki görü modeli kullanılır. Model gerekince LM Studio'da kendiliğinden yüklenir.</small></div>
        <select class="field" value={state.vision_model}
          onchange={(event) => run('phone_set', null, null, null, event.currentTarget.value)}>
          <option value="">(görü modeliyle aynı)</option>
          {#each visionNames as name}<option value={name}>{name}</option>{/each}
        </select>
      </div>
    {/if}
    {#if state.phones.length || searching}
      <div class="fr phones">
        <div class="l">Eşlenen telefonlar</div>
        <div class="list">
          {#each state.phones as phone (phone.id)}
            <div class="phone">
              <span>{phone.ad}<small>{phone.eslesme}</small></span>
              <button class="btn sm ghost" title="Eşlemeyi kaldır" onclick={() => run('phone_remove', phone.id)}><Icon name="trash" size={14} /></button>
            </div>
          {:else}
            <span class="dim-text">Yok</span>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</section>

<style>
  .fr { display: flex; align-items: center; gap: 20px; padding: 12px 0; border-bottom: 1px solid var(--outline); }
  .fr:last-child { border-bottom: 0; }
  .l { flex: 1; min-width: 0; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  small.okc { color: var(--ok); }
  .dim-text { font-size: 12px; color: var(--secondary); white-space: nowrap; }
  .pair { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
  .addr { font-family: var(--mono); font-size: 13px; background: none; border: 0; color: var(--text); cursor: pointer; padding: 0; }
  .addr:hover { color: var(--accent); }
  .code { font-family: var(--mono); font-size: 22px; font-weight: 600; letter-spacing: 3px; }
  .phones { align-items: flex-start; }
  .list { display: flex; flex-direction: column; gap: 4px; min-width: 220px; }
  .phone { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .phone small { display: block; color: var(--dim); font-size: 11px; }
</style>
