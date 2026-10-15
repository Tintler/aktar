"""Kutuphane sayfasinin arka ucu (Bridge'e karisan sinif): koleksiyonlar, dosya tablosu,
transkript aramasi, toplu hazirlik kuyrugu, disa aktarma ve koleksiyona sor.

Koleksiyon mantigi library.py / collection_qa.py'dedir; burada eski library_panel'in
akisi arayuzden bagimsiz tutulur. Tarama ve durum okuma arka planda yapilir; sonuc
'library' olayiyla gelir. Kaynak dosyalar SALT-OKUNUR: "Koleksiyondan cikar" yalnizca
kaydi degistirir.
"""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

import chat_templates
import collection_qa
import documents
import library
import qa
import search_index
import speech
import transcript_export
import video_frames
from app_core import Client, GracefulStop, load_config

CHAT_GREETING = ('Bu koleksiyondaki dosyalar hakkında soru sorun; cevaplar hangi dosyada, '
                 'hangi dakikada ya da sayfada geçtiğini gösterir.')
MIN_SEARCH_CHARS = 3     # transkript aramasi bu uzunluktan sonra baslar
HIT_LIMIT = 200          # gosterilen en fazla transkript eslesmesi
REPEATED_ERROR_LIMIT = 3  # ust uste ayni hata: kuyruk durur
KIND_LABELS = {'video': 'Video', 'document': 'Belge', 'image': 'Görsel'}
STATUS_TEXT = {'ready': 'Hazır', 'transcript': 'Metin hazır', 'pending': 'Bekliyor',
               'no_subtitle': 'Altyazı yok · Whisper bekliyor',
               'no_text': 'Metin yok · OCR bekliyor', 'missing': 'Bulunamadı'}
META_TEXT = {'ready': 'hazır', 'transcript': 'metin hazır', 'pending': 'bekliyor',
             'no_subtitle': 'Whisper bekliyor', 'no_text': 'OCR bekliyor', 'missing': 'bulunamadı'}
OCR_OVERRIDES = ('tesseract', 'model', 'vision')  # prepare_start: yalnizca bu hazirlik icin
PLAN_GROUPS = ('ready', 'summary', 'index', 'document', 'subtitle', 'vision', 'whisper', 'frames')


def format_duration(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def format_size(path):
    try:
        size = Path(path).stat().st_size
    except OSError:
        return '—'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit in ('B', 'KB') else f'{size:.1f} {unit}'
        size /= 1024
    return '—'


def where(entry):
    """Klasor sutunu: kaynak klasore gore goreli alt klasor (kokteyse klasor adi)."""
    parent = entry['path'].parent
    if entry['root']:
        try:
            relative = parent.relative_to(entry['root'])
        except ValueError:
            return parent.name
        return Path(entry['root']).name if str(relative) == '.' else str(relative)
    return parent.name


def row_of(entry, info, dates=None, fallback=None):
    """Tablo satiri (JSON): transkript satirlari arayuze gonderilmez.

    `dates`: elle girilen belge tarihleri (library.manual_dates); icerikten cikarilani ezer.
    `fallback`: {anahtar: tarih} postanin gelis tarihi (F89); yalnizca baska tarih yoksa."""
    key = library._key(entry['path'])
    manual = (dates or {}).get(key, '')
    content = info.get('date', '')
    mail = '' if manual or content else (fallback or {}).get(key, '')
    date = collection_qa.normalize_date(manual or content or mail)
    if entry['kind'] == 'image':
        length = '—' if entry['missing'] else format_size(entry['path'])
    elif info['duration'] and entry['kind'] == 'document':
        length = f'{int(info["duration"])} sayfa'
    elif info['duration']:
        length = format_duration(info['duration'])
    else:
        length = '—' if entry['missing'] else format_size(entry['path'])
    return {'key': library._key(entry['path']), 'path': str(entry['path']), 'name': entry['path'].name,
            'kind': entry['kind'], 'where': where(entry), 'folder': str(entry['path'].parent),
            'length': length, 'measured': bool(info['duration']), 'source': info['source'],
            'status': info['status'], 'status_text': STATUS_TEXT[info['status']],
            'new': bool(entry['new']), 'missing': bool(entry['missing']),
            'length_sort': _length_sort(entry, info),
            'date': date, 'date_text': collection_qa.format_date(date), 'date_manual': bool(manual),
            'date_mail': bool(mail)}


def _length_sort(entry, info):
    """Uzunluk sutununu siralamak icin (F93): once tur (video sure, belge sayfa, digerleri boyut),
    sonra sayi. Bulunamayan dosya None (sonda)."""
    if entry['missing']:
        return None
    if info.get('duration') and entry['kind'] != 'image':
        return [0 if entry['kind'] == 'video' else 1, float(info['duration'])]
    try:
        return [2, Path(entry['path']).stat().st_size]
    except OSError:
        return None


STREAM_INTERVAL = 0.08  # saniye: akis olaylarinin en sik gonderilme araligi


def pending_entry(value):
    """Bekleyen kayit: duz metin ya da canli dusunceli {'text', 'thinking'} (F102)."""
    if isinstance(value, dict):
        return {'kind': 'pending', 'text': str(value.get('text') or ''), 'thinking': str(value.get('thinking') or '')}
    return {'kind': 'pending', 'text': str(value), 'thinking': ''}


def reasoning_feed(entries, push):
    """Uretim sirasindaki dusunceyi bekleyen kayda yazan on_reasoning geri cagrisi (F102).

    entries() guncel kayit listesini verir; push() arayuze olay yayar (STREAM_INTERVAL ile seyreltilir)."""
    last = [0.0]

    def feed(text):
        items = entries()
        for index, (kind, value) in enumerate(items):
            if kind == 'pending':
                label = value.get('text', '') if isinstance(value, dict) else value
                items[index] = ('pending', {'text': label, 'thinking': text})
        now = time.monotonic()
        if now - last[0] >= STREAM_INTERVAL:
            last[0] = now
            push()
    return feed


def chat_entries(entries):
    """Sohbet kayitlari (tur, deger) -> arayuzun ciz(ebil)ecegi JSON."""
    result = []
    for kind, value in entries:
        if kind == 'pending':
            result.append(pending_entry(value))
        elif kind == 'assistant':
            parts = []
            for part_kind, part in value.get('parts', []):
                if part_kind == 'cite':
                    parts.append({'type': 'cite', 'items': [
                        {'path': str(cite['video']), 'start': cite['start'], 'label': cite['label'],
                         'title': cite.get('title', ''), 'document': bool(cite.get('document'))}
                        for cite in part]})
                else:
                    parts.append({'type': 'text', 'text': str(part)})
            sources = [{'path': str(item['video']), 'start': item['start'], 'label': item['label'],
                        'title': item['title'], 'count': item['count']} for item in value.get('sources', [])]
            result.append({'kind': 'assistant', 'parts': parts, 'sources': sources,
                           'thinking': str(value.get('thinking') or ''), 'think': value.get('think'),
                           'template': str(value.get('template') or '')})
        else:
            result.append({'kind': kind, 'text': str(value)})
    return result


class LibraryMixin:
    def _init_library(self):
        self._lib_slug = ''
        self._lib_data = None
        self._lib_entries = []
        self._lib_infos = []
        self._lib_generation = 0
        self._lib_scanning = False
        self._lib_check_folders = set()
        self._lib_plan = None             # son 'Hepsini hazirla' plani
        self._lib_plan_cancel = None
        self._queue_worker = None         # threading.Thread
        self._queue = None                # kuyruk durumu (sozluk)
        self._queue_cancel = threading.Event()
        self._queue_resume = threading.Event()
        self._row_status = {}             # anahtar -> kuyruk sirasinda gecici durum
        self._chats = {}                  # slug -> {'session', 'history', 'entries'}
        self._ask_busy = False
        self._overviews = {}

    # ------------------------------------------------------------------ durum
    def library_collections(self):
        result = []
        for slug, data in library.list_collections().items():
            result.append({'slug': slug, 'title': data['title'], 'folders': len(data.get('folders', [])),
                           'files': len(data.get('files', []))})
        return result

    def library_overview(self):
        """Kutuphane ana sayfasi: her koleksiyon icin dosya sayisi ve (varsa) ozeti."""
        result = []
        for slug, data in library.list_collections().items():
            overview = library.load_overview(slug) or {}
            result.append({'slug': slug, 'title': data['title'], 'folders': len(data.get('folders', [])),
                           'count': len(data.get('known') or []) or len(data.get('files', [])),
                           'summary': str(overview.get('summary', '')),
                           'topics': list(overview.get('topics') or [])[:4]})
        return result

    def _folders(self):
        counts = {}
        for entry in self._lib_entries:
            if entry['root']:
                counts[entry['root']] = counts.get(entry['root'], 0) + 1
        return [{'path': folder, 'name': Path(folder).name or folder, 'count': counts.get(folder, 0)}
                for folder in (self._lib_data or {}).get('folders', [])]

    def _meta(self):
        counts = {}
        for info in self._lib_infos:
            counts[info['status']] = counts.get(info['status'], 0) + 1
        parts = [f'{len(self._lib_entries)} dosya']
        parts += [f'{counts[key]} {META_TEXT[key]}' for key in
                  ('ready', 'transcript', 'pending', 'no_subtitle', 'no_text', 'missing') if counts.get(key)]
        return ' · '.join(parts)

    def library_state(self):
        data = self._lib_data
        dates = library.manual_dates(data) if data else {}
        fallback = self._mail_fallback()
        rows = [row_of(entry, info, dates, fallback) for entry, info in zip(self._lib_entries, self._lib_infos)]
        for row in rows:
            if row['key'] in self._row_status:
                row['busy_text'], row['busy_tone'] = self._row_status[row['key']]
        return {'collections': self.library_collections(), 'slug': self._lib_slug,
                'title': data['title'] if data else '', 'folders': self._folders() if data else [],
                'rows': rows, 'meta': self._meta() if data else '', 'scanning': self._lib_scanning,
                'queue': self._queue, 'kinds': KIND_LABELS, 'watch': bool((data or {}).get('watch'))}

    def _mail_fallback(self):
        return {library._key(path): value for path, value in getattr(self, '_mail_dates', {}).items()}

    def _push_library(self):
        self._emit('library', self.library_state())

    # ------------------------------------------------------------------ koleksiyonlar
    def library_open(self, slug=None):
        """Koleksiyonu acar (bos: ilk koleksiyon) ve klasorleri arka planda yeniden tarar."""
        collections = library.list_collections()
        slug = slug or self._lib_slug or next(iter(collections), '')
        if not slug or slug not in collections:
            self._lib_slug, self._lib_data, self._lib_entries, self._lib_infos = '', None, [], []
            return self.library_state()
        try:
            data = library.load_collection(slug)
        except (OSError, ValueError) as error:
            return {'error': 'Koleksiyon açılamadı: ' + str(error)}
        if slug != self._lib_slug:
            self._lib_entries, self._lib_infos = [], []
        self._lib_slug, self._lib_data = slug, data
        self._rescan()
        if hasattr(self, '_mail_auto'):
            self._mail_auto()  # F89: yeni postalar arka planda indirilir
        return self.library_state()

    def _rescan(self):
        if self._lib_data is None:
            return
        self._lib_generation += 1
        generation, slug, data = self._lib_generation, self._lib_slug, copy.deepcopy(self._lib_data)
        self._lib_scanning = True

        def work():
            try:
                entries, changed = library.scan(data)
                cfg = library._embedding_cfg(None)
                infos = [library.describe(entry, cfg=cfg) for entry in entries]
            except Exception as error:  # tarama hatasi arayuzu dusurmesin
                if generation == self._lib_generation:
                    self._lib_scanning = False
                    self._emit('toast', {'message': 'Koleksiyon taranamadı: ' + str(error), 'kind': 'error'})
                    self._push_library()
                return
            if generation != self._lib_generation or slug != self._lib_slug:
                return  # bu arada baska koleksiyon secildi / icerik degisti
            self._lib_data = data
            if changed:
                try:
                    library.save_collection(data, slug)
                except RuntimeError as error:
                    self._log('UYARI: ' + str(error))
            self._lib_entries, self._lib_infos = entries, infos
            self._lib_scanning = False
            self._warn_empty_folders()
            self._push_library()
            self._push_chat()

        threading.Thread(target=work, name='aktar-library-scan', daemon=True).start()

    def library_rescan(self):
        self._rescan()
        return self.library_state()

    def _warn_empty_folders(self):
        check, self._lib_check_folders = self._lib_check_folders, set()
        roots = {entry['root'] for entry in self._lib_entries if entry['root']}
        empty = [folder for folder in check if folder not in roots]
        if empty:
            kinds = ', '.join(sorted(library.supported_suffixes()))
            self._emit('toast', {'kind': 'error', 'message': 'Şu klasörlerde desteklenen dosya bulunamadı: '
                                 + ', '.join(Path(folder).name for folder in empty)
                                 + f'. Desteklenen türler: {kinds}'})

    def _save_collection(self, message=''):
        try:
            library.save_collection(self._lib_data, self._lib_slug)
        except RuntimeError as error:
            return {'error': str(error)}
        if message:
            self._log(message)
        self._rescan()
        return self.library_state()

    def new_collection(self, title):
        try:
            slug, _data = library.create_collection(title)
        except (ValueError, RuntimeError) as error:
            return {'error': str(error)}
        self._log('Koleksiyon oluşturuldu: ' + ' '.join(str(title).split()))
        return self.library_open(slug)

    def rename_collection(self, slug, title):
        try:
            library.rename_collection(slug, title)
        except (ValueError, RuntimeError) as error:
            return {'error': str(error)}
        if slug == self._lib_slug and self._lib_data is not None:
            self._lib_data['title'] = ' '.join(str(title).split())
        return self.library_state()

    def delete_collection(self, slug):
        try:
            title = library.load_collection(slug)['title']
        except (OSError, ValueError) as error:
            return {'error': str(error)}
        library.delete_collection(slug)
        self._chats.pop(slug, None)
        self._overviews.pop(slug, None)
        self._log('Koleksiyon silindi: ' + title)
        if slug == self._lib_slug:
            self._lib_slug, self._lib_data, self._lib_entries, self._lib_infos = '', None, [], []
        return self.library_open()

    # ------------------------------------------------------------------ ekleme / cikarma
    def library_choose_folder(self, new_collection=False):
        folder = self._dialog('open_folder', 'Klasör seç')
        return self.library_add_paths([folder], new_collection) if folder else None

    def library_choose_files(self):
        patterns = ['Desteklenen dosyalar (' + ';'.join('*' + suffix for suffix in library.supported_suffixes()) + ')']
        patterns += [f'{KIND_LABELS.get(kind, kind)} (' + ';'.join('*' + suffix for suffix in suffixes) + ')'
                     for kind, suffixes in library.KINDS.items()]
        paths = self._dialog('open_files', 'Dosya seç', tuple(patterns))
        return self.library_add_paths(paths) if paths else None

    def library_add_paths(self, paths, new_collection=False):
        """Birakilan/secilen klasor ve dosyalari acik koleksiyona ekler; koleksiyon yoksa (ya da
        `new_collection` ile, kutuphane ana sayfasinda) klasorun adiyla yeni koleksiyon kurar."""
        paths = [str(path) for path in paths or []]
        folders = [path for path in paths if Path(path).is_dir()]
        files = [path for path in paths if Path(path).is_file()]
        skipped = [Path(path).name for path in files if library.kind_of(path) is None]
        files = [path for path in files if library.kind_of(path) is not None]
        if not folders and not files:
            return {'error': 'Desteklenen dosya bulunamadı.'
                    + (' Atlananlar: ' + ', '.join(skipped[:5]) if skipped else '')}
        self._lib_check_folders = {library._clean(folder) for folder in folders}
        if self._lib_data is None or new_collection:
            try:
                slug, _data = library.create_collection(library.default_title(folders + files),
                                                        folders=folders, files=files)
            except (ValueError, RuntimeError) as error:
                return {'error': str(error)}
            self._log('Koleksiyon oluşturuldu: ' + library.load_collection(slug)['title'])
            return self.library_open(slug)
        changed = sum(1 for folder in folders if library.add_folder(self._lib_data, folder))
        changed += library.add_files(self._lib_data, files)
        if not changed:
            self._log('Eklenenler zaten koleksiyonda.')
            self._emit('toast', {'message': 'Eklenenler zaten koleksiyonda.', 'kind': 'info'})
            return self.library_state()
        return self._save_collection(f'Koleksiyona eklendi: {len(folders)} klasör, {len(files)} dosya.')

    def library_remove_folder(self, folder):
        removed = [entry['path'] for entry in self._lib_entries if entry['root'] == folder]
        if self._lib_data is None or not library.remove_folder(self._lib_data, folder):
            return self.library_state()
        state = self._save_collection('Klasör koleksiyondan kaldırıldı: ' + folder)
        self._forget(removed)
        return state

    def library_exclude(self, paths):
        paths = [Path(path) for path in paths or []]
        if not paths or self._lib_data is None:
            return self.library_state()
        library.exclude(self._lib_data, paths)
        state = self._save_collection(f'{len(paths)} dosya koleksiyondan çıkarıldı (diskte duruyor).')
        self._forget(paths)
        return state

    def library_set_date(self, paths, value):
        """Belge tarihini elle ayarlar (F88); bos deger icerikten cikarilan tarihe doner."""
        paths = [Path(path) for path in paths or []]
        if not paths or self._lib_data is None:
            return self.library_state()
        text = str(value or '').strip()
        date = collection_qa.normalize_date(text)
        if text and not date:
            return {'error': f'Tarih anlaşılamadı: "{text}". Örnek: 15.09.2026, 09.2026 ya da 2026.'}
        library.set_date(self._lib_data, paths, date)
        chat = self._chats.get(self._lib_slug)
        if chat is not None:
            chat['session'] = None  # sohbet baglami yeni tarihlerle kurulsun
        names = ', '.join(path.name for path in paths[:3]) + (' …' if len(paths) > 3 else '')
        return self._save_collection(f'Tarih {collection_qa.format_date(date) if date else "içerikten"}: {names}')

    def _forget(self, paths):
        """Cikarilan dosyalar sohbette ve koleksiyon ozetinde hatirlanmasin."""
        if not paths or self._lib_data is None:
            return
        slug, keys = self._lib_slug, {library._key(path) for path in paths}
        chat = self._chat(slug)
        chat['session'], chat['history'] = None, []
        chat['entries'].append(('note', f'{len(paths)} dosya koleksiyondan çıkarıldı; sohbet '
                                        'bundan sonra onları kullanmaz.'))
        library.save_chat(slug, chat['entries'], chat['history'])
        self._push_chat()
        overview = library.load_overview(slug)
        if not overview or not keys & {library._key(item) for item in overview.get('videos', [])}:
            return
        library.overview_path(slug).unlink(missing_ok=True)
        self._overviews.pop(slug, None)
        self._push_chat()
        remaining = [entry['path'] for entry in self._lib_entries
                     if not entry['missing'] and library._key(entry['path']) not in keys]
        title = self._lib_data['title']
        dates = dict(self._lib_data.get('dates') or {})

        def work():
            try:
                rebuilt = collection_qa.build_overview(title, remaining, load_config(), log=lambda _message: None,
                                                       dates=dates)
                if rebuilt is not None:
                    library.save_overview(slug, rebuilt)
                    self._log('Koleksiyon özeti güncellendi.')
                    self._overview_ready(slug)
            except Exception as error:  # ozet sonra 'Hepsini hazirla' ile de uretilebilir
                self._log('Koleksiyon özeti yeniden üretilemedi: ' + str(error))

        threading.Thread(target=work, name='aktar-overview-rebuild', daemon=True).start()
        self._log('Koleksiyon özeti çıkarılan dosyalar olmadan yeniden üretiliyor…')

    # ------------------------------------------------------------------ yeniden isleme (F85)
    def library_reset(self, paths):
        """Secili dosyalarin transkript/OCR, ozet ve indeks kayitlarini siler (kaynaklar kalir).

        Koleksiyon ozeti bu dosyalari iceriyorsa o da silinir; 'Hepsini hazirla' yeniden uretir."""
        if self._queue_running():
            return {'error': 'Toplu hazırlık sürerken yeniden işlenemez; önce durdurun.'}
        paths = [Path(path) for path in paths or []]
        if not paths or self._lib_data is None:
            return self.library_state()
        keys = {library._key(path) for path in paths}
        removed = library.reset_files(paths)
        overview = library.load_overview(self._lib_slug)
        if overview and keys & {library._key(item) for item in overview.get('videos', [])}:
            library.overview_path(self._lib_slug).unlink(missing_ok=True)
        self._after_reset()
        self._log(f'{len(paths)} dosyanın Aktar kayıtları silindi ({removed} önbellek dosyası); '
                  'kaynak dosyalar duruyor. "Hepsini hazırla" ile yeniden işlenir.')
        self._rescan()
        return self.library_state()

    def library_reset_collection(self, slug=None):
        """Koleksiyon ozeti + koleksiyondaki tum dosyalarin onbellek kayitlari silinir."""
        if self._queue_running():
            return {'error': 'Toplu hazırlık sürerken sıfırlanamaz; önce durdurun.'}
        slug = slug or self._lib_slug
        if slug != self._lib_slug:
            state = self.library_open(slug)
            if 'error' in state:
                return state
        if self._lib_data is None:
            return self.library_state()
        try:
            entries, _changed = library.scan(copy.deepcopy(self._lib_data))
        except OSError as error:
            return {'error': 'Koleksiyon taranamadı: ' + str(error)}
        removed = library.reset_files([entry['path'] for entry in entries])
        library.overview_path(slug).unlink(missing_ok=True)
        self._after_reset()
        self._log(f'Koleksiyon sıfırlandı: {self._lib_data["title"]} ({len(entries)} dosya, {removed} '
                  'önbellek dosyası silindi; kaynak dosyalar duruyor).')
        self._rescan()
        return self.library_state()

    def _after_reset(self):
        slug = self._lib_slug
        self._overviews.pop(slug, None)
        chat = self._chats.get(slug)
        if chat is not None:
            chat['session'] = None  # eski indeks/ozetle kurulmus soru oturumu kullanilmasin
        self._push_chat()

    # ------------------------------------------------------------------ arama
    def library_search(self, query):
        """Dosya adinda ve transkriptlerde model kullanmadan arama (en az 3 harf)."""
        query = str(query or '').strip()
        words = library.fold(query).split()
        hits, matched = ([], set())
        if len(query) >= MIN_SEARCH_CHARS:
            hits, matched = library.transcript_hits(self._lib_entries, self._lib_infos, query, HIT_LIMIT)
        keys = []
        for entry in self._lib_entries:
            name = library.fold(entry['path'].name)
            if not words or all(word in name for word in words) or library._key(entry['path']) in matched:
                keys.append(library._key(entry['path']))
        manual = library.manual_dates(self._lib_data or {})
        dates = {library._key(entry['path']): collection_qa.format_date(
                     manual.get(library._key(entry['path'])) or info.get('date', '')
                or self._mail_fallback().get(library._key(entry['path']), ''))
                 for entry, info in zip(self._lib_entries, self._lib_infos)}
        return {'query': query, 'keys': keys, 'files': len(matched), 'limited': len(hits) >= HIT_LIMIT,
                'searched': len(query) >= MIN_SEARCH_CHARS,
                'hits': [{'path': str(hit['path']), 'name': hit['path'].stem, 'start': hit['start'],
                          'date': dates.get(library._key(hit['path']), ''),
                          'where': qa.format_position(hit['start'], library.kind_of(hit['path']) in library.TEXT_KINDS),
                          'text': hit['text']} for hit in hits]}

    # ------------------------------------------------------------------ disa aktarma
    def export_transcript(self, path):
        """Tek dosyanin transkripti: kayit penceresinde secilen uzantiya gore txt/srt/md."""
        video = Path(path)
        target = self._dialog('save_file', 'Transkripti dışa aktar', video.with_suffix('.txt').name,
                              ('Metin (*.txt)', 'Altyazı (*.srt)', 'Markdown (*.md)'))
        if not target:
            return None
        suffix = Path(target).suffix.lower().lstrip('.')
        fmt = suffix if suffix in transcript_export.FORMATS else 'txt'
        try:
            session = search_index.primary_session(video)
            if session is None:
                raise ValueError('Bu dosyanın transkripti yok.')
            target = Path(target).with_suffix('.' + fmt)
            transcript_export.write(target, transcript_export.render(session, fmt))
        except (OSError, ValueError) as error:
            return {'error': 'Dışa aktarılamadı: ' + str(error)}
        self._log(f'Transkript dışa aktarıldı: {target}')
        return {'path': str(target)}

    def export_formats(self):
        return [{'id': key, 'label': label} for key, label in transcript_export.FORMATS.items()]

    def export_transcripts(self, paths, fmt):
        """Birden cok dosya: klasor sorulur, her dosya <ad>.<uzanti> olarak yazilir."""
        if fmt not in transcript_export.FORMATS:
            return {'error': 'Bilinmeyen biçim: ' + str(fmt)}
        folder = self._dialog('open_folder', 'Transkriptlerin yazılacağı klasör')
        if not folder:
            return None
        try:
            written, missing = transcript_export.export_many([Path(path) for path in paths], folder, fmt)
        except (OSError, ValueError) as error:
            return {'error': 'Dışa aktarılamadı: ' + str(error)}
        message = f'{len(written)} transkript dışa aktarıldı: {folder}' + (
            f' (transkripti olmayan: {", ".join(missing)})' if missing else '')
        self._log(message)
        return {'message': message}

    def export_collection(self):
        if self._lib_data is None:
            return None
        target = self._dialog('save_file', 'Koleksiyonu dışa aktar', self._lib_data['title'] + '.md',
                              ('Markdown (*.md)',))
        if not target:
            return None
        videos = [entry['path'] for entry, info in zip(self._lib_entries, self._lib_infos)
                  if info['status'] in ('ready', 'transcript')]
        try:
            text = transcript_export.render_collection(self._lib_data['title'], videos, self._overview())
            target = transcript_export.write(Path(target).with_suffix('.md'), text)
        except (OSError, ValueError) as error:
            return {'error': 'Dışa aktarılamadı: ' + str(error)}
        self._log(f'Koleksiyon dışa aktarıldı ({len(videos)} dosya): {target}')
        return {'path': str(target)}

    # ------------------------------------------------------------------ toplu hazirlik
    def prepare_plan(self):
        """'Hepsini hazirla' penceresi acildi: dosyalari arka planda yoklar ('prepare' olayi)."""
        if self._queue_running():
            return {'error': 'Toplu hazırlık zaten sürüyor.'}
        entries = [entry for entry in self._lib_entries if not entry['missing']]
        if not entries:
            return {'error': 'Koleksiyonda hazırlanacak dosya yok.'}
        if self._lib_plan_cancel is not None:
            self._lib_plan_cancel.set()
        cancel = self._lib_plan_cancel = threading.Event()
        self._lib_plan = None
        cfg = load_config()
        whisper_ready, whisper_hint = speech.available()
        warnings = []
        if not str(cfg.get('embedding_model', '')).strip():
            warnings.append('Embedding modeli seçilmedi: yalnızca transkript çıkarılır (Ayarlar → Kütüphane indeksi).')
        if not whisper_ready:
            warnings.append(whisper_hint)

        def progress(done, total):
            if not cancel.is_set():
                self._emit('prepare', {'done': done, 'total': total})

        def work():
            try:
                result = library.plan(entries, progress=progress, cancelled=cancel.is_set)
            except Exception as error:  # yoklama hatasi pencereyi kilitlemesin
                result = {key: [] for key in PLAN_GROUPS}
                result.update(whisper_seconds=0.0, vision_pages=0, failed=[(None, str(error))])
            if cancel.is_set():
                return
            self._lib_plan = result
            failed = [entry['path'].name if entry is not None else error for entry, error in result['failed']]
            self._emit('prepare', {'counts': {key: len(result[key]) for key in PLAN_GROUPS},
                                   'whisper_seconds': format_duration(result['whisper_seconds'])
                                   if result['whisper_seconds'] else '',
                                   'vision_pages': result['vision_pages'], 'failed': failed,
                                   'frames_seconds': format_duration(result['frames_seconds'])
                                   if result['frames_seconds'] else '',
                                   # transkripti hazir olup yalniz goruntusu okunacaklar (sayaca eklenir)
                                   'frames_extra': len({library._key(entry['path']) for entry in result['frames']}
                                                       & {library._key(entry['path']) for entry in result['ready']})})

        threading.Thread(target=work, name='aktar-library-plan', daemon=True).start()
        return {'files': len(entries), 'model': cfg['model'], 'whisper': whisper_ready,
                'frames': bool((self._lib_data or {}).get('frames')),
                'whisper_model': cfg['whisper_model'], 'whisper_device': cfg['whisper_device'],
                'vision_model': str(cfg.get('vision_model', '')).strip() or cfg['model'],
                'ocr_engine': documents.ocr_engine(cfg), 'warnings': warnings}

    def prepare_cancel(self):
        if self._lib_plan_cancel is not None:
            self._lib_plan_cancel.set()
        self._lib_plan = None
        return True

    def prepare_start(self, summaries=True, vision=True, whisper=False, ocr_engine='', frames=False):
        """`ocr_engine` ('tesseract' | 'model' | 'vision'; bos: Ayarlardaki) yalnizca bu
        hazirlik icin taranmis sayfalarin motorunu degistirir. `frames` (F114): videolarin
        goruntusu de okunur; secim koleksiyona yazilir (klasor izleme de ona uyar)."""
        plan = self._lib_plan
        if plan is None:
            return {'error': 'Hazırlık planı hazır değil.'}
        if self._queue_running():
            return {'error': 'Toplu hazırlık zaten sürüyor.'}
        whisper = bool(whisper) and speech.available()[0]
        ocr_engine = ocr_engine if ocr_engine in OCR_OVERRIDES else ''
        # Sira: once hizli isler (ozet, indeks, belge, altyazi), sonra gorsel okuma ve Whisper.
        entries = ((list(plan['summary']) if summaries else []) + list(plan['index'])
                   + list(plan['document']) + list(plan['subtitle'])
                   + (list(plan['vision']) if vision else []) + (list(plan['whisper']) if whisper else []))
        if frames:  # transkripti hazir olup yalniz goruntusu okunacak videolar da siraya girer
            queued = {library._key(entry['path']) for entry in entries}
            entries += [entry for entry in plan['frames'] if library._key(entry['path']) not in queued]
        if self._lib_data is not None and bool(self._lib_data.get('frames')) != bool(frames):
            self._lib_data['frames'] = bool(frames)
            library.save_collection(self._lib_data, self._lib_slug)
        self._lib_plan = None
        if not entries and not summaries:
            return self.library_state()
        videos = [entry['path'] for entry in self._lib_entries if not entry['missing']]
        collection = (self._lib_slug, self._lib_data['title'], videos) if self._lib_data else None
        self._start_queue(entries, whisper, summaries, collection, vision, ocr_engine, frames)
        return self.library_state()

    def _start_queue(self, entries, whisper, summaries, collection, vision=True, ocr_engine='', frames=False):
        """Kuyrugu baslatir; acik olmayan koleksiyonun dosyalari da olabilir (F114 klasor izleme)."""
        self._queue_cancel = threading.Event()
        self._queue_resume = threading.Event()
        self._queue_resume.set()
        self._queue = {'total': len(entries), 'done': 0, 'index': 0, 'name': '', 'step': '',
                       'label': 'Başlıyor…', 'paused': False, 'percent': None, 'failed': []}
        self._row_status = {library._key(entry['path']): ('Sırada', 'dim') for entry in entries}
        self._log(f'Toplu hazırlık başladı: {len(entries)} dosya' + (' (Whisper açık).' if whisper else '.'))
        self._queue_worker = threading.Thread(
            target=self._run_queue, args=(entries, whisper, bool(summaries), collection, bool(vision), ocr_engine,
                                          bool(frames)),
            name='aktar-library-queue', daemon=True)
        self._queue_worker.start()

    def _queue_running(self):
        return self._queue_worker is not None and self._queue_worker.is_alive()

    def _push_queue(self):
        self._emit('queue', {'queue': self._queue})

    def _set_row(self, path, text, tone):
        key = library._key(path)
        self._row_status[key] = (text, tone)
        self._emit('row_status', {'key': key, 'text': text, 'tone': tone})

    def queue_pause(self):
        if not self._queue_running() or self._queue is None:
            return None
        paused = self._queue_resume.is_set()
        if paused:
            self._queue_resume.clear()
            self._queue['label'] = f'Duraklatıldı · {self._queue["name"] or "geçerli dosya"} bitince bekler'
        else:
            self._queue_resume.set()
            self._queue['label'] = 'Devam ediliyor…'
        self._queue['paused'] = paused
        self._push_queue()
        return self._queue

    def queue_stop(self):
        if not self._queue_running() or self._queue is None:
            return None
        self._queue_cancel.set()
        self._queue_resume.set()
        self._queue['label'] = 'Durduruluyor…'
        self._push_queue()
        return self._queue

    def _run_queue(self, entries, allow_whisper, summaries, collection, allow_vision, ocr_engine='', frames=False):
        """Eski QueueWorker.run: siradaki dosyalari library.transcribe/index ile isler."""
        done = failed = 0
        last_error, repeats = '', 0
        queue = self._queue
        cancel = self._queue_cancel
        cfg = load_config()
        if ocr_engine:
            cfg['ocr_engine'] = ocr_engine
            self._log('Bu hazırlıkta taranmış sayfalar için OCR motoru: ' + ocr_engine)
        client = Client(cfg, log=self._log)  # indeksleme icin tek istemci
        frame_reader = []  # F114: ilk videoda kurulur

        def started(index, path, step):
            queue.update(index=index, name=Path(path).name, step=step, percent=None,
                         label=f'Hazırlanıyor {index + 1}/{queue["total"]} · {Path(path).name} — {step}')
            self._set_row(path, 'İşleniyor…', 'accent')
            self._push_queue()

        for index, entry in enumerate(entries):
            while not self._queue_resume.wait(0.2):
                if cancel.is_set():
                    break
            if cancel.is_set():
                break
            path = entry['path']
            log = (lambda message, name=path.name: self._log(f'[{name}] {message}'))
            probed = library.cached_probe(path)
            whisper = probed is not None and not qa.pick_subtitle_stream(probed['subtitles'])
            has_text = bool(qa.cached_sessions(path))
            document = entry['kind'] in library.TEXT_KINDS
            try:
                vision = document and allow_vision and documents.needs_vision(path)
            except (RuntimeError, ValueError, OSError):
                vision = False
            reader = documents.reader_name(cfg, entry['kind'] == 'image')
            started(index, path, f'{reader} ile okunuyor' if vision else 'indeksleniyor' if has_text
                    else 'belgeden metin' if document else 'Whisper ile transkript' if whisper
                    else 'altyazıdan metin')

            def whisper_progress(seconds, total, path=path, index=index):
                if total > 0:
                    percent = int(100 * seconds / total)
                    queue['percent'] = percent
                    self._set_row(path, f'Whisper %{percent}', 'accent')
                    self._push_queue()

            def counted(prefix, path=path):
                return lambda current, total: total > 0 and self._set_row(path, f'{prefix} {current}/{total}', 'accent')

            try:
                outcome = library.transcribe(entry, cfg, allow_whisper, log=log, progress=whisper_progress,
                                             cancelled=cancel.is_set, allow_vision=allow_vision,
                                             vision_progress=counted('Görü' if reader == 'görü modeli' else 'OCR'))
                if (frames and outcome != 'skipped' and entry['kind'] == 'video'
                        and not qa.load_visual(path)[1]):
                    started(index, path, 'görüntüler okunuyor')
                    if not frame_reader:
                        frame_reader.append(library.vision_reader(cfg, self._log))
                    count = video_frames.read_video(path, cfg, frame_reader[0], log=log, progress=counted('Kare'),
                                                    cancelled=cancel.is_set)
                    log(f'{count} kare betimlendi')
                    has_text = False  # indeks kare betimleriyle yeniden kurulur
                if outcome != 'skipped' and str(cfg.get('embedding_model', '')).strip():
                    if not has_text:
                        started(index, path, 'indeksleniyor')
                    library.index(entry, cfg, log=log, cancelled=cancel.is_set, client=client)
                if outcome != 'skipped' and summaries:
                    started(index, path, 'özetleniyor')
                    collection_qa.summarize_video(path, log=log, progress=counted('Özet'), cancelled=cancel.is_set)
            except GracefulStop:
                break
            except Exception as error:  # tek dosyanin hatasi kuyrugu durdurmasin
                failed += 1
                queue['done'] += 1
                queue['failed'].append(path.name)
                self._log(f'HATA [{path.name}]: {error}')
                self._set_row(path, 'Hata', 'danger')
                self._push_queue()
                # Ayni hata ust uste tekrarlaniyorsa (LM Studio kapali vb.) bosuna surdurme.
                repeats = repeats + 1 if str(error) == last_error else 1
                last_error = str(error)
                if repeats >= REPEATED_ERROR_LIMIT:
                    self._log(f'Aynı hata {repeats} kez üst üste: kuyruk durduruldu. {error}')
                    break
                continue
            repeats = 0
            done += 1
            queue['done'] += 1
            self._row_status.pop(library._key(path), None)
            self._refresh_entry(path)
            self._push_queue()
        if summaries and collection and not cancel.is_set():
            slug, title, videos = collection
            queue.update(label='Koleksiyon özeti çıkarılıyor…', name='')
            self._push_queue()
            try:
                overview = collection_qa.build_overview(title, videos, cfg, log=self._log,
                                                        dates=(self._lib_data or {}).get('dates'))
                if overview is not None:
                    library.save_overview(slug, overview)
                    self._log(f'Koleksiyon özeti hazır: {len(overview["videos"])} dosya.')
                    self._overview_ready(slug)
            except Exception as error:  # ozet cikmazsa hazirlanan transkriptler yine kullanilir
                self._log('Koleksiyon özeti çıkarılamadı: ' + str(error))
        stopped = cancel.is_set()
        message = (f'Toplu hazırlık {"durduruldu" if stopped else "bitti"}: {done} dosya hazır'
                   + (f', {failed} hata ({", ".join(queue["failed"][:5])}).' if failed else '.'))
        self._log(message)
        self._queue = None
        self._queue_worker = None
        self._row_status = {}
        self._emit('queue', {'queue': None, 'message': message, 'failed': failed})
        self._rescan()
        if collection and hasattr(self, '_subs_auto_scan'):
            self._subs_auto_scan(collection[0])  # F114: hazirlanan ekstreler (OCR'li) okunur

    def _refresh_entry(self, path):
        key = library._key(path)
        for row, entry in enumerate(self._lib_entries):
            if library._key(entry['path']) == key:
                self._lib_infos[row] = library.describe(entry)
                self._emit('row', {'row': row_of(entry, self._lib_infos[row],
                                                 library.manual_dates(self._lib_data or {}),
                                                 self._mail_fallback()),
                                   'meta': self._meta()})
                self._push_chat()
                return

    def _stop_library_for_close(self):
        if self._queue_running():
            self._queue_cancel.set()
            self._queue_resume.set()
            self._queue_worker.join(5)
        if self._lib_plan_cancel is not None:
            self._lib_plan_cancel.set()

    # ------------------------------------------------------------------ koleksiyona sor
    def _chat(self, slug=None):
        slug = slug or self._lib_slug
        if slug not in self._chats:
            saved = library.load_chat(slug)
            self._chats[slug] = {'session': None, 'history': saved['history'],
                                 'entries': [('note', CHAT_GREETING)] + saved['entries']}
        return self._chats[slug]

    def _overview(self, slug=None):
        slug = slug or self._lib_slug
        if slug not in self._overviews:
            self._overviews[slug] = library.load_overview(slug)
        return self._overviews[slug]

    def _overview_ready(self, slug):
        self._overviews.pop(slug, None)
        chat = self._chats.get(slug)
        if chat is not None:
            chat['session'] = None  # yeni ozetle yeniden kurulsun
        if slug == self._lib_slug:
            self._push_chat()

    def _scope_videos(self, selected=None):
        """Soru kapsami: hazir (indeksli) dosyalar; secim verildiyse yalnizca secililer."""
        wanted = {library._key(path) for path in selected} if selected else None
        return [entry['path'] for entry, info in zip(self._lib_entries, self._lib_infos)
                if info['status'] == 'ready' and (wanted is None or library._key(entry['path']) in wanted)]

    def chat_state(self, selected=None):
        if self._lib_data is None:
            return None
        slug = self._lib_slug
        overview = self._overview(slug)
        entries = self._chat(slug)['entries']
        if overview:
            entries = [item for item in entries if item != ('note', CHAT_GREETING)]
        model = str(library._embedding_cfg(None).get('embedding_model', '')).strip()
        ready = sum(1 for info in self._lib_infos if info['status'] == 'ready')
        videos = self._scope_videos(selected)
        if not model:
            note = 'Embedding modeli seçilmedi: Ayarlar → Kütüphane indeksi.'
        elif not ready:
            note = 'Henüz indeksli dosya yok: önce "Hepsini hazırla".'
        elif not videos:
            note = 'Seçili dosyalar arasında hazır dosya yok.'
        else:
            waiting = len(self._lib_entries) - ready
            note = f'{len(videos)} hazır dosya' + (
                f' · {waiting} dosya henüz hazır değil' if waiting and not selected else '')
        return {'slug': slug, 'entries': chat_entries(entries), 'busy': self._ask_busy,
                'overview': {'summary': overview.get('summary', ''), 'topics': overview.get('topics') or [],
                             'questions': overview.get('questions') or [],
                             'videos': len(overview.get('videos') or [])} if overview else None,
                'note': 'Cevap hazırlanıyor…' if self._ask_busy else note,
                'template': str(self._lib_data.get('template') or ''),
                'template_note': str(self._lib_data.get('template_note') or ''),
                'enabled': bool(videos) and bool(model) and not self._ask_busy}

    # ------------------------------------------------------------------ sohbet sablonlari (F104)
    def templates_list(self):
        return chat_templates.load()

    def templates_save(self, items):
        try:
            return chat_templates.save(items)
        except OSError as error:
            return {'error': 'Şablonlar kaydedilemedi: ' + str(error)}

    def chat_set_template(self, template=None, note=None):
        """Koleksiyonun sohbet sablonu ve notu; None verilen alan degismez."""
        if self._lib_data is None:
            return None
        if template is not None:
            self._lib_data['template'] = str(template or '')
        if note is not None:
            self._lib_data['template_note'] = str(note or '').strip()[:chat_templates.NOTE_LIMIT]
        try:
            library.save_collection(self._lib_data, self._lib_slug)
        except RuntimeError as error:
            return {'error': str(error)}
        return self.chat_state()

    def _push_chat(self):
        self._emit('chat', {'slug': self._lib_slug})

    def chat_clear(self):
        if self._ask_busy or self._lib_data is None:
            return self.chat_state()
        library.clear_chat(self._lib_slug)
        self._chats.pop(self._lib_slug, None)
        self._log('Koleksiyon sohbeti temizlendi: ' + self._lib_data['title'])
        return self.chat_state()

    def chat_ask(self, question, selected=None, think=None):
        question = ' '.join(str(question or '').split())
        videos = self._scope_videos(selected)
        if not question or not videos or self._ask_busy or self._lib_data is None:
            return self.chat_state(selected)
        slug = self._lib_slug
        chat = self._chat(slug)
        session = chat['session']
        if session is None or [str(path) for path in session.videos] != [str(path) for path in videos]:
            # Kapsam degisti: etiketler yeni listeye gore; konusma gecmisi korunur.
            fresh = collection_qa.CollectionQA(videos, self._lib_data['title'], log=self._log,
                                               overview=self._overview(slug),
                                               dates=self._lib_data.get('dates'),
                                               fallback_dates=getattr(self, '_mail_dates', {}))
            fresh.history = session.history if session is not None else list(chat['history'])
            session = chat['session'] = fresh
        chat['entries'] += [('user', question), ('pending', 'Dosyalarda aranıyor…')]
        self._ask_busy = True
        instructions, name = chat_templates.instruction(self._lib_data.get('template'),
                                                        self._lib_data.get('template_note'))

        def work():
            turn, error = None, ''
            try:
                turn = session.ask(question, think=think, on_reasoning=reasoning_feed(
                    lambda: chat['entries'], lambda: self._emit('chat', {'slug': slug})),
                    instructions=instructions, template=name)
            except Exception as failure:  # baglanti/model hatasi sohbete yazilir
                error = str(failure)
            chat['entries'] = [item for item in chat['entries'] if item[0] != 'pending']
            chat['entries'].append(('assistant', turn) if turn is not None
                                   else ('error', 'Cevap alınamadı: ' + error))
            if chat['session'] is not None:
                chat['history'] = chat['session'].history
            library.save_chat(slug, chat['entries'], chat['history'])
            if error:
                self._log('Koleksiyon sorusu: ' + error)
            self._ask_busy = False
            self._emit('chat', {'slug': slug})

        threading.Thread(target=work, name='aktar-collection-ask', daemon=True).start()
        return self.chat_state(selected)
