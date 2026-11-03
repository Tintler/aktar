<script>
  // F239: yedekleme ve tasima (bridge_backup.py). Ayarlar, kitaplik, koleksiyonlar, ses onayarlari ... tek ZIP; istege
  // bagli calisma dosyalari ve hazirlanmis sesler. Geri yuklemeden once mevcut veri Aktar/yedekler altina yedeklenir;
  // baska bilgisayarda bulunamayan kitap/klasor yollari secilen klasorde aranip duzeltilir.
  import Icon from '../lib/Icon.svelte';
  import Toggle from './Toggle.svelte';
  import { act, toast } from '../lib/state.svelte.js';
  import { call, on } from '../lib/api.js';
  import { confirm } from '../lib/confirm.svelte.js';

  let info = $state(null);
  let extra = $state({ work: false, audio: false });
  let job = $state(null);   // {done, total}
  let restored = $state(false);

  async function load() {
    const value = await call('backup_info').catch(() => null);
    if (value && !value.error) info = value;
  }
  load();

  $effect(() => on('backup', (data) => {
    if (!data.finished) { job = { done: data.done, total: data.total }; return; }
    job = null;
    if (data.error) toast('Yedek yazılamadı: ' + data.error, 'error');
    else if (data.cancelled) toast('Yedekleme durduruldu.');
    else toast(`Yedek yazıldı: ${data.path} (${data.files} dosya, ${size(data.bytes)}).`, 'ok');
  }));

  function size(bytes) {
    if (!bytes) return '0 MB';
    return bytes >= 1e9 ? `${(bytes / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} GB`
      : `${Math.max(0.1, bytes / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} MB`;
  }
  const missingCount = (m) => (m ? (m.books ?? 0) + (m.folders ?? 0) + (m.files ?? 0) : 0);

  async function create() {
    const groups = Object.entries(extra).filter(([, on]) => on).map(([key]) => key);
    const result = await act('backup_create', groups);
    if (result?.started) job = { done: 0, total: 0 };
  }

  async function restore() {
    const chosen = await act('backup_choose');
    if (!chosen || chosen.error) return;
    const when = chosen.created ? new Date(chosen.created).toLocaleString('tr-TR') : '?';
    const yes = await confirm({
      title: 'Yedeği geri yükle',
      message: `${when} tarihli yedek (${chosen.platform || '?'}, Aktar ${chosen.app_version || '?'}, ${chosen.entries} dosya) geri yüklensin mi? ` +
        'Aynı adlı ayarlar ve kayıtlar yedektekiyle değiştirilir. Şu anki veriniz önce Aktar klasöründeki "yedekler" ' +
        'altına yedeklenir. Bitince Aktar\'ı yeniden başlatın. API anahtarları yedekte yoktur; yeniden girmeniz gerekir.',
      ok: 'Geri yükle', cancel: 'Vazgeç', danger: true,
    });
    if (!yes) return;
    const result = await act('backup_restore', chosen.path);
    if (!result || result.error) return;
    restored = true;
    await load();
    const left = missingCount(result.missing);
    toast(`Yedek geri yüklendi (${result.files} dosya). Aktar'ı yeniden başlatın.` +
      (left ? ` ${left} kitap/klasör bu bilgisayarda bulunamadı: "Bulunamayan dosyaları bul" ile yeniden bağlayın.` : ''), 'ok');
  }

  async function relink() {
    const result = await act('backup_relink');
    if (!result || result.error) return;
    await load();
    const fixed = result.books + result.folders + result.files;
    toast(fixed ? `${fixed} yol düzeltildi${result.left ? `; ${result.left} tanesi hâlâ bulunamadı` : ''}. Aktar'ı yeniden başlatın.`
      : 'Seçilen klasörde aynı adlı dosya ya da klasör bulunamadı.', fixed ? 'ok' : 'error');
  }
</script>

<section>
  <h2>Yedekleme ve taşıma</h2>
  <div class="fr">
    <div class="l">Yedek al<small>Ayarlar, model bağlantıları, kitaplık ve okuma konumları, Kütüphane koleksiyonları ve sohbetler, altyazı serileri ve
      sözlükler, temalar, kayıtlı sesler, duygu etiketleri, karakter sesleri, kitap özetleri ve görselleri, Ekran Çeviri profilleri tek ZIP dosyasına
      yazılır{info ? ` (${size(info.groups.core.bytes)})` : ''}. Modeller ve ses motorları yedeğe girmez. API anahtarları işletim sisteminin şifre deposundadır; yedekte yoktur.</small></div>
    {#if job}
      <button class="btn sm" onclick={() => act('backup_cancel')}><Icon name="loader" size={14} spin />{job.total ? `%${Math.floor((100 * job.done) / job.total)}` : 'Hazırlanıyor'} · Durdur</button>
    {:else}
      <button class="btn sm primary" onclick={create}><Icon name="download" size={14} />Yedek al…</button>
    {/if}
  </div>
  {#if info}
    {#each ['work', 'audio'] as key}
      <div class="fr">
        <div class="l">{info.groups[key].label}<small>{info.groups[key].files} dosya · {size(info.groups[key].bytes)}{key === 'work'
          ? '. Videoların transkriptleri yeniden çıkarılmasın diye; ayrılmış müzik parçaları alınmaz.'
          : '. Hazırlanmış sesler yeniden üretilmez (ücretli bulut sesleri kaybolmaz).'}</small></div>
        <Toggle checked={extra[key]} disabled={Boolean(job)} onchange={(value) => (extra[key] = value)} />
      </div>
    {/each}
  {/if}
  <div class="fr">
    <div class="l">Yedekten geri yükle<small>Başka bir bilgisayardan (Windows ya da Linux) alınan yedek de olur. Önce şu anki veri Aktar klasöründeki
      "yedekler" altına yedeklenir.{#if restored} <b>Geri yüklendi: Aktar'ı yeniden başlatın.</b>{/if}</small></div>
    <div class="row-btns">
      <button class="btn sm" title="Önceki yedekler (geri yükleme öncesi)" onclick={() => act('backup_open_folder')}><Icon name="folder" size={14} /></button>
      <button class="btn sm" disabled={Boolean(job)} onclick={restore}><Icon name="upload" size={14} />Geri yükle…</button>
    </div>
  </div>
  <div class="fr">
    <div class="l">Bulunamayan dosyaları bul<small>{#if missingCount(info?.missing)}Bu bilgisayarda {info.missing.books} kitap, {info.missing.folders} koleksiyon klasörü ve
      {info.missing.files} dosya bulunamıyor (başka bilgisayardan taşınınca yollar değişir).{:else}Kitaplık ve koleksiyonlardaki bütün dosyalar yerinde.{/if}
      Seçtiğiniz klasörün altında aynı adlı dosya ve klasörler aranır, yollar düzeltilir.</small></div>
    <button class="btn sm" disabled={!missingCount(info?.missing)} onclick={relink}><Icon name="search" size={14} />Klasör seç…</button>
  </div>
</section>

<style>
  h2 { font-size: 20px; font-weight: 700; letter-spacing: -.01em; margin-bottom: 6px; }
  .fr { display: flex; align-items: center; gap: 20px; padding: 12px 0; border-bottom: 1px solid var(--outline); }
  .fr:last-child { border-bottom: 0; }
  .l { flex: 1; min-width: 0; font-weight: 500; }
  .l small { display: block; color: var(--dim); font-size: 12px; font-weight: 400; margin-top: 2px; }
  .row-btns { display: flex; gap: 6px; flex: none; }
</style>
