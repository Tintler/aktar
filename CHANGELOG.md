# Değişiklik günlüğü

Sürümler [Anlamsal Sürümleme](https://semver.org/lang/tr/) düzenindedir: yeni özellik ikinci, yalnızca düzeltme üçüncü sayıyı artırır. Ayrıntılı geçmiş `git log` içindeki `F<numara>` commit'lerindedir.

## 2.3.2 — 2026-10-21

### Düzeltme
- **Drama 3 kısa parçalar (F163):** Okuyucunun gönderdiği metindeki ardışık cümleler sınır elverdiğince tek istekte gider; tek başına kalan "dedi.", "işte…" gibi kısa parçaları model susarak ya da mırıldanarak okuyordu (az parça ayrıca daha az ton değişimi demek). Metne göre çok uzun süren ses (ör. tek kelime için 7 sn) ya da hiç konuşma içermeyen ses de artık yakalanıp yeniden istenir. Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.3.1 — 2026-10-21

### Düzeltme
- **Drama 3 erken bitirme (F162):** Model bazen parçayı son kelimeyi söylemeden bitiriyordu ("…ifadeler için [tarıyorum]"); ses sessizliğe inmeden kesildiği için bu artık yakalanır ve parça yeniden istenir. Sunucunun süre sınırına (~14,9 sn) ulaşan parça, kesilme bir duraklamaya denk gelse de bölünüp yeniden istenir (önceden böyle bir parçada 7 kelime kayboluyordu). Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.3.0 — 2026-10-21

### Yeni
- **Drama 3 ayarları (F161):** Ayarlar → Ses'te Drama 3'ün parça uzunluğu (60-250 karakter, varsayılan 150), temperature (varsayılan 0,8) ve top_p (varsayılan 0,9) kaydırıcıyla ayarlanır; "Varsayılana dön" ile sıfırlanır. Değiştirilen ayarla hazırlanan cümleler yeniden üretilir.
- Uzun cümle artık ortadan, dengeli bölünür (önce ortaya yakın virgül/noktalı virgül); sonda tek kalan kısa kırıntılar ve cümle ortasındaki gereksiz ses değişimleri azaldı. Sunucunun süre sınırına (serve_tr.sh MAXNEW, ~15 sn) takılıp konuşmanın ortasında kesilen parça kendiliğinden ikiye bölünüp yeniden istenir.

## 2.2.2 — 2026-10-20

### Düzeltme
- **Drama 3 atlamaları (F160):** Model bazen cümlenin ortasında susuyor ya da cümleyi erken bitirip kalanını okumuyordu. 2.2.1'deki dar örnekleme (top_p 0.7) susmayı sıklaştırmıştı; örnekleme gevşetildi (temperature 0.8, sunucunun top_p'si). Konuşma süresi metne göre çok kısa kalan parça sunucu varsayılanıyla en fazla iki kez yeniden istenir. Sunucuya giden parçalar 100 karakterle sınırlandı (uzun parçayı model erken bitirebiliyordu). "44. bölümünü" gibi noktadan sonra küçük harfle süren yerler artık bölünmüyor. Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.2.1 — 2026-10-20

### Düzeltme
- **Drama 3 tonlaması (F159):** Cümleler daha düşük örnekleme sıcaklığıyla (temperature 0.7, top_p 0.7) üretilir. Cümleden cümleye perde ve ses düzeyi değişimi azaldı (ölçümde perde sapması 16,5 → 11 Hz), telaffuz hataları da düştü. Bu motorla önceden hazırlanmış cümleler yeni ayarla yeniden üretilir.

## 2.2.0 — 2026-10-20

### Yeni
- **Drama 3 (Türkçe) ses motoru (F158):** Fish Audio Drama 3'ün Türkçeye uyarlanmış sürümüyle kayıttan klonlanan, doğal ve duygulu ses (Türkçe ve İngilizce). Motor, kullanıcının kendi başlattığı SGLang-Omni sunucusuna HTTP ile bağlanır; Aktar sunucuyu başlatmaz. Sunucu adresi (varsayılan `http://127.0.0.1:7861`) ve "Bağlantıyı dene" Ayarlar → Ses'tedir; sunucu yoksa anlaşılır bir hata gösterilir. Metin cümlelere, uzun cümleler virgüllerden bölünüp birleştirilir; `[laughs]`, `<whisper>…</whisper>` etiketleri aynen geçer; modelin bıraktığı uzun sessizlikler kısaltılır; hata veren istek bir kez yeniden denenir. Klon kaydının metni yazılmazsa ya da kayıt 20 saniyeden uzunsa (kırpılır) metin Whisper ile çıkarılır. Okuyucu, sesli kitap, sohbet sesi ve dublajda kayıtlı ses olarak kullanılır. Built with Fish Audio; rızası olmadan tanınabilir kişilerin sesini klonlamak yasaktır.

## 2.1.1 — 2026-10-20

### Düzeltme
- **VoxCPM model yüklemesi (F157):** Trendyol, tarif edilen ve klon sesler model önbellekteyse Hugging Face'e bağlanmadan yüklenir; önceden her yüklemede Hub'a güncelleme sorulduğu için yavaş ya da kopuk ağda yükleme uzuyordu. Model yalnızca önbellekte yoksa indirilir ve arayüzde "Model indiriliyor" yazar.

## 2.1.0 — 2026-10-18

### Yeni
- **Çeviri dilleri (F151):** Kaynak dil (Otomatik dahil 18 dil) ve hedef dil seçilebilir; varsayılan İngilizce → Türkçe. Altyazı Çevir ve Kitap Çevir sayfasının başında ve Ayarlar → Altyazı çevirisi'nde seçilir. Çıktı dosyası hedef dilin kodunu ek alır (`_TR`, `_DE`, `_JA`…). Kitap projeleri oluşturuldukları dil çiftini korur; seri sözlükleri tek hedef dile aittir. Türkçeye özgü yönergeler (sen/siz, kesme işaretiyle ek) yalnızca hedef Türkçe iken istemde kalır; sözlük denetimi diğer dillerde çekim eklerine toleranslıdır, Japonca/Çince gibi boşluksuz dillerde alt dizeyle arar. ASS fontları hedef dilin harfleriyle denetlenir.
- **Model sunucuları (F152):** LM Studio'nun yanında OpenAI uyumlu her sunucu: Ollama, llama.cpp, vLLM, OpenAI, OpenRouter… Yerel ağdaki sunucular http, internetteki sunucular https ile kullanılabilir. API anahtarı işletim sisteminin şifre deposunda saklanır. İnternetteki bir sunucu seçilince Ayarlar'da verinin bilgisayardan çıkacağı uyarısı görünür. Kitap çevirisi OpenAI uyumlu sunucularda `/chat/completions` ile çalışır.
- **E-kitap biçimleri (F153):** Kitap Çevir ve Okuma MOBI, AZW3, AZW, PRC ve FB2 (FB2.ZIP, FBZ) açar; kitap önce EPUB'a dönüştürülür. Calibre kuruluysa MOBI/AZW3 için o kullanılır, yoksa yerleşik okuyucu. DRM'li kitaplar açılmaz. PDF'den kitapta dil algılama 18 dile genişledi ve Tesseract kitabın diliyle çalışır.
- **Bileşen denetimi (F154):** İlk açılışta model sunucusu, FFmpeg, embedding modeli, Whisper, ses motoru, Tesseract, libmpv ve Calibre denetlenir; eksik olanın nasıl kurulacağı ve ilgili ayar gösterilir. Ayarlar → Gelişmiş'ten yeniden açılır.
- **Sürüm takibi (F155):** Sürüm `src/version.py`'de tutulur; Ayarlar'da, `--version` çıktısında ve Windows'ta `Aktar.exe` dosya özelliklerinde görünür.

## 2.0.0 — 2026-10-18

pywebview + Svelte arayüzüyle yeniden yazılan sürüm (F131–F150).

- Kitap Çevir: Çevirgeç kitap çeviri çekirdeği, terim sözlüğü, ön analiz, terim onayı.
- Okuma: EPUB kitaplığı, okuyucu, yer imleri, kitapta arama, Kitaba sor.
- Sesli okuma ve sesli kitap (M4B/MP3), ses önayarları ve klon sesler.
- PDF'den kitap: OCR, temizleme, bölümleme ve gözden geçirme ekranı.
- Videoya Türkçe dublaj: müzik koruma, konuşmacı başına ses, ses önizlemesi.
- Sohbette sesli mod; arka plan işleri listesi; kategorili Ayarlar.
