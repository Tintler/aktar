<script>
  // Bu belgeye sor: tek belge sohbeti; s.N atiflari goruntuleyiciyi o sayfaya goturur.
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import { app, act } from '../lib/state.svelte.js';
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
    const state = await act('doc_ask', value);
    if (state && app.document) app.document.chat = state;
  }
</script>

<aside class="panel">
  <div class="head" use:dragArea><span class="pill">Bu belgeye sor</span></div>
  {#if chat}
    <div class="messages" bind:this={scroller}>
      <ChatMessages entries={chat.entries} single oncite={(item) => (app.docSeek = { page: item.start })} />
    </div>
    {#if chat.note}<div class="note">{#if !chat.ready && !chat.note.startsWith('Bu belge')}<Icon name="loader" size={13} spin />{/if}{chat.note}</div>{/if}
    <form class="ask" onsubmit={(e) => { e.preventDefault(); ask(); }}>
      <input bind:value={question} disabled={!chat.enabled} placeholder="Belgeye sor…" />
      <button class="send" type="submit" title="Gönder" disabled={!chat.enabled || !question.trim()}><Icon name="send" size={16} /></button>
    </form>
    <p class="foot">Yapay zekâ yanlış bilgi verebilir; sayfa atıflarına tıklayıp belgede doğrulayın.</p>
  {/if}
</aside>

<style>
  .panel { width: 380px; flex: none; height: 100%; background: var(--panel); display: flex; flex-direction: column; padding: 14px 16px 12px; min-height: 0; gap: 10px; }
  .head { display: flex; align-items: center; padding: 30px 0 4px; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .messages { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 4px 8px 0; }
  .note { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--dim); }
  .ask { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 5px 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid transparent; }
  .ask:focus-within { border-color: var(--outline); background: var(--surface-hover); }
  .ask input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; }
  .ask input::placeholder { color: var(--dim); }
  .send { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
  .foot { font-size: 11px; color: var(--dim); }
</style>
