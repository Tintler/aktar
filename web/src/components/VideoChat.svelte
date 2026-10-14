<script>
  // Bu videoya sor (eski qa_panel'in sag karti): transkript kaynagi, hazirlik durumu, atifli sohbet.
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import { app, act, seekPlayer } from '../lib/state.svelte.js';
  import { confirm } from '../lib/confirm.svelte.js';
  import { dragArea } from '../lib/frame.svelte.js';

  const p = $derived(app.player);
  const q = $derived(p?.qa);
  let question = $state('');
  let scroller = $state();

  $effect(() => {
    q?.entries.length;
    q?.chips;
    if (scroller) queueMicrotask(() => (scroller.scrollTop = scroller.scrollHeight));
  });

  async function ask(text = question) {
    const value = text.trim();
    if (!value || !q?.ready || q.asking) return;
    question = '';
    const state = await act('player_ask', value);
    if (state) app.player = state;
  }

  async function chip(item) {
    if (item.action === 'ask') return ask(item.label);
    const state = await act('player_prepare', item.action);
    if (state) app.player = state;
  }

  async function changeSource(event) {
    const state = await act('player_set_source', event.currentTarget.value);
    if (state) app.player = state;
  }

  async function clear() {
    const ok = await confirm({ title: 'Sohbeti temizle', message: 'Bu videonun sohbeti ve kayıtlı geçmişi silinsin mi?', ok: 'Temizle', danger: true });
    if (!ok) return;
    const state = await act('player_clear_chat');
    if (state) app.player = state;
  }

  const preparing = $derived(!!q?.busy && !q.asking);
  const percent = $derived(q?.progress ? Math.round((q.progress.done * 100) / q.progress.total) : null);
  const hasChat = $derived((q?.entries ?? []).some((e) => e.kind === 'user'));
</script>

<aside class="panel">
  <div class="head" use:dragArea>
    <span class="pill">Bu videoya sor</span>
    <span class="grow"></span>
    <button class="icon-btn sm" title="Sohbeti temizle" disabled={!hasChat || q?.asking} onclick={clear}><Icon name="trash" size={15} /></button>
  </div>
  {#if q}
    {#if q.sources.length}
      <label class="source">
        <span class="label">Transkript</span>
        <select class="field" value={q.source} disabled={q.busy} onchange={changeSource} title="Soru-cevapta kullanılacak transkript">
          {#each q.sources as s}<option value={s.key}>{s.label}</option>{/each}
        </select>
      </label>
    {/if}
    {#if preparing}
      <div class="prep">
        <span class="orb"><Icon name="sparkles" size={16} /></span>
        <div class="ptext">
          <span class="ellipsis" title={q.status}>{q.status}</span>
          <div class="bar" class:indeterminate={percent === null}><i style:width="{percent ?? 35}%"></i></div>
        </div>
        {#if percent !== null}<span class="mono pct">%{percent}</span>{/if}
      </div>
    {:else}
      <div class="status">
        {#if q.ready}<Icon name="check" size={14} />{/if}
        <span class="ellipsis" title={q.status}>{q.status}</span>
      </div>
    {/if}
    <div class="messages" bind:this={scroller}>
      <ChatMessages entries={q.entries} single oncite={(item) => seekPlayer(item.start, true)} />
      {#if preparing && !hasChat}
        <div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
      {/if}
      {#if q.chips}
        <div class="chips">
          <span class="dim">{q.chips.title}</span>
          {#each q.chips.items as item}
            <button class="suggest" onclick={() => chip(item)}>{item.label}</button>
          {/each}
        </div>
      {/if}
    </div>
    <form class="ask" onsubmit={(e) => { e.preventDefault(); ask(); }}>
      <input bind:value={question} disabled={!q.ready || q.asking}
        placeholder={q.asking ? 'Yanıt hazırlanıyor…' : q.ready ? 'Soru sorun…' : 'Video hazırlanıyor…'} />
      <button class="send" type="submit" title="Sor" disabled={!q.ready || q.asking || !question.trim()}><Icon name="send" size={16} /></button>
    </form>
  {/if}
</aside>

<style>
  .panel { width: 380px; flex: none; height: 100%; background: var(--panel); display: flex; flex-direction: column; padding: 14px 16px 12px; min-height: 0; gap: 10px; }
  .head { display: flex; align-items: center; gap: 4px; padding: 30px 0 4px; }
  .grow { flex: 1; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .source { display: flex; align-items: center; gap: 10px; }
  .source .field { flex: 1; height: 32px; }
  .status { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--secondary); }
  .status :global(svg) { color: var(--accent); }

  /* Hazirlik: kucuk bir kart; ince ilerleme cizgisi, belirsizse kayan parilti. */
  .prep { flex: none; display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px; background: var(--surface);
    border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--outline)); }
  .orb { width: 30px; height: 30px; border-radius: 50%; flex: none; display: grid; place-items: center; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent); animation: breathe 2.4s ease-in-out infinite; }
  @keyframes breathe { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 30%, transparent); }
    50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent) 0%, transparent); } }
  .ptext { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; font-size: 12.5px; color: var(--secondary); }
  .bar { height: 3px; border-radius: 3px; background: var(--surface-active); overflow: hidden; }
  .bar i { display: block; height: 100%; border-radius: 3px; background: var(--accent); transition: width .3s; }
  .bar.indeterminate i { animation: slide 1.6s ease-in-out infinite; }
  @keyframes slide { 0% { margin-left: -35%; } 100% { margin-left: 100%; } }
  .pct { font-size: 11.5px; color: var(--dim); }

  .skeleton { display: flex; flex-direction: column; gap: 9px; padding: 4px 0; }
  .skeleton i { height: 10px; border-radius: 6px; background: linear-gradient(90deg, var(--surface) 0%, var(--surface-hover) 50%, var(--surface) 100%);
    background-size: 200% 100%; animation: shimmer 1.8s linear infinite; }
  .skeleton i:nth-child(1) { width: 88%; }
  .skeleton i:nth-child(2) { width: 72%; }
  .skeleton i:nth-child(3) { width: 54%; }
  @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

  .messages { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 4px 8px 0; }
  .chips { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; font-size: 12px; }
  .suggest { max-width: 92%; text-align: left; padding: 7px 14px; border-radius: 16px; border: 1px solid var(--outline); font-size: 13px; color: var(--text); }
  .suggest:hover { border-color: var(--accent); color: var(--accent); }
  .ask { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 5px 0 16px; border-radius: 999px; background: var(--surface); border: 1px solid transparent; }
  .ask:focus-within { border-color: var(--outline); background: var(--surface-hover); }
  .ask input { flex: 1; min-width: 0; background: none; border: 0; outline: none; font-size: 14px; }
  .ask input::placeholder { color: var(--dim); }
  .send { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
</style>
