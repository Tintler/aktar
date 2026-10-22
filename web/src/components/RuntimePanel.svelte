<script>
  // F183: sol alttaki "Model sunucusu" kutusuna tiklayinca acilan panel (ayri sayfa degil). Bellekte duran modeller:
  // model sunucusunda (LM Studio) yuklu ornekler ve Aktar'in isinmis ses motoru; ikisi de buradan bosaltilir.
  // Surekli sorgu yok: liste panel acilinca bir kez (ve yenile dugmesiyle) istenir; ses motoru durumu bellekten
  // okunur ve panel acikken 'tts' olayiyla yenilenir.
  import { untrack } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import { call, on } from '../lib/api.js';
  import { toast } from '../lib/state.svelte.js';

  let { open = $bindable(false), anchor = null } = $props();

  let llm = $state({ loading: false, models: [], kept: [], error: '' });
  let engine = $state(null);
  let busy = $state('');      // bosaltilan ornegin kimligi ('tts' ses motoru)
  let place = $state({ left: 12, bottom: 80 });

  async function loadLlm() {
    if (llm.loading) return;      // sorgu suruyorsa ikincisi gonderilmez
    llm = { ...llm, loading: true, error: '' };
    const result = await call('llm_loaded');
    llm = result?.error ? { loading: false, models: [], kept: [], error: result.error }
      : { loading: false, models: result?.models ?? null, kept: result?.kept ?? [], error: '' };
  }
  async function loadEngine() {
    engine = (await call('tts_runtime'))?.engine ?? null;
  }
  function refresh() {
    loadLlm();
    loadEngine();
  }

  // Yalnizca `open` izlenir: yenileme `llm`i okuyup yazdigi icin izlenirse effect kendini yeniden tetikler
  // ve model sunucusuna art arda istek gider.
  $effect(() => {
    if (!open) return;
    untrack(() => {
      if (anchor) {
        const rect = anchor.getBoundingClientRect();
        place = { left: rect.left, bottom: window.innerHeight - rect.top + 8 };
      }
      refresh();
    });
    return on('tts', () => loadEngine());
  });

  async function ejectModel(model) {
    busy = model.instance;
    const result = await call('llm_unload', model.instance);
    busy = '';
    if (result?.error) return toast(result.error, 'error');
    llm = { loading: false, models: result.models ?? null, kept: result.kept ?? [], error: '' };
    toast(`${model.name} bellekten boşaltıldı.`, 'ok');
  }
  async function ejectEngine() {
    busy = 'tts';
    const result = await call('tts_unload');
    busy = '';
    if (result?.error) return toast(result.error, 'error');
    engine = result?.engine ?? null;
    toast('Ses motoru bellekten boşaltıldı.', 'ok');
  }

  const gb = (bytes) => (bytes ? (bytes / 1024 ** 3).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + ' GB' : '');
  const TYPES = { llm: 'Dil modeli', vlm: 'Görü modeli', embedding: 'Embedding' };
  const KINDS = { process: 'Python süreci', server: 'Model sunucusu (Aktar başlattı)', remote: 'Uzak sunucu istemcisi (burada bellek tutmaz)' };
  const modelLine = (m) => [TYPES[m.type] ?? m.type, m.params, m.quant, m.context ? `${Math.round(m.context / 1024)}K bağlam` : '', gb(m.size)]
    .filter(Boolean).join(' · ');
  const engineLine = (e) => [KINDS[e.kind] ?? e.kind, e.pid ? `PID ${e.pid}` : '', e.device && e.device !== 'auto' ? e.device : '']
    .filter(Boolean).join(' · ');

  function outside(event) {
    if (open && !event.target.closest('.runtime-pop') && !(anchor && anchor.contains(event.target))) open = false;
  }
</script>

<svelte:window onclick={outside} onkeydown={(e) => { if (open && e.key === 'Escape') open = false; }} onresize={() => (open = false)} />

{#if open}
  <div class="runtime-pop" role="dialog" aria-label="Bellekteki modeller" style:left="{place.left}px" style:bottom="{place.bottom}px">
    <div class="head">
      <span>Model sunucusu</span>
      <button class="icon-btn sm" title="Yenile" disabled={llm.loading} onclick={refresh}><Icon name="refresh" size={14} spin={llm.loading} /></button>
    </div>
    {#if llm.loading && !llm.models?.length}
      <div class="empty"><Icon name="loader" size={14} spin />Yüklü modeller soruluyor…</div>
    {:else if llm.error}
      <div class="empty bad"><Icon name="alert" size={14} /><span class="selectable">{llm.error}</span></div>
    {:else if llm.models === null}
      <div class="empty">Bu sunucu bellekteki modelleri bildirmiyor; listeleme ve boşaltma yalnızca LM Studio'da var.</div>
    {:else}
      {#each llm.models as model (model.instance)}
        <div class="item">
          <span class="ic"><Icon name={model.type === 'embedding' ? 'database' : 'brain'} size={17} /></span>
          <span class="body">
            <b title={model.instance}>{model.name}</b>
            <small>{modelLine(model)}</small>
            {#if llm.kept.includes(model.instance)}<small class="tag">Aktar yükledi · kapanışta boşaltılır</small>{/if}
          </span>
          <button class="btn sm" title="LM Studio'ya bu modeli bellekten boşaltma isteği gönder" disabled={!!busy} onclick={() => ejectModel(model)}>
            <Icon name={busy === model.instance ? 'loader' : 'power'} size={14} spin={busy === model.instance} />Boşalt
          </button>
        </div>
      {:else}
        <div class="empty">Bellekte yüklü model yok. İlk istekte sunucu modeli kendisi yükler.</div>
      {/each}
    {/if}

    <div class="head sep"><span>Ses motoru</span></div>
    {#if engine}
      <div class="item">
        <span class="ic"><Icon name={engine.state === 'loading' ? 'loader' : 'waveform'} size={17} spin={engine.state === 'loading'} /></span>
        <span class="body">
          <b>{engine.name}{engine.voice ? ` · ${engine.voice}` : ''}</b>
          <small>{engineLine(engine)}</small>
          {#if engine.message}<small class="tag" title={engine.message}>{engine.message}</small>{/if}
        </span>
        <button class="btn sm" disabled={!!busy || engine.state === 'loading' || engine.busy}
          title={engine.state === 'loading' ? 'Yükleniyor; yüklenince boşaltılabilir' : engine.busy ? 'Ses kaydedilirken boşaltılamaz' : 'Ses motorunu durdur (bellek boşalır); okurken yeniden yüklenir'}
          onclick={ejectEngine}>
          <Icon name={busy === 'tts' ? 'loader' : 'power'} size={14} spin={busy === 'tts'} />Boşalt
        </button>
      </div>
    {:else}
      <div class="empty">Bellekte ses motoru yok. Sesli okuma, metinden ses ya da dublaj başlayınca yüklenir.</div>
    {/if}
  </div>
{/if}

<style>
  .runtime-pop { position: fixed; z-index: 45; width: 380px; max-width: calc(100vw - 24px); max-height: 70vh; overflow: auto; padding: 6px;
    background: var(--overlay); border: 1px solid var(--outline); border-radius: 14px; box-shadow: 0 8px 28px var(--shadow); white-space: normal; }
  .head { display: flex; align-items: center; justify-content: space-between; font-size: 11px; font-weight: 700; color: var(--dim);
    text-transform: uppercase; letter-spacing: .06em; padding: 6px 6px 4px 10px; min-height: 30px; }
  .head.sep { margin-top: 6px; border-top: 1px solid var(--outline); padding-top: 10px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 10px; }
  .item:hover { background: var(--surface-hover); }
  .ic { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .body b { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .body small { color: var(--secondary); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .body small.tag { color: var(--dim); font-size: 11px; }
  .btn { flex: none; }
  .empty { display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px 10px; color: var(--dim); font-size: 12px; line-height: 1.5; }
  .empty :global(svg) { flex: none; margin-top: 2px; }
  .empty.bad { color: var(--danger); }
</style>
