# Aktar — Geliştirme Devir Belgesi

Bu belge, uzun çalışma oturumlarında **context dolduğunda yeni bir chat ile kaldığımız yerden devam edebilmemiz** için tutulur. Yapılan işler, tasarım kararları ve tamamlanma durumları burada işaretlenir.

- **Proje yolu:** `Z:\LLM-Files\Projects\Aktar`
- **Köken (tarihsel):** İlk sürümler Cevirgec'ten uyarlandı (kardeş proje: `Cevirgec-git`), ancak projeler belirgin biçimde ayrıştı; Cevirgec artık kod kaynağı değildir (2026-09-20).
- **Son güncelleme:** 20 Eylül 2026 — **F43 (gerçek LM Studio ile VM'de uçtan uca test: `altyazi-ornekleri` 12/12 dosya çevrildi, yapı korundu; gözlenen hata davranışları raporlandı; 129/129 birim test `OK`) bitti**. **F42 (README'ye kardeş projelerdeki gibi ortalanmış açık/koyu tema logo başlığı eklendi; `assets/logo-light.svg` + `assets/logo-dark.svg` üretildi — XML geçerli, headless Edge ile iki temada görsel doğrulandı) bitti**. **F41 (sürükle-bırak alanında yalnızca ikon + "Videoyu buraya bırakın" kaldı; ikona tıklayınca "Video Seç" akışı tetikleniyor — 129/129 test `OK`, offscreen fonksiyonel probe geçti) bitti ve kullanıcı GUI'de doğruladı ("düzgün çalışıyor onaylıyorum.", 2026-09-20)**. **F40 (temizlik: `.gitignore`'a çalışma zamanı dosyaları eklendi, `requirements.txt` güncel doğrulandı, README'ye İngilizce açıklama, `offscreen.png`/`config.json`/`series`/`work_files` silindi — 128/128 test `OK`) bitti**. **F39 (ayarlardan model seçilince sağ üstteki durum rozetinin güncellenmemesi düzeltildi) bitti ve kullanıcı GUI'de doğruladı ("Olmuş onaylıyorum.", 2026-09-20); 128/128 test `OK`**. **F37 (çeviri tamamlanınca toast yerine "Tamam" ile kapatılan modal bildirim) bitti ve kullanıcı GUI'de doğruladı (çeviri bitince "Çeviri tamamlandı" uyarısı açılıyor, 2026-09-20); F37 sözleşme testi yeni davranışa göre güncellendi (127/127 test `OK`)**. **F36 ("aktar." marka noktasının yazıyla baseline hizalanması + Video Seç etiketi test sözleşmesinin kullanıcı kararına göre güncellenmesi) kodlandı ve otomatik doğrulandı (127/127 test OK)**. F35 (ikonlu düğmelerde yeşil vurgu yalnızca hover'da + seri dropdown popup'ının combo altına açılması) kodlandı ve otomatik doğrulandı (127/127 test OK) ve kullanıcı GUI'de doğruladı (2026-09-20)**. F34 (tıklanabilir öğelerde hover'da yeşil metin/simge vurgusu + pencere düğmelerinde yeşil arka planın kaldırılması) kodlandı ve otomatik doğrulandı (126/126 test OK) (tıklanabilir öğelerde hover'da yeşil metin/simge vurgusu + pencere düğmelerinde yeşil arka planın kaldırılması) kodlandı ve otomatik doğrulandı (126/126 test OK)**. F33 (üst bar alt kenarındaki istenmeyen "genişletme" bölgesi kaldırıldı) kodlandı ve otomatik doğrulandı (124/124 test OK). F32 (frameless pencere + özel başlık şeridi) kodlandı ve otomatik doğrulandı; kenardan boyutlandırma, dış çerçeve (QFrame#appRoot), ortalanmış pencere düğmeleri ve yeşil hover eklendi. Gerçek Windows etkileşim doğrulaması bekliyor. F31 bitti ve doğrulandı (118/118 test OK + kullanıcı GUI doğrulaması).

> **GÜNCEL DEVİR — F30:** Aşağıdaki F28/F29 kayıtları geçmiş denemelerdir; oradaki "sıra güvenilirdir" kararı geri alındı. Eşit cevap sayısı doğru eşleşmenin kanıtı değildir. Eski protokolün çeviri checkpoint'leri bu sürümde kabul edilmez; dosyayı yedekleyip yeniden adlandırarak temiz çeviri başlatın. Kullanıcının son başarısız çalışmasının ham model yanıtı bu pakette bulunmadığından, o yanıtın birebir yeniden üretildiği iddia edilmez.

> **YENİ CHAT — ÖNCE BUNU OKU (devir notu, 2026-09-19):**
> - **Bitti ve doğrulandı:** F0-F4, F11, F12. Kanıtlar `Z:\LLM-Files\Projects\Aktar\test-cikti\` klasöründe (`test sonucu.txt`, `programdaki log.txt`, kaynak/çeviri `.ass`, `LM studio logs.txt`).
> - **F11 çözümü:** `subtitle.rebuild` satır sayısı uyuşmazlığında artık hata vermez; çeviriyi kaynak satır sayısına göre **kelime sınırında** yeniden böler (`subtitle._reflow`). Motor `_assemble` bunu `note=self._note_reflow` ile loglar (`BILGI: model satir sayisini degistirdi ... yeniden bolundu.`). `validate_structure` yalnızca testlerde güvenlik ağı olarak kaldı.
> - **Yapılan son değişiklikler:** `subtitle.py` (`_reflow`, `rebuild(..., note=)`), `app_core.py` (`_assemble` instance metodu + `_note_reflow`), `translation_prompt.txt` (satır sonu kuralı), `tests/test_core.py` (5 rebuild + 1 motor testi; toplam 62), `README.md`, `KULLANIM.md`, `DERLE.cmd`.
> - **§5 kararları ONAYLANDI (2026-09-19):** madde 4 → yalnızca `Dialogue` metni (varsayılan); madde 5 → kaynak Türkçe ise **atla-uyar, çeviriyi engelleme**; madde 6 → yeni terim önerisi **seri düzeyinde** saklanır (`the_office_1` çevrilince terimler seriye yazılır, `the_office_2` oradan referans alır). Kod uygulaması F14'te bekliyor.
> - **F13 (arayüz yenileme) — kod tamam:** `gui.py` mockup-2 v2 düzenine göre baştan yazıldı: üst `QToolBar` (Dosya / Seri + **Terim** + sağda **Ayarlar**), checkbox'lı akış tablosu, işlem satırı (**Ön analiz yap** tick → **Çevir** → **Duraklat**), altta `QDockWidget` + sekmeler (**Konsol** / **Ön Analiz**). **Tek "Çevir" butonu** çıkarma + çeviriyi zincirler (çıkarma bitmeden çeviri başlamaz), iş boyunca **pasif** olur. Duraklat düğmesi eklendi. Ön analiz sonrası **terim onay diyaloğu** (`GlossaryReviewDialog`) açılır; onaylananlar seri sözlüğüne yazılır. Kullanıcı testi bekliyor.
> - **F13/F14-madde6/F15 — BİTTİ VE DOĞRULANDI (2026-09-19):** 67/67 test `OK`; kullanıcı GUI'de denedi, düzgün çalışıyor. Ön analiz → **terim onay diyaloğu** (`GlossaryReviewDialog`) açılıp seri sözlüğüne yazıyor; sağ üstte **Ayarlar** (`SettingsDialog`) Base URL/Model/Katı sözlük/Otomatik tekrar yönetiyor; `glossary_strict` motor tarafında uygulanıyor.
> - **Kalan tek iş (§5 madde 5 / F14):** kaynak altyazı zaten Türkçe ise satır-bazlı tespit → UYARI logu, çeviri engellenmez. Henüz kodlanmadı.
> - **Diğer bekleyenler:** `README.md` için `docs/screenshot.png` henüz eklenmedi.
> - **F16 (tema + logo/simge) — BİTTİ VE DOĞRULANDI (2026-09-19):** `gui.py` tema sözlüğü + QSS şablonu (`.format()`), araç çubuğunda logo + küçük harf `aktar` + lime nokta; `DERLE.cmd` `--icon assets\aktar.ico` + `assets` gömme. Kullanıcı arayüzü ve `.exe` simgesini doğruladı (ilk bakışta eski görünmesi Windows ikon önbelleğiydi; exe yeni adla kopyalanınca doğru çıktı). `asset_path` artık `test-cikti/export`'a bakmaz.
> - **F24 (arayüz tazeleme) — kod tamam:** `gui.py` düzeni kart yüzeylerine (`QFrame#card`) taşındı, `QDockWidget` yerine `QSplitter` geldi, araç çubuğu ikon kazandı, boş durum ekranı eklendi, tamamlanma bildirimi modal yerine **toast** oldu. **Renk paleti değişmedi** (kullanıcı isteği); yalnızca lime'ın düşük opaklıklı türevleri (`accent_soft`/`accent_edge`) eklendi. `tests/test_gui_contract.py` paletin sabitliğini de doğruluyor.
> - **F29 (2026-09-19) — Bitti ve otomatik doğrulandı:** F28 sonrası aynı bölüm bu kez **35. partide** durdu. Model, kaynağın kendi liste numaralarını (`1.`/`2.`/`3.`) ID sanıp `1,2,3,1,2,3,...` diye numaraladı. **Ders:** modelin ürettiği numaralar güvenilmez; doğru sinyal **sıradır**. `parse_translation_response` numara değerlerini artık karşılaştırmıyor, blok **sayısı** beklenen ID sayısına eşitse sıraya göre eşliyor (ID etiketi varsa o yine öncelikli). 103/103 test `OK`; LM Studio'daki gerçek ham yanıt ve gerçek S02E18 (1242 cue) ile uçtan uca doğrulandı.
> - **Kural hatırlatması:** `test-cikti/` klasörü bilerek `.gitignore`'a **eklenmedi** (kullanıcı isteği).
> - **F28 (2026-09-19) — Bitti ve otomatik doğrulandı:** `S02E18-Turning Point 3` 46. partide kalıyordu çünkü model 10 girdiyi tek satıra indirip `ID:`/`TEXT:` etiketlerini **tamamen** düşürdü (`1. Cansız madde çağırma` …). `subtitle.parse_translation_response` artık düz numaralı liste biçimini de kabul ediyor; numara dizisi beklenen ID'lerle birebir örtüşmezse yine hata verir. 100/100 test `OK`; gerçek S02E18 ile sahte-model uçtan uca koşu `1242 -> 1242` geçti. Kullanıcı tarafında yeniden çeviri bekliyor; kaldığı yerden devam ederse checkpoint temizlenmeli.

---

## 0. Devir protokolü — ÖNCE BUNU OKU

### Yeni chat başlatınca
Aşağıdaki talimatı yapıştır (veya aynısını söyle):

> `Z:\LLM-Files\Projects\Aktar\GELISTIRME.md` dosyasını oku. `[x]` işaretlerini ve "Durum" satırlarını doğrula; kaldığımız işten devam et. Yapılan her yeni işi bu dosyada `[ ]` → `[x]` yap ve "İş işaretleme kuralları"na uy.

### İş işaretleme kuralları
Bir geliştirme maddesi tamamlandığında:

1. İlgili satırın `[ ]` işaretini `[x]` yap.
2. "Durum:" satırını `Bitti` yap.
3. Altına `- **Yapıldı (TARİH):** ...` şeklinde kısa not ekle (hangi dosyalar değişti, hangi test eklendi/geçti, elle doğrulama yapıldıysa ne yapıldı).
4. `main` → testler → kısa özet sırasıyla işi bitir.

### Her oturumda yapılacak sabit kontrol
```bat
cd /d Z:\LLM-Files\Projects\Aktar
py -3 -m unittest discover -s tests -v
```
Testler geçmeden maddeyi `[x]` yapma.

### Test ortamı
Komut satırı erişimi olan geliştirme ortamında `python -m unittest discover -s tests -v` çalıştırılır. Windows/EXE/GUI davranışları ayrıca kullanıcı tarafında doğrulanır. Komut satırı olmayan bir ortamda kod/test eklenir fakat **çalıştırılmamış sonuç geçmiş gibi yazılmaz**.

### Kod değişikliği öncesi altın kurallar
- Kullanıcı mesajları Türkçe; anahtar/dosya adları İngilizce ve ASCII (kod içinde Türkçe karakter yok).
- Kullanıcıya ham `FileExistsError`, `KeyError` gibi ham istisnalar gösterme; anlamlı `RuntimeError`/`ValueError` üret.
- **Kaynak video salt-okunur kabul edilir.** Kopyalama, klonlama, taşıma, yeniden encode veya `ffmpeg ... output.mkv` gibi yeni video üretimi yoktur. Yalnızca okunur ve seçilen subtitle stream üzerinde işlem yapılır.
- Çeviri/checkpoint/glossary mantığı tek bir çekirdekte (`app_core.py`) tutulur; GUI ve CLI bunu paylaşır, mantık kopyalanmaz.
- Çekirdek ve arayüz platformdan bağımsız yazılır; Windows'a özgü kısımlar (`.cmd`, `.exe`, bundled `ffmpeg.exe`) ayrıca ve açıkça ele alınır.

### Belge görevleri
- **README.md:** GitHub ana sayfası — kısa tanım, ekran görüntüsü, öne çıkan özellikler, gereksinimler, hızlı başlangıç, KULLANIM bağlantısı, gizlilik/sınırlama özeti, lisans.
- **KULLANIM.md:** Kullanıcıya yönelik tam kılavuz — kurulum, LM Studio, bütün akışlar, glossary, ayarlar, sorun giderme.
- **GELISTIRME.md:** Bu belge — tasarım kararları, tamamlanan/bekleyen işler, test sonuçları. Son kullanıcı kılavuzu yerine kullanılmaz.

---

## 1. Proje tanımı ve kapsam

**Aktar**, video dosyalarındaki (öncelikle `.mkv` / `.mp4`) **metin tabanlı altyazı akışlarını** tespit edip çıkaran ve bunları **LM Studio'da çalışan yerel bir modelle Türkçeye çeviren** masaüstü uygulamasıdır. Çevirgeç'in çekirdek mantığını (yerel LLM istemcisi, zorunlu terim sözlüğü, ön analiz, kontrol noktası/retry) altyazı alanına uyarlar.

**Hedef akış:**
```
Video (sürükle-bırak veya Video Seç)
  ↓ ffprobe → subtitle stream'lerini listele (codec + dil + başlık)
  ↓ kullanıcı desteklenen bir stream seçer
  ↓ ffmpeg → seçilen stream'i çıkar (orijinal formatta)
  ↓ altyazıyı parse et (yalnızca çevrilecek metni ayır)
  ↓ LLM ile Türkçeye çevir (glossary zorunlu)
  ↓ timestamp / sıra / ASS tag'leri program tarafından korunur
  ↓ çıktı: videonun yanına "<video>_TR.srt"
```

**Prensip:** LLM'e ham altyazı dosyasını değiştirip geri üretme sorumluluğu **verilmez**. Program yapısal bilgiyi (timestamp, sıra numarası, ASS tag'leri) kendisi yönetir; LLM'e yalnızca `ID` + `TEXT` gönderilir, yalnızca çevrilmiş metin geri alınır. Böylece timestamp bozulması, satır atlama, sıra değişimi, ASS tag bozulması ve blok kaybı engellenir veya doğrulamayla tespit edilir.

---

## 2. Mimari ve teknoloji kararları

### 2.1 Çekirdek (backend) — Python
Çevirgeç'teki bütün değerli mantık Python'da ve altyazı alanında neredeyse birebir yeniden kullanılabilir:
- LM Studio istemcisi (`Client`, yerel HTTP, proxy yok, redirect reddi)
- Zorunlu terim sözlüğü (glossary) + Türkçe çekim toleransı (`_target_search`, `_strip_turkish_suffixes`, `source_term_regex`)
- Ön analiz + terim önerisi onay akışı
- Kontrol noktası (checkpoint) / duraklat / sürdür
- `auto_retry_count`, bitiş işareti, yapısal doğrulama desenleri

**Karar:** Çekirdek Python'dur. `app_core.py` Cevirgeç'ten uyarlanır (kopyala-yapıştır değil; EPUB'a özgü kısımlar çıkarılıp altyazıya özgü doğrulama eklenir).

### 2.2 Ortam araçları — ffmpeg / ffprobe
- `ffprobe`: stream + metadata tespiti (`-show_streams -show_format -of json`).
- `ffmpeg`: seçilen metin tabanlı stream'i çıkarma / gerektiğinde uygun formata dönüştürme.
- Uygulamayla **taşınabilir** sağlanır: `bin\ffmpeg.exe`, `bin\ffprobe.exe`. Kullanıcının sistemine ayrıca FFmpeg kurması zorunlu değildir.
- **Teknik uyarı:** `-map 0:s:N` subtitle stream'leri **subtitle sırasına** göre indeksler; ffprobe'daki global stream `index` ile aynı değildir. Eşleme karışıklığını önlemek için global stream index kullanılmalı ve test edilmelidir.

### 2.3 Arayüz — PySide6 (karar verildi)
**Karar (2026-09-18): PySide6.** Gerekçe: çekirdek zaten Python; tek dil, tek derleme (PyInstaller), `app_core` doğrudan import edilir. Arayüz ince (sürükle-bırak + stream listesi + ilerleme + hata mesajı) olduğundan Electron+Vite+Python sidecar'ın iki-toolchain ve IPC maliyeti gereksiz. Değerlendirilen alternatif: Electron + Vite (arayüz) + Python sidecar (arka taraf, izci yığını) — reddedildi.

### 2.4 Modül taslağı (stack ne olursa olsun çekirdek aynı kalır)
```
Aktar/
  app_core.py        # LM Studio istemcisi, glossary, ceviri motoru, checkpoint
  media.py           # ffprobe stream tespiti + ffmpeg cikarma (subprocess)
  subtitle.py        # SRT/ASS/SSA/VTT parse + yaz (yapisal koruma)
  series.py          # seri bazli glossary + continuity deposu (APP_DIR/series)
  cevir.py           # CLI giris noktasi (extract / translate / check)
  gui.py             # arayuz (PySide6)
  bin/ffmpeg.exe, bin/ffprobe.exe
  series/            # seri sozlukleri (kullanici verisi; surum kontrolune girmez)
  config.json, translation_prompt.txt
  tests/test_core.py
  README.md, KULLANIM.md, GELISTIRME.md, LICENSE, requirements.txt
```

---

## 3. Kesinleşen kararlar

- **Kaynak video salt-okunur.** Kopyalanmaz/klonlanmaz/taşınmaz/değiştirilmez/yeniden encode edilmez.
- **İlk sürümde yalnızca metin tabanlı altyazılar:** SRT, ASS, SSA, VTT, MOV Text (tx3g). Görüntü tabanlı (PGS/hdmv_pgs_subtitle, VobSub/dvd_subtitle) **desteklenmez** ve tespit edilirse "Görüntü tabanlı altyazı — şu anda desteklenmiyor." mesajı gösterilir (hata fırlatılmaz).
- **Altyazı türü uzantıya göre tahmin edilmez**; codec bilgisi ffprobe'dan okunur (`.sub` hem MicroDVD hem VobSub olabilir).
- **Çıktı konumu:** Videonun kendi dizini (ayrı `Output\` klasörü **değil**).
- **Format korunur:** Kaynak altyazının formatı korunur — SRT→SRT, ASS→ASS, SSA→SSA, VTT→VTT. ASS altyazılar otomatik olarak SRT'ye dönüştürülmez (stil/konumlandırma/karaoke kaybını önlemek için). Yalnızca `mov_text`/`tx3g` (MP4) uygun metin formatına (SRT) dönüştürülür.
- **Çıktı adı:** `<video-adı>_TR.<uzantı>` (örn. `Movie.mkv` + SRT kaynak → `Movie_TR.srt`; ASS kaynak → `Movie_TR.ass`).
- **Çıktı çakışması:** Var olan dosyanın üzerine **sessizce yazılmaz**; `Movie_TR (2).srt`, `Movie_TR (3).srt` ... biçiminde yeni ad üretilir.
- **Çeviri çekirdeği LLM'e yapı bırakmaz:** yalnızca metin gider, yalnızca çeviri döner; timestamp/sıra/ASS tag'leri program korur.

### 3.1 Seri (TV dizisi/anime) bazlı glossary + continuity
**Karar (2026-09-18):** Seri içeriklerde bölümler arası tutarlılık için **glossary + continuity kararları** birlikte seri düzeyinde saklanır (yalnızca glossary yetersiz: hitap biçimleri sen/siz, isim yazımı, tekrar eden kalıplar da sabit kalmalı).

- **Depolama:** `APP_DIR\series\<slug>.json` (uygulama dizini; taşınabilir). Yazma başarısız olursa (`C:\Program Files` gibi korumalı klasör) anlamlı `RuntimeError` ile bildirilir — sessizce yutulmaz.
- **Dosya biçimi:**
  ```json
  {
    "title": "Game of Thrones",
    "created": "2026-09-18T00:00:00",
    "folder_hints": ["Game of Thrones"],
    "glossary": [{"source": "White Walker", "target": "Ak Gezen"}],
    "decisions": ["Jon Snow'a 'sen', Lord'lara 'siz'"],
    "episodes": [{"file": "S01E01.mkv", "date": "2026-09-18T00:00:00"}]
  }
  ```
- **Akış:** GUI'de üstte dropdown: `[ Yok | Game of Thrones | ... | + Yeni seri... ]`. Video klasör adı `folder_hints` ile eşleşirse seri **önerilir** (zorlanmaz, önceden seçili gelir). `+ Yeni seri...` → başlık sorulur, ASCII slug ile dosya oluşturulur.
- **Çeviri kapsamı:** seri glossary temel alınır + bölüme özel glossary eklenir; **çakışmada bölümün kendi girdisi kazanır**, ikisi de zorunlu uygulanır. Seri `decisions` listesi her çeviri isteğine referans olarak verilir.
- **Yeni terim önerisi:** Bölüm çevrilince analizde çıkan yeni terimler, seriye eklenmek üzere onaya sunulur (Çevirgeç G16 deseni).
- **Eşzamanlılık:** Seri dosyasına yazım `app_core.FileLock` ile korunur.
- **Not (F0 kapsamı):** `series.py` ve `series/` iskeleti F0'da kurulur; GUI dropdown ve otomatik öneri F3'te, terim önerisi onay akışı F2/F3'te bağlanır.

---

## 4. Yol haritası (fazlar)

### F0. İskelet ve altyapı
- [x] **Durum:** Bitti
- [x] Proje iskeleti, `requirements.txt`, `config.json`, `translation_prompt.txt` (altyazı uyarlaması)
- [x] `bin\ffmpeg.exe` + `bin\ffprobe.exe` taşınabilir yerleşimi ve yol çözümlemesi (`media.py`)
- [x] `series.py` + `series/` klasörü (seri glossary + continuity deposu)
- [x] `.gitignore`, `LICENSE` (MIT)
- **Yapıldı (2026-09-18):** Proje iskeleti oluşturuldu: `app_core.py` (LM Studio istemcisi + glossary + seri bağlama iskeleti), `media.py` (ffprobe/ffmpeg yol çözümleme + stream tespiti/çıkarma iskeleti), `subtitle.py` (SRT/ASS/SSA/VTT parse/yaz iskeleti), `series.py` (seri deposu), `cevir.py` (CLI), `config.json`, `translation_prompt.txt`, `requirements.txt`, `.gitignore`, `LICENSE`, `tests/test_core.py`.
- **Doğrulama:** `py -3 -m unittest discover -s tests -v` → 29 testin tamamı `OK` (2026-09-18, kullanıcı tarafında). `bin/` içine ffmpeg/ffprobe ikilileri kullanıcı tarafından konacak.

### F1. Video açma + altyazı listeleme + çıkarma (çevirisiz)
- [x] **Durum:** Bitti
- [x] Sürükle-bırak ile video alma (`gui.py` DropArea)
- [x] Klasörden video bulma/seçme (`media.find_videos` + "Klasör Seç")
- [x] `ffprobe` ile subtitle stream listesi (codec + dil + başlık + global index)
- [x] Desteklenmeyen (görüntü tabanlı) stream'ler işaretli gösterim
- [x] `ffmpeg` ile seçilen stream'i orijinal formatta çıkarma
- [x] Çıktı adı/konumu (videonun dizini, `<video>_TR.<uzantı>`) ve çakışma (`_TR (2)`) davranışı
- **Yapıldı (2026-09-18):** `gui.py` (PySide6) eklendi: DropArea ile sürükle-bırak, "Klasör Seç" (`find_videos`), stream tablosu (codec/dil/başlık/durum), "Altyazıyı Çıkar" (ffprobe/ffmpeg worker thread'de). `tests/test_core.py`: `MediaProbeTests` eklendi — ffprobe JSON parse (desteklenen/görüntü tabanlı ayrımı), probe hatası, `-map 0:<global index>` kullanımı, `mov_text`→SRT dönüşümü, görüntü tabanlı codec reddi.
- **Doğrulama:** Birim testleri kullanıcı tarafında geçti (34/34 `OK`, 2026-09-18). **Gerçek uçtan uca elle doğrulama da yapıldı (2026-09-18):** `bin\` içine ffmpeg/ffprobe konuldu, `GUI_BASLAT.cmd` çalıştı; altyazılı `.mkv` sürükle-bırak → stream listesi geldi (ASS / eng / English sub); PGS stream "Görüntü tabanlı - desteklenmiyor" gösterdi; metin tabanlı stream seçilip "Altyazıyı Çıkar" → `[SubsPlease] Clevatess S2 - 01v2 (1080p) [E4151116]_TR.ass` oluştu; ikinci çıkarma → `..._TR (2).ass`.
- **Bilinen arayüz kusuru (F3'e taşındı):** Stream tablosunda `QHeaderView.Stretch` tüm sütunlara uygulandığından sütunlar sıkışıp iç içe geçiyor. Çözüm: `#`/`Codec`/`Dil`/`Durum` sütunları `ResizeToContents`, yalnızca `Başlık` `Stretch`. Kullanıcı kararı: en kolay yer olduğu için sonra dönülecek.

### F2. Çeviri çekirdeği (glossary + checkpoint)
- [x] **Durum:** Bitti
- [x] `app_core.py` LM Studio istemcisi (`Client`), yanıt doğrulama (`clean_response`), retry (`_generate`)
- [x] SRT/ASS/SSA/VTT parse + yapısal doğrulama (`subtitle.py`; timestamp/sıra/tag korunumu)
- [x] ID+TEXT tabanlı kontrollü çeviri isteği (`build_translation_request` / `parse_translation_response`)
- [x] Glossary + Türkçe çekim toleransı (`glossary_missing`, `_target_search`) + zorunlu düzeltme turu
- [x] Parti bazlı checkpoint / duraklat / sürdür (`TranslationEngine`, `PauseController`)
- **Yapıldı (2026-09-18):**
  - `app_core.py`: `TranslationEngine` (parti bazlı çeviri, imza tabanlı checkpoint, glossary zorunluluğu ve tek düzeltme turu), `PauseController` (duraklat/kapat + `GracefulStop`), `clean_response`, `glossary_missing`, `GLOSSARY_FIX_PROMPT`, `prompt_path`.
  - `cevir.py`: `translate` komutu (`--series`, `--glossary Kaynak=Karşılık`); çıktı altyazının dizinine `<ad>_TR.<uzantı>`, çakışmada `_TR (2)`.
  - `tests/test_core.py`: `EngineTests` (10 test) — timestamp korunumu, ID/TEXT + glossary gönderimi, tek glossary düzeltme turu, düzeltme sonrası hâlâ eksikse hata, checkpoint ile tamamlanan partilerin atlanması, imza uyuşmazlığı, duraklat/kapat davranışı, `clean_response` reddi, kaynakta geçmeyen terimin denetlenmemesi.
- **Doğrulama:** `py -3 -m unittest discover -s tests -v` → 43 testin tamamı `OK` (2026-09-18, kullanıcı tarafında). **Düzeltilen hata:** `_load_state` checkpoint'ten okunan JSON sözlük anahtarlarını (`"0"`) `int`'e çevirmiyordu; "bu parti tamamlandı" kontrolü hiç tutmuyor, kesilen çeviri kaldığı yerden devam etmiyordu. Test (`test_checkpoint_skips_completed_batches`) bunu yakaladı; düzeltme sonrası geçti.
- **Not:** Ön analiz (kitap analizi karşılığı) ve seri terim önerisi onayı bu fazda yok; F3/G-sonrası olarak değerlendirilecek. Gerçek LM Studio ile uçtan uca çeviri henüz denenmedi (F3 sonrası).

### F3. Arayüz (PySide6)
- [x] **Durum:** Kod tamam — Windows'ta kullanıcı testi bekliyor
- [x] Sürükle-bırak, stream seçimi, ilerleme, hata mesajları
- [x] Seri dropdown'u (`(Seri yok) | <seri> | + Yeni seri...`) + `folder_hints` ile otomatik öneri
- [x] Glossary düzenleme (bölüm + seri) — tek `GlossaryDialog`
- [x] Çeviri akışı: çıkar → çevir → `<video>_TR.<uzantı>`; ilerleme + iptal
- [x] Stream tablosu sütun düzeltmesi (`#`/`Codec`/`Dil`/`Durum` = ResizeToContents, `Başlık` = Stretch)
- **Yapıldı (2026-09-18):**
  - `gui.py`: seri dropdown + "Seri sözlüğünü düzenle"; `GlossaryDialog` (bölüm ve seri için ortak); "Altyazıyı Çıkar" → "Çevir" akışı (`TranslateWorker` — worker thread, ilerleme, iptal/duraklat); sütun yeniden boyutlandırma düzeltildi; `folder_hints` ile seri önerisi.
  - `subtitle.py`: `parse_by_extension` / `render_by_kind` / `cues_of` (GUI ve CLI ortak).
  - `media.py`: `unique_source_path` (kaynak altyazı çıkarma adı) — `unique_output_path` (çeviri `_TR`) ile birlikte tek `_unique_path` üzerinden.
  - `cevir.py`: `translate` komutu `subtitle.parse_by_extension` kullanacak şekilde sadeleştirildi.
  - `tests/test_core.py`: `SubtitleFormatTests` (4 test) + `test_unique_source_path_adds_counter`.
- **Doğrulama:** Kod yazıldı; testler ve GUI elle doğrulaması Windows'ta kullanıcı tarafından yapılacak. **Gerçek LM Studio ile uçtan uca çeviri (çıkarılmış `.ass`/`.srt` üzerinde) henüz denenmedi.**
- **Bekleyen (F3 sonrası / yeni madde):** seri terim önerisi onayı (bölüm çevrilince yeni terimleri seriye ekleme önerisi), ön analiz, duraklat düğmesi (kod hazır, arayüz düğmesi eklenmedi).

### F5. İlk gerçek LM Studio çalıştırmasında iki hata (retry sayacı + boş yanıt teşhisi)
- [x] **Durum:** Bitti
- **Sorun 1 — retry sayacı:** Log'da `Gecici hata, yeniden deneme 1/2, 2/2, 3/2` görülüyordu; döngü `retries + 1` kez çalıştığı halde sayaç `retries`e kadar yazıyordu (yanlış) ve son denemede gereksiz bir ek deneme mesajı üretiyordu.
- **Sorun 2 — boş yanıt teşhisi yok:** `Bos veya kod blogu iceren yanit alindi.` hatası modelin **neden** metin döndürmediğini söylemiyordu. Gerçek çalıştırmada model yanıtı boş geliyor; `finish_reason` ve düşünce uzunluğu bilinmiyordu.
- **Sorun 3 — base_url belirsizliği:** Kullanıcı `config.json`'da portu değiştirdiği halde log'da hâlâ eski adres görünüyordu; hangi model/adresle çalışıldığı loglanmıyordu.
- **Yapıldı (2026-09-18):**
  - `app_core.Client.generate`: yanıt boşsa `finish_reason` ve `dusunce_uzunlugu` (reasoning_content/reasoning uzunluğu) ile anlamlı `ValueError`; `choices[0].message` eksikse `Beklenmeyen API cikti bicimi`.
  - `app_core.clean_response`: kod bloğu / düşünce işareti / boş yanıt hatalarına yanıtın ilk 180 karakteri (`Baslangic: ...`) ekleniyor.
  - `app_core.TranslationEngine._generate`: `attempt >= retries` iken yeniden denemez, hatayı doğrudan yükseltir; log `Gecici hata (deneme N/toplam)` biçiminde.
  - `app_core.TranslationEngine.translate`: başta `Model: <ad> @ <base_url> (batch_cues=N)` loglanıyor.
  - `tests/test_core.py`: `test_empty_response_retries_then_raises`, `test_client_reports_empty_content_with_finish_reason`, `test_client_returns_content_when_present` eklendi.
- **Doğrulama:** `py -3 -m unittest discover -s tests -v` → 48 test `OK` (2026-09-18, kullanıcı tarafında; F5 öncesi). F5 sonrası koşu bekleniyor.
- **Açık konu:** Gerçek çeviri hâlâ tamamlanmadı; yeni log satırı (`Model: ... @ ...`) ve boş yanıt teşhisi (`finish_reason=...`) sonucu bekleniyor. Olası nedenler: model adı eşleşmiyor, `max_tokens` (4096) düşük, ya da model çıktıyı `reasoning_content`'e koyup `content`'i boş bırakıyor.

### F6. Gerçek çalıştırmada kök neden: model "thinking" üretiyor (content boş)
- [x] **Durum:** Bitti (kod tarafı) — kullanıcı tarafı LM Studio preset ayarı bekliyor
- **Sorun/bağlam:** LM Studio log'u kesin nedeni gösterdi: `finish_reason=length`, `completion_tokens=4096`, `reasoning_tokens=4093`, `content=""`, `reasoning_content` dolu (çeviri taslağı). Yani **model düşünmeye tüm `max_tokens` bütçesini harcıyor**, asıl `content` hiç üretilmiyor. Kod hatası değil; model preset'i "thinking" açık.
- **Yapıldı (2026-09-18):**
  - `app_core.Client.generate`: boş yanıt teşhisi `reasoning_tokens` (usage.completion_tokens_details) ile zenginleştirildi ve mesaja çözüm önerisi eklendi.
  - `disable_thinking` config alanı eklendi; `true` iken istek gövdesine `chat_template_kwargs: {enable_thinking: false}` eklenir (LM Studio desteklerse; desteklemezse yok sayılır).
  - `DEFAULT_CONFIG`/`config.json`: `batch_cues` 40→10 (thinking ile tek istekte 40 satır çok ağır), `max_tokens` 4096→8192.
  - `tests/test_core.py`: `test_disable_thinking_adds_chat_template_kwargs`, `test_thinking_disabled_by_default` eklendi.
- **Kullanıcı tarafı (kalıcı çözüm):** LM Studio'da model preset'inden thinking/reasoning kapatılmalı (reasoning budget yoksa "thinking" anahtarı kapatılır). `disable_thinking` LM Studio sürümü desteklerse alternatif yol olarak çalışır.
- **Doğrulama:** Bekliyor — kullanıcı LM Studio'da thinking kapatıp yeniden deneyecek; testler yeniden koşulacak.

### F7. ASS override tag'leri model tarafından bozuluyordu → tag maskeleme
- [x] **Durum:** Bitti
- **Sorun/bağlam:** Gerçek çalıştırmada `Yapisal altyazi isaretleri korunmadi: girdi 8 ASS tag sayisi degisti.` alındı. Model, `{\fad(1375,0)\pos(320,20)...\t(1982,2730,1 \c&H261DAA&...)}` gibi karmaşık override bloğunu birebir kopyalamak zorunda kalıyordu; tek karakter farkı doğrulamayı düşürüyordu. Cevirgeç'te aynı sınıf sorun EPUB anchor'larında yaşanmıştı (G42).
- **Yapıldı (2026-09-18):**
  - `subtitle.py`: `mask_overrides` (override bloklarını `[[T1]]`, `[[T2]]` ... yer tutucularına çevirir) ve `restore_overrides` (yer tutucuları orijinal bloklarla geri koyar; sayı uyuşmazsa anlamlı `ValueError`).
  - `subtitle.validate_structure`: ASS tag sayısı denetimi korunur; ayrıca `\N` / `\n` satır sonu sayısı denetimi eklendi.
  - `subtitle.build_translation_request`: artık Cue yerine **metin listesi** alır (maskelenmiş metin gönderilir).
  - `app_core.TranslationEngine`: `_mask` / `_unmask` ile parti çevirisi ve glossary düzeltme turu maskelenmiş metin üzerinden çalışır; tag'ler model dönüşünde **program tarafında** geri konur.
  - `translation_prompt.txt`: `[[T#]]` ve `[[BR]]` işaretlerinin birebir korunması kuralı eklendi.
  - `tests/test_core.py`: `test_mask_and_restore_overrides_round_trip`, `test_restore_overrides_detects_dropped_placeholder`, `test_mask_overrides_is_noop_without_tags`; `build_translation_request` imzasına göre mevcut test güncellendi.
- **Kazanç:** Model artık tag kopyalamak zorunda değil; ASS tag'leri kaybedilemez veya bozulamaz. Model yalnızca görünür metni çevirir.
- **Doğrulama:** Bekliyor — kullanıcı yeniden çeviri deneyecek; testler yeniden koşulacak.

### F8. ASS satır sonları (\N) ve modelin eklediği parantezler yapısal doğrulamayı düşürüyordu
- [x] **Durum:** Bitti
- **Sorun/bağlam:** F7'de tag'ler maskelendi ama `\N` satır sonları **maskelenmiyordu**; model bunları yönetmek zorundaydı. Gerçek çalıştırmada (Clevatess S2 bölümü) batch 1-2 geçti, batch 3'te `girdi 8 ASS tag sayisi degisti` alındı. Girdi 8 = `{\an7...}Reigning Sword Saint\N{\fs24}Owen Koath`. Tag'ler maskeli olduğundan geri koyma başarılıydı; sayaç farkı ancak modelin görünür metne **fazladan `{...}` bloğu** (veya yer tutucuyu `{...}` içine sarması) ile doğdu. Tasarım ilkesi ihlali: yapısal belirteçler (tag **ve** satır sonu) modele gitmemeli.
- **Yapıldı (2026-09-19):**
  - `subtitle.py`: `_ASS_STRUCTURE = \{[^}]*\}|\\[Nnh]` — override blokları **ve** `\N`/`\n`/`\h` satır sonları birlikte maskelenir. `mask_overrides`/`restore_overrides` → `mask_structure`/`restore_structure` olarak yeniden adlandırıldı.
  - `subtitle.strip_spurious_braces`: modelin görünür metne eklediği `{...}` blokları ve tek başına `{`/`}` karakterleri temizlenir (yer tutucu içeren blokta yalnızca parantez atılır); temizlenen adet döner.
  - `app_core.TranslationEngine._mask/_unmask`: maskeleme artık satır sonlarını da kapsar; `_unmask` önce `strip_spurious_braces` uygular ve temizlenen adedi loglar. Yapısal doğrulama hatasında model yanıtının ilk 300 karakteri loglanır (teşhis).
  - `translation_prompt.txt`: `[[T#]]` işaretlerinin "formatlama veya satır sonu" belirteci olduğu ve modele `{`/`}` üretmemesi kuralı eklendi.
  - `tests/test_core.py`: `test_mask_structure_masks_line_breaks`, `test_strip_spurious_braces_*` (3 test) eklendi; eski adlar `mask_structure`/`restore_structure` olarak güncellendi.
- **Kazanç:** Model artık ne tag ne satır sonu yönetir; ikisi de program tarafından geri konur. Modelin eklediği parantezler çıktıyı bozamaz.
- **Doğrulama:** Bekliyor — kullanıcı yeniden çeviri deneyecek; testler yeniden koşulacak.

### F9. Yer tutucu yaklaşımı kırılgandı → yapı iskeleti (modele hiç belirteç gitmez)
- [x] **Durum:** Bitti
- **Sorun/bağlam:** F8'de tag'ler `[[T1]]` yer tutucusuna çevrildi; gerçek çalıştırmada model **yer tutucuyu düşürdü** (`yer tutucular beklenenle uyusmuyor (beklenen 1, bulunan [])`). Ayrıca bu hata `_generate` dışında oluştuğu için **retry de çalışmıyordu** — yapısal hatalar yeniden denenmiyordu. Kök neden: yer tutucu da modelin kopyalaması gereken bir metindi; kırılgan.
- **Yapıldı (2026-09-19):**
  - `subtitle.extract_structure` / `join_structure`: ASS metni **görünür parçalara** ve **yapı iskeletine** ayrılır. Tag'ler ve `\N`/`\n`/`\h` modele **hiç gönderilmez**; yalnızca görünür parçalar `[[BR]]` ile birleştirilir. Çeviri dönünce yapı **aynı sırayla** program tarafından geri kurulur.
  - `subtitle.mask_structure` / `restore_structure` bu ikisi üzerinden yeniden yazıldı; `[[T#]]` yer tutucu kavramı **kaldırıldı**.
  - `app_core.TranslationEngine._retry(cfg, action)`: **tüm** parti denemesi (istek + ayrıştırma + iskelet kurma + doğrulama) retry sarmalına alındı. Artık yapısal doğrulama hataları da `auto_retry_count` kadar yeniden denenir.
  - `app_core.TranslationEngine._attempt` / `_fix_glossary`: `_generate` yerine doğrudan `clean_response(client.generate(...))`; glossary düzeltmesi de `_retry` ile sarıldı. Ölü `_generate` kaldırıldı.
  - `translation_prompt.txt`: `[[T#]]` kuralı kaldırıldı; modele `{`/`}` veya backslash tag üretmemesi ve `[[BR]]`'yi koruması söyleniyor.
  - `tests/test_core.py`: maskeleme testleri yeni anlamlılığa göre güncellendi (`test_mask_structure_masks_line_breaks`, `test_restore_structure_detects_missing_part` / `_extra_part`, `test_strip_spurious_braces_*`); yanlış yazılmış `test_strip_spurious_braces_removes_lone_braces` beklentisi düzeltildi (`{ b }` bloğu b ile birlikte silinir → `a  c`).
- **Kazanç:** Modelin kopyalaması gereken **tek** şey `[[BR]]`; tag'ler ve satır sonları tamamen programın elinde. Model belirteç düşürse bile artık yeniden denenir.
- **Doğrulama:** Bekliyor — kullanıcı yeniden çeviri deneyecek; testler yeniden koşulacak.

### F10. `[[BR]]` işareti de kırılgandı → tag'ler modele hiç gitmez (cue tek ID)
- [x] **Durum:** Bitti
- **Sorun/bağlam:** F9'da tag'ler metinden çıkarıldı ama görünür parçalar modele `[[BR]]` ile birleştirilerek gönderiliyordu. Gerçek çalıştırmada model bazı partilerde `[[BR]]`'yi düşürdü (`metin parcasi sayisi beklenenle uyusmuyor (beklenen 2, bulunan 1)`). Yani modelin kopyalaması gereken her işaret kırılgan çıkıyordu.
- **Karar:** Modelin kopyalaması gereken **hiçbir** özel işaret kalmamalı. Ancak parçaları ayrı ID yapmak da yanlış: `\N` cümle ortasından bölünebilir (`All except the\N"Bridge of the Ancients"`), ayrı çevrilirse bozuk Türkçe çıkar. Doğru tasarım: **her cue tek ID** (cümle bütünlüğü korunur), tag'ler metinden çıkarılır, satır sonları korunur.
- **Yapıldı (2026-09-19):**
  - `subtitle.analyze(text)`: cue metnini satırlara (`_LINE_BREAK` = `\N`/`\n`/`\h`/gerçek satır sonu) ve her satırı **baş tag'leri + görünür metin + son tag'leri** olarak ayırır. Satır ortasındaki tag'ler (`C{\fs38}L...` gibi karakter bazlı efektler) düşürülür ve `dropped_tags` ile sayılır (uyarı loglanır).
  - `subtitle.send_text(analysis)`: görünür satırları **gerçek yeni satırla** birleştirir; model cue'yu bütün olarak görür, satır sonlarını doğal biçimde korur.
  - `subtitle.rebuild(analysis, translated)`: ceviri satır sayısı kaynakla uyuşmazsa anlamlı `ValueError`; uyuşursa baş/son tag'ler ve satır sonları **program tarafından** geri kurulur.
  - `[[BR]]` ve `[[T#]]` kavramları **tamamen kaldırıldı**; `Cue.text` artık `\n` ile birleştirir.
  - `app_core.TranslationEngine`: `_request_texts` (her cue tek ID), `_fix_texts` (glossary düzeltmesi), `_assemble` (cue iskeletini geri kurar). `_retry` **tüm** parti denemesini sarar; yapısal hatalar da yeniden denenir.
  - `translation_prompt.txt`: `[[BR]]`/`[[T#]]` kuralları kaldırıldı; modele `{`/`}` veya backslash tag üretmemesi ve her girdinin tek ekran satırı olması söyleniyor.
  - `tests/test_core.py`: `analyze`/`send_text`/`rebuild`/`dropped_tags` testleri; `Cue.text` artık `\n` kullandığı için ilgili testler güncellendi.
- **Kazanç:** Model yalnızca ID/TEXT biçimini korur; tag'ler ve satır sonları tamamen programın elinde. Model belirteç düşürse bile `_retry` devreye girer.
- **Not:** Satır ortasındaki karakter bazlı tag'ler (nadir, ör. `CLEVATESS` başlığı) korunmaz ve loglanır — çeviri kelime sırasını değiştirdiği için bunları güvenle taşımak mümkün değil.
- **Doğrulama:** Bekliyor — kullanıcı yeniden çeviri deneyecek; testler yeniden koşulacak.

### F11. Model çok satırlı cue'yu tek satıra indiriyor → hoşgörülü yeniden bölme
- [x] **Durum:** Bitti ve doğrulandı
- **Sorun/bağlam:** F10 sonrası tasarım: her cue tek ID olarak gönderiliyor, tag'ler metinden çıkarılıyor, satır sonları (`\N`) modele gerçek yeni satır olarak veriliyor. Gerçek çalıştırmada partiler 1-4 geçti, sonra:
  ```
  Yapisal altyazi isaretleri korunmadi: satir sayisi beklenenle uyusmuyor (beklenen 2, bulunan 1).
  ```
  Yani model, iki satırlık bir cue'yu (`...\N...`) tek satırda birleştirip döndürdü. `_retry` 3 deneme yaptı ama model her seferinde birleştirdiği için kalıcı hata.
- **Log kanıtı (2026-09-19):**
  - `UYARI: satir ortasinda 8 ASS tag cikarildi (karakter bazli efekt); bunlar ceviriye girmez.` (parti 1 — `CLEVATESS` başlığı; beklenen davranış, F10'da belgelendi)
  - `UYARI: satir ortasinda 1 ASS tag cikarildi ...` (parti 4)
  - `Yapisal altyazi isaretleri korunmadi: satir sayisi beklenenle uyusmuyor (beklenen 2, bulunan 1).`
- **Karar:** Çözüm yönü 1 uygulandı (hoşgörülü yeniden bölme). Yön 3 (her satır ayrı ID) F10'da reddedilmişti — `\N` cümle ortasından bölünebildiği için korunur. Yön 2 (prompt zorlaması) tek başına güvenilir değil; yine de prompt iyileştirildi.
- **Yapıldı (2026-09-19):**
  - `subtitle.py`: yeni `_reflow(text, weights)` — çeviri kelimeleri, kaynak satırların görünür uzunluk oranlarına göre **kelime sınırında** satırlara dağıtılır (kelime asla bölünmez). Ceviri kelime sayısı dolu satır sayısından azsa kelimeler sırayla doldurulur, kalan satırlar boş kalır.
  - `subtitle.rebuild(analysis, translated, note=None)`: satır sayısı uyuşmazlığında artık `ValueError` **vermez**; `_reflow` ile kaynak satır sayısına yeniden böler ve `note(beklenen, bulunan)` geri çağrısını tetikler. Tag'ler ve satır sonları her durumda program tarafından geri kurulur. Fazla satır (kaynak 1, ceviri 2+) da tek satıra indirilir.
  - `app_core.TranslationEngine._assemble`: `@staticmethod` kaldırıldı; `rebuild`'e `note=self._note_reflow` geçirilir. Yeni `_note_reflow` modelin satır sayısını bozduğunu loglar (`BILGI: model satir sayisini degistirdi ... yeniden bolundu.`).
  - `translation_prompt.txt`: "Each entry is one screen line; do not add line breaks inside an entry." kuralı düzeltildi → "If a source entry contains line breaks, keep exactly the same number of line breaks in its translation; if it has none, do not add any." (F10 tasarımıyla çelişen eski kural kaldırıldı).
  - `tests/test_core.py`: `test_rebuild_detects_line_count_change` kaldırıldı; yerine `test_rebuild_reflows_merged_multiline_translation`, `test_rebuild_collapses_extra_lines_to_source_count`, `test_rebuild_reports_line_count_change`, `test_rebuild_collapses_extra_lines_for_single_line_cue`, `test_rebuild_keeps_exact_line_count_untouched` ve motor seviyesinde `test_translate_reflows_merged_multiline_cue` eklendi.
- **Kazanç:** Modelin satır sayısını bozması artık kalıcı hata üretmez; çıktı her zaman kaynak yapıyı korur. `_retry`'nin boşa dönmesi sorunu ortadan kalkar (hata yerine düzeltme).
- **Notlar:**
  - `_reflow` oranları kaynak **karakter uzunluğuna** göre hesaplar; çok kısa/çok uzun satırlarda bölme noktası yaklaşıktır ama her zaman kelime sınırındadır.
  - `validate_structure` (sert denetim) korunur; SRT/VTT/ASS round-trip testlerinde yapisal guvenlik agi olarak kullanilir. Motor akisi artik bu sert denetime dayanmaz (rebuild yapiyi garanti eder), boylece model kaynakli uyusmazlik kalici hata yerine duzeltilir.
  - `re.split` yakalama grubu bug'ı F10 sonunda düzeltilmişti (`_ASS_SPLIT`).
- **Doğrulama (TAMAM, 2026-09-19):** Kullanıcı tarafında koşuldu. `test-cikti/` klasöründe kanıtlar:
  - `test sonucu.txt`: **62/62 test `OK`** (`Ran 62 tests in 0.131s`).
  - `programdaki log.txt`: 38/38 parti tamamlandı, `Ceviri yazildi: ..._TR.ass`; hata yok. 15+ kez `BILGI: model satir sayisini degistirdi (beklenen 2, bulunan 1); ... yeniden bolundu.` → `_reflow` beklendiği gibi devreye girdi. Fazla satır (`beklenen 1, bulunan 2`) veya sahte parantez UYARI'sı **yok**.
  - Kaynak `.ass` ↔ `_TR.ass` karşılaştırması: `[Script Info]`/`[V4+ Styles]`/`[Aegisub Project Garbage]` blokları birebir; Dialogue satır sayısı/sırası korunmuş; tüm `\N` satır sonları ve override tag'leri (`{\an7...}`, `{\fad(1375,0)...}`, `{\fs24}`, `{\fs30}`) korunmuş. Örnek: `Reigning Sword Saint\N{\fs24}Owen Koath` → `Hüküm Süren Kılıç Azizi\N{\fs24}Owen Koath` (kelime sınırında, oranlı bölme).
  - `LM studio logs.txt`: `chat_template_kwargs: {enable_thinking:false}` gönderiliyor, `reasoning_tokens: 0` → thinking kapalı çalışıyor.
  - **Not (F11 dışı):** `CLEVATESS` başlığındaki satır ortası karakter-bazlı tag'ler F10'da belgelendiği gibi düşürülmüş; `durduğumın` gibi model kaynaklı yazım hataları var (kalite, yapı değil).

### F4. Paketleme ve belgeler
- [x] **Durum:** Bitti
- [x] Tek dosyalı `.exe` (ffmpeg/ffprobe gömülü) — Windows
- [x] `README.md`
- [x] `KULLANIM.md`
- **Yapıldı (2026-09-19):**
  - `README.md`: kısa tanım, öne çıkan özellikler, gereksinimler (Python/PySide6/FFmpeg/LM Studio), hızlı başlangıç, komut satırı örnekleri, sınırlamalar, gizlilik özeti, MIT lisans bağlantısı. Ekran görüntüsü için `docs/screenshot.png` yeri ayrıldı (henüz eklenmedi).
  - `KULLANIM.md`: kurulum (kaynak kod + `bin\` ikilileri + LM Studio), `config.json` alan tablosu, arayüz akışı (video açma, stream tablosu sütunları, çıkar/çevir), glossary (denetim + Türkçe çekim toleransı + çakışma kuralı), seri desteği, 7 maddelik sorun giderme (boş yanıt/thinking, checkpoint uyuşmazlığı, yeniden bölme bilgisi, görüntü tabanlı altyazı, dosya kilidi, yazma izni), komut satırı ve gizlilik.
  - `DERLE.cmd`: PyInstaller `--onefile --windowed` ile tek dosya `.exe`; `bin` (ffmpeg/ffprobe), `config.json`, `translation_prompt.txt` pakete gömülür. `bin\` ikilileri yoksa anlamlı hata verip durur.
- **Doğrulama (TAMAM, 2026-09-19):** Belgeler yazıldı ve `.exe` derlemesi (`DERLE.cmd`) kullanıcı tarafında **çalıştı**; uygulama çalışıyor. Derleme betiği: PyInstaller `--onefile --windowed`; `bin` (ffmpeg/ffprobe), `config.json`, `translation_prompt.txt` pakete gömülür. `bin\` ikilileri yoksa anlamlı hata verip durur.

### F12. F11 sonrası doğrulama ve devam
- [x] **Durum:** Bitti
- [x] `py -3 -m unittest discover -s tests -v` koşusu — **62/62 `OK`** (2026-09-19, kullanıcı tarafında)
- [x] Gerçek çeviri (Clevatess S2 bölümü) — 38/38 parti tamamlandı, çok satırlı cue'lar hatasız; log'da `BILGI: model satir sayisini degistirdi ...` görüldü ve yapı korundu
- [x] Kalan bekleyen kararlar (§5, madde 4-6) kullanıcı onayı — **onaylandı (2026-09-19)**
- **Yapıldı (2026-09-19):** Kanıtlar `test-cikti/` klasöründe: `test sonucu.txt` (62 `OK`), `programdaki log.txt` (38/38 parti), kaynak/çeviri `.ass` ve `LM studio logs.txt`. Yapısal karşılaştırma temiz; F11 doğrulandı.

### F13. Arayüz yenileme (mockup → uygulama)
- [x] **Durum:** Bitti ve doğrulandı
- [x] `test-cikti/mockup/` içine 3 HTML varyasyonu (PySide6 kabiliyetleri içinde)
- [x] Seçilen varyasyonu (mockup-2) `gui.py`'ye uygula (butonlar gruplanır, stream tablosu iç içe geçmez)
- [x] **Tek eylem: "Çevir" butonu** — çıkarma işini de arka planda yapar (çıkar → otomatik çeviri); basıldıktan sonra **pasif** (disabled) olur
- [x] **Ön analiz** — Çevir'in **solunda ticklenebilir** seçenek (checkbox), araç çubuğunda değil
- [x] Stream tablosunda **seçim tick ile** (satır vurgusu yerine ilk sütunda checkbox; tek akış seçilebilir)
- [x] Konsol ekranda görünmeye devam eder; sürükle-bırak korunur
- [x] Üst araç çubuğunda seri yanındaki düğme adı **"Terim"** (kullanıcı isteği)
- **Yapıldı (2026-09-19):** `test-cikti/mockup/` altına 3 varyasyon yazıldı (yan panel / üst araç çubuğu / adım kartları); her mockup başında PySide6 karşılığı yorum olarak belgelendi.
- **Yapıldı (2026-09-19, mockup-2 v2 — kullanıcı geri bildirimi):** Ön analiz araç çubuğundan çıkarıldı → Çevir'in solunda ticklenebilir seçenek; buton adı **"Çevir"**, basınca **pasif**; stream seçimi **ilk sütundaki checkbox** ile (tek seçim, görüntü tabanlı akış devre dışı); "Sözlük" → **"Terim"**.
- **Yapıldı (2026-09-19, `gui.py` uygulaması):**
  - **`gui.py` baştan yazıldı** (mockup-2 v2): `QToolBar` (Dosya: Video/Klasör Sec — Seri: dropdown/**Terim**), ortada `DropArea` + checkbox'lı akış tablosu, işlem satırı (`Bölüm terimleri...` / `On analiz yap` tick / **`Çevir`** / `Duraklat` / ilerleme), altta `QDockWidget` + `QTabWidget` (**Konsol** / **Ön Analiz**).
  - **Tek eylem zinciri:** yeni `RunWorker` — önce `extract_subtitle`, sonra (tick ise) ön analiz, sonra `TranslationEngine`. Çıkarma bitmeden çeviri başlamaz. Buton iş boyunca **pasif**; bitince yeniden etkinleşir. Eski `ExtractWorker`/`TranslateWorker` ayrımı kaldırıldı.
  - **Akış tablosu:** `QTableWidget` ilk sütununda checkbox (`ItemIsUserCheckable`); `on_item_changed` tek seçim sağlar; görüntü tabanlı/desteklenmeyen akışların kutusu devre dışı. Satır seçim vurgusu kaldırıldı.
  - **Duraklat** düğmesi arayüze eklendi (kod hazır bekliyordu); `PauseController` üzerinden çalışır.
  - **Ön analiz:** `analysis_check` tick'liyse `RunWorker` `app_core.candidate_terms` ile aday terimleri çıkarır, "Ön Analiz" sekmesine yazar ve **`GlossaryReviewDialog`** onay diyaloğunu açar (F14 madde 6).
  - `app_core.candidate_terms` + `tests/test_core.py` `CandidateTermTests` (4 test) eklendi.
  - `start_run` içindeki hatalı `series.merge_glossaries` çağrısı → `app_core.merge_glossaries` olarak düzeltildi (latent bug).
- **Doğrulama (TAMAM, 2026-09-19):** `py -3 -m unittest discover -s tests -v` → **67/67 `OK`** (kullanıcı tarafında). Kullanıcı `GUI_BASLAT.cmd` ile denedi: yeni düzen düzgün çalışıyor, **Çevir** basınca buton pasifleşiyor, çıkarma + çeviri zinciri ilerliyor.

### F14. §5 madde 5-6 kod uygulaması (Türkçe kaynak uyarısı + seri terim deposu)
- [ ] **Durum:** Kısmen bitti — **madde 6 tamam ve doğrulandı**; madde 5 bekliyor
- [ ] Madde 5: kaynak Türkçe ise satır-bazlı tespit → UYARI logu + durum rozeti; çeviri engellenmez
- [x] Madde 6: ön analiz aday terimleri → **onay diyaloğu** ile seri glossary'sine yazılır; sonraki bölüm oradan referans alır (depo: `series/<slug>.json`)
- **Yapıldı (2026-09-19):** `app_core.candidate_terms` (aday terim tarayıcı). `gui.py`: "On analiz yap" tick'liyse `RunWorker` önce altyazıyı çıkarır, adayları çıkarır, `review_requested` sinyaliyle ana thread'de **`GlossaryReviewDialog`** açar (mevcut seri terimleri korunur, öneriler işaretli gelir); worker onayı bekler (`threading.Event`). Onaylanan terimler seri sözlüğüne yazılır ve bu çeviride de uygulanır.
- **Doğrulama (TAMAM, 2026-09-19):** Kullanıcı GUI'de ön analiz → terim onay diyaloğu akışını denedi; çalışıyor. `CandidateTermTests` (4 test) 67/67 içinde `OK`.
- **Bekleyen (madde 5):** kaynak altyazı zaten Türkçe ise satır-bazlı tespit + UYARI logu; çeviri engellenmez. Henüz kod yazılmadı.

### F15. Ayarlar penceresi + Katı sözlük davranışı (Cevirgeç deseni)
- [x] **Durum:** Bitti ve doğrulandı
- [x] Programın **sağ üstünde** `Ayarlar` düğmesi (`QToolBar` spacer ile sağa yaslı)
- [x] **Base URL** ve **Model** alanları (model dropdown + elle yazılabilir + "Yüklü modelleri sorgula")
- [x] **Katı sözlük** (`glossary_strict`) ve **Otomatik tekrar sayısı** (`auto_retry_count`) alanları
- [x] Ek: parti boyutu, thinking kapat, max_tokens, timeout, temperature + "Varsayılan ayarlara dön"
- [x] Çeviri sürerken model/bağlantı alanları kilitlenir (Cevirgeç G43 deseni)
- **Yapıldı (2026-09-19):**
  - `gui.py`: `SettingsDialog` (Cevirgeç `SettingsDialog` uyarlaması). Kaydet → `validate_config` + `save_json(APP_DIR/config.json)`. `MainWindow.show_settings` + `refresh_loaded_models` (arka planda `Client.models()`).
  - `app_core.TranslationEngine._translate_batch`: `glossary_strict` artık gerçekten uygulanıyor — **açıkken** eksik glossary terimi kalıcı `ValueError`; **kapalıyken** (varsayılan) `UYARI: glossary zorunlulugu saglanamadi (kati sozluk kapali); ceviri devam ediyor: ...` loglanır ve çeviri sürer.
  - `tests/test_core.py`: `test_glossary_still_missing_raises_when_strict`, `test_glossary_missing_continues_when_not_strict` (eski `test_glossary_still_missing_raises` yerine).
- **Doğrulama (TAMAM, 2026-09-19):** `py -3 -m unittest discover -s tests -v` → **67/67 `OK`** (`test_glossary_still_missing_raises_when_strict`, `test_glossary_missing_continues_when_not_strict` dahil). Kullanıcı GUI'de **Ayarlar** penceresini (sağ üstte) denedi; çalışıyor.

### F16. Kurumsal tema (koyu + neon lime) ve logo/simge
- [x] **Durum:** Bitti ve doğrulandı
- [x] Tema sözlüğü + QSS şablonu (`.format()` ile enjeksiyon)
- [x] Araç çubuğu markası: logo + küçük harf `aktar` + `#c8ff00` nokta
- [x] `.exe` simgesi (`--icon`) ve pencere simgesi
- **Yapıldı (2026-09-19):**
  - `gui.py`: `STYLE` kaldırıldı → `THEME` sözlüğü + `STYLE_TEMPLATE`; `build_style()` font tespiti (`QFontDatabase`) ve onay işareti yolunu (`assets/check-lime.svg`) enjekte eder. Renkler tek yerde; tema değiştirmek için yalnızca `THEME` güncellenir.
  - Renk şeması uygulandı: `bg #03080a`, `chrome #080d0f`, `panel #0c1113`, `border #1a2226`, `panel_alt #101719`, `text #e6edee`, `secondary #9aabaf`, `muted #6f8085`, `accent #c8ff00`, `accent_text #0a1200`, `disabled #54666b`, `drop_border #243035`.
  - Vurgu kuralı: accent yalnızca `QPushButton#primary` (Çevir), `QTabBar::tab:selected` alt çizgisi, tablo onay işareti (indicator) ve `QProgressBar::chunk`'ta. `primary:disabled` accent'i bırakıp panele döner.
  - Butonlar 6px köşe + 1px kenarlık + panel zemini; hover `panel_alt`; disabled metin `#54666b`. Sürükle-bırak alanı 1px dashed `#243035`, 8px köşe, monospace. Tablo: grid kapalı (`setShowGrid(False)`), satır yüksekliği 34px, başlık `panel_alt` + 12px ikincil renk.
  - Yazı tipi: `IBM Plex Sans` (yoksa `Segoe UI`), gövde 14px; dosya yolu/monospace alanlarda `IBM Plex Mono` (yoksa `Consolas`) 13px.
  - **Marka:** araç çubuğunun en solunda `_brand_pixmap(22)` ile logo, ardından küçük harf `aktar` ve `#c8ff00` nokta. Sürükle-bırak alanının altına `QLabel#filePath` (monospace) ile tam yol.
  - **Logo varlıkları:** `assets/aktar-icon.svg` (C2PA metadata'sı temizlenmiş, `#0c1113` zemin + `#e6edee` gövde + `#c8ff00` ok), `assets/check-lime.svg` (onay işareti). PNG/ICO kopyalanmadı; `asset_path()` önce PNG/ICO, yoksa SVG'yi `QSvgRenderer` ile çizer, bu yüzden eksik dosya hata vermez.
  - `DERLE.cmd`: `--icon assets\aktar.ico` (yoksa uyarı verip simgesiz derler) + `--add-data "assets;assets"`.
  - `Aktar.spec`: **`DERLE.cmd` çalıştırıldığında PyInstaller bu dosyayı kendisi yeniden üretir** (elle düzenlemeler ezilir). Üretilen spec'te `icon=['assets\\aktar.ico']` ve `datas` içinde `assets` görünür.
  - **Kanıt (2026-09-19):** `build\Aktar\EXE-00.toc` içinde ikon listesi `['Z:\\LLM-Files\\Projects\\Aktar\\assets\\aktar.ico']` → simge `.exe`'ye **gömüldü**. Görev çubuğu/pencere simgesi (`setWindowIcon`) doğru; **Explorer'daki dosya simgesi eski görünüyorsa bu Windows ikon önbelleğidir** (aynı yol `dist\Aktar.exe` yeniden derlendiği için eski simge önbellekte kalır). Çözüm: exe'yi yeni adla kopyalayıp bakmak veya ikon önbelleğini temizlemek.
  - **Gecici klasor temizligi (2026-09-19):** `asset_path` artık `test-cikti/export`'a bakmaz; yalnızca `APP_DIR/assets` (exe yanı) ve pakete gömülü `assets/` (ROOT). Kullanıcı tüm logo varlıklarını `assets\` içine taşıdı (`aktar-icon-256.png`, `aktar-icon-512.png`, `aktar.ico`, `aktar-icon.svg`, `check-lime.svg`).
- **Uygulanamayan istekler (QSS sınırı):** animasyonlu `transition`, `box-shadow`/dış parlama, gradient ve **native başlık çubuğu** rengi QSS ile yapılamaz. Başlık çubuğu yerine iç `QToolBar` şeridi `chrome` rengine boyandı.
- **Doğrulama (TAMAM, 2026-09-19):** `py -3 -m unittest discover -s tests -v` → **67/67 `OK`** (kullanıcı tarafında). Kullanıcı yeni temayı ve araç çubuğu markasını onayladı ("arayüz iyi"). `DERLE.cmd` ile derlenen `dist\Aktar.exe` simgesi doğrulandı: ilk bakışta eski PyInstaller simgesi görünmesi **Windows ikon önbelleği** kaynaklıydı; exe yeni adla kopyalanınca doğru simge çıktı (kanıt: `build\Aktar\EXE-00.toc` ikon listesinde `assets\aktar.ico`).

### F17. Gerçek ASS regresyonları + görünür metin normalizasyonu
- [x] **Durum:** Bitti ve otomatik doğrulandı
- [x] Kullanıcının verdiği `Clevatess S2 - 01v2` ve `Ryoumin ... - 06` tam ASS dosyaları test koşusuna bağlandı; `tests/fixtures/` içinde iki küçük kalıcı regresyon örneği bulunur.
- [x] Parse → görünür metin → sahte LLM çeviri montajı → render zincirinde yapı ve override tag'leri korunuyor.
- [x] `\\N`/`\\n`/`\\h` ve override tag'leri analiz metnine girmiyor; `Nand`, `Nthe`, `Nfor` gibi sahte adaylar oluşmuyor.
- [x] Satır ortası karakter efektleri düşürülmüyor; modelden uzak tutulup çevrilmiş metindeki oransal konumlarına geri yerleştiriliyor.

### F18. LLM tabanlı ön analiz + Türkçe terim önerileri
- [x] **Durum:** Kodlandı; gerçek LM Studio/GUI kullanıcı testi bekliyor
- [x] Görünür altyazı `analysis_chunk_chars` sınırıyla parçalara ayrılıp modele gönderiliyor.
- [x] JSON şeması: `terms[{source,target,type,reason}]` ve `decisions[{type,value,reason}]`; kullanım sayısı program tarafından hesaplanıyor.
- [x] Kaynakta bulunmayan, hedefi boş veya mevcut glossary'de olan öneriler eleniyor.
- [x] Onay tablosu: **Ekle | Kaynak | Türkçe önerisi | Tür | Gerekçe | Kullanım | Kapsam**; hedef düzenlenebilir.
- [x] Kapsam **Seriye ekle / Yalnız bu bölüm**; ön analiz onayı çeviri başlamadan etkinleşiyor.
- [x] Analiz parçaları ayrı checkpoint'e yazılıyor.

### F19. Çeviri sonrası terim ve continuity toplama
- [x] **Durum:** Kodlandı; gerçek LM Studio/GUI kullanıcı testi bekliyor
- [x] Ön analiz kapalı olsa bile hizalı kaynak + Türkçe cue çiftleri çeviri sonunda inceleniyor.
- [x] Kaynak terimin kaynakta, hedefin gerçek çeviride bulunduğu doğrulanıyor; uydurulmuş çiftler eleniyor.
- [x] İkinci onay penceresinde terim ve continuity kapsamı seçiliyor; kullanıcı onayı olmadan seri dosyasına yazılmıyor.

### F20. Bölüm içi tutarlılık + zengin seri verisi
- [x] **Durum:** Kodlandı; gerçek LM Studio/GUI kullanıcı testi bekliyor
- [x] Çeviri sonunda onaylanan hedef, aynı kaynak terimin geçtiği fakat hedefin bulunmadığı cue'lara ayrı düzeltme isteğiyle uygulanıyor; yalnız etkilenen cue'lar değişiyor.
- [x] Glossary ile continuity ayrıldı; seri terimleri `type`, `origin`, `first_seen`, `locked` alanlarını taşıyor.
- [x] Araç çubuğundaki **Süreklilik** düğmesi `decisions` listesini görüntülüyor ve düzenliyor.

### F21. Güvenli seri eşleştirme
- [x] **Durum:** Kodlandı ve otomatik doğrulandı
- [x] `qbit`, `downloads`, `video`, `anime`, `tv` ve sezon klasörleri otomatik ipucu olmuyor.
- [x] Birden fazla eşleşmede kullanıcı seçim yapıyor; elle seçilmiş seri otomatik öneriden üstün.
- [x] Fansub köşeli parantezleri, bölüm/sezon ve kalite ekleri temizlenerek yeni seri başlığı öneriliyor.

### F22. Ön analizden sonra inceleme penceresinin açılmaması
- [x] **Durum:** Düzeltildi ve otomatik sözleşme testi eklendi
- [x] **Kök neden:** `handle_review`, `GlossaryReviewDialog` sınıfına `decisions` ve `has_series` gönderiyordu; pakette kalan eski sınıf imzası bu alanları kabul etmeyip ana GUI thread'inde `TypeError` oluşturuyordu. Worker ise inceleme onay olayını beklemeyi sürdürdüğü için program durmuş görünüyordu ve LM Studio'ya yeni istek gitmiyordu.
- [x] İnceleme penceresi terim ve süreklilik sekmeleriyle yenilendi; Türkçe karşılık düzenlenebilir, her satır seçilebilir ve **Seriye ekle / Yalnız bu bölüm** kapsamı atanabilir.
- [x] `handle_review` artık `finally` bloğunda bekleyen worker'ı her durumda serbest bırakır; ilerideki bir arayüz hatası çeviriyi sessizce sonsuza kadar kilitlemez, konsola ve uyarı penceresine açık hata yazar.
- [x] `tests/test_gui_contract.py`, pencere kurucu imzası ile çağrının uyumunu ve bekleme olayının `finally` içinde bırakılmasını PySide6 gerektirmeden doğrular.

### F23. Arayüz sadeleştirme, tamamlanma bildirimi ve Türkçe karakterler
- [x] **Durum:** Kodlandı ve otomatik sözleşme testleri eklendi
- [x] Toplu seçim yapmadığı ve **Video Seç** ile aynı işi tekrarladığı için **Klasör Seç** düğmesi, sinyal bağlantısı ve GUI metodu kaldırıldı.
- [x] Başarılı çeviri sonunda çıktı yolunu gösteren **Çeviri tamamlandı** penceresi açılıyor; pencere uygulama simgesini, koyu temayı ve lime birincil düğmeyi kullanıyor.
- [x] Düğmeler, tablo başlıkları, araç ipuçları, analiz pencereleri, uyarılar ve konsolda gösterilen çekirdek mesajlar Türkçe karakterlerle düzeltildi.
- [x] Çeviri sürerken Ayarlar ekranındaki metin/sayı alanları salt okunur; açılır liste ve checkbox'lar devre dışı, Kaydet/varsayılana dön/model sorgulama işlemleri kilitli. Ekranda salt okunur durumu açıklanıyor.
- [x] `tests/test_gui_contract.py` klasör seçiminin kaldırılmasını, tamamlanma penceresini, çeviri sırasındaki kilidi ve temel Türkçe etiketleri doğruluyor.

### F24. Arayüz tazeleme (kart yüzeyleri, Fusion, ikonlar, toast) — palet sabit
- [x] **Durum:** Kodlandı ve otomatik sözleşme testleri eklendi; gerçek Windows GUI/`.exe` doğrulaması bekliyor
- [x] **Palet değişmedi.** `THEME` renk anahtarlarının tamamı F16'daki değerleriyle duruyor; yalnızca lime'ın düşük opaklıklı iki türevi (`accent_soft` = `rgba(200,255,0,0.12)`, `accent_edge` = `rgba(200,255,0,0.28)`) ve ölçü anahtarları (`radius`, `radius_small`) eklendi. `tests/test_gui_contract.test_theme_palette_is_unchanged` on iki rengi kilitler.
- [x] **Fusion stili zorunlu.** `main()` içinde `app.setStyleSheet` öncesinde `app.setStyle('Fusion')`. Windows'un yerel stili QSS'in bir kısmını (spinbox, combobox oku, `QTableWidget::indicator`, progress köşesi) yok sayıyordu; Fusion ile aynı sonuç her platformda alınır.
- [x] **Native başlık çubuğu koyulaştırıldı.** Yeni `apply_window_chrome(widget)` `MainWindow.showEvent`'te çağrılır; `ctypes` ile DWM özniteliği 20 (`IMMERSIVE_DARK_MODE`) ve 33 (`CORNER_PREFERENCE = ROUND`) set edilir. Windows dışında ve çağrı başarısız olduğunda sessizce atlanır — F16'daki "QSS başlık çubuğuna erişemez" sınırı böylece aşıldı.
- [x] **Kart yüzeyleri.** `card()` yardımcısı `QFrame#card` (12px köşe + 1px kenarlık + `panel` zemin) üretir ve `add_shadow()` ile `QGraphicsDropShadowEffect` bağlar (QSS'te `box-shadow` yok). Dosya kartı, akış tablosu kartı, işlem kartı ve konsol kartı bu yüzeyleri kullanır.
- [x] **`QDockWidget` → `QSplitter`.** Alt panelin başlık çubuğu kalktı; konsol/ön analiz sekmeleri ince tutamaklı dikey `QSplitter` ile boyutlandırılıyor (`setSizes([520, 220])`, `setChildrenCollapsible(False)`).
- [x] **İkon seti.** `assets/icons/` altına 12 tek renkli SVG (`video`, `terms`, `continuity`, `settings`, `pause`, `play`, `translate`, `trash`, `upload`, `refresh`, `film`, `check`). Yeni `tinted_icon(name, color, size)` SVG'yi `QSvgRenderer` ile çizip `CompositionMode_SourceIn` ile tema rengine boyar; böylece tek set hem normal hem soluk hem accent durumda kullanılır. 2x çizim + `setDevicePixelRatio(2)` ile HiDPI'de bulanıklaşmaz. Sözleşme testi her `tinted_icon('...')` çağrısı için dosyanın varlığını denetler.
- [x] **Anahtar (toggle).** `ToggleSwitch(QCheckBox)` — gösterim `paintEvent`'te çizilir, geçiş `QVariantAnimation` ile yumuşar; `isChecked()`/sinyaller değişmediği için `start_run` tarafında hiçbir uyarlama gerekmedi. "Ön analiz yap" bu anahtarı kullanır.
- [x] **Boş durum ekranı.** `DropArea` artık `QLabel` değil `QFrame`: ikon + başlık + desteklenen uzantı rozetleri + salt-okunur notu. Sürüklerken kesikli kenarlık accent'e döner. Video açılınca `_show_empty_state(False)` ile bırakma alanı gizlenip **dosya kartı** (ad + klasör yolu + "Değiştir") ve akış tablosu görünür.
- [x] **Toast bildirimi.** Başarılı çeviri artık modal kutu açmaz; `Toast` sınıfı pencerenin sağ altında `QGraphicsOpacityEffect` + `QPropertyAnimation` ile belirip 6 saniyede kaybolur. **Uyarı/hata yolu değişmedi** — `warn()` hâlâ `_message_box` (lime `primary` düğmeli, temalı `QMessageBox`) kullanır.
- [x] **Durum rozeti.** Araç çubuğunun sağında `QLabel#statusPill`: model adı + host. Arka plandaki `refresh_loaded_models` sorgusu yeni `status_ready = Signal(str, bool)` ile ana thread'e döner (worker thread'den doğrudan widget'a dokunulmaz).
- [x] **Diğer cilalar:** ilerleme çubuğu 8px yuvarlak dolgu ve `QVariantAnimation` ile yumuşak geçiş; duraklat düğmesi metin yerine `play`/`pause` ikonu + araç ipucu; çeviri sürerken birincil düğme "Çevriliyor" yazıp `accent_soft` zemine düşer; tablo satır yüksekliği 34→40, odak çerçevesi kapalı, satır üstü hover ve desteklenen akış için lime durum metni; özel ince `QScrollBar`; `QLabel { background:transparent }` küresel kuralı sayesinde kart içi etiketler için ayrı sıfırlama gerekmiyor.
- [x] **Tema dışı kalan son inline stiller temizlendi:** `SettingsDialog.model_hint` (`color:#8b95a4; font-size:8pt;`) → `QLabel#hint`; eski `font-weight:600` / `9pt` etiket stilleri `QLabel#cardTitle` ve `QLabel#hint`e taşındı. Kalan `setStyleSheet` çağrıları yalnızca `THEME` değerlerini kullanan dinamik durumlar (sürükleme vurgusu, rozet zemini).
- **Yapıldı (2026-09-19):** `gui.py` (tema anahtarları, QSS şablonu, `tinted_icon`/`apply_window_chrome`/`add_shadow`/`card`/`section_label`, `ToggleSwitch`, `Toast`, `DropArea`, `MainWindow._build`/`_build_file_card`/`_build_stream_card`/`_build_action_card`/`_build_console`/`_build_toolbar`/`_show_empty_state`/`_set_status`/`_set_pause_button`, `showEvent`/`resizeEvent`, `update_progress`, `complete`, `main`), `assets/icons/*.svg` (12 yeni dosya), `tests/test_gui_contract.py` (7 yeni test).
- **Doğrulama (2026-09-19):** `python -m unittest discover -s tests` → **92/92 `OK`**; `py_compile` temiz. Ayrıca bu ortamda PySide6 kurulup **offscreen** (`QT_QPA_PLATFORM=offscreen`) açılış denendi: boş durum ve çeviri-sürüyor ekranları hatasız çizildi, `SettingsDialog` açıldı, `complete()` toast'ı tetikledi. **Kullanıcı tarafında bekleyen:** gerçek Windows'ta başlık çubuğu rengi/köşesi ve `DERLE.cmd` sonrası `.exe` içinde `assets\icons` ikonlarının görünmesi.
- **Not:** `DERLE.cmd` zaten `--add-data "assets;assets"` kullandığı için `assets\icons` alt klasörü pakete kendiliğinden girer; ek değişiklik gerekmedi.

- **Toplu doğrulama (2026-09-19):** Kullanıcının iki tam ASS dosyası dahil 92/92 test `OK`; `app_core.py`, `series.py`, `subtitle.py`, `gui.py`, `cevir.py` `py_compile` kontrolünden geçti. Çalışma ortamında PySide6 bulunmadığı için gerçek GUI açılışı burada yapılamadı.

### F25. Arayüz iyileştirmeleri (buton highlight, toggle görünürlük, ayarlar ikonu)
- [x] **Durum:** Kodlandı; kullanıcı testi bekliyor
- [x] QPushButton:hover rengi `#1a2530` olarak belirginleştirildi (`panel_alt #101719` çok silikti)
- [x] ToggleSwitch off durumu track rengi `#1e2a30` (önceki `panel_alt` yerine) → daha görünür
- [x] Ayarlar butonu ikonu inline SVG olarak eklendi (`_settings_svg_icon`) — verdiğiniz dişli ikonu
- [x] "Çevir" butonunun solundaki translate ikonu kaldırıldı (yalnızca metin: **Çevir**)
- **Yapıldı (2026-09-19):** `gui.py` → QSS hover rengi, ToggleSwitch paintEvent off track rengi, `_settings_svg_icon()` fonksiyonu eklendi, `translate_button.setIcon(...)` satırı silindi.

### F26. Çalışma dosyaları APP_DIR/work_files/ altına taşındı
- [x] **Durum:** Bitti ve doğrulandı (TARİH)
- `gui.py` `RunWorker.__init__()` → `self.work_dir = APP_DIR / 'work_files'` eklendi
- `gui.py` `RunWorker.run()` → kaynak altyazı, checkpoint, ön analiz ve çeviri sonu analizi dosyaları artık `APP_DIR/work_files/` altında
- Çeviri çıktı dosyaları (`.srt`, `.ass`) videonun dizininde kalıyor — değişiklik yok
- **Doğrulama:** Kullanıcı GUI'de test etti; `work_files/` altında checkpoint ve kaynak altyazı var, çeviri çıktısı video yanına yazıldı.

### F27. `[EMBER] Sakamoto Days - 12.srt` çevirisinin 28. partide kalıcı durması
- [x] **Durum:** Bitti ve doğrulandı (2026-09-19) — kök neden bulundu, düzeltildi; birim + uçtan uca + gerçek LM Studio/GUI doğrulaması yapıldı
- **Belirti:** SRT kaynağında çeviri 27/32 partiyi geçiyor, **28. partide kalıcı** duruyor:
  `Geçici hata (deneme 1/3): Çeviri kimlikleri: eksik=[2, 3] fazla=[]` (3 deneme de aynı) → `Çeviri kimlikleri: eksik=[2, 3] fazla=[]`.
  Checkpoint kanıtı (`dist\work_files\[EMBER] Sakamoto Days - 12.state.json`): 320 girdiden 270'i (0-269) tamamlanmış.
- **Kök neden:** LM Studio ham yanıtı: model 28. partide **2. ve 3. girdide `TEXT:` etiketini düşürdü** (`ID: 2` satırından sonra doğrudan metin geliyor). `subtitle.parse_translation_response` regex'i `TEXT:` etiketini **zorunlu** sayıyordu; bu yüzden ID 2 ve 3 hiç bulunamıyordu. Yapısal bir ASS/SRT sorunu **değil**; yalnızca ayrıştırıcının biçim katılığı.
- **Yapıldı (2026-09-19):**
  - `subtitle.parse_translation_response`: `TEXT:` etiketi **isteğe bağlı** hale getirildi (`[ \t]*(?:TEXT[ \t]*:[ \t]*)?`). **ID kümesi denetimi aynen korundu**; gerçekten eksik/fazla ID yine anlamlı `ValueError` üretir ve `_retry` çalışır.
  - `tests/test_core.py`: `test_translation_response_allows_dropped_text_label` ve `test_translation_response_dropped_label_multiline_value` eklendi (toplam 94 test).
- **Doğrulama (TAMAM, 2026-09-19):** `python -m unittest discover -s tests` → **94/94 `OK`**. Ayrıca gerçek Sakamoto SRT'siyle, 28. partide ID 2-3'te `TEXT:` düşüren sahte modelle uçtan uca koşu: `TRANSLATE OK -> 320 cue`, `RENDER OK` (düzeltme öncesi aynı senaryo `eksik=[2,3]` ile duruyordu). `TEXT:` etiketi normal geldiğinde ayrıştırma değişmiyor (94 testin tamamı geçti).
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-19):** Gerçek LM Studio + GUI ile **2 `.ass` + 1 `.srt`** (hatayı veren `[EMBER] Sakamoto Days - 12.srt` dahil) çevrildi; **hata alınmadı**, hepsi tamamlandı. Böylece düzeltme gerçek ortamda da doğrulandı ve diğer dosyaların çalışması bozulmadı.

### F29. `S02E18` ikinci varyant: model `ID:` yerine kaynağın kendi liste numaralarını tekrarladı
- [x] **Durum:** Bitti ve otomatik doğrulandı (2026-09-19)
- **Belirti:** F28 sonrası yeniden derlenen sürümle aynı bölüm bu kez **35. partide** kalıcı durdu:
  `Geçici hata (deneme 1/3): Çeviri kimlikleri: eksik=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] fazla=[]` (3 deneme de aynı).
- **Kök neden (LM Studio logu):** 35. parti kaynağı bir **numaralı liste** (bir summoning büyüsünün 3 seçeneği birden çok cue'da tekrarlanıyor): `1. Summon inorganic matter`, `2. Summon organic matter`, `3. Summon an organism...`, sonra yine `1.`, `2.`, `3.` … Model `ID:` etiketlerini düşürüp **kaynak metnin kendi numaralarını ID sandı** ve yanıtı `1,2,3,1,2,3,1,2,3,1` diye numaraladı (10 girdi). F28'in "numaralar beklenen ID dizisiyle birebir örtüşmeli" kuralı bu yüzden reddediyordu.
- **Karar:** Modelin ürettiği **numaraların kendisi güvenilmez** (kaynak metinden gelebilir). Doğru sinyal **sıradır**: model girdileri sırayla ve doğru sayıda döndürür. Bu yüzden numaralar yalnızca "blok başlangıcı" işareti sayılır; ceviriler blok **sırasına** göre `expected_ids` ile eşleşir.
- **Yapıldı (2026-09-19):**
  - `subtitle.parse_translation_response`: `_parse_numbered_response` → `_parse_listed_response` olarak yeniden yazıldı. Artık numara **değerleri karşılaştırılmaz**; yalnızca blok sayısı beklenen ID sayısına eşit olmalıdır. Eşleme sıraya göre yapılır.
  - Yeni `_parse_blank_block_response`: model ne etiket ne numara kullanıp yalnızca beklenen sayıda ceviri bloğunu **bos satırla ayrılmış** döndürürse de sıraya göre eşleşir (sayı eşitliği şartıyla).
  - `_parse_labeled_response` (F28) **öncelikli** kalır: `ID:` etiketi varsa ID'ler açıktır ve o biçim kullanılır.
  - **ID kümesi denetimi korundu:** blok sayısı beklenen sayıya eşit değilse (gerçekten eksik/fazla) yine anlamlı `ValueError` ve `_retry`.
  - `tests/test_core.py`: `test_translation_response_numbered_list_numbering_is_ignored`, `_requires_matching_count`, `test_translation_response_blank_blocks_without_labels_or_numbers`, `_require_matching_count` eklendi; eski "numara değerleri birebir olmalı" testi kaldırıldı (toplam **103** test).
- **Doğrulama (TAMAM, 2026-09-19):**
  - `python -m unittest discover -s tests` → **103/103 `OK`**.
  - **LM Studio'daki gerçek ham yanıt** (F29 logundaki `1,2,3,1,2,3,...`) doğrudan ayrıştırıldı: 10 girdi doğru **sırayla** eşleşti; 4-9 ID'leri kaynak sırasıyla (`1,2,3,1,2,3`) aynı.
  - **Gerçek S02E18 ASS'si (1242 cue)** ile, kaynakta `Summon organic matter` geçen partide bu gerçek yanıtı döndüren sahte modelle uçtan uca: `1242 -> 1242 cue`, `RENDER OK`, **kalıcı hata yok**; 340-343. cue'lar (`Cansız madde çağırma` / `Organik madde çağırma` / `Bir organizma çağır`) doğru sırayla yazıldı.
- **Not:** F28 kuralı bu partide yanlış pozitif üretti (numaralar tekrarlandığı için reddetti). Yeni kural numaraları yok sayıp sıraya güvendiği için hem F28 senaryosunu hem bu senaryoyu kapsar.
- **Kullanıcı tarafı doğrulaması:** Bekliyor — gerçek LM Studio + GUI ile yeniden çeviri (temiz checkpoint ile, `.exe` yeniden derlendikten sonra).

### F28. `S02E18-Turning Point 3` çevirisinin 46. partide kalması — model `ID:`/`TEXT:` etiketlerini tamamen düşürdü
- [x] **Durum:** Bitti ve otomatik doğrulandı (2026-09-19)
- **Belirti:** Mushoku Tensei `S02E18-Turning Point 3 [96557C59].ass` çevirisinde 45/125 parti geçiyor, **46. partide kalıcı** duruyor:
  `Geçici hata (deneme 1/3): Çeviri kimlikleri: eksik=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10] fazla=[]` (3 deneme de aynı). Checkpoint kanıtı (`S02E18...state.json`): 450/1242 girdi (0-449) tamamlanmış.
- **Kök neden (LM Studio logu):** 46. partide model 10 girdiyi **tek satıra** indirdi ve `ID:`/`TEXT:` etiketlerini **tamamen düşürdü**; yanıt düz numaralı liste oldu:
  `1. Cansız madde çağırma` … `10. Cansız madde çağırma`. F27'de (`Sakamoto Days - 12`) yalnızca `TEXT:` etiketi düşürülmüştü; bu kez `ID:` etiketi de gitmişti ve `parse_translation_response` hiçbir ID bulamıyordu. Yapısal bir ASS sorunu **değil**; yalnızca ayrıştırıcının biçim katılığı.
- **Yapıldı (2026-09-19):**
  - `subtitle.parse_translation_response`: ayrıştırma satır bazlı `_parse_labeled_response` + `_parse_numbered_response` olarak yeniden yazıldı. (**F29'da güncellendi:** `_parse_numbered_response` → `_parse_listed_response`; numara değerleri artık karşılaştırılmaz, eşleme sıraya göre yapılır.)
  - **Etiketli biçim** artık daha hoşgörülü: `ID` ve `TEXT` etiketi tek satırda (`ID: 1 TEXT: ...`) veya ayrı satırda olabilir; `TEXT:` etiketi isteğe bağlıdır; değer çok satırlı olabilir.
  - **Numaralı liste biçimi** (`1.`, `1)`, `1-`) eklendi; **yalnızca numara dizisi beklenen ID dizisiyle birebir örtüştüğünde** kabul edilir. Etiketli biçim kısmen geldiyse numaralı biçime **düşülmez**.
  - **ID kümesi denetimi aynen korundu:** numaralar kayarsa/eksik-fazla olursa yine anlamlı `ValueError` üretilir ve `_retry` çalışır.
  - `tests/test_core.py`: `test_translation_response_numbered_list_without_labels`, `_accepts_parenthesis_and_dash`, `_multiline_value`, `_wrong_numbers_is_rejected`, `test_translation_response_labeled_with_inline_text`, `test_translation_response_does_not_mix_labeled_and_numbered` eklendi (toplam **100** test).
- **Doğrulama (TAMAM, 2026-09-19):** `python -m unittest discover -s tests` → **100/100 `OK`**. Ayrıca **gerçek S02E18 ASS'si (1242 cue)** ile, 46. partide düz numaralı liste döndüren sahte modelle uçtan uca koşu: `1242 -> 1242 cue`, `RENDER OK`, **kalıcı hata yok** (düzeltme öncesi aynı senaryo `eksik=[1..10]` ile 46. partide duruyordu). `reflow` 26 kez normal biçimde devreye girdi (modelin 10 satırlık öbekleri tek satıra indirmesi beklenen davranış; etiketli partiler etkilenmedi).
- **Kullanıcı tarafı doğrulaması:** Bekliyor — gerçek LM Studio + GUI ile yeniden çeviri. **Not:** Mevcut `S02E18...state.json` checkpoint'i ilk 450 girdiyi içerir; çeviri kaldığı yerden devam ederse düzeltme yalnızca 46. partiden sonrasını kurtarır. Baştan temiz bir koşu için ilgili `.state.json`/`.pre-analysis.state.json`/`.post-analysis.state.json` silinmelidir.

---


## F30. ASS animasyon tekrarları ve güvenli yanıt kurtarma
- [x] **Durum:** Kodlandı; otomatik regresyonlar geçti.
- [ ] Gerçek LM Studio modeliyle S02E18'in yeniden çevrilmesi ve Windows EXE kontrolü.
- **Yapıldı (2026-09-19):** `subtitle.py`, `app_core.py`, `translation_prompt.txt`, `tests/test_core.py`, yeni `tests/test_recovery.py` ve üç tam test girdisi. Bağımsız Astra incelemesi yapıldı; bildirilen bozuk ID satırı açığı da kapatıldı.

### Doğrulanan neden ve eski testlerin sınırı
- S02E18: **1242 Dialogue, 353 farklı görünür metin**. Numaralı büyü listesinin her satırı 108 animasyon karesinde tekrarlanıyor. Önceki kod her kareyi bağımsız çeviri gibi gönderiyordu.
- F28/F29 yalnızca belirli sahte model cevaplarının ayrıştırılmasını denetliyordu. Sayı eşitliği; sıralamanın, metinlerin veya özgün liste numaralarının korunduğunu kanıtlamaz. F29, gerçek liste numaralarını silebiliyor ve ters sıralı etiketsiz cevabı yanlış girdilere yazabiliyordu.

### Yeni davranış
1. ASS'de yalnızca `pos`/`move` içeren, görünür metni ve zaman dışındaki Events alanları aynı olan, zaman aralıkları örtüşen veya birbirine değen olaylar gruplanır. Zaman bakımından ayrı tekrarlar, farklı stil/konuşmacılar ve normal SRT girdileri birleştirilmez. Her olayın özgün zamanlaması, öneki ve etiket iskeleti ayrı saklanır.
2. S02E18: **1242 → 385 çeviri birimi**; E15: **471 → 363**; Sakamoto: **320 → 320**. Çıktı girdi sayısı değişmez. Birim sayısı bütün dosyada tekilleştirilmiş metin sayısı değildir; farklı zamanlardaki tekrarlar korunur.
3. Çok girdili cevaplarda açık ID'ler zorunlu. `TEXT:` düşmesi ve satır içi `ID: 1 TEXT: ...` hâlâ desteklenir. Yinelenen ID/TEXT, boş değer, bozuk protokol satırı, eksik/fazla ID reddedilir. Etiketsiz numaralı/bos satırlı listeler sıraya göre kabul edilmez.
4. Yeniden denemeler bitince model yanıtı doğrulama hatası veren parti ikiye bölünür; gerekirse tek girdiye kadar iner. Tek girdilik cevapta kimlik eşleme belirsizliği yoktur; düz metin kabul edilir, özgün `1.` gibi numaralar silinmez. Tek girdi hâlâ geçersizse açık hata verilir; kaynak metin çeviri yerine sessizce kopyalanmaz. Ağ/HTTP hataları parti bölmeye yol açmaz.
5. Başarılı alt parti hemen checkpoint'e yazılır, sonra duraklat/kapat kontrolü yapılır. Sonraki alt parti başarısız olsa da öncekiler tekrar çevrilmez. Protokol sürümü imzaya eklenmiştir; eski F29 çıktısı taşıyan checkpoint otomatik kullanılmaz veya silinmez.
6. `finish_reason=length` ile kesilen dolu cevaplar da reddedilir. Sözlük düzeltme isteğine artık İngilizce kaynak değil, gerçekten önceki çeviri gönderilir.

### Kanıt ve sınırlar
- `python3 -m unittest discover -s tests` → **111 test OK**. Eski F28/F29'un belirsiz cevapları kabul etmeyi şart koşan testleri, bu cevapların reddedilmesi ve motorun güvenli biçimde toparlaması testleriyle değiştirildi.
- Üç tam kullanıcı dosyası: normal açık ID'li cevaplar ve her çoklu isteğe yanlış sıralanmış etiketsiz cevap veren sahte model ile ayrı ayrı uçtan uca çalıştırıldı. Girdi sayısı, zamanlar, sıra, Events alanları, meta, etiketler ve her girdinin beklenen dönüştürülmüş metni denetlendi; çıktı yeniden parse edildi.
- Ayrıca alt parti checkpoint/sürdürme, güvenli durdurma, kalıcı tekli hata, HTTP hatasında bölmeme, token sınırı, eski checkpoint reddi, farklı zaman/stil/konuşmacı ve sırasız animasyon girdileri sınandı.
- `py_compile`: çekirdek, altyazı, CLI ve GUI başarılı.
- Bu testler gerçek Türkçe çeviri kalitesini, oynatıcıdaki görsel sonucu veya tüm olası ASS/SRT uç durumlarını kanıtlamaz. Gerçek LM Studio ve Windows GUI/EXE bu ortamda çalıştırılmadı. Önceden var olan ASS çizim/karaoke ve satır ortası efekt yerleşimi davranışları için kapsamlı oynatıcı doğrulaması ayrıca gereklidir.

### Kullanıcıda temiz doğrulama
1. Yeni kaynakları ayrı klasöre çıkarın; `bin` içindeki mevcut FFmpeg araçlarını kullanın. EXE kullanılıyorsa `DERLE.cmd` ile yeniden derleyin.
2. Eski kurulum üzerine güncelleme yapıldıysa çalışan uygulamanın `work_files` klasöründeki yalnızca ilgili bölümün `S02E18-Turning Point 3 [96557C59].state.json` dosyasını yedekleyip yeniden adlandırın. EXE için bu klasör EXE'nin yanındadır. `.pre-analysis.state.json` çeviri checkpoint'i değildir; bu düzeltme onu silmeyi gerektirmez.
3. Çeviriyi başlatın. Konsolda 1242 girdinin 385 çeviri birimine ayrıldığı görülebilir. Model biçimi bozarsa `parti ... bölünüyor` mesajı kurtarma akışıdır.
4. Model tek girdide de geçersiz cevap verirse konsol hatası ve LM Studio ham yanıtıyla devam edin; otomatik test sonucu canlı başarı olarak kaydedilmemelidir.

---

## F31. Türkçe karakter desteklemeyen kaynak fontlar → çıktıda Calibri
- [x] **Durum:** Bitti ve doğrulandı (2026-09-20)
- [x] Gerçek LM Studio + Windows GUI/EXE ile oynatıcı görsel doğrulaması — kullanıcı doğruladı ("Çalıştı.", 2026-09-20).
- **İstek:** Kaynak altyazıdaki font Türkçe karakterleri desteklemiyorsa, Türkçe çeviri çıktısındaki font Türkçe destekleyen **Calibri** olmalı.
- **Sorun/bağlam:** Gerçek ASS dosyalarında (örn. `turning-point-3.ass`) fontlar `[V4+ Styles]` `Fontname` sütununda ve satır içi `\fn<ad>` etiketlerinde geçer. Bu fontlar (Gandhi Sans, Signika, Bolton, EraserDust, Quadraat-Regular, ITC Souvenir Std Light) sistemde kurulu değildir veya `ğ/Ğ/ı/İ/ş/Ş` gliflerini içermez; oynatıcı bu harfleri eksik/bozuk gösterir.
- **Yapıldı (2026-09-19):**
  - Yeni `fonts.py`: **Windows GDI** (`GetGlyphIndicesW`) ile fontun `çÇğĞıİöÖşŞüÜ` harflerini çizip çizemediği tespit edilir (`supports_turkish`). Font kurulu değilse de GDI yedek fonta düşüp glif "yok" (0xFFFF) döndürdüğü için sonuç doğru biçimde "desteklemiyor" olur. Tespit yapılamazsa (Windows dışı ortam, GDI hatası) yanlış font değişikliği yapmamak için font **destekliyor varsayılır**. `FALLBACK_FONT = 'Calibri'`, `turkish_replacements(families)`.
  - `subtitle.py`: `ass_font_families(text)` (Styles `Fontname` + `\fn<ad>` taraması) ve `apply_ass_font_fallback(text, replacements)` (yalnızca `[V4+ Styles]` `Fontname` sütunu ve `\fn` değerleri değiştirilir; yapı/diğer tag'ler korunur). `render_ass` değişmedi.
  - `app_core.render_output(kind, payload, cues, log=None)`: SRT/VTT'de dokunulmaz; ASS/SSA'da Türkçe desteklemeyen fontlar Calibri ile değiştirilir ve `log` verilirse `Font uyarısı: ... Calibri kullanıldı (...)` yazılır. Üretim akışı bu fonksiyondan geçer.
  - `gui.py` (`RunWorker.run` çıktı yazımı) ve `cevir.py` (`command_translate`) `subtitle.render_by_kind` yerine `app_core.render_output` kullanacak şekilde güncellendi.
  - `tests/test_core.py`: `FontFallbackTests` (7 test) — font aile toplama, `\fn` + Style dönüşümü, replacements yokken no-op, yetenek tabanlı eşleme, `render_output` ASS/SSA/SRT davranışı (`supports_turkish` mock'lanır; GDI'ya bağımlı değildir).
- **Doğrulama (TAMAM, 2026-09-19):** `py -3 -m unittest discover -s tests` → **118/118 `OK`** (F30 sonrası 111 → +7). Gerçek `turning-point-3.ass` (1242 cue) üzerinde: Arial destekliyor → değişmedi; 6 font Calibri'ye çevrildi; cue sayısı 1242/1242, fontlar ve tüm `\fn` etiketleri çıktıda; konsol uyarısı üretildi. `py_compile`/AST temiz. GUI `QT_QPA_PLATFORM=offscreen` ile import edildi.
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Gerçek Windows ortamında çalıştı; font değişimi beklendiği gibi sonuç verdi.
- **Sınır/not:** Font tespiti **sistemin kurulu fontlarına** bakar; kaynak ASS içine gömülü font (attached fonts) bu sürümde okunmaz. Oynatıcı gömülü font kullanıyorsa Calibri yine de seçilir (kaynakta gömülü font olup Türkçe destekliyorsa gereksiz değişiklik olabilir; gerçek dosyalarda bu durum görülmedi). GDI tespiti Windows'a özgüdür; Windows dışında çıktı değiştirilmez.

---

## F32. Frameless pencere + özel başlık şeridi (PROTOTİP)
- [x] **Durum:** Prototip kodlandı ve otomatik doğrulandı; gerçek Windows GUI/etkileşim doğrulaması bekliyor
- [x] Kenardan boyutlandırma (`startSystemResize` + görünmez kenar tutamaçları)
- [x] Dış çerçeve (pencere sınırı koyu zeminden ayrışsın diye `QWidget#appRoot` kenarlığı)
- [x] Pencere düğmeleri `QPainter` ile tam ortalanmış; hover programın yeşili (`accent`)
- [ ] Win11 Snap Layouts (büyütme düğmesi hover menüsü) — kapsam dışı
- **İstek (2026-09-20):** Windows native başlık çubuğu yerine sistemin kalanıyla uyumlu (koyu + lime) özel şerit.
- **Karar:** `Qt.FramelessWindowHint` + kendi `TitleBar` şeridi. Sürükleme, Aero Snap ve kenardan boyutlandırma **elle yazılmaz**; `QWindow.startSystemMove()` / `startSystemResize(edges)` ile işletim sistemine devredilir (PySide6 6.10.1'de mevcut olduğu doğrulandı). Çift tık büyüt/küçült. Pencere düğmeleri sağ uçta.
- **Yapıldı (2026-09-20):**
  - `gui.py`: `MainWindow.__init__` → `setWindowFlags(Qt.Window | Qt.FramelessWindowHint)`; yeni `TitleBar(QFrame)` (44px, `mousePressEvent` → üst kenarda `startSystemResize`, aksi halde `startSystemMove`; `mouseDoubleClickEvent` → `toggle_maximize`; `mouseMoveEvent` ile kenar imleci).
  - `_build_toolbar` → **`_build_title_bar`**: eski `QToolBar` kaldırıldı, aynı marka + Video Seç + Seri + Terim + Süreklilik + durum rozeti + Ayarlar içeriği şeride taşındı.
  - **Kenardan boyutlandırma:** yeni `ResizeEdges(QObject)` — 8 görünmez tutamaç (4 kenar 6px + 4 köşe 12px), `eventFilter` ile `startSystemResize`; `reposition()` `resizeEvent` ve `_sync_window_state`'te çağrılır, maximize/fullscreen'de gizlenir. Yardımcılar `edges_at()` ve `resize_cursor()`.
  - **Dış çerçeve:** `centralWidget` → `setObjectName('appRoot')`; QSS'te `QWidget#appRoot { border:1px solid {frame_border} }` (yeni `frame_border = #33434a`, `bg`'den açık). Arkada koyu bir zemin varsa pencere sınırı artık ayrışıyor.
  - **Pencere düğmeleri:** yeni `CaptionButton(QPushButton)` — küçült/büyüt/geri yükle/kapat glifleri fonttan bağımsız `QPainter` ile tam ortalanarak çizilir (font fallback taban çizgisi kayması giderildi). Düğmeler bitişik bir `QWidget` içinde toplandı; hover/pressed zemini `accent` + `accent_text`, kapat için kırmızı `#c42b1c` **kaldırıldı**.
  - Kullanılmayan `apply_window_chrome` (DWM native başlık boyama) ve `QToolBar` importu kaldırıldı.
  - `tests/test_gui_contract.py`: `test_native_title_bar_is_darkened_on_show` kaldırıldı; `test_window_is_frameless_with_custom_title_bar`, `test_title_bar_drag_and_double_click_are_wired`, `test_edges_allow_resizing_and_use_system_resize`, `test_caption_buttons_are_painted_and_use_accent_hover`, `test_root_frame_border_is_applied` eklendi.
- **Doğrulama (2026-09-20):** `py -3 -m unittest discover -s tests` → **123/123 `OK`**; `py_compile` temiz. `QT_QPA_PLATFORM=offscreen` ile: frameless=True, şerit 44px, 8 kenar tutamaç doğru konumda (`reposition`), maximize'da tutamaçlar gizleniyor/geri geliyor, `edges_at`/`resize_cursor` köşe ve kenarları doğru seçiyor, büyüt düğmesi `max`↔`restore` geçiyor, düğme hover'ı `underMouse=True` ile accent zemine dönüyor; `grab()` ile şerit, çerçeve ve ortalanmış glifler görsel olarak denetlendi.
- **Kullanıcı geri bildirimi sonrası düzeltmeler (2026-09-20):**
  - **Dış çerçeve hiç çizilmiyordu.** İki neden: (1) `QWidget` QSS `border`'ı boyamaz — kök widget `QFrame#appRoot` yapıldı; (2) ata kural `QFrame#customTitleBar QPushButton` (1 ID + 2 element) Qt'nin CSS2 özgüllüğü nedeniyle `QPushButton#winButton`'u (1 ID + 1 element) ezerek caption düğmelerine `padding:6px 11px` uyguluyor ve 46×32'yi **68×44**'e şişiriyordu. Düğme kuralları da ata seçiciyle yazıldı. Ölçüm: `frame_border` pikselleri 0 → dört kenar + köşelerde doğrulandı.
  - **Küçült/büyüt düğmeleri ortalanmamıştı.** Şişme giderildikten sonra ölçüldü: her üç düğme 46×32, glif merkezi = düğme merkezi (23, 16); küçült çizgisi y=16 (tam orta), kapat ✕ 11–21 aralığında.
  - **Yeni test:** `test_caption_buttons_keep_fixed_size` (özgüllük kaynaklı şişmeyi kilitler).
- **Kullanıcı tarafında bekleyen (manuel):** Gerçek Windows'ta (a) şeritten sürükleme + Aero Snap, (b) **kenardan/köşeden boyutlandırma** (özellikle `startSystemResize` davranışı), (c) çift tık büyüt/geri yükle, (d) maximize'da görev çubuğunu örtme, (e) hover yeşili ve düğme ortalaması, (f) `DERLE.cmd` sonrası `.exe`.

---

## F33. Üst barın alt kenarındaki istenmeyen "genişletme" (resize) bölgesi kaldırıldı
- [x] **Durum:** Kodlandı ve otomatik doğrulandı (2026-09-20); gerçek Windows fare etkileşimi doğrulaması bekliyor
- **Belirti (kullanıcı, 2026-09-20):** Üst barın hemen altında, içerikten önce genişletme (pencere boyutlandırma) alanı çıkıyor. Kullanıcının ekran görüntüsünde kırmızı oklarla işaretlediği bölge tam olarak bu.
- **Kök neden:** `TitleBar._edge_at()` başlık şeridinin **alt 6px**'ini de pencere alt kenarı sayıyordu (`edges_at(...)` `height - RESIZE_MARGIN` sınırına kadar). Fare oraya gelince `SizeVerCursor` (dikey genişletme) imleci çıkıyor ve basılıp sürüklenince `startSystemResize(Qt.BottomEdge)` çağrıldığı için pencere yanlış kenardan (alttan) boyutlandırılıyordu. Bu davranış F32'nin frameless şeridiyle geldi.
- **Yapıldı (2026-09-20):**
  - `gui.py` → `TitleBar` sınıfına `RESIZE_EDGES = Qt.TopEdge | Qt.LeftEdge | Qt.RightEdge` eklendi. `_edge_at()` artık `edges_at()` sonucunu bu kümeyle `&` maskeler; sonuç boşsa `None` döner. Böylece şeridin **alt kenarı boyutlandırmaya kapalı**; o bölgede `mousePressEvent` sürüklemeye (`startSystemMove`) düşer. Şeridin üst/sol/sağ kenarı ve üst köşeleri (TopEdge|LeftEdge, TopEdge|RightEdge) boyutlandırmaya devam eder.
  - `tests/test_gui_contract.py`: `test_title_bar_does_not_resize_from_its_bottom_edge` eklendi (`RESIZE_EDGES` var, üç kenar birleşimi var, `Qt.BottomEdge` şeritte geçmiyor).
- **Doğrulama (TAMAM, 2026-09-20):** `py -3 -m unittest discover -s tests` → **124/124 `OK`**. `QT_QPA_PLATFORM=offscreen` ile `TitleBar._edge_at` taraması: üst kenar y=2/5/6 → `TopEdge` (SizeVer), **y=8..43 → None (Arrow)**; sol/sağ kenar → `LeftEdge`/`RightEdge` (SizeHor); üst köşeler → `TopEdge|LeftEdge` / `TopEdge|RightEdge` (SizeFDiag/SizeBDiag). Fareyle alt kenara gelindiğinde artık genişletme imleci çıkmıyor. **Not:** Alt kenar tutamacı bilerek korundu; yalnızca üst bar üzerindeki (içerik ile üst bar arasındaki) istenmeyen resize bölgesi kaldırıldı.
- **Kullanıcı doğrulaması (TAMAM, 2026-09-20):** Kullanıcı düzeltmeyi gerçek Windows arayüzünde denedi — "Tamam oldu. Başarılı." Üst barın alt kenarındaki istenmeyen genişletme bölgesi kalktı.
- **`.exe` derlemesi (TAMAM, 2026-09-20):** `bin\ffmpeg.exe` + `bin\ffprobe.exe` yerleştirildikten sonra `DERLE.cmd` bu VM'de çalıştırıldı → `dist\Aktar.exe` (≈223 MB, PyInstaller `--onefile --windowed`) başarıyla üretildi. `dist\Aktar.exe` başlatıldı, açıldı ve çökmeyi beklemeden sorunsuz çalıştı. Simge gömülü (`build\Aktar\EXE-00.toc` içinde `assets\aktar.ico`).

---

## F34. Tıklanabilir kayıtlarda hover yeşil vurgusu + pencere düğmelerinin yeşil arka planı kaldırıldı
- [x] **Durum:** Kodlandı ve otomatik doğrulandı (2026-09-20); gerçek Windows fare etkileşimi doğrulaması bekliyor
- **İstek (kullanıcı, 2026-09-20):** Tıklanabilir kayıtların üzerine gelindiğinde yazıları sistemin yeşil rengiyle (`accent`) highlight edilsin. Pencere düğmelerinde (küçült/büyüt/kapat) hover'daki yeşil arka plan kaldırılıp diğer öğelerle aynı olsun; bu düğmelerin **simgeleri** de hover'da yeşil olsun. "Tam ekran yapma" = büyüt düğmesiyle ilgili; ayrı bir tam ekran özelliği eklenmedi.
- **Yapıldı (2026-09-20):**
  - `gui.py` QSS: `QTableWidget::item:hover` arka planı kaldırıldı → `color:{accent}`. `QPushButton:hover` ve `:pressed` accent metne döndü; `#primary/#ghost/#iconOnly/#iconFlat` hover/pressed renkleri accent yapıldı. Pencere düğmeleri (`#winButton/#winClose`) hover/pressed zemini `#1a2530` (genel düğmelerle aynı), yazı/simge `accent`; yeşil dolgu kaldırıldı.
  - `gui.py` yeni `HoverHighlightDelegate(QStyledItemDelegate)` + `highlight_rows(table)`: QSS `::item:hover` yalnızca fare altındaki **tek** hücreyi renklendirebildiği için hover satırı `eventFilter` (viewport, `MouseMove`/`Leave`) ile izlenir; `initStyleOption`'da o satırın tüm hücre metinleri accent'e çevrilir. **İşaretlenmiş (checkbox) satırlar** da kalıcı olarak accent renkte kalır (önceki `panel_alt` arka plan vurgusunun yerini alır).
  - Delegate bağlandı: ana **akış tablosu**, `GlossaryDialog` tablosu, `GlossaryReviewDialog` terim ve süreklilik tabloları.
  - `gui.py` yeni `_recolor_pixmap(pixmap, color)` + `_icon_with_accent_hover(pixmap, icon)`: `tinted_icon` ve `_settings_svg_icon` artık ikonun **Active (hover)** modu için accent kopyası ekler (`icon.addPixmap(accent, QIcon.Active)`). Böylece metinsiz ikon düğmelerinin (Ayarlar, Duraklat, Ok/Terim/Süreklilik, temizle) ikonları da hover'da yeşile döner.
  - `CaptionButton.paintEvent` glif rengi hover'da `accent_text` yerine **`accent`** yapıldı; böylece pencere düğmeleri hover'da diğerleriyle aynı koyu zeminde (`#1a2530`) **yeşil simge** gösterir.
  - `tests/test_gui_contract.py`: `test_caption_buttons_are_painted_and_use_accent_hover` → `..._use_accent_glyph` olarak güncellendi (yeşil arka plan **yok**, zemin `#1a2530`, glif `accent`); yeni `test_clickable_items_highlight_in_accent_on_hover` ve `test_tables_use_hover_highlight_rows` eklendi. Toplam **126** test.
- **Doğrulama (2026-09-20):** `python -m unittest discover -s tests` → **126/126 `OK`**; `py_compile` temiz. `QT_QPA_PLATFORM=offscreen` ile: delegate hover satırının "Dil" hücresi `#c8ff00`, hover olmayan satır `#54666b`, işaretli satır yine `#c8ff00`; `QIcon.Active` varyantı hem Ayarlar hem `tinted_icon('video', ...)` için `#c8ff00` çizildi.
- **Kullanıcı tarafında bekleyen (manuel):** Gerçek Windows'ta (a) tablo satırı hover'ında tüm satırın yeşile dönmesi, (b) pencere düğmelerinin hover zemininin diğerleriyle aynı olması ve **simgelerin yeşil** görünmesi, (c) genel buton hover metin rengi. `underMouse()` offscreen'de her zaman `False` döndüğünden glif rengi burada görsel olarak doğrulanamadı.

---

## F35. İkonlu düğmelerde yeşil vurgu yalnızca hover'da + seri dropdown popup düzeltmesi

- [x] **Durum:** Bitti — kodlandı, otomatik doğrulandı (127/127 test OK) ve kullanıcı GUI'de doğruladı (2026-09-20)
- **İstek (kullanıcı, 2026-09-20):** (a) Üst bardaki Video Seç / Terim / Süreklilik / Ayarlar (ve Bölüm terimleri / Duraklat) ikonları tıklamadan sonra yeşil kalıyordu; mouse üzerinde değilken bile yeşil yanmaya devam ediyordu — yeşil **yalnızca hover'da** olmalı. (b) SERİ dropdown'ına tıklayınca açılan menü "kısık" açılıyordu (combo'nun üzerine biniyor, son öğe kesiliyor).
- **Teşhis (offscreen + gerçek Windows probe'larıyla ölçüldü):**
  - Yeşil ikon sorununun kökü: Qt, ikonun `QIcon.Active` modunu hover'da **değil**, `State_HasFocus`'ta da çiziyor (PySide6 6.10.1'de ölçüldü). F34'te ikonların Active moduna accent kopyası eklenmişti; düğmeye tıklanıp diyolog açılınca klavye focus'u düğmede kaldığından ikon yeşil kalıyordu. Hover'da ikon hiç yeşile dönmüyordu (yalnızca QSS `:hover` metni renklendiriyordu).
  - Popup sorununun kökü: Qt 6.10 combo popup'unu, **seçili öğeyi combo ile aynı çizgiye** hizalayarak açıyor (currentIndex kaç ise popup o kadar yukarı kayıyor; index 0'da popup combo'nun üstüne biniyor). Ayrıca container (`QComboBoxPrivateContainer`) view'ın etrafına köşe maskeleme widget'ları (üst 6 + alt 10 + alt 6 px; alt payı kaydırma çubuğu görünürlüğüne göre değişiyor) ekliyor; Qt'nin kendi yükseklik hesabı son öğeyi kesiyordu (view 86px < içerik 96px).
- **Yapıldı (2026-09-20):**
  - `gui.py` yeni `HoverIconButton(QPushButton)`: ikon yalnızca `enterEvent`/`leaveEvent` ile accent varyanta döner; focus durumundan bağımsız. `setTintedIcon(name, color, size)` normal + accent (hover) ikonu birlikte atar; `setHoverIcon(icon)` özel ikonlar için (Ayarlar SVG'si, Duraklat/Devam). `leaveEvent`'te yalnızca hover ikonu hâlâ görünüyorsa eski ikona dönülür (runtime ikon değişiminde eski ikon geri yazılmaz). Pasif düğme swap yapmaz.
  - `gui.py`: `_icon_with_accent_hover` ve `_recolor_pixmap` kaldırıldı; `tinted_icon`/`_settings_svg_icon` sade ikon döndürür. `_settings_svg_icon` artık `color=` parametresiyle accent varyant üretebiliyor.
  - `HoverIconButton`'a çevrilen düğmeler: Video Seç, Terim, Süreklilik, Ayarlar, Duraklat/Devam (`_set_pause_button` hover ikonunu da günceller), Bölüm terimleri, konsol temizle, Ayarlar'daki "Yüklü modelleri sorgula".
  - `gui.py` yeni `DropdownCombo(QComboBox)`: `showPopup()` override — popup `super().showPopup()` sonrası açıkça **combo'nun altına** taşınır (ekranın altına sığmazsa alt kenarı combo üstüne gelecek şekilde yukarıda açılır); yükseklik tüm öğeleri sığdırır (`MAX_VISIBLE_ROWS = 10`, fazlasında kaydırma çubuğu), genişlik en uzun öğe metnine göre genişler (`TEXT_WIDTH_PAD = 44`), container'daki köşe maske widget'ları layout'tan çıkarılır, layout defer edebildiği için her turda `activate()` ile senkron boyut okunur (3 tura kadar düzeltme).
  - `DropdownCombo` uygulamanın tüm combolarında: seri combo (üst bar), Ayarlar'daki Model combo (editable), `GlossaryReviewDialog` kapsam combo'ları.
  - `tests/test_gui_contract.py`: `test_clickable_items_highlight_in_accent_on_hover` güncellendi (HoverIconButton sözleşmesi; `QIcon.Active`/`addPixmap`/`_icon_with_accent_hover` kullanılmamalı); yeni `test_dropdown_combo_places_popup_below_the_field`; `test_icon_assets_exist_for_every_tinted_icon` artık `setTintedIcon` çağrılarını da tarıyor.
- **Doğrulama (2026-09-20):** `python -m unittest discover -s tests` → **127/127 `OK`**; `py_compile` temiz. `QT_QPA_PLATFORM=offscreen` + gerçek Windows probe'ları: (a) tüm ikon düğmelerinde normal→secondary piksel, hover→accent piksel, leave→secondary geri; focus'ta ikon accent OLMUYOR; pasif Duraklat'ta swap yok, aktifken var. (b) Seri popup: combo alt kenarıyla (global y 97) popup üstü (97) hizalı, view 98px = içerik 96 + çerçeve 2, viewport 96 = içerik 96, kaydırma çubuğu yok, 4 öğenin tamamı görünür; ekran altına taşınan pencerede popup alt kenarı combo üstüne (y 873) sabitlendi; 16 öğede kaydırma çubuğu devreye giriyor. Popup görseli `grab()` ile denetlendi (offscreen'de fontlar kutu çizdi, gerçek platformda metinler doğru). SettingsDialog + GlossaryReviewDialog DropdownCombo ile açılıyor.
- **Kullanıcı doğrulaması (TAMAM, 2026-09-20):** Kullanıcı gerçek Windows'ta denedi, "Güzel çalışıyor." — ikon yeşili artık yalnızca hover'da, tıklama sonrası sönüyor; seri menüsü combo'nun altında tüm öğeleri göstererek açılıyor.

---

## F36. "aktar." marka noktasının yazıyla baseline hizalanması

- [x] **Durum:** Bitti — kodlandı, otomatik doğrulandı (127/127 test OK); GUI görsel doğrulaması kullanıcıda bekliyor
- **İstek (kullanıcı, 2026-09-20):** Üst bardaki "aktar." markasındaki nokta, "aktar" yazısıyla hizalı değildi.
- **Teşhis:** Nokta ayrı bir `QLabel` idi (16px font) ve `Qt.AlignBottom` ile **widget kutusunun** tabanına yaslanıyordu; "aktar" etiketi ise 14px metnini kendi kutusunda **dikey ortalıyordu**. İki ayrı widget kutusunun glif baseline'ları layout hizalamasıyla asla garanti örtüşmüyor; ayrıca 8px `spacing` noktayı yazıdan ayırıp "aktar ." görünümü veriyordu.
- **Yapıldı (2026-09-20):**
  - `gui.py` `_build_title_bar`: nokta ayrı `QLabel`'dan çıkarıldı; "aktar" ve nokta **tek `QLabel` içinde zengin metinle** birleştirildi (`aktar<span style="color:{accent}; font-size:16px;">.</span>`, `setTextFormat(Qt.RichText)`). Tek metin satırı olduğundan nokta yazının **aynı baseline'ına** oturur; 16px nokta boyutu ve accent rengi korunur. `QLabel#brandDot` QSS kuralı kaldırıldı (başka kullanım yok).
  - `tests/test_gui_contract.py`: `test_primary_ui_labels_use_turkish_characters` beklentisi `'Video Seç...'` → `'Video Seç'` güncellendi (kullanıcı üç noktayı bilerek kaldırmıştı; test beklentisi bayat kalmış, ilk koşuda bu nedenle düşmüştü) ve üç noktalı `HoverIconButton('Video Seç...')` obsolete listesine eklendi (kullanıcı kararının geri dönmemesi için).
- **Doğrulama (2026-09-20):** `python -m py_compile gui.py` temiz; `python -m unittest discover -s tests` → **127/127 `OK`** (exit 0).
- **Kullanıcı tarafında bekleyen (manuel):** Gerçek Windows'ta marka noktasının baseline hizasının görsel onayı.

---

## F37. Çeviri tamamlanınca toast yerine "Tamam" ile kapatılan modal bildirim

- [x] **Durum:** Bitti ve doğrulandı (2026-09-20 — kullanıcı GUI doğrulaması tamam)
- **İstek (kullanıcı):** Başarılı çeviri sonucu toast yerine, kullanıcının "Tamam" ile kapattığı modal bir bildirim açılsın.
- **Yapıldı:** `gui.py` `MainWindow.complete`: `self.toast.show_message(...)` kaldırıldı; yerine `_message_box('Çeviri tamamlandı', 'Çeviri başarıyla tamamlandı. Çıktı: <ad>')` modal bildirimi geldi. `Toast` sınıfı duruyor; uyarı akışı (`warn` → `_message_box`) değişmedi.
- **Yapıldı (test, 2026-09-20):** `tests/test_gui_contract.py` `test_completion_uses_toast_and_warnings_stay_modal` bayat kalmıştı (hâlâ `self.toast.show_message` arıyordu) → `test_completion_uses_modal_and_warnings_stay_modal` olarak yenilendi: `complete` içinde `toast.show_message` YOK, `_message_box` + `Çeviri tamamlandı` VAR; `warn` hâlâ modal. Doğrulama: **127/127 test `OK`** (exit 0).
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Gerçek Windows GUI'de çeviri bitince "Çeviri tamamlandı" uyarısı açılıyor ve çalışıyor.

---

## F39. Ayarlardan model seçilince sağ üstteki durum rozetinin güncellenmemesi

- [x] **Durum:** Bitti ve doğrulandı (2026-09-20 — kullanıcı GUI doğrulaması tamam)
- **Belirti (kullanıcı, 2026-09-20):** Ayarlar'dan LM Studio modeli seçilip kaydedilince sağ üstteki durum rozeti model adını güncellemiyor. Model seçimi arka planda doğru uygulanıyor (LM Studio seçileni çağırıyor); yalnızca görsel sorun.
- **Kök neden:** `MainWindow.show_settings` config'i kaydedip yalnızca `Ayarlar kaydedildi.` yazıyordu. Durum rozetini güncelleyen tek yol açılıştaki `refresh_loaded_models` → `status_ready` → `_set_status` zinciriydi; kayıt sonrası rozet hiç tazelenmiyordu.
- **Yapıldı (2026-09-20):**
  - `gui.py` yeni `MainWindow._status_text(cfg)` statik yardımcısı: rozet metnini `<model> · <host>` biçiminde üretir (host normalizasyonu tek yerde).
  - `refresh_loaded_models`: host normalizasyonu ve metin üretimi `_status_text`'e taşındı; `status_ready.emit(self._status_text(cfg), bool(names))`.
  - `show_settings`: kayıt sonrası rozet anında `_set_status(self._status_text(dict(load_config())), None)` ile güncellenir, ardından `refresh_loaded_models()` bağlantı durumunu (renk/araç ipucu) düzeltir.
  - `tests/test_gui_contract.py`: `test_settings_save_refreshes_status_pill` eklendi — `_status_text` varlığı, `show_settings` içinde `_set_status` ve `refresh_loaded_models` çağrıları, `refresh_loaded_models` içinde `_status_text(cfg)` kullanımı (regresyon kilidi). Toplam **128** test.
- **Doğrulama (2026-09-20):** `python -m unittest discover -s tests` → **128/128 `OK`** (exit 0); `py_compile gui.py` temiz. Offscreen fonksiyonel probe: `MainWindow` + sahte kayıt diyaloğu ile `show_settings` sonrası rozet `'neptune-7b · 127.0.0.1:5000'` oldu (`PILL_UPDATED: True`).
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Gerçek Windows GUI'de denendi — model değiştirilip kaydedilince sağ üstteki rozet yeni model adını gösteriyor. "Olmuş onaylıyorum."

---

## F38. Ayarlar Model alanı yalnızca listeden seçim + Cevirgec'ten ayrışma notları

- [x] **Durum:** Bitti ve doğrulandı (2026-09-20 — kullanıcı GUI doğrulaması tamam)
- **İstek (kullanıcı, 2026-09-20):** "Yüklü modelleri sorgula" butonu tüm modelleri listeliyordu; model alanı freetext'e dönüşmüş görünüyordu. Karar: alan yalnızca listeden seçilir (serbest metin kaldırıldı).
- **Yapıldı (2026-09-20):**
  - `gui.py` `SettingsDialog`: `model.setEditable(True)` → `False`; alan yalnızca listeden seçim yapar. Tooltip `'LM Studio tarafından yüklü bildirilen modeller arasından seçim yapılır.'` olarak sadeleştirildi.
  - `_on_models` (sorgu sonrası liste doldurma + mevcut seçimi koruma) zaten doğru çalışıyordu; değişmedi. Offscreen probe: alan `isEditable() == False`, sorgu sonrası liste dolduruluyor (`4 model bulundu.`).
- **Ayrışma notu:** Aktar ile Cevirgec belirgin biçimde ayrıştı — Aktar'ın kendi modül düzeni (`subtitle/media/series/fonts`), kendi GUI yığını (frameless pencere, `DropdownCombo`/`HoverIconButton`, `THEME` tabanlı stil) ve kendi sözleşme testleri (`tests/test_gui_contract.py`) var. Cevirgec artık kod kaynağı değildir; bu belgenin üst notu ve global `AGENTS.md` Aktar bölümü buna göre güncellendi (kod taşıma öncesi her iki güncel depo doğrulanmalıdır).
- **Doğrulama (2026-09-20):** `python -m unittest discover -s tests` → başta **126/127** (tek hata F37 testi), ardından F37 testi yeni davranışa göre güncellendi → **127/127 `OK`** (exit 0). Önceki tek hata `test_completion_uses_toast_and_warnings_stay_modal` idi; F37 `complete()`'i toast yerine modala çevirmiş, test beklentisi bayat kalmıştı. Test `test_completion_uses_modal_and_warnings_stay_modal` olarak yenilendi (`toast.show_message` YOK, `_message_box` + `Çeviri tamamlandı` VAR, `warn` modal kalıyor). `py_compile gui.py` temiz.
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Gerçek Windows GUI'de denendi — Model alanı modelleri listeliyor, listeden seçilince LM Studio'daki o model çağrılıyor. "Başarılı oldu."

---

## F40. Temizlik: .gitignore, requirements.txt, README İngilizce açıklama, çalışma zamanı dosyalarının kaldırılması

- [x] **Durum:** Bitti ve otomatik doğrulandı (128/128 test `OK`)
- **İstek (kullanıcı, 2026-09-20):** `.gitignore` kontrolü ve gereksiz girinti eklenmesi; `requirements.txt`'nin güncelliği; README'ye diğer projeler gibi kısa İngilizce açıklama; `offscreen.png`, `config.json`, `series/`, `work_files/` silinmesi.
- **Yapıldı (2026-09-20):**
  - `.gitignore`: `work_files/`, `config.json`, `offscreen*.png` eklendi (çalışma zamanı üretilen veriler). `series/` zaten yok sayılıyordu.
  - `requirements.txt`: denetlendi — tek çalışma zamanı bağımlılığı **PySide6** (`QtSvg` dahil), derleme için **PyInstaller**. Kurulu sürümlerle birebir uyumlu (6.10.1 / 6.17.0); değişiklik gerekmedi.
  - `README.md`: Cevirgec deseninde kısa İngilizce açıklama eklendi (`> **English:** Aktar is a PySide6 desktop app ...`).
  - `DERLE.cmd`: `--add-data "config.json;."` satırı kaldırıldı — çalışma zamanı config'i `APP_DIR/config.json` (exe/source dizini) okunur; bundle'daki kopya hiç kullanılmıyordu ve `config.json` silinince derleme kırılırdı.
  - Silindi: `offscreen.png` (offscreen probe kalıntısı), `config.json` (yoksa `load_config` varsayılanlara düşer; ilk Ayarlar kaydında yeniden oluşur), `series/` (2 küçük glossary dosyası — aşağıdaki nota bak), `work_files/` (1 çıkarılmış `.ass` — saf çalışma zamanı verisi).
- **Doğrulama (2026-09-20):** `python -m unittest discover -s tests` → **128/128 `OK`** (exit 0). `load_config()` config olmadan `DEFAULT_CONFIG` döndürdü; dört öğenin de diski temizlendiği doğrulandı.
- **Not (veri kaybı uyarısı):** `series/` içindeki 2 dosya (`ryoumin-0-nin...json`, `toukutsu-ou.json`, toplam ~500 byte) kullanıcı onayıyla oluşan seri glossary/süreklilik verisiydi. Silindikleri için geri gelmez; gerekiyorsa yedekten geri konabilir. `work_files/` içindeki `.ass` kaynak videodan yeniden çıkarılabilir.

---

## F41. Sürükle-bırak alanında yalnızca ikon + "Videoyu buraya bırakın"; ikona tıklayınca "Video Seç"

- [x] **Durum:** Bitti ve doğrulandı (2026-09-20 — kullanıcı GUI doğrulaması tamam)
- **İstek (kullanıcı, 2026-09-20):** Ana ekrandaki video sürükle-bırak alanında sadece logo/ikon ve "Videoyu buraya bırakın" yazısı kalsın; logo ikona tıklanınca "Video Seç"e tıklanmış gibi davransın.
- **Yapıldı (2026-09-20):**
  - `gui.py` `DropArea` sadeleştirildi: ipucu satırı (`veya araç çubuğundan "Video Seç" ile açın`), uzantı rozetleri ve salt-okunur notu kaldırıldı; ikon + "Videoyu buraya bırakın" kaldı.
  - Yeni `ClickableLabel(QLabel)`: sol tıkta `clicked` sinyali yayar. İkon (`self.mark`) bu sınıftan; el imleci (`PointingHandCursor`) + "Video Seç" araç ipucu ile; `clicked` → `DropArea.select_requested` → `MainWindow.choose_video` bağlandı (dosya seçiciyi açar).
  - Kullanılmayan QSS kuralları kaldırıldı: `dropHint`, `dropNote`, `extBadge` (F36 `brandDot` deseni).
  - `tests/test_gui_contract.py`: yeni `test_drop_area_is_minimal_and_icon_opens_video_pick` eklendi (yalnızca ikon+başlık kalır, eski metinler/QSS kuralları yok, `select_requested`→`choose_video` bağı var).
- **Doğrulama (2026-09-20):** `python -m py_compile gui.py` temiz; `python -m unittest discover -s tests` → **129/129 `OK`**. Offscreen fonksiyonel probe: ikona `QTest.mouseClick` → `select_requested` tetiklendi; alandaki metinler yalnızca `['Videoyu buraya bırakın']`; el imleci + "Video Seç" araç ipucu; `acceptDrops()` hâlâ `True` (sürükle-bırak korunuyor); ikon/başlık yatay hizalı ve alan ortasına dikey ortalanmış (600x320'de grup merkezi 173 vs. alan ortası 160).
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Gerçek Windows GUI'de denendi — sürükle-bırak alanında yalnızca ikon + "Videoyu buraya bırakın" görünüyor, ikona tıklayınca dosya seçici açılıyor. Kullanıcı: "düzgün çalışıyor onaylıyorum."

---

## F42. README başlığına açık/koyu tema logo (kardeş proje deseni)

- [x] **Durum:** Bitti ve doğrulandı (2026-09-20 — XML geçerliliği + headless görsel kontrol + kullanıcı onayı)
- **İstek (kullanıcı, 2026-09-20):** `Cevirgec-git`, `izci-git`, `TPowerPlanSwitcher` README'lerinin en başındaki gibi ortalanmış logo başlığı Aktar README'sine de eklensin.
- **Yapıldı (2026-09-20):**
  - Yeni `assets/logo-light.svg` ve `assets/logo-dark.svg`: mevcut `aktar-icon.svg` simgesi (konuşma balonu + lime ok) + uygulamadaki marka yazısı (`aktar` + `THEME['accent']` `#c8ff00` nokta). Simgenin koyu kare zemini kaldırıldı; **arka plan saydam** (ikon artık kendi başına duruyor, kutu yok). Açık temada metin ve balon gövdesi `#1f2328`, koyu temada metin `#e6e9ef` + balon gövdesi `#e6edee`; ok ve nokta her iki temada lime `#c8ff00`.
  - `README.md`: `# Aktar` başlığı kaldırıldı; yerine `<div align="center"><picture>` bloğu geldi (`prefers-color-scheme` ile açık/koyu logo seçimi, `width="190"`). Diğer projelerle aynı desen.
- **Doğrulama (2026-09-20):** İki SVG de PowerShell `[xml]` ile geçerli XML olarak ayrıştırıldı. Görsel kontrol: `python -m http.server` + headless Edge (`--headless=new --screenshot`) ile açık ve koyu zemin üzerinde render edilip incelendi; simge + `aktar.` markası her iki temada doğru göründü. Geçici staging klasörü ve sunucu temizlendi.
- **Ok (limon yeşili) kırpma hatası düzeltildi (2026-09-20):** Orijinal `aktar-icon.svg` içindeki `clipPath` dikdörtgeni (`y="-320"`) oku üst yarısından kesiyordu; okun tepesi gövde renginde kalıyordu. Kırpma tamamen kaldırıldı; ok artık ayrı bir `path` olarak lime çiziliyor. Aynı düzeltme logolara da uygulandı.
  - `assets/aktar-icon.svg` düzeltildi ve bu kaynaktan `aktar-icon-256.png`, `aktar-icon-512.png`, `aktar.ico` (16/24/32/48/64/128/256, PNG sıkıştırmalı) PySide6 `QSvgRenderer` ile yeniden üretildi. Uygulama `_brand_pixmap` önce PNG'yi kullandığı için araç çubuğu logosu da bu düzeltmeden etkilenir.
- **Kullanıcı tarafı doğrulaması (TAMAM, 2026-09-20):** Kullanıcı sonucu onayladı ("Oldu başarılı."). README logoları ve düzeltilmiş simge (ok tamamen lime, saydam arka plan) kabul edildi.
- **Not:** README'deki `docs/screenshot.png` (ekran görüntüsü) hâlâ yok; bu iş yalnızca logo başlığını kapsar. GitHub'daki gerçek görünüm kullanıcı tarafından doğrulanabilir.


---

## 5. Bekleyen kararlar

1. ~~**Arayüz yığını:**~~ → **ÇÖZÜLDÜ:** PySide6 (2026-09-18).
2. ~~**ASS/SSA kaynağında çıktı formatı:**~~ → **ÇÖZÜLDÜ:** format korunur, ASS kaynağı `_TR.ass` olur (2026-09-18).
3. ~~**Çıktı çakışması:**~~ → **ÇÖZÜLDÜ:** `_TR (2).srt`, `_TR (3).srt` ... (2026-09-18).
4. ~~**Çeviri kapsamı (ASS):**~~ → **ÇÖZÜLDÜ (2026-09-19):** Yalnızca `Dialogue` metni çevrilir; `Styles`/`Fonts`/override tag'ler ve `[Script Info]`/`[V4+ Styles]`/`[Aegisub Project Garbage]` blokları **dokunulmadan** kalır. (Zaten mevcut davranış; kullanıcı onayı: varsayılan.)
5. ~~**Çok dilli kaynak:**~~ → **ÇÖZÜLDÜ (2026-09-19):** Kaynak zaten Türkçe ise **atla-uyar**: kullanıcı uyarılır (log + durum rozeti) ama **çeviri engellenmez**; istenirse yine çevrilir. (Uygulama: `app_core` tarafında satır-bazlı Türkçe tespiti → UYARI logu, akış devam eder.)
6. ~~**Seri glossary öneri kapsamı:**~~ → **ÇÖZÜLDÜ (2026-09-19):** Yeni terim önerisi **seri düzeyinde** saklanır. Bir bölüm seçilip çevrildiğinde (örn. `the_office_1`) çıkan yeni terimler o serinin glossary'sine yazılır; sonraki bölüm (`the_office_2`) çevrilirken **referans oradan** alınır. Depo: `APP_DIR\series\<slug>.json` (`glossary` + `decisions`). Öneri akışı: ön analiz ve/veya bölüm çevirisi sonunda yeni terimler onaya sunulur; onaylananlar seri glossary'sine eklenir.

---

## 6. Çalışma ortamı notları

- **Donanım:** RTX 5080 (16 GB VRAM), Ryzen 7800X3D, 32 GB RAM (Çevirgeç ile aynı makine)
- **Model:** LM Studio yerel sunucu, varsayılan `http://127.0.0.1:1234/v1`
- **Test komutu:** `cd /d Z:\LLM-Files\Projects\Aktar && py -3 -m unittest discover -s tests -v`
- **Güncel doğrulama:** F30 testleri Linux/Python ortamında çalıştırıldı. Windows/EXE ve gerçek LM Studio ayrıca kullanıcı tarafında doğrulanır.
- **VM notu (2026-09-20, F43):** Geliştirme VM'i (12 GB RAM, GPU yok) için LM Studio 0.4.25 kuruldu; `lms` CLI (`%LOCALAPPDATA%\Programs\LM Studio\resources\app\.webpack\lms.exe`) ve yerel sunucu 1234 kullanılıyor. `lms get`'in kendi CDN'i timeout yiyor; model indirme için HF'dan doğrudan curl (resume) geçerli yol. Elle konulan GGUF'u LM Studio ancak kendi indirme/dizinlemesi sonrası görüyor (`lms ls`). VM'de CPU'ya ancak ≤3B q4 model sığar (Qwen2.5 1.5B Q4_K_M ile 12/12 dosya test edildi); kalite düşüktür — akış doğrulaması içindir.
