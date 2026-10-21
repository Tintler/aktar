"""Drama 3'un kabul ettigi duygu/ses etiketleri (F171): Ayarlar'da secilebilir katalog.

Fish Audio Drama 3'te sabit bir etiket listesi yok: koseli parantez icindeki yonergeler serbest metindir (Fish
belgesi 'calm and inviting' gibi duz anlatim onerir). Katalog belgelerde ve kaynaklarda gecen etiketlerden olusur:
  - nokta etiketleri [..]: docs.fish.audio Drama 3 (gulme, ic cekme, nefes, kisa duraklama ornekleri), vLLM tarifi
    ([sighs], [laughs], [whisper], [angry], [excited], [pause]), fish.audio ana sayfa ornekleri ([sad],
    [embarrassed], [whispering], [soft], [breathy], [excited], [clear throat], [long pause]); [fısıldar] ve
    [shouting] Turkce dinleme setinden. Turkceye budanmis surumde yalnizca parcanin EN BASINDA calisiyorlar.
  - cift etiketler <..>..</..>: docs.fish.audio'nun destekledigi yedi kelime etiketi; konusmayi sarar.
'status': kullanicinin dinleme seti (F168): 'works' calisti, 'fails' calismadi, 'untested' denenmedi.
'cue': anlatici ipucu (Turkce kucuk harf, regex; emotion_tags kelime listesi), None ise yalnizca modelle.
Sira kelime listesinde onceliktir (ayni cumlede fisilti ve bagirma ofkeden baskin).
"""
from __future__ import annotations

_WHISPER = r'fısılda(?:dı|yarak|yordu|mış|şarak|ştı)|fısıltıyla|fısıltı (?:halinde|ile)|alçak sesle'
_SOFT = r'yumuşak bir sesle|şefkatle|usulca|tatlı bir sesle|yumuşacık'

CATALOG = (
    {'tag': '[fısıldar]', 'kind': 'point', 'label': 'Fısıltı (Türkçe yazım)', 'status': 'works', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[whisper]', 'kind': 'point', 'label': 'Fısıltı (İngilizce yazım)', 'status': 'untested', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[whispering]', 'kind': 'point', 'label': 'Fısıldayarak', 'status': 'untested', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '<whisper>', 'kind': 'paired', 'label': 'Fısıltı (konuşmayı sarar)', 'status': 'fails', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[shouting]', 'kind': 'point', 'label': 'Bağırma', 'status': 'works',
     'cue': r'bağır(?:dı|arak|ıyordu|ıp|mış|ınca)|haykır(?:dı|arak|ıyordu|ıp|mış)|çığlık (?:attı|atarak)'
            r'|avaz avaz|gürledi|gürleyerek',
     'examples': 'bağırdı, haykırarak, avaz avaz', 'llm': 'bağırarak'},
    {'tag': '<forceful>', 'kind': 'paired', 'label': 'Sert, buyurgan', 'status': 'untested',
     'cue': r'sertçe|sert bir sesle|emreder gibi|buyurgan bir|kesin bir sesle',
     'examples': 'sertçe, emreder gibi, kesin bir sesle', 'llm': 'sert ve buyurgan'},
    {'tag': '[angry]', 'kind': 'point', 'label': 'Öfke', 'status': 'works',
     'cue': r'öfkeyle|öfkeli bir|öfkelen(?:di|erek|miş)|sinirle|sinirli bir|sinirlen(?:di|erek|miş)'
            r'|kızgın(?:lıkla)?|kızarak|kızdı(?!\w)|hiddetle|hiddetlen(?:di|erek)|köpürdü|tersledi|çıkıştı',
     'examples': 'öfkeyle, sinirle, kızarak, tersledi', 'llm': 'öfkeyle'},
    {'tag': '[crying]', 'kind': 'point', 'label': 'Ağlama', 'status': 'fails',
     'cue': r'ağla(?:dı|yarak|yordu|mış|maklı)|hıçkır(?:dı|arak|ıklar|ıklarla)|gözyaşları içinde',
     'examples': 'ağlayarak, hıçkırarak, gözyaşları içinde', 'llm': 'ağlayarak'},
    {'tag': '[sad]', 'kind': 'point', 'label': 'Hüzün', 'status': 'untested',
     'cue': r'üzgün(?:ce| bir)|hüzünle|kederle|mahzun|buruk bir sesle|üzüntüyle',
     'examples': 'üzgünce, hüzünle, kederle', 'llm': 'üzgün, hüzünlü'},
    {'tag': '[shaky breath]', 'kind': 'point', 'label': 'Titrek nefes', 'status': 'untested',
     'cue': r'titrek bir sesle|sesi titre(?:yerek|di|yordu)|titreyen bir sesle',
     'examples': 'titrek bir sesle, sesi titreyerek', 'llm': 'titrek sesle'},
    {'tag': '[excited]', 'kind': 'point', 'label': 'Heyecan', 'status': 'untested',
     'cue': r'heyecanla|coşkuyla|sevinçle|heyecanlan(?:dı|arak|mış)',
     'examples': 'heyecanla, coşkuyla, sevinçle', 'llm': 'heyecanla, coşkuyla'},
    {'tag': '[embarrassed]', 'kind': 'point', 'label': 'Utanma', 'status': 'untested',
     'cue': r'utanarak|mahcup(?:ça| bir)|utangaç bir|kızararak|utandı',
     'examples': 'utanarak, mahcupça, kızararak', 'llm': 'utanarak, mahcup'},
    {'tag': '[laughs]', 'kind': 'point', 'label': 'Gülme', 'status': 'works',
     'cue': r'gül(?:erek|dü|üyordu|üştü|üşerek|üşüyorlardı|mekten|meye başladı)|kahkaha|kıkırda(?:dı|yarak)'
            r'|katıla katıla',
     'examples': 'gülerek, güldü, kahkaha', 'llm': 'gülerek'},
    {'tag': '[small laugh]', 'kind': 'point', 'label': 'Hafif gülüş', 'status': 'untested',
     'cue': r'gülümse(?:di|yerek|yip|miş)|hafifçe gül(?:dü|erek)',
     'examples': 'gülümseyerek, hafifçe güldü', 'llm': 'gülümseyerek, hafif gülüşle'},
    {'tag': '[sighs]', 'kind': 'point', 'label': 'İç çekme', 'status': 'works',
     'cue': r'iç(?:ini)? çek(?:ti|erek|iyordu|ip|miş)|iç geçir(?:di|erek|iyordu)',
     'examples': 'içini çekerek, iç geçirdi', 'llm': 'iç çekerek'},
    {'tag': '[breathy]', 'kind': 'point', 'label': 'Nefes nefese', 'status': 'untested',
     'cue': r'nefes nefese|soluk soluğa|solu(?:yarak|du)(?!\w)',
     'examples': 'nefes nefese, soluk soluğa', 'llm': 'nefes nefese'},
    {'tag': '[clear throat]', 'kind': 'point', 'label': 'Boğaz temizleme', 'status': 'untested',
     'cue': r'boğazını temizle(?:di|yerek|yip)|öksür(?:dü|erek|üp)',
     'examples': 'boğazını temizleyerek, öksürdü', 'llm': 'boğazını temizleyerek'},
    {'tag': '[long pause]', 'kind': 'point', 'label': 'Uzun duraklama', 'status': 'untested',
     'cue': r'uzun bir sessizlik(?:ten sonra)?|uzun süre sustu',
     'examples': 'uzun bir sessizlikten sonra', 'llm': 'uzun bir sessizlikten sonra'},
    {'tag': '[pause]', 'kind': 'point', 'label': 'Kısa duraklama', 'status': 'untested',
     'cue': r'duraksa(?:dı|yarak|yıp)|tereddütle|tereddüt ederek|bir an durdu',
     'examples': 'duraksayarak, tereddütle', 'llm': 'duraksayarak, tereddütle'},
    {'tag': '[soft]', 'kind': 'point', 'label': 'Yumuşak ses', 'status': 'untested', 'cue': _SOFT,
     'examples': 'yumuşak bir sesle, şefkatle, usulca', 'llm': 'yumuşak, şefkatli'},
    {'tag': '<soft>', 'kind': 'paired', 'label': 'Yumuşak (konuşmayı sarar)', 'status': 'untested', 'cue': _SOFT,
     'examples': 'yumuşak bir sesle, şefkatle, usulca', 'llm': 'yumuşak, şefkatli'},
    {'tag': '<emphasis>', 'kind': 'paired', 'label': 'Vurgulu', 'status': 'untested',
     'cue': r'vurgulayarak|üstüne basa basa|üstüne basarak',
     'examples': 'vurgulayarak, üstüne basa basa', 'llm': 'vurgulayarak'},
    {'tag': '<stress>', 'kind': 'paired', 'label': 'Gergin, baskılı', 'status': 'untested', 'cue': None,
     'examples': 'yalnızca model kipinde', 'llm': 'gergin, baskı altında'},
    {'tag': '<fast>', 'kind': 'paired', 'label': 'Hızlı', 'status': 'untested',
     'cue': r'hızlı hızlı|bir çırpıda|çabucak|telaşla|aceleyle',
     'examples': 'hızlı hızlı, telaşla, bir çırpıda', 'llm': 'hızlı, telaşla'},
    {'tag': '<slow>', 'kind': 'paired', 'label': 'Yavaş', 'status': 'untested',
     'cue': r'yavaşça|ağır ağır|tane tane|yavaş yavaş',
     'examples': 'yavaşça, ağır ağır, tane tane', 'llm': 'yavaşça, tane tane'},
)

ALL_TAGS = tuple(entry['tag'] for entry in CATALOG)
POINT_TAGS = tuple(entry['tag'] for entry in CATALOG if entry['kind'] == 'point')
PAIRED_TAGS = tuple(entry['tag'] for entry in CATALOG if entry['kind'] == 'paired')
WHISPER_TAGS = ('[fısıldar]', '[whisper]', '[whispering]', '<whisper>')
DEFAULT_TAGS = tuple(entry['tag'] for entry in CATALOG if entry['status'] == 'works')


def allowed(chosen=None):
    """Ayarlarda secilen etiketler (katalog sirasiyla); secim yoksa (None) calistigi bilinenler."""
    if chosen is None:
        return DEFAULT_TAGS
    chosen = set(chosen or ())
    return tuple(tag for tag in ALL_TAGS if tag in chosen)


def public():
    """Ayarlar icin katalog (regex'siz)."""
    return [{key: entry[key] for key in ('tag', 'kind', 'label', 'status', 'examples')} | {'default': entry['tag'] in DEFAULT_TAGS}
            for entry in CATALOG]
