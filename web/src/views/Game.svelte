<script>
  // Oyun Cevirisi (F194): oyunun ekranindaki yaziyi okuyup Turkce cevirisini oyunun ustundeki katmanda gosterir.
  // Arka uc bridge_game.py (game_ onekli); canli durum 'game' olayiyla app.game.status'a gelir.
  // Ayarlar APP_DIR/oyun-ceviri/ayarlar.json, oyunlar (bolgeler + terimler) oyunlar/<kimlik>.json.
  import { onMount } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import Toggle from '../components/Toggle.svelte';
  import { app, act, toast } from '../lib/state.svelte.js';
  import { call } from '../lib/api.js';
  import { confirm, prompt } from '../lib/confirm.svelte.js';

  const TABS = [['live', 'Çeviri'], ['regions', 'Bölgeler'], ['terms', 'İsimler ve terimler'], ['settings', 'Ayarlar']];
  const PLACEMENTS = [['below', 'Bölgenin altında'], ['above', 'Bölgenin üstünde'], ['cover', 'Orijinal yazının üzerinde'], ['custom', 'Özel konumda']];
  const SPEAKERS = [['auto', 'Otomatik bul'], ['first_line', 'İlk satır her zaman ad'], ['none', 'Yok']];
  const ACTIONS = [['toggle', 'Çeviriyi aç / kapat'], ['overlay', 'Katmanı gizle / göster'], ['now', 'Şu anki ekranı şimdi çevir']];
  const ENGINES = [['auto', 'Otomatik (Windows OCR, yoksa Tesseract)'], ['windows', 'Windows OCR'], ['tesseract', 'Tesseract']];

  let snap = $state(null);
  let tab = $state('live');
  let tests = $state({});        // bolge kimligi -> deneme sonucu
  let picking = $state(false);
  let recording = $state('');    // kaydedilen kisayolun eylemi
  let termFilter = $state('');
  let draft = $state({ source: '', target: '', note: '' });

  const status = $derived(app.game.status);
  const settings = $derived(snap?.settings);
  const game = $derived(snap?.game);
  const regions = $derived(game?.regions ?? []);
  const terms = $derived(game?.terms ?? []);
  const models = $derived(app.models.names ?? []);
  const shownTerms = $derived(termFilter.trim()
    ? terms.map((t, i) => [t, i]).filter(([t]) => (t.source + ' ' + t.target).toLocaleLowerCase('tr').includes(termFilter.trim().toLocaleLowerCase('tr')))
    : terms.map((t, i) => [t, i]));
  const newSpeakers = $derived([...new Set((status.recent ?? []).map((r) => r.speaker).filter(Boolean))]
    .filter((name) => !terms.some((t) => t.source.toLocaleLowerCase('tr') === name.toLocaleLowerCase('tr'))));
  const ocrNote = $derived.by(() => {
    if (!snap || !game) return '';
    const tags = snap.ocr_languages ?? [];
    const has = tags.some((t) => t.toLowerCase().split('-')[0] === game.language);
    if (has) return `Windows OCR bu dili okuyabiliyor (${tags.join(', ')}).`;
    return `Windows OCR'da bu dil yüklü değil (yüklü: ${tags.join(', ') || 'yok'}). Windows Ayarlar → Zaman ve dil → Dil bölümünden dili ekleyin ya da Tesseract kullanılır; süslü yazılar için bölgeyi "Görsel model" yapın.`;
  });

  function apply(result) {
    if (!result) return false;
    snap = result;
    app.game.status = result.status;
    return true;
  }

  onMount(async () => {
    apply(await act('game_snapshot'));
    if (!models.length) call('refresh_models');
  });

  async function saveSettings(values) {
    apply(await act('game_save_settings', values));
  }

  async function saveGame(values) {
    const result = await act('game_update', values);
    if (result?.game) snap.game = result.game;
    return result;
  }

  async function newGame() {
    const name = await prompt({ title: 'Yeni oyun', message: 'Bölgeler ve isim listesi her oyun için ayrı tutulur.', placeholder: 'Oyunun adı' });
    if (name?.trim()) apply(await act('game_create', name.trim()));
  }

  async function renameGame() {
    const name = await prompt({ title: 'Oyunun adı', value: game.name });
    if (name?.trim()) await saveGame({ name: name.trim() });
    apply(await act('game_snapshot'));
  }

  async function deleteGame() {
    if (!(await confirm({ title: `"${game.name}" silinsin mi?`, message: 'Bölgeler, isim listesi ve çeviri önbelleği silinir.', ok: 'Sil', danger: true }))) return;
    apply(await act('game_delete', game.id));
  }

  // ---------------------------------------------------------------- bolgeler
  async function pick(hint) {
    picking = true;
    try {
      const result = await act('game_pick_region', hint);
      return result?.rect ? result : null;
    } finally {
      picking = false;
    }
  }

  async function addRegion() {
    const result = await pick('');
    if (!result) return;
    const textCount = regions.filter((r) => r.role === 'text').length;
    await saveGame({ regions: [...regions, { name: textCount ? `Bölge ${regions.length + 1}` : 'Diyalog', rect: result.rect, preview: result.preview }] });
  }

  async function updateRegion(index, values) {
    await saveGame({ regions: regions.map((r, i) => (i === index ? { ...r, ...values } : r)) });
  }

  async function reselect(index) {
    const result = await pick('');
    if (result) await updateRegion(index, { rect: result.rect, preview: result.preview });
  }

  async function chooseTarget(index) {
    const result = await pick('Çevirinin görüneceği alanı sürükleyerek seçin · Esc ya da sağ tık: vazgeç');
    if (result) await updateRegion(index, { placement: 'custom', target: result.rect });
  }

  async function placement(index, value) {
    if (value === 'custom' && !regions[index].target) await chooseTarget(index);
    else await updateRegion(index, { placement: value });
  }

  async function removeRegion(index) {
    if (!(await confirm({ title: `"${regions[index].name}" silinsin mi?`, ok: 'Sil', danger: true }))) return;
    await saveGame({ regions: regions.filter((_, i) => i !== index) });
  }

  async function test(region) {
    tests[region.id] = { busy: true };
    const result = await act('game_test_region', region);
    tests[region.id] = result ?? null;
  }

  // ---------------------------------------------------------------- terimler
  async function saveTerms(list) {
    await saveGame({ terms: list });
  }

  async function addTerm() {
    if (!draft.source.trim()) return;
    await saveTerms([{ ...draft }, ...terms]);
    draft = { source: '', target: '', note: '' };
  }

  function editTerm(index, key, value) {
    if (terms[index][key] === value) return;
    saveTerms(terms.map((t, i) => (i === index ? { ...t, [key]: value } : t)));
  }

  // ---------------------------------------------------------------- kisayollar
  const CODES = { Space: 'Space', Enter: 'Enter', Tab: 'Tab', Backspace: 'Backspace', Insert: 'Insert', Delete: 'Delete', Home: 'Home', End: 'End',
    PageUp: 'PageUp', PageDown: 'PageDown', Pause: 'Pause', ScrollLock: 'ScrollLock', ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right',
    Backquote: '`', Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Backslash: '\\', Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/',
    NumpadAdd: 'Numpad+', NumpadSubtract: 'Numpad-', NumpadMultiply: 'Numpad*', NumpadDivide: 'Numpad/' };

  function keyName(code) {
    let m;
    if ((m = code.match(/^Key([A-Z])$/)) || (m = code.match(/^Digit(\d)$/))) return m[1];
    if ((m = code.match(/^F(\d{1,2})$/))) return 'F' + m[1];
    if ((m = code.match(/^Numpad(\d)$/))) return 'Numpad' + m[1];
    return CODES[code] ?? '';
  }

  async function startRecording(action) {
    recording = action;
    await call('game_hotkeys_pause', true);
  }

  async function stopRecording() {
    if (!recording) return;
    recording = '';
    const result = await call('game_hotkeys_pause', false);
    if (result?.hotkey_errors) snap.hotkey_errors = result.hotkey_errors;
  }

  async function record(event) {
    if (!recording) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'Escape') { stopRecording(); return; }
    const key = keyName(event.code);
    if (!key) return;   // yalnizca degistirici basildi
    const mods = [event.ctrlKey && 'Ctrl', event.altKey && 'Alt', event.shiftKey && 'Shift', event.metaKey && 'Win'].filter(Boolean);
    if (!mods.length && !/^F\d+$|^Pause$|^ScrollLock$/.test(key)) {
      toast('Kısayolda Ctrl, Alt, Shift ya da Win de olmalı (F tuşları hariç).', 'warning');
      return;
    }
    const action = recording;
    recording = '';
    await call('game_hotkeys_pause', false);
    await saveSettings({ hotkeys: { ...settings.hotkeys, [action]: [...mods, key].join('+') } });
  }

  const start = async () => { const r = await act('game_start'); if (r) app.game.status = r; };
  const stop = async () => { const r = await act('game_stop'); if (r) app.game.status = r; };
  const overlay = async () => { const r = await act('game_overlay'); if (r) app.game.status = r; };
  const now = () => act('game_translate_now');
  const rect = (r) => r ? `${r[0]}, ${r[1]} · ${r[2]}×${r[3]}` : '';
</script>

<svelte:window onkeydown={record} />

<section class="page">
  <div class="page-head">
    <h1>Oyun Çevirisi</h1>
    {#if snap?.supported}
      <div class="games">
        <select class="field" value={settings.game} onchange={(e) => act('game_select', e.currentTarget.value).then(apply)} disabled={!snap.games.length}>
          {#if !snap.games.length}<option value="">Oyun yok</option>{/if}
          {#each snap.games as g}<option value={g.id}>{g.name}</option>{/each}
        </select>
        <button class="icon-btn filled" title="Yeni oyun" onclick={newGame}><Icon name="plus" size={18} /></button>
      </div>
      {#if game}
        {#if status.running}
          <button class="btn primary" onclick={stop}><Icon name="stop" size={15} />Durdur</button>
        {:else}
          <button class="btn primary" onclick={start} disabled={!regions.some((r) => r.enabled && r.role === 'text')}
            title={regions.length ? '' : 'Önce Bölgeler sekmesinden okunacak bölgeyi seçin'}><Icon name="play" size={15} />Başlat</button>
        {/if}
      {/if}
    {/if}
  </div>

  {#if !snap}
    <div class="page-body"><p class="dim">Yükleniyor…</p></div>
  {:else if !snap.supported}
    <div class="page-body"><div class="card empty"><Icon name="gamepad" size={32} /><b>Oyun çevirisi yalnızca Windows'ta çalışır.</b>
      <span>Ekran okuma ve oyunun üstündeki katman Windows'un pencere özelliklerini kullanıyor.</span></div></div>
  {:else if !game}
    <div class="page-body"><div class="card empty">
      <Icon name="gamepad" size={32} /><b>Türkçesi olmayan oyunları oynarken ekrandaki yazıyı anında çevirin.</b>
      <span>Önce oyunu ekleyin; sonra ekranda diyalog kutusunu seçip çeviriyi başlatın. Oyunun dosyalarına ya da belleğine dokunulmaz, yalnızca ekranda görünen okunur.</span>
      <button class="btn primary" onclick={newGame}><Icon name="plus" size={15} />Oyun ekle</button>
    </div></div>
  {:else}
    <div class="tabs" role="tablist">
      {#each TABS as [value, label]}
        <button role="tab" aria-selected={tab === value} class:on={tab === value} onclick={() => (tab = value)}>{label}
          {#if value === 'regions'}<i>{regions.length}</i>{:else if value === 'terms'}<i>{terms.length}</i>{/if}</button>
      {/each}
    </div>

    <div class="page-body">
      {#if tab === 'live'}
        <div class="live">
          <div class="card state">
            <div class="row">
              <span class="dot" class:on={status.running}></span>
              <b>{status.running ? 'Çeviri açık' : 'Çeviri kapalı'}</b>
              {#if status.info?.engine}<span class="dim small">{status.info.engine} · okuma {status.info.ocr_ms} ms</span>{/if}
              <div class="grow"></div>
              <button class="btn sm" onclick={overlay}><Icon name={status.overlay ? 'eye' : 'eye'} size={14} />{status.overlay ? 'Katmanı gizle' : 'Katmanı göster'}</button>
              <button class="btn sm" onclick={now}><Icon name="sparkles" size={14} />Şimdi çevir</button>
            </div>
            {#if status.error}<p class="err small selectable">{status.error}</p>{/if}
            {#if !status.overlay}<p class="warn small">Katman gizli: çeviri sürüyor ama oyunun üstünde gösterilmiyor.</p>{/if}
            <div class="keys">
              {#each ACTIONS as [action, label]}
                <span><kbd>{settings.hotkeys[action] || '—'}</kbd>{label}</span>
              {/each}
            </div>
            <p class="note small"><Icon name="info" size={14} /><span>Oyunu <b>pencereli tam ekran</b> (borderless / windowed fullscreen) modunda çalıştırın. Özel tam ekran (exclusive fullscreen) modunda katman oyunun üstünde görünmez ve ekran okunamaz. Fare, klavye ve oyun kumandası doğrudan oyuna gider; katman tıklamaları geçirir.</span></p>
          </div>

          <div class="recent">
            {#each status.recent ?? [] as item}
              <div class="card item">
                <div class="meta"><span>{item.time}</span><span>{item.region}</span>
                  <span class="badge" class:cached={item.cached}>{item.cached ? 'önbellekten' : `${(item.ms / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} sn`}</span></div>
                {#if item.speaker}<div class="who">{item.speaker}</div>{/if}
                <div class="tr selectable">{item.translation}</div>
                <div class="src selectable">{item.source}</div>
              </div>
            {:else}
              <p class="dim">Çevrilen satırlar burada görünür.</p>
            {/each}
          </div>
        </div>

      {:else if tab === 'regions'}
        <div class="bar">
          <button class="btn primary" onclick={addRegion} disabled={picking}><Icon name="plus" size={15} />Ekranda bölge seç</button>
          <span class="dim small">Aktar küçülür; oyunda okunacak alanı (ör. diyalog kutusu) fareyle sürükleyerek seçin. Esc ya da sağ tık vazgeçer.</span>
        </div>
        <div class="regions">
          {#each regions as region, index (region.id)}
            <div class="card region" class:off={!region.enabled}>
              <div class="head">
                <input class="field name" value={region.name} onchange={(e) => updateRegion(index, { name: e.currentTarget.value })} />
                <Toggle checked={region.enabled} onchange={(v) => updateRegion(index, { enabled: v })} label="Etkin" />
                <button class="icon-btn sm" title="Sil" onclick={() => removeRegion(index)}><Icon name="trash" size={15} /></button>
              </div>
              {#if region.preview}<img class="thumb" src={region.preview} alt="" />{/if}
              <div class="dim small">Ekranda: {rect(region.rect)}</div>
              <div class="grid">
                <label>Ne okunur
                  <select class="field" value={region.role} onchange={(e) => updateRegion(index, { role: e.currentTarget.value })}>
                    <option value="text">Çevrilecek yazı</option><option value="speaker">Konuşan karakterin adı</option>
                  </select>
                </label>
                {#if region.role === 'text'}
                  <label>Okuma yöntemi
                    <select class="field" value={region.mode} onchange={(e) => updateRegion(index, { mode: e.currentTarget.value, auto: e.currentTarget.value === 'ocr' })}>
                      <option value="ocr">Yazı okuma (hızlı)</option><option value="vision">Görsel model (süslü yazılar)</option>
                    </select>
                  </label>
                  {#if region.mode === 'ocr'}
                    <label>Konuşanın adı
                      <select class="field" value={region.speaker} onchange={(e) => updateRegion(index, { speaker: e.currentTarget.value })}>
                        {#each SPEAKERS as [value, label]}<option {value}>{label}</option>{/each}
                      </select>
                    </label>
                  {/if}
                  <label>Çeviri nerede görünsün
                    <select class="field" value={region.placement} onchange={(e) => placement(index, e.currentTarget.value)}>
                      {#each PLACEMENTS as [value, label]}<option {value}>{label}</option>{/each}
                    </select>
                  </label>
                {/if}
              </div>
              {#if region.role === 'text'}
                <Toggle checked={region.auto} onchange={(v) => updateRegion(index, { auto: v })}
                  label={region.mode === 'vision' ? 'Görüntü değişince otomatik gönder (kapalıyken yalnızca "Şimdi çevir" ile)' : 'Otomatik izle (kapalıyken yalnızca "Şimdi çevir" ile)'} />
              {:else}
                <p class="dim small">Bu bölgedeki ad, çeviriye konuşan karakter olarak verilir (hitap ve ton için).</p>
              {/if}
              <div class="actions">
                <button class="btn sm" onclick={() => reselect(index)} disabled={picking}><Icon name="squarePen" size={14} />Yeniden seç</button>
                {#if region.placement === 'custom'}<button class="btn sm" onclick={() => chooseTarget(index)} disabled={picking}><Icon name="squarePen" size={14} />Çeviri konumunu seç</button>{/if}
                {#if region.mode === 'ocr'}<button class="btn sm" onclick={() => test(region)}><Icon name="search" size={14} />Şimdi oku</button>{/if}
              </div>
              {#if tests[region.id]}
                <div class="test">
                  {#if tests[region.id].busy}<span class="dim small">Okunuyor…</span>
                  {:else}
                    <div class="dim small">{tests[region.id].engine} · {tests[region.id].ms} ms{#if tests[region.id].speaker} · konuşan: <b>{tests[region.id].speaker}</b>{/if}</div>
                    <div class="selectable">{tests[region.id].text || '(yazı bulunamadı)'}</div>
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            <p class="dim">Henüz bölge yok. Oyunu açın, sonra "Ekranda bölge seç" ile diyalog kutusunu seçin. Konuşanın adı ayrı bir kutudaysa onu da "Konuşan karakterin adı" olarak ekleyebilirsiniz.</p>
          {/each}
        </div>

      {:else if tab === 'terms'}
        <div class="terms">
          <p class="dim small">Bu oyunun karakter, yer ve eşya adları. Karşılığı boş bırakılan ad çevrilmez, olduğu gibi kalır. Büyük harfle yazılan ad (ör. <b>Rain</b>) yalnızca büyük harfle geçtiğinde eşleşir: küçük harfli "rain" sıradan kelime olarak çevrilir; cümle başında hangisi olduğuna model bağlama göre karar verir.</p>
          <div class="add">
            <input class="field" placeholder="Ad ya da terim (ör. Lasswell)" bind:value={draft.source} onkeydown={(e) => e.key === 'Enter' && addTerm()} />
            <input class="field" placeholder="Türkçe karşılığı (boş: çevrilmez)" bind:value={draft.target} onkeydown={(e) => e.key === 'Enter' && addTerm()} />
            <input class="field" placeholder="Not (ör. kadın, Rain'in kardeşi)" bind:value={draft.note} onkeydown={(e) => e.key === 'Enter' && addTerm()} />
            <button class="btn primary" onclick={addTerm} disabled={!draft.source.trim()}><Icon name="plus" size={15} />Ekle</button>
          </div>
          {#if newSpeakers.length}
            <div class="suggest small"><span class="dim">Son konuşanlar:</span>
              {#each newSpeakers as name}<button class="chip" onclick={() => saveTerms([{ source: name, target: '', note: '' }, ...terms])}><Icon name="plus" size={12} />{name}</button>{/each}
            </div>
          {/if}
          {#if terms.length > 8}<input class="field filter" placeholder="Listede ara" bind:value={termFilter} />{/if}
          <div class="list">
            {#each shownTerms as [term, index] (term.source)}
              <div class="term">
                <input class="field" value={term.source} onchange={(e) => editTerm(index, 'source', e.currentTarget.value)} />
                <input class="field" value={term.target} placeholder="(çevrilmez)" onchange={(e) => editTerm(index, 'target', e.currentTarget.value)} />
                <input class="field" value={term.note} placeholder="Not" onchange={(e) => editTerm(index, 'note', e.currentTarget.value)} />
                <button class="icon-btn sm" title="Sil" onclick={() => saveTerms(terms.filter((_, i) => i !== index))}><Icon name="trash" size={15} /></button>
              </div>
            {:else}
              <p class="dim">Liste boş.</p>
            {/each}
          </div>
        </div>

      {:else}
        <div class="settings">
          <section class="card">
            <h3>Model</h3>
            <label class="fr"><span>Çeviri modeli<small>Küçük ve hızlı bir model önerilir: oyun da ekran kartını kullanıyor. Düşünme (reasoning) her zaman kapalıdır.</small></span>
              <select class="field" value={settings.model} onchange={(e) => saveSettings({ model: e.currentTarget.value })}>
                <option value="">(Ayarlar'daki analiz modeli)</option>
                {#each [...new Set([...models, settings.model].filter(Boolean))] as m}<option value={m}>{m}</option>{/each}
              </select>
            </label>
            <label class="fr"><span>Görsel model<small>"Görsel model" bölgeleri ve bölge yokken "Şimdi çevir" için; görüntü okuyabilen bir model olmalı.</small></span>
              <select class="field" value={settings.vision_model} onchange={(e) => saveSettings({ vision_model: e.currentTarget.value })}>
                <option value="">(Ayarlar'daki görsel model)</option>
                {#each [...new Set([...models, settings.vision_model].filter(Boolean))] as m}<option value={m}>{m}</option>{/each}
              </select>
            </label>
            {#if app.models.state === 'failed'}<p class="err small selectable">{app.models.message}</p>{/if}
          </section>

          <section class="card">
            <h3>Okuma</h3>
            <label class="fr"><span>Oyunun dili<small>{ocrNote}</small></span>
              <select class="field" value={game.language} onchange={(e) => saveGame({ language: e.currentTarget.value }).then(() => act('game_snapshot').then(apply))}>
                {#each snap.languages as l}<option value={l.code}>{l.label}</option>{/each}
              </select>
            </label>
            <label class="fr"><span>Yazı okuma</span>
              <select class="field" value={settings.ocr_engine} onchange={(e) => saveSettings({ ocr_engine: e.currentTarget.value })}>
                {#each ENGINES as [value, label]}<option {value}>{label}</option>{/each}
              </select>
            </label>
            <label class="fr"><span>Ekranı okuma sıklığı<small>Bölge yalnızca değişince okunur. Kısa aralık daha hızlı tepki verir.</small></span>
              <span class="range"><input type="range" min="100" max="1000" step="50" value={settings.interval_ms} onchange={(e) => saveSettings({ interval_ms: +e.currentTarget.value })} /><b>{settings.interval_ms} ms</b></span>
            </label>
            <label class="fr"><span>Yazının yerleşmesini bekle<small>Harf harf gelen diyalog bu süre değişmeden kalınca çevrilir.</small></span>
              <span class="range"><input type="range" min="100" max="1500" step="50" value={settings.settle_ms} onchange={(e) => saveSettings({ settle_ms: +e.currentTarget.value })} /><b>{settings.settle_ms} ms</b></span>
            </label>
            <label class="fr"><span>Bağlam satırları<small>Önceki satırlar modele bağlam olarak verilir (hitap ve tutarlılık için).</small></span>
              <span class="range"><input type="range" min="0" max="6" step="1" value={settings.context_lines} onchange={(e) => saveSettings({ context_lines: +e.currentTarget.value })} /><b>{settings.context_lines}</b></span>
            </label>
          </section>

          <section class="card">
            <h3>Görünüm</h3>
            <label class="fr"><span>Yazı boyutu</span>
              <span class="range"><input type="range" min="12" max="56" step="1" value={settings.font_size} onchange={(e) => saveSettings({ font_size: +e.currentTarget.value })} /><b>{settings.font_size} px</b></span>
            </label>
            <label class="fr"><span>Zemin opaklığı<small>0: tamamen saydam, 100: opak. "Orijinal yazının üzerinde" için yüksek tutun.</small></span>
              <span class="range"><input type="range" min="0" max="100" step="5" value={Math.round(settings.opacity * 100)} onchange={(e) => saveSettings({ opacity: +e.currentTarget.value / 100 })} /><b>%{Math.round(settings.opacity * 100)}</b></span>
            </label>
            <label class="fr"><span>Renkler<small>Yazı ve zemin</small></span>
              <span class="colors">
                <input type="color" value={settings.text_color} onchange={(e) => saveSettings({ text_color: e.currentTarget.value })} />
                <input type="color" value={settings.background} onchange={(e) => saveSettings({ background: e.currentTarget.value })} />
                <span class="sample" style:color={settings.text_color} style:background={settings.background} style:font-size="{Math.min(settings.font_size, 22)}px"
                  style:opacity={0.35 + settings.opacity * 0.65}>Örnek çeviri</span>
              </span>
            </label>
            <div class="fr"><span>Konuşanın adını göster</span><Toggle checked={settings.show_speaker} onchange={(v) => saveSettings({ show_speaker: v })} /></div>
            <div class="fr"><span>Yazı kaybolunca çeviriyi gizle</span><Toggle checked={settings.hide_when_gone} onchange={(v) => saveSettings({ hide_when_gone: v })} /></div>
          </section>

          <section class="card">
            <h3>Kısayollar</h3>
            <p class="dim small">Oyun açıkken de çalışır. Değiştirmek için kutuya tıklayıp yeni tuş birleşimine basın (Esc: vazgeç). Seçilen birleşim Aktar açıkken başka programlara gitmez.</p>
            {#each ACTIONS as [action, label]}
              <div class="fr"><span>{label}{#if snap.hotkey_errors?.[action]}<small class="err">{snap.hotkey_errors[action]}</small>{/if}</span>
                <span class="hk">
                  <button class="field key" class:rec={recording === action} onclick={() => startRecording(action)} onblur={stopRecording}>
                    {recording === action ? 'Tuşlara basın…' : settings.hotkeys[action] || 'Yok'}</button>
                  {#if settings.hotkeys[action]}<button class="icon-btn sm" title="Kısayolu kaldır" onclick={() => saveSettings({ hotkeys: { ...settings.hotkeys, [action]: '' } })}><Icon name="x" size={14} /></button>{/if}
                </span>
              </div>
            {/each}
          </section>

          <section class="card">
            <h3>{game.name}</h3>
            <div class="fr"><span>Çeviri önbelleği<small>Daha önce çevrilen {snap.cache} cümle; aynı cümle gelince model beklenmeden gösterilir.</small></span>
              <button class="btn sm" disabled={!snap.cache} onclick={async () => { const r = await act('game_clear_cache'); if (r) snap.cache = 0; }}><Icon name="trash" size={14} />Temizle</button></div>
            <div class="fr"><span>Oyun</span>
              <span class="hk"><button class="btn sm" onclick={renameGame}><Icon name="pencil" size={14} />Yeniden adlandır</button>
                <button class="btn sm danger" onclick={deleteGame}><Icon name="trash" size={14} />Sil</button></span></div>
          </section>
        </div>
      {/if}
    </div>
  {/if}
</section>

<style>
  .games { display: flex; gap: 6px; align-items: center; }
  .games select { min-width: 220px; }
  .tabs { display: flex; gap: 4px; background: var(--surface); border-radius: 999px; padding: 3px; margin: 0 32px 16px; align-self: flex-start; }
  .tabs button { padding: 5px 14px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--secondary); display: flex; align-items: center; gap: 6px; }
  .tabs button.on { background: var(--surface-active); color: var(--text); }
  .tabs i { font-style: normal; font-size: 11px; color: var(--dim); }
  .dim { color: var(--dim); }
  .small { font-size: 12px; }
  .err { color: var(--danger); }
  .warn { color: var(--warning); }
  .grow { flex: 1; }
  .empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 48px 24px; text-align: center; max-width: 640px; margin: 24px auto; }
  .empty :global(svg) { color: var(--accent); }
  .empty span { color: var(--secondary); font-size: 13px; }
  .live { display: flex; flex-direction: column; gap: 14px; max-width: 980px; }
  .state { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--surface-active); }
  .dot.on { background: var(--ok); box-shadow: 0 0 0 4px color-mix(in srgb, var(--ok) 25%, transparent); }
  .keys { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--secondary); }
  .keys span { display: flex; align-items: center; gap: 6px; }
  kbd { font: 600 11px/1 ui-monospace, monospace; padding: 4px 7px; border-radius: 6px; background: var(--surface); border: 1px solid var(--outline); color: var(--text); }
  .note { display: flex; gap: 8px; align-items: flex-start; color: var(--secondary); line-height: 1.5; }
  .note :global(svg) { flex: none; margin-top: 2px; color: var(--accent); }
  .recent { display: flex; flex-direction: column; gap: 8px; }
  .item { padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
  .meta { display: flex; gap: 10px; font-size: 11px; color: var(--dim); }
  .badge { margin-left: auto; }
  .badge.cached { color: var(--ok); }
  .who { font-size: 12px; font-weight: 700; color: var(--accent); }
  .tr { font-size: 15px; line-height: 1.5; }
  .src { font-size: 12px; color: var(--dim); line-height: 1.4; }
  .bar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
  .regions { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 14px; }
  .region { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .region.off { opacity: .6; }
  .head { display: flex; align-items: center; gap: 10px; }
  .head .name { flex: 1; min-width: 0; font-weight: 600; }
  .thumb { width: 100%; max-height: 140px; object-fit: contain; background: #000; border-radius: 8px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--secondary); }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .test { padding: 10px 12px; border-radius: 8px; background: var(--surface); display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .terms { display: flex; flex-direction: column; gap: 12px; max-width: 980px; }
  .add, .term { display: grid; grid-template-columns: 1fr 1fr 1.3fr auto; gap: 8px; align-items: center; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .suggest { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .suggest .chip { display: inline-flex; align-items: center; gap: 4px; height: 26px; font-size: 12px; }
  .filter { max-width: 320px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 14px; align-items: start; }
  .settings section { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .settings h3 { font-size: 15px; font-weight: 700; }
  .fr { display: flex; align-items: center; justify-content: space-between; gap: 16px; font-size: 13px; }
  .fr > span:first-child { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .fr small { font-size: 11px; color: var(--dim); line-height: 1.4; }
  .fr small.err { color: var(--danger); }
  .fr select { max-width: 240px; }
  .range { display: flex; align-items: center; gap: 8px; flex: none; }
  .range input { width: 150px; accent-color: var(--accent); }
  .range b { min-width: 56px; font-size: 12px; text-align: right; }
  .colors { display: flex; align-items: center; gap: 8px; flex: none; }
  .colors input { width: 34px; height: 28px; border: 0; padding: 0; background: none; cursor: pointer; }
  .sample { padding: 4px 10px; border-radius: 6px; }
  .hk { display: flex; align-items: center; gap: 6px; flex: none; }
  .key { min-width: 150px; justify-content: center; display: inline-flex; align-items: center; font-weight: 600; cursor: pointer; }
  .key.rec { border-color: var(--accent); color: var(--accent); }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } .add, .term { grid-template-columns: 1fr 1fr; } }
</style>
