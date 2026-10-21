# Değişiklik günlüğü

Sürümler [Anlamsal Sürümleme](https://semver.org/lang/tr/) düzenindedir: yeni özellik ikinci, yalnızca düzeltme üçüncü sayıyı artırır. Ayrıntılı geçmiş `git log` içindeki `F<numara>` commit'lerindedir.

## 2.11.2 — 2026-10-21

### Düzeltme
- **Drama 3 TR "kütüphaneler yükleniyor"da takılabiliyordu (F176):** Sunucu Aktar'ın ortamını miras alıyordu: Whisper için PATH'e eklenen CUDA 12 klasörleri, Aktar'ın kendi `bin` klasörü ve paketli Aktar'ın geçici DLL klasörü klasördeki torch'un (CUDA 13) yanlış kütüphaneleri yüklemesine yol açabiliyordu. Sunucu artık bunlardan arındırılmış bir ortamla başlar. Yükleme aşamaları ayrıldı (torch, model kodu, model) ve torch'un GPU'yu görüp görmediği Konsol'a yazılır.

## 2.11.1 — 2026-10-21

### Düzeltme
- **Drama 3 TR Linux'ta yüklendikten hemen sonra kapanıyordu (F176):** Sunucuyu "Aktar kapanınca kapan" diye işaretleyen Linux yöntemi, süreci başlatan iş parçacığına bağlıydı; yükleme bitince sunucu da kapanıyordu. Artık sunucu, Aktar'ın açık tuttuğu boru kapanınca kendini kapatır: Aktar kapanır ya da çökerse sunucu her platformda arkada kalmaz.

## 2.11.0 — 2026-10-21

### Yeni
- **Drama 3 TR ses motoru (F176):** Fish Audio Drama 3'ün tam okuyucusu ile 32 uzmanlı Türkçe konuşmacıyı (kasparovabi/drama-3-tr) kullanan yeni ses motoru: duygulu, kayıttan klonlanan ses, tek 16 GB GPU'da, WSL gerekmez. Model (~45 GB: drama-3-tr reposu, fish-speech, orijinal `fishaudio/drama-3`, `speaker.safetensors` ve `.venv` Python ortamı) Aktar klasörüne kopyalanmaz; Ayarlar → Ses → Drama 3 TR → Model klasörü'nden seçilen klasörde durur, Aktar eksikleri adıyla gösterir. Aktar sunucuyu o klasörün Python'uyla kendisi başlatır, ses motoru durunca ya da pencere kapanınca kapatır (Windows'ta Aktar çökse de). Klon kaydı her istekle gider: dublajda konuşmacılara farklı sesler atanabilir, ses değişince sunucu yeniden başlamaz. İlk istekteki ısınma (yaklaşık bir dakika) yüklemede yapılır, okuma başlayınca ilk cümle beklemez. Fısıltı için üç deneme yapılmaz (her istek ~4 sn sabit süre ekliyor; yönerge gücü fısıltıyı zaten belirginleştiriyor). Ayarlar: parça uzunluğu, yönerge gücü (0 kapalı, daha hızlı), temperature. Duygu etiketleri bu motorda da kullanılır.

## 2.10.0 — 2026-10-21

### Yeni
- **Dublaj düzenleyicisi (F175):** Dublaj artık tek seferde yazılmak zorunda değil. Oynatıcıda dalga simgesiyle (ya da CC menüsünden "Dublaj düzenleyicisi") sayfa video düzenleyici düzenine geçer: video sol üstte, sağda satır denetçisi ve satır listesi, altta zaman çizelgesi (özgün sesin dalga biçimi ve kısma aralıkları, altyazı satırları, dublaj sesleri). Dublaj penceresindeki "Düzenleyicide hazırla" aynı seçeneklerle (müzik ayrımı, ifade, konuşmacılar) düzenlenebilir bir proje hazırlar. Her satırın metni ve Drama 3 ifade etiketi düzeltilir, sesi (konuşmacı), hızı ve ses düzeyi değiştirilir; satır metindeki imleçten bölünür, sonrakiyle birleştirilir, silinir ya da yeni satır eklenir. Dublaj sesi sürükleyerek ya da "İmlece taşı" ile istenen ana taşınır; altyazı kutusunun kenarlarından süre değişir. İstenen satır yeniden seslendirilir (önbelleğe bakmadan yeni deneme); metni, etiketi ya da sesi değişen satır "eski" işaretlenir, "Eksikleri seslendir" yalnızca eksik ve eski satırları üretir. Özgün ses şeridinde sürükleyerek istenen aralıkta ses kısılır, aralığın düzeyi ayrı ayarlanır (tamamen susturmak dahil); "Otomatik kısmaya dön" ile eski davranışa dönülür. "Dublajı dinle" açıkken video oynarken satır sesleri yerlerinde çalar ve video sesi kısma aralıklarında kısılır. Ctrl+Z geri alır, S böler, Delete siler, Ctrl+tekerlek yakınlaştırır. "Dışa aktar" projeyi `.dublaj.mkv`/`.m4a` olarak yazar. Proje `work_files/dublaj/` altında saklanır; kaynak videoya dokunulmaz.

## 2.9.0 — 2026-10-21

### Yeni
- **Kayıt kesmede zamanlı metin ve oynatma imleci (F174):** Ses kaydı seçilince Whisper (Ayarlar'daki model) kaydı kelime zamanlarıyla yazıya döker ve metin dalga biçiminin altında görünür; seçimin içindeki kelimeler parlak, dışındakiler soluk, 0,6 sn'den uzun sessizlikler `·` ile gösterilir. Kelimeye tıklamak seçimi oradan başlatır, Shift ile tıklamak orada bitirir. Dalga biçiminin altında zaman cetveli, üzerinde fare imlecinin zamanı ve tutamaçların zamanları yazar. "Seçimi dinle" ve "Tümünü dinle" çalarken oynatma imleci ilerler, çalınan kelime vurgulanır. "Seçilen parçanın metnini yaz" ile seçimin metni Kaydın metni kutusuna yazılır. Metin dosya içeriğine göre saklanır; aynı kayıt yeniden açılınca Whisper çalışmaz.

## 2.8.0 — 2026-10-21

### Yeni
- **Ses kaydından parça kesme (F173):** Yeni ses (ya da sesi düzenle) penceresinde klonlanacak kayıt seçilince dalga biçimi görünür; iki tutamaçla (ya da Baş/Son kutularıyla) istenen aralık seçilir, seçim dinlenebilir. Yeni seçilen uzun kayıtta seçim ilk 20 saniyeyle başlar (modeller yaklaşık bu kadarını kullanır; "20 sn" ve "Tümü" kısayolları var). Kaydedince yalnızca seçilen parça kesilip ses klasörüne `<kimlik>-kayit.wav` olarak yazılır (16 bit mono, uçlarda kısa yumuşatma); özgün dosyaya dokunulmaz. Kayıtlı bir sesin kaydı da yeniden kesilebilir.

## 2.7.0 — 2026-10-21

### Yeni
- **Dublajda ifade aktarma (F172):** Dublaj penceresinde "Gülme, ağlama, iç çekme ve duraklamaları aktar" seçeneği. Özgün konuşma yerelde çözümlenir (sherpa-onnx: CED ses olayı modeli + Silero VAD, ilk kullanımda ~50 MB, sonuç saklanır; müziği koruma açıksa ayrılmış konuşmadan): satırın içinde ya da hemen öncesinde gülme, ağlama, iç çekme, fısıltı, bağırma, nefes ya da öksürük duyulursa satıra Ayarlar → Ses'te seçili Drama 3 etiketlerinden uyanı eklenir (Drama 3 dışındaki motorlar etiketsiz okur). Konuşmacı cümle ortasında duraksadıysa satır en yakın noktalamadan bölünür ve kalanı özgün konuşma yeniden başlayınca çalar (her motorda). Altyazıdaki `(laughs)`, `[GÜLER]`, `*iç çeker*`, `[MUSIC]`, `♪` gibi notlar artık okunmaz; ifade seçeneği açıksa nota göre etiket verilir, yalnızca nottan oluşan satırın ifadesi sonraki satıra geçer.

## 2.6.0 — 2026-10-21

### Yeni
- **Drama 3 etiketleri seçilebilir (F171):** Ayarlar → Ses'te Drama 3'ün altında 25 etiketlik bir katalog var: Fish Audio belgelerinde ve örneklerinde geçen köşeli etiketler (`[laughs]`, `[small laugh]`, `[sighs]`, `[sad]`, `[crying]`, `[excited]`, `[embarrassed]`, `[soft]`, `[breathy]`, `[shaky breath]`, `[clear throat]`, `[pause]`, `[long pause]`, `[whisper]`, `[whispering]`, `[fısıldar]`, `[shouting]`, `[angry]`) ve resmî yedi çift etiket (`<whisper>`, `<soft>`, `<emphasis>`, `<stress>`, `<forceful>`, `<fast>`, `<slow>`). Drama 3'te sabit bir liste yok; her etiketin yanında dinleme setinize göre durumu (Çalıştı / Çalışmadı / Denenmedi) ve hangi anlatıcı sözcüklerinden çıkarıldığı yazar. Varsayılan seçim çalıştığı bilinen beş etiket. Kitaplıktan etiketlerken kelime listesi ve model istemi yalnızca seçilenleri kullanır; seçimden çıkardığınız etiket okurken hemen uygulanmaz, yeni seçtiğiniz etiket için kitabı yeniden etiketlemeniz gerekir (okuyucudaki "Duygulu" düğmesi bunu hatırlatır). Çift etiketler konuşmayı sarar; uzun konuşma bölününce her parçada yeniden açılıp kapanır. `[whisper]`, `[whispering]` ve `<whisper>` da `[fısıldar]` gibi üç denemeyle üretilir.

## 2.5.0 — 2026-10-21

### Değişiklik
- **Duygu etiketleri artık kitaplıktan, bir kez oluşturulur (F170):** Okuyucu bölüm açılırken etiketlemeyi kaldırdı; ses motoru ile dil modeli aynı anda çalışıp belleği dolduruyordu. Kitaplıkta kitaba sağ tıklayıp "Duygu etiketleri oluştur" deyince (model sunucusuyla ya da yalnızca kelime listesiyle) bütün kitabın etiketli sürümü arka planda hazırlanır; iş sağ üstteki arka plan işlerinde görünür, sağ tık menüsünden durdurulur. Bu sırada ses motoru durdurulur ve yeni ses motoru başlatılmaz; işin yüklediği model bitince boşaltılır. Kitaplıkta kitap tek görünür ("duygu etiketli" notuyla); etiketler ve okunabilir etiketli metin `duygu-etiketleri/<kitap>.json` ve `.txt` olarak saklanır ("Etiketli metni göster", "Duygu etiketlerini sil"). Kitabın sesi Drama 3 ise okuyucuda "Duygulu" düğmesiyle etiketli sürüm açılıp kapanır; Ayarlar → Ses'teki seçenek "Etiketli sürüm varsa kullan / Kapalı" oldu. Eski, okurken çıkarılmış etiketler kullanılmaz.

## 2.4.1 — 2026-10-21

### Düzeltme
- **Drama 3 fısıltı daha sık duyulur (F169):** Türkçe Drama 3 `[fısıldar]` etiketini istek başına ancak üçte bir olasılıkla gerçekten fısıldayarak okuyor (etiket biçimi fark etmiyor). Fısıltı etiketli cümle için artık üç deneme üretilir ve atlama/erken bitme denetimlerinden geçenler arasından ses düzeyi en düşük olan seçilir (dinleme setinde kulakla fısıltı sayılanlar çoğunlukla en kısık denemelerdi). Fısıltılı cümleler biraz daha geç hazırlanır; yalnızca fısıltı etiketli cümleler yeniden üretilir, diğer etiketler ve etiketsiz cümleler değişmez.

## 2.4.0 — 2026-10-21

### Yeni
- **Drama 3 duygu etiketleri, deneysel (F168):** Ayarlar → Ses'te Drama 3'ün altında "Duygu etiketleri" seçeneği (varsayılan kapalı). Açıkken okuyucu her bölümün diyaloglarına Türkçe Drama 3'te çalışan etiketleri ekler: gülme `[laughs]`, iç çekme `[sighs]`, fısıltı `[fısıldar]`, bağırma `[shouting]`, öfke `[angry]`. "Kelime listesiyle" kipinde anlatıcının ipucu ("gülerek", "fısıldadı", "bağırdı", "öfkeyle", "içini çekerek"…) aynı ya da bitişik cümledeki konuşmaya atanır, anlatıcı cümlesine verilmez; "Model sunucusuyla" kipinde Modeller'deki sohbet modeli bağlamdan da çıkarır (açık ipuçları korunur). Okuyucudaki metin ve vurgulama değişmez: etiket yalnızca sunucuya giden metne, tırnaktan önce ve parçanın başına eklenir. Etiketler kitap başına saklanır; etiketli cümleler ayrı önbelleğe yazılır, sesli kitap ve bölüm kaydı da etiketleri kullanır. Model etiketle takılıp gülmeyi bitirmezse parça etiketsiz yeniden istenir. Ölçüm (28 diyalog cümlesi × 2 deneme, Whisper karşılaştırması): atlama oranı artmadı, etiketli cümlelerde yeniden deneme biraz arttı; ara sıra model konuşma yerine yalnızca güler.

## 2.3.6 — 2026-10-21

### Düzeltme
- **Drama 3 kısa parçada erken bitirme (F167):** Erken bitirme denetimi gürültü düzeyini parçanın kendisinden ölçtüğü için kısa ve kesintisiz konuşan parçalarda ("…önüne [gitmiştim].", "…ederim, [de]...") hiç devreye girmiyordu; gürültü düzeyi artık klon kaydından ölçülür. Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.3.5 — 2026-10-21

### Düzeltme
- **Drama 3 soru sonrası tek kelime (F166):** "…değil mi? işte…" gibi soru ya da ünlem işaretinden sonra tek kısa kelimeyle biten cümlelerde model soruda bitirip son kelimeyi sıkça atlıyordu (denemelerde üçte bir); sunucuya giden metinde o işaret virgüle çevrilir (okuyucuda görünen metin değişmez, soru tonlaması korunuyor). Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.3.4 — 2026-10-21

### Düzeltme
- **Drama 3 kısa cümleler (F165):** "Dedi.", "— Gevezeliği bırak." gibi kısa cümlelerde model bazen neredeyse hiç konuşmadan (0,2–0,4 sn) bitiriyordu ve cümle duyulmuyordu; kısa parçada konuşma süresi metne göre çok kısaysa parça yeniden istenir. Bu motorla hazırlanmış cümleler yeniden üretilir.

## 2.3.3 — 2026-10-21

### Düzeltme
- **Drama 3 gürültülü klon kayıtlar (F164):** Yankılı ya da arka plan sesi olan bir kayıtla parçaların ~%20'si gereksiz yere "erken bitti" sayılıp yeniden isteniyor, okuma yavaşlıyordu; eşik artık sesin gürültü düzeyine göre ayarlanır. Klon kaydı kırpılırken (20 sn sınırı) cümle sonu yoksa kelimeler arasındaki bir duraklamada kesilir ve sonuna kısa bir ses azaltma eklenir; konuşmanın ortasında biten kayıt modele de sesi birden bitirmeyi öğretiyordu. Klon kayıtları ve bu motorla hazırlanmış cümleler yeniden hazırlanır.

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
