<script>
  // Konsol: uygulamanin tum gunlugu (ceviri, toplu hazirlik, OCR, Whisper, sohbet hatalari).
  import Icon from '../lib/Icon.svelte';
  import { app, toast, clearLog } from '../lib/state.svelte.js';

  let query = $state('');
  let onlyIssues = $state(false);
  let follow = $state(true);
  let box = $state();

  const ISSUE = /\b(HATA|Hata|hata|UYARI|Uyarı|uyarı|başarısız|alınamadı|kurulamadı|okunamadı|reddedildi|zaman aşımı|zaman asimi)/;
  const issue = (line) => ISSUE.test(line);
  const lines = $derived.by(() => {
    const needle = query.trim().toLocaleLowerCase('tr');
    return app.log.filter((line) => (!onlyIssues || issue(line)) && (!needle || line.toLocaleLowerCase('tr').includes(needle)));
  });
  const issues = $derived(app.log.filter(issue).length);

  $effect(() => {
    lines.length;
    if (box && follow) queueMicrotask(() => (box.scrollTop = box.scrollHeight));
  });

  // Kullanici yukari kaydirinca otomatik takip durur, en alta inince yeniden baslar.
  function scrolled() {
    follow = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      toast('Günlük panoya kopyalandı.', 'ok');
    } catch {
      toast('Panoya kopyalanamadı.', 'error');
    }
  }
</script>

<section class="page">
  <div class="page-head">
    <h1>Konsol</h1>
    <label class="search">
      <Icon name="search" size={16} />
      <input bind:value={query} placeholder="Günlükte ara…" />
      {#if query}<button class="icon-btn sm" title="Temizle" onclick={() => (query = '')}><Icon name="x" size={14} /></button>{/if}
    </label>
    <button class="chip" class:on={onlyIssues} onclick={() => (onlyIssues = !onlyIssues)}>
      Hatalar ve uyarılar{#if issues}<span class="count">{issues}</span>{/if}</button>
    <button class="btn sm" disabled={!lines.length} onclick={copy}><Icon name="copy" size={14} />Kopyala</button>
    <button class="btn sm" disabled={!app.log.length} onclick={clearLog}><Icon name="trash" size={14} />Temizle</button>
  </div>
  <div class="page-body body">
    <div class="console selectable" bind:this={box} onscroll={scrolled}>
      {#each lines as line}
        <div class="line" class:bad={issue(line)}>{line}</div>
      {:else}
        <div class="empty">{app.log.length ? 'Filtreyle eşleşen satır yok.' : 'Henüz günlük yok. Çeviri, hazırlık ve sohbet işlerinin ayrıntıları burada görünür.'}</div>
      {/each}
    </div>
    {#if !follow}
      <button class="jump btn sm" onclick={() => { follow = true; box.scrollTop = box.scrollHeight; }}><Icon name="down" size={14} />En alta git</button>
    {/if}
  </div>
</section>

<style>
  .search { width: 280px; height: 34px; display: flex; align-items: center; gap: 8px; padding: 0 4px 0 12px; border-radius: 999px;
    background: var(--surface); color: var(--secondary); border: 1px solid var(--field-border); transition: border-color .15s, box-shadow .15s; }
  .search:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .search input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 13px; color: var(--text); }
  .search input::placeholder { color: var(--dim); }
  .count { margin-left: 6px; padding: 0 6px; border-radius: 999px; font-size: 11px; background: var(--danger); color: #fff; }
  .body { display: flex; flex-direction: column; position: relative; }
  .console { flex: 1; min-height: 0; overflow: auto; padding: 12px 14px; background: var(--panel); border: 1px solid var(--outline); border-radius: 12px;
    font: 12px/1.65 var(--mono); color: var(--secondary); }
  .line { white-space: pre-wrap; overflow-wrap: anywhere; }
  .line.bad { color: var(--danger); }
  .empty { color: var(--dim); font-family: inherit; }
  .jump { position: absolute; right: 52px; bottom: 40px; box-shadow: 0 6px 18px var(--shadow); }
</style>
