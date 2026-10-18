<script>
  // Ilk acilis bilesen denetimi (F154): eksik bilesenler, nasil kurulacaklari ve ilgili ayar.
  // Ilk acilista kendiliginden gelir (ui.json setup_seen yoksa); Ayarlar → Gelismis'ten yeniden acilir.
  import Modal from './Modal.svelte';
  import Icon from '../lib/Icon.svelte';
  import { app, act, go, savePref } from '../lib/state.svelte.js';

  let items = $state(null);
  let busy = $state(false);

  async function check() {
    busy = true;
    items = (await act('setup_check')) ?? [];
    busy = false;
  }
  check();

  const required = $derived((items ?? []).filter((i) => i.required));
  const optional = $derived((items ?? []).filter((i) => !i.required));
  const blocking = $derived(required.filter((i) => i.state === 'missing').length);
  const ICONS = { ok: 'check', warn: 'alert', missing: 'x' };

  function close() {
    savePref({ setup_seen: true });
    app.setup = false;
  }
  function openSettings(category) {
    app.settingsTab = category;
    close();
    go('settings');
  }
</script>

<Modal title="Bileşen denetimi" width={680} onclose={close}>
  <p class="hint">Aktar'ın kullandığı programlar ve modeller. Zorunlu olanlar çeviri, sohbet ve video için gerekir; isteğe bağlı olanlar yalnızca o özellik kullanılınca.</p>
  {#if items === null}
    <div class="empty"><Icon name="loader" spin /> Denetleniyor…</div>
  {:else}
    {#each [['Zorunlu', required], ['İsteğe bağlı', optional]] as [label, list]}
      <h3>{label}</h3>
      <ul>
        {#each list as item (item.id)}
          <li class={item.state}>
            <span class="badge"><Icon name={ICONS[item.state]} size={14} /></span>
            <div class="text">
              <b>{item.label}</b>
              <span class="detail selectable">{item.detail}</span>
              {#if item.state !== 'ok' && item.hint}<span class="howto selectable">{item.hint}</span>{/if}
            </div>
            <div class="acts">
              {#if item.state !== 'ok' && item.url}
                <button class="btn sm ghost" onclick={() => act('reader_open_link', item.url)} title={item.url}><Icon name="external" size={14} />Sayfa</button>
              {/if}
              {#if item.settings}
                <button class="btn sm ghost" onclick={() => openSettings(item.settings)}><Icon name="settings" size={14} />Ayar</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {/each}
  {/if}
  {#snippet footer()}
    <span class="summary">{items === null ? '' : blocking ? `${blocking} zorunlu bileşen eksik` : 'Zorunlu bileşenler hazır'}</span>
    <button class="btn" disabled={busy} onclick={check}><Icon name="refresh" size={16} spin={busy} />Yeniden denetle</button>
    <button class="btn primary" onclick={close}>Tamam</button>
  {/snippet}
</Modal>

<style>
  .hint { color: var(--dim); font-size: 13px; }
  h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--dim); margin-top: 4px; }
  ul { list-style: none; display: flex; flex-direction: column; gap: 6px; }
  li { display: flex; gap: 12px; align-items: flex-start; padding: 10px 12px; border-radius: 10px; background: var(--surface); }
  .badge { flex: none; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; margin-top: 1px; }
  li.ok .badge { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
  li.warn .badge { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
  li.missing .badge { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
  .detail { color: var(--dim); overflow-wrap: anywhere; }
  .howto { font-size: 12px; overflow-wrap: anywhere; }
  .acts { display: flex; gap: 4px; flex: none; }
  .summary { flex: 1; color: var(--dim); font-size: 13px; }
  .empty { color: var(--dim); padding: 24px; text-align: center; }
</style>
