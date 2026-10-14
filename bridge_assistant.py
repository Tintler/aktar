"""Genel sohbet ve tekil dosya incelemenin arka ucu (Bridge'e karisan siniflar).

Sohbet (assistant.py): cevap akisli gelir; 'assistant_stream' olayi o ana kadarki metni,
'assistant' olayi bitince sohbetin kimligini tasir. Ayni anda tek cevap uretilir.
Tekil dosyalar: koleksiyona eklenmeden acilan dosyalarin listesi (library.load_recent);
acma isi oynatici / belge goruntuleyicinin kendisidir.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import assistant
import library
from bridge_library import KIND_LABELS, chat_entries

STREAM_INTERVAL = 0.08  # saniye: akis olaylarinin en sik gonderilme araligi


class AssistantMixin:
    def _init_assistant(self):
        self._conv = assistant.new_conversation()
        self._conv_busy = None            # cevap uretilen sohbetin kimligi
        self._conv_stream = ''
        self._conv_cancel = threading.Event()

    def _assistant_state(self, data=None):
        data = data or self._conv
        busy = self._conv_busy == data['id']
        return {'id': data['id'], 'title': data.get('title', ''), 'entries': chat_entries(data['entries']),
                'busy': busy, 'stream': self._conv_stream if busy else None,
                'locked': bool(self._conv_busy) and not busy, 'saved': bool(data['entries'])}

    def assistant_list(self):
        return {'items': assistant.list_conversations(), 'current': self._conv['id']}

    def assistant_state(self):
        return self._assistant_state()

    def assistant_new(self):
        if self._conv['entries'] or self._conv_busy == self._conv['id']:
            self._conv = assistant.new_conversation()
        return self._assistant_state()

    def assistant_open(self, conversation_id):
        if conversation_id == self._conv['id']:
            return self._assistant_state()
        try:
            self._conv = assistant.load_conversation(conversation_id)
        except ValueError as error:
            return {'error': str(error)}
        return self._assistant_state()

    def assistant_delete(self, conversation_id):
        if self._conv_busy == conversation_id:
            return {'error': 'Cevap üretilirken sohbet silinemez.'}
        assistant.delete_conversation(conversation_id)
        if self._conv['id'] == conversation_id:
            self._conv = assistant.new_conversation()
        return self._assistant_state()

    def assistant_rename(self, conversation_id, title):
        try:
            data = assistant.rename_conversation(conversation_id, title)
        except (ValueError, OSError) as error:
            return {'error': str(error)}
        if self._conv['id'] == conversation_id:
            self._conv['title'] = data['title']
        return self._assistant_state()

    def assistant_stop(self):
        self._conv_cancel.set()
        return True

    def assistant_ask(self, text):
        text = str(text or '').strip()
        data = self._conv
        if not text or self._conv_busy:
            return self._assistant_state()
        if not data['title']:
            data['title'] = assistant.make_title(text)
        data['entries'].append(('user', text))
        self._conv_busy = data['id']
        self._conv_stream = ''
        self._conv_cancel.clear()
        last = [0.0]

        def delta(value):
            self._conv_stream = value
            now = time.monotonic()
            if now - last[0] >= STREAM_INTERVAL:
                last[0] = now
                self._emit('assistant_stream', {'id': data['id'], 'text': value})

        def work():
            log = lambda message: self._log('[Sohbet] ' + str(message))  # noqa: E731
            try:
                turn = assistant.Assistant(data['history'], log=log).ask(
                    text, on_delta=delta, cancelled=self._conv_cancel.is_set)
            except Exception as failure:  # baglanti/model hatasi sohbete yazilir
                log('Cevap alınamadı: ' + str(failure))
                data['entries'].append(('error', 'Cevap alınamadı: ' + str(failure)))
            else:
                if turn['answer']:
                    data['entries'].append(('assistant', turn))
                    data['history'].append({'question': turn['question'], 'answer': turn['answer']})
                elif turn['stopped']:
                    data['entries'].append(('error', 'Durduruldu.'))
            try:
                assistant.save_conversation(data)
            except OSError as error:
                log('Sohbet kaydedilemedi: ' + str(error))
            self._conv_busy = None
            self._conv_stream = ''
            self._emit('assistant', {'id': data['id']})

        threading.Thread(target=work, name='aktar-assistant', daemon=True).start()
        return self._assistant_state()

    def _stop_assistant_for_close(self):
        self._conv_cancel.set()


class FilesMixin:
    def _files_state(self):
        items = []
        for item in library.load_recent():
            path = Path(item['path'])
            items.append({'path': str(path), 'name': path.name, 'folder': str(path.parent),
                          'kind': library.kind_of(path) or 'document', 'opened': item['opened'],
                          'missing': not path.is_file()})
        return {'items': items}

    def files_recent(self):
        return self._files_state()

    def files_touch(self, path):
        """Dosya Tekil dosya sayfasindan acildi: listenin basina alinir."""
        path = Path(str(path))
        if not path.is_file():
            return {'error': 'Dosya bulunamadı: ' + str(path)}
        if library.kind_of(path) is None:
            return {'error': 'Bu dosya türü desteklenmiyor: ' + path.name}
        try:
            library.touch_recent(path)
        except OSError as error:
            return {'error': str(error)}
        assistant.forget_snapshot()
        return self._files_state()

    def files_forget(self, path):
        try:
            library.forget_recent(path)
        except OSError as error:
            return {'error': str(error)}
        assistant.forget_snapshot()
        return self._files_state()

    def files_choose(self):
        patterns = ['Desteklenen dosyalar (' + ';'.join('*' + suffix for suffix in library.supported_suffixes()) + ')']
        patterns += [f'{KIND_LABELS.get(kind, kind)} (' + ';'.join('*' + suffix for suffix in suffixes) + ')'
                     for kind, suffixes in library.KINDS.items()]
        return self._dialog('open_file', 'Dosya seç', tuple(patterns))
