<script>
  import Icon from '../lib/Icon.svelte';
  import BookCover from '../components/BookCover.svelte';
  import { app, act, openPdfImport, toast, refreshEmotionBooks } from '../lib/state.svelte.js';
  import { confirm, choose } from '../lib/confirm.svelte.js';
  import { bookSections } from '../lib/emotions.js';

  let { onopen } = $props();
  let menu = $state(null);

  const recent = $derived(app.shelf.find((b) => b.opened && b.exists && b.percent < 100) ?? null);

  async function add() {
    const result = await act('shelf_add');
    if (result) app.shelf = result.books;
    if (result?.errors?.length) toast(result.errors.join(' · '), 'error');
  }

  async function remove(book) {
    menu = null;
    const yes = await confirm({
      title: 'Kitaplıktan kaldır',
      message: `"${book.title}" kitaplıktan kaldırılsın mı? Dosyanın kendisi silinmez; okuma konumu ve yer imleri silinir.`,
      ok: 'Kaldır', cancel: 'Vazgeç',
    });
    if (!yes) return;
    const books = await act('shelf_remove', book.id);
    if (books) { app.shelf = books; toast('Kitap kaldırıldı.'); }
  }

  // F170: Drama 3 duygu etiketleri butun kitap icin bir kez olusturulur; okuyucu Drama 3 ile okurken bu etiketli
  // surumu kullanir. Kitaplikta tek kitap kalir, etiketler APP_DIR/duygu-etiketleri altinda saklanir.
  const tagged = (book) => app.emotionBooks.includes(book.id);

  async function createEmotions(book) {
    menu = null;
    if (app.emotionJob) { toast('Başka bir kitabın duygu etiketleri oluşturuluyor.'); return; }
    if (app.ttsPrepare || app.ttsAudiobook) { toast('Ses hazırlanırken ya da sesli kitap kaydedilirken duygu etiketi oluşturulamaz.'); return; }
    const catalog = await act('tts_emotion_catalog');
    if (!catalog) return;
    // F187: serbest yonergede model katalogla sinirli degil; secili etiketler yalnizca kelime listesi icin
    const free = catalog.style !== 'catalog';
    if (!catalog.allowed.length && !free) { toast("Ayarlar → Ses'te Drama 3 için en az bir duygu etiketi seçin.", 'error'); return; }
    const count = catalog.allowed.length;
    const words = `Dil modeli kullanılmaz. Anlatıcıdaki "gülerek", "fısıldadı" gibi kalıplar Ayarlar → Ses'te seçtiğiniz ` +
      `${count} etiketten karşılığına çevrilir ("gülerek" → [laughs]); yeni yönerge üretilmez. Hızlıdır.`;
    const method = await choose({
      title: tagged(book) ? 'Duygu etiketlerini yeniden oluştur' : 'Duygu etiketleri oluştur',
      message: `"${book.title}" kitabının konuşmalarına Fish Audio Drama 3 ile okurken kullanılacak yönergeler eklenir. ` +
        'Okuyucudaki metin değişmez. İki yöntem var:',
      options: [
        { value: 'llm', label: 'Dil modeliyle',
          hint: (free
            ? 'Model sahneye bakıp konuşmaya kendi yönergesini yazar, listeyle sınırlı değildir: Türkçe ön ek ([titrek bir ' +
              'sesle]), cümle ortasında ses ya da duraklama ([derin bir nefes alır]), birkaç kelimeyi saran çift etiket ' +
              '(<whisper>…</whisper>). Modelin dokunmadığı konuşmada anlatıcıda açık ipucu varsa kelime listesinin etiketi kalır.'
            : `Model yalnızca seçtiğiniz ${count} etiketten birini konuşmanın başına koyar (Ayarlar → Ses → "Yalnızca ` +
              'katalog"): ' + catalog.allowed.join(' ') + '.') +
            " Ayarlar → Modeller'deki sohbet modeli kullanılır; bu sırada ses motoru durdurulur, bitince model boşaltılır." },
        { value: 'words', label: 'Yalnızca kelime listesiyle', hint: words },
      ],
      ok: 'Oluştur',
    });
    if (!method) return;
    app.emotionJob = { book: book.id, title: book.title, done: 0, total: 0, reading: true };
    let sections;
    try {
      sections = await bookSections(book.id, app.ttsPrefs.split ?? {});
    } catch (error) {
      app.emotionJob = null;
      toast(String(error?.message ?? error), 'error');
      return;
    }
    const result = await act('tts_emotions_create', book.id, sections, method, book.title);
    if (!result?.started) app.emotionJob = null;
    else if (app.emotionJob?.reading) app.emotionJob = { book: book.id, title: book.title, done: 0, total: result.total };
  }

  async function removeEmotions(book) {
    menu = null;
    const yes = await confirm({ title: 'Duygu etiketlerini sil', message: `"${book.title}" kitabının duygu etiketleri silinsin mi?`,
      ok: 'Sil', cancel: 'Vazgeç', danger: true });
    if (!yes) return;
    if (await act('tts_emotions_clear', book.id)) { await refreshEmotionBooks(); toast('Duygu etiketleri silindi.'); }
  }

  async function showEmotions(book) {
    menu = null;
    const result = await act('tts_emotions_info', book.id, book.language || 'tr');
    if (result?.info?.text) act('reveal', result.info.text);
  }

  function open(book) {
    if (!book.exists) { toast('Kitap dosyası bulunamadı: ' + book.path, 'error'); return; }
    onopen(book);
  }

  const progressLabel = (b) => (!b.exists ? 'Dosya bulunamadı' : b.percent >= 100 ? 'Bitti' : b.percent ? `%${Math.round(b.percent)} okundu` : 'Yeni')
    + (tagged(b) ? ' · duygu etiketli' : '');
</script>

<svelte:window onclick={() => (menu = null)} />

<section class="page">
  <div class="page-head">
    <h1>Okuma</h1>
    <button class="btn" onclick={() => openPdfImport(null, 'reading')} title="PDF'yi (taranmış ya da metinli) okuyup EPUB kitap yapar"><Icon name="fileText" size={16} />PDF'den kitap</button>
    <button class="btn primary" onclick={add}><Icon name="plus" size={16} />Kitap ekle</button>
  </div>

  <div class="page-body scroll">
    {#if recent}
      <div class="hero card">
        <div class="hc"><BookCover book={recent} /></div>
        <div class="hm">
          <div class="k">Okumaya devam et</div>
          <div class="t">{recent.title}</div>
          <div class="s">{[recent.author, `%${Math.round(recent.percent)} okundu`].filter(Boolean).join(' · ')}</div>
          <div class="track"><i style:width="{recent.percent}%"></i></div>
          <button class="btn primary" onclick={() => open(recent)}><Icon name="book" />Devam et</button>
        </div>
      </div>
    {/if}

    <h2>Kitaplığım <small>{app.shelf.length || ''}</small></h2>
    <div class="shelf">
      {#each app.shelf as book (book.id)}
        <button class="bk" class:missing={!book.exists} onclick={() => open(book)} title={book.path}
          oncontextmenu={(e) => { e.preventDefault(); menu = { x: e.clientX, y: e.clientY, book }; }}>
          <BookCover {book} />
          <span class="t">{book.title}</span>
          <span class="s">{progressLabel(book)}</span>
          <span class="p"><i style:width="{book.percent}%"></i></span>
          <span class="x" role="presentation" title="Kitaplıktan kaldır" onclick={(e) => { e.stopPropagation(); remove(book); }}><Icon name="x" size={14} /></span>
        </button>
      {/each}
      <button class="drop" onclick={add}>
        <Icon name="plus" size={28} />
        <span>EPUB ekleyin</span>
        <small>ya da pencereye sürükleyip bırakın</small>
      </button>
    </div>
  </div>
</section>

{#if menu}
  <div class="menu" style:left="{menu.x}px" style:top="{menu.y}px">
    <button onclick={() => open(menu.book)}><Icon name="book" size={15} />Aç</button>
    {#if app.emotionJob?.book === menu.book.id}
      <button onclick={() => { menu = null; act('tts_emotions_cancel'); }}><Icon name="stop" size={15} />Duygu etiketlemeyi durdur</button>
    {:else}
      <button disabled={!menu.book.exists || Boolean(app.emotionJob)} onclick={() => createEmotions(menu.book)}>
        <Icon name="sparkles" size={15} />{tagged(menu.book) ? 'Duygu etiketlerini yeniden oluştur' : 'Duygu etiketleri oluştur'}</button>
    {/if}
    {#if tagged(menu.book)}
      <button onclick={() => showEmotions(menu.book)}><Icon name="fileText" size={15} />Etiketli metni göster</button>
      <button onclick={() => removeEmotions(menu.book)}><Icon name="trash" size={15} />Duygu etiketlerini sil</button>
    {/if}
    <button onclick={() => remove(menu.book)}><Icon name="trash" size={15} />Kitaplıktan kaldır</button>
  </div>
{/if}

<style>
  .scroll { display: flex; flex-direction: column; gap: 22px; }

  .hero { display: flex; gap: 22px; align-items: center; padding: 20px; background: linear-gradient(120deg, color-mix(in srgb, var(--accent) 14%, var(--panel)), var(--panel) 70%); }
  .hc { width: 96px; flex: none; }
  .hm { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
  .k { font-size: 12px; font-weight: 600; color: var(--secondary); text-transform: uppercase; letter-spacing: .06em; }
  .hm .t { font-size: 24px; font-weight: 700; }
  .hm .s { color: var(--secondary); }
  .hm .track { width: min(360px, 100%); flex: none; margin: 8px 0 12px; }

  h2 { font-size: 20px; font-weight: 700; }
  h2 small { color: var(--dim); font-size: 14px; font-weight: 500; margin-left: 6px; }
  .shelf { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 18px; }
  .bk { display: flex; flex-direction: column; text-align: left; padding: 10px; border-radius: 12px; position: relative; min-width: 0; }
  .bk:hover { background: var(--surface); }
  .bk.missing { opacity: .5; }
  .bk .t { margin-top: 10px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bk .s { color: var(--dim); font-size: 12px; }
  .bk .p { height: 3px; border-radius: 3px; background: var(--surface-active); margin-top: 8px; overflow: hidden; }
  .bk .p i { display: block; height: 100%; background: var(--accent); }
  .bk .x { position: absolute; top: 16px; right: 16px; width: 26px; height: 26px; border-radius: 50%; display: none; place-items: center;
    background: rgba(0, 0, 0, .65); color: #fff; }
  .bk:hover .x { display: grid; }
  .drop { border: 2px dashed var(--outline); border-radius: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 6px; color: var(--dim); aspect-ratio: 2 / 3; margin: 10px; font-size: 13px; text-align: center; padding: 12px; }
  .drop small { font-size: 11px; }
  .drop:hover { border-color: var(--accent); color: var(--accent); }

  .menu { position: fixed; z-index: 40; background: var(--overlay); border: 1px solid var(--outline); border-radius: 10px; padding: 4px; box-shadow: 0 8px 28px var(--shadow); }
  .menu button { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 7px; font-size: 13px; width: 100%; }
  .menu button:hover:not(:disabled) { background: var(--surface-hover); }
  .menu button:disabled { opacity: .5; }
</style>
