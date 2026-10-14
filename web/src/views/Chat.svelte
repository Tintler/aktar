<script>
  // Genel sohbet: serbest konusma; soru kutuphanedeki dosyalarla ilgiliyse model atif yapar.
  import Icon from '../lib/Icon.svelte';
  import Logo from '../components/Logo.svelte';
  import { app, act, loadAssistant, refreshConversations, openFile, toast } from '../lib/state.svelte.js';
  import { prompt, confirm } from '../lib/confirm.svelte.js';
  import { openMenu } from '../lib/menu.svelte.js';
  import { richHtml, escapeHtml } from '../lib/markdown.js';

  const SUGGESTIONS = [
    'Kütüphanemde neler var?',
    'Koleksiyonlarımdaki ana konuları özetle',
    'Bana bir konuyu basitçe anlat',
    'Bir metni düzeltmeme yardım et',
  ];

  loadAssistant();

  const chat = $derived(app.assistant);
  const entries = $derived(chat?.entries ?? []);
  const empty = $derived(!!chat && !entries.length && !chat.busy);
  let text = $state('');
  let scroller = $state();
  let input = $state();
  let stick = true;

  $effect(() => {
    entries.length;
    chat?.stream;
    chat?.id;
    if (scroller && stick) queueMicrotask(() => (scroller.scrollTop = scroller.scrollHeight));
  });

  $effect(() => {
    chat?.id;
    queueMicrotask(() => input?.focus());
  });

  function scrolled() {
    stick = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 40;
  }

  function grow() {
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 220) + 'px';
  }

  async function send(value = text) {
    const message = value.trim();
    if (!message || !chat || chat.busy || chat.locked) return;
    text = '';
    queueMicrotask(grow);
    stick = true;
    const state = await act('assistant_ask', message);
    if (state) app.assistant = state;
    refreshConversations();
  }

  function keydown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  }

  async function newChat() {
    const state = await act('assistant_new');
    if (state) app.assistant = state;
    text = '';
  }

  async function open(id) {
    const state = await act('assistant_open', id);
    if (state) app.assistant = state;
  }

  async function rename(item) {
    const title = await prompt({ title: 'Sohbeti yeniden adlandır', message: 'Başlık:', value: item.title, ok: 'Kaydet' });
    if (!title?.trim()) return;
    const state = await act('assistant_rename', item.id, title.trim());
    if (state && chat?.id === item.id) app.assistant = state;
    refreshConversations();
  }

  async function remove(item) {
    const ok = await confirm({ title: 'Sohbeti sil', message: `"${item.title}" silinsin mi?`, ok: 'Sil', danger: true });
    if (!ok) return;
    const state = await act('assistant_delete', item.id);
    if (state && chat?.id === item.id) app.assistant = state;
    refreshConversations();
  }

  function itemMenu(event, item) {
    openMenu(event, [
      { label: 'Yeniden adlandır', icon: 'pencil', action: () => rename(item) },
      'sep',
      { label: 'Sil', icon: 'trash', danger: true, action: () => remove(item) },
    ]);
  }

  // Sohbet listesi tarihe gore gruplanir (Bugun / Dun / Son 7 gun / Daha eski).
  const groups = $derived.by(() => {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const result = [];
    // Ilk cevap yazilirken sohbet henuz diske yazilmadi; listede hemen gorunsun.
    const pending = chat?.title && !app.conversations.some((item) => item.id === chat.id)
      ? [{ id: chat.id, title: chat.title, updated: now.toISOString() }] : [];
    for (const item of [...pending, ...app.conversations]) {
      const time = new Date(item.updated).getTime();
      const label = time >= today ? 'Bugün' : time >= today - 86400000 ? 'Dün' : time >= today - 7 * 86400000 ? 'Son 7 gün' : 'Daha eski';
      if (result.at(-1)?.label !== label) result.push({ label, items: [] });
      result.at(-1).items.push(item);
    }
    return result;
  });

  // Cevap metni + atif dugmeleri -> tek HTML (atiflar Markdown'u bolmesin diye yer tutucu).
  function answerHtml(entry) {
    const tokens = [];
    let source = '';
    for (const part of entry.parts) {
      if (part.type === 'cite') {
        source += `\u0001${tokens.length}\u0001`;
        tokens.push(part.items.map((item) => {
          const key = cites.push(item) - 1;
          return `<button class="cite" data-cite="${key}" title="${escapeHtml(item.title)}">${escapeHtml(item.label)}</button>`;
        }).join(' '));
      } else source += part.text;
    }
    return richHtml(source, tokens);
  }
  let cites = [];
  const rendered = $derived.by(() => {
    cites = [];
    return entries.map((entry) => (entry.kind === 'assistant' ? answerHtml(entry) : null));
  });

  function clickAnswer(event) {
    const button = event.target.closest('button.cite[data-cite]');
    if (!button) return;
    const item = cites[Number(button.dataset.cite)];
    if (item) openFile(item, item.start);
  }

  async function copy(entry) {
    const value = entry.parts.map((p) => (p.type === 'cite' ? p.items.map((i) => `[${i.label}]`).join(' ') : p.text)).join('');
    try {
      await navigator.clipboard.writeText(value);
      toast('Cevap kopyalandı.', 'ok');
    } catch {
      toast('Panoya kopyalanamadı.', 'error');
    }
  }
</script>

{#snippet composer(big)}
  <form class="composer" class:big onsubmit={(e) => { e.preventDefault(); send(); }}>
    <textarea bind:this={input} bind:value={text} rows="1" oninput={grow} onkeydown={keydown} disabled={!chat || chat.locked}
      placeholder={chat?.locked ? 'Başka bir sohbette cevap hazırlanıyor…' : big ? 'Bir şey sorun ya da konuşmaya başlayın…' : 'Yanıtlayın…'}></textarea>
    <div class="row">
      <span class="hint dim">{chat?.busy ? 'Cevap yazılıyor…' : 'Enter: gönder · Shift+Enter: yeni satır'}</span>
      {#if chat?.busy}
        <button class="send stop" type="button" title="Durdur" onclick={() => act('assistant_stop')}><Icon name="stop" size={14} /></button>
      {:else}
        <button class="send" type="submit" title="Gönder" disabled={!text.trim() || !chat || chat.locked}><Icon name="arrowUp" size={18} /></button>
      {/if}
    </div>
  </form>
{/snippet}

<section class="chat">
  <aside class="convs">
    <button class="new" onclick={newChat}><Icon name="squarePen" size={17} />Yeni sohbet</button>
    <div class="clist">
      {#each groups as group}
        <div class="glabel">{group.label}</div>
        {#each group.items as item (item.id)}
          <button class="conv" class:on={chat?.id === item.id} onclick={() => open(item.id)} oncontextmenu={(e) => itemMenu(e, item)} title={item.title}>
            <span class="ellipsis">{item.title}</span>
            <span class="more" role="button" tabindex="-1" title="Diğer" onclick={(e) => { e.stopPropagation(); itemMenu(e, item); }}
              onkeydown={() => {}}><Icon name="more" size={15} /></span>
          </button>
        {/each}
      {:else}
        <p class="none">Henüz sohbet yok.</p>
      {/each}
    </div>
  </aside>

  <div class="main">
    {#if empty}
      <div class="welcome">
        <div class="hello"><Logo size={34} /><h1>Bugün ne konuşalım?</h1></div>
        {@render composer(true)}
        <div class="suggestions">
          {#each SUGGESTIONS as s}<button class="chip" onclick={() => send(s)}>{s}</button>{/each}
        </div>
        <p class="note dim">Genel sorulara kendi bilgisiyle cevap verir; sorunuz kütüphanenizdeki videolar ya da belgelerle ilgiliyse onlara bakıp kaynak gösterir.</p>
      </div>
    {:else}
      <div class="scroll" bind:this={scroller} onscroll={scrolled}>
        <div class="thread">
          {#each entries as entry, index}
            {#if entry.kind === 'user'}
              <div class="user selectable">{entry.text}</div>
            {:else if entry.kind === 'assistant'}
              <div class="turn">
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <div class="md selectable" onclick={clickAnswer}>{@html rendered[index]}</div>
                {#if entry.sources?.length}
                  <div class="sources">
                    {#each entry.sources as source}
                      <button class="source" title={source.title} onclick={() => openFile(source, source.start)}>
                        <span class="cite">{source.label}</span><span class="ellipsis">{source.title}</span>
                      </button>
                    {/each}
                  </div>
                {/if}
                <div class="tools"><button class="icon-btn sm" title="Kopyala" onclick={() => copy(entry)}><Icon name="copy" size={14} /></button></div>
              </div>
            {:else if entry.kind === 'error'}
              <div class="error selectable"><Icon name="alert" size={15} />{entry.text}</div>
            {/if}
          {/each}
          {#if chat?.busy}
            <div class="turn">
              {#if chat.stream}
                <div class="md selectable streaming">{@html richHtml(chat.stream)}</div>
              {:else}
                <div class="thinking"><span class="spark"><Icon name="sparkles" size={16} /></span><span class="dots"><i></i><i></i><i></i></span></div>
              {/if}
            </div>
          {/if}
        </div>
      </div>
      <div class="dock">{@render composer(false)}</div>
    {/if}
  </div>
</section>

<style>
  .chat { height: 100%; display: flex; min-height: 0; }

  .convs { width: 250px; flex: none; display: flex; flex-direction: column; gap: 8px; padding: 0 10px 16px 24px; min-height: 0; }
  .new { display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 12px; border-radius: 10px; font-weight: 600; font-size: 14px; color: var(--text); }
  .new:hover { background: var(--surface-hover); }
  .new :global(svg) { color: var(--accent); }
  .clist { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 1px; }
  .glabel { font-size: 11.5px; font-weight: 600; color: var(--dim); padding: 14px 12px 6px; }
  .conv { display: flex; align-items: center; gap: 6px; padding: 7px 6px 7px 12px; border-radius: 8px; font-size: 13.5px; color: var(--secondary); text-align: left; width: 100%; }
  .conv > span:first-child { flex: 1; min-width: 0; }
  .conv:hover { background: var(--surface-hover); color: var(--text); }
  .conv.on { background: var(--surface-active); color: var(--text); }
  .conv .more { opacity: 0; width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center; flex: none; color: var(--dim); }
  .conv:hover .more, .conv.on .more { opacity: 1; }
  .conv .more:hover { color: var(--text); background: var(--surface); }
  .none { color: var(--dim); font-size: 12.5px; padding: 10px 12px; }

  .main { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
  .welcome { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 22px; padding: 0 32px 12vh; }
  .hello { display: flex; align-items: center; gap: 14px; }
  .hello h1 { font-size: clamp(26px, 3vw, 36px); font-weight: 700; letter-spacing: -.02em; }
  .suggestions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; max-width: 720px; }
  .suggestions .chip { color: var(--secondary); }
  .suggestions .chip:hover { color: var(--text); }
  .note { font-size: 12.5px; max-width: 560px; text-align: center; line-height: 1.6; }

  .scroll { flex: 1; min-height: 0; overflow: auto; }
  .thread { max-width: 780px; margin: 0 auto; padding: 8px 32px 24px; display: flex; flex-direction: column; gap: 22px; }
  .dock { padding: 0 32px 22px; }
  .dock .composer { max-width: 780px; margin: 0 auto; }

  .composer { width: min(720px, 100%); display: flex; flex-direction: column; gap: 6px; padding: 12px 12px 10px 18px; border-radius: 22px;
    background: var(--surface); border: 1px solid var(--outline); box-shadow: 0 6px 24px color-mix(in srgb, var(--shadow) 60%, transparent); }
  .composer:focus-within { border-color: color-mix(in srgb, var(--accent) 45%, var(--outline)); }
  .composer.big { padding: 16px 14px 12px 20px; }
  .composer textarea { resize: none; border: 0; outline: none; background: none; font: inherit; font-size: 15px; line-height: 1.55; color: var(--text);
    max-height: 220px; padding: 2px 0; }
  .composer.big textarea { min-height: 52px; }
  .composer textarea::placeholder { color: var(--dim); }
  .composer .row { display: flex; align-items: center; gap: 8px; }
  .composer .hint { flex: 1; font-size: 11.5px; }
  .send { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--accent); color: var(--on-accent); flex: none; }
  .send:disabled { background: var(--surface-active); color: var(--dim); opacity: 1; }
  .send.stop { background: var(--text); color: var(--window); }

  .user { align-self: flex-end; max-width: 80%; background: var(--surface-active); padding: 10px 16px; border-radius: 18px 18px 4px 18px;
    font-size: 14.5px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
  .turn { display: flex; flex-direction: column; gap: 8px; }
  .turn .tools { opacity: 0; transition: opacity .15s; margin-left: -6px; }
  .turn:hover .tools { opacity: 1; }
  .error { display: flex; gap: 8px; align-items: flex-start; color: var(--danger); font-size: 13.5px; }
  .error :global(svg) { flex: none; margin-top: 2px; }
  .thinking { display: flex; align-items: center; gap: 10px; height: 28px; }
  .spark { color: var(--accent); display: grid; animation: spin 2.4s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .dots { display: inline-flex; gap: 4px; }
  .dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: blink 1.2s infinite; }
  .dots i:nth-child(2) { animation-delay: .2s; }
  .dots i:nth-child(3) { animation-delay: .4s; }
  @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }

  /* Markdown cevap */
  .md { font-size: 14.5px; line-height: 1.7; color: var(--text); overflow-wrap: anywhere; }
  .md :global(p) { margin: 0 0 .75em; }
  .md :global(p:last-child), .md :global(ul:last-child), .md :global(ol:last-child) { margin-bottom: 0; }
  .md :global(h3), .md :global(h4), .md :global(h5), .md :global(h6) { margin: 1.1em 0 .45em; font-weight: 700; line-height: 1.35; }
  .md :global(h3) { font-size: 1.18em; }
  .md :global(h4) { font-size: 1.07em; }
  .md :global(h5), .md :global(h6) { font-size: 1em; }
  .md :global(:first-child) { margin-top: 0; }
  .md :global(ul), .md :global(ol) { margin: 0 0 .75em; padding-left: 1.5em; }
  .md :global(li) { margin: .2em 0; }
  .md :global(li::marker) { color: var(--secondary); }
  .md :global(code) { font: .88em/1.5 var(--mono); padding: .1em .38em; border-radius: 5px; background: var(--surface); }
  .md :global(pre) { margin: .3em 0 .9em; padding: 12px 14px; border-radius: 10px; background: var(--panel); border: 1px solid var(--outline); overflow: auto; }
  .md :global(pre code) { padding: 0; background: none; font-size: 12.5px; white-space: pre; }
  .md :global(blockquote) { margin: 0 0 .75em; padding: 2px 0 2px 14px; border-left: 3px solid var(--outline); color: var(--secondary); }
  .md :global(hr) { border: 0; border-top: 1px solid var(--outline); margin: 1.1em 0; }
  .md :global(.table-wrap) { overflow: auto; margin: 0 0 .9em; }
  .md :global(table) { border-collapse: collapse; font-size: .93em; }
  .md :global(th), .md :global(td) { border: 1px solid var(--outline); padding: 6px 10px; text-align: left; vertical-align: top; }
  .md :global(th) { background: var(--surface); font-weight: 600; }
  .md :global(.link) { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .md :global(.cite), .source .cite { display: inline-block; padding: 0 7px; margin: 0 1px; border-radius: 999px; font-size: 11.5px; font-weight: 700; line-height: 19px;
    color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); vertical-align: 1px; white-space: nowrap; }
  .md :global(button.cite:hover) { background: var(--accent); color: var(--on-accent); }
  .md :global(.cite.raw) { opacity: .7; }
  .streaming :global(> :last-child)::after { content: ''; display: inline-block; width: 8px; height: 1em; margin-left: 3px; vertical-align: -2px;
    border-radius: 2px; background: var(--accent); animation: blink 1s infinite; }
  .sources { display: flex; flex-wrap: wrap; gap: 6px; }
  .source { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 3px 10px 3px 3px; border-radius: 999px; background: var(--surface); font-size: 12px; color: var(--secondary); }
  .source:hover { background: var(--surface-hover); color: var(--text); }
  .source .ellipsis { max-width: 220px; }

  @media (max-width: 1100px) { .convs { width: 210px; } }
</style>
