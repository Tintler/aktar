<script>
  // Bu belgeye sor: tek belge sohbeti; s.N atiflari goruntuleyiciyi o sayfaya goturur.
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import ThinkToggle from './ThinkToggle.svelte';
  import { app, act } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { dragArea } from '../lib/frame.svelte.js';

  const chat = $derived(app.document?.chat);
  let question = $state('');
  let scroller = $state();

  $effect(() => {
    chat?.entries.length;
    if (scroller) queueMicrotask(() => (scroller.scrollTop = scroller.scrollHeight));
  });

  async function ask() {
    const value = question.trim();
    if (!value || !chat?.enabled) return;
    question = '';
    const state = await act('doc_ask', value, app.think);
    if (state && app.document) app.document.chat = state;
  }

  async function clear() {
    const ok = await confirm({ title: 'Sohbeti temizle', message: 'Bu belgenin sohbeti ve kayıtlı geçmişi silinsin mi?', ok: 'Temizle', danger: true });
    if (!ok) return;
    const state = await act('doc_clear_chat');
    if (state && app.document) app.document.chat = state;
  }
</script>

<aside class="panel">
  <div class="head" use:dragArea>
    <span class="pill">Bu belgeye sor</span>
    <span class="grow"></span>
    <button class="icon-btn sm" title="Sohbeti temizle" disabled={!chat || chat.asking || !chat.entries.some((e) => e.kind === 'user')} onclick={clear}><Icon name="trash" size={15} /></button>
  </div>
  {#if chat}
    <div class="messages" bind:this={scroller}>
      <ChatMessages entries={chat.entries} single oncite={(item) => (app.docSeek = { page: item.start })} />
    </div>
    {#if chat.note}<div class="note">{#if !chat.ready && !chat.note.startsWith('Bu belge')}<Icon name="loader" size={13} spin />{/if}{chat.note}</div>{/if}
    <form class="ask" onsubmit={(e) => { e.preventDefault(); ask(); }}>
      <input bind:value={question} disabled={!chat.enabled} placeholder="Belgeye sor…" />
      <ThinkToggle />
      <button class="send" type="submit" title="Gönder" disabled={!chat.enabled || !question.trim()}><Icon name="send" size={16} /></button>
    </form>
  {/if}
</aside>

<style>
  .panel { width: 380px; flex: none; height: 100%; background: var(--panel); display: flex; flex-direction: column; padding: 14px 16px 12px; min-height: 0; gap: 10px; }
  .head { display: flex; align-items: center; gap: 4px; padding: 30px 0 4px; }
  .grow { flex: 1; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .messages { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 4px 8px 0; }
  .note { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--dim); }
  .ask { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 5px 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid var(--field-border); transition: border-color .15s, box-shadow .15s; }
  .ask:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .ask input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; }
  .ask input::placeholder { color: var(--dim); }
  .send { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
</style>
