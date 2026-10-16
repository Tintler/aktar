// ffmpeg akisini (parcali MP4) Media Source Extensions ile <video>'ya besler.
// Akis `offset` anindan baslar; timestampOffset sayesinde videonun zamani gercek zamandir ve
// indirilmis kisimda tarayici kendisi sarar. Indirilmemis bir ana sarmak icin akis o andan
// yeniden baslatilir (start). Bellek: oynatma noktasinin cok gerisindeki veri silinir,
// cok ilerisi indirilmeden bekler. Tarayicinin MSE kotasi (~150 MB) dolarsa parca ATILMAZ
// (atilan parca akisi bozar): ileri sinir kucultulur ve oynatma ilerleyene kadar beklenir.

const AHEAD = 120;      // saniye: oynatma noktasinin bu kadar ilerisi indirilince bekle
const BEHIND = 90;      // saniye: bunun gerisindeki veri silinir
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const once = (target, name) => new Promise((resolve) => target.addEventListener(name, resolve, { once: true }));

export function mseSupported(mime) {
  return !!(window.MediaSource && mime && MediaSource.isTypeSupported(mime));
}

export class StreamFeed {
  constructor(video) {
    this.video = video;
    this.token = 0;
    this.controller = null;
    this.source = null;
    this.buffer = null;
    this.onerror = null;
    this.limit = AHEAD;
  }

  stop() {
    this.token++;
    this.controller?.abort();
    this.controller = null;
  }

  // Zaman `time` indirilmis bir araliktaysa true (o zaman yeniden baslatmaya gerek yok).
  has(time) {
    const ranges = this.video.buffered;
    for (let i = 0; i < ranges.length; i++) if (time >= ranges.start(i) && time <= ranges.end(i) - 0.3) return true;
    return false;
  }

  ahead() {
    const ranges = this.video.buffered;
    const now = this.video.currentTime;
    for (let i = 0; i < ranges.length; i++) if (now >= ranges.start(i) - 0.5 && now <= ranges.end(i)) return ranges.end(i) - now;
    return 0;
  }

  async start({ url, offset, mime, duration }) {
    this.stop();
    const token = this.token;
    this.limit = AHEAD;
    const controller = (this.controller = new AbortController());
    const source = new MediaSource();
    const objectUrl = URL.createObjectURL(source);
    this.video.src = objectUrl;
    await once(source, 'sourceopen');
    URL.revokeObjectURL(objectUrl);
    if (token !== this.token) return;
    let buffer;
    try {
      if (duration > 0) source.duration = duration;
      buffer = source.addSourceBuffer(mime);
      buffer.timestampOffset = offset;
    } catch (error) {
      this.onerror?.(error);
      return;
    }
    this.source = source;
    this.buffer = buffer;
    try {
      const response = await fetch(url, { signal: controller.signal });
      const reader = response.body.getReader();
      for (;;) {
        while (this.ahead() > this.limit && token === this.token) await sleep(400);
        if (token !== this.token) break;
        const { done, value } = await reader.read();
        if (done || token !== this.token) break;
        await this.append(buffer, value, token);
      }
      if (token === this.token && source.readyState === 'open') {
        while (buffer.updating) await once(buffer, 'updateend');
        source.endOfStream();
      }
    } catch (error) {
      if (token === this.token && error.name !== 'AbortError') this.onerror?.(error);
    }
  }

  async append(buffer, chunk, token) {
    while (buffer.updating) await once(buffer, 'updateend');
    if (token !== this.token) return;
    const now = this.video.currentTime;
    // Gerideki veriyi sil (uzun videolarda bellek dolmasin).
    if (buffer.buffered.length && now - buffer.buffered.start(0) > BEHIND + 30) {
      buffer.remove(0, now - BEHIND);
      await once(buffer, 'updateend');
    }
    for (;;) {
      try {
        buffer.appendBuffer(chunk);
        await once(buffer, 'updateend');
        return;
      } catch (error) {
        if (error.name !== 'QuotaExceededError') throw error;
      }
      // Kota doldu: yer acilana kadar bekle; sonraki parcalar daha az ileri indirilir.
      this.limit = Math.max(15, Math.min(this.limit, this.ahead()) * 0.7);
      const behind = this.video.currentTime - 10;
      if (buffer.buffered.length && behind > buffer.buffered.start(0) + 1) {
        buffer.remove(0, behind);
        await once(buffer, 'updateend');
      } else {
        await sleep(500);
      }
      if (token !== this.token) return;
    }
  }
}
