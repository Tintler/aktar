<script>
  import Modal from './Modal.svelte';
  import { pending } from '../lib/confirm.svelte.js';

  function done(accepted) {
    const current = pending.current;
    pending.current = null;
    if (!current) return;
    if (current.kind === 'confirm') current.resolve(accepted);
    else current.resolve(accepted ? current.value : null);
  }

  function focus(node) {
    node.focus();
    if (node.select) node.select();
  }

  function keydown(event) {
    if (event.key === 'Enter' && !(event.target.tagName === 'TEXTAREA')) {
      event.preventDefault();
      done(true);
    }
  }
</script>

{#if pending.current}
  {@const c = pending.current}
  <Modal title={c.title} width={c.multiline ? 620 : 500} onclose={() => done(false)}>
    {#if c.message}<p class="msg">{c.message}</p>{/if}
    {#if c.list?.length}
      <ul>{#each c.list as item}<li>{item}</li>{/each}</ul>
    {/if}
    {#if c.kind === 'prompt'}
      {#if c.multiline}
        <textarea class="field area" bind:value={c.value} placeholder={c.placeholder} use:focus></textarea>
      {:else}
        <input class="field" bind:value={c.value} placeholder={c.placeholder} use:focus onkeydown={keydown} />
      {/if}
    {:else if c.kind === 'choose'}
      <div class="options">
        {#each c.options as option}
          <button class="option" class:on={c.value === option.value} onclick={() => (c.value = option.value)}
            ondblclick={() => { c.value = option.value; done(true); }}>{option.label}{#if option.hint}<small>{option.hint}</small>{/if}</button>
        {/each}
      </div>
    {/if}
    {#snippet footer()}
      {#if c.cancel}<button class="btn" onclick={() => done(false)}>{c.cancel}</button>{/if}
      <button class="btn primary" class:danger={c.danger} onclick={() => done(true)}>{c.ok}</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .msg { color: var(--secondary); white-space: pre-line; line-height: 1.55; }
  ul { list-style: none; background: var(--surface); border-radius: 10px; padding: 8px 12px; max-height: 220px; overflow: auto; font-size: 13px; }
  li { padding: 3px 0; color: var(--text); }
  .field { width: 100%; }
  .area { height: 260px; padding: 10px; resize: vertical; line-height: 1.5; }
  .options { display: flex; flex-direction: column; gap: 2px; max-height: 300px; overflow: auto; }
  .option { text-align: left; padding: 9px 12px; border-radius: 8px; color: var(--secondary); }
  .option:hover { background: var(--surface-hover); color: var(--text); }
  .option.on { background: var(--surface-active); color: var(--text); font-weight: 600; }
  .option small { display: block; margin-top: 3px; font-size: 12px; font-weight: 400; line-height: 1.45; color: var(--dim); }
</style>
