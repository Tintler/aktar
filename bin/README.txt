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

Linux: ffmpeg/ffprobe'u sistemden kurmaniz yeterlidir (sudo apt install ffmpeg);
bu klasordeki .exe dosyalari Linux'ta yok sayilir. Tasinabilir Linux ikilileri
kullanmak isterseniz (or. https://johnvansickle.com/ffmpeg/) calistirilabilir
olarak bin/ffmpeg ve bin/ffprobe adlariyla koyun; ./derle.sh bunlari pakete gomer.

Gomulu oynatici (Windows, istege bagli): libmpv-2.dll
    https://github.com/shinchiro/mpv-winbuild-cmake/releases
    mpv-dev-x86_64-<tarih>-git-<surum>.7z arsivindeki libmpv-2.dll dosyasini bu klasore
    koyun (py -3 -m pip install python-mpv de gerekir). DERLE.cmd onu .exe'ye gommez,
    dist\bin\ icine kopyalar: Aktar.exe'nin yanindaki bin\ klasorunde durmalidir.
    Yoksa oynatici WebView ile calisir.
