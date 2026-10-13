# Aktar — Kullanım Kılavuzu

Bu kılavuz son kullanıcı içindir: kurulum, LM Studio ayarı, bütün akışlar (Kütüphane ve Altyazı Çevir sekmeleri, videoya soru sorma), terim sözlüğü (glossary), seri ayarları ve sorun giderme.

---

## 1. Kurulum

### 1.1 Kaynak koddan çalıştırma

Linux için bkz. **1.6**.

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
1. İsterseniz `bin` klasörüne `ffmpeg.exe` ve `ffprobe.exe` dosyalarını yerleştirdikten sonra uygulamayı .exe olarak derleyebilirsiniz. FFmpeg lisansından dolayı GitHub sayfasında derlenmiş .exe sunulmuyor.
2. `DERLE.cmd` dosyasını çalıştırarak `dist\Aktar.exe` dosyasını oluşturabilirsiniz.
3. Konuşmadan metin (Whisper) `Aktar.exe`'ye gömülmez; ayrı bir paket olarak derlenip yanına konur (bkz. 1.5 → "Derlenmiş .exe ile").

### 1.5 İsteğe bağlı: konuşmadan metin (Whisper)
Altyazısı olmayan videolarda **Soru Sor** sekmesi konuşmayı sesten metne çevirebilir (faster-whisper). Bu özellik isteğe bağlıdır; yoksa uygulama bunu söyler, geri kalan her şey çalışır.

**Kaynak koddan çalıştırırken:**

```bat
py -3 -m pip install -r requirements-whisper.txt
```

**Derlenmiş .exe ile:** Whisper, `ffmpeg`'in `bin` klasöründe ayrı durması gibi ayrı bir paket olarak çalışır. `Aktar.exe` bu paketi kendi klasöründe bulursa kullanır.

1. Derleme yapacağınız bilgisayarda Whisper bağımlılıklarını kurun:

   ```bat
   py -3 -m pip install -r requirements.txt -r requirements-whisper.txt
   ```

2. GPU için aşağıdaki **NVIDIA GPU** bölümüne bakın. Kütüphaneleri zaten başka bir klasörde tutuyorsanız (A seçeneği) bu adımda bir şey yapmanız gerekmez.
3. `DERLE_WHISPER.cmd` dosyasını çalıştırın. Çıktı `dist\aktar-whisper\` klasörüdür.
4. Bu klasörü olduğu gibi `Aktar.exe`'nin yanına koyun:

   ```
   Aktar.exe
   aktar-whisper\aktar-whisper.exe   (+ _internal\ klasörü)
   models\whisper\                   (ilk kullanımda otomatik oluşur)
   ```

Paket boyutu GPU kütüphaneleri olmadan ~270 MB, pakete gömülü NVIDIA kütüphaneleriyle ~2.1 GB'tır. Whisper'a ihtiyaç duymayanlar paketi hiç kopyalamaz; `Aktar.exe` küçük kalır.

- Model ilk kullanımda uygulama klasöründeki `models\whisper\` altına indirilir (varsayılan **large-v3-turbo**, ~1.6 GB; bir kez internet gerekir).
- **NVIDIA GPU ile hızlandırma (önerilir):** Whisper'ın GPU'da çalışması için **cuBLAS 12** ve **cuDNN 9** DLL'leri gerekir. İki yol var:
  - **A) Mevcut klasörünüzü gösterin (önerilir, başka programlarla ortak):** Bu DLL'leri zaten bir klasörde tutuyorsanız tekrar indirmeyin. Klasörde örneğin `cublas64_12.dll`, `cublasLt64_12.dll`, `cudnn64_9.dll`, `cudnn_ops64_9.dll` ... bulunur.
    1. Aktar'da **Ayarlar → Soru Sor · konuşmadan metin (Whisper) → GPU kütüphane klasörü** alanına klasörü yazın ya da **Gözat...** ile seçin.
    2. Alanın altında `cuBLAS 12 ve cuDNN 9 bulundu.` yazmalı.

    Kaynak koddan çalışırken de, `aktar-whisper` paketiyle de bu klasör kullanılır. Paketi NVIDIA kütüphaneleri olmadan, yani küçük haliyle (~270 MB) derlemeniz yeterlidir.
  - **B) pip ile kurun:**

    ```bat
    py -3 -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*
    ```

    `DERLE_WHISPER.cmd` bunları bulursa pakete gömer (~2.1 GB). Bu yüzden derlenmiş paket için bu adımı `DERLE_WHISPER.cmd`'den önce yapın.

  Cihaz ayarı `auto` iken GPU varsa önce o denenir. Konsolda önce `GPU kütüphaneleri: cublas (...), cudnn (...)` satırı görünür. Kütüphaneler eksikse ya da GPU çalışmazsa nedeni yazılır ve işlemciyle devam edilir (çok daha yavaş).

### 1.6 Linux (Debian, Ubuntu, Fedora; KDE Plasma, GNOME)
Aktar Linux'ta kaynak koddan çalışır. Arayüz Qt (PySide6) olduğu için KDE Plasma'da hem Wayland hem X11 oturumunda doğal görünür. Windows betikleri (`.cmd`) yerine aynı işi yapan `.sh` betikleri vardır:

| Windows | Linux | Ne yapar |
|---|---|---|
| `py -3 -m pip install -r requirements.txt` | `./kur.sh` | `.venv` sanal ortamını oluşturur, paketleri kurar |
| `GUI_BASLAT.cmd` | `./baslat.sh` | Arayüzü başlatır |
| `DERLE.cmd` | `./derle.sh` | Tek dosya `dist/Aktar` derler |
| `DERLE_WHISPER.cmd` | `./derle_whisper.sh` | `dist/aktar-whisper/` paketini derler |

**Kurulum (Debian 12/13, Ubuntu 22.04+):**

```bash
sudo apt install python3-venv ffmpeg fontconfig libxcb-cursor0
./kur.sh --kisayol
./baslat.sh
```

- Debian/Ubuntu sistem Python'una doğrudan `pip install` yaptırmaz; bu yüzden `kur.sh` paketleri proje klasöründeki `.venv` içine kurar. `baslat.sh` bu ortamı kendiliğinden kullanır.
- `--kisayol`, uygulama menüsüne **Aktar** kısayolu ekler. Dosya yöneticisinde (Dolphin) bir videoya sağ tıklayıp **Birlikte Aç → Aktar** dediğinizde video doğrudan açılır.
- `--whisper` konuşmadan metni (faster-whisper) kurar. `--gpu` buna ek olarak NVIDIA CUDA 12 kütüphanelerini (cuBLAS, cuDNN) `.venv` içine kurar. Seçenekler birlikte verilebilir: `./kur.sh --gpu --kisayol`.
- **FFmpeg:** Sistemdeki `ffmpeg`/`ffprobe` kullanılır (`sudo apt install ffmpeg`). `bin/` içindeki Windows `.exe` dosyaları Linux'ta yok sayılır. Taşınabilir Linux ikilileri isterseniz `bin/ffmpeg` ve `bin/ffprobe` olarak koyun.
- **LM Studio:** Linux sürümü (AppImage) [lmstudio.ai](https://lmstudio.ai) adresinden indirilir. Sunucu ayarı Windows'takiyle aynıdır (1.3).
- **Türkçe font kontrolü (3.5):** Linux'ta `fontconfig` (`fc-list`) ile yapılır. Calibri Linux'ta genellikle kurulu değildir; oynatıcı (mpv, VLC) onun yerine benzer bir font kullanır. Calibri ile aynı ölçülere sahip açık kaynak **Carlito** fontunu kurmanız önerilir: `sudo apt install fonts-crosextra-carlito`.
- **NVIDIA GPU (Whisper):** `./kur.sh --gpu` yeterlidir. Kütüphaneleri başka bir klasörde tutuyorsanız Ayarlar'daki **GPU kütüphane klasörü** alanına o klasörü gösterin; klasörde `libcublas.so.12` ve `libcudnn.so.9` bulunmalıdır. NVIDIA sürücüsü kurulu değilse Whisper işlemciyle çalışır.
- **Derleme:** Önce `sudo apt install libpython3-dev` (PyInstaller Python kütüphanesini pakete koyar). `./derle.sh` ile oluşan `dist/Aktar`, derlendiği dağıtımdaki glibc sürümüne bağlıdır. Birden fazla dağıtımda çalışacaksa en eski hedef sistemde derleyin. Whisper paketi `./derle_whisper.sh` ile derlenir ve `dist/aktar-whisper/` klasörü `Aktar`'ın yanına konur.

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
  "disable_thinking": true,
  "qa_context_chars": 24000,
  "whisper_model": "large-v3-turbo",
  "whisper_device": "auto",
  "whisper_language": ""
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
| `qa_context_chars` | Soru Sor: modele tek istekte gidecek en fazla transkript karakteri (≥1000). Transkript sığmazsa video haritası kullanılır (bkz. 3.6). LM Studio'daki model bağlam uzunluğuna göre ayarlayın. |
| `embedding_model` | Kütüphane indeksi için LM Studio embedding modeli (ör. `text-embedding-embeddinggemma-2`). Boş: indeksleme kapalı, yalnızca transkript çıkarılır. Ayarlar → **Kütüphane indeksi**. |
| `embedding_query_template` / `embedding_document_template` | Embedding modeline gönderilen metnin biçimi. Varsayılanlar EmbeddingGemma içindir (`task: search result \| query: {query}`, `title: {title} \| text: {text}`); başka bir embedding modeli kullanıyorsanız modelin önerdiği biçimi yazın. `{query}` / `{text}` zorunludur. |
| `whisper_model` | Konuşmadan metin modeli: `large-v3-turbo` (varsayılan), `large-v3`, `medium`, `small`, `base`. |
| `whisper_device` | `auto` (GPU varsa GPU), `cuda` veya `cpu`. |
| `whisper_language` | Konuşma dili kodu (örn. `en`, `ja`); boşsa otomatik algılanır. |
| `whisper_cuda_dir` | Başka programlarla ortak kullanılan cuBLAS 12 / cuDNN 9 DLL klasörü (örn. `Z:\Ai Tools\cuBLAS and cuDNN`); boşsa pip ile kurulan veya pakete gömülü kütüphaneler aranır. |

Bu ayarların hepsi **Ayarlar** penceresinden de değiştirilebilir.

> `base_url` **yalnızca yerel** olabilir; uzak adres reddedilir (gizlilik ilkesi).

---

## 3. Arayüz akışı

Başlık şeridindeki **Kütüphane | Altyazı Çevir** seçicisiyle iki sekme arasında geçilir. Uygulama Kütüphane sekmesiyle açılır. Video Seç, Seri, Terim ve Süreklilik düğmeleri yalnızca Altyazı Çevir sekmesinde görünür. 3.0 Kütüphaneyi, 3.1–3.5 Altyazı Çevir sekmesini, 3.6 videoya soru sormayı anlatır.

### 3.0 Kütüphane
Videolarınızı ve belgelerinizi **koleksiyonlarda** toplar (ör. "Makine Öğrenmesi", "Kullanım Kılavuzları").

**Desteklenen dosyalar:** videolar (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`, `.ts`, `.wmv`, `.flv`) ve belgeler: **PDF** (metin katmanı okunur), **.txt** ve **.md**. Belgelerde konum dakika yerine sayfadır: atıflar `V5 s.12` biçimindedir, tıklayınca PDF uygulama içinde o sayfada açılır. Belgeye çift tıklayınca görüntüleyicinin sağında **Bu belgeye sor** alanı açılır: belgenin metni hemen çıkarılır; kısa belgede metnin tamamı, uzun belgede (embedding modeli seçiliyse) soruyla ilgili bölümler modele verilir, cevaptaki `s.N` atıfına tıklayınca belge o sayfaya gider (metin dosyaları 60 satırlık sayfalara bölünür). Taranmış (metin katmanı olmayan) PDF'ler şimdilik okunmaz; tabloda **Metin yok (taranmış PDF)** görünür. Görseller, Word ve Excel sonraki sürümlerde gelecek.

- **İlk açılış:** Henüz koleksiyon yoksa ortada **Klasör veya dosya bırak** alanı görünür. Bir klasör bırakın ya da **Klasör seç** / **Dosya seç** ile seçin; klasörün adıyla bir koleksiyon oluşur.
- **Koleksiyonlar (sol):** Koleksiyona tıklayınca içeriği açılır. **Yeni koleksiyon** ile boş bir koleksiyon oluşturulur. Sağ tık: **Yeniden adlandır**, **Yeniden tara**, **Koleksiyonu dışa aktar (Markdown)…** (açık koleksiyonun tüm transkriptleri tek dosyada; koleksiyon ve video özetleri varsa başlarında), **Koleksiyonu sil**. Silme yalnızca koleksiyon kaydını siler; dosyalarınız diskte kalır.
- **Kaynak klasörler (sol alt):** Klasörler alt klasörleriyle birlikte taranır (gizli ve sistem klasörleri atlanır). Koleksiyon her açıldığında klasörler yeniden taranır: yeni bulunan videolar adının yanında **yeni** ile işaretlenir, diskten silinen ya da takılı olmayan diskteki videolar **Bulunamadı** olarak listede kalır. Sağ tık: **Klasörü aç**, **Koleksiyondan kaldır**.
- **Klasör ekle / Dosya ekle:** Açık koleksiyona klasör veya tek tek video ekler. Klasör ve videolar sayfaya sürüklenerek de eklenebilir.
- **Dosya tablosu:** Dosya adı, bulunduğu alt klasör, süre (hazırlanmamışsa dosya boyutu), metin kaynağı (Altyazı · dil / Whisper · model) ve durum (**Hazır**: transkript çıkarılmış ve aranabilir indekse eklenmiş; **Metin hazır**: transkript var, indeks yok ya da embedding modeli seçilmemiş; **Bekliyor**; **Altyazı yok · Whisper bekliyor**; **Bulunamadı**). 
- **Arama kutusu:** Dosya adında ve transkriptlerde model kullanmadan anında arar (en az 3 harf). Büyük/küçük harf ve Türkçe karakter farkı yok sayılır (`asiri` = `aşırı`); birden çok kelime yazılırsa hepsi aynı satırda geçmelidir. Eşleşen transkript satırları tablonun üstünde listelenir (video · dakika · metin); tıklayınca video o anda açılır. Tablo da yalnızca adı ya da transkripti eşleşen dosyalara süzülür.
- **Videoya çift tıklayınca** oynatıcı ve soru-cevap açılır (bkz. 3.6); sol üstteki geri düğmesi listeye döndürür.
- **Sağ tık menüsü:** **Oynat ve soru sor**, **Altyazıyı çevir…** (videoyu Altyazı Çevir sekmesinde açar), **Dosya konumunu aç**, **Transkripti dışa aktar…**, **Koleksiyondan çıkar** (dosya diskte kalır; birden çok satır seçilebilir).
- **Transkripti dışa aktar:** Transkripti olan videolar için. Tek video seçiliyse kayıt penceresinde biçim seçilir: **Metin** (`[m:ss] satır`), **Altyazı (SRT)** (zamanlı altyazı; oynatıcılarda açılabilir) veya **Markdown** (video özeti varsa başta). Birden çok video seçiliyse önce biçim, sonra klasör sorulur; her video `<video adı>.<uzantı>` olarak yazılır, var olan dosyanın üzerine yazılmaz (`(2)` eklenir). Kaynak videolara dokunulmaz.
- **Hepsini hazırla:** Belgelerin metni hızlıca çıkarılır (**Belgelerden metin**). Koleksiyondaki tüm videoların transkriptini sırayla çıkarır ve aranabilir indekse ekler. İndeks için Ayarlar → **Kütüphane indeksi** bölümünden bir embedding modeli seçilmelidir (LM Studio'da indirilmiş olması yeterli; ilk istekte yüklenir). Transkript ~90 saniyelik parçalara bölünür ve her parça vektöre çevrilir; seçilmezse yalnızca transkript çıkarılır. Açılan pencere videoları yoklar ve gruplara ayırır: **Zaten hazır** (tekrar işlenmez), **Yalnızca özeti eksik**, **Yalnızca indekslenecek** (transkript var, indeks yok), **Gömülü altyazıdan** (hızlı; şarkı/yazı izleri atlanır) ve **Altyazı yok → Whisper** (toplam ses süresiyle). Whisper yalnızca bu penceredeki **Altyazısız videolarda Whisper kullan** anahtarı açıksa çalışır; kapalıysa bu videolar atlanır ve tabloda **Altyazı yok · Whisper bekliyor** olarak görünür. Sıra: önce altyazılı videolar, sonra Whisper.
  - Çalışırken tablonun üstündeki şerit ilerlemeyi gösterir; satırlarda **Sırada**, **İşleniyor…**, **Whisper %42** gibi durumlar görünür. **Duraklat** sıradaki videodan önce bekler (Whisper bir videoyu bitirmeden durmaz); **Durdur** işi keser, yarım kalan video bir sonraki sefere baştan yapılır. Hazırlanan transkriptler önbelleğe yazılır; videoya çift tıklayınca beklemeden kullanılır.
  - **Dosya özetleri ve koleksiyon özeti çıkar** (varsayılan açık): her videonun ve belgenin genel özeti sohbet modeliyle çıkarılır (videoya çift tıklayınca açılan ekrandaki özetle aynıdır; orada tekrar beklenmez), en sonda bu özetlerden **koleksiyon özeti** üretilir. Video başına birkaç model isteği yapılır; uzun videolarda önce bölüm özetleri çıkarıldığı için dakikalar sürebilir. Kapalıysa yalnızca transkript ve indeks hazırlanır.
  - Hata veren videolar (ör. seste konuşma yoksa) atlanır ve sonunda listelenir; ayrıntılar Altyazı Çevir sekmesindeki konsoldadır.
- **Koleksiyona sor (sağ panel):** Koleksiyondaki **Hazır** (indeksli) videoların hepsine birden soru sorarsınız. Soru önce indekste aranır, en ilgili transkript parçaları sohbet modeline verilir; cevap Türkçedir ve iddialar `V3 12:34` gibi atıflarla desteklenir (V3 = koleksiyondaki 3. dosya). Cevabın altındaki **Kaynaklar** satırı hangi videonun kaç kez kaynak gösterildiğini listeler.
  - Atfa tıklayınca o video oynatıcıda açılır ve o ana gider; geri düğmesiyle sohbete dönersiniz, sohbet kaybolmaz.
  - **Kapsam:** **Tüm koleksiyon** ya da **Seçili dosyalar** (tabloda seçtiğiniz satırlar). Henüz hazır olmayan dosyalar cevaba dahil edilmez; panelin altındaki not kaç dosyanın beklediğini söyler.
  - Önceki sorular hatırlanır; "peki neden?" gibi devam soruları çalışır. Her koleksiyonun sohbeti ayrıdır ve `library\` klasörüne kaydedilir (son 50 soru); uygulama yeniden açılınca kaldığı yerden devam eder. Panelin sağ üstündeki çöp kutusu sohbeti ve kaydını siler; koleksiyon silinince sohbeti de silinir.
  - Soru-cevap için Ayarlar'daki sohbet modeli, arama için embedding modeli kullanılır; ikisi de LM Studio'da aynı adresten çalışır. Koleksiyon özeti çıkarıldıysa sohbetin başında bir kartta görünür (genel özet, konular ve tıklanınca sorulan önerilen sorular); bu özet ve video özetleri her soruda modele de verilir, böylece "bu derslerde neler anlatılıyor?" gibi genel sorular da bütün koleksiyona göre cevaplanır. Özet yoksa genel sorular yalnızca soruya en yakın parçalarla cevaplanır.

Koleksiyonlar uygulama dizinindeki `library\` klasöründe tutulur.

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

### 3.6 Videoya soru sorma (Kütüphane → videoya çift tıklama)
Video hakkında yerel modelle soru sormanızı sağlar: solda video oynatıcı, sağda yerel modelle sohbet.

**Hazırlık.** Video ilk açıldığında videonun transkripti çıkarılır ve model videoya genel bir bakış hazırlar. Bu sırada videoya özel önerilen sorular da üretilir. Sonuç `work_files\qa\` altında saklanır, aynı video tekrar açıldığında hesaplanmaz.
- Transkript kaynağı varsayılan olarak videodaki metin altyazısıdır. Birden fazla altyazı varsa **Transkript** seçicisinden değiştirilebilir. Seçicideki **Sesten (Whisper)** seçeneği konuşmayı sesten metne çevirir (bkz. 1.5). Videoda birden fazla ses parçası varsa (örneğin `.mkv` içinde Japonca ve İngilizce) her parça ayrı **Sesten (Whisper) · <parça>** seçeneği olarak listelenir; Whisper'a hangi sesin gideceğini buradan seçersiniz. Her parçanın transkripti ayrı önbelleğe alınır.
- Altyazısı olmayan videoda **Sesten transkript çıkar (Whisper)** önerisi çıkar. Model büyük olduğu için işlem otomatik başlamaz.
- Kısa videolarda modele transkriptin tamamı gider. Transkript `qa_context_chars` sınırını aşarsa video bölümlere ayrılır (videoda gömülü bölüm/chapter varsa onlar, yoksa ~4 dakikalık parçalar) ve her bölüm özetlenir. Böylece uzun videolarda da genel sorular cevaplanabilir.

**Soru sorma.** Önerilen sorulardan birine tıklayın ya da kendi sorunuzu yazın. "Videoyu özetle", "Sonunda ne oluyor?" gibi genel sorular da, belirli ayrıntılar da sorulabilir. Önceki konuşma hatırlanır, yani "peki neden?" gibi devam soruları çalışır.
- Cevaplar Türkçedir. İddialar zaman damgasıyla desteklenir: tek an için `12:34`, bir aralık için `3:10-7:45`.
- Zaman damgasına tıklayınca video o ana gider ve oynamaya başlar.
- Transkriptte karşılığı olmayan (uydurma) zaman damgaları cevaptan çıkarılır.
- Model videoda geçmeyen genel bilgi eklerse bunu "videoda geçmiyor" diye belirtir.

**Oynatıcı.**
- Videoya tıklamak veya **Boşluk** tuşu oynatır/duraklatır. **←/→** 5 saniye geri/ileri sarar.
- Arama çubuğu videonun bölümlerine göre parçalıdır. Üzerine gelince zaman ve bölüm adı görünür.
- Listeye dönünce ya da Altyazı Çevir sekmesine geçince video duraklar. Aynı videoyu tekrar açarsanız sohbet ve video konumu korunur; başka bir video açılınca önceki sohbet kapanır.
- **Ses parçası (kulaklık düğmesi):** Videoda birden fazla ses parçası varsa CC düğmesinin solunda görünür. Oynatılan sesi buradan değiştirirsiniz; video konumu korunur.

**Altyazılar (CC düğmesi).** Oynatıcının sağ altındaki CC düğmesi şunları listeler:
- **Kapalı**
- **Videodaki altyazılar** (metin tabanlı akışlar)
- **Video klasöründeki dosyalar:** videoyla aynı adla başlayan `.srt`/`.ass`/`.ssa`/`.vtt` dosyaları. Aktar'ın `<video>_TR` çevirisi de burada çıkar, yani çeviriyi oynatıcıda doğrudan izleyebilirsiniz.
- **Sesten (Whisper):** Whisper transkripti varsa seçilebilir; yoksa **Sesten oluştur...** ile çıkarılır. Birden fazla ses parçası varsa **Sesten oluştur** alt menüsünden Whisper'a gidecek parça seçilir.

ASS altyazılarda stil ve konum gösterilmez, yalnızca metin görünür. Ekranda gösterilen altyazı ile soru-cevabın kullandığı transkript birbirinden bağımsızdır.

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
`bin\` klasörüne `ffprobe.exe` ve `ffmpeg.exe` koyun. Ya da FFmpeg'i sistem `PATH`'ine ekleyin. Linux'ta: `sudo apt install ffmpeg` (bkz. 1.6).

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
Kaynak ASS/SSA fontu Türkçe karakterleri desteklemiyor olabilir. Aktar bu durumda çıktıdaki fontu **Calibri** ile değiştirir; konsolda `Font uyarısı: ... Calibri kullanıldı (...)` mesajını görürsünüz. Türkçe harfler hâlâ görünmüyorsa oynatıcıda Calibri kurulu değil ya da gömülü font (attached fonts) kullanılıyor olabilir; oynatıcının font ayarını kontrol edin. Linux'ta Calibri yerine Carlito fontunu kurun (`sudo apt install fonts-crosextra-carlito`).

### 6.9 `Yanıt doğrulanamadı; ... parti ... bölünüyor`
Model çoklu istekte ID'leri düşürmüş, girdileri eksik döndürmüş veya token sınırına ulaşmış olabilir. Program aynı partiyi daha küçük parçalara ayırıp tekrar dener; gerekirse tek girdiye iner. Başarılı alt partiler kaydedilir. Tek girdide de hata sürerse işlem durur; konsoldaki hatayı ve LM Studio'nun ham yanıtını inceleyin. Bu mekanizma yanlış sıralanmış cevapları sessizce kabul etmez; çevirinin anlamsal doğruluğunu otomatik olarak garanti etmez.

### 6.10 Soru Sor: `HTTP 400: LM Studio istegi reddedildi`
Transkript modelin bağlam uzunluğuna sığmıyor. LM Studio'da modelin **Context Length** ayarını artırın (varsayılan `qa_context_chars` 24000 için en az ~12k token önerilir) veya Ayarlar → Gelişmiş → **Soru-cevap bağlam karakteri** değerini düşürün.

### 6.11 Soru Sor: Whisper GPU kullanmıyor / çok yavaş
Konsolda `Whisper cuda ile çalışamadı: ...` görüyorsanız:
- `GPU kütüphaneleri: bulunamadı` yazıyorsa CUDA kütüphaneleri eksiktir. Ayarlar'da **GPU kütüphane klasörü** alanına mevcut cuBLAS/cuDNN klasörünüzü gösterin ya da 1.5'teki B seçeneğini uygulayın.
- `UYARI: GPU kütüphane klasöründe eksik: ...` yazıyorsa gösterdiğiniz klasörde listelenen DLL yoktur; doğru klasörü seçtiğinizi kontrol edin.
- `CUDA driver version is insufficient` yazıyorsa NVIDIA sürücüsünü güncelleyin.
- Linux'ta `GPU kütüphaneleri: bulunamadı` yazıyorsa NVIDIA sürücüsü yüklü değildir (`nvidia-smi` çalışmalı) ya da `./kur.sh --gpu` henüz çalıştırılmamıştır.

Başarılı olunca konsolda `cihaz: cuda` yazar. GPU'suz bilgisayarda Ayarlar'dan daha küçük bir model (`small`) seçebilirsiniz.

### 6.12 Soru Sor: `Konuşmadan metin (Whisper) paketi bulunamadı`
Derlenmiş `Aktar.exe` (Linux'ta `Aktar`) kullanıyorsunuz ve yanında `aktar-whisper` klasörü yok. 1.5'teki "Derlenmiş .exe ile" adımlarını izleyin. Paket varsa ama hata veriyorsa mesajın sonundaki ayrıntıya bakın; paketin kendi hata çıktısı oraya eklenir.

### 6.13 Soru Sor: video oynatılmıyor
Oynatıcı Qt Multimedia'nın FFmpeg altyapısını kullanır. Hata mesajı sohbet alanına yazılır. Videonun başka bir oynatıcıda açıldığını kontrol edin. Soru-cevap ve altyazı çıkarma oynatma olmadan da çalışır.

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

- Tüm çeviri ve soru-cevap yerel LM Studio sunucusunda yapılır; **internete veri gitmez**.
- Konuşmadan metin (Whisper) tamamen bilgisayarınızda çalışır. Yalnızca modelin kendisi ilk kullanımda Hugging Face'ten indirilir; video, ses veya metin gönderilmez.
- `base_url` yalnızca yerel adres olabilir.
- Kaynak video **salt-okunur**: kopyalanmaz, taşınmaz, değiştirilmez, yeniden encode edilmez.
- Seri sözlükleri uygulama dizinindeki `series\` klasöründe tutulur (kullanıcı verisi; sürüm kontrolüne girmez).
- Kütüphane koleksiyonları `library\` klasöründe tutulur; yalnızca dosya yollarını içerir, dosyaların kendisi kopyalanmaz.
- Soru Sor transkriptleri, video haritası ve Whisper sonuçları `work_files\qa\` altında, kütüphane indeksi (embedding vektörleri) `work_files\index\` altında önbelleğe alınır. Silmek güvenlidir; gerekirse yeniden üretilir.
