<script>
  // Bu videoya sor (eski qa_panel'in sag karti): transkript kaynagi, hazirlik durumu, atifli sohbet.
  import Icon from '../lib/Icon.svelte';
  import ChatMessages from './ChatMessages.svelte';
  import { app, act, seekPlayer } from '../lib/state.svelte.js';
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

  const percent = $derived(q?.progress ? Math.round((q.progress.done * 100) / q.progress.total) : null);
</script>

<aside class="panel">
  <div class="head" use:dragArea><span class="pill">Bu videoya sor</span></div>
  {#if q}
    {#if q.sources.length}
      <label class="source">
        <span class="label">Transkript</span>
        <select class="field" value={q.source} disabled={q.busy} onchange={changeSource} title="Soru-cevapta kullanılacak transkript">
          {#each q.sources as s}<option value={s.key}>{s.label}</option>{/each}
        </select>
      </label>
    {/if}
    <div class="status">
      {#if q.busy && !q.asking}<Icon name="loader" size={14} spin />{:else if q.ready}<Icon name="check" size={14} />{/if}
      <span class="ellipsis" title={q.status}>{q.status}</span>
    </div>
    {#if q.busy && !q.asking}
      <div class="track" class:indeterminate={percent === null}><i style:width="{percent ?? 30}%"></i></div>
    {/if}
    <div class="messages" bind:this={scroller}>
      <ChatMessages entries={q.entries} single oncite={(item) => seekPlayer(item.start, true)} />
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
    <p class="foot">Yapay zekâ yanlış bilgi verebilir; zaman atıflarına tıklayıp videoda doğrulayın.</p>
  {/if}
</aside>

<style>
  .panel { width: 380px; flex: none; height: 100%; background: var(--panel); display: flex; flex-direction: column; padding: 14px 16px 12px; min-height: 0; gap: 10px; }
  .head { display: flex; align-items: center; padding: 30px 0 4px; }
  .pill { background: var(--text); color: var(--window); font-weight: 600; font-size: 13px; padding: 5px 12px; border-radius: 999px; }
  .source { display: flex; align-items: center; gap: 10px; }
  .source .field { flex: 1; height: 32px; }
  .status { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--secondary); }
  .status :global(svg) { color: var(--accent); }
  .track.indeterminate i { animation: slide 1.4s ease-in-out infinite; }
  @keyframes slide { 0% { margin-left: -30%; } 100% { margin-left: 100%; } }
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
  .foot { font-size: 11px; color: var(--dim); }
</style>
