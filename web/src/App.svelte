<script>
  import Icon from './lib/Icon.svelte';
  import Logo from './components/Logo.svelte';
  import TitleBar from './components/TitleBar.svelte';
  import ConfirmHost from './components/ConfirmHost.svelte';
  import ReviewModal from './components/ReviewModal.svelte';
  import BookReviewModal from './components/BookReviewModal.svelte';
  import PdfImportModal from './components/PdfImportModal.svelte';
  import BookArt from './components/BookArt.svelte';
  import SetupWizard from './components/SetupWizard.svelte';
  import Collections from './components/Collections.svelte';
  import ChatPanel from './components/ChatPanel.svelte';
  import MenuHost from './components/MenuHost.svelte';
  import TaskTray from './components/TaskTray.svelte';
  import RuntimePanel from './components/RuntimePanel.svelte';
  import Library from './views/Library.svelte';
  import Translate from './views/Translate.svelte';
  import Books from './views/Books.svelte';
  import Reading from './views/Reading.svelte';
  import TextSpeech from './views/TextSpeech.svelte';
  import Gazete from './views/Gazete.svelte';
  import Game from './views/Game.svelte';
  import PdfReview from './views/PdfReview.svelte';
  import Settings from './views/Settings.svelte';
  import Player from './views/Player.svelte';
  import VideoChat from './components/VideoChat.svelte';
  import Document from './views/Document.svelte';
  import DocChat from './components/DocChat.svelte';
  import Chat from './views/Chat.svelte';
  import Files from './views/Files.svelte';
  import Console from './views/Console.svelte';
  import Subscriptions from './views/Subscriptions.svelte';
  import { app, init, toasts, dismissToast, go, toggleSidebar } from './lib/state.svelte.js';
  import { call } from './lib/api.js';
  import { frame, initFrame, dragArea } from './lib/frame.svelte.js';

  init();
  initFrame();

  const nav = [
    ['chat', 'Sohbet', 'message'],
    ['library', 'Kütüphane', 'library'],
    ['files', 'Dosya incele', 'fileSearch'],
    ['game', 'Ekran Çeviri', 'screentext'],
    ['translate', 'Altyazı Çevir', 'languages'],
    ['books', 'Kitap Çevir', 'bookA'],
    ['reading', 'Okuma', 'book'],
    ['speech', 'Metinden ses', 'waveform'],
    ['gazete', 'Gazete', 'newspaper'],
    ['subscriptions', 'Abonelikler', 'creditCard'],
    ['console', 'Konsol', 'terminal'],
  ];
  // Oynatici / belge acikken, dosya nereden acildiysa o menu ogesi vurgulanir.
  const active = (key) => app.view === key
    || (['player', 'document'].includes(app.view) && key === (app.fileOrigin === 'files' ? 'files' : 'library'));
  const issues = $derived(app.view === 'console' ? 0 : app.log.filter((line) => /\b(HATA|Hata|hata)\b/.test(line)).length);
  let seenIssues = $state(0);
  $effect(() => {
    if (app.view === 'console') seenIssues = app.log.filter((line) => /\b(HATA|Hata|hata)\b/.test(line)).length;
  });
  $effect(() => {
    if (app.log.length === 0) seenIssues = 0;
  });

  // Geri/ileri: sayfalar arasinda gezinme gecmisi (Deeverse ust cubugu gibi).
  let history = $state(['library']);
  let position = $state(0);
  let moving = false;
  $effect(() => {
    const view = app.view;
    if (moving) { moving = false; return; }
    if (history[position] === view) return;
    history = [...history.slice(0, position + 1), view];
    position = history.length - 1;
  });
  function step(delta) {
    const next = position + delta;
    if (next < 0 || next >= history.length) return;
    position = next;
    moving = true;
    app.view = history[next];
  }

  const panelOpen = $derived((app.view === 'library' && !!app.library.slug && !app.libraryView.home && app.libraryView.chatOpen)
    || (app.view === 'player' && !!app.player && !app.dubEditor) || (app.view === 'document' && !!app.document));
  const models = $derived(app.models);
  const modelListed = $derived((models.names ?? []).includes(models.model));
  let runtimeOpen = $state(false);
  let lmBox = $state(null);

  let dragging = $state(false);
  const hasFiles = (event) => [...(event.dataTransfer?.types ?? [])].includes('Files');
  // Birakilan dosyalari desktop.py tam yollariyla alir; sayfa yalnizca birakmaya izin verir.
  function dragover(event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragging = true;
  }
  const dropHint = $derived(app.view === 'translate' ? 'Videoyu açmak için bırakın'
    : app.view === 'books' ? 'EPUB, PDF ya da çeviri klasörünü açmak için bırakın'
    : app.view === 'reading' ? "E-kitabı (EPUB, MOBI, AZW3, FB2) ya da PDF'yi kitaplığa eklemek için bırakın"
    : app.view === 'files' ? 'İncelemek için bırakın'
    : app.view === 'speech' ? 'Metin dosyasını (.txt) açmak için bırakın'
    : app.view === 'subscriptions' ? 'Logo olarak eklemek için bırakın' : 'Koleksiyona eklemek için bırakın');

  async function submitBookReview(values) {
    app.books.review = null;
    await call('book_submit_review', values);
  }

  async function submitReview(values) {
    app.review = null;
    await call('submit_review', values);
  }
</script>

<svelte:window ondragover={dragover} ondragleave={(e) => { if (!e.relatedTarget) dragging = false; }}
  ondrop={(e) => { e.preventDefault(); dragging = false; }} />

{#if dragging}
  <div class="dropzone"><div><Icon name="upload" size={40} /><b>{dropHint}</b></div></div>
{/if}

<div class="shell">
  <aside class="side" class:mini={app.sideCollapsed}>
    <div class="brand" use:dragArea>
      <button class="logo" title={app.sideCollapsed ? 'Menüyü genişlet' : 'Menüyü daralt'} onclick={toggleSidebar}>
        <Logo size={30} /><span class="word">aktar<i>.</i></span>
      </button>
    </div>
    <nav>
      {#each nav as [key, label, icon]}
        <button class="nav" class:on={active(key)} title={app.sideCollapsed ? label : null}
          onclick={() => { if (key === 'library') app.libraryView.home = true; go(key); }}>
          <span class="ic"><Icon name={icon} size={22} />{#if key === 'console' && issues > seenIssues}<i class="badge-dot"></i>{/if}</span>
          <span class="label-text">{label}</span>
        </button>
      {/each}
    </nav>
    <div class="rule"></div>
    <div class="side-body" inert={app.sideCollapsed}><Collections /></div>
    <div class="lm" class:on={runtimeOpen} bind:this={lmBox}>
      <div class="row">
        <!-- F183: tiklayinca bellekteki modeller paneli acilir (ayri sayfa degil). -->
        <button class="lm-open" title={(models.message ? models.message + '\n' : '') + 'Bellekteki modeller ve ses motoru'}
          aria-expanded={runtimeOpen} onclick={() => (runtimeOpen = !runtimeOpen)}>
          <span class="dot {models.state === 'probing' ? 'wait' : models.state === 'failed' ? 'bad' : modelListed ? '' : 'wait'}"></span>
          <span class="st">{models.state === 'probing' ? 'Model sunucusu sorgulanıyor…' : models.state === 'failed' ? 'Model sunucusu bağlı değil' : modelListed ? 'Model sunucusu bağlı' : 'Model listede yok'}</span>
        </button>
        <button class="icon-btn sm" title="Yeniden sorgula" onclick={() => call('refresh_models')}><Icon name="refresh" size={14} /></button>
      </div>
    </div>
  </aside>

  <main class:controls={frame.custom && !panelOpen}>
    <header class="top" use:dragArea>
      <button class="icon-btn filled sm" title="Geri" disabled={position === 0} onclick={() => step(-1)}><Icon name="back" size={16} /></button>
      <button class="icon-btn filled sm" title="İleri" disabled={position >= history.length - 1} onclick={() => step(1)}><Icon name="forward" size={16} /></button>
      <div class="grow"></div>
      {#if app.view === 'library' && app.library.slug && !app.libraryView.home && !app.libraryView.chatOpen}
        <button class="btn sm" title="Koleksiyona sor panelini aç" onclick={() => (app.libraryView.chatOpen = true)}><Icon name="message" size={15} />Koleksiyona sor</button>
      {/if}
      <TaskTray />
      <button class="icon-btn" class:on={app.view === 'settings'} title="Ayarlar" onclick={() => go('settings')}><Icon name="settings" size={20} /></button>
    </header>
    <div class="view">
      {#if app.view === 'library'}<Library />
      {:else if app.view === 'chat'}<Chat />
      {:else if app.view === 'files'}<Files />
      {:else if app.view === 'console'}<Console />
      {:else if app.view === 'subscriptions'}<Subscriptions />
      {:else if app.view === 'translate'}<Translate />
      {:else if app.view === 'books'}<Books />
      {:else if app.view === 'reading'}<Reading />
      {:else if app.view === 'speech'}<TextSpeech />
      {:else if app.view === 'gazete'}<Gazete />
      {:else if app.view === 'game'}<Game />
      {:else if app.view === 'pdfreview' && app.pdfReview}{#key app.pdfReview.path}<PdfReview />{/key}
      {:else if app.view === 'player'}<Player />
      {:else if app.view === 'document'}<Document />
      {:else}<Settings />{/if}
    </div>
  </main>
  {#if panelOpen}{#if app.view === 'player'}<VideoChat />{:else if app.view === 'document'}<DocChat />{:else}<ChatPanel />{/if}{/if}
</div>
<TitleBar />
<MenuHost />
<RuntimePanel bind:open={runtimeOpen} anchor={lmBox} />

{#if app.busy}
  <!-- Video/belge acilirken: tiklamalar engellenir, ne olup bittigi gorunur. -->
  <div class="busy" role="status" aria-live="polite"><div class="card"><Icon name="loader" size={30} spin /><b>{app.busy}</b></div></div>
{/if}

{#if app.review}<ReviewModal data={app.review} onsubmit={submitReview} />{/if}
{#if app.books.review}<BookReviewModal data={app.books.review} onsubmit={submitBookReview} />{/if}
{#if app.pdfImport?.open}<PdfImportModal />{/if}
{#if app.artModal}<BookArt book={app.artModal.book} title={app.artModal.title} onclose={() => (app.artModal = null)} />{/if}
{#if app.setup}<SetupWizard />{/if}
<ConfirmHost />

<div class="toasts">
  {#each toasts as t (t.id)}
    <div class="toast {t.kind}">
      <Icon name={t.kind === 'error' || t.kind === 'warning' ? 'alert' : t.kind === 'ok' ? 'check' : 'info'} size={16} /><span class="selectable">{t.message}</span>
      <button class="close" title="Kapat" onclick={() => dismissToast(t.id)}><Icon name="x" size={14} /></button>
    </div>
  {/each}
</div>

<style>
  .shell { display: flex; height: 100%; }
  /* Sol menu: logoya tiklayinca akordiyon gibi yalnizca simgelere daralir. */
  .side { width: 300px; flex: none; overflow: hidden; white-space: nowrap;
    transition: width .32s cubic-bezier(.22, .8, .24, 1), padding .32s cubic-bezier(.22, .8, .24, 1); }
  @media (max-width: 1500px) { .side { width: 260px; } }
  .side.mini { width: 76px; }
  .side { background: var(--panel); display: flex; flex-direction: column; padding: 14px 12px 12px; min-height: 0; }
  .brand { display: flex; align-items: center; padding: 0 0 14px; }
  .logo { display: flex; align-items: center; gap: 10px; padding: 4px 11px; max-width: 100%; overflow: hidden; border-radius: 10px; font-weight: 700; font-size: 21px; letter-spacing: -.01em; }
  .logo:hover { background: var(--surface-hover); }
  .logo :global(svg) { flex: none; transition: transform .32s cubic-bezier(.22, .8, .24, 1); }
  .logo:active :global(svg) { transform: scale(.92); }
  .logo i { color: var(--accent); font-style: normal; }
  .word, .label-text, .side-body, .lm .st, .lm .icon-btn, .rule { transition: opacity .2s ease; }
  nav { display: flex; flex-direction: column; gap: 2px; }
  .nav { display: flex; align-items: center; gap: 16px; padding: 10px 14px; border-radius: 8px; color: var(--secondary); font-weight: 700; font-size: 16px; width: 100%; text-align: left; }
  .nav:hover { color: var(--text); }
  .nav.on { color: var(--text); background: var(--surface); }
  .nav.on .ic :global(svg) { color: var(--accent); }
  .ic { position: relative; display: grid; flex: none; }
  .badge-dot { position: absolute; top: -2px; right: -3px; width: 8px; height: 8px; border-radius: 50%; background: var(--danger); box-shadow: 0 0 0 2px var(--panel); }
  .rule { height: 1px; background: var(--outline); margin: 14px 6px; }
  .side-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .mini .word, .mini .label-text, .mini .side-body, .mini .lm .st, .mini .lm .icon-btn { opacity: 0; pointer-events: none; }
  .mini .rule { opacity: .6; }
  .mini .lm { background: transparent; padding-left: 22px; }
  .lm { margin-top: 8px; padding: 10px 12px; border-radius: 10px; background: var(--surface); font-size: 12px; }
  .lm .row { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; }
  .lm .st { flex: 1; min-width: 0; text-align: left; overflow: hidden; text-overflow: ellipsis; }
  .lm-open { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; margin: -6px -4px; padding: 6px 4px; border-radius: 8px;
    font: inherit; color: inherit; cursor: pointer; }
  .lm-open:hover .st, .lm.on .st { color: var(--accent); }
  .lm.on { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent); }
  .lm .icon-btn { margin: -4px -6px -4px 0; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 25%, transparent); flex: none; }
  .dot.wait { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 25%, transparent); }
  .dot.bad { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 25%, transparent); }

  main { flex: 1; min-width: 0; min-height: 0; height: 100%; display: flex; flex-direction: column; }
  /* Pencere dugmeleri sag ustte sabit: panel kapaliyken ust cubuk onlara yer birakir. */
  main.controls .top { padding-right: 150px; }
  .top { height: 64px; flex: none; display: flex; align-items: center; gap: 8px; padding: 0 8px 0 32px; }
  .top .grow { flex: 1; align-self: stretch; }
  .top .icon-btn.on { color: var(--accent); }
  .view { flex: 1; min-height: 0; }

  .dropzone { position: fixed; inset: 0; z-index: 70; background: rgba(0, 0, 0, .55); display: grid; place-items: center; pointer-events: none; }
  .dropzone div { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 40px 56px; border: 2px dashed var(--accent);
    border-radius: 20px; color: var(--accent); background: var(--panel); font-size: 16px; }
  .busy { position: fixed; inset: 0; z-index: 85; display: grid; place-items: center; background: rgba(0, 0, 0, .45); cursor: progress; }
  .busy .card { display: flex; align-items: center; gap: 14px; padding: 20px 28px; color: var(--accent); }
  .busy b { color: var(--text); font-size: 15px; }
  .toasts { position: fixed; right: 20px; bottom: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 60; max-width: 440px; }
  .toast { display: flex; gap: 10px; align-items: flex-start; padding: 12px 14px; border-radius: 12px; background: var(--overlay); border: 1px solid var(--outline); box-shadow: 0 8px 28px var(--shadow); font-size: 13px; }
  .toast > span { flex: 1; overflow-wrap: anywhere; }
  .toast .close { color: var(--dim); margin: -2px -4px 0 0; display: grid; place-items: center; }
  .toast .close:hover { color: var(--text); }
  .toast.ok > :global(svg) { color: var(--ok); }
  .toast.info > :global(svg) { color: var(--accent); }
  .toast.error { border-color: color-mix(in srgb, var(--danger) 50%, var(--outline)); }
  .toast.error > :global(svg) { color: var(--danger); }
  .toast.warning { border-color: color-mix(in srgb, var(--warning) 50%, var(--outline)); }
  .toast.warning > :global(svg) { color: var(--warning); }
</style>
