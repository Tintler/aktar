"""Oyun cevirisi katmani (F194): oyunun ustunde duran ceviri kutulari, ekranda bolge secme ve genel
kisayollar.

Katman pencereleri (Windows):
  * WS_EX_LAYERED + WS_EX_TRANSPARENT: tiklamalar ve fare icinden oyuna gecer,
  * WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW: odak almaz, Alt+Tab'da ve gorev cubugunda gorunmez,
  * HWND_TOPMOST: pencereli tam ekran oyunun ustunde kalir,
  * WDA_EXCLUDEFROMCAPTURE: ekran yakalamaya girmez; Aktar kendi yazdigi Turkce metni tekrar okumaz.
Klavye, fare ve oyun kumandasi hic dinlenmez; yalnizca RegisterHotKey ile secilen kisayollar alinir.
Yazi Pillow ile cizilir ve UpdateLayeredWindow ile verilir (piksel basina saydamlik, GPU kullanilmaz).

Tum pencereler tek bir is parcaciginda, kendi Win32 ileti dongusuyle calisir; diger is parcaciklari isi
OverlayHost.call() ile birakir. stop() donguyu bitirir, kisayollari ve pencereleri birakir.
render/place/parse_hotkey saf fonksiyonlardir (her platformda test edilir).
"""
from __future__ import annotations

import os
import queue
import threading

WINDOWS = os.name == 'nt'

MODIFIERS = {'ctrl': 0x2, 'control': 0x2, 'alt': 0x1, 'shift': 0x4, 'win': 0x8}
_NAMED_KEYS = {
    'space': 0x20, 'enter': 0x0D, 'insert': 0x2D, 'delete': 0x2E, 'home': 0x24, 'end': 0x23,
    'pageup': 0x21, 'pagedown': 0x22, 'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'pause': 0x13, 'scrolllock': 0x91, 'backspace': 0x08, 'tab': 0x09,
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC, ';': 0xBA, "'": 0xDE,
    ',': 0xBC, '.': 0xBE, '/': 0xBF,
    'numpad+': 0x6B, 'numpad-': 0x6D, 'numpad*': 0x6A, 'numpad/': 0x6F,
}
# Degistirici tus olmadan kabul edilen tuslar: oyunda yazi yazmayi engellemesinler diye harfler kabul edilmez.
_ALONE = {0x13, 0x91} | set(range(0x70, 0x88))


def parse_hotkey(text):
    """'Ctrl+Alt+T' -> (degistiriciler, sanal tus kodu). Gecersizse ValueError."""
    parts = [part.strip() for part in str(text or '').replace(' ', '').split('+')]
    if not text or any(not part for part in parts):
        raise ValueError('Kısayol boş ya da eksik.')
    *mods, key = parts
    flags = 0
    for mod in mods:
        if mod.lower() not in MODIFIERS:
            raise ValueError(f'Bilinmeyen tuş: {mod}')
        flags |= MODIFIERS[mod.lower()]
    lowered = key.lower()
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif lowered in _NAMED_KEYS:
        vk = _NAMED_KEYS[lowered]
    elif lowered.startswith('numpad') and lowered[6:].isdigit() and len(lowered) == 7:
        vk = 0x60 + int(lowered[6:])
    elif lowered.startswith('f') and lowered[1:].isdigit() and 1 <= int(lowered[1:]) <= 24:
        vk = 0x6F + int(lowered[1:])
    else:
        raise ValueError(f'Bilinmeyen tuş: {key}')
    if not flags and vk not in _ALONE:
        raise ValueError('Kısayolda Ctrl, Alt, Shift ya da Win de olmalı (F1-F24 hariç).')
    return flags, vk


# ------------------------------------------------------------------ cizim (saf)
_FONT_FILES = {
    False: ('C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf'),
    True: ('C:/Windows/Fonts/segoeuib.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
           'DejaVuSans-Bold.ttf'),
}
_fonts = {}


def _font(size, bold=False):
    from PIL import ImageFont
    key = (size, bold)
    if key not in _fonts:
        font = None
        for path in _FONT_FILES[bold]:
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        _fonts[key] = font or ImageFont.load_default(size)
    return _fonts[key]


def _color(value, alpha=255):
    value = str(value or '#ffffff').lstrip('#')
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)
    except ValueError:
        return (255, 255, 255, alpha)


def wrap(text, font, width):
    """Yaziyi piksel genisligine gore satirlara boler (uzun kelime harf harf)."""
    lines = []
    for paragraph in str(text).split('\n'):
        current = ''
        for word in paragraph.split(' '):
            candidate = f'{current} {word}' if current else word
            if font.getlength(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = ''
            for char in word:
                if font.getlength(current + char) > width and current:
                    lines.append(current)
                    current = ''
                current += char
        lines.append(current)
    return lines


def render(text, width, style, speaker='', fit_height=None, pad=None, min_width=80):
    """Ceviri kutusu -> PIL RGBA. style: font_size, opacity, text_color, background, show_speaker.
    fit_height: 'kapsa' yerlesiminde kutu bu yukseklige sigsin diye yazi kuculur (en az 11 px).
    pad: kenar boslugu (varsayilan yazi boyunun yarisi)."""
    from PIL import Image, ImageDraw
    size = int(style.get('font_size', 22))
    width = max(min_width, int(width))
    fixed_pad = pad
    show_name = bool(speaker) and style.get('show_speaker', True)
    while True:
        pad = fixed_pad if fixed_pad is not None else max(8, size // 2)
        font, bold = _font(size), _font(max(10, int(size * 0.85)), True)
        spacing = int(size * 0.3)
        lines = wrap(text, font, width - 2 * pad)
        line_height = size + spacing
        name_height = int(size * 0.85) + spacing if show_name else 0
        height = 2 * pad + name_height + len(lines) * line_height - spacing
        if not fit_height or height <= fit_height or size <= 11:
            break
        size -= 1
    height = max(height, int(fit_height or 0))
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    alpha = round(255 * float(style.get('opacity', 0.85)))
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=max(4, size // 3),
                           fill=_color(style.get('background', '#101418'), alpha))
    color = _color(style.get('text_color', '#ffffff'))
    shadow = (0, 0, 0, 200)
    y = pad
    if show_name:
        draw.text((pad + 1, y + 1), speaker, font=bold, fill=shadow)
        draw.text((pad, y), speaker, font=bold, fill=(*color[:3], 190))
        y += name_height
    for line in lines:
        draw.text((pad + 1, y + 1), line, font=font, fill=shadow)
        draw.text((pad, y), line, font=font, fill=color)
        y += line_height
    return image


def place(region, placement, size, screen, target=None, gap=6):
    """Kutunun sol ust kosesi. region/target/screen: [x, y, w, h]; size: (genislik, yukseklik).
    Ust/alt yerlesim ekrandan tasarsa diger tarafa gecer; kutu ekranin icinde kalir."""
    rx, ry, rw, rh = region
    width, height = size
    sx, sy, sw, sh = screen
    if placement == 'custom' and target:
        x, y = target[0], target[1]
    elif placement == 'cover':
        x, y = rx, ry
    elif placement == 'above':
        x, y = rx, ry - height - gap
        if y < sy:
            y = ry + rh + gap
    else:
        x, y = rx, ry + rh + gap
        if y + height > sy + sh:
            y = ry - height - gap
    x = min(max(x, sx), sx + sw - width)
    y = min(max(y, sy), sy + sh - height)
    return int(x), int(y)


def render_block(text, box, line_height, style, screen=None):
    """Tarama kipi: ceviri, oyundaki yazinin tam ustune ve ayni boyda. (PIL RGBA, x, y) doner.
    Yazi boyu ozgun satir yuksekliginden; Turkce uzun gelirse kucultulur, tek satirlik kisa yazida kutu
    biraz genisleyebilir (ozgunun 1,8 katina kadar). Zemin ozgun yaziyi ortecek kadar opak."""
    x, y, width, height = box
    size = max(11, min(72, round(line_height)))
    pad = max(4, size // 3)
    style = dict(style, font_size=size, show_speaker=False,
                 opacity=max(0.96, float(style.get('opacity', 0.85))))
    inner = width
    if height < 1.8 * line_height:      # tek satir: cevirinin tamami sigsin diye genisleyebilir
        inner = min(max(width, _font(size).getlength(text) + 2), width * 1.8)
    image = render(text, inner + 2 * pad, style, fit_height=height + 2 * pad, pad=pad, min_width=1)
    x, y = x - pad, y - pad
    if screen:
        sx, sy, sw, sh = screen
        x = min(max(x, sx), sx + sw - image.width)
        y = min(max(y, sy), sy + sh - image.height)
    return image, int(x), int(y)


def box_width(region, placement, target=None):
    if placement == 'custom' and target:
        return target[2]
    return region[2]


# ------------------------------------------------------------------ Windows pencereleri
if WINDOWS:
    import ctypes
    from ctypes import wintypes

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                    ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                    ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [('hdc', wintypes.HDC), ('fErase', wintypes.BOOL), ('rcPaint', wintypes.RECT),
                    ('fRestore', wintypes.BOOL), ('fIncUpdate', wintypes.BOOL), ('rgbReserved', ctypes.c_byte * 32)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [('BlendOp', ctypes.c_byte), ('BlendFlags', ctypes.c_byte), ('SourceConstantAlpha', ctypes.c_ubyte),
                    ('AlphaFormat', ctypes.c_byte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                           ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                           wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_byte, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                    wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.BeginPaint.restype = wintypes.HDC
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.FrameRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT),
                                 wintypes.UINT]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.SetCapture.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetFocus.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                       wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.BitBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                                                  wintypes.DWORD]
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    WS_POPUP = 0x80000000
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST = 0x80000, 0x20, 0x8
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
    WDA_EXCLUDEFROMCAPTURE = 0x11
    HWND_TOPMOST = wintypes.HWND(-1)
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
    SW_HIDE, SW_SHOW, SW_SHOWNOACTIVATE = 0, 5, 4
    WM_DESTROY, WM_PAINT, WM_ERASEBKGND, WM_SETCURSOR, WM_KEYDOWN = 0x2, 0xF, 0x14, 0x20, 0x100
    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x200, 0x201, 0x202, 0x205
    WM_HOTKEY, WM_APP, WM_QUIT = 0x312, 0x8000, 0x12
    MOD_NOREPEAT = 0x4000
    LWA_COLORKEY, LWA_ALPHA = 0x1, 0x2
    VK_ESCAPE = 0x1B
    KEY_COLOR = 0x00FF00FF           # secim dikdortgeninin ici: tamamen saydam (oyun net gorunur)
    DT_CENTER, DT_WORDBREAK = 0x1, 0x10
    IDC_CROSS = 32515


def _signed(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _dib(image):
    """PIL goruntu -> GDI bitmap (32 bit, ust-alt). Cagiran DeleteObject ile birakir."""
    width, height = image.size
    data = image.convert('RGBA').tobytes('raw', 'BGRA')
    header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        raise OSError('Ekran görüntüsü hazırlanamadı.')
    ctypes.memmove(bits, data, len(data))
    return bitmap


class OverlayHost:
    """Katman pencereleri, bolge secici ve kisayollar icin tek Win32 is parcacigi.

    show(anahtar, PIL RGBA, x, y) / hide(anahtar) / set_visible(bool) / select(geri cagirma, ipucu) /
    set_hotkeys({eylem: 'Ctrl+Alt+T'}) -> hatalar. on_hotkey(eylem) is parcaciginda cagrilir, kisa tutulmali."""

    CLASS = 'AktarOyunKatmani'

    def __init__(self, on_hotkey=None, log=print):
        if not WINDOWS:
            raise RuntimeError('Oyun çevirisi katmanı yalnızca Windows\'ta çalışır.')
        self.on_hotkey = on_hotkey or (lambda _action: None)
        self.log = log
        self.capture_safe = True     # WDA_EXCLUDEFROMCAPTURE kabul edildi mi
        self._queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = None
        self._tid = 0
        self._windows = {}           # anahtar -> hwnd
        self._shown = {}             # anahtar -> (resim, x, y): gizle/goster icin son icerik
        self._visible = True
        self._hotkeys = {}           # kimlik -> eylem
        self._selector = None
        self._proc = WNDPROC(self._wndproc)   # referans tutulmali: yoksa geri cagirma silinir

    # -------------------------------------------------------------- dongu
    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._run, name='aktar-game-overlay', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError('Oyun katmanı başlatılamadı.')
        return self

    def alive(self):
        return bool(self._thread and self._thread.is_alive())

    def stop(self):
        if self.alive():
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(3)

    def call(self, fn, wait=False):
        """fn katman is parcaciginda calisir; wait=True ise sonucu doner."""
        if not self.alive():
            return None
        done = threading.Event() if wait else None
        box = []

        def run():
            try:
                box.append(fn())
            finally:
                if done:
                    done.set()
        self._queue.put(run)
        user32.PostThreadMessageW(self._tid, WM_APP, 0, 0)
        if done and threading.current_thread() is not self._thread:
            done.wait(5)
        return box[0] if box else None

    def _run(self):
        try:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        self._tid = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)   # ileti kuyrugu olussun
        self._instance = kernel32.GetModuleHandleW(None)
        cls = WNDCLASSEXW(ctypes.sizeof(WNDCLASSEXW), 0, self._proc, 0, 0, self._instance, None,
                          user32.LoadCursorW(None, ctypes.c_void_p(IDC_CROSS)), None, None, self.CLASS, None)
        user32.RegisterClassExW(ctypes.byref(cls))   # ikinci kez basarisiz olur (zaten kayitli); sorun degil
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    action = self._hotkeys.get(int(message.wParam))
                    if action:
                        try:
                            self.on_hotkey(action)
                        except Exception as error:  # kisayol isleyicisi donguyu durdurmasin
                            self.log(f'Oyun çevirisi kısayolu hatası: {error}')
                    continue
                if message.message == WM_APP and not message.hWnd:
                    self._drain()
                    continue
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._unregister()
            for hwnd in list(self._windows.values()):
                user32.DestroyWindow(hwnd)
            self._windows.clear()
            if self._selector:
                user32.DestroyWindow(self._selector['hwnd'])
                self._selector = None

    def _drain(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as error:  # bir cizim hatasi katmani durdurmasin
                self.log(f'Oyun çevirisi katmanı hatası: {error}')

    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            selector = self._selector
            if selector and hwnd == selector['hwnd']:
                handled = self._selector_message(selector, message, wparam, lparam)
                if handled is not None:
                    return handled
        except Exception as error:
            self.log(f'Bölge seçici hatası: {error}')
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    # -------------------------------------------------------------- ceviri kutulari
    def show(self, key, image, x, y):
        self.call(lambda: self._show(key, image, x, y))

    def hide(self, key):
        self.call(lambda: self._hide(key))

    def hide_all(self):
        self.call(lambda: [self._hide(key) for key in list(self._shown)])

    def set_visible(self, visible):
        def apply():
            self._visible = bool(visible)
            for key, (image, x, y) in list(self._shown.items()):
                if self._visible:
                    self._blit(self._window(key), image, x, y)
                else:
                    user32.ShowWindow(self._windows[key], SW_HIDE)
        self.call(apply)

    def shown_rects(self):
        return self.call(lambda: [(x, y, image.width, image.height) for image, x, y in self._shown.values()],
                         wait=True) or []

    def _window(self, key):
        hwnd = self._windows.get(key)
        if hwnd:
            return hwnd
        style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = user32.CreateWindowExW(style, self.CLASS, 'Aktar oyun çevirisi', WS_POPUP, 0, 0, 1, 1,
                                      None, None, self._instance, None)
        if not hwnd:
            raise OSError('Katman penceresi açılamadı.')
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            if self.capture_safe:
                self.log('UYARI: Windows katmanı ekran yakalamadan dışlayamadı (Windows 10 2004 ve sonrası gerekir); '
                         'çeviri kutusu okunan bölgenin üstündeyse Aktar onu yakalarken kısa süre gizler.')
            self.capture_safe = False
        self._windows[key] = hwnd
        return hwnd

    def _show(self, key, image, x, y):
        self._shown[key] = (image, x, y)
        if self._visible:
            self._blit(self._window(key), image, x, y)

    def _hide(self, key):
        self._shown.pop(key, None)
        hwnd = self._windows.get(key)
        if hwnd:
            user32.ShowWindow(hwnd, SW_HIDE)

    def _blit(self, hwnd, image, x, y):
        """RGBA goruntuyu (on carpilmis BGRA) katman penceresine verir ve en uste alir; odak almaz."""
        from PIL import Image
        width, height = image.size
        red, green, blue, alpha = image.convert('RGBa').split()
        data = Image.merge('RGBA', (blue, green, red, alpha)).tobytes()
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(memory, bitmap)
            blend = BLENDFUNCTION(0, 0, 255, 1)
            user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
                                       ctypes.byref(wintypes.SIZE(width, height)), memory,
                                       ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)
            gdi32.SelectObject(memory, old)
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    # -------------------------------------------------------------- kisayollar
    def set_hotkeys(self, combos):
        """{eylem: 'Ctrl+Alt+T'} kaydeder; donen {eylem: hata} (bos kisayol atlanir)."""
        def apply():
            self._unregister()
            errors = {}
            for number, (action, combo) in enumerate(sorted(combos.items()), 1):
                if not combo:
                    continue
                try:
                    mods, vk = parse_hotkey(combo)
                except ValueError as error:
                    errors[action] = str(error)
                    continue
                if not user32.RegisterHotKey(None, number, mods | MOD_NOREPEAT, vk):
                    errors[action] = f'{combo} başka bir program tarafından kullanılıyor.'
                    continue
                self._hotkeys[number] = action
            return errors
        return self.call(apply, wait=True) or {}

    def _unregister(self):
        for number in list(self._hotkeys):
            user32.UnregisterHotKey(None, number)
        self._hotkeys.clear()

    # -------------------------------------------------------------- bolge secici
    def select(self, callback, hint='', frozen=None):
        """Tum ekranlari karartan pencerede surukleyerek dikdortgen sectirir. callback([x, y, w, h] | None).
        frozen: secimden hemen once yakalanan sanal ekran goruntusu (PIL); verilirse secim bu donmus kare
        uzerinde yapilir (oyundaki yazi secerken kaybolmaz, onizleme tam olarak gorulen alandan kesilir)."""
        self.call(lambda: self._open_selector(callback, hint, frozen))

    def _open_selector(self, callback, hint, frozen=None):
        if self._selector:
            self._close_selector(None)
        metric = user32.GetSystemMetrics
        bounds = [metric(76), metric(77), metric(78), metric(79)]
        bitmaps = None
        if frozen is not None and frozen.size == tuple(bounds[2:]):
            from PIL import ImageEnhance
            bitmaps = (_dib(frozen), _dib(ImageEnhance.Brightness(frozen).enhance(0.45)))
        # Donmus kare varsa pencere opaktir (kendi resmini cizer); yoksa yari saydam karartma + renk anahtari.
        style = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | (0 if bitmaps else WS_EX_LAYERED)
        hwnd = user32.CreateWindowExW(style, self.CLASS, 'Aktar bölge seçimi', WS_POPUP, *bounds, None, None,
                                      self._instance, None)
        if not hwnd:
            for handle in bitmaps or ():
                gdi32.DeleteObject(handle)
            callback(None)
            return
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        if not bitmaps:
            user32.SetLayeredWindowAttributes(hwnd, KEY_COLOR, 120, LWA_COLORKEY | LWA_ALPHA)
        self._selector = {'hwnd': hwnd, 'bounds': bounds, 'start': None, 'end': None, 'callback': callback,
                          'bitmaps': bitmaps,
                          'hint': hint or 'Okunacak bölgeyi fareyle sürükleyerek seçin · Esc ya da sağ tık: vazgeç'}
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)

    def _close_selector(self, rect):
        selector, self._selector = self._selector, None
        if not selector:
            return
        user32.ReleaseCapture()
        user32.DestroyWindow(selector['hwnd'])
        for handle in selector.get('bitmaps') or ():
            gdi32.DeleteObject(handle)
        try:
            selector['callback'](rect)
        except Exception as error:
            self.log(f'Bölge seçimi işlenemedi: {error}')

    def _selection(self, selector):
        if not selector['start'] or not selector['end']:
            return None
        (x1, y1), (x2, y2) = selector['start'], selector['end']
        return [min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)]

    def _selector_message(self, selector, message, wparam, lparam):
        point = (_signed(lparam), _signed(lparam >> 16))
        if message == WM_SETCURSOR:
            user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(IDC_CROSS)))
            return 1
        if message == WM_LBUTTONDOWN:
            selector['start'] = selector['end'] = point
            user32.SetCapture(selector['hwnd'])
            return 0
        if message == WM_MOUSEMOVE and selector['start']:
            selector['end'] = point
            user32.InvalidateRect(selector['hwnd'], None, False)
            return 0
        if message == WM_LBUTTONUP and selector['start']:
            selector['end'] = point
            rect = self._selection(selector)
            if rect and rect[2] >= 8 and rect[3] >= 8:
                left, top = selector['bounds'][:2]
                self._close_selector([rect[0] + left, rect[1] + top, rect[2], rect[3]])
            else:
                selector['start'] = selector['end'] = None
                user32.ReleaseCapture()
                user32.InvalidateRect(selector['hwnd'], None, False)
            return 0
        if message == WM_RBUTTONUP or (message == WM_KEYDOWN and wparam == VK_ESCAPE):
            self._close_selector(None)
            return 0
        if message == WM_ERASEBKGND:
            return 1
        if message == WM_PAINT:
            self._paint_selector(selector)
            return 0
        return None

    def _paint_selector(self, selector):
        paint = PAINTSTRUCT()
        hdc = user32.BeginPaint(selector['hwnd'], ctypes.byref(paint))
        width, height = selector['bounds'][2:]
        memory = gdi32.CreateCompatibleDC(hdc)
        bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
        old = gdi32.SelectObject(memory, bitmap)
        dark, clear, white = gdi32.CreateSolidBrush(0x00101010), gdi32.CreateSolidBrush(KEY_COLOR), \
            gdi32.CreateSolidBrush(0x00FFFFFF)
        font = gdi32.CreateFontW(-30, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, 'Segoe UI')
        bitmaps = selector.get('bitmaps')
        source = gdi32.CreateCompatibleDC(hdc) if bitmaps else None
        try:
            if bitmaps:
                previous = gdi32.SelectObject(source, bitmaps[1])
                gdi32.BitBlt(memory, 0, 0, width, height, source, 0, 0, 0x00CC0020)
                gdi32.SelectObject(source, previous)
            else:
                user32.FillRect(memory, ctypes.byref(wintypes.RECT(0, 0, width, height)), dark)
            gdi32.SetBkMode(memory, 1)
            gdi32.SetTextColor(memory, 0x00FFFFFF)
            old_font = gdi32.SelectObject(memory, font)
            # ipucu birincil ekranin ust ortasinda (sanal ekranin sol ustu negatif olabilir)
            left, top = -selector['bounds'][0], -selector['bounds'][1]
            text_rect = wintypes.RECT(left, top + 40, left + user32.GetSystemMetrics(0), top + 200)
            user32.DrawTextW(memory, selector['hint'], -1, ctypes.byref(text_rect), DT_CENTER | DT_WORDBREAK)
            gdi32.SelectObject(memory, old_font)
            rect = self._selection(selector)
            if rect and rect[2] > 0 and rect[3] > 0:
                box = wintypes.RECT(rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])
                if bitmaps:     # secilen alan donmus karede parlak (karartmasiz) gorunur
                    previous = gdi32.SelectObject(source, bitmaps[0])
                    gdi32.BitBlt(memory, rect[0], rect[1], rect[2], rect[3], source, rect[0], rect[1], 0x00CC0020)
                    gdi32.SelectObject(source, previous)
                else:
                    user32.FillRect(memory, ctypes.byref(box), clear)
                for inset in (0, 1):
                    edge = wintypes.RECT(box.left - inset - 1, box.top - inset - 1, box.right + inset + 1,
                                         box.bottom + inset + 1)
                    user32.FrameRect(memory, ctypes.byref(edge), white)
            gdi32.BitBlt(hdc, 0, 0, width, height, memory, 0, 0, 0x00CC0020)
        finally:
            gdi32.SelectObject(memory, old)
            for handle in (bitmap, dark, clear, white, font):
                gdi32.DeleteObject(handle)
            gdi32.DeleteDC(memory)
            if source:
                gdi32.DeleteDC(source)
            user32.EndPaint(selector['hwnd'], ctypes.byref(paint))
