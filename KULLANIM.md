# Aktar — Kullanım Kılavuzu

Bu kılavuz son kullanıcı içindir: kurulum, LM Studio ayarı, bütün akışlar, terim sözlüğü (glossary), seri ayarları ve sorun giderme.

---

## 1. Kurulum

### 1.1 Kaynak koddan çalıştırma

```bat
cd /d Z:\LLM-Files\Projects\Aktar
py -3 -m pip install -r requirements.txt
```

`requirements.txt`: `PySide6`, `PyInstaller`.

### 1.2 FFmpeg / ffprobe

Uygulama, videoyu okumak ve altyazı akışını çıkarmak için FFmpeg kullanır. İkililer **projeye taşınabilir** olarak konur:

```
Aktar\bin\ffmpeg.exe
Aktar\bin\ffprobe.exe
```

`bin\` içinde bulunmazsa sistem `PATH`'indeki `ffmpeg`/`ffprobe` denenir. Bulunamazsa uygulama anlamlı bir hata verir:

> `ffprobe bulunamadi. Uygulama klasorundeki "bin" dizinine ffprobe.exe dosyasini koyun.`

FFmpeg'i [ffmpeg.org](https://ffmpeg.org/download.html) üzerinden indirip `bin` klasörüne kopyalayabilirsiniz. Sistem geneline kurmak zorunlu değildir.

### 1.3 LM Studio

1. LM Studio'yu açın ve kullanmak istediğiniz modeli yükleyin.
2. **Developer / Local Server** sekmesinden yerel sunucuyu başlatın (varsayılan `http://127.0.0.1:1234`).
3. Modeli **thinking/reasoning kapalı** olacak şekilde ayarlayın (aşağıda 6.2'ye bakın).

### 1.4 aktar.exe derlemesi
1. İsterseniz bin klasörüne ffmpeg.exe dosyasını yerleştirdikten sonra .exe olarak derleyebilirsiniz. FFmpeg lisansından dolayı github sayfasında derlenmiş .exe sunulmuyor.
2. ffmpeg.ex DERLE.cmd çalıştırarak aktar.exe'yi oluşturabilirsiniz.
---

## 2. Yapılandırma — `config.json`

Uygulama dizinindeki `config.json` dosyası ayarları tutar. Yoksa `DEFAULT_CONFIG` değerleri kullanılır.

```json
{
  "base_url": "http://127.0.0.1:5000/v1",
  "model": "gemma-4-26b-a4b-it-qat@q4_k_xl",
  "batch_cues": 10,
  "max_tokens": 8192,
  "temperature": 0.2,
  "timeout_seconds": 1800,
  "auto_retry_count": 2,
  "glossary_strict": false,
  "analysis_chunk_chars": 12000,
  "disable_thinking": true
}
```

| Alan | Açıklama |
| --- | --- |
| `base_url` | LM Studio yerel sunucu adresi. **Yalnızca yerel** (`localhost` / `127.0.0.1` / `::1`) HTTP adresi kabul edilir. |
| `model` | LM Studio'da yüklü model kimliği (boş olamaz). |
| `batch_cues` | Bir istekte modele gönderilecek altyazı girdisi sayısı. Thinking açıkken küçük tutun (örn. 10). |
| `max_tokens` | Yanıt için üst token sınırı. Thinking'li modellerde artırın. |
| `temperature` | 0–2 arası; düşük değer daha tutarlı çeviri verir. |
| `timeout_seconds` | Tek isteğin zaman aşımı. |
| `auto_retry_count` | Geçici hatalarda yeniden deneme sayısı (1–100). |
| `glossary_strict` | Zorunlu terim denetimi katılığı. |
| `analysis_chunk_chars` | Ön/son analizde tek model isteğine gönderilecek yaklaşık görünür karakter sayısı. |
| `disable_thinking` | `true` ise istek gövdesine `chat_template_kwargs: {enable_thinking: false}` eklenir (LM Studio destekliyorsa). Desteklenmezse yok sayılır. |

> `base_url` **yalnızca yerel** olabilir; uzak adres reddedilir (gizlilik ilkesi).

---

## 3. Arayüz akışı

```
Video (sürükle-bırak veya Video Seç)
  ↓ ffprobe → altyazı akışları listelenir (codec + dil + başlık + durum)
  ↓ metin tabanlı bir akış seç
  ↓ Çevir → altyazıyı çıkarır, çevirir ve <video>_TR.<uzantı> olarak yazar
```

### 3.1 Video açma
- **Sürükle-bırak:** Video dosyasını penceredeki kesikli alana bırakın. Video açılınca bu alanın yerini dosya kartı (ad + klasör) ve altyazı akışı tablosu alır; **Değiştir** ile başka bir video seçebilirsiniz.
- **Video Seç…:** Dosya seçiciden bir video seçin.

Desteklenen video uzantıları: `.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`, `.ts`, `.wmv`, `.flv`.

### 3.2 Altyazı akışları tablosu
| Sütun | Anlamı |
| --- | --- |
| `Seç` | Çevrilecek altyazı akışını işaretler; aynı anda yalnızca bir akış seçilebilir. |
| `Codec` | Altyazı codec'i (subrip, ass, webvtt, mov_text …). |
| `Dil` | Metadata dil etiketi (varsa). |
| `Başlık` | Metadata başlık etiketi (varsa). |
| `Durum` | Desteklenen çıktı formatı (SRT/ASS/SSA/VTT) veya "Görüntü tabanlı - desteklenmiyor". |

Görüntü tabanlı altyazılar (PGS/VobSub) seçilemez; çevrilemez.

### 3.3 Altyazıyı Çıkar
Seçilen metin tabanlı akış, videonun kendi dizinine **orijinal formatta** çıkarılır:

- SRT kaynak → `<video>.srt`
- ASS kaynak → `<video>.ass`
- `mov_text` (MP4) → `<video>.srt` (dönüştürülür)

Aynı ada sahip dosya varsa `<video> (2).srt`, `<video> (3).srt` … biçiminde yeni ad üretilir (üzerine yazılmaz).

> **Kaynak video hiçbir şekilde değiştirilmez.** Yalnızca okunur ve seçilen altyazı akışı çıkarılır.

### 3.4 Çevir
**Çevir** düğmesine basınca:
1. **Ön analiz yap** seçiliyse model Türkçe terim ve süreklilik önerileri üretir; onay ekranında karşılık ve kapsam seçilir.
2. Altyazı, partiler (`batch_cues` kadar çeviri birimi) hâlinde LM Studio'ya gönderilir. ASS animasyonunda aynı yazıyı gösteren bitişik/örtüşen kareler birlikte çevrilir; çıktıdaki bütün kareler ve zamanları korunur. Model cevabı doğrulanamazsa parti otomatik küçültülür; başarılı alt partiler kaydedilir.
3. Çeviri bitince kaynak/çeviri çiftlerinden sonraki bölümlerde yararlı olabilecek yeni öneriler çıkarılır ve ikinci onay ekranı açılır.
4. Çıktı `<video>_TR.<uzantı>` adıyla videonun yanına yazılır (çakışmada `_TR (2)` …).
5. İşlem başarıyla bittiğinde çıktı yolunu gösteren temalı **Çeviri tamamlandı** penceresi açılır.

### 3.5 Türkçe karakter ve fontlar (ASS/SSA)
Türkçe'ye özgü harfler (`ç ğ ı İ ö ş ü` ve büyükleri) her fontta bulunmaz. Kaynak ASS/SSA dosyasındaki bir font bu harfleri çizemiyorsa (font sistemde kurulu değilse ya da glifleri eksikse) çıktıdaki o font **Calibri** ile değiştirilir. Hem `[V4+ Styles]` satırındaki `Fontname` sütunu hem de metin içindeki `{\fn...}` etiketleri güncellenir; böylece Türkçe çeviri doğru görüntülenir. Değişiklik konsola `Font uyarısı: ... Calibri kullanıldı (...)` olarak yazılır.

SRT/VTT font taşımadığı için bu işlem yalnızca ASS/SSA çıktısında uygulanır. Türkçe karakterleri destekleyen fontlara (örn. Arial) dokunulmaz.

Çeviri sürerken düğme **İptal** olur; duraklatma desteği kod tarafında mevcuttur.

---

## 4. Terim sözlüğü (glossary)

Glossary, belirli kaynak terimlerin çeviride **zorunlu** olarak belirtilen Türkçe karşılığıyla geçmesini sağlar.

- **Bölüm terimleri…** düğmesi: yalnızca bu altyazıya özel terimler.
- **Seri sözlüğünü düzenle** düğmesi: seçili seriye ait tüm bölümlerde geçerli terimler.

Her iki düğme de aynı tabloyu açar: **Kaynak terim** ve **Karşılık** sütunları. Boş satırlar yok sayılır.

### Yapay zekâ öneri ekranı
Ön analiz ve çeviri sonrası inceleme ekranlarında şu bilgiler gösterilir: **Kaynak terim, Türkçe önerisi, tür, gerekçe, kullanım sayısı ve kapsam**. Türkçe karşılık düzenlenebilir. Seçili seri varsa kapsam **Seriye ekle** veya **Yalnız bu bölüm** olabilir. İptal edilen ya da işareti kaldırılan öneri kaydedilmez.

Ön analiz, terimleri çeviri başlamadan etkinleştirdiği için aynı bölümdeki tutarlılığı artırır. Çeviri sonrası bulunan yeni terimler ise kullanıcı onayından sonra esas olarak sonraki bölümlerde kullanılır.

### Denetim nasıl çalışır
- Yalnızca **kaynak metinde geçen** terimler denetlenir.
- Karşılık, Türkçe çekim ekleriyle birlikte aranır: `Yapı` → `yapılar`, `yapısının`, `yapıda` **kabul**; `külot` (kül + ot) **reddedilir**.
- Eksik terim varsa tek bir **düzeltme turu** yapılır; hâlâ eksikse çeviri hata verir.

### Çakışma kuralı
Bölüm terimi ile seri terimi aynı kaynağa sahipse **bölüm terimi kazanır** (seri sözlüğü taban, bölüm sözlüğü üst katmandır).

---

## 5. Seri (dizi/anime) desteği

Seri, bölümler arası tutarlılık için **glossary + continuity kararlarını** birlikte saklar.

- Üstteki **Seri sözlüğü** açılır listesi: `(Seri yok) | <seri> | + Yeni seri...`
- Video klasör adı seri ile eşleşiyorsa seri **önerilir** (zorlanmaz, önceden seçilir).
- **+ Yeni seri…** → başlık sorulur, ASCII slug ile `series\<slug>.json` oluşturulur.
- **Süreklilik** düğmesi: sen/siz, isim yazımı, karakter sesi ve tekrar eden kalıp kararlarını satır satır düzenler.
- `qbit`, `downloads`, `Season 1` gibi genel klasörler otomatik eşleştirme ipucu olarak kaydedilmez. Birden fazla seri eşleşirse seçim kullanıcıya bırakılır.

Seri deposu uygulama dizinindedir (`series\`). Yazma korumalı bir klasörde (örn. `C:\Program Files`) başarısız olursa anlamlı hata verilir.

Çeviri tamamlandığında bölüm, seriye `episodes` listesine eklenir.

---

## 6. Sorun giderme

### 6.1 `ffprobe bulunamadi` / `ffmpeg bulunamadi`
`bin\` klasörüne `ffprobe.exe` ve `ffmpeg.exe` koyun. Ya da FFmpeg'i sistem `PATH`'ine ekleyin.

### 6.2 Model metin döndürmüyor (boş yanıt)
Hata mesajında `finish_reason=length` ve yüksek `dusunce_token` görürseniz, model **düşünmeye tüm token bütçesini harcıyor** demektir.

Çözümler:
1. **LM Studio model preset'inden thinking/reasoning'i kapatın** (kalıcı çözüm).
2. `config.json` içinde `disable_thinking` değerini `true` deneyin (LM Studio sürümü destekliyorsa).
3. `max_tokens` değerini artırın ve `batch_cues` değerini küçültün.

### 6.3 `Kontrol noktasi bu altyazi/ayarlarla uyusmuyor`
Altyazı, ayarlar (model, glossary, prompt, parti boyutu) veya çeviri protokolü değiştiğinde eski checkpoint kullanılamaz. GUI için çalışan uygulamanın yanındaki `work_files/<video-adı>.state.json` dosyasını yedekleyip yeniden adlandırın ve baştan başlayın. EXE kullanıyorsanız `work_files` EXE'nin yanındadır. F30 güncellemesi eski çeviri checkpoint'lerini bilerek kabul etmez; daha önce yanlış eşlenmiş metinler yeni çıktıya taşınmaz. Ön analiz checkpoint'ini bu nedenle silmek gerekmez.

### 6.4 `Yapisal altyazi isaretleri korunmadi`
Bu hata normal akışta görülmemelidir: model satır sayısını bozsa bile çıktı kaynak yapıya göre **otomatik yeniden bölünür** (log: `BILGI: model satir sayisini degistirdi ... yeniden bolundu.`). Hatayı yine de görürseniz log ile birlikte bildirin.

### 6.5 `Goruntu tabanli altyazi - su anda desteklenmiyor`
Seçilen akış PGS/VobSub gibi görüntü tabanlıdır; metin çevirisi yapılamaz. Varsa metin tabanlı bir akış seçin.

### 6.6 `Bu seri/sozluk dosyasi baska bir Aktar ornesi tarafindan kullaniliyor`
Aynı seri dosyasına başka bir Aktar penceresi erişiyor. Diğer pencereleri kapatıp yeniden deneyin.

### 6.7 Seri sözlüğü kaydedilemiyor
Uygulama korumalı bir klasörde (örn. `C:\Program Files`) çalışıyor olabilir. Uygulamayı yazma izni olan bir klasöre taşıyın.

### 6.8 Çeviride Türkçe harfler görünmüyor (kutu/boş kare)
Kaynak ASS/SSA fontu Türkçe karakterleri desteklemiyor olabilir. Aktar bu durumda çıktıdaki fontu **Calibri** ile değiştirir; konsolda `Font uyarısı: ... Calibri kullanıldı (...)` mesajını görürsünüz. Türkçe harfler hâlâ görünmüyorsa oynatıcıda Calibri kurulu değil ya da gömülü font (attached fonts) kullanılıyor olabilir; oynatıcının font ayarını kontrol edin.

---

## 7. Komut satırı

Arayüz olmadan da kullanılabilir (aynı çekirdeği paylaşır):

```bat
py -3 cevir.py check
py -3 cevir.py streams "C:\video\Movie.mkv"
py -3 cevir.py extract "C:\video\Movie.mkv" --stream 2
py -3 cevir.py translate "C:\video\Movie.ass" --series game-of-thrones --glossary "Ash=Kul"
```

- `check` — ffmpeg/ffprobe bulunabilirliği ve yapılandırma geçerliliği.
- `streams` — videodaki altyazı akışlarını listeler.
- `extract --stream N` — seçilen global stream index'i çıkarır.
- `translate` — altyazıyı Türkçeye çevirir; `--series` ve `--glossary Kaynak=Karşılık` (çoklanabilir).

---

## 8. Gizlilik ve veri

- Tüm çeviri yerel LM Studio sunucusunda yapılır; **internete veri gitmez**.
- `base_url` yalnızca yerel adres olabilir.
- Kaynak video **salt-okunur**: kopyalanmaz, taşınmaz, değiştirilmez, yeniden encode edilmez.
- Seri sözlükleri uygulama dizinindeki `series\` klasöründe tutulur (kullanıcı verisi; sürüm kontrolüne girmez).

### 6.7 `Yanıt doğrulanamadı; ... parti ... bölünüyor`
Model çoklu istekte ID'leri düşürmüş, girdileri eksik döndürmüş veya token sınırına ulaşmış olabilir. Program aynı partiyi daha küçük parçalara ayırıp tekrar dener; gerekirse tek girdiye iner. Başarılı alt partiler kaydedilir. Tek girdide de hata sürerse işlem durur; konsoldaki hatayı ve LM Studio'nun ham yanıtını inceleyin. Bu mekanizma yanlış sıralanmış cevapları sessizce kabul etmez; çevirinin anlamsal doğruluğunu otomatik olarak garanti etmez.
