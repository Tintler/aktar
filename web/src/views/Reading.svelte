<script>
  // Okuma (Cevirgec): kitaplik ya da acik kitap.
  import Shelf from './Shelf.svelte';
  import Reader from './Reader.svelte';
  import { app, act, onDrop, openPdfImport } from '../lib/state.svelte.js';
  import { presetDrop } from '../components/VoicePresetModal.svelte';

  // Pencereye birakilan EPUB'lar kitapliga eklenir.
  onDrop('reading', async (paths) => {
    if (presetDrop.handler) return presetDrop.handler(paths);   // ses penceresi acikken: ses resmi
    const pdf = paths.find((path) => /\.pdf$/i.test(path));
    if (pdf) return openPdfImport(pdf, 'reading');              // F138: taranmis PDF'den kitap
    const result = await act('shelf_add', paths);
    if (result) app.shelf = result.books;
  });

  async function open(entry) {
    const data = await act('reader_open', entry.id);
    if (!data) return;
    app.reading = { book: data, section: data.position.section, offset: data.position.offset, percent: data.percent };
  }

  async function close() {
    app.reading = { book: null, section: 0, offset: 0, percent: 0 };
    const books = await act('shelf_list');
    if (books) app.shelf = books;
  }
</script>

{#if app.reading.book}
  <Reader onclose={close} />
{:else}
  <Shelf onopen={open} />
{/if}
