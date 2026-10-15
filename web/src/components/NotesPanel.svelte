<script>
  // Notlar paneli (F113): acik videonun/belgenin notlari, yeni not yazma alani, duzenleme.
  // Satira tiklayinca `onjump(at)` ile o ana / sayfaya gidilir.
  import Icon from '../lib/Icon.svelte';
  import { openMenu } from '../lib/menu.svelte.js';
  import { notes, addNote, updateNote, deleteNote, NOTE_COLORS } from '../lib/notes.svelte.js';

  // doc: belgenin turu ('pdf', 'text', ...) ya da video icin false
  let { path, doc = false, current = null, onjump } = $props();

  const COLOR_NAMES = { yellow: 'Sarı', green: 'Yeşil', blue: 'Mavi', pink: 'Pembe' };
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
  };
  const where = (at) => (doc ? `s.${Math.round(at)}` : fmt(at));

  let text = $state('');
  let color = $state('yellow');
  let editing = $state(null);   // duzenlenen notun id'si
  let editText = $state('');
  let input = $state();

  $effect(() => {
    if (notes.draft) { text = ''; queueMicrotask(() => input?.focus()); }
  });

  async function save() {
    const draft = notes.draft;
    if (!draft || (!text.trim() && !draft.quote)) return;
    if (await addNote(path, draft.at, text, draft.quote, color)) { notes.draft = null; text = ''; }
  }

  function keys(event, submit, cancel) {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
    else if (event.key === 'Escape') { event.preventDefault(); cancel(); }
    event.stopPropagation();   // oynaticinin kisayollari (bosluk, oklar) calismasin
  }

  function edit(note) {
    editing = note.id;
    editText = note.text;
  }

  async function saveEdit(note) {
    if (await updateNote(path, note.id, editText)) editing = null;
  }

  function menu(event, note) {
    openMenu(event, [
      { label: 'Düzenle', icon: 'pencil', action: () => edit(note) },
      'sep', { label: 'Renk', disabled: true },
      ...Object.keys(NOTE_COLORS).map((key) => ({ label: COLOR_NAMES[key], icon: note.color === key ? 'check' : null,
        action: () => updateNote(path, note.id, null, key) })),
      'sep', { label: 'Sil', icon: 'trash', action: () => deleteNote(path, note.id) },
    ]);
  }
</script>

<div class="notes card">
  <div class="head">
    <strong>Notlar</strong>
    <span class="dim count">{notes.items.length}</span>
    <span class="grow"></span>
    {#if !notes.draft && current !== null}
      <button class="btn sm ghost" onclick={() => { notes.draft = { at: current, quote: '', n: Date.now() }; }}>
        <Icon name="plus" size={14} />{doc ? `s.${Math.round(current)}` : fmt(current)} için not</button>
    {/if}
    <button class="icon-btn sm" title="Notları gizle" onclick={() => { notes.open = false; notes.draft = null; }}><Icon name="x" size={16} /></button>
  </div>

  {#if notes.draft}
    <div class="draft">
      <div class="meta">
        <span class="pos mono">{where(notes.draft.at)}</span>
        {#each Object.entries(NOTE_COLORS) as [key, value]}
          <button class="swatch" class:on={color === key} style:background={value} title={COLOR_NAMES[key]} aria-label={COLOR_NAMES[key]} onclick={() => (color = key)}></button>
        {/each}
      </div>
      {#if notes.draft.quote}<blockquote style:border-color={NOTE_COLORS[color]}>{notes.draft.quote}</blockquote>{/if}
      <textarea class="field" rows="2" bind:this={input} bind:value={text}
        placeholder={notes.draft.quote ? 'Not (isteğe bağlı) — yalnız vurgulamak için boş bırakın' : 'Notunuz…'}
        onkeydown={(e) => keys(e, save, () => (notes.draft = null))}></textarea>
      <div class="actions">
        <span class="dim hint">Enter kaydeder · Shift+Enter yeni satır · Esc vazgeçer</span>
        <button class="btn sm ghost" onclick={() => (notes.draft = null)}>Vazgeç</button>
        <button class="btn sm primary" disabled={!text.trim() && !notes.draft.quote} onclick={save}>Kaydet</button>
      </div>
    </div>
  {/if}

  <div class="list">
    {#each notes.items as note (note.id)}
      <div class="item" role="button" tabindex="0" onclick={() => editing !== note.id && onjump?.(note.at)}
        onkeydown={(e) => e.key === 'Enter' && editing !== note.id && onjump?.(note.at)}
        oncontextmenu={(e) => { e.preventDefault(); menu(e, note); }}>
        <span class="dot" style:background={NOTE_COLORS[note.color]}></span>
        <div class="content">
          <span class="pos mono">{where(note.at)}</span>
          {#if note.quote}<span class="quote" style:--mark={NOTE_COLORS[note.color]}>{note.quote}</span>{/if}
          {#if editing === note.id}
            <!-- svelte-ignore a11y_autofocus -->
            <textarea class="field" rows="2" autofocus bind:value={editText} onclick={(e) => e.stopPropagation()}
              onkeydown={(e) => keys(e, () => saveEdit(note), () => (editing = null))}></textarea>
          {:else if note.text}
            <span class="text">{note.text}</span>
          {/if}
        </div>
        <button class="icon-btn sm more" title="Not seçenekleri" onclick={(e) => { e.stopPropagation(); menu(e, note); }}><Icon name="more" size={16} /></button>
      </div>
    {:else}
      {#if !notes.draft}
        <p class="dim empty">{doc ? 'Henüz not yok. Sayfaya not eklemek için “Not ekle”ye basın'
          + (doc !== 'pdf' && doc !== 'image' ? ' ya da metin seçip vurgulayın.' : '.') : 'Henüz not yok. Videonun o anına not eklemek için N tuşuna basın.'}</p>
      {/if}
    {/each}
  </div>
</div>

<style>
  .notes { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 14px; border-bottom: 1px solid var(--outline); }
  .count { font-size: 12px; }
  .grow { flex: 1; }
  .draft { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--outline); }
  .meta { display: flex; align-items: center; gap: 6px; }
  .meta .pos { margin-right: auto; }
  .swatch { width: 16px; height: 16px; border-radius: 50%; border: 2px solid transparent; }
  .swatch.on { border-color: var(--text); }
  blockquote { margin: 0; padding: 4px 10px; border-left: 3px solid; color: var(--secondary); font-size: 13px; max-height: 80px; overflow: auto; }
  textarea { width: 100%; resize: vertical; min-height: 52px; padding: 8px 10px; font: inherit; font-size: 13px; line-height: 1.5; }
  .actions { display: flex; align-items: center; gap: 6px; }
  .hint { font-size: 11px; margin-right: auto; }
  .list { overflow: auto; min-height: 0; flex: 1; padding: 4px 0; }
  .item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 8px 8px 14px; cursor: pointer; }
  .item:hover { background: var(--surface-hover); }
  .dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; flex: none; }
  .content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .pos { font-size: 12px; color: var(--accent); }
  .quote { font-size: 13px; color: var(--text); background: color-mix(in srgb, var(--mark) 28%, transparent); border-radius: 3px; padding: 1px 4px;
    display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .text { font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .more { opacity: 0; }
  .item:hover .more { opacity: 1; }
  .empty { font-size: 13px; padding: 10px 14px; margin: 0; }
</style>
