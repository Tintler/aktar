<script>
  import Icon from './lib/Icon.svelte';
  import Logo from './components/Logo.svelte';
  import TitleBar from './components/TitleBar.svelte';
  import ConfirmHost from './components/ConfirmHost.svelte';
  import ReviewModal from './components/ReviewModal.svelte';
  import Collections from './components/Collections.svelte';
  import ChatPanel from './components/ChatPanel.svelte';
  import MenuHost from './components/MenuHost.svelte';
  import Library from './views/Library.svelte';
  import Translate from './views/Translate.svelte';
  import Settings from './views/Settings.svelte';
  import Player from './views/Player.svelte';
  import VideoChat from './components/VideoChat.svelte';
  import { app, init, toasts, dismissToast, go } from './lib/state.svelte.js';
  import { call } from './lib/api.js';
  import { frame, initFrame, dragArea } from './lib/frame.svelte.js';

  init();
  initFrame();

  const nav = [
    ['library', 'Kütüphane', 'library'],
    ['translate', 'Altyazı Çevir', 'languages'],
  ];

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

  const panelOpen = $derived((app.view === 'library' && !!app.library.slug && app.libraryView.chatOpen)
    || (app.view === 'player' && !!app.player));
  const models = $derived(app.models);
  const modelListed = $derived((models.names ?? []).includes(models.model));

  let dragging = $state(false);
  const hasFiles = (event) => [...(event.dataTransfer?.types ?? [])].includes('Files');
  // Birakilan dosyalari desktop.py tam yollariyla alir; sayfa yalnizca birakmaya izin verir.
  function dragover(event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragging = true;
  }
  const dropHint = $derived(app.view === 'translate' ? 'Videoyu açmak için bırakın' : 'Koleksiyona eklemek için bırakın');

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
  <aside class="side">
    <div class="brand" use:dragArea><Logo size={30} /><span>aktar<i>.</i></span></div>
    <nav>
      {#each nav as [key, label, icon]}
        <button class="nav" class:on={app.view === key || (key === 'library' && app.view === 'player')} onclick={() => go(key)}><Icon name={icon} size={22} /><span>{label}</span></button>
      {/each}
    </nav>
    <div class="rule"></div>
    <div class="side-body"><Collections /></div>
    <div class="lm" title={models.message || ''}>
      <div class="row">
        <span class="dot {models.state === 'probing' ? 'wait' : models.state === 'failed' ? 'bad' : modelListed ? '' : 'wait'}"></span>
        <span class="st">{models.state === 'probing' ? 'LM Studio sorgulanıyor…' : models.state === 'failed' ? 'LM Studio bağlı değil' : modelListed ? 'LM Studio bağlı' : 'Model listede yok'}</span>
        <button class="icon-btn sm" title="Yeniden sorgula" onclick={() => call('refresh_models')}><Icon name="refresh" size={14} /></button>
      </div>
      <div class="m selectable ellipsis">{models.model}</div>
    </div>
  </aside>

  <main class:controls={frame.custom && !panelOpen}>
    <header class="top" use:dragArea>
      <button class="icon-btn filled sm" title="Geri" disabled={position === 0} onclick={() => step(-1)}><Icon name="back" size={16} /></button>
      <button class="icon-btn filled sm" title="İleri" disabled={position >= history.length - 1} onclick={() => step(1)}><Icon name="forward" size={16} /></button>
      <div class="grow"></div>
      {#if app.view === 'library' && app.library.slug && !app.libraryView.chatOpen}
        <button class="btn sm" title="Koleksiyona sor panelini aç" onclick={() => (app.libraryView.chatOpen = true)}><Icon name="message" size={15} />Koleksiyona sor</button>
      {/if}
      <button class="icon-btn" class:on={app.view === 'settings'} title="Ayarlar" onclick={() => go('settings')}><Icon name="settings" size={20} /></button>
    </header>
    <div class="view">
      {#if app.view === 'library'}<Library />
      {:else if app.view === 'translate'}<Translate />
      {:else if app.view === 'player'}<Player />
      {:else}<Settings />{/if}
    </div>
  </main>
  {#if panelOpen}{#if app.view === 'player'}<VideoChat />{:else}<ChatPanel />{/if}{/if}
</div>
<TitleBar />
<MenuHost />

{#if app.review}<ReviewModal data={app.review} onsubmit={submitReview} />{/if}
<ConfirmHost />

<div class="toasts">
  {#each toasts as t (t.id)}
    <div class="toast {t.kind}">
      <Icon name={t.kind === 'error' ? 'alert' : t.kind === 'ok' ? 'check' : 'info'} size={16} /><span class="selectable">{t.message}</span>
      <button class="close" title="Kapat" onclick={() => dismissToast(t.id)}><Icon name="x" size={14} /></button>
    </div>
  {/each}
</div>

<style>
  .shell { display: flex; height: 100%; }
  .side { width: 300px; flex: none; }
  @media (max-width: 1500px) { .side { width: 260px; } }
  .side { background: var(--panel); display: flex; flex-direction: column; padding: 14px 12px 12px; min-height: 0; }
  .brand { display: flex; align-items: center; gap: 10px; padding: 4px 14px 18px; font-weight: 700; font-size: 21px; letter-spacing: -.01em; }
  .brand i { color: var(--accent); font-style: normal; }
  nav { display: flex; flex-direction: column; gap: 2px; }
  .nav { display: flex; align-items: center; gap: 16px; padding: 10px 14px; border-radius: 8px; color: var(--secondary); font-weight: 700; font-size: 16px; width: 100%; text-align: left; }
  .nav:hover { color: var(--text); }
  .nav.on { color: var(--text); background: var(--surface); }
  .nav.on :global(svg) { color: var(--accent); }
  .rule { height: 1px; background: var(--outline); margin: 14px 6px; }
  .side-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .lm { margin-top: 8px; padding: 10px 12px; border-radius: 10px; background: var(--surface); font-size: 12px; }
  .lm .row { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; }
  .lm .st { flex: 1; min-width: 0; }
  .lm .icon-btn { margin: -4px -6px -4px 0; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 25%, transparent); flex: none; }
  .dot.wait { background: var(--warning); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warning) 25%, transparent); }
  .dot.bad { background: var(--danger); box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 25%, transparent); }
  .lm .m { color: var(--secondary); margin-top: 4px; }

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
  .toasts { position: fixed; right: 20px; bottom: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 60; max-width: 440px; }
  .toast { display: flex; gap: 10px; align-items: flex-start; padding: 12px 14px; border-radius: 12px; background: var(--overlay); border: 1px solid var(--outline); box-shadow: 0 8px 28px var(--shadow); font-size: 13px; }
  .toast > span { flex: 1; overflow-wrap: anywhere; }
  .toast .close { color: var(--dim); margin: -2px -4px 0 0; display: grid; place-items: center; }
  .toast .close:hover { color: var(--text); }
  .toast.ok > :global(svg) { color: var(--ok); }
  .toast.info > :global(svg) { color: var(--accent); }
  .toast.error { border-color: color-mix(in srgb, var(--danger) 50%, var(--outline)); }
  .toast.error > :global(svg) { color: var(--danger); }
</style>
