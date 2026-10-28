"""Gazete (F225): telefon kamerasinin karesini sayinin sayfalariyla eslestirir.

Telefon basili sayfanin bir bolumunu (bulanik, egik, karanlik olabilir) gosterir; yazinin okunmasi
gerekmez. Sayfa goruntulerinden SIFT ozellikleri bir kez cikarilir, karenin ozellikleri hepsiyle
eslestirilir (Lowe orani), en cok eslesen sayfada RANSAC ile homografi kurulur ve karenin merkezinin
sayfadaki yeri bulunur. 20 sayfalik ornek sayida benzetilmis 100 telefon karesinin (egik, bulanik,
karanlik) 98'i dogru sayfada bulundu, yanlis sayfa yok; kare basina ~90 ms.

OpenCV (opencv-python-headless) gerekir; yoksa ImportError anlasilir bir iletiyle yukselir.
"""
from __future__ import annotations

import threading

REFERENCE_LONG_SIDE = 2000   # sayfa ozellikleri bu boyda cikarilir
PAGE_FEATURES = 12000        # 20 sayfada ~120 MB; azaltinca kucuk kadrajlar bulunamiyor
FRAME_LONG_SIDE = 800
FRAME_FEATURES = 3000
RATIO = 0.8
MIN_MATCHES = 12
MIN_INLIERS = 20             # 15'te benzer sayfa duzeninde yanlis sayfa bulunabiliyordu
RANSAC_PIXELS = 6.0


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ImportError("Sayfa eşleştirme için OpenCV gerekir: py -3 -m pip install opencv-python-headless") from error
    return cv2, np


def _gray(image, long_side):
    """Pillow ya da OpenCV goruntusunden gri, en fazla long_side boyunda; (gri, olcek)."""
    cv2, np = _cv()
    if not isinstance(image, np.ndarray):
        image = np.asarray(image.convert('L'))
    elif image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, long_side / max(image.shape[:2]))
    if scale < 1.0:
        image = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)),
                           interpolation=cv2.INTER_AREA)
    return image, scale


def decode(data):
    """JPEG/PNG baytlari -> OpenCV goruntusu (cozulemezse ValueError)."""
    cv2, np = _cv()
    try:
        image = cv2.imdecode(np.frombuffer(data or b'', np.uint8), cv2.IMREAD_COLOR) if data else None
    except cv2.error:
        image = None
    if image is None:
        raise ValueError('Görüntü çözülemedi.')
    return image


class PageIndex:
    """Bir sayinin sayfalari icin eslestirme dizini. pages: [(sayfa no, Pillow goruntusu)]."""

    def __init__(self, pages):
        cv2, np = _cv()
        self._sift = cv2.SIFT_create(nfeatures=PAGE_FEATURES)
        self._frame_sift = cv2.SIFT_create(nfeatures=FRAME_FEATURES)
        self._lock = threading.Lock()   # SIFT/FLANN nesneleri is parcacigi guvenli degil
        self.pages = []
        points, owners, descriptors = [], [], []
        for number, image in pages:
            gray, scale = _gray(image, REFERENCE_LONG_SIDE)
            keypoints, found = self._sift.detectAndCompute(gray, None)
            if found is None:
                continue
            slot = len(self.pages)
            self.pages.append({'page': number, 'scale': scale})
            points.append(np.float32([kp.pt for kp in keypoints]) / scale)   # sayfa goruntusu pikseli
            owners.append(np.full(len(keypoints), slot, np.int32))
            descriptors.append(found)
        if not descriptors:
            raise ValueError('Sayfalarda eşleştirilecek ayrıntı bulunamadı.')
        self._points = np.concatenate(points)
        self._owners = np.concatenate(owners)
        self._matcher = cv2.FlannBasedMatcher({'algorithm': 1, 'trees': 5}, {'checks': 64})
        self._matcher.add([np.concatenate(descriptors)])
        self._matcher.train()

    def locate(self, frame, point=(0.5, 0.5)):
        """Karenin `point` (0-1 oraninda) noktasinin sayfadaki yeri: {page, x, y, inliers} ya da None."""
        cv2, np = _cv()
        gray, _scale = _gray(frame, FRAME_LONG_SIDE)
        with self._lock:
            keypoints, found = self._frame_sift.detectAndCompute(gray, None)
            if found is None or len(keypoints) < MIN_MATCHES:
                return None
            pairs = self._matcher.knnMatch(found, k=2)
        good = [first for first, second in (pair for pair in pairs if len(pair) == 2)
                if first.distance < RATIO * second.distance]
        if len(good) < MIN_MATCHES:
            return None
        votes = np.bincount(self._owners[[m.trainIdx for m in good]], minlength=len(self.pages))
        slot = int(votes.argmax())
        chosen = [m for m in good if self._owners[m.trainIdx] == slot]
        if len(chosen) < MIN_MATCHES:
            return None
        source = np.float32([keypoints[m.queryIdx].pt for m in chosen])
        target = self._points[[m.trainIdx for m in chosen]]
        page = self.pages[slot]
        homography, mask = cv2.findHomography(source, target, cv2.RANSAC, RANSAC_PIXELS / page['scale'])
        if homography is None:
            return None
        inliers = int(mask.sum())
        if inliers < MIN_INLIERS:
            return None
        height, width = gray.shape
        spot = np.float32([[[point[0] * width, point[1] * height]]])
        x, y = cv2.perspectiveTransform(spot, homography)[0, 0]
        return {'page': page['page'], 'x': float(x), 'y': float(y), 'inliers': inliers}


def load_index(name):
    """Kayitli sayinin dizini (sayfa goruntulerinden)."""
    from PIL import Image
    import gazete
    data = gazete.load(name)
    pages = []
    for info in data.get('pages', []):
        with Image.open(gazete.page_path(name, info['page'])) as opened:
            pages.append((info['page'], opened.convert('L')))
    return PageIndex(pages)
