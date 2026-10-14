<script>
  import Icon from '../lib/Icon.svelte';
  import { menu, closeMenu } from '../lib/menu.svelte.js';

  let node = $state();
  let position = $state({ x: 0, y: 0 });

  // Menu pencereden tasmasin: olculup gerekirse sola/yukari kaydirilir.
  $effect(() => {
    const current = menu.current;
    if (!current || !node) return;
    const rect = node.getBoundingClientRect();
    position = {
      x: Math.min(current.x, window.innerWidth - rect.width - 8),
      y: current.y + rect.height > window.innerHeight - 8 ? Math.max(8, current.y - rect.height) : current.y,
    };
  });

  function run(item) {
    closeMenu();
    if (!item.disabled) item.action?.();
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && closeMenu()} onblur={closeMenu} />

{#if menu.current}
  <div class="veil" role="presentation" onmousedown={closeMenu} oncontextmenu={(e) => { e.preventDefault(); closeMenu(); }}></div>
  <div class="menu" bind:this={node} style:left="{position.x}px" style:top="{position.y}px" role="menu">
    {#each menu.current.items as item}
      {#if item === 'sep'}
        <div class="sep"></div>
      {:else}
        <button role="menuitem" class:danger={item.danger} disabled={item.disabled} onclick={() => run(item)}>
          {#if item.icon}<Icon name={item.icon} size={16} />{:else}<span class="pad"></span>{/if}{item.label}
        </button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .veil { position: fixed; inset: 0; z-index: 80; }
  .menu { position: fixed; z-index: 81; min-width: 220px; padding: 6px; background: var(--overlay); border: 1px solid var(--outline);
    border-radius: 12px; box-shadow: 0 8px 28px var(--shadow); }
  button { display: flex; align-items: center; gap: 12px; width: 100%; padding: 8px 12px; border-radius: 8px; font-size: 13px; text-align: left; color: var(--text); }
  button :global(svg) { color: var(--secondary); }
  button:not(:disabled):hover { background: var(--surface-hover); }
  button.danger, button.danger :global(svg) { color: var(--danger); }
  .pad { width: 16px; }
  .sep { height: 1px; background: var(--outline); margin: 5px 8px; }
</style>
