<script>
  // Kitaba sor (F146): okuyucunun sag panelinde okunan kitabin sohbeti. Cevaptaki s.N atfi kitabi N. bolume
  // goturur. "Okudugum yere kadar" acikken acik bolumden sonrasi modele gitmez (surprizler bozulmaz).
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import ThinkToggle from './ThinkToggle.svelte';
  import MicButton from './MicButton.svelte';
  import TemplatePicker from './TemplatePicker.svelte';
  import Toggle from './Toggle.svelte';
  import { templateFor } from '../lib/templates.svelte.js';
  import { app, act, savePref } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';

  // fraction: acik bolumun okunan orani (ekranin alt kenarina kadar, 0-1) -- uzun bolumlerde ilerleme bazli sinir
  let { book, section = 0, fraction = 1, ongo, onclose } = $props();

  const chat = $derived(app.bookChat?.book === book.id ? app.bookChat.chat : null);
  let question = $state('');
  let scroller = $state();
  let spoilers = $state(app.prefs.book_chat?.until_here ?? true);

  const opened = Date.now();
  act('reader_chat_open', book.id).then((state) => {
    // Bu arada gelen 'reader_chat' olayi daha yenidir; cevap onu ezmesin.
    if (state && !(app.bookChat?.book === state.book && app.bookChat.at >= opened)) app.bookChat = state;
  });

  $effect(() => {
    chat?.entries.length;
    if (scroller) queueMicrotask(() => (scroller.scrollTop = scroller.scrollHeight));
  });

  function setSpoilers(value) {
    savePref({ book_chat: { until_here: value } });
  }

  async function ask(text = question, think = app.think) {
    const value = text.trim();
    if (!value || !chat?.enabled) return;
    question = '';
    const state = await act('reader_chat_ask', value, think, templateFor('doc'), spoilers ? section : null, spoilers ? fraction : null);
    if (state && app.bookChat?.book === book.id) app.bookChat.chat = state;
  }

  async function clear() {
    const ok = await confirm({ title: 'Sohbeti temizle', message: 'Bu kitabın sohbeti ve kayıtlı geçmişi silinsin mi?', ok: 'Temizle', danger: true });
    if (!ok) return;
    const state = await act('reader_chat_clear');
    if (state && app.bookChat?.book === book.id) app.bookChat.chat = state;
  }

  const SUGGESTIONS = ['Şimdiye kadar neler oldu?', 'Bu bölümü özetle', 'Ana karakterler kimler?'];
</script>

<aside class="panel">
  <div class="head">
    <span class="pill">Kitaba sor</span>
    <span class="grow"></span>
    <button class="icon-btn sm" title="Sohbeti temizle" disabled={!chat || chat.asking || !chat.entries.some((e) => e.kind === 'user')} onclick={clear}><Icon name="trash" size={15} /></button>
    <button class="icon-btn sm" title="Kapat" onclick={onclose}><Icon name="x" size={15} /></button>
  </div>
  <div class="scope" title="Açıkken yalnızca okuduğunuz yere (açık bölümde ekranın alt kenarına) kadarki kısım modele gider; sonrası hiç gösterilmez.">
    <Toggle bind:checked={spoilers} onchange={setSpoilers} label={`Okuduğum yere kadar (${section + 1}. bölüm, %${Math.round(fraction * 100)})`} />
  </div>
  {#if chat}
    <div class="messages" bind:this={scroller}>
      <ChatMessages entries={chat.entries} single oncite={(item) => ongo?.(Math.max(0, Number(item.start) - 1))} />
      {#if chat.enabled && !chat.entries.some((e) => e.kind === 'user')}
        <div class="suggest">
          {#each SUGGESTIONS as s}<button class="chip" onclick={() => ask(s)}>{s}</button>{/each}
        </div>
      {/if}
    </div>
    {#if chat.note}<div class="note">{#if !chat.ready && !chat.note.startsWith('Bu belge')}<Icon name="loader" size={13} spin />{/if}{chat.note}</div>{/if}
    <form class="ask" onsubmit={(e) => { e.preventDefault(); ask(); }}>
      <input bind:value={question} disabled={!chat.enabled} placeholder="Kitaba sor…" />
      <MicButton bind:value={question} disabled={!chat.enabled} />
      <TemplatePicker kind="doc" />
      <ThinkToggle />
      <button class="send" type="submit" title="Gönder" disabled={!chat.enabled || !question.trim()}><Icon name="send" size={16} /></button>
    </form>
  {:else}
    <div class="note"><Icon name="loader" size={13} spin />Kitap hazırlanıyor…</div>
  {/if}
</aside>

<style>
  .panel { width: 360px; flex: none; min-height: 0; background: var(--panel); border-left: 1px solid var(--outline); display: flex; flex-direction: column;
    padding: 12px 14px; gap: 10px; }
  .head { display: flex; align-items: center; gap: 4px; }
  .grow { flex: 1; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .scope { font-size: 12.5px; }
  .messages { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 4px 8px 0; }
  .suggest { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: 12.5px; padding: 6px 10px; border-radius: 999px; background: var(--surface); border: 1px solid var(--outline); color: var(--secondary); }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .note { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--dim); }
  .ask { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 5px 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid var(--field-border); }
  .ask:focus-within { border-color: var(--accent); box-shadow: var(--focus-ring); }
  .ask input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; }
  .ask input::placeholder { color: var(--dim); }
  .send { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
  @media (max-width: 900px) { .panel { width: 300px; } }
</style>
