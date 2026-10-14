<script>
  // Kutuphane 2. asamada Svelte'ye tasinacak; simdilik yer tutucu.
  import Icon from '../lib/Icon.svelte';
  import { onDrop, toast } from '../lib/state.svelte.js';

  onDrop('library', () => toast('Kütüphane henüz yeni arayüze taşınmadı.', 'info'));
</script>

<section class="page">
  <div class="page-head"><h1>Kütüphane</h1></div>
  <div class="page-body">
    <div class="card empty-card">
      <Icon name="library" size={36} />
      <b>Kütüphane yeni arayüze taşınıyor</b>
      <span class="dim">Koleksiyonlar, dosya tablosu ve koleksiyona sor bir sonraki aşamada burada olacak.</span>
    </div>
  </div>
</section>

<style>
  .empty-card { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 64px 24px; color: var(--secondary); text-align: center; }
  .empty-card b { color: var(--text); font-size: 18px; }
</style>
