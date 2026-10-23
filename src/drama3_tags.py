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

import re

_WHISPER = r'fısılda(?:dı|yarak|yordu|mış|şarak|ştı)|fısıltıyla|fısıltı (?:halinde|ile)|alçak sesle'
_SOFT = r'yumuşak bir sesle|şefkatle|usulca|tatlı bir sesle|yumuşacık'
EMOTION, VOICE, SOUND, PAUSE, PAIRED = ('Duygu', 'Ses yüksekliği ve konuşma biçimi', 'Gülme, ağlama ve diğer sesler',
                                        'Duraklama ve vurgu', 'Çift etiketler (konuşmayı sarar)')


def _more(group, tag, label, cue=None, examples='yalnızca model kipinde', llm=None):
    """F179: kullanicinin Fish Audio etiket listesinden eklenen, henuz dinlenmemis nokta etiketi."""
    return {'tag': tag, 'kind': 'point', 'group': group, 'label': label, 'status': 'untested', 'cue': cue,
            'examples': examples, 'llm': llm or label.lower()}


CATALOG = (
    {'tag': '[fısıldar]', 'kind': 'point', 'group': VOICE, 'label': 'Fısıltı (Türkçe yazım)', 'status': 'works', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[whisper]', 'kind': 'point', 'group': VOICE, 'label': 'Fısıltı (İngilizce yazım)', 'status': 'untested', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[whispering]', 'kind': 'point', 'group': VOICE, 'label': 'Fısıldayarak', 'status': 'untested', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '<whisper>', 'kind': 'paired', 'group': PAIRED, 'label': 'Fısıltı (konuşmayı sarar)', 'status': 'fails', 'cue': _WHISPER,
     'examples': 'fısıldadı, fısıldayarak, alçak sesle', 'llm': 'fısıldayarak'},
    {'tag': '[shouting]', 'kind': 'point', 'group': VOICE, 'label': 'Bağırma', 'status': 'works',
     'cue': r'bağır(?:dı|arak|ıyordu|ıp|mış|ınca)|haykır(?:dı|arak|ıyordu|ıp|mış)|çığlık (?:attı|atarak)'
            r'|avaz avaz|gürledi|gürleyerek',
     'examples': 'bağırdı, haykırarak, avaz avaz', 'llm': 'bağırarak'},
    {'tag': '<forceful>', 'kind': 'paired', 'group': PAIRED, 'label': 'Sert, buyurgan', 'status': 'untested',
     'cue': r'sertçe|sert bir sesle|emreder gibi|buyurgan bir|kesin bir sesle',
     'examples': 'sertçe, emreder gibi, kesin bir sesle', 'llm': 'sert ve buyurgan'},
    {'tag': '[angry]', 'kind': 'point', 'group': EMOTION, 'label': 'Öfke', 'status': 'works',
     'cue': r'öfkeyle|öfkeli bir|öfkelen(?:di|erek|miş)|sinirle|sinirli bir|sinirlen(?:di|erek|miş)'
            r'|kızgın(?:lıkla)?|kızarak|kızdı(?!\w)|hiddetle|hiddetlen(?:di|erek)|köpürdü|tersledi|çıkıştı',
     'examples': 'öfkeyle, sinirle, kızarak, tersledi', 'llm': 'öfkeyle'},
    {'tag': '[crying]', 'kind': 'point', 'group': SOUND, 'label': 'Ağlama', 'status': 'fails',
     'cue': r'ağla(?:dı|yarak|yordu|mış|maklı)|hıçkır(?:dı|arak|ıklar|ıklarla)|gözyaşları içinde',
     'examples': 'ağlayarak, hıçkırarak, gözyaşları içinde', 'llm': 'ağlayarak'},
    {'tag': '[sad]', 'kind': 'point', 'group': EMOTION, 'label': 'Hüzün', 'status': 'untested',
     'cue': r'üzgün(?:ce| bir)|hüzünle|kederle|mahzun|buruk bir sesle|üzüntüyle',
     'examples': 'üzgünce, hüzünle, kederle', 'llm': 'üzgün, hüzünlü'},
    {'tag': '[shaky breath]', 'kind': 'point', 'group': SOUND, 'label': 'Titrek nefes', 'status': 'untested',
     'cue': r'titrek bir sesle|sesi titre(?:yerek|di|yordu)|titreyen bir sesle',
     'examples': 'titrek bir sesle, sesi titreyerek', 'llm': 'titrek sesle'},
    {'tag': '[excited]', 'kind': 'point', 'group': EMOTION, 'label': 'Heyecan', 'status': 'untested',
     'cue': r'heyecanla|coşkuyla|sevinçle|heyecanlan(?:dı|arak|mış)',
     'examples': 'heyecanla, coşkuyla, sevinçle', 'llm': 'heyecanla, coşkuyla'},
    {'tag': '[embarrassed]', 'kind': 'point', 'group': EMOTION, 'label': 'Utanma', 'status': 'untested',
     'cue': r'utanarak|mahcup(?:ça| bir)|utangaç bir|kızararak|utandı',
     'examples': 'utanarak, mahcupça, kızararak', 'llm': 'utanarak, mahcup'},
    {'tag': '[laughs]', 'kind': 'point', 'group': SOUND, 'label': 'Gülme', 'status': 'works',
     'cue': r'gül(?:erek|dü|üyordu|üştü|üşerek|üşüyorlardı|mekten|meye başladı)|kahkaha(?:yla|larla| atarak| attı| atıyordu| koparak| kopardı|ya boğul)|kıkırda(?:dı|yarak)'
            r'|katıla katıla',
     'examples': 'gülerek, güldü, kahkaha', 'llm': 'gülerek'},
    {'tag': '[small laugh]', 'kind': 'point', 'group': SOUND, 'label': 'Hafif gülüş', 'status': 'untested',
     'cue': r'gülümse(?:di|yerek|yip|miş)|hafifçe gül(?:dü|erek)',
     'examples': 'gülümseyerek, hafifçe güldü', 'llm': 'gülümseyerek, hafif gülüşle'},
    {'tag': '[sighs]', 'kind': 'point', 'group': SOUND, 'label': 'İç çekme', 'status': 'works',
     'cue': r'iç(?:ini)? çek(?:ti|erek|iyordu|ip|miş)|iç geçir(?:di|erek|iyordu)',
     'examples': 'içini çekerek, iç geçirdi', 'llm': 'iç çekerek'},
    {'tag': '[breathy]', 'kind': 'point', 'group': SOUND, 'label': 'Nefes nefese', 'status': 'untested',
     'cue': r'nefes nefese|soluk soluğa|solu(?:yarak|du)(?!\w)',
     'examples': 'nefes nefese, soluk soluğa', 'llm': 'nefes nefese'},
    {'tag': '[clear throat]', 'kind': 'point', 'group': SOUND, 'label': 'Boğaz temizleme', 'status': 'untested',
     'cue': r'boğazını temizle(?:di|yerek|yip)|öksür(?:dü|erek|üp)',
     'examples': 'boğazını temizleyerek, öksürdü', 'llm': 'boğazını temizleyerek'},
    {'tag': '[long pause]', 'kind': 'point', 'group': PAUSE, 'label': 'Uzun duraklama', 'status': 'untested',
     'cue': r'uzun bir sessizlik(?:ten sonra)?|uzun süre sustu',
     'examples': 'uzun bir sessizlikten sonra', 'llm': 'uzun bir sessizlikten sonra'},
    {'tag': '[pause]', 'kind': 'point', 'group': PAUSE, 'label': 'Kısa duraklama', 'status': 'untested',
     'cue': r'duraksa(?:dı|yarak|yıp)|tereddütle|tereddüt ederek|bir an durdu',
     'examples': 'duraksayarak, tereddütle', 'llm': 'duraksayarak, tereddütle'},
    {'tag': '[soft]', 'kind': 'point', 'group': VOICE, 'label': 'Yumuşak ses', 'status': 'untested', 'cue': _SOFT,
     'examples': 'yumuşak bir sesle, şefkatle, usulca', 'llm': 'yumuşak, şefkatli'},
    {'tag': '<soft>', 'kind': 'paired', 'group': PAIRED, 'label': 'Yumuşak (konuşmayı sarar)', 'status': 'untested', 'cue': _SOFT,
     'examples': 'yumuşak bir sesle, şefkatle, usulca', 'llm': 'yumuşak, şefkatli'},
    {'tag': '<emphasis>', 'kind': 'paired', 'group': PAIRED, 'label': 'Vurgulu', 'status': 'untested',
     'cue': r'vurgulayarak|üstüne basa basa|üstüne basarak',
     'examples': 'vurgulayarak, üstüne basa basa', 'llm': 'vurgulayarak'},
    {'tag': '<stress>', 'kind': 'paired', 'group': PAIRED, 'label': 'Gergin, baskılı', 'status': 'untested', 'cue': None,
     'examples': 'yalnızca model kipinde', 'llm': 'gergin, baskı altında'},
    {'tag': '<fast>', 'kind': 'paired', 'group': PAIRED, 'label': 'Hızlı', 'status': 'untested',
     'cue': r'hızlı hızlı|bir çırpıda|çabucak|telaşla|aceleyle',
     'examples': 'hızlı hızlı, telaşla, bir çırpıda', 'llm': 'hızlı, telaşla'},
    {'tag': '<slow>', 'kind': 'paired', 'group': PAIRED, 'label': 'Yavaş', 'status': 'untested',
     'cue': r'yavaşça|ağır ağır|tane tane|yavaş yavaş',
     'examples': 'yavaşça, ağır ağır, tane tane', 'llm': 'yavaşça, tane tane'},
    # F179: kullanicinin listesindeki diger etiketler (denenmedi). Sonda: kelime listesinde eskilerin onceligi korunur;
    # ipucu yalnizca baska bir etiketin ipucuyla cakismayan anlatimlar icin var.
    _more(EMOTION, '[surprised]', 'Şaşırmış', r'şaşkınlıkla|şaşırarak|hayretle', 'şaşkınlıkla, hayretle'),
    _more(EMOTION, '[shocked]', 'Şok olmuş', r'dehşetle|şok içinde|şoke ol(?:du|muş|arak)', 'dehşetle, şok içinde'),
    _more(EMOTION, '[scared]', 'Korkmuş', r'korkuyla|korkarak|ürkerek|ürkekçe|korku içinde', 'korkuyla, ürkerek'),
    _more(EMOTION, '[happy]', 'Mutlu', r'mutlulukla|neşeyle|neşeli bir sesle', 'mutlulukla, neşeyle'),
    _more(EMOTION, '[curious]', 'Meraklı', r'merakla|meraklı bir sesle', 'merakla'),
    _more(EMOTION, '[nervous]', 'Gergin', r'gerginlikle|gergin bir sesle|endişeyle|kaygıyla', 'endişeyle, gerginlikle'),
    _more(EMOTION, '[confident]', 'Kendinden emin', r'kendinden emin(?: bir sesle)?', 'kendinden emin'),
    _more(EMOTION, '[sarcastic]', 'Alaycı', r'alayla|alaycı bir|iğneleyerek|dalga geçerek', 'alayla, iğneleyerek'),
    _more(EMOTION, '[disappointed]', 'Hayal kırıklığına uğramış', r'hayal kırıklığıyla', 'hayal kırıklığıyla'),
    _more(EMOTION, '[frustrated]', 'Bıkmış, sinirlenmiş', r'bıkkınlıkla|bezgin bir sesle|usanmış bir sesle', 'bıkkınlıkla'),
    _more(EMOTION, '[soothing]', 'Yatıştırıcı', r'yatıştırıcı bir sesle|teskin ederek|yatıştırmaya çalışarak',
          'yatıştırıcı bir sesle, teskin ederek'),
    _more(EMOTION, '[empathetic]', 'Empatik', r'anlayışla', 'anlayışla'),
    _more(VOICE, '[screaming]', 'Çığlık atarak', r'çığlık çığlığa|çığlıklar atarak', 'çığlık çığlığa'),
    _more(VOICE, '[loud]', 'Yüksek sesle', r'yüksek sesle', 'yüksek sesle'),
    _more(VOICE, '[loud voice]', 'Yüksek sesli konuşma'),
    _more(VOICE, '[soft voice]', 'Yumuşak, sakin ses'),
    _more(VOICE, '[low voice]', 'Daha pes ses', r'kalın bir sesle|pes bir sesle', 'kalın bir sesle'),
    _more(VOICE, '[low volume]', 'Düşük ses seviyesi', r'kısık (?:bir )?sesle', 'kısık sesle'),
    _more(VOICE, '[volume up]', 'Sesi yükselt'),
    _more(VOICE, '[volume down]', 'Sesi azalt'),
    _more(VOICE, '[speaking slowly]', 'Yavaş konuşma'),
    _more(VOICE, '[speaking quickly]', 'Hızlı konuşma'),
    _more(VOICE, '[hesitant]', 'Tereddütlü', r'kekele(?:di|yerek)|çekinerek|çekingen bir sesle', 'kekeleyerek, çekinerek'),
    _more(VOICE, '[robotic voice]', 'Robotik konuşma', r'robot gibi|mekanik bir sesle', 'robot gibi'),
    _more(VOICE, '[professional broadcast tone]', 'Profesyonel spiker tonu'),
    _more(VOICE, '[singing]', 'Şarkı söyler gibi', r'şarkı söyler gibi|şarkı söyle(?:di|yerek)', 'şarkı söyleyerek'),
    _more(SOUND, '[laughing]', 'Gülme'),
    _more(SOUND, '[chuckling]', 'Hafifçe kıkırdama'),
    _more(SOUND, '[giggle]', 'Kıkırdama'),
    _more(SOUND, '[laughing tone]', 'Gülümseyerek konuşma'),
    _more(SOUND, '[sobbing]', 'Hıçkırarak ağlama'),
    _more(SOUND, '[sigh]', 'İç çekme (tekil yazım)'),
    _more(SOUND, '[inhale]', 'Nefes alma', r'derin (?:bir )?nefes al(?:dı|arak|ıp)', 'derin bir nefes alarak'),
    _more(SOUND, '[exhale]', 'Nefes verme', r'nefesini (?:bıraktı|vererek|verdi)|soluğunu bıraktı', 'nefesini bırakarak'),
    _more(SOUND, '[gasp]', 'Şaşkınlıkla nefes çekme', r'(?:nefesi|soluğu) kesil(?:di|erek)', 'nefesi kesilerek'),
    _more(SOUND, '[panting]', 'Soluk soluğa kalma'),
    _more(SOUND, '[groan]', 'İnleme', r'inle(?:di|yerek)|homurdan(?:dı|arak)', 'inleyerek, homurdanarak'),
    _more(SOUND, '[moaning]', 'İnleyerek ses çıkarma'),
    _more(SOUND, '[clearing throat]', 'Boğaz temizleme (uzun yazım)'),
    _more(SOUND, '[tsk]', 'Dil şaklatma', r'dilini şaklat(?:tı|arak)|cık cık', 'dilini şaklatarak'),
    _more(SOUND, '[chuckle]', 'Kısa gülüş'),
    _more(SOUND, '[interrupting]', 'Söz kesme', r'(?:sözünü|lafını) kes(?:ti|erek)|araya gir(?:di|erek)', 'sözünü keserek'),
    _more(SOUND, '[echo]', 'Yankı efekti', r'yankılan(?:dı|arak|an bir sesle)', 'yankılanan bir sesle'),
    _more(SOUND, '[rustling sound]', 'Hışırtı'),
    _more(PAUSE, '[short pause]', 'Çok kısa duraklama'),
    _more(PAUSE, '[emphasis]', 'Sonraki kelimeyi vurgulama'),
    _more(PAUSE, '[pitch up]', 'Sesi daha tiz yapma', r'ince bir sesle|tiz bir sesle', 'ince bir sesle'),
    _more(PAUSE, '[pitch down]', 'Sesi daha pes yapma'),
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
    """Ayarlar icin katalog (regex'siz); F179 gruplarina gore dizili (grup icinde katalog sirasi)."""
    groups = (EMOTION, VOICE, SOUND, PAUSE, PAIRED)
    return [{key: entry[key] for key in ('tag', 'kind', 'group', 'label', 'status', 'examples')} | {'default': entry['tag'] in DEFAULT_TAGS}
            for entry in sorted(CATALOG, key=lambda entry: groups.index(entry['group']))]


# ---------------------------------------------------------------- F187: serbest yonerge (Drama 3 TR, budanmamis)
# Drama 3 resmi belgesi ve teknik raporu (Ek C): yonergeler serbest metin, Turkce de olabilir. Nokta etiketi olayin
# oldugu yere (cumle ortasi da), on ek ([titrek bir sesle]) sozlerin onune, cift etiket yalnizca sardigi kelimelere
# etki eder; resmi cift etiketler yedi tane (katalogdaki PAIRED_TAGS). Kullanicinin Drama 3 TR dinlemesi: Turkce ve
# Ingilizce on ek, cumle ortasindaki [derin bir nefes alir]/[gasps], tek kelimeyi saran <emphasis> calisti; ayni
# istekteki on ek sonraki cumlelere tasiyor (RESET ile kesiliyor).
STYLES = ('free', 'catalog')   # ui.json tts.emotion_style: serbest yonerge ya da yalnizca katalog
MAX_DIRECTIONS = 3             # bir cumlede en fazla yonerge (on ek + nokta + cift etiket)
MAX_WORDS = 8                  # bir yonergenin en fazla kelimesi
RESET_NARRATION = '[sakin anlatıcı sesi]'   # ayni istekte on ekli cumleden sonraki etiketsiz cumleye
RESET_SPEECH = '[doğal ses]'
_DIRECTION = re.compile(r'\[([^\[\]<>\n]*)\]')
_SCOPED = re.compile(r'<(/?)([A-Za-z]+)>')
_CUE_PATTERNS = tuple((entry['tag'], re.compile(r'(?<!\w)(?:' + entry['cue'] + r')', re.U))
                      for entry in CATALOG if entry['cue'])


def style(value):
    return value if value in STYLES else 'free'


def plain(markup):
    """Yonergeler cikarilmis metin (okunacak sozler)."""
    return ' '.join(_SCOPED.sub('', _DIRECTION.sub(' ', str(markup or ''))).split())


def _letters(text):
    return re.sub(r'\s+', '', str(text or ''))


def same_text(markup, text):
    """Yonergeler cikarilinca `text` ile ayni sozler mi (bosluklar haric)."""
    return bool(_letters(text)) and _letters(plain(markup)) == _letters(text)


_IGNORED = set('“”«»„"\'’‘‚')   # model JSON yazarken “ ” -> " ve ’ -> ' yapiyor (gemma denemesi)


def reproject(markup, text):
    """F187: modelin etiketli cumlesindeki yonergeleri `text`in kendi karakterlerine tasir: bosluklar ve tirnak/kesme
    isaretleri karsilastirilmaz (model “Yine mi?”yi "Yine mi?" diye yaziyor), geri kalan her karakter ayni olmali.
    Tirnaktan once yazilan yonerge tirnaktan once kalir. Sozler uyusmuyorsa ''."""
    text, markup = ' '.join(str(text or '').split()), ' '.join(str(markup or '').split())
    keyed = lambda ch: not ch.isspace() and ch not in _IGNORED
    target = [i for i, ch in enumerate(text) if keyed(ch)]
    inserts, count, last = [], 0, 0

    def consume(segment):
        nonlocal count
        for ch in segment:
            if keyed(ch):
                if count >= len(target) or text[target[count]] != ch:
                    return False
                count += 1
        return True

    for match in re.finditer(_DIRECTION.pattern + '|' + _SCOPED.pattern, markup):
        if not consume(markup[last:match.start()]):
            return ''
        last = match.end()
        tag = match.group(0)
        if tag.startswith('</'):
            position = target[count - 1] + 1 if count else 0
            if markup[match.start() - 1:match.start()] in _IGNORED:   # '..."</soft>': tirnaktan sonra kapanir
                while position < len(text) and text[position] in _IGNORED:
                    position += 1
        else:
            position = target[count] if count < len(target) else len(text)
            following = markup[match.end():].lstrip()[:1]
            if following in _IGNORED or following in '[<':   # '[x] "Yine': tirnaktan once kalir
                while position > 0 and text[position - 1] in _IGNORED:
                    position -= 1
        inserts.append((position, len(inserts), tag))
    if not consume(markup[last:]) or count != len(target) or not inserts:
        return ''
    result, last = [], 0
    for position, _order, tag in sorted(inserts):
        result.append(text[last:position])
        result.append(f' {tag} ' if tag.startswith('[') else tag)
        last = position
    result.append(text[last:])
    return ' '.join(''.join(result).split())


def is_markup(value):
    """Etiketli cumle mi (tek bir katalog etiketi degil)."""
    value = str(value or '')
    return bool(value) and value not in ALL_TAGS and (bool(_DIRECTION.search(value)) or bool(_SCOPED.search(value)))


def directions(markup):
    """Yonergeler sirayla: [('[..]' ya da '<..>', metin)] (kapanan cift etiketler haric)."""
    found = []
    for match in re.finditer(_DIRECTION.pattern + '|' + _SCOPED.pattern, str(markup or '')):
        if match.group(0).startswith('['):
            found.append((match.group(0), match.group(1).strip()))
        elif not match.group(2):
            found.append((f'<{match.group(3)}>', match.group(3)))
    return found


def valid(markup, text, chosen=None, free=True):
    """Dil modelinin etiketli cumlesi: kurallara uyuyorsa duzenlenmis hali, uymuyorsa ''. Sozler degismemeli;
    yonerge en fazla MAX_DIRECTIONS, her biri en fazla MAX_WORDS kelime; cift etiketler resmi yedi etiketten,
    acilip kapanmali, ic ice olmamali; <|..|> belirteci olmamali. `free` degilse yonergeler secili katalogdan."""
    markup = ' '.join(str(markup or '').split())
    if not markup or '<|' in markup or not same_text(markup, text):
        return ''
    residual = _DIRECTION.sub('', _SCOPED.sub('', markup))
    if any(residual.count(mark) != str(text).count(mark) for mark in '[]<>'):
        return ''   # kapanmayan ya da ic ice parantez
    chosen = allowed(chosen)
    open_name = ''
    for match in _SCOPED.finditer(markup):
        name = match.group(2)
        if f'<{name}>' not in PAIRED_TAGS or (not free and f'<{name}>' not in chosen):
            return ''
        if match.group(1):
            if open_name != name:
                return ''
            open_name = ''
        elif open_name:
            return ''
        else:
            open_name = name
    if open_name:
        return ''
    found = directions(markup)
    if not found or len(found) > MAX_DIRECTIONS:
        return ''
    for tag, words in found:
        if tag.startswith('['):
            if not words or len(words.split()) > MAX_WORDS or (not free and tag not in chosen):
                return ''
    return markup


# Tirnakli soz: “..”, «..», ".." ve F187 tek tirnak ‘..’ (Turkce ceviride ic diyalog, Delikanli); arkasindan harf
# gelen ’ kesme isaretidir (Olya’ya), tirnagi kapatmaz.
QUOTED = r'[“«"][^”»"]*(?:[”»"]|$)|‘(?:[^’]|’(?=[^\W\d_]))*(?:’|$)'
OPEN_QUOTES = '“«"‘'
_QUOTED = re.compile(QUOTED)
_STARTS_QUOTE = re.compile(r'(?:\s*\[[^\[\]]*\])*\s*(?:<[A-Za-z]+>\s*)?[“«"‘]')


# Konusmayi bildiren anlatici fiili (cizgili diyalogda '— Gel, dedi adam.' ve araya giren '–dedi Zosimov,–')
SPEECH_VERB = (r'(?:diye|diyerek|diyince|de(?:di\w*|r|miş\w*|yip|yince|yerek)|diyor\w*|sor(?:du\w*|arak|muş\w*)|yanıtla\w*'
               r'|cevap ver\w*|bağır\w*|haykır\w*|fısılda\w*|mırılda\w*|söylen\w*|homurdan\w*|ekle(?:di\w*|yerek)'
               r'|seslen\w*|kükre\w*|inle\w*|gülümse\w*|gül(?:dü\w*|erek))(?!\w)')
_CLOSER = re.compile(r'[”»]|’(?![^\W\d_])|(?<=\S)"')
_INTERJECTION = re.compile(r'(?<=[^\s—–-])\s*[–—]\s*(?=[^\W\d_])[^–—"“”]*?[–—]')
_ATTRIBUTION = re.compile(r'(?<=[,.!?…])\s+(?=' + SPEECH_VERB + ')')
# '— Yahu, dedi, altı aydır gelir gideriz…' (Bay Duduk): kisa anlatici arasindan sonra konusma surer
_SHORT_ATTRIBUTION = re.compile(r'(?<=[,.!?…])\s+' + SPEECH_VERB + r'(?:\s+[^\s,.!?…—–]+){0,2},\s+(?=[^\W\d_])')
_LEADING = re.compile(r'(?:\s*\[[^\[\]]*\])*\s*[—–-]')


def _quote_spans(markup, continued=False):
    """Tirnak araliklari; `continued` (onceki cumlede acilip kapanmamis tirnak) ise ilk kapanis tirnagina kadari da
    sozdur ('Onu görenler, size benzediğini söylüyorlar," dedi.')."""
    spans, start = [], 0
    if continued:
        closer = _CLOSER.search(markup)
        if closer:
            spans.append((0, closer.end()))
            start = closer.end()
    spans += [(m.start(), m.end()) for m in _QUOTED.finditer(markup, start)]
    return spans


def _without(markup, keep):
    """`keep(match)` False olan [..] yonergeleri atar."""
    kept, last = [], 0
    for match in _DIRECTION.finditer(markup):
        if not keep(match):
            piece = markup[last:match.start()]
            following = markup[match.end():].lstrip()
            punctuated = following[:1] in tuple(',.;:!?…')
            kept.append(piece.rstrip() if punctuated else piece)
            last = len(markup) - len(following) if punctuated else match.end()
    return ' '.join((''.join(kept) + markup[last:]).split())


def _dash_safe(markup):
    """Cizgili diyalog: anlaticinin araya giren ('–dedi Zosimov,–') ve sondaki ('…, dedi adam.') sozleri yonergesiz;
    onlardan once RESET_NARRATION, araya girenden sonra konusmanin on eki yeniden."""
    leading = _LEADING.match(markup)
    if not leading or not (_DIRECTION.search(markup) or _SCOPED.search(markup)):
        return markup
    style = next((m.group(0) for m in _DIRECTION.finditer(markup)
                  if not re.search(r'[^\W\d_]', _DIRECTION.sub('', markup[leading.end():m.start()]))), '')
    narrator = [(m.start(), m.end(), True) for m in _INTERJECTION.finditer(markup, leading.end())]
    narrator += [(m.start(), m.end(), True) for m in _SHORT_ATTRIBUTION.finditer(markup, leading.end())
                 if not any(a <= m.start() < b for a, b, _ in narrator)]
    narrator.sort()
    tail = None
    for match in _ATTRIBUTION.finditer(markup, leading.end()):
        if not any(a <= match.start() < b for a, b, _ in narrator):
            tail = match
    if tail:
        narrator = [span for span in narrator if span[0] < tail.start()] + [(tail.start(), len(markup), False)]
    if not narrator:
        return markup
    result, last = [], 0
    for start, end, inner in narrator:
        result.append(markup[last:start])
        piece = _without(markup[start:end], lambda _match: False)
        result.append(f' {RESET_NARRATION} {piece} ')
        if inner and style and re.search(r'[^\W\d_]', markup[end:]):
            result.append(f'{style} ')
        last = end
    result.append(markup[last:])
    return ' '.join(''.join(result).split())


def narrator_safe(markup, continued=False):
    """F187: tirnakli cumlede anlaticinin sozlerine konan [..] yonergeleri atilir ('[kendi kendine fısıldayarak] Ve
    araba ... [panikle] “Hırsız!” diye tekrarladım.' -> yalnizca [panikle] kalir); tirnagin hemen onundekiler ve
    icindekiler kalir. Yonergeli sozden sonra anlatici devam ediyorsa tirnak kapaninca RESET_NARRATION eklenir
    (kullanicinin dinlemesi: on ek tirnaktan sonraki 'diye haykırıyorlardı...' kismina da tasabiliyor).
    Cizgili diyalogda anlaticinin sozleri _dash_safe ile. `continued`: cumle onceki cumlede acilan tirnagin icinde
    baslar (tirnaksizsa butunu soz)."""
    markup = str(markup or '')
    spans = _quote_spans(markup, continued)
    if not spans:
        return markup if continued else _dash_safe(markup)
    inside = lambda position: any(start <= position < end for start, end in spans)
    markup = _without(markup, lambda match: inside(match.start()) or _STARTS_QUOTE.match(markup, match.end())
                      or (continued and match.start() < spans[0][1]))
    result, last, styled, style, reset = [], 0, False, '', False
    for start, end in _quote_spans(markup, continued):
        own = _DIRECTION.search(markup, last, start + 1) or _DIRECTION.match(markup, start + 1)
        if own:
            style = own.group(0)
        elif reset and style:
            # '"Her neyse," [sakin anlatıcı sesi] dedi Didactylos, "yapılması…"': ayni konusmacinin sozu surer
            result.append(markup[last:start] + f' {style} ')
            last = start
        styled = styled or bool(_DIRECTION.search(markup, last, end) or _SCOPED.search(markup, last, end))
        reset = False
        closing = re.match(r'\s*</[A-Za-z]+>', markup[end:])
        if closing:
            end += closing.end()
        end += re.match(r'[,.;:!?…]*', markup[end:]).end()   # '“Teddy!”, diye' -> sifirlama virgulden sonra
        result.append(markup[last:end])
        last = end
        following = markup[end:]
        if styled and re.match(r'[\s—–-]*[^\W\d_]', following) and not _STARTS_QUOTE.match(following):
            result.append(' ' + RESET_NARRATION)
            reset = True
        styled = False
    return ' '.join((''.join(result) + markup[last:]).split())


def legacy_tag(markup, chosen=None):
    """Budanmis Drama 3 icin etiketli cumleden tek katalog etiketi: icindeki ilk katalog etiketi, yoksa yonerge
    metnindeki anlatim ipucu ('[öfkeyle, dişlerini sıkarak]' -> [angry]); '' yok."""
    chosen = allowed(chosen)
    found = directions(markup)
    for tag, _words in found:
        if tag in chosen:
            return tag
    for _tag, words in found:
        lower = words.replace('I', 'ı').replace('İ', 'i').lower()
        for tag, pattern in _CUE_PATTERNS:
            if tag in chosen and tag.startswith('[') and pattern.search(lower):
                return tag
    return ''


def starts_with_style(markup):
    """Etiketli cumle on ekle mi basliyor (sonraki cumlelere tasiyabilir)."""
    text = str(markup or '').lstrip('—–- "“«')
    return text.startswith('[')
