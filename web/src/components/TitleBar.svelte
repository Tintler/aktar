<script>
  // Kendi pencere cercevesi (Windows, window_frame.py): ust cubugun sagindaki pencere
  // dugmeleri ve kenarlardan boyutlandirma. Diger sistemlerde sistemin cercevesi kalir.
  import Icon from '../lib/Icon.svelte';
  import { frame, windowCommand } from '../lib/frame.svelte.js';

  // Boyutlandirma bolgeleri; ad hem CSS sinifi hem Python'a giden kenar adi.
  const edges = ['top', 'bottom', 'left', 'right', 'topleft', 'topright', 'bottomleft', 'bottomright'];

  function resize(event, edge) {
    if (event.button !== 0) return;
    event.preventDefault();
    windowCommand('resize', edge);
  }
</script>

{#if frame.custom}
  <div class="controls">
    <button title="Küçült" onclick={() => windowCommand('minimize')}><Icon name="minus" size={16} /></button>
    <button title={frame.maximized ? 'Önceki boyut' : 'Ekranı kapla'} onclick={() => windowCommand('toggle_maximize')}>
      <Icon name={frame.maximized ? 'restore' : 'square'} size={14} /></button>
    <button class="close" title="Kapat" onclick={() => windowCommand('close')}><Icon name="x" size={16} /></button>
  </div>
  {#if !frame.maximized}
    {#each edges as edge}
      <div class="edge {edge}" onmousedown={(event) => resize(event, edge)} role="presentation"></div>
    {/each}
  {/if}
{/if}

<style>
  .controls { position: fixed; top: 6px; right: 8px; z-index: 40; display: flex; gap: 2px; }
  .controls button { width: 40px; height: 30px; border-radius: 6px; display: grid; place-items: center; color: var(--secondary); }
  .controls button:hover { background: var(--surface-hover); color: var(--text); }
  .controls .close:hover { background: #c42b1c; color: #fff; }

  .edge { position: fixed; z-index: 90; }
  .top, .bottom { left: 10px; right: 10px; height: 5px; cursor: ns-resize; }
  .top { top: 0; }
  .bottom { bottom: 0; }
  .left, .right { top: 10px; bottom: 10px; width: 5px; cursor: ew-resize; }
  .left { left: 0; }
  .right { right: 0; }
  .topleft, .topright, .bottomleft, .bottomright { width: 10px; height: 10px; }
  .topleft { top: 0; left: 0; cursor: nwse-resize; }
  .bottomright { bottom: 0; right: 0; cursor: nwse-resize; }
  .topright { top: 0; right: 0; cursor: nesw-resize; }
  .bottomleft { bottom: 0; left: 0; cursor: nesw-resize; }
</style>
