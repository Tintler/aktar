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

`requirements.txt`: `pywebview` (pencere), `pypdfium2` ve `Pillow` (PDF ve görseller), `PyInstaller`.

Arayüz Svelte ile yazılmış bir web arayüzüdür ve uygulama penceresinde (Windows'ta WebView2, Linux'ta WebKitGTK) açılır. Kaynak koddan çalıştırmak için **Node.js** gerekir ([nodejs.org](https://nodejs.org)): `GUI_BASLAT.cmd` ilk açılışta `web\` klasöründe bağımlılıkları kurar ve arayüzü her açılışta derler (~1 sn). Derlenmiş `Aktar.exe` için Node.js gerekmez.

### 1.2 FFmpeg / ffprobe

Uygulama, videoyu okumak ve altyazı akışını çıkarmak için FFmpeg kullanır. İkililer **projeye taşınabilir** olarak konur:

```
Aktar\bin\ffmpeg.exe
Aktar\bin\ffprobe.exe
```

`bin\` içinde bulunmazsa sistem `PATH`'indeki `ffmpeg`/`ffprobe` denenir. Bulunamazsa uygulama anlamlı bir hata verir:

> `ffprobe bulunamadi. Uygulama klasorundeki "bin" dizinine ffprobe.exe dosyasini koyun.`

FFmpeg'i [ffmpeg.org](https://ffmpeg.org/download.html) üzerinden indirip `bin` klasörüne kopyalayabilirsiniz. Sistem geneline kurmak zorunlu değildir.

### 1.3 Model sunucusu (LM Studio, Ollama, llama.cpp, OpenAI…)

**LM Studio** (varsayılan):
1. LM Studio'yu açın ve kullanmak istediğiniz modeli yükleyin.
2. **Developer / Local Server** sekmesinden yerel sunucuyu başlatın (varsayılan `http://127.0.0.1:1234`).
3. Modeli **thinking/reasoning kapalı** olacak şekilde ayarlayın (aşağıda 6.2'ye bakın).

**OpenAI uyumlu sunucular:** **Ayarlar → Modeller → Hazır ayar** listesinden Ollama (`http://127.0.0.1:11434/v1`), llama.cpp `llama-server` (`http://127.0.0.1:8080/v1`), vLLM, OpenAI ya da OpenRouter seçilir. Bu, adresi ve **Sunucu türünü** (*OpenAI uyumlu*) doldurur. Anahtar isteyen sunucular için **API anahtarı** alanına anahtarı girip **Kaydet**'e basın. Anahtar config.json'a yazılmaz; Windows Kimlik Bilgileri'nde (Linux'ta Secret Service) `Aktar/llm-api-key` adıyla saklanır. `AKTAR_API_KEY` ya da `LM_STUDIO_API_KEY` ortam değişkeni de kullanılabilir.

- Bu bilgisayar ve yerel ağ (`192.168.x.x`, `10.x.x.x`, `.local`, tek parçalı makine adı, Tailscale `100.64.x.x`) için `http`, internetteki sunucular için `https` zorunludur.
- İnternetteki bir sunucu seçilince Ayarlar'da metinlerin bilgisayardan çıkacağı uyarısı görünür.
- OpenAI uyumlu türde LM Studio'ya özgü istekler (modeli kalıcı yükleme, yüklü modelin bağlam uzunluğu) yapılmaz. Kitap çevirisi bağlam uzunluğu olarak **Ayarlar → Kitap çevirisi → Yedek context** değerini kullanır. İnternetteki sunuculara düşünme (thinking) için standart dışı alanlar gönderilmez.
- Küçük modeller (1–2 milyar parametre) altyazıyı çevirebilir, ama kitap çevirisinde bitiş işaretini sık atlar. Kitap için en az 4 milyar parametreli bir model ya da **Ayarlar → Kitap çevirisi**'nde bitiş işaretinin kapatılması önerilir.

**Bileşen denetimi:** İlk açılışta model sunucusu, FFmpeg, embedding modeli, Whisper, ses motoru, Tesseract, libmpv ve Calibre denetlenir; eksik olanların nasıl kurulacağı ve ilgili ayar gösterilir. **Ayarlar → Gelişmiş → Bileşen denetimi** ile yeniden açılır.

### 1.4 aktar.exe derlemesi
1. İsterseniz `bin` klasörüne `ffmpeg.exe` ve `ffprobe.exe` dosyalarını yerleştirdikten sonra uygulamayı .exe olarak derleyebilirsiniz. FFmpeg lisansından dolayı GitHub sayfasında derlenmiş .exe sunulmuyor.
2. `DERLE.cmd` dosyasını çalıştırarak `dist\Aktar.exe` dosyasını oluşturabilirsiniz. Betik önce web arayüzünü derler; bunun için Node.js kurulu olmalıdır.
3. Konuşmadan metin (Whisper) `Aktar.exe`'ye gömülmez; ayrı bir paket olarak derlenip yanına konur (bkz. 1.5 → "Derlenmiş .exe ile").

### 1.5 İsteğe bağlı: konuşmadan metin (Whisper)
Altyazısı olmayan videolarda **Soru Sor** sekmesi konuşmayı sesten metne çevirebilir (faster-whisper). Bu özellik isteğe bağlıdır; yoksa uygulama bunu söyler, geri kalan her şey çalışır.

Aynı paket (`requirements-whisper.txt` içindeki **sherpa-onnx**) dublajda **ses ayırmayı** (konuşma / müzik ve efektler) ve **konuşmacı ayrımını** da yapar. Modelleri ilk kullanımda `models\sherpa` altına bir kez indirilir (ses ayırma ~65 MB, konuşmacı ayrımı ~30 MB); sonra internet kullanılmaz.

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
Aktar Linux'ta kaynak koddan çalışır. Pencere WebKitGTK ile açılır (KDE Plasma ve GNOME'da, Wayland ve X11 oturumunda); videolar GStreamer ile oynatılır. Windows betikleri (`.cmd`) yerine aynı işi yapan `.sh` betikleri vardır:

| Windows | Linux | Ne yapar |
|---|---|---|
| `py -3 -m pip install -r requirements.txt` | `./kur.sh` | `.venv` sanal ortamını oluşturur, paketleri kurar |
| `GUI_BASLAT.cmd` | `./baslat.sh` | Arayüzü başlatır |
| `DERLE.cmd` | `./derle.sh` | Tek dosya `dist/Aktar` derler |
| `DERLE_WHISPER.cmd` | `./derle_whisper.sh` | `dist/aktar-whisper/` paketini derler |

**Kurulum (Debian 12/13, Ubuntu 22.04+):**

```bash
sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1 nodejs npm ffmpeg fontconfig \
                 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
./kur.sh --kisayol
./baslat.sh
```

- `python3-gi` ve `gir1.2-webkit2-4.1` pencereyi, `gstreamer1.0-libav` H.264/AAC videoların oynatılmasını sağlar. `kur.sh` sanal ortamı sistem paketlerini görecek şekilde (`--system-site-packages`) kurar; eski bir `.venv` varsa silip yeniden kurun. `nodejs`/`npm` arayüzü derlemek içindir.
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
  "provider": "lmstudio",
  "model": "gemma-4-26b-a4b-it-qat@q4_k_xl",
  "source_language": "en",
  "target_language": "tr",
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
| `base_url` | Model sunucusunun OpenAI uyumlu adresi (`.../v1`). Bu bilgisayar ve yerel ağ için `http`, internet için `https`. |
| `provider` | Sunucu türü: `lmstudio` (varsayılan; modeller kalıcı yüklenir, gerçek bağlam uzunluğu okunur, kitap çevirisi LM Studio REST API'siyle) ya da `openai` (Ollama, llama.cpp, vLLM, OpenAI, OpenRouter…; yalnızca standart istekler). |
| `source_language` | Çeviri kaynak dili: `auto` ya da `en`, `ja`, `de`, `fr`, `es`, `it`, `pt`, `nl`, `pl`, `ru`, `uk`, `el`, `ar`, `fa`, `hi`, `ko`, `zh`, `tr`. Altyazılar ve **yeni** kitap projeleri için geçerlidir. |
| `target_language` | Çeviri hedef dili (aynı kodlar, `auto` hariç; varsayılan `tr`). Çıktı dosyası bu dilin kodunu ek alır (`_TR`, `_DE`…). |
| `model` | **Analiz modeli**: çeviri, dosya/koleksiyon özetleri ve analiz için LM Studio model kimliği (boş olamaz). |
| `qa_model` | **Soru-cevap modeli**: koleksiyon, belge ve video sohbetinde soruları cevaplayan model. Boş: analiz modeli. Ayrı bir model seçmek, LM Studio'da analiz/embedding/sohbet modelleri arasında yükle-boşalt beklemesini azaltır (LM Studio'nun aynı anda birden çok modeli bellekte tutabilmesi gerekir). |
| `batch_cues` | Bir istekte modele gönderilecek altyazı girdisi sayısı. Thinking açıkken küçük tutun (örn. 10). |
| `max_tokens` | Yanıt için üst token sınırı. Thinking'li modellerde artırın. |
| `temperature` | 0–2 arası; düşük değer daha tutarlı çeviri verir. |
| `timeout_seconds` | Tek isteğin zaman aşımı. |
| `auto_retry_count` | Geçici hatalarda yeniden deneme sayısı (1–100). |
| `glossary_strict` | Zorunlu terim denetimi katılığı. |
| `analysis_chunk_chars` | Ön/son analizde tek model isteğine gönderilecek yaklaşık görünür karakter sayısı. |
| `disable_thinking` | `true` ise istek gövdesine `chat_template_kwargs: {enable_thinking: false}` eklenir (LM Studio destekliyorsa). Desteklenmezse yok sayılır. |
| `qa_context_chars` | Soru Sor: modele tek istekte gidecek en fazla transkript karakteri (≥1000). Transkript sığmazsa video haritası kullanılır (bkz. 3.6). LM Studio'daki model bağlam uzunluğuna göre ayarlayın. |
| `vision_model` | Taranmış PDF sayfalarını ve görselleri okuyan LM Studio modeli (görsel destekli). Boş: analiz modeli (`model`) kullanılır. Ayarlar → **Kütüphane indeksi** → **Görü modeli**. |
| `ocr_engine` | Taranmış PDF sayfalarını okuyan motor: `auto` (varsayılan; Tesseract kuruluysa o, değilse seçili OCR modeli, o da yoksa görü modeli), `tesseract` (yerel Tesseract; çok hızlı, metin uydurmaz, LM Studio'yu meşgul etmez), `model` (OCR modeli) ya da `vision` (görü modeli). Görseller her zaman görü modeliyle okunur. Ayarlar → **OCR motoru**. |
| `ocr_model` | Taranmış PDF sayfaları için OCR'a özel LM Studio modeli (ör. `glm-ocr`). Görseller yine `vision_model` ile tarif edilir. Ayarlar → **OCR modeli**. |
| `ocr_model_prompt` | OCR modeline giden kısa komut (varsayılan `Text Recognition:`; GLM-OCR için). Başka bir OCR modeli farklı bir komut bekliyorsa (ör. `OCR`) buradan değiştirilir. |
| `tesseract_path` | Tesseract programının yolu. Boş: PATH, `C:\Program Files\Tesseract-OCR\` ve uygulamanın `bin\tesseract\` klasöründe aranır. |
| `tesseract_lang` | Tesseract dilleri (varsayılan `tur+eng`). Dil verisi eksikse kurulu olanlarla okunur. |
| `embedding_model` | Kütüphane indeksi için LM Studio embedding modeli (ör. `text-embedding-embeddinggemma-2`). Boş: indeksleme kapalı, yalnızca transkript çıkarılır. Ayarlar → **Kütüphane indeksi**. |
| `embedding_query_template` / `embedding_document_template` | Embedding modeline gönderilen metnin biçimi. Varsayılanlar EmbeddingGemma içindir (`task: search result \| query: {query}`, `title: {title} \| text: {text}`); başka bir embedding modeli kullanıyorsanız modelin önerdiği biçimi yazın. `{query}` / `{text}` zorunludur. |
| `whisper_model` | Konuşmadan metin modeli: `large-v3-turbo` (varsayılan), `large-v3`, `medium`, `small`, `base`. |
| `whisper_device` | `auto` (GPU varsa GPU), `cuda` veya `cpu`. |
| `whisper_language` | Konuşma dili kodu (örn. `en`, `ja`); boşsa otomatik algılanır. |
| `whisper_cuda_dir` | Başka programlarla ortak kullanılan cuBLAS 12 / cuDNN 9 DLL klasörü (örn. `Z:\Ai Tools\cuBLAS and cuDNN`); boşsa pip ile kurulan veya pakete gömülü kütüphaneler aranır. |

Bu ayarların hepsi **Ayarlar** penceresinden de değiştirilebilir.

> İnternetteki `http` adresleri reddedilir; internetteki sunucular `https` olmalıdır.

**Çeviri dilleri:** Altyazı Çevir ve Kitap Çevir sayfalarının başındaki iki seçici (kaynak → hedef) ya da **Ayarlar → Altyazı çevirisi** dil çiftini değiştirir. İstemler İngilizce → Türkçe yazılmıştır. Başka bir çift seçilince dil adları değişir ve Türkçeye özgü yönergeler (sen/siz, özel isimlere kesme işaretiyle ek) yalnızca hedef Türkçe iken kalır. Varsayılan çiftte istem bayt bayt aynıdır, eski kontrol noktaları geçerli kalır.

- Kitap projeleri dil çiftini oluşturuldukları anda `epub-import.json`'a yazar ve hep o çiftle sürer; sayfadaki seçici yalnızca yeni projeleri etkiler.
- Seri sözlükleri tek hedef dile aittir. Başka dilde açılan serinin sözlüğü o çeviride kullanılmaz; günlüğe uyarı yazılır.
- Sözlük denetimi Türkçede çekim eklerini tanır. Diğer dillerde son kelimenin kökünü (birkaç harf ek payıyla) arar; Japonca, Çince ve Korece gibi boşluksuz dillerde alt dize arar.
- ASS/SSA çıktısında font hedef dilin harflerini çizemiyorsa o dilin yedek fontu kullanılır (Türkçe/Latin/Kiril: Calibri, Japonca: Yu Gothic, Çince: Microsoft YaHei, Korece: Malgun Gothic).

---

## 3. Arayüz akışı

Sol menüde **Sohbet**, **Kütüphane**, **Dosya incele**, **Altyazı Çevir** ve **Konsol** sayfaları vardır; koleksiyonlar da sol menüde listelenir. **aktar** logosuna tıklayınca menü yalnızca simgelere daralır (tekrar tıklayınca genişler; tercih hatırlanır). Üst çubuktaki **‹ ›** düğmeleri önceki/sonraki sayfaya döner, dişli simgesi **Ayarlar**'ı açar. Uygulama son kullandığınız sayfayla açılır. Pencereye bırakılan dosyalar açık sayfaya gider: Kütüphane'de koleksiyona eklenir, Dosya incele'de açılır, Altyazı Çevir'de video açılır. 3.0 Kütüphaneyi, 3.1–3.5 Altyazı Çevir sayfasını, 3.6 videoya soru sormayı, 3.7 görünümü ve temaları, 3.8 genel sohbeti, 3.9 tek dosya incelemeyi, 3.10 konsolu anlatır.

### 3.0 Kütüphane
Videolarınızı ve belgelerinizi **koleksiyonlarda** toplar (ör. "Makine Öğrenmesi", "Kullanım Kılavuzları").

**Desteklenen dosyalar:** videolar (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`, `.ts`, `.wmv`, `.flv`) ve belgeler: **PDF** (metin katmanı okunur), **.txt**/**.md**, **Word** (.docx; Word'ün sayfa sonları korunur), **Excel** (.xlsx) ve **.csv** (her çalışma sayfası bir sayfadır; satırlar başlıklarla birlikte okunur, sayfa başına en fazla 5000 satır) ve **EPUB** e-kitap (her bölüm bir sayfadır); ayrıca **PowerPoint** (.pptx; her slayt bir sayfa), **OpenDocument** (.odt, .ods, .odp), **RTF** ve **HTML** (.html/.htm). Eski Office biçimleri (**.doc, .xls, .ppt**) bilgisayarda **LibreOffice** kuruluysa otomatik olarak .docx/.xlsx/.pptx'e dönüştürülüp okunur (kaynak dosyaya dokunulmaz; dönüştürülen kopya `work_files\converted\` altında saklanır); LibreOffice yoksa tabloda hata olarak bildirilir. Belgelerde konum dakika yerine sayfadır: atıflar `V5 s.12` biçimindedir, tıklayınca PDF uygulama içinde o sayfada açılır. Belgeye çift tıklayınca görüntüleyicinin sağında **Bu belgeye sor** alanı açılır: belgenin metni hemen çıkarılır; kısa belgede metnin tamamı, uzun belgede (embedding modeli seçiliyse) soruyla ilgili bölümler modele verilir, cevaptaki `s.N` atıfına tıklayınca belge o sayfaya gider (metin dosyaları 60 satırlık sayfalara bölünür). **Görseller** (.jpg, .png, .webp, .bmp, .gif) de eklenebilir.

**Taranmış PDF'ler ve görseller (görü modeli):** Metin katmanı olmayan PDF sayfaları görüntüye çevrilir ve Ayarlar'daki **Görü modeli** ile okunur (varsayılan: sohbet modeli; görsel destekli olmalı, ör. gemma-4). Karışık PDF'lerde yalnızca metinsiz sayfalar okunur; görü okuması kapalıyken metinli sayfalar hemen kullanılır, kalan sayfalar tabloda **PDF metni · N sayfa okunmadı** olarak görünür ve sonraki **Hepsini hazırla**'da okunur. Görsellerde model önce görseli 2-4 cümleyle tarif eder, sonra içindeki yazıları aynen yazar; görsel böylece aramaya ve sohbete girer (atıf: `V7 görsel`). Sayfa sonuçları ayrı önbelleğe yazılır, uzun bir tarama kesilirse kaldığı sayfadan devam eder. Belgeye ya da görsele çift tıklayınca görü okuması da hemen yapılır (20 sayfadan uzun taramalar **Hepsini hazırla**'ya bırakılır). OCR'a özel küçük bir model (ör. Hugging Face'teki GLM-OCR ya da PaddleOCR-VL GGUF) LM Studio'ya yüklenip **Görü modeli** olarak seçilebilir. 

**OCR modeli (ör. GLM-OCR):** LM Studio'ya OCR için eğitilmiş küçük bir model indirilip Ayarlar → **OCR modeli**'nde seçilirse taranmış sayfalar onunla okunur (sayfa başına birkaç saniye). Çok sütunlu sayfalarda okuma sırası Tesseract'tan iyidir ve metin uydurmaz; GLM-OCR'ın zayıf yanı Türkçe harflerdir (ı/ş bazen i/s olur) ve gri zeminli kutuları atlayabilir. OCR modelleri fotoğraf tarif edemez; görseller her zaman **Görü modeli** ile okunur. Karşılaştırma (çok sütunlu, düşük kaliteli dergi taraması): Tesseract ~0,5 sn/sayfa, harfler doğru; GLM-OCR ~4-6 sn/sayfa, sıra doğru; genel görü modeli (Gemma 26B) 20-55 sn/sayfa ve metin uydurdu.

**Tesseract (klasik OCR):** Tesseract kuruluysa taranmış PDF'ler varsayılan olarak onunla okunur (Ayarlar → **OCR motoru** → **Otomatik**); sayfalar LM Studio yerine bilgisayardaki Tesseract ile okunur; işlemci çekirdeği sayısına göre birkaç sayfa (en fazla 8) aynı anda işlenir. Çok sütunlu sayfalarda sütunlar zaman zaman birbirine karışabilir, ama metin uydurulmaz. **Uyarı:** Gemma gibi genel görü modelleri küçük yazılı sayfalarda (dergi, künye) okuyamadığı yeri kendi tahminiyle doldurabilir ya da aynı cümleyi tekrar tekrar yazabilir; Aktar tekrarları keser ve günlükte uyarır. Görü modeli kullanılacaksa OCR için eğitilmiş küçük bir model (ör. GLM-OCR) daha güvenilirdir. Görseller (fotoğraf, ekran görüntüsü) tarif gerektirdiği için her zaman görü modeliyle okunur. Kurulum: Windows'ta UB Mannheim Tesseract kurulum dosyası (kurulumda **Turkish** dil verisini işaretleyin); Linux'ta `sudo apt install tesseract-ocr tesseract-ocr-tur`. Ayarlar penceresi Tesseract'ın bulunup bulunmadığını gösterir. 

- **İlk açılış:** Henüz koleksiyon yoksa ortada **Klasör veya dosya bırak** alanı görünür. Bir klasör bırakın ya da **Klasör seç** / **Dosya seç** ile seçin; klasörün adıyla bir koleksiyon oluşur.
- **Koleksiyonlar (sol menü):** Koleksiyona tıklayınca içeriği açılır. **+** ile boş bir koleksiyon oluşturulur. Sağ tık: **Yeniden adlandır**, **Yeniden tara**, **Koleksiyonu dışa aktar (Markdown)…** (açık koleksiyonun tüm transkriptleri tek dosyada; koleksiyon ve video özetleri varsa başlarında), **Koleksiyonu sil**. Silme yalnızca koleksiyon kaydını siler; dosyalarınız diskte kalır.
- **Kaynak klasörler (koleksiyon başlığının altında, sağda):** Klasörler alt klasörleriyle birlikte taranır (gizli ve sistem klasörleri atlanır). Koleksiyon her açıldığında klasörler yeniden taranır: yeni bulunan videolar adının yanında **yeni** ile işaretlenir, diskten silinen ya da takılı olmayan diskteki videolar **Bulunamadı** olarak listede kalır. Sağ tık: **Klasörü aç**, **Koleksiyondan kaldır**.
- **Klasör ekle / Dosya ekle:** Açık koleksiyona klasör veya tek tek video ekler. Klasör ve videolar sayfaya sürüklenerek de eklenebilir.
- **Sıralama:** Tablodaki her sütun başlığına tıklayınca o sütuna göre sıralanır (Dosya/Klasör/Metin kaynağı A → Z, Tarih yeniden eskiye, Uzunluk uzundan kısaya, Durum hazırdan bekleyene); ikinci tıklama sırayı ters çevirir, üçüncüsü koleksiyon sırasına döner. Boş değerler (tarihsiz, bulunamayan dosya) her iki yönde de sonda kalır; Uzunluk'ta videolar, belgeler ve diğer dosyalar kendi aralarında sıralanır.
- **Dosya tablosu:** Dosya adı, bulunduğu alt klasör, süre (hazırlanmamışsa dosya boyutu), metin kaynağı (Altyazı · dil / Whisper · model) ve durum (**Hazır**: transkript çıkarılmış ve aranabilir indekse eklenmiş; **Metin hazır**: transkript var, indeks yok ya da embedding modeli seçilmemiş; **Bekliyor**; **Altyazı yok · Whisper bekliyor**; **Bulunamadı**). 
- **Arama kutusu:** Dosya adında ve transkriptlerde model kullanmadan anında arar (en az 3 harf). Büyük/küçük harf ve Türkçe karakter farkı yok sayılır (`asiri` = `aşırı`); birden çok kelime yazılırsa hepsi aynı satırda geçmelidir. Eşleşen transkript satırları tablonun üstünde listelenir (video · dakika · metin); tıklayınca video o anda açılır. Tablo da yalnızca adı ya da transkripti eşleşen dosyalara süzülür.
- **Videoya çift tıklayınca** oynatıcı ve soru-cevap açılır (bkz. 3.6); üst çubuktaki **‹** düğmesi listeye döndürür. Tabloda Ctrl/Shift ile birden çok satır seçilir, Ctrl+A hepsini seçer.
- **Sağ tık menüsü:** **Oynat ve soru sor**, **Altyazıyı çevir…** (videoyu Altyazı Çevir sekmesinde açar), **Dosya konumunu aç**, **Transkripti dışa aktar…**, **Koleksiyondan çıkar** (dosya diskte kalır; birden çok satır seçilebilir). Çıkarılan dosya (ya da kaldırılan klasörün dosyaları) sohbette artık kullanılmaz: sohbetin model geçmişi sıfırlanır ve koleksiyon özeti kalan dosyalardan arka planda yeniden üretilir.
- **Transkripti dışa aktar:** Transkripti olan videolar için. Tek video seçiliyse kayıt penceresinde biçim seçilir: **Metin** (`[m:ss] satır`), **Altyazı (SRT)** (zamanlı altyazı; oynatıcılarda açılabilir) veya **Markdown** (video özeti varsa başta). Birden çok video seçiliyse önce biçim, sonra klasör sorulur; her video `<video adı>.<uzantı>` olarak yazılır, var olan dosyanın üzerine yazılmaz (`(2)` eklenir). Kaynak videolara dokunulmaz.
- **Hepsini hazırla:** Belgelerin metni hızlıca çıkarılır (**Belgelerden metin**; taranmış PDF ve görseller **Taranmış PDF / görsel → görü modeli** satırında sayılır ve yalnızca **Taranmış PDF ve görselleri görü modeliyle oku** açıksa okunur). Koleksiyondaki tüm videoların transkriptini sırayla çıkarır ve aranabilir indekse ekler. İndeks için Ayarlar → **Kütüphane indeksi** bölümünden bir embedding modeli seçilmelidir (LM Studio'da indirilmiş olması yeterli; ilk istekte yüklenir). Transkript ~90 saniyelik parçalara bölünür ve her parça vektöre çevrilir; seçilmezse yalnızca transkript çıkarılır. Açılan pencere videoları yoklar ve gruplara ayırır: **Zaten hazır** (tekrar işlenmez), **Yalnızca özeti eksik**, **Yalnızca indekslenecek** (transkript var, indeks yok), **Gömülü altyazıdan** (hızlı; şarkı/yazı izleri atlanır) ve **Altyazı yok → Whisper** (toplam ses süresiyle). Whisper yalnızca bu penceredeki **Altyazısız videolarda Whisper kullan** anahtarı açıksa çalışır; kapalıysa bu videolar atlanır ve tabloda **Altyazı yok · Whisper bekliyor** olarak görünür. Sıra: önce altyazılı videolar, sonra Whisper. **Videoların görüntüsünü de oku** açılırsa, transkripti çıkan her videoda görüntü değiştikçe (en geç 2 dakikada bir) kare alınır, birbirinin aynısı kareler atılır; yazılı kareler OCR motoruyla, diğerleri görü modeliyle kısaca betimlenir. Betimler sohbete ve aramaya `[Görüntü]` satırları olarak girer, dışa aktarılan transkripte girmez. Bu seçim koleksiyonda hatırlanır; klasör izleme de ona uyar. **Videolarda konuşmacıları ayır** açılırsa her videoda kimin ne zaman konuştuğu bulunur; transkript, dışa aktarılan TXT/SRT/Markdown ve soru-cevap satırları `K1: …`, `K2: …` diye başlar, böylece "K2 ne dedi?" gibi sorular cevaplanır. Konuşmacılara dublaj penceresinden ad verilebilir (ad tüm etiketlerde görünür). Bu seçim de koleksiyonda hatırlanır. **Klasörü izle** açıkken uygulama açık olduğu sürece klasöre gelen yeni dosyalar kendiliğinden hazırlanır; uygulama kapalıyken hiçbir şey çalışmaz, kapalıyken gelen dosyalar bir sonraki açılışta yakalanır.
  - Çalışırken tablonun üstündeki şerit ilerlemeyi gösterir; satırlarda **Sırada**, **İşleniyor…**, **Whisper %42** gibi durumlar görünür. **Duraklat** sıradaki videodan önce bekler (Whisper bir videoyu bitirmeden durmaz); **Durdur** işi keser, yarım kalan video bir sonraki sefere baştan yapılır. Hazırlanan transkriptler önbelleğe yazılır; videoya çift tıklayınca beklemeden kullanılır.
  - **Dosya özetleri ve koleksiyon özeti çıkar** (varsayılan açık): her videonun ve belgenin genel özeti sohbet modeliyle çıkarılır (videoya çift tıklayınca açılan ekrandaki özetle aynıdır; orada tekrar beklenmez), en sonda bu özetlerden **koleksiyon özeti** üretilir. Video başına birkaç model isteği yapılır; uzun videolarda önce bölüm özetleri çıkarıldığı için dakikalar sürebilir. Kapalıysa yalnızca transkript ve indeks hazırlanır.
  - Hata veren videolar (ör. seste konuşma yoksa) atlanır ve sonunda listelenir; ayrıntılar **Konsol** sayfasındadır.
- **Koleksiyona sor (sağ panel; kapatılırsa üst çubuktaki Koleksiyona sor düğmesiyle açılır):** Koleksiyondaki **Hazır** (indeksli) videoların hepsine birden soru sorarsınız. Soru önce indekste aranır, en ilgili transkript parçaları sohbet modeline verilir; cevap Türkçedir ve iddialar `V3 12:34` gibi atıflarla desteklenir (V3 = koleksiyondaki 3. dosya). Cevabın altındaki **Kaynaklar** satırı hangi videonun kaç kez kaynak gösterildiğini listeler.
  - Atfa tıklayınca o video oynatıcıda açılır ve o ana gider; **‹** düğmesiyle sohbete dönersiniz, sohbet kaybolmaz.
  - **Kapsam:** **Tüm koleksiyon** ya da **Seçili dosyalar** (tabloda seçtiğiniz satırlar). Henüz hazır olmayan dosyalar cevaba dahil edilmez; panelin altındaki not kaç dosyanın beklediğini söyler.
  - Önceki sorular hatırlanır; "peki neden?" gibi devam soruları çalışır. Her koleksiyonun sohbeti ayrıdır ve `library\` klasörüne kaydedilir (son 50 soru); uygulama yeniden açılınca kaldığı yerden devam eder. Panelin sağ üstündeki çöp kutusu sohbeti ve kaydını siler; koleksiyon silinince sohbeti de silinir.
  - **Belge tarihi:** Ekstre, fon bülteni gibi aynı adla her ay gelen belgelerde tarih dosya adında olmadığı için Aktar belgenin kendi tarihini (ekstre kesim tarihi, rapor dönemi, fatura tarihi) özet adımında içerikten çıkarır. Tablodaki **Tarih** sütununda görünür; başlığa tıklayınca tarihe göre sıralanır. Yanlışsa sağ tık → **Tarihi düzenle…** (`15.09.2026`, `09.2026` ya da `2026`; boş bırakılırsa içerikten çıkarılana döner). Tarihler soru-cevapta modele verilir ("geçen ayki ekstrede…" gibi sorular) ve atıflarda dosya adının yanında yazar.
  - Soru-cevap için Ayarlar'daki **Soru-cevap modeli** (boşsa analiz modeli), arama için embedding modeli kullanılır; ikisi de LM Studio'da aynı adresten çalışır. Koleksiyon özeti çıkarıldıysa sohbetin başında bir kartta görünür (genel özet, konular ve tıklanınca sorulan önerilen sorular); bu özet ve video özetleri her soruda modele de verilir, böylece "bu derslerde neler anlatılıyor?" gibi genel sorular da bütün koleksiyona göre cevaplanır. Özet yoksa genel sorular yalnızca soruya en yakın parçalarla cevaplanır.

Koleksiyonlar uygulama dizinindeki `library\` klasöründe tutulur.

#### E-postadan al (Gmail)
Kredi kartı ekstreleri, fon bültenleri gibi e-postayla gelen belgeler kurallarla koleksiyona indirilir.

1. **Ayarlar → E-posta (Gmail):** Gmail adresini yazıp **Kaydet**'e basın. Sonra **uygulama şifresini** girin: normal Google şifreniz değil, Google hesabı → Güvenlik → 2 adımlı doğrulama → **Uygulama şifreleri**'nden alınan 16 harflik şifre. Şifre `config.json`'a yazılmaz, Windows Kimlik Bilgileri Yöneticisi'nde (Linux'ta sistemin anahtar zincirinde, `secret-tool` gerekir) saklanır. **Bağlantıyı dene** girişi sınar.
2. **Koleksiyon → E-postadan al → Kural ekle:** **Gönderen içerir** (ör. `@worldcard.com.tr`) ve/veya **Konu içerir** (ör. `Hesap Özeti`; büyük/küçük harf ve Türkçe harf farkı yok sayılır), **Ne alınsın** (ekler, e-posta gövdesi ya da ikisi; ekler: PDF, Excel (.xlsx/.xls/.csv/.ods), Word ve kütüphanenin okuduğu diğer belgeler; logo gibi görseller ve .zip alınmaz), **Şu tarihten beri** (boş: son 1 yıl), **İndirilecek klasör** ve gerekiyorsa **PDF şifresi**. Klasör koleksiyona eklenir. **Önizle** hiçbir şey indirmeden eşleşen postaları gösterir.
3. **Şimdi indir** ya da koleksiyonu açmak (en sık 10 dakikada bir) yeni postaların eklerini indirir; yeni dosyalar tabloda **yeni** görünür, hazırlığı **Hepsini hazırla** ile siz başlatırsınız.

- Postalar Gmail'in **Tüm Postalar** kutusunda aranır (arşivlenenler dahil) ve okunmuş işaretlenmez.
- Dosya adı postanın geliş günüyle başlar: `2026-10-03 World Gold Hesap Ozeti.pdf`. Aynı gün aynı adla farklı içerik gelirse sonuna içeriğin kısa özeti eklenir.
- Aynı posta iki kez indirilmez (dosyayı silseniz bile); aynı ek başka bir postayla tekrar gelirse de atlanır. Kayıt: `library\<koleksiyon>.mail.json`.
- Şifreli PDF'ler kuraldaki PDF şifresiyle açılıp **şifresiz kopya** olarak kaydedilir; şifre yoksa ya da yanlışsa dosya şifreli hâliyle kaydedilir ve Konsol'da uyarı yazılır.
- Belgenin içeriğinden tarih henüz çıkarılmadıysa Tarih sütununda (soluk) postanın geliş tarihi görünür.

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

Ses dosyaları da açılabilir: `.mp3`, `.m4a`, `.aac`, `.wav`, `.flac`, `.ogg`, `.opus`, `.wma`, `.mka`. Ses dosyasında altyazı akışı olmadığından önce **Whisper ile altyazı oluştur** kullanılır; zamanlı altyazı dosyanın yanına `.srt` olarak yazılır ve çevrilebilir. Oynatıcıda aynı dosyadan dublaj da yapılabilir; ses dosyasının dublajı her zaman `.dublaj.m4a` olur.

### 3.2 Altyazı akışları tablosu
| Sütun | Anlamı |
| --- | --- |
| `Seç` | Çevrilecek altyazı akışını işaretler; aynı anda yalnızca bir akış seçilebilir. |
| `Codec` | Altyazı codec'i (subrip, ass, webvtt, mov_text …). |
| `Dil` | Metadata dil etiketi (varsa). |
| `Başlık` | Metadata başlık etiketi (varsa). |
| `Durum` | Desteklenen çıktı formatı (SRT/ASS/SSA/VTT), "Görüntü tabanlı" ya da OCR ile okunmuşsa "OCR · SRT". |

**Görüntü tabanlı altyazılar (PGS/VobSub/DVB).** Satırdaki **OCR ile oku** düğmesi altyazı görüntülerini metne çevirir: FFmpeg her satırın görüntüsünü ve zamanını çıkarır, aynı görüntüler bir kez okunur. Okuyucu **Ayarlar → OCR motoru**dur (Tesseract akışın diliyle okur; OCR modeli ya da görü modeli LM Studio'da çalışır). Sonuç videonun yanına `<video>.<dil>.srt` olarak yazılır, akış **OCR · SRT** olur ve çevrilebilir. Okuma yarıda kalırsa okunan görüntüler önbellekte kalır, tekrar başlatınca kaldığı yerden sürer.

**Dışa aktar…** (listenin başlığında) işaretli akışı başka biçimde kaydeder; bkz. 3.6 *Altyazıyı dışa aktarma*.

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

- **Görüntü tabanlı (PGS/VobSub):** **OCR ile oku** seçilince altyazı okunur ve bitince ekranda açılır (bkz. 3.2).
- Whisper transkriptinde kelime zamanları varsa söylenen kelimeler sarıya döner (CC → **Söylenen kelimeyi vurgula** ile kapatılır). Eski transkriptlerde kelime zamanı yoksa CC → **Kelime zamanlarını çıkar** Whisper'ı bir kez daha çalıştırır.

ASS altyazılarda stil ve konum gösterilmez, yalnızca metin görünür. Ekranda gösterilen altyazı ile soru-cevabın kullandığı transkript birbirinden bağımsızdır.

**Altyazı zamanlaması (saat düğmesi).** Altyazı sesle uyuşmuyorsa:
- **G / H** altyazıyı 0,1 saniye erkene / geçe alır (Shift ile 1 saniye). Panelde değer elle de yazılabilir; artı değer altyazıyı geç gösterir.
- **Kare hızı:** altyazı ilerledikçe kayıyorsa (başta doğru, sonda saniyelerce kaymış) 23,976 ↔ 25 gibi oranlardan birini seçin.
- **Elle eşitle:** bir satırı duyduğunuz anda yanındaki **Şimdi**'ye basın. Tek satır kaydırmayı, birbirinden uzak iki satır hem kaydırmayı hem hızı düzeltir.
- **Whisper ile otomatik hizala:** konuşma Whisper ile çıkarılır (önbellekte varsa kullanılır) ve altyazı satırları konuşmaya oturtulur. Kaydırma ve kare hızı birlikte bulunur; dilden bağımsız olduğu için Türkçe çeviri altyazı da İngilizce sese hizalanabilir. Sonucun yanında güven derecesi yazar; **düşük** ise elle kontrol edin.
- Düzeltme oynatıcıda anında görünür; dışa aktarma ve klip aynı düzeltmeyi kullanır. Kaynak altyazı dosyası değişmez.

**Altyazıyı dışa aktarma.** Zamanlama panelindeki (ya da Altyazı Çevir'deki) **Dışa aktar…** altyazıyı düzeltilmiş zamanlarla kaydeder. Önerilen ad `<video>.<dil>.<uzantı>`dır; VLC ve mpv bu adlı dosyayı videoyla birlikte kendiliğinden açar. Biçimler:
- **Kaynağın biçimi** (ASS stilleri korunur), **SRT**, **ASS**, **WebVTT**.
- Whisper transkriptinde ayrıca: **ASS karaoke** (her kelime söylendiği anda renk değiştirir; `\kf` akarak dolar, `\k` kelime kelime; VLC, mpv, MPC-HC ve libass kullanan oynatıcılarda çalışır), **SRT kelime vurgulu** (karaoke desteklemeyen oynatıcılar için, o anki kelime `<font color>` ile renkli), **WebVTT kelime zamanlı**, **SRT tek kelime** (her kelime ayrı satır) ve **JSON** (kelime kelime zamanlar). Vurgu rengi, henüz söylenmeyen renk ve yazı boyutu seçilebilir.

**Klip (makas düğmesi).** Videonun bir bölümünü ayrı dosya olarak kaydeder:
- **I** başlangıcı, **O** bitişi şu anki konuma koyar; panelde zamanlar elle yazılabilir ya da ‹ › ile 0,1 saniye kaydırılabilir. Seçilen aralık arama çubuğunda gösterilir. **Önizle** aralığı oynatıp sonunda durur.
- **Satıra hizala** başlangıç ve bitişi altyazı satırlarının sınırlarına, **Kelimeye hizala** (Whisper kelime zamanları) en yakın kelime sınırına çeker; cümle ortasından kesilmez.
- **Biçim:** MP4, MKV, GIF ya da yalnız ses (M4A). **Kesim:** *Hızlı* yeniden kodlamadan saniyeler içinde keser (başlangıç bir önceki anahtar kareye kayabilir); *Hassas* H.264 ile kare kare keser. Kalite ve çözünürlük (yalnızca küçültür) seçilebilir.
- **Altyazı:** *Yok*, *Ayrı dosya* (klibin yanına, klibe göre zamanlanmış), *Gömülü* (oynatıcıda açılıp kapanır; MP4'te düz metin, karaoke için MKV) ya da *Görüntüye yak* (her oynatıcıda görünür; karaoke renkleri de yakılır). Altyazı CC menüsünde seçili olandır ve zamanlama düzeltmesi uygulanır.
- Klip arka planda kaydedilir; ilerleme kontrol çubuğunda görünür. Uygulama kapanırken iş durdurulur, yarım dosya silinir.

**Oynatıcı kısayolları:** Boşluk oynat/duraklat, ←/→ 5 saniye, **F** tam ekran (**Esc** çıkar; tam ekranda fare durunca kontroller gizlenir, kıpırdayınca geri gelir), **N** not, **G / H** altyazı ±0,1 sn, **I / O** klip başlangıcı / bitişi. Arama çubuğunun üzerine gelince zaman ve bölüm adı görünür. Sayfadan çıkıp aynı videoya dönünce kaldığı yerden açılır.

**Belgeler:** PDF sayfaları uygulama içinde gösterilir (sayfa gezinme, yakınlaştırma); diğer belgeler sayfa başlıklarıyla düz metin olarak açılır. Sağdaki **Bu belgeye sor** cevaplarındaki `s.N` atfı belgeyi o sayfaya götürür. **Varsayılan uygulamada aç** dosyayı bilgisayarınızdaki programla açar.

### 3.7 Görünüm ve temalar
**Ayarlar → Görünüm** bölümünde tema önizlemeleriyle seçilir:
- **Sistem:** Windows/Linux'un açık-koyu tercihini izler.
- **Koyu / Açık:** Aktar'ın yerleşik temaları.
- **Hazır temalar:** Acid, Apricot Dawn, Apricot Dusk, Celadon Dune, Cossack, Etruscan Night, Mossfire, Oled, Sepia Ember. İlk açılışta uygulama klasöründeki `themes\` klasörüne bir kez yazılır; silerseniz geri gelmez, düzenlerseniz üzerine yazılmaz.

Kendi temanızı yapmak için `themes\` klasörüne bir `.json` dosyası koyun (**Temalar klasörünü aç** düğmesi klasörü açar, **Yeniden yükle** listeyi yeniler). Dosya bir temel (`dark` ya da `light`) ve değiştirmek istediğiniz renkleri içerir; verilmeyen renkler temelden gelir:

```json
{"base": "dark", "colors": {"accent": "#a238ff", "accent_hover": "#b55cff", "on_accent": "#ffffff"}}
```

Renk adları: `window`, `panel`, `surface`, `surface_hover`, `surface_active`, `outline`, `text`, `secondary`, `dim`, `accent`, `accent_hover`, `on_accent`, `danger`, `warning`, `overlay`, `shadow`. Renkler `#RRGGBB` ya da saydamlıkla `#RRGGBBAA` olarak yazılır. Deeverse'in tema dosyaları aynen çalışır. Bozuk dosyalar listede **Bozuk dosya** olarak görünür ve seçilemez.

### 3.8 Sohbet (genel sohbet)
Sol menünün en üstündeki **Sohbet**, Claude/ChatGPT benzeri serbest bir sohbettir: genel sorulara modelin kendi bilgisiyle cevap verir, yazı, açıklama ve kod gibi işlerde yardımcı olur. Cevaplar yazılırken akış halinde görünür; **■** düğmesi cevabı durdurur. **Enter** gönderir, **Shift+Enter** yeni satır açar.

Her mesajda soru, bütün koleksiyonlardaki ve Dosya incele listesindeki hazır (indeksli) dosyalarda arka planda aranır. Yeterince ilgili bir parça bulunursa modele "kütüphane notu" olarak verilir; model bunu yalnızca soru dosyalarınızla ilgiliyse kullanır ve o zaman `V2 12:34` / `V3 s.5` atıfları yapar (tıklayınca video o anda, belge o sayfada açılır). İlgisiz sorularda kütüphaneden hiç söz etmez. "Kütüphanemde neler var?" gibi sorular için koleksiyon adları ve özetleri de modele verilir. Kütüphane araması için Ayarlar → **Kütüphane indeksi**'nde bir embedding modeli seçili olmalıdır; seçili değilse sohbet yine çalışır ama dosyalara bakmaz.

Sohbetler soldaki listede tarihe göre gruplanır ve `library\conversations\` klasöründe saklanır; sağ tık (ya da **⋯**) ile yeniden adlandırılır veya silinir. **Yeni sohbet** boş bir sohbet açar.

### 3.9 Dosya incele (koleksiyona eklemeden)
**Dosya incele** sayfasında bir dosyayı seçin ya da sayfaya bırakın: koleksiyona eklenmeden açılır. Video oynatıcıda açılır ve yanında **Bu videoya sor**, belge görüntüleyicide açılır ve yanında **Bu belgeye sor** paneli vardır. Son incelenen dosyalar sayfada listelenir; sohbetleri ve hazırlıkları (transkript, OCR) saklanır, dosyayı yeniden açınca kaldığınız yerden devam edersiniz. Satırın menüsünden **Koleksiyona ekle…**, **Altyazıyı çevir…**, **Dosya konumunu aç** ve **Listeden kaldır** seçilebilir (listeden kaldırmak kayıtlı sohbeti de siler; dosyaya dokunulmaz).

Video ve belge sohbetleri Kütüphane'den açılan dosyalarda da saklanır; panelin üstündeki çöp kutusu simgesi sohbeti temizler.

### 3.10 Konsol
Sol menüdeki **Konsol**, uygulamanın bütün günlüğünü gösterir: çeviri adımları, toplu hazırlık, OCR, Whisper, sohbet ve hata ayrıntıları. Üstteki kutuyla günlükte arama yapılır, **Hatalar ve uyarılar** yalnızca sorunlu satırları gösterir, **Kopyala** görünen satırları panoya alır. Konsol açık değilken yeni bir hata yazılırsa menüdeki simgede kırmızı bir nokta belirir.

### 3.11 Abonelikler
Sol menüdeki **Abonelikler**, düzenli ve tek seferlik ödemelerinizi (Netflix, Amazon Prime, elektrik faturası, bir kurs ücreti…) takip eder. **Yeni kayıt** ile ad, kategori, tutar ve para birimi (TRY, USD, EUR, GBP), tür (**Tekrarlayan** ya da **Tek seferlik**), dönem (haftalık, aylık, 3 ayda bir, 6 ayda bir, yıllık), durum (**Aktif**, **Deneme**, **Durduruldu**, **İptal edildi**), başlangıç, yenileme/ödeme ve bitiş tarihleri girilir. **Ödeme** bölümünde yöntem (kredi kartı, banka kartı, havale/otomatik ödeme, nakit), banka, kart adı ve kartın son 4 hanesi yazılabilir; kart numarasının tamamı saklanmaz.

Yenileme tarihi geçmişte kaldıysa bir sonraki ödeme tarihi dönem eklenerek kendiliğinden hesaplanır (31'inde yenilenen aylık kayıt kısa aylarda ayın son gününe düşer). Sayfanın üstünde aylık ve yıllık toplam (para birimine göre ayrı), önümüzdeki 30 günde ödenecek tutar ve aktif kayıt sayısı; sağda banka ve ödeme yöntemine göre aylık yük görünür. Durduruldu/iptal edilmiş ve tek seferlik kayıtlar aylık toplama girmez. Bir satıra tıklayınca kayıt düzenlenir ya da silinir. Kayıtlar kütüphane klasöründeki `subscriptions.data.json` dosyasında durur.

Her kayda bir **logo** eklenebilir: düzenleme penceresinde logo kutusuna ya da **Logo seç**'e tıklayıp görsel seçin (PNG, JPG, WebP, GIF, BMP, ICO), panodaki görseli **Ctrl+V** ile yapıştırın (tarayıcıda logoya sağ tık → *Resmi kopyala*) ya da görsel dosyasını pencereye sürükleyip bırakın. Görselin çevresindeki saydam boşluk kırpılır, en fazla 128 piksele küçültülüp `subscriptions.logos` klasörüne PNG olarak kaydedilir. **Kaldır** logoyu siler; logosu olmayan kayıtta adın baş harfi görünür.

### 3.12 Sesle soru sorma
Sohbet, Koleksiyona sor, Bu videoya sor ve Bu belgeye sor kutularındaki **mikrofon** düğmesine tıklayıp konuşun; düğme kırmızıya döner ve süreyi gösterir. Tekrar tıklayınca kayıt biter, konuşma bilgisayarınızda Whisper ile metne çevrilir ve kutudaki metnin sonuna eklenir. Metni düzeltip kendiniz gönderirsiniz. **Esc** kaydı vazgeçerek kapatır; kayıt en fazla 2 dakika sürer. Konuşmanın dili kendiliğinden algılanır; model ve cihaz Ayarlar'daki Whisper ayarlarından gelir.

Ses hiçbir yere gönderilmez: kayıt `work_files\qa` altına geçici bir WAV olarak yazılır, metne çevrilir ve hemen silinir. Mikrofon izni yalnızca uygulamanın kendi sayfasına verilir. Whisper kurulu değilse (bkz. 1.5) düğme soluk görünür ve üzerine gelince nedenini söyler. Linux'ta mikrofon WebKitGTK'nin GStreamer eklentileriyle alınır; mikrofon bulunamıyorsa `gstreamer1.0-pulseaudio` (PipeWire'da `gstreamer1.0-pipewire`) paketini kurun.

### 3.13 Kitap Çevir (EPUB, MOBI, AZW3, FB2)
Sol menüdeki **Kitap Çevir**, DRM içermeyen e-kitapları sayfanın başında seçilen dile çevirir (varsayılan İngilizce → Türkçe; Çevirgeç'in çeviri motoru, kurallar ve kalite denetimleri aynen korunur). Kitabı sayfaya sürükleyin ya da **E-kitap aç** ile seçin.

**MOBI, AZW3, AZW, PRC ve FB2 (FB2.ZIP, FBZ)** önce EPUB'a dönüştürülür. Dönüştürülen EPUB uygulama klasöründeki `work_files\ebooks` altına yazılır; kaynak dosyaya dokunulmaz. MOBI/AZW3 için Calibre kuruluysa (`ebook-convert`) o kullanılır. Yoksa yerleşik okuyucu metni, başlıkları, görselleri, kapağı, yazarı ve dili okur, ama biçimlendirme yaklaşıktır. DRM'li kitaplar ve KFX biçimi açılmaz.

 çalışma klasörü varsayılan olarak EPUB'un klasörüdür (yol satırına tıklayıp değiştirilebilir). **Çeviriyi başlat** önce kitabı bölümlerine ayırıp `<KitapAdı>-ceviri` klasörünü oluşturur ve ilk çalıştırmada **terim sözlüğünü** sorar (boş bırakılabilir). **Ön analiz** açıksa önce analize girecek bölümler seçilir; analiz bitince model terim önerileri sunar, onaylananlar sözlüğe eklenir.

Her parça kaydedildiği için çeviri **Duraklat**, **Durdur** ya da uygulama kapanınca kaldığı yerden sürer: yarım projeyi **Projeyi sürdür** ile (ya da `-ceviri` klasörünü sayfaya bırakarak) açın. Soldaki listede bölüm durumları görünür; bir bölüme tıklayınca kaynak ve çeviri yan yana, sözlük terimleri vurgulu gösterilir, sağ tık **Bu bölümü yeniden çevir** seçeneğini açar. **Terim sözlüğü** sonradan düzenlenirse değişen terimlerin geçtiği çevrilmiş bölümlerin yeniden çevrilmesi önerilir. Bitince klasörde `TAM-CEVIRI.md` ve `<KitapAdı> TR.epub` (hedef dil başkaysa `DE`, `JA`…) oluşur; ayrıntılı kayıt `translation.log` dosyasında ve sayfanın **Günlük** sekmesindedir.

Sunucu, model, temperature, zaman aşımı, otomatik tekrar ve katı sözlük ortak ayarlardan gelir; parça boyutu, token payları, bitiş işareti ve EPUBCheck **Ayarlar → Kitap çevirisi** bölümündedir (`config.json` içinde `"book"` anahtarı). Komut satırından aynı motor `py -3 src/book_cli.py --epub kitap.epub` ile çalışır.

### 3.14 Okuma (EPUB kitaplığı)
Sol menüdeki **Okuma**, EPUB kitaplarınızı uygulama içinde okumanızı sağlar (Çevirgeç'in okuyucusu). **Kitap ekle** ile ya da e-kitapları (EPUB, MOBI, AZW3, FB2) sayfaya sürükleyerek kitaplığa ekleyin (EPUB dışındakiler önce dönüştürülür, bkz. 3.13); dosyalar taşınmaz, yalnızca yolları `book_library.json` dosyasına yazılır. DRM'li EPUB'lar açılmaz. Kitap Çevir sayfasında çeviri bitince **Türkçe EPUB'u oku** çıktıyı kitaplığa ekleyip doğrudan açar.

Okurken üstteki liste düğmesi **İçindekiler** ve **Yer imleri** panelini açar; yer imi düğmesi bulunduğunuz yeri işaretler. Bölüm sonunda **Sonraki bölüm**'e basın ya da kaydırmaya devam edin; **Alt+←/→** bölümler arasında geçer. **Aa** düğmesi yazı boyutu, yazı tipi (Literata serif / Inter), satır aralığı, sütun genişliği ve sayfa rengini (tema, koyu, sepya, açık) değiştirir; seçimler `ui.json`'da saklanır. Okuma konumu kendiliğinden kaydedilir ve kitaplıkta ilerleme yüzdesi olarak görünür. Kitaptaki web bağlantıları sistem tarayıcısında açılır; betikler, stiller ve dış kaynaklar kitaptan hiç yüklenmez.

**Kitapta ara:** **Ctrl+F** (ya da yan paneldeki **Ara** sekmesi) kelime ya da cümleyi kitabın tüm bölümlerinde arar; büyük/küçük harf ve Türkçe I/ı/İ/i farkı gözetilmez. Sonuçlar bölüm bölüm, çevresindeki metinle listelenir; birine tıklayınca o bölüm açılır, eşleşme vurgulanır ve ortaya kaydırılır. **Enter** sonraki, **Shift+Enter** önceki eşleşmeye geçer, **Esc** aramayı kapatır.

**Kitaba sor:** Üst çubuktaki konuşma balonu sağda kitabın sohbetini açar ("3. bölümde ne oldu?", "X kimdir?", "Bu bölümü özetle"). Kitap ilk açılışta hazırlanır (embedding modeli seçiliyse indekslenir; uzun kitaplarda soruyla ilgili kısımlar aranır). Cevaptaki `s.N` atfı kitabın N. bölümüdür; tıklayınca okuyucu o bölüme gider. Soruda bölüm numarası ya da içindekilerdeki bir başlık geçerse o bölümün başı ayrıca modele verilir. **Okuduğum yere kadar** açıkken (varsayılan) yalnızca okuduğunuz yere kadarki kısım modele gider: önceki bölümler ve açık bölümün ekranın alt kenarına kadarki kısmı (anahtarın yanında bölüm ve yüzde görünür; uzun bölümlerde de geçerlidir). Sonrası hiç gösterilmez, sürprizler bozulmaz. Sohbet kitap başına saklanır; çöp kutusu düğmesi siler.

### 3.15 Sesli okuma
Okuma sayfasında alttaki **oynat** düğmesi bölümü cümle cümle sesli okur; okunan cümle vurgulanır, metne tıklayınca o cümleye atlanır, **Boşluk** duraklatır. Hız düğmesi okuma hızını değiştirir. **Hazırla** bu bölümün (ya da buradan kitabın sonuna kadar) sesini önceden üretip `ses-onbellegi` klasöründe saklar; hazır bölümler motor yüklenmeden anında okunur. **Kaydet** bölümü tek bir WAV dosyası olarak yazar.

Ses, bilgisayarınızda çalışan ayrı bir ses motoruyla üretilir (Çevirgeç'in motorları): **EMA Lightning** (küçük ve hızlı Türkçe ses) ve **VoxCPM** (Trendyol-TTS anlatıcı, tarifle tasarlanan ya da bir kayıttan klonlanan ses; NVIDIA ekran kartı önerilir). Kaynak koddan çalışırken `py -3 -m pip install -r requirements-tts.txt` ile paketler kuruluysa motorlar doğrudan kullanılır. `.exe` için motor paketini proje klasöründe `DERLE_SES.cmd` ile oluşturun (`dist-engines\aktar-ses-<motor>-win64.zip`) ve **Ayarlar → Sesli okuma → Dosyadan kur** ile kurun; motorlar `ses-motorlari` klasörüne açılır, modeller ilk kullanımda iner. Çevirgeç için derlenmiş paketler de kurulabilir. Ses, işlemci (CPU/GPU), varsayılan hız, cümle ve paragraf sonu duraklamaları ve tırnak içini bölmeme aynı bölümden ayarlanır (`ui.json` → `tts`).

**Okuyan ses:** Okuyucunun sağ altındaki ses düğmesi kayıtlı sesleri resimleriyle listeler; birine tıklayınca okuma o sesle, kaldığı cümleden sürer. **Yeni ses** ile ad, resim (Resim seç, Ctrl+V ya da pencereye bırakma) ve motor sesi seçilir: EMA Lightning, VoxCPM Trendyol-TTS, tarifle tasarlanan ses (ses tarifi yazılır) ya da kayıttan klonlanan ses (kayıt ve isteğe bağlı metni). Klon kaydı sesin içine kopyalanır; asıl dosya taşınsa da ses çalışır. Sesler `ses-presetleri` klasöründe durur; düzenlemek için listede kalem simgesine basın. **Ayarlardaki ses** seçilirse Ayarlar → Ses bölümündeki ses kullanılır.

Motor yalnızca okurken çalışan bir alt süreçtir; Aktar kapanınca (çökse bile) kendiliğinden kapanır.

### 3.16 PDF'den kitap (taranmış PDF)
Taranmış (metni resim olan) bir PDF'yi Okuma ya da Kitap Çevir sayfasına bırakın veya **PDF'den kitap** düğmesine basın. Pencerede kitap adı ve yazar (dosya adından tahmin edilir) düzeltilir, kitabın sonra nereye gideceği seçilir: **Okuma'ya ekle** (Türkçe kitaplar, sesli okuma) ya da **Kitap Çevir'de aç** (İngilizce kitaplar). Sayfalar Ayarlar → Kütüphane ve belgeler'deki OCR motoruyla okunur: **OCR modeli** (ör. LM Studio'da glm-ocr) daha doğru, **Tesseract** çok daha hızlıdır (yüzlerce sayfa birkaç dakikada). Tesseract seçiliyse kitabın dili birkaç sayfadan anlaşılır ve kitabın tamamı yalnızca o dille okunur.

Okunan her sayfa PDF'nin yanındaki `<PDF adı>-pdf\ocr` klasörüne yazılır; iş durdurulursa ya da Aktar kapanırsa bir sonraki sefer kaldığı sayfadan sürer. Pencere kapatılabilir, okuma arka planda sürer ve bitince sonuç gösterilir. Temizleme kurallarla yapılır: tekrar eden üst/alt bilgiler ve filigranlar, sayfa numaraları, satır ve sayfa sonunda bölünmüş kelimeler, sayfalar arasında yarım kalan paragraflar, taramada iki kez geçen sayfalar; çift sayfa taramalar ikiye bölünür, dipnotlar bölüm sonunda "Notlar" altında toplanır. Bölümler sırasıyla PDF'nin yer imlerinden, kitabın kendi içindekiler sayfasından, bölüm başlıklarından ("Chapter 3", "Kısım Bir", sayfa başındaki "12") ya da sayfa düzeninden (üstünde büyük boşluk olan bölüm başı sayfaları) bulunur; OCR'ın okumadığı ya da yanlış okuduğu bölüm numaraları sayfa düzenine bakılarak düzeltilir. OCR hatası olabilecek sayfalar sonuçta "Kontrol edilecek sayfalar" olarak listelenir.

Türkçe Tesseract dil dosyası kurulumda yoksa ve Program Files'a yazma izniniz yoksa `tur.traineddata` dosyasını Aktar'ın yanındaki `models\tessdata` klasörüne koyun; Aktar oradaki dilleri kullanır.

**Gözden geçir:** Kitap hazır olunca (ya da sayfaları daha önce okunmuş bir PDF'yi yeniden bırakınca) **Gözden geçir** ekranı açılır. Solda bölümler: adı doğrudan düzeltilir, ok düğmeleriyle bölüm bir kısmın altına alınır ya da üst düzeye çıkarılır, yukarı ok bölümü öncekiyle birleştirir; sayfa numarasına tıklayınca o sayfaya gidilir. Ortada sayfanın görüntüsü, sağda metni durur: metin düzeltilip **Sayfayı kaydet** ile saklanır (OCR çıktısı bozulmaz, düzeltmeler `<PDF adı>-pdf\duzeltme` altında tutulur; **OCR'a dön** düzeltmeyi siler). Sağ altta sayfadaki paragraflar listelenir; **Bölüm başlat** o paragraftan yeni bölüm açar (OCR'ın kaçırdığı bölüm numaraları için). **Otomatik bölümle** bölümleri baştan bulur. Bölümler `kitap.json` dosyasına kaydedilir; **Kitabı oluştur** OCR yapmadan EPUB'u yeniden yazar ve Okuma'daki kitap yerinde güncellenir.

### 3.17 Arka plan işleri
Sağ üstte, Ayarlar'ın solundaki simge arka planda çalışan işleri gösterir: altyazı ve kitap çevirisi, toplu hazırlık (transkript, analiz, özet, indeks), PDF'den kitap, altyazı araçları (OCR, hizalama, klip) ve sesli okumanın hazırlama/kayıt işleri. Simgedeki sayı çalışan iş sayısıdır; açılan listede her işin aşaması ve ilerlemesi görünür, işe tıklayınca ilgili sayfaya gidilir.

---

### 3.18 Videoya Türkçe dublaj
Oynatıcıda Türkçe bir altyazı seçip CC menüsünden **Bu altyazıyla Türkçe dublaj…**'ı açın. Her satır sesli okuma motoruyla seslendirilir, satırın zamanına yerleştirilir (sığmayan satırlar hızlandırılır) ve videonun yanına `.dublaj.mkv` (dublaj varsayılan ses parçası olur, özgün sesler ve altyazılar korunur) ya da `.dublaj.m4a` olarak yazılır.

- **Müziği ve efektleri koru:** Videonun sesi önce konuşma ve müzik/efekt olarak ayrılır; müzik ve efektler tam düzeyde kalır, yalnızca özgün konuşma dublaj konuşurken kısılır (düzeyi kaydırıcıyla). İşlemcide videonun süresinin yaklaşık yarısı kadar sürer; sonuç saklanır, aynı videonun ikinci dublajı beklemez.
- **Konuşmacılara farklı ses ver:** Videodaki konuşmacılar ayrılır ve her satır konuşmacısının sesiyle okunur. **Konuşmacıları bul** listeyi önceden çıkarır: her konuşmacının adı (değiştirilebilir), satır sayısı, konuşma süresi ve örnek satırı görünür; oynat düğmesi konuşmacının özgün sesinden birkaç saniye çalar (kadın mı erkek mi anlaşılsın). Ses **Otomatik** (en çok konuşan ana sesi, diğerleri sırayla kayıtlı sesleri ya da başka motor seslerini alır), **Ana ses** ya da listeden bir ses olabilir. Tarifle tasarlanan ve kayıttan klonlanan sesler burada listelenmez: önce okuyucudaki ses seçicide **Yeni ses** ile kayıtlı ses olarak hazırlayın, sonra **Kayıtlı sesler** altında seçin. Konuşmacı sayısı yanlış çıkarsa sayıyı seçip **Yeniden ayır**'a basın. Her ses için motor bir kez yüklenir.

İş arka planda çalışır, sağ üstteki iş listesinde görünür ve pencere kapanınca durur. Hazır satırlar saklanır; durdurulup yeniden başlatılınca baştan üretilmez.

---

### 3.19 Oyun Çevirisi (Windows)
Türkçesi olmayan bir oyunu oynarken ekrandaki yazıyı okuyup Türkçe çevirisini oyunun üstünde gösterir. Oyunun dosyalarına, belleğine ya da kurulumuna dokunulmaz; yalnızca ekranda görünen okunur. **Oyunu pencereli tam ekran (borderless / windowed fullscreen) modunda çalıştırın**: özel tam ekran (exclusive fullscreen) modunda katman görünmez ve ekran okunamaz.

1. Sol menüden **Oyun Çevirisi**'ni açın, **+** ile oyunu ekleyin (bölgeler, isim listesi ve çeviri önbelleği her oyun için ayrıdır).
2. **Bölgeler** sekmesinde **Ekranda bölge seç**: Aktar küçülür, ekranın o anki görüntüsü donar ve kararır; okunacak alanı (ör. diyalog kutusu) fareyle sürükleyin. Esc ya da sağ tık vazgeçer. **Şimdi oku** bölgede okunan yazıyı gösterir (ayarı denemek için).
   - *Konuşanın adı:* Ad diyalog kutusunun ilk satırındaysa **Otomatik bul** onu ayırır; ayrı bir kutudaysa o kutuyu **Konuşan karakterin adı** olarak ayrı bölge ekleyin. Ad, çeviriye bağlam olarak verilir (hitap ve ton için) ve isim listesindeki ada oturtulur.
   - *Çeviri nerede:* bölgenin altında, üstünde, **orijinal yazının üzerinde** (yazıyı kapatır) ya da **özel konumda** (ekranda ayrıca seçilir).
   - *Görsel model:* süslü/dekoratif yazılar (oyun girişleri) için görüntü doğrudan görsel destekli modele gider. Bu bölgeler varsayılan olarak yalnızca **Şimdi çevir** ile okunur.
   - **Tüm ekranı tara** (ya da yerleşimde **Her yazının üstünde**): bölgedeki her yazı ayrı bulunur ve çevirisi oyundaki yazının tam üstüne, aynı boyda basılır. **Yalnızca cümleler** (varsayılan) seçiliyken diyalog, hikaye, görev ve açıklama metinleri çevrilir; beceri, silah, menü adları ve puanlar (Lv, HP, MP, AP) oyundaki gibi kalır. Yeni yazılar yerleşince tek istekte toplu çevrilir; yazı ekrandan kalkınca çevirisi de kalkar.
3. **İsimler ve terimler** sekmesine karakter ve yer adlarını ekleyin. Karşılığı boş ad çevrilmez. Büyük harfle yazılan ad (ör. `Rain`) yalnızca büyük harfle geçince eşleşir: küçük harfli "rain" yağmur diye çevrilir; cümle başında hangisi olduğuna model karar verir. **Son konuşanlar** düğmeleri okunan adları tek tıkla ekler.
4. **Başlat**. Bölge yalnızca değiştiğinde okunur; harf harf gelen diyalog yerleşince bir kez çevrilir. Daha önce çevrilen cümle (yazı daha ekrana gelirken bile) model beklenmeden gösterilir.

**Kısayollar** (Ayarlar sekmesinden değiştirilebilir; oyun açıkken de çalışır): Ctrl+F9 çeviriyi açar/kapatır, Ctrl+F10 katmanı gizler/gösterir, Ctrl+F11 şu anki ekranı hemen çevirir (bölge yoksa ekranın tamamı görsel modele gider). Kısayola basınca oyunun üstünde kısa bir durum yazısı görünür.

**Ayarlar** sekmesi: çeviri modeli (küçük ve hızlı bir model önerilir; oyun da ekran kartını kullanıyor), görsel model, oyunun dili, okuma yöntemi (Windows OCR; o dil yüklü değilse Tesseract), okuma sıklığı, yazının yerleşmesini bekleme süresi, bağlam satırı sayısı, yazı boyutu, renkler ve zemin opaklığı.

Katman tıklamaları ve fareyi oyuna geçirir, odak almaz, Alt+Tab'da görünmez; klavye ve oyun kumandası dinlenmez (yalnızca seçilen kısayollar alınır). Katman ekran yakalamaya girmez; Aktar kendi yazdığı Türkçe metni tekrar okumaz. Japonca gibi diller için Windows Ayarlar → Zaman ve dil → Dil bölümünden o dili ekleyin (Windows OCR onu okuyabilsin). Aktar kapanınca katman, kısayollar ve okuma tamamen durur.

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

### 6.5 `Görüntü tabanlı altyazıyı önce "OCR ile oku" ile metne çevirin`
Seçilen akış PGS/VobSub gibi görüntü tabanlıdır. Satırdaki **OCR ile oku** ile metne çevirin (bkz. 3.2), sonra çevirin. OCR sonucu kötüyse Ayarlar'dan başka bir OCR motoru seçin (Tesseract'ta akışın dil verisi kurulu olmalı; örneğin İngilizce için `eng`).

### 6.6 `Bu seri/sozluk dosyasi baska bir Aktar ornesi tarafindan kullaniliyor`
Aynı seri dosyasına başka bir Aktar penceresi erişiyor. Diğer pencereleri kapatıp yeniden deneyin.

### 6.7 Seri sözlüğü kaydedilemiyor
Uygulama korumalı bir klasörde (örn. `C:\Program Files`) çalışıyor olabilir. Uygulamayı yazma izni olan bir klasöre taşıyın.

### 6.8 Çeviride Türkçe harfler görünmüyor (kutu/boş kare)
Kaynak ASS/SSA fontu Türkçe karakterleri desteklemiyor olabilir. Aktar bu durumda çıktıdaki fontu **Calibri** ile değiştirir; konsolda `Font uyarısı: ... Calibri kullanıldı (...)` mesajını görürsünüz. Türkçe harfler hâlâ görünmüyorsa oynatıcıda Calibri kurulu değil ya da gömülü font (attached fonts) kullanılıyor olabilir; oynatıcının font ayarını kontrol edin. Linux'ta Calibri yerine Carlito fontunu kurun (`sudo apt install fonts-crosextra-carlito`).

### 6.9 `Yanıt doğrulanamadı; ... parti ... bölünüyor`
Model çoklu istekte ID'leri düşürmüş, girdileri eksik döndürmüş veya token sınırına ulaşmış olabilir. Program aynı partiyi daha küçük parçalara ayırıp tekrar dener; gerekirse tek girdiye iner. Başarılı alt partiler kaydedilir. Tek girdide de hata sürerse işlem durur; konsoldaki hatayı ve LM Studio'nun ham yanıtını inceleyin. Bu mekanizma yanlış sıralanmış cevapları sessizce kabul etmez; çevirinin anlamsal doğruluğunu otomatik olarak garanti etmez.

### 6.10 Soru Sor: `HTTP 400: model sunucusu isteği reddetti`
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
MP4/WebM (H.264, VP9, AV1 + AAC/MP3/Opus) videolar doğrudan oynatılır. Diğerleri (MKV, AVI, AC3/DTS ses, ikinci ses parçası) FFmpeg ile anında paketlenir; oynatıcıda **paketlenerek** rozeti görünür, görüntü kopyalanır ve yalnızca ses AAC'ye çevrilir. Tarayıcı görüntüyü de çözemezse (ör. 10 bit H.264, HEVC/x265, MPEG-4) görüntü H.264'e yeniden kodlanır: **Ayarlar → Video oynatma → Dönüştürmede donanım hızlandırma** *Otomatik* iken ekran kartının kodlayıcısı (NVIDIA NVENC, Intel Quick Sync, AMD AMF ya da Windows Media Foundation) kullanılır ve kaynak da ekran kartında çözülür; rozet **GPU ile dönüştürülerek** olur. Çalışan GPU kodlayıcısı yoksa ya da kodlama başarısız olursa oynatıcı kendiliğinden işlemciye (x264) geçer; rozet **işlemciyle dönüştürülerek** olur ve hangi kodlayıcının kullanıldığı Konsol'a yazılır. Ayarlar sayfası bu bilgisayarda çalışan GPU kodlayıcılarını listeler. Rozet her zaman görünür: **doğrudan · HEVC** gibi bir rozet, videonun dönüştürülmeden WebView tarafından çözüldüğünü gösterir (HEVC için Windows'un HEVC çözücüsü). Video takılırsa Konsol'a `Takılma … sn` satırı yazılır: *önde veri vardı* diyorsa çözücü yetişmiyordur, *önde veri yoktu* diyorsa veri geç geliyordur. HEVC video doğrudan oynatılırken takılıyorsa **Ayarlar → Video oynatma → HEVC'yi WebView ile doğrudan oynat**ı kapatın; HEVC o zaman seçili kodlayıcıyla (ör. Windows Media Foundation) H.264'e dönüştürülür. İşlemciyle dönüştürmede takılma varsa güncel ekran kartı sürücüsü kurun ya da listeden çalışan bir kodlayıcı seçin. Dönüştürülen videoda indirilmiş kısımda anında sarılır; daha ileriye sarınca akış o andan yeniden başlar (bir-iki saniye bekleme). Hata mesajı videonun üzerinde görünür. FFmpeg'in (`bin\ffmpeg.exe`) bulunduğunu kontrol edin. Linux'ta `gstreamer1.0-libav` kurulu olmalıdır. Soru-cevap ve altyazı çıkarma oynatma olmadan da çalışır.

---

## 7. Komut satırı

Arayüz olmadan da kullanılabilir (aynı çekirdeği paylaşır):

```bat
py -3 src/cevir.py check
py -3 src/cevir.py streams "C:\video\Movie.mkv"
py -3 src/cevir.py extract "C:\video\Movie.mkv" --stream 2
py -3 src/cevir.py translate "C:\video\Movie.ass" --series game-of-thrones --glossary "Ash=Kul"
```

- `check` — ffmpeg/ffprobe bulunabilirliği ve yapılandırma geçerliliği.
- `streams` — videodaki altyazı akışlarını listeler.
- `extract --stream N` — seçilen global stream index'i çıkarır.
- `translate` — altyazıyı `config.json`'daki dil çiftiyle (varsayılan Türkçeye) çevirir; `--series` ve `--glossary Kaynak=Karşılık` (çoklanabilir).

`py -3 desktop.py --version` uygulamanın sürümünü yazar.

---

## 8. Gizlilik ve veri

- Çeviri ve soru-cevap seçtiğiniz model sunucusunda yapılır. Sunucu bu bilgisayardaysa ya da yerel ağdaysa **internete veri gitmez**. İnternetteki bir sunucu (OpenAI, OpenRouter…) seçerseniz çevrilen ve sorulan metinler o sunucuya gönderilir; Ayarlar bunu açıkça uyarır.
- Konuşmadan metin (Whisper) tamamen bilgisayarınızda çalışır. Yalnızca modelin kendisi ilk kullanımda Hugging Face'ten indirilir; video, ses veya metin gönderilmez.
- İnternetteki sunucular yalnızca `https` ile kullanılabilir; API anahtarı config.json'a değil işletim sisteminin şifre deposuna yazılır.
- Kaynak video **salt-okunur**: kopyalanmaz, taşınmaz, değiştirilmez, yeniden encode edilmez.
- Seri sözlükleri uygulama dizinindeki `series\` klasöründe tutulur (kullanıcı verisi; sürüm kontrolüne girmez).
- Kütüphane koleksiyonları `library\` klasöründe tutulur; yalnızca dosya yollarını içerir, dosyaların kendisi kopyalanmaz. Genel sohbetler `library\conversations\`, Dosya incele listesi `library\recent.files.json`, dosya sohbetleri `library\file-*.chat.json` dosyalarındadır.
- Soru Sor transkriptleri, video haritası ve Whisper sonuçları `work_files\qa\` altında, kütüphane indeksi (embedding vektörleri) `work_files\index\` altında önbelleğe alınır. Silmek güvenlidir; gerekirse yeniden üretilir.
