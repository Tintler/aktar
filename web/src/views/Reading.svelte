<script>
  // Okuma (Cevirgec): kitaplik ya da acik kitap.
  import Shelf from './Shelf.svelte';
  import Reader from './Reader.svelte';
  import { app, act, onDrop } from '../lib/state.svelte.js';

  // Pencereye birakilan EPUB'lar kitapliga eklenir.
  onDrop('reading', async (paths) => {
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
