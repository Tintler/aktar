<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Aktar" width="190">
  </picture>
</div>

![aktar arayüzü](preview.png)

Video dosyalarındaki **metin tabanlı altyazıları** çıkarıp, **yerel bir yapay zeka modeliyle Türkçeye çeviren** ve videolarınız hakkında **soru sorabildiğiniz** masaüstü uygulaması.

> **Gizlilik:** Hiçbir veri internet üzerinden gönderilmez. Çeviri ve soru-cevap tamamen yerel ağdaki LM Studio sunucusunda (`127.0.0.1`) yapılır. Kaynak video dosyası **salt-okunur** kabul edilir; kopyalanmaz, taşınmaz, değiştirilmez veya yeniden encode edilmez.

> **English:** Aktar is a cross-platform (Windows, Linux) PySide6 desktop app (with a companion CLI) that extracts text subtitles from video files and translates them to Turkish with a local LLM served by LM Studio. Everything runs locally and the source video is treated as read-only. The program preserves subtitle structure, timings, order and ASS tags — while the model only ever sees plain text, and it enforces a glossary for consistent terminology across episodes. The **Library** home page groups folders and videos into named collections (rescanned on open); opening a video gives a built-in player plus a chat that answers questions about your own videos with clickable timestamp citations, using embedded subtitles or optional local speech-to-text (faster-whisper).

---

## Öne çıkan özellikler

- **Kütüphane (açılış sayfası):** Klasörleri ve videoları adlandırılmış koleksiyonlarda toplar. Klasörler alt klasörleriyle taranır, koleksiyon her açıldığında yeni eklenen videolar bulunur. Tabloda her videonun transkript kaynağı ve hazırlık durumu görünür; **Hepsini hazırla** tüm transkriptleri sırayla çıkarır (altyazısız videolarda onayla Whisper) ve LM Studio'daki bir embedding modeliyle (ör. EmbeddingGemma) aranabilir indekse ekler. Sağdaki **Koleksiyona sor** paneli tüm hazır videolara birden soru sorar; cevaptaki `V3 12:34` atıflarına tıklayınca ilgili video o anda açılır. Videoya çift tıklayınca tek video oynatıcı ve soru-cevap açılır.
- **Zorunlu terim sözlüğü (glossary):** Çeviride belirtilen terimlerin karşılığı Türkçe çekim ekleriyle birlikte denetlenir; eksikse tek düzeltme turu yapılır.
- **Seri bazlı glossary + süreklilik:** TV dizisi/anime bölümleri arasında isim yazımı, hitap biçimi (sen/siz) ve tekrar eden kalıplar seri düzeyinde saklanır.
- **Yapay zekâ ön analizi:** Kaynak altyazıdan çevrilebilir kurgu terimleri, unvanlar, yerler ve kalıcı süreklilik kararları için Türkçe öneriler üretir; kullanıcı karşılığı düzenleyip yalnız bölüm veya seri kapsamıyla onaylayabilir.
- **Çeviri sonrası öğrenme:** Ön analiz kapalı olsa bile çevirinin sonunda sonraki bölümlerde kullanılabilecek terimler ve süreklilik kararları çıkarılır; kullanıcı onayı olmadan seri terimlerine yazılmaz.
- **Format korunur:** SRT→SRT, ASS→ASS, SSA→SSA, VTT→VTT. Yalnızca `mov_text` SRT'ye dönüştürülür.
- **Videoya soru sor (Kütüphane → video):** Yerleşik oynatıcının yanında videonun içeriği hakkında yerel modelle sohbet eder; özet gibi genel sorular da belirli ayrıntılar da cevaplanır. Cevaptaki `12:34` atıflarına tıklayınca video o ana gider. Uzun videolarda bölüm bölüm "video haritası" çıkarılır.
- **Altyazısız videolar için konuşmadan metin (isteğe bağlı):** faster-whisper ile ses yerelde metne çevrilir; sonuç hem soru-cevapta hem oynatıcıda altyazı olarak kullanılır. NVIDIA GPU varsa hızlandırılır.
- **Oynatıcıda altyazı seçimi:** Videodaki akışlar, video klasöründeki altyazı dosyaları (Aktar'ın `_TR` çevirisi dahil) ve Whisper transkripti CC menüsünden seçilip izlenebilir.
- **Türkçe karakter güvenliği:** Kaynak ASS/SSA fontu Türkçe harfleri (`ç ğ ı İ ö ş ü`) çizemiyorsa çıktıda o font otomatik olarak **Calibri** ile değiştirilir.

---

## Gereksinimler

- **Windows 10/11** veya **Linux** (Debian, Ubuntu, Fedora…; KDE Plasma/GNOME, Wayland veya X11). Linux kurulumu için aşağıdaki **Linux** bölümüne bakın.
- **Python 3.10+** (kaynak koddan çalıştırma için).
- **PySide6** (arayüz).
- **FFmpeg / ffprobe:** `bin\ffmpeg.exe` ve `bin\ffprobe.exe` olarak taşınabilir şekilde projeye konur(daha fazla bilgi için bin klasöründe  **[README.txt](bin/README.txt)** 'i okuyabilirsiniz).
- **LM Studio:** yerel sunucu açık olmalı (varsayılan `http://127.0.0.1:1234/v1`) ve bir model yüklü olmalı. Soru Sor için modelin bağlam uzunluğu en az ~12k token önerilir.
- **İsteğe bağlı — faster-whisper:** altyazısız videolarda konuşmadan metin için. Kaynak koddan çalışırken `requirements-whisper.txt`; derlenmiş .exe ile `DERLE_WHISPER.cmd`'nin ürettiği ayrı `aktar-whisper` paketi. GPU için cuBLAS 12 / cuDNN 9; başka programlarla ortak kullandığınız bir klasör varsa Ayarlar'dan gösterilebilir. Bkz. KULLANIM.md 1.5.

---

## Hızlı başlangıç

Release'deki .exe dosyası veya derlemeden kullanmak istiyorsanız;

```bat
cd /d Z:\LLM-Files\Projects\Aktar
py -3 -m pip install -r requirements.txt
```

1. `bin\` klasörüne `ffmpeg.exe` ve `ffprobe.exe` koyun.
2. LM Studio'da modeli yükleyip yerel sunucuyu başlatın; `config.json` içindeki `base_url` ve `model` alanlarını kendi ayarınıza göre düzenleyin.
3. Arayüzü başlatın:

```bat
GUI_BASLAT.cmd
```

4. Açılan **Kütüphane** sayfasına bir klasör veya video sürükleyin; koleksiyon oluşur. Videoya çift tıklayınca oynatıcı ve soru-cevap açılır.
5. Altyazı çevirmek için başlık şeridinden **Altyazı Çevir** sekmesine geçin (ya da tablodaki videoya sağ tıklayıp **Altyazıyı çevir…**): videoyu sürükleyin → altyazı akışını işaretleyin → **Çevir**.

### Linux (Debian, Ubuntu, KDE Plasma…)

```bash
sudo apt install python3-venv ffmpeg fontconfig libxcb-cursor0
./kur.sh --kisayol
./baslat.sh
```

`kur.sh`, paketleri proje klasöründeki `.venv` sanal ortamına kurar. `--whisper` konuşmadan metni, `--gpu` bunun yanında NVIDIA CUDA kütüphanelerini de kurar; `--kisayol` uygulama menüsüne kısayol ekler. FFmpeg sistemden kullanılır. Derleme için `./derle.sh` ve `./derle_whisper.sh` var. Ayrıntılar: **[KULLANIM.md → 1.6](KULLANIM.md#16-linux-debian-ubuntu-fedora-kde-plasma-gnome)**.

Ayrıntılı kullanım ve .exe'nin derlenmesi için bkz. **[KULLANIM.md](KULLANIM.md)**.

### Komut satırı (isteğe bağlı)

```bat
py -3 cevir.py check
py -3 cevir.py streams "C:\video\Movie.mkv"
py -3 cevir.py extract "C:\video\Movie.mkv" --stream 2
py -3 cevir.py translate "C:\video\Movie.ass" --series game-of-thrones --glossary "Ash=Kul"
```

---

## Sınırlamalar

- Yalnızca **metin tabanlı** altyazılar desteklenir; görüntü tabanlı altyazılar (PGS/VobSub) çevrilemez.
- Satır ortasındaki karakter bazlı ASS efektleri (`C{\fs38}L...` gibi) modelden uzak tutulup çevrilmiş metindeki oransal konumlarına geri yerleştirilir. Etiketler korunur; kelime sırası değiştiğinde görsel konumları yaklaşık olabilir.
- Çeviri kalitesi seçilen modele ve prompt'a bağlıdır; LM Studio model preset'inde "thinking" kapatılması önerilir (bkz. KULLANIM.md → Sorun giderme).
- Otomatik konuşmacı ayrımı, karaoke zamanlaması veya altyazı zamanlaması düzeltmesi yapılmaz.
- Soru Sor cevapları yalnızca transkripte (altyazı veya konuşma) dayanır; görüntüdeki içerik (grafikler, ekrandaki yazılar) görülmez. Whisper, `Aktar.exe`'ye gömülmez; ayrı `aktar-whisper` paketi olarak yanına konur.

---

## Lisans

MIT — bkz. [LICENSE](LICENSE).
