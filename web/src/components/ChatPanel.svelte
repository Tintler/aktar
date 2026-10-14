<script>
  // Koleksiyona sor: Deeverse'teki sag panel (kuyruk/sozler) yerinde. Indeksli dosyalarda atifli sohbet.
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import { app, act, refreshChat, selectedPaths, openFile } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { dragArea } from '../lib/frame.svelte.js';

  const chat = $derived(app.chat);
  const view = app.libraryView;
  let question = $state('');
  let scroller = $state();

  $effect(() => {
    chat?.entries.length;
    chat?.busy;
    if (scroller) queueMicrotask(() => (scroller.scrollTop = scroller.scrollHeight));
  });

  async function ask(text = question) {
    const value = text.trim();
    if (!value || !chat?.enabled) return;
    question = '';
    const state = await act('chat_ask', value, view.scope === 'selected' ? selectedPaths() : null);
    if (state) app.chat = state;
  }

  async function clear() {
    const ok = await confirm({ title: 'Sohbeti temizle', message: 'Bu koleksiyonun sohbeti ve kayıtlı geçmişi silinsin mi?', ok: 'Temizle', danger: true });
    if (ok) app.chat = await act('chat_clear');
  }

  function setScope(scope) {
    view.scope = scope;
    refreshChat();
  }
</script>

<aside class="panel">
  <div class="head" use:dragArea>
    <span class="pill">Koleksiyona sor</span>
    <span class="grow"></span>
    <button class="icon-btn sm" title="Sohbeti temizle" disabled={!chat || chat.busy} onclick={clear}><Icon name="trash" size={15} /></button>
    <button class="icon-btn sm" title="Paneli kapat" onclick={() => (view.chatOpen = false)}><Icon name="x" size={16} /></button>
  </div>
  <div class="scope">
    <button class="chip" class:on={view.scope === 'all'} onclick={() => setScope('all')}>Tüm koleksiyon</button>
    <button class="chip" class:on={view.scope === 'selected'} onclick={() => setScope('selected')}>Seçili dosyalar{view.selected.length ? ` · ${view.selected.length}` : ''}</button>
  </div>
  <div class="messages" bind:this={scroller}>
    {#if chat?.overview}
      <div class="overview">
        <span class="label">Koleksiyon özeti · {chat.overview.videos} dosya</span>
        <p class="selectable">{chat.overview.summary}</p>
        {#if chat.overview.topics.length}
          <div class="topics">{#each chat.overview.topics as topic}<span class="badge">{topic}</span>{/each}</div>
        {/if}
        {#each chat.overview.questions as q}
          <button class="suggest" disabled={!chat.enabled} onclick={() => ask(q)}><Icon name="forward" size={14} />{q}</button>
        {/each}
      </div>
    {/if}
    <ChatMessages entries={chat?.entries ?? []} oncite={(item) => openFile(item, item.start)} />
  </div>
  <div class="note">{chat?.note ?? ''}</div>
  <form class="ask" onsubmit={(e) => { e.preventDefault(); ask(); }}>
    <input bind:value={question} disabled={!chat?.enabled} placeholder={view.scope === 'selected' ? 'Seçili dosyalara sor…' : 'Tüm dosyalara sor…'} />
    <button class="send" type="submit" title="Gönder" disabled={!chat?.enabled || !question.trim()}><Icon name="send" size={16} /></button>
  </form>
</aside>

<style>
  .panel { width: 360px; flex: none; height: 100%; background: var(--panel); display: flex; flex-direction: column; padding: 14px 16px 12px; min-height: 0; }
  .head { display: flex; align-items: center; gap: 4px; padding: 30px 0 10px; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .grow { flex: 1; }
  .scope { display: flex; gap: 6px; padding-bottom: 12px; }
  .scope .chip { height: 28px; font-size: 12px; padding: 0 12px; }
  .messages { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 4px 4px 12px 0; }
  .overview { background: var(--surface); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; min-width: 0; overflow-wrap: anywhere; }
  .overview p { font-size: 13px; color: var(--secondary); line-height: 1.55; }
  .topics { display: flex; flex-wrap: wrap; gap: 4px; }
  /* uzun konu adlari paneli genisletmesin: rozet satira sigmazsa alt satira kirilir */
  .topics .badge { white-space: normal; max-width: 100%; line-height: 1.4; }
  .suggest { display: flex; align-items: flex-start; gap: 8px; text-align: left; font-size: 12.5px; color: var(--accent); padding: 3px 0; }
  .suggest :global(svg) { margin-top: 2px; }
  .suggest:not(:disabled):hover { text-decoration: underline; }
  .note { font-size: 12px; color: var(--dim); padding: 6px 2px; }
  .ask { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 5px 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid var(--field-border); transition: border-color .15s, box-shadow .15s; }
  .ask:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .ask input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; }
  .ask input::placeholder { color: var(--dim); }
  .send { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
</style>
