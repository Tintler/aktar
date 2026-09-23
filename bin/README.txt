Bu klasore tasinabilir FFmpeg ikililerini koyun:

    bin\ffmpeg.exe
    bin\ffprobe.exe

Aktar, bu ikilileri uygulamayla birlikte tasir; kullanicinin sistemine ayrica
FFmpeg kurmasi gerekmez. Uygulama once bu klasore, sonra PyInstaller'in actigi
gecici _MEIPASS klasorune bakar (paketlenmis .exe icin).

Indirme (Windows, "essentials" veya "full" build):
    https://www.gyan.dev/ffmpeg/builds/
veya
    https://github.com/BtbN/FFmpeg-Builds/releases

Arsivden cikan ffmpeg.exe ve ffprobe.exe dosyalarini bu klasore kopyalayin.
