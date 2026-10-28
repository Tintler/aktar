# Değişiklik günlüğü

Sürümler [Anlamsal Sürümleme](https://semver.org/lang/tr/) düzenindedir: yeni özellik ikinci, yalnızca düzeltme üçüncü sayıyı artırır. Ayrıntılı geçmiş `git log` içindeki `F<numara>` commit'lerindedir.

## 2.42.0 — 2026-10-28

### Düzeltilen
- **Kitap görsellerinde kimlikli sahneler (F221):** Gerçek Krea 2 denemelerinde görülen üç sorun giderildi. Tam boy kıyafet referansı artık başı açık ve eşyasız üretiliyor: kemerde kask olan referans, sahnede başta ikinci bir kask çizdiriyordu. Var olan tam boy referanslar bir sonraki üretimde kendiliğinden yenilenir. Kimlik istemi yüz ifadesinin referanstan değil sahneden gelmesini ve referanstaki her kişinin sahnede yalnızca bir kez çizilmesini söylüyor: yüz her sahnede portredeki sakin ifadeyle kalıyor, kişi kimi sahnede iki kez çiziliyordu. Plan çıkarılırken dil modelinden görünen yüzlerin ifadesini somut olarak yazması isteniyor. Çok açılı karakter kâğıdı (QuadView ve Identity Edit) da denendi; kişiyi sahnede çoğalttığı için eklenmedi.

## 2.41.0 — 2026-10-27

### Eklenen
- **Kitap görsellerinde tam boy kıyafet referansı (F220):** "Karakter kimliği" bölümündeki yeni "Tam boy kıyafet referansı" seçeneği açıkken, karakterin giydiği her kıyafet için portresi referans verilerek ayakta, önden, düz fonlu bir tam boy görsel üretilir. Kıyafetli sahneler portre yerine o anki kıyafetin tam boy görseliyle çizilir, böylece kıyafet tarifin yanında görselden de korunur. Bu görseller sahne üretilirken eksik olanlar için kendiliğinden üretilir; kıyafet, görünüş ya da portre değişince yenilenir, artık gerekmeyenler silinir. Kartta küçük görselleri gösterilir ve yeni seed ile yeniden üretilebilir. Yalnızca kimlik iş akışının referans sayısı kadar kişiye üretilir; kıyafeti olmayan karakter (giysisi tarifinde) portresiyle çizilir. Seçenek kapalıyken her şey eskisi gibi.

## 2.40.0 — 2026-10-27

### Eklenen
- **Kitap görsellerinde kıyafet kilidi (F219):** Karakterlerin kıyafeti artık görünüşten ayrı bir alanda tutuluyor ve sahne istemine dil modeli yerine Aktar ekliyor ("Clothing: the man in his fifties wears …"). Böylece kitap kıyafetten söz etmeyince karakter sahneden sahneye aynı giysiyle çiziliyor. Kıyafet değişimleri her parça için ayrı bir soruyla bulunuyor. Kalıcı değişimler (yeni üniforma, eski giysiye dönüş) karakterin "Ad (kıyafet) [5. bölüm]: …" satırına yazılıyor. O ana özgü olanlar (gecelik, can yeleği, zırh, kılık değiştirme) yalnızca o aralıktaki sahnelere ekleniyor. Sahne düzenlenirken "Bu sahneye özel kıyafet" kutusundan elle de verilebiliyor. Portre ve kimlik istemleri de güncel kıyafeti kullanıyor; kimlik açıkken kıyafet referans portreden değil tariften geliyor. Yeni planda "Kıyafet kilidi" seçeneği varsayılan olarak açık; eski planların istemleri değişmiyor.

## 2.39.0 — 2026-10-27

### Eklenen
- **Kitap görsellerinde dört yeni LoRA tarzı ve "Ek LoRA" (F218):** LoRA tarzlarına Sinematik bilimkurgu (DC Sci-Fi), 90'lar retro anime, 80'ler fantastik film ve Neon VHS eklendi; tetik kelimeleri ve güçleri Civitai sayfalarından. Tarzın altındaki yeni "Ek LoRA" satırında "Dinamik pozlar" (More Dynamic Poses, tetik PoseDaal, güç 0,8) herhangi bir tarzla birlikte seçilebiliyor: karakterlere hareketli duruşlar ve farklı kamera açıları katar. Ek LoRA yalnızca sahnelere eklenir, karakter portreleri sade kalır; "dynamic pose" son eki yalnızca istemde insan varsa eklenir. Plan inceleme ekranında ek LoRA açılıp kapatılabilir, gücü değiştirilebilir (görsellere yeniden üretince yansır). LoRA dosyaları ComfyUI'nin models/loras klasörüne konmalı.

## 2.38.0 — 2026-10-27

### Eklenen
- **Kitap görsellerinde "Orta boş" seçeneği (F217):** Yeni planda "Orta boş (koyu)" ya da "Orta boş (açık)" seçilince görselin ortası yazı için boş kalır. Krea ortayı istemle boş bırakmadığı için her sahne iki ayrı geniş şeritte üretilir: dil modeli aynı an için iki kompozisyon yazar ("Top:" üstte görünen gökyüzü, tavan, uzak manzara; "Bottom:" zemin, figürler, nesneler), Aktar ikisini ayrı ayrı üretip üst ve alt kenara yerleştirir, her birini ortaya doğru siyaha ya da beyaza yumuşakça soldurur. Sahne başına iki görsel üretildiği için süre uzar. Eski istemler ("Top:/Bottom:" yoksa) iki şeride de aynı istemle, üst/alt ekiyle gider. İki seçenekten yalnızca biri seçilebilir.

## 2.37.5 — 2026-10-27

### Düzeltilen
- **"Yüz gösterme" açıkken yüzler yine görünüyordu (F215):** Seçeneğin görsel istemine eklediği "arkadan görülen kişiler" eki, kişinin aşağıdan görüldüğü sahnelerde (düşüş, atlayış) ön plana arkası dönük bir seyirci kalabalığı ekletiyordu; ek artık kişi adı taşımıyor ("back view"). Dil modelinin kurala rağmen yazdığı "kameraya bakıyor", yüz ifadesi ve göğüsten yukarı/yakın çekim ifadeleri üretimde istemden ayıklanıyor: kameraya bakış arkasını dönmeye çevriliyor, yüzü anlatan yan cümle atılıyor. Kayıtlı istem değişmiyor; var olan planlarda görselleri yeniden üretmek yetiyor. Dil modeline giden kural da yakın çekim, kameraya bakış ve yüz ifadesini açıkça yasaklıyor. Gerçek dil modeliyle (Gemma 4 26B, Qwen 3.6 35B; Yıkıma Giden Adam ve Compulsory) denendi: yeni kuralla yüz anlatan istemler yaklaşık yarıya iniyor, kalanlar ayıklanıyor; kişiyi tarif eden "yorgun yüzlü" gibi ifadeler korunuyor.

## 2.37.4 — 2026-10-27

### Düzeltilen
- **Kitap görsellerinde dil modeli hataları sahne kaybettiriyordu (F214):** Yanıttaki JSON'dan sonra açıklama, ikinci bir nesne ya da sondaki virgül olunca parça sessizce sahnesiz geçiyordu; okunamayan yanıt bölüm açılış sayfasını kalıcı olarak "hikâye dışı" sayıyordu. JSON artık sağlam ayıklanıyor, okunamayan ya da token sınırında kesilen yanıt iki kez yeniden isteniyor. Yine okunamayan parça planı durdurmuyor; plan sonunda bildiriliyor ve pencerede "Yeniden dene" ile yalnızca o parçalar tekrar soruluyor. Açılış yalnızca model sayfayı açıkça atladıysa bir daha sorulmuyor.
- "Baştan planla" eski planı ve görselleri iş başlamadan siliyordu; dil modeli kapalıysa elde hiçbir şey kalmıyordu. Eski plan artık yedekte bekliyor, yeni plan kaydedilemezse geri konuyor, yeni plan tamamlanınca siliniyor.
- Görsel üretiminde tek bir hata bütün kuyruğu durduruyordu: hatalı görsel kartında hatasıyla işaretlenip sıradakine geçiliyor ("Eksikleri üret" yeniden dener); art arda üç hata olursa iş duruyor. ComfyUI'nin tek bir yoklamaya geç yanıt vermesi işi bozmuyor, kuyrukta bekleme süresi görselin süresine sayılmıyor.
- Plan çıkarılırken yapılan stil, karakter ve sahne düzenlemeleri planın sonraki kaydında kayboluyordu: plan sürerken düzenleme engelleniyor, plan işi kendi kopyasında çalışıyor.
- Çok bölümlü kitapta stil kılavuzu örneği ilk bölümlerde bitiyordu (200 bölümde ilk 62); artık her bölümden pay alınıyor.
- Tam ekran okuyucuda cümle bölme ayarı değişince görsel yanlış cümlede açılıyordu; sahnenin ilk cümlesi birleşen ya da bölünen cümlelerde de bulunuyor.

## 2.37.3 — 2026-10-27

### Düzeltilen
- **"Yüz gösterme" insansız sahnelere siluet ekliyordu (F213):** Seçeneğin "arkadan ya da siluet olarak görülen figürler" eki her görsel istemine gidiyordu; görsel modeli boş odaya, masaya, manzaraya da arkası dönük biri ekliyordu. Dil modeli de kuralı her sahneye bir kişi koymak gibi anlıyordu. Ek artık yalnızca istemde insan geçen sahnelere gidiyor; kural yalnızca metnin sahneye koyduğu kişiler için ve figür eklenmemesini açıkça söylüyor. Gerçek dil modeliyle (Qwen 3.6, Gemma 4) denendi: insansız sahneler figürsüz kalıyor. Var olan planlarda görselleri yeniden üretmek yetiyor; sahne istemleri için planı yeniden çıkarmak gerekir.
- Karakter kimliği "Yüz gösterme" ile birlikteyken portrenin yüzü değil saçı, yapısı ve giysisi korunuyor (öne bakan yüz sahneye taşınıyordu).
- Dil modelinin talimata rağmen yazdığı yalın olumsuz cümleler ("No faces are shown.") istemden atılıyor; olumsuz istem çalışmayan modelde tersine o şeyi çizdiriyordu.
- ComfyUI: iş akışında önizleme düğümü varsa onun geçici çıktısı yerine kaydedilen görsel alınıyor; stil ile istem birleşirken nokta ikilenmiyor.

## 2.37.2 — 2026-10-27

### Düzeltilen
- **Kitap görselleri penceresi açılmıyordu (F212):** Bir parçadaki iki sahne aynı yeni karakteri tanıtınca plan o karakteri iki kez yazıyordu; pencere bu planda "Yükleniyor…"da kalıyor, plan bitince de hiç planlanmamış gibi görünüyordu. Karakterler artık tekrarsız birleştiriliyor; tekrarlı eski planlar açılırken kendiliğinden onarılıyor.

## 2.37.1 — 2026-10-27

### Düzeltilen
- **Ufak tefek karakterler çocuk gibi çiziliyordu (F211):** Dil modeli bazı karakterlere yaş ve cinsiyet yazmadan ("small, slight build") tarif veriyordu; görsel modeli bunları iri kafalı bir çocuk olarak çiziyor, portre de sahnelere bu yüzü taşıyordu. Karakter tarifleri artık açık yaş ve cinsiyetle başlıyor ("Man in his fifties"); yaş vermeyen tarif dil modeline bir kez yeniden yazdırılıyor, yine yaşsız kalan insan tarifi portre ve sahne istemlerinde yetişkin sayılıyor. Hayvan, robot, yaratık ve ruh gibi insan olmayan karakterler ayrıca işaretleniyor; onlara yaş eklenmiyor. Var olan planlarda portreyi yeniden üretmek yetiyor.
- **Sahne kartında kitabın bölüm adı:** Kartlar okuyucunun dosya sırasını ("Bölüm 9") değil, kitabın içindekilerdeki adı ("1. bölüm", "Sunuş") gösteriyor; okuyucudaki numara ipucunda.

## 2.37.0 — 2026-10-27

### Değişen
- **Her bölüm başında görsel (F210):** Bölüm açılış görseli artık sıklıktan bağımsız; "Çok seyrek"te bile her bölüm bir görselle açılıyor. Seçenek Sıklık satırının yanına taşındı. Görsel ayrı bir istekle ve yalnızca bölümün ilk sayfasından yazılıyor: dil modeli bölümün devamını görmediği için okurun henüz okumadığı bir şeyi göstermiyor. Kısa bölümler de açılış alıyor; künye, ithaf, yazarın hayatı gibi hikâye dışı sayfaları model atlıyor ve bu sayfalar bir daha sorulmuyor.
- **Eksik bölüm açılışlarını tamamla:** İnceleme ekranındaki düğme, var olan planı silmeden açılış görseli olmayan bölümlere görsel ekliyor.

## 2.36.0 — 2026-10-26

### Yeni
- **Kitap görsellerinde daha seyrek sıklık (F209):** Sıklık seçeneklerine "Seyrek" (yaklaşık 10 sayfada bir) ve "Çok seyrek" (yaklaşık 25 sayfada bir) eklendi. Az ve daha seyrek sıklıkta dil modeli kitabı sahne değişimlerinden bölmüyor; dönüm noktaları, doruk anlar, güçlü ya da çarpıcı sahneler ve önemli karakterlerin ilk göründüğü yerler gibi önemli anları seçiyor. Seyrek ve Çok seyrekte her bölümden önem puanlı aday anlar toplanıyor, plan bitince kitabın tamamından en önemlileri birbirine çok yakın düşmeyecek şekilde seçiliyor; eşit önemde kitaba yayılanlar öne geçiyor. Sahne kartında önem puanı görünüyor.
- **Tarzı değiştir:** İnceleme ekranında "Baştan planla"dan ayrı bir düğme. Plan ve sahne istemleri aynen kalıyor; yeni hazır tarz, LoRA tarzı ya da notla dil modeli yalnızca stil kılavuzunu yeniden yazıyor (istenirse kılavuz olduğu gibi kalır, yalnızca tarz ve LoRA değişir). Ardından bütün görseller aynı seed'lerle yeni tarzda yeniden üretiliyor; karakter kimliği açıksa kullanıcının kendi koymadığı portreler de yenileniyor.
- **Bölüm açılış görseli (seçenek):** Her bölümün başında, ilk satırlar okunurken bölümün mekânını ve havasını gösteren geniş bir görsel. Tam ekran okuyucuda ve sesli kitap videosunda bölümün ilk cümlesinde görünüyor. Kısa bölümler ve hikâye dışı ön kısım (yazarın hayatı, künye) açılış görseli almıyor.
- **Mekân kimliği (seçenek):** Sık geçen mekânlara sabit bir tarif yazılıyor; sahne yalnızca mekânın adını taşıyor, kalıcı tarif üretimde isteme ekleniyor. Mekân tarifleri inceleme ekranında düzenlenebiliyor ve yeniden üretilen görsellere yansıyor; her sahnenin mekânı karttan değiştirilebiliyor.
- **Görünüm değişimi (seçenek):** Karakter yaşlanır, kıyafeti, saçı değişir ya da yara izi kalırsa sonraki sahneler yeni görünüşle yazılıyor. Karakterler kutusunda "Ad [5. bölüm]: yeni görünüş" satırıyla düzenlenebiliyor; karakter kimliği açıkken de sahnenin yerindeki görünüş kullanılıyor (portre aynı yüz olarak kalıyor).
- **RTX büyütme (seçenek):** Üretilen her görsel ComfyUI'de NVIDIA RTX Video Super Resolution ile 1,5×, 2×, 3× ya da 4× büyütülüyor. Kullanıcının iş akışına dokunulmuyor; Aktar görseli geri yükleyip kendi küçük iş akışıyla büyütüyor. Var olan görseller yeniden üretilmeden büyütülebiliyor; katsayı değişince yalnızca aradaki fark kadar büyütülüyor. ComfyUI'de "Nvidia RTX Nodes" eklentisi ve RTX ekran kartı gerekiyor.

## 2.35.0 — 2026-10-26

### Yeni
- **Sesli kitap videosu tam ekran okuyucu gibi (F208):** Video artık yalnızca görsellerden oluşmuyor; tam ekran okuyucunun görünümü kare kare yazılıyor. Okunan cümle grubu ortada, arkada kitap görselleri (yazı bandı ve yazının çevresindeki parıltıyla) ya da düz renk. Yazı okuyucudaki gibi Kayma ya da Belirme ile değişiyor, görseller yumuşakça geçiyor; bölüm başlarında da geçiş var.
- **Kaydetme penceresi:** Okuyucuda Kaydet → "Kitabın tamamı: sesli kitap ya da video…" bir pencere açar. Burada biçim (Video MP4, M4B, MP3 klasörü), ses ve video görünümü seçilir: arka plan, yazı açık/kapalı, yazı ve görsel geçişi, yazı boyutu, yazı tipi, renk, yazı bandı ve çözünürlük (1080p/720p). Önizleme, videonun gerçek bir karesidir. Seçimler hatırlanır.
- **Ses seçimi:** Pencerede okuyucunun sesi ve Hazırla'daki diğer sesler (kayıtlı sesler, yerel/bulut) listelenir; her birinin yanında kitabın ne kadarının o sesle hazır olduğu yazar. Tamamı hazır bir ses, ses motoru yüklenmeden ve okuyucunun sesi değişmeden yazılır. Eksiği olan ses kayıt süresince okuyucunun sesi olur; kayıt bitince, durdurulunca ya da hata olunca önceki ses geri gelir.
- Bölümlerin görüntüsü ayrı saklanır: durdurulan video kaldığı bölümden sürer, ayar değişmeyen bölüm yeniden çizilmez.

## 2.34.0 — 2026-10-26

### Yeni
- **Sesli kitap videosu (F207):** Okuyucuda Kaydet → "Sesli kitap videosu: MP4" kitabın tamamını tek bir MP4 olarak yazar: ses sesli kitabınki (bölüm işaretli), görüntü kitap görselleri. Her görsel, tam ekran okuyucunun Görselli arka planındaki gibi sahnesinin ilk cümlesi okunurken gelir; ilk sahneye kadar kapak görünür. Görsel 1920×1080 kareye sığdırılır, boş kalan yer aynı görselin bulanık hâliyle dolar. Kitabın bütün sesi hazırlanmışsa (Hazırla) ses motoru yüklenmeden yazılır; bu M4B ve MP3 için de geçerli.

## 2.33.1 — 2026-10-26

### Düzeltme
- **Drama 3 parantezli cümleyi okumuyordu (F206):** "(Eğlence akışındaki hayali insanlar…)" gibi parantezle başlayan cümleyi model yönerge sanıp okumuyor, yerine klon kaydının metnini okuyordu (OpenRouter'da 4/4 deneme). Modele giden metinden parantezler çıkarılır; okuyucuda görünen metin değişmez. Daha önce yanlış kaydedilmiş cümleler kendiliğinden yenilenmez (ödenmiş sesler korunur): sağ tık → "Bu cümle öbeğini yeniden seslendir".

## 2.33.0 — 2026-10-26

### Yeni
- **Cümle öbeğini yeniden seslendirme (F205):** Okuyucuda bir cümleye sağ tıklayıp "Bu cümle öbeğini yeniden seslendir" seçilince yalnızca o cümle (grup okuyan motorlarda birlikte okunan cümleler) yeniden üretilir; kitabın geri kalanı ve hazırlanmış sesler değişmez, yeni ses hemen çalınır. Eski ses silinmez: "Önceki sesine dön" ile geri alınabilir (bir daha seçince yeni sese döner). Sesli kitap kaydı ve bölüm WAV'ı yeni sesi kullanır. Menüde ayrıca "Buradan oku" var.

## 2.32.1 — 2026-10-26

### Düzeltme
- **Kitap görselleri planı hiç başlamıyordu (2.32.0):** "Durdur" için eklenen denetim, işin durdurulduğunu yanlış anlayıp planı dil modeline hiç göndermiyordu; pencere "bölümler okunuyor"da kalıyordu. Başlatma artık kendi numarasıyla tanınır.

## 2.32.0 — 2026-10-26

### Yeni
- **Okurken hazırlanmış ses önerisi (F203):** Oynat düğmesine basıldığında bölüm başka bir sesle (kayıtlı ses, motor sesi, yerel/bulut) seçili sesten daha çok hazırlanmışsa, en çok hazırlanan ses kaç cümlesinin hazır olduğuyla birlikte önerilir; seçilirse o sese geçip okur. Seçili ses zaten en çok hazırlanan ise sorulmaz.

### Düzeltme
- **Kitap görselleri planı:** Bölümler okunurken "Durdur" artık bekleyen başlatmayı bırakır (önceden pencere "bölümler okunuyor"da kalabiliyordu). Planın her adımı (ses motorunu durdurma, ComfyUI belleğini boşaltma, dil modeline ilk istek) Konsol'a yazılır; dil modeline istek gitmezse nerede beklediği görülür.

## 2.31.0 — 2026-10-26

### Yeni
- **Kitap görsellerinde LoRA tarzları (F202, Krea 2):** Hazır tarzların altına sekiz LoRA'lı tarz eklendi: Fever Dream, Pastel neon sis (YFG Fwshn), Grimm yağlıboya, Karanlık fantastik (Dark Fantasy), Eskiz (KreaSketching), Kaotik şekiller (Chaotic Shapes), Fantastik illüstrasyon (DC Dark Fantasy Style 7) ve Devasa gelecek (DC Colossal Future). Tarz seçilince LoRA dosyasının ComfyUI'de olup olmadığı denetlenir; üretimde LoRA iş akışına kendiliğinden eklenir (iş akışını değiştirmek gerekmez) ve tetik kelimesi istemin başına yazılır. LoRA gücü plan ekranında değiştirilebilir. Dosyalar ComfyUI'nin `models/loras` klasöründe olmalı (alt klasörde ya da adı biraz değişmiş olsa da bulunur).
- **Tarzdan bağımsız seçenekler:** "Karakter olmasın", "Yalnızca manzara" ve "Yüz gösterme" düğmeleri herhangi bir tarzla birlikte seçilebilir (ör. Fever Dream + Yalnızca manzara). Dil modeline kesin kural olarak verilir, görsel istemine de olumlu ifade olarak eklenir; karakter çizilmeyen seçeneklerde karakter kimliği kapanır.

## 2.30.0 — 2026-10-26

### Yeni
- **Kitap görsellerinde karakter kimliği (F201, isteğe bağlı):** Kitap görselleri penceresinde yeni **Karakter kimliği** anahtarı; açılınca karakterler her görselde aynı yüzle çıkar. Her karaktere düz fonlu bir portre üretilir (ya da kendi görselinizi seçersiniz), karakterli sahneler bu portre referans verilerek ikinci bir ComfyUI iş akışıyla (ör. Krea 2 Identity Edit LoRA'sı ve ComfyUI-Krea2Edit düğümleri) çizilir. Kapalıyken görseller eskisi gibi yalnızca metin tarifinden üretilir; var olan planlar ve görseller değişmez.
- Kimlik açıkken planlanan kitaplarda dil modeli her sahnede görünen karakterleri yazar ve onların pozunu, bakışını, ifadesini ayrıca tarif eder (portredeki duruş sahneye kopyalanmasın). Eski planlarda karakterler sahne isteminden bulunur. Her sahne kartında karakter düğmeleriyle kimin referans alınacağı değiştirilebilir; portresi olmayan karakterin portresi sahneden önce kendiliğinden üretilir.
- **Ayarlar → Kitap görselleri → Karakter kimliği iş akışı:** "Export (API)" ile dışa aktarılan iş akışı; Aktar portreyi başlığı "REFERENCE" olan LoadImage düğümüne (ikinci kişi için "REFERENCE-B") koyar.

## 2.29.3 — 2026-10-26

### Düzeltme
- **Önceden kaydedilmiş sesler yeniden kayıtsız görünüyordu (F200):** 2.29.1'deki sayı okuma düzeltmesi, sıra sayısı ya da Romen rakamı içeren cümlelerin (ve okuyucu cümleleri gruplayarak okuduğu için o cümlenin bulunduğu bütün grubun) ses önbelleği anahtarını değiştirmişti; tarih kitaplarında bölümlerin bir kısmı "hazır değil" görünüyor, OpenRouter'da parası ödenmiş sesler yeniden istenecekti. Artık bu cümlelerin eski kaydı varsa o kullanılır; yalnızca hiç kaydedilmemiş cümleler sayılar yazıyla okunarak üretilir.

## 2.29.2 — 2026-10-26

### Düzeltme
- **Kitap görselleri, tam ekranda görsel geçişi (F199):** Kapak gibi içi boş bölümü olan kitaplarda sahneler bir önceki bölüme bağlanıyordu; tam ekran okuyucu görselli kipte okunan bölümün sahnelerini bulamıyor, tek görselde takılıyordu. Plan artık okuyucunun bölüm numarasını saklar. Eski planlar kitap ilk açıldığında kitabın metniyle bir kez onarılır (her sahnenin başlangıç cümlesi yeni bölümünde aranır, eşleşmezse plana dokunulmaz); görselleri yeniden üretmek gerekmez.

## 2.29.1 — 2026-10-25

### Düzeltme
- **Drama 3 TR sayı okuma (F198):** Sıra sayıları ve Romen rakamları modele yazıyla gider: "44. bölüm" artık "kırk dördüncü bölüm", "IV. Murad" "Dördüncü Murad", "XV. yüzyıl" "on beşinci yüzyıl" okunur. OpenRouter'daki orijinal Drama 3 bunları "kırk dört bölüm" diye ya da harf harf okuyordu. Okuyucuda görünen metin değişmez; ses önbelleğinde yalnızca bu kuralın değiştirdiği cümleler yeniden okunur.

## 2.29.0 — 2026-10-25

### Yeni
- **Kitap görselleri (F197):** Kitaplıkta kitaba sağ tıklayıp **Kitap görselleri oluştur** denince dil modeli kitabı okur, sahne değişimlerini seçer ve her sahne için bir görsel istemi yazar; görseller yerel **ComfyUI**'de (ör. Krea2) üretilir. Bütün görseller kitap için bir kez yazılan tek bir stil kılavuzu ve sabit karakter tarifleriyle üretilir, böylece kitap boyunca aynı tarzda kalır.
- Görsellere söz hakkı: planlamadan önce **kitap notu** ("daha soyut ol, yüz gösterme") ve hazır tarzlar (Sinematik, Suluboya, Gravür, Soyut, Sade), sıklık (Az / Orta / Çok). Plan bitince stil ve karakterler düzenlenebilir; her sahnede kısa bir **Düzelt** notu ("daha karanlık", "kişiyi çıkar") istemi sahneyi baştan kurmadan en az değişiklikle yeniden yazar. Ayrıca **Yeniden dene** (yeni seed), **İstemi düzenle** ve **Görsel olmasın**.
- Tam ekran okuyucuda yeni **Arka plan: Düz | Görselli** seçimi (Görünüm menüsü). Görselli kipte yazı ortada kalır, sahnenin görseli üstte ve altta açık, ortaya doğru koyulaşan bantla yazıya bağlanır; sahne değişince görsel çapraz geçişle değişir. Bant koyuluğu ayarlanabilir. Var olan düz görünüm değişmedi.
- **Ayarlar → Kitap görselleri:** ComfyUI adresi, iş akışı ("Export (API)" ile dışa aktarılan JSON; düğümler "Positive", "PRE-PROMPT", "POST-PROMPT" başlıklarından bulunur), görsel boyutu ve bağlantı denemesi.
- Plan ve üretim arka planda sürer (sağ üstteki işler), durdurulabilir; yarım kalan plan kaldığı yerden sürdürülür. Dil modeli ile görsel modeli aynı GPU'yu paylaştığı için planlamadan önce ComfyUI'den modellerini bırakması istenir, plan bitince dil modeli boşaltılır, plan sürerken ses motoru başlatılmaz. Seslendirilmiş kitapların ses önbelleğine dokunulmaz.

## 2.28.2 — 2026-10-25

### Düzeltme
- Sol menüde **Ekran Çeviri**, **Dosya incele**'nin hemen altına taşındı.

## 2.28.1 — 2026-10-25

### Düzeltme
- Ekran Çeviri: sol menüde ve iş tepsisinde oyun kolu yerine ekran-çeviri simgesi.
- Sayfa metinleri yalnızca oyunlara değil her ekrana göre yazıldı: oyunlar artık **profil** (Yeni profil, Profil ekle), "Oyunun dili" → "Ekrandaki yazının dili", "oyunun renkleri" → "özgün renkler".
- Bölgeler sekmesinde uzun seçenekli bölge kartları (ör. "Yalnızca cümleler (diyalog, hikaye, açıklama)") sayfayı sağa taşırıyor, üstteki profil seçici ekranın dışında kalıyordu: kartlar ve açılır listeler artık sütuna sığar.

## 2.28.0 — 2026-10-25

### Yeni
- **Ekran Çeviri (F196):** Sol menüdeki "Oyun Çevirisi" sayfasının adı **Ekran Çeviri** oldu (oyunların yanında ekrandaki her türlü yazı için de kullanılabilir).
- Tarama kipinde çevirisi beklenen yazı o sırada boş bir kutuyla örtülür: özgün İngilizce çeviri gelene kadar görünmez. Harf harf gelen tek satırın kutusu sağa geniş tutulur, yeni gelen harfler de örtülür.
- Tarama kutuları oyundaki yazının zemin ve yazı rengini alır, yazı boyu ve satır aralığı özgün yazıya oturur (OCR kelime yüksekliği yazı boyunun ~%73'ü olarak ölçüldü). Ayarlar sekmesinden kapatılabilir.

### Düzeltme
- Diyalog geçince ya da kutu kapanınca çeviri ekranda gecikmeli kalıyordu: çeviri kutusunun altındaki alan her turda ucuzca denetlenir; yazı kalkınca kutu hemen (~0,1–0,4 sn) kaybolur, yerine yeni yazı geldiyse boş kutuyla örtülür.
- "Yalnızca cümleler" kipinde düğme çubukları ve ad dizileri (`Skill Details Hide Tips Back`, `Bronze Chestplate Earrings of Health`) cümle sayılmıyor: noktalamasız ve her kelimesi büyük harfle başlayan yazı çevrilmez.

## 2.27.0 — 2026-10-25

### Yeni
- **Oyun Çevirisi — ekran taraması (F195):** Bölgeler sekmesindeki **Tüm ekranı tara** (ya da bir bölgede "Her yazının üstünde" yerleşimi) ekrandaki her yazıyı ayrı bulur ve çevirisini oyundaki yazının tam üstüne, aynı boyda basar. Yazılar Windows OCR'ın kelime konumlarıyla paragraflara ayrılır; yerleşen yeni yazılar tek istekte toplu çevrilir ve akarken biten her çeviri hemen görünür; önbellektekiler beklemeden gösterilir. Yazı ekrandan kalkınca (sahne değişince) çevirisi de kalkar.
  - Varsayılan **Yalnızca cümleler**: diyalog, hikaye, görev ve açıklama metinleri çevrilir; beceri, silah ve menü adları, nitelik etiketleri ve puanlar (Lv, HP, MP, AP) oyundaki gibi kalır. İstenirse "Menüler dahil her yazı".
  - Uzun yazının hemen üstündeki tek satırlık ad (ör. `Innkeeper`) konuşan olarak bağlama verilir.

### Düzeltme
- Ekranda bölge seçerken ekranın o anki görüntüsü donar ve seçim onun üzerinde yapılır; bölge önizlemesi tam olarak seçilen alandan kesilir (önceden seçimden sonra yakalandığı için geri açılan Aktar penceresi görünebiliyordu).
- Boş oyun sayfasındaki "Oyun ekle" düğmesinin simgesi görünmüyordu (yazı ortalanmamış duruyordu).
- İsimler ve terimler sekmesi: ekleme alanı ayrı bir kutuda, kayıtlı adlar başlıklı bir tabloda.

## 2.26.0 — 2026-10-25

### Yeni
- **Oyun Çevirisi (F194):** Türkçesi olmayan oyunlarda ekrandaki yazı okunup Türkçe çevirisi oyunun üstünde gösterilir. Sol menüdeki yeni sayfadan oyun eklenir, ekranda okunacak bölgeler (ör. diyalog kutusu, konuşanın adı) fareyle seçilir ve çeviri başlatılır. Oyunun dosyalarına, belleğine ya da kurulumuna dokunulmaz; yalnızca ekranda görünen okunur.
  - Yazı Windows'un kendi OCR'ıyla okunur (ekran kartı kullanılmaz, okuma ~10 ms); dil paketi yoksa Tesseract. Bölge yalnızca değişince okunur; harf harf gelen diyalog yerleşince bir kez çevrilir.
  - Çeviri, Aktar'ın model sunucusuna akışlı istekle gider; sayfada ayrı bir çeviri modeli seçilebilir. Önceki satırlar ve konuşan karakterin adı bağlam olarak verilir. Çevrilen cümleler oyuna özel önbellekte tutulur: aynı cümle (yazı daha ekrana gelirken bile) anında gösterilir.
  - Oyuna özel isim/terim listesi: karşılığı boş adlar çevrilmez; büyük harfli ad (`Rain`) yalnızca büyük harfle geçince eşleşir, cümle başında model bağlama göre karar verir.
  - Katman tıklamaları geçirir, odak almaz, Alt+Tab'da görünmez ve ekran yakalamaya girmez (Aktar kendi Türkçe yazısını yeniden okumaz). Çeviri bölgenin altında, üstünde, orijinal yazının üzerinde ya da seçilen bir yerde gösterilir; yazı boyutu, renkler ve saydamlık ayarlanır.
  - Süslü/dekoratif yazılar için bölge "Görsel model" ile okunabilir; bölge yokken "Şimdi çevir" ekranın tamamını görsel modele gönderir.
  - Ayarlanabilir genel kısayollar: çeviriyi aç/kapat (Ctrl+F9), katmanı gizle/göster (Ctrl+F10), şu anki ekranı şimdi çevir (Ctrl+F11). Oyun pencereli tam ekran (borderless) modunda çalışmalıdır.

## 2.25.3 — 2026-10-24

### Düzeltme
- Kitap çevirisi sözlüğünde büyük harfle başlayan terimler (ör. `Preservation`) özel isim sayılır ve yalnızca büyük harfli yazımla eşleşir; küçük harfli "preservation" (koruma) sözlük düzeltmesi istemez. Kitapta küçük harfle sıradan kelime olarak da geçen tek kelimelik bir özel isim cümle ya da paragraf başındaysa zorunlu düzeltmeye girmez; orada karar sözlük talimatıyla modele bırakılır. `Preservation Station` gibi çok kelimeli terimler her yerde denetlenir.

## 2.25.2 — 2026-10-24

### Düzeltme
- Kitap çevirisi sözlüğünde tamamı büyük harfli kısaltmalar (ör. `ART -> GAT`) artık yalnızca aynı yazımla eşleşir: küçük harfli "art" (sanat) geçen bölümlerde sözlük düzeltmesi istenmez ve modele bu terimin yalnızca büyük harfli yazımla geçerli olduğu söylenir. `ART` ve `art` sözlükte ayrı kayıt olarak tutulabilir.

## 2.25.1 — 2026-10-24

### Düzeltme
- Kayıtlı sesler listesi geniş pencerede yan yana sütunlara dizilir (sığarsa 3 sütun); sıra soldan sağa okunur, taşıma okları "öne / sona doğru" oldu.

## 2.25.0 — 2026-10-24

### Yeni
- **Ses önizlemesi (F191):** Metinden ses → Kayıtlı sesler sekmesi artık sayfanın tamamını kullanır; bir sese tıklayınca sağdaki panelde örnek metin yazılıp o sesle okutulabilir. Beğenilen okuma "Önizleme olarak sakla" ile sesin önizlemesi olur: listedeki ▶ düğmesi ve dublajdaki ses seçicileri bu okumayı çalar. Ses başka bir motora geçirilince önizleme silinir.

## 2.24.2 — 2026-10-24

### Düzeltme
- "Başka seslerle hazır" araması yaklaşık 4 kat hızlandı: kitabın duygu etiketleri ve önbellek dosyaları her ses için yeniden okunmuyor.
- "Hazırla" menüsü arama sürerken "aranıyor…", hiçbir ses bulunmazsa "Bu bölüm başka bir sesle hazırlanmamış" yazar. Menü açılınca denenen sesler ve hazır cümle sayıları Konsol'a yazılır.

## 2.24.1 — 2026-10-24

### Düzeltme
- "Hazırla" menüsünde tek bir sesin okunamaması bütün "Başka seslerle hazır" listesini boşaltıyordu; artık o ses atlanır, hata Konsol'a yazılır. Liste menü her açıldığında yenilenir.
- Ayarlar aynı uzunlukta art arda kaydedilince eski değer okunabiliyordu (`ui.json` önbelleği).

## 2.24.0 — 2026-10-24

### Yeni
- **Başka seslerle hazırlanan bölümler (F190):** Okuyucudaki "Hazırla" menüsü, bölüm başka bir kayıtlı sesle, başka bir motorla ya da Drama 3 TR'nin öteki çalışma yeriyle (yerel / bulut) hazırlandıysa onları "Ses adı · Motor — 150/150 hazır" biçiminde listeler; tıklayınca o sese geçilir, yeniden hazırlamaya gerek kalmaz. Böyle bir ses varsa "Hazırla" düğmesinde sayısı görünür.

### Değişiklik
- Ayarlar'daki duygu etiketlerinden "deneysel" notu ve etiketlerin yanındaki Çalıştı / Çalışmadı / Denenmedi işaretleri kaldırıldı.

## 2.23.0 — 2026-10-23

### Yeni
- **Tam ekran okumada görünüm menüsü (F189):** Üst satırdaki "T" düğmesi yazı boyutunu (24-120, klavyede + / −), rengi ve geçişi seçtirir; seçimler saklanır. Okuyucunun sayfa rengine ek olarak uzaktan okumaya uygun sekiz renk çifti var (gece, siyah üstüne sarı, sıcak koyu, lacivert, yeşil, sepya, beyaz, sarı üstüne siyah). Seçilen boyut üst sınırdır: uzun grup ekrana sığmazsa yazı yalnızca o grup için küçülür.
- **Belirme geçişi:** Kaymaya ek olarak eski parça hafifçe küçülüp söner, yenisi yavaşça belirir.

### Değişiklik
- Grup içinde okunan cümle artık ayrıca vurgulanmaz, bütün grup aynı parlaklıkta durur: vurgu Drama 3'ün okuduğu yerle tam örtüşmüyordu.
- Fare durunca ilerleme çubuğu da düğmelerle birlikte gizlenir.

## 2.22.0 — 2026-10-23

### Yeni
- **Tam ekran sesli okuma (F189):** Okuyucunun üst çubuğundaki yeni düğme (yer imi ile görünüm düğmesinin arasında) ekranı kaplar ve yalnızca o anda okunan parçayı büyük yazıyla gösterir. Parça bitince eskisi yukarı kayıp kaybolur, yenisi aşağıdan gelir; birkaç cümlelik grupta okunan cümle parlak, diğerleri soluk görünür. Fare 2,5 saniye durunca üst satır ve düğmeler gizlenir. Boşluk oynatır/duraklatır, Esc çıkar; çıkınca sayfa okunan yere kayar. Okuyucunun sayfa rengi ve yazı tipi kullanılır.

### Düzeltme
- **Sesli okurken ekran kararıyordu:** Okuyucu sesi Web Audio ile çaldığı için Windows bunu etkinlik saymıyor, ekran kararma süresi dolunca ekran (ve ekrana bağlı hoparlör) kapanıyordu. Artık okuma sürdükçe ekran kararmaz ve bilgisayar uykuya girmez; duraklatınca, okuma bitince ya da pencere kapanınca istek bırakılır. Linux'ta aynı iş `systemd-inhibit` ile yapılır.

## 2.21.0 — 2026-10-23

### Yeni
- **Drama 3 TR OpenRouter üzerinden de çalışır (F188):** Ayarlar → Ses → Drama 3 TR'de "Çalışma yeri" seçilebilir: yerel klasör (GPU) ya da OpenRouter (bulut, ücretli). Kayıtlı sesler (klon kaydı ve metni) iki yerde de aynen kullanılır; kayıt her istekle gider (MP3, 64 kbit/sn). Bulutta orijinal Fish Audio Drama 3 (`fish-audio/drama-3`) çalışır, yerel klasördeki 32 uzmanlı Türkçe konuşmacı değil. API anahtarı işletim sisteminin şifre deposunda durur; "Anahtarı dene" ses üretmeden anahtarı, harcamayı ve kalan sınırı gösterir. Hız sınırında (429) ve sağlayıcı hatasında istek bekleyip yeniden denenir. "Yönerge gücü" yalnızca yerel kipte vardır. Bulutta üretilen sesler yerel seslerden ayrı önbelleğe alınır; yerel önbellek geçerli kalır.
- **OpenRouter istekleri Konsol'da görünür:** Her istek (karakter sayısı, süre), hız sınırı, hata ve yanıtsız kalan istek Konsol'a yazılır; 90 saniyede yanıt gelmezse istek yeniden denenir (eskiden hazırlama sessizce bekliyordu).
- **Hazırla uzun bölümde dakikalarca 0'da kalıyordu:** Okuyucunun bölüm planı (F186) her cümle grubu için motor dosyalarını ve ui.json'u diskten yeniden okuyordu; 853 cümlelik bölümde tek plan 22,8 sn sürüyordu, okuyucu da aynı anda birkaç kez soruyordu. Artık motor listesi 2 saniye, ui.json değişene kadar bellekte tutulur: aynı plan 0,6 sn. Yerel kipte de geçerli.
- **OpenRouter'ın yavaş akan yanıtı Hazırla'yı durduruyordu:** Fish arada bir sesi gerçek zamandan çok yavaş gönderiyor (ölçümde 68 karakterlik parça 62 sn, normali 1-2 sn). Veri geldiği için zaman aşımı dolmuyor, Hazırla dakikalarca aynı cümlede bekliyordu. Artık 15 sn'den sonra gelen ses geçen sürenin yarısından azsa, yanıt 90 sn'de bitmezse ya da model metne göre çok uzun ses üretirse istek kesilip yeniden gönderilir; 30 sn'yi geçen istek Konsol'a yazılır.
- **Hazırla takılırsa nerede beklediği görünür:** İş 2 dakika ilerlemezse beklediği kod satırları Konsol'a bir kez yazılır.
- Not: OpenRouter ücreti klon kaydının metnini de sayar gibi görünüyor; denemede kitabın iki sayfası ~0,02 $ tuttu.

## 2.20.0 — 2026-10-23

### Yeni
- **Tablolar sütun sütun okunur:** Okuyucu veri tablolarını (en az iki sütun, kısa hücreler) her sütunu tek cümle olarak okur: "VENÜS: Ortalama Güneş Günü 22, Öğlen + 09." Eskiden hücreler satır satır ayrı ayrı okunuyor, değerler başlıklarından kopuyordu ve her hücre ayrı istek olduğu için küçük bir tablo bile bir dakikadan uzun sürüyordu. Okurken sütunun bütün hücreleri birlikte vurgulanır; boş hücreler sütun düzenini bozmaz. Uzun hücreli düzen tabloları (şiir, iki sütunlu metin) eskisi gibi okunur.

### Düzeltme
- **Yalnızca rakamdan oluşan parçalar okunmuyordu:** "M.S. 2301"de yıl, tablolardaki sayılar ve "1" gibi bölüm numaraları atlanıyordu; artık okunur. M.S., M.Ö., İ.S., İ.Ö. kısaltma olarak tanınır (cümle sonu sayılmaz).
- **Duygu etiketlerinde uç durumlar (F187; 11 Türkçe kitapla Gemma 4 26B, 4 kitapla Haiku denemesi):**
  - Tek tırnaklı iç diyalog (`‘Anne, uyumuyor musunuz?’ dedi.`) konuşma sayılır; arkasından harf gelen ’ (Olya’ya) kesme işaretidir.
  - Basım hatası `“Biliyor musunuz?..’` artık ’ ile kapanır; hiç kapanmayan tırnak en fazla altı cümle konuşma sayılır (bütün paragraf konuşma sanılıyordu).
  - Çizgili diyalogda anlatıcının sözleri yönergesiz: "— Olur, gidelim, dedi." "dedi"den önce `[sakin anlatıcı sesi]` alır; araya giren "–dedi Zosimov,–" ya da kısa "…, dedi, …" sonrasında konuşmanın ön eki yeniden konur.
  - Anlatıcıdan sonra gelen ikinci tırnak ("Her neyse," dedi Didactylos, "ben yaptım.") aynı konuşmacının ön ekini yeniden alır.
  - Önceki cümlede açılan alıntının düz tırnakla kapanan devamında kapanış tırnağı doğru tanınır; "–diye mırıldandı." gibi çizgiyle başlayan anlatıcı cümlesi konuşma sayılmaz; "diyerek" anlatıcı fiili olarak tanınır.
- Not: Tablolu bölümlerde hazırlanan sesler yeniden üretilir; yeni kurallar için kitapları yeniden etiketleyin.

## 2.19.4 — 2026-10-23

### Düzeltme
- **Dil modelinin yönergeleri çoğunlukla atılıyordu (F187):** Gemma 4 26B denemesinde model kitaptaki “ ” tırnaklarını JSON'da düz " olarak yazıyordu; sözlerin değişmediği denetimi bunu "söz değişti" sayıp iyi yanıtların neredeyse tamamını atıyordu (Yıkıma Giden Adam'ın iki bölümünde 311 konuşmadan 7'si etiketlendi). Artık tırnak ve kesme işaretleri karşılaştırılmaz, yönergeler kitabın kendi metnine yerleştirilir; aynı iki bölümde 350 konuşma etiketlendi.
- **Uzun alıntının tırnaksız cümleleri konuşma sayılmıyordu:** Okuyucu uzun bir alıntıyı cümlelere böldüğünde ortadaki cümleler tırnaksız kalıyordu; artık aynı paragrafta açılıp kapanmamış bir tırnağın içindeki cümle de konuşma sayılır.
- **Model her konuşmaya yerinde yönerge yazınca yanıt atılıyordu:** "Konuşmaların yarısından fazlası etiketlendiyse yanıtı at" koruması (küçük modelin her şeye `[laughs]` basmasına karşı) serbest kipte yalnızca yönergelerin yarısından fazlası aynıysa uygulanır.
- **Anlatıcının sözleri yönergesiz okunur:** Tırnaklı cümlede anlatıcının sözlerine konan yönerge (`[kendi kendine fısıldayarak] Ve araba yol alırken…`) atılır, tırnağın önündeki ve içindekiler kalır. Yönergeli sözden sonra anlatıcı devam ediyorsa tırnaktan sonra `[sakin anlatıcı sesi]` eklenir (dinleme denemesinde ön ek "diye haykırıyorlardı…" kısmına taşabiliyordu). İstem de bunu açıkça söyler ve model yalnızca yönerge eklediği cümleleri döndürür (yanıtlar kısaldı, istek başına ~12 sn'den ~8 sn'ye).
- **Kelime listesi serbest kipte modelin kararını yanlış etiketlerle eziyordu:** Model bir konuşmayı nötr bıraktığında kelime listesi seçili 73 etiketin denenmemiş ipuçlarıyla etiket koyuyordu ("Kahkahaları anında dondu" → `[laughs]`, `[interrupting]` …). Serbest kipte artık yalnızca çalıştığı bilinen beş etiketle doldurur; `[laughs]` ipucu da yalnızca "kahkahayla, kahkaha atarak…" gibi kalıplara bakar.
- Not: Yeni sürümle kitabı yeniden etiketleyin.

## 2.19.3 — 2026-10-23

### Düzeltme
- **Serbest yönergede modele etiket listesi verilmez (F187):** Serbest kipte dil modeline Ayarlar'da seçili etiketlerin tamamı (çoğu denenmemiş İngilizce etiket) "hazır etiket" olarak gidiyordu; bu, modeli dinlemede iyi sonuç veren Türkçe tariften uzaklaştırabiliyordu. Artık istemde yalnızca Türkçe örnekler ve resmi yedi çift etiket var. Kelime listesi ve "Yalnızca katalog" kipi seçili etiketleri eskisi gibi kullanır.

## 2.19.2 — 2026-10-23

### Düzeltme
- **"Duygu etiketleri oluştur" penceresi iki yöntemi karıştırıyordu (F187):** "Seçtiğiniz 73 etiket modele örnek olarak verilir" ile "Kelime listesi yalnızca bu etiketleri kullanır" aynı paragrafta geçtiği için serbest yönergenin listeyle sınırlı olduğu sanılıyordu. Artık her yöntemin açıklaması kendi seçeneğinin altında yazar: dil modeli konuşmaya kendi yönergesini yazar, listeyle sınırlı değildir; kelime listesi dil modeli kullanmaz, yalnızca seçili etiketleri koyar.

## 2.19.1 — 2026-10-23

### Düzeltme
- **"Duygu etiketleri oluştur" penceresi serbest yönergeyi anlatmıyordu (F187):** Ayarlarda "Serbest yönerge" seçiliyken de pencere seçili katalog etiketlerinin tamamını sıralayıp yalnızca bunların ekleneceğini söylüyordu. Artık serbest kipte modelin kendi yönergesini yazdığını ve seçili etiketlerin modele yalnızca örnek olarak verildiğini anlatır; serbest kipte hiç etiket seçili değilken model kipi de başlatılabilir.
- **Açılan ses motorunun ayarları hangi motora ait belli değildi:** Ayarlar → Ses'te bir motorun ayrıntıları açılınca ayarlar motor başlığının altında, girintili ve sol çizgili bir kutuda gösterilir; sonraki motor çizgiyle ayrılır.

## 2.19.0 — 2026-10-23

### Yeni
- **Duygu etiketlerinde serbest yönerge (F187):** Kitaplıkta sağ tık → "Duygu etiketleri oluştur" artık dil modelini katalogla sınırlamaz. Model, Drama 3'ün resmi yönerge sistemine göre konuşmanın yönergeli halini yazar: sözlerin önüne Türkçe ön ek (`[titrek bir sesle, ağlamamak için kendini zorlayarak]`), olayın olduğu yere ses ya da duraklama (`Peki [derin bir nefes alır] tamam`) ve yalnızca birkaç kelimeyi saran çift etiket (`<whisper>kimseye söylemeyeceğim</whisper>`; resmi yedi etiket). Model cümlenin bir kelimesini bile değiştirirse yanıt atılır ve kelime listesinin etiketi kalır. Ayarlar → Ses → Drama 3 TR'de "Model ile etiketleme biçimi" ile eski davranışa ("Yalnızca katalog") dönülebilir; seçtiğiniz etiketler serbest kipte modele örnek olarak verilir.
- **Drama 3 TR cümle ortasındaki etiketi izler (F187):** Budanmamış model etiketi cümle ortasında da izlediği için metin artık etiketlerden önce ayrı isteklere bölünmez.
- **Gruplu okumada ön ek taşmıyor (F187):** Dinleme denemesinde ön ek aynı istekteki sonraki cümlelere de geçiyordu. Artık ön ekli cümleden sonraki etiketsiz cümleye `[sakin anlatıcı sesi]` (konuşmaysa `[doğal ses]`) eklenir; denemede bu taşmayı kesti.
- Budanmış eski Drama 3 motoru serbest yönergeyi anlamadığı için ona yönergeden en yakın tek katalog etiketi gider (`[öfkeyle, dişlerini sıkarak]` → `[angry]`).
- Not: Yeni biçimi kullanmak için kitabı yeniden etiketleyin.

## 2.18.2 — 2026-10-23

### Düzeltme
- **"Hazırla" parça uzunluğuna göre gruplar (F186):** Drama 3 TR'de "Hazırla" her cümleyi ayrı istekle üretiyordu; her istek ~4 sn sabit süre eklediği için hazırlama çok uzuyordu. Artık okuyucuyla aynı grupları (paragraf sınırını aşmadan "Parça uzunluğu" kadar ardışık cümle) tek istekte üretir; deneme bölümünde 100 cümle 38 istekle hazırlandı. Okuyucu, "Hazır x/y" sayacı, bölüm kaydı ve sesli kitap aynı grupları kullanır, böylece hazırlanan ses hiçbir yerde yeniden üretilmez. Daha önce cümle cümle hazırlanmış sesler de bulunur ve tek başına okunur.
- **Grup okunurken sarı vurgu kayıyordu (F186):** Vurgu, grup içinde yalnızca karakter oranıyla ilerliyordu; uzun gruplarda konuşma hızı değiştikçe saniyelerce kayıyordu. Artık her cümle sınırı, sesin içindeki en yakın duraklamaya oturtulur.
- Not: "Parça uzunluğu" ses ayarlarından biri olduğundan değiştirildiğinde hazırlanan sesler yeniden üretilir.

## 2.18.1 — 2026-10-23

### Düzeltme
- **Hazırlanan sesler okurken kullanılmıyordu (F185):** Drama 3 TR gibi ardışık cümleleri tek istekte okuyan motorlarda okuyucu cümleleri grupluyor, "Hazırla" ise cümle cümle kaydediyordu; anahtarlar uyuşmadığı için hazırlanan sesler bulunmuyor, her şey yeniden üretiliyordu. Artık hazırlanmış cümle gruba alınmaz, önbellekten tek başına okunur; yalnızca hazırlanmamış cümleler gruplanır. Daha önce hazırladığınız sesler silinmedi, bu sürümle doğrudan kullanılır.

## 2.18.0 — 2026-10-22

### Yeni
- **Metinden seste mikrofon (F184):** Metin kutusunun altındaki "Mikrofon" düğmesiyle konuşun; konuşma yerelde Whisper ile metne çevrilip kutuya eklenir. Metin seçili sesle (kayıtlı ses, motor sesi ya da Ayarlardaki ses) okutulup WAV ya da MP3 olarak kayıt klasörüne yazılır. "Mikrofon kaydı bitince seçili sesle hemen seslendir" açıksa bu, kayıt biter bitmez kendiliğinden yapılır; kapalıyken metni düzeltip "Sese dönüştür"e basabilirsiniz. Bu düğme sohbetlerdeki mikrofon ayarından bağımsız olarak hep görünür.

## 2.17.1 — 2026-10-22

### Düzeltme
- **Bellekteki modeller paneli model sunucusunu boğuyordu (F183):** Panel açıkken liste yenilemesi kendini yeniden tetikliyor ve LM Studio'ya saniyede yüzlerce `/api/v1/models` isteği gidiyordu, program da kasıyordu. Liste artık panel açılınca yalnızca bir kez istenir; ayrıca arka uç bu sorguyu saniyede en fazla bir kez sunucuya iletir.

## 2.17.0 — 2026-10-22

### Yeni
- **Bellekteki modeller paneli (F183):** Sol alttaki "Model sunucusu" kutusuna tıklayınca ayrı sayfa açılmadan bir panel açılır. LM Studio'da o an bellekte (VRAM/RAM) yüklü modeller boyut, nicemleme ve bağlam uzunluğuyla listelenir ve her biri "Boşalt" ile bellekten çıkarılabilir (eject). Aktar'ın ısınmış ses motoru da (Python süreci ya da Aktar'ın başlattığı Drama 3 TR sunucusu, PID ile) burada görünür ve durdurulabilir; motoru kullanan bir iş sürerken boşaltma reddedilir. Sunucu sürekli sorgulanmaz: liste yalnızca panel açılınca (ve yenile düğmesiyle) bir kez istenir.

## 2.16.1 — 2026-10-22

### Düzeltme
- **Şarkılı seste "Seste konuşma bulunamadı" (F182):** Whisper'ın konuşma algılayıcısı şarkı ve koroyu konuşma saymadığı için müzik dosyalarından hiç metin çıkmıyordu. Konuşma bulunamazsa Whisper artık konuşma algılaması olmadan yeniden çalışır; müziğe uydurduğu kısa satırlar ("Thank you.", "We'll be right back.") ve güveni düşük satırlar ayıklanır, şarkı sözleri zamanlı altyazı olarak çıkar. Bu yeniden denemede ilerleme çubuğu baştan dolar.
- **Durum yazısı takılı kalıyordu:** Oynatıcıda sesten metin çıkarma başarısız olunca sağ paneldeki "Konuşmadan metin çıkarılıyor…" yazısı değişmiyordu; artık "Konuşmadan metin çıkarılamadı." gösterilir.

## 2.16.0 — 2026-10-22

### Yeni
- **Ses dosyaları (F181):** MP3, M4A, AAC, WAV, FLAC, OGG, Opus, WMA ve MKA dosyaları da videolar gibi açılır. Oynatıcıda Whisper ile zamanlı altyazı çıkarılabilir, altyazı dışa aktarılabilir, dublaj (doğrudan ya da düzenleyiciyle) yapılabilir ve soru sorulabilir; Altyazı Çevir sayfasında ses dosyasından altyazı oluşturulup çevrilebilir. Ses dosyasının dublajı ve klibi her zaman `.m4a` olarak yazılır. Ses dosyaları gömülü mpv yerine uygulamanın kendi oynatıcısında çalınır; kütüphaneye de eklenebilir (kare okuma atlanır).

## 2.15.0 — 2026-10-21

### Yeni
- **Kayıtlı sesler sekmesi ve sıralama (F180):** Metinden ses sayfasına "Kayıtlı sesler" sekmesi eklendi. Sesler burada eklenir, düzenlenir ve sürükle-bırak ya da oklarla sıralanır; okuyucudaki, dublajdaki ve Metinden ses'teki ses seçicileri bu sırayla gösterir. Son açılan sekme hatırlanır.
- **Ayarlar > Ses açılır/kapanır:** Whisper, Ses motorları, Okuma sesi ve Okuma ayarları bölümleri ile her ses motorunun ayrıntıları başlığa tıklanarak kapatılabilir; son durum hatırlanır. Arama sırasında bütün bölümler açık görünür. Drama 3 etiket listesi varsayılan olarak kapalıdır ve gruplara ayrılmıştır.
- **Daha fazla Drama 3 etiketi:** Duygu, ses yüksekliği ve konuşma biçimi, gülme/ağlama/nefes sesleri, duraklama ve vurgu gruplarında 48 yeni etiket ([sarcastic], [scared], [speaking slowly], [gasp], [pitch up]…). Hepsi "Denenmedi" olarak gelir ve varsayılan seçime girmez; anlatıcı ipucu olanlar kelime listesinde de bulunur.

### Düzeltme
- **Dublaj düzenleyicisinde özgün ses düzeyi etkisizdi:** Elle düzenlenen kısma aralıklarının hepsi silinince düzey kaydırıcısı ne önizlemede ne dışa aktarmada bir şey değiştiriyordu. Son aralık silinince artık otomatik kısmaya dönülür; böyle kalmış projeler de açılışta otomatik kısmaya geçer.

## 2.14.0 — 2026-10-21

### Yeni
- **Dublaj düzenleyicisinde arka plan konuşmasını bastırma (F179):** Proje sekmesine "Müziği ve efektleri koru" anahtarı eklendi. Açıkken dışa aktarmada videonun sesi konuşma ve müzik/efekt olarak ayrılır; kısma yalnızca özgün konuşmaya uygulanır. Düzey %0 yapılırsa özgün konuşma tamamen bastırılır, müzik ve efektler tam düzeyde kalır.

### Düzeltme
- **Dublaj kaydedilemiyordu:** Elle düzenlenen kısma aralıklarının hepsi silinince FFmpeg "No commands were specified" hatasıyla duruyordu.

## 2.13.0 — 2026-10-21

### Yeni
- **Metinden ses (F178):** Sol menüde yeni sayfa. Yazılan ya da yapıştırılan (veya .txt dosyası bırakılarak açılan) metin, seçilen kayıtlı sesle, bir motor sesiyle ya da Ayarlar'daki sesle okunur ve seçilen klasöre WAV ya da MP3 olarak yazılır. Hız, biçim, klasör ve ses seçimi hatırlanır; dosya adı boşsa metnin ilk kelimeleri kullanılır, aynı adda dosya varsa üzerine yazılmaz. Cümleler okuyucudaki gibi bölünür ve aradaki duraklamalar Ayarlar'daki duraklama ayarından gelir; Drama 3 TR'de aynı paragraftaki cümleler birleştirilerek okunur. Kayıt arka planda sürer (sağ üstteki işlerde görünür, durdurulabilir); bitince sayfada dinlenebilir.

## 2.12.0 — 2026-10-21

### Değişiklik
- **Drama 3 TR'de okuyucu cümleleri birleştirir (F177):** Bu motorda her istek, cümle ne kadar kısa olursa olsun ~4 saniyelik sabit bir süre ekliyor; okuyucu cümle cümle istediği için kısa cümlelerde ses metinden yavaş üretiliyordu. Artık okuyucu aynı paragraftaki ardışık cümleleri "Parça uzunluğu" ayarına kadar (varsayılan 200 karakter) tek istekte okutur, sonraki iki grubu önceden hazırlar. Vurgu çalan sesin içinde cümleden cümleye karakter oranına göre ilerler (duraklatınca durur); duygu etiketleri her cümlenin kendi yerinde kalır; ayarlanan cümle arası duraklama grubun sonuna konur. Diğer ses motorları eskisi gibi cümle cümle okur.

## 2.11.3 — 2026-10-21

### Düzeltme
- **Drama 3 TR Windows'ta "torch yükleniyor"da takılıyordu (F176):** 2.11.1'de sunucuya Aktar kapanınca kapanması için stdin borusunu izleyen bir iş parçacığı eklenmişti; Windows'ta bu okuma beklerken stdin'e bakan başka çağrılar (torch'un yüklenmesi) donuyordu. Windows'ta boru kullanılmaz (Aktar çökerse sunucuyu iş nesnesi kapatır); boru izleme yalnızca Linux'ta.

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
