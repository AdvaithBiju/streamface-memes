"""Face detection + cartoony cutout.

Pipeline: decode image -> find the largest face (MediaPipe, OpenCV Haar as
fallback) -> expand the box to include hair/chin -> oval mask with feathered
edges -> transparent PNG.
"""
from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
# Backup detector. OpenCV 5 no longer ships its Haar cascade files, so fetch it like the model above.
HAAR_URL = ("https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades/"
            "haarcascade_frontalface_default.xml")
MAX_CUTOUT_SIZE = 512  # longest side of the saved PNG


class FaceError(ValueError):
    """Raised when an image can't be turned into a face cutout."""


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int


class FaceDetector:
    def __init__(self, model_path: Path):
        self.model_path = model_path
        self._mp_detector = None
        self._haar = None
        self.backend = "none"
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            if not self.model_path.exists():
                self.model_path.parent.mkdir(parents=True, exist_ok=True)
                log.info("Downloading MediaPipe face model -> %s", self.model_path)
                urllib.request.urlretrieve(MODEL_URL, self.model_path)

            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision

            options = vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                min_detection_confidence=0.5,
            )
            self._mp_detector = vision.FaceDetector.create_from_options(options)
            self._mp = mp
            self.backend = "mediapipe"
        except Exception as exc:  # missing wheel or system library, offline, etc.
            log.warning("MediaPipe unavailable (%s); using OpenCV Haar cascade", exc)
            self._init_haar()

    def _init_haar(self) -> None:
        path = self.model_path.parent / "haarcascade_frontalface_default.xml"
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(HAAR_URL, path)
            haar = cv2.CascadeClassifier(str(path))
            if haar.empty():
                raise ValueError(f"couldn't load {path}")
        except Exception as exc:
            log.error("No face detector available: %s", exc)
            return
        self._haar = haar
        self.backend = "opencv-haar"

    def detect(self, bgr: np.ndarray) -> Box | None:
        """Return the largest face in the image, or None."""
        boxes = self.detect_all(bgr)
        return boxes[0] if boxes else None

    def detect_all(self, bgr: np.ndarray) -> list[Box]:
        """Every face in the image, largest first."""
        if self._mp_detector is not None:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            boxes = self._mp_boxes(rgb, 0, 0)
            # The model squeezes the photo into a small square, so faces in a wide
            # screenshot or group shot get too small to find. Also look at overlapping
            # square tiles, full height and half height.
            h, w = rgb.shape[:2]
            for side in (min(h, w), min(h, w) // 2):
                if side < 160:
                    break
                step = side // 2
                for y in _offsets(h, side, step):
                    for x in _offsets(w, side, step):
                        tile = np.ascontiguousarray(rgb[y:y + side, x:x + side])
                        boxes += self._mp_boxes(tile, x, y)
            boxes = _dedupe(boxes)
        elif self._haar is not None:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            found = self._haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                                minSize=(60, 60))
            boxes = [Box(int(x), int(y), int(w), int(h)) for x, y, w, h in found]
        else:
            raise FaceError("Face detection isn't working on the server right now. Please tell the streamer.")

        return sorted(boxes, key=lambda b: b.w * b.h, reverse=True)

    def _mp_boxes(self, rgb: np.ndarray, dx: int, dy: int) -> list[Box]:
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        return [Box(d.bounding_box.origin_x + dx, d.bounding_box.origin_y + dy,
                    d.bounding_box.width, d.bounding_box.height)
                for d in self._mp_detector.detect(image).detections]


def _offsets(length: int, side: int, step: int) -> list[int]:
    """Tile start positions covering 0..length, the last one flush with the end."""
    starts = list(range(0, max(1, length - side + 1), step))
    if starts[-1] + side < length:
        starts.append(length - side)
    return starts


def _dedupe(boxes: list[Box]) -> list[Box]:
    """The same face found twice (whole photo + a tile): keep the bigger box."""
    def overlap(a: Box, b: Box) -> float:
        ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
        iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
        return ix * iy / min(a.w * a.h, b.w * b.h)

    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: b.w * b.h, reverse=True):
        if all(overlap(box, k) < 0.4 for k in kept):
            kept.append(box)
    return kept


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError("That file isn't a readable image.")
    # Keep processing fast on huge phone photos.
    h, w = img.shape[:2]
    scale = 1600 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def make_cutout(bgr: np.ndarray, box: Box) -> np.ndarray:
    """Crop around the face and apply a soft oval mask. Returns BGRA."""
    img_h, img_w = bgr.shape[:2]

    # Detector boxes are tight around eyes/mouth; grow them to include
    # forehead, hair and chin so the paste looks like a "head".
    cx = box.x + box.w / 2
    cy = box.y + box.h / 2 - box.h * 0.12
    crop_w = box.w * 1.45
    crop_h = box.h * 1.85

    x0 = int(max(0, cx - crop_w / 2))
    y0 = int(max(0, cy - crop_h / 2))
    x1 = int(min(img_w, cx + crop_w / 2))
    y1 = int(min(img_h, cy + crop_h / 2))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        raise FaceError("Face is too close to the edge of the photo.")

    h, w = crop.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    feather = max(3, int(min(w, h) * 0.06))
    cv2.ellipse(mask, (w // 2, h // 2),
                (max(1, w // 2 - feather), max(1, h // 2 - feather)),
                0, 0, 360, 255, thickness=-1)
    k = feather * 2 + 1
    mask = cv2.GaussianBlur(mask, (k, k), 0)

    bgra = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = mask

    scale = MAX_CUTOUT_SIZE / max(h, w)
    if scale < 1:
        bgra = cv2.resize(bgra, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return bgra


def process_photo(detector: FaceDetector, data: bytes, out_path: Path, max_faces: int = 1) -> list[Path]:
    """Full pipeline: raw upload bytes -> transparent PNG at out_path.

    With max_faces > 1, a group shot gives one cutout per person (largest
    first): out_path, then <name>-2.png, <name>-3.png, ... Returns the paths written.
    """
    bgr = decode_image(data)
    boxes = detector.detect_all(bgr)
    if not boxes:
        raise FaceError("No face found. Try a well-lit, front-facing photo.")
    if boxes[0].w < 40 or boxes[0].h < 40:
        raise FaceError("Face is too small. Try a closer photo.")
    # Skip tiny faces in the background: usually posters, crowds or false hits.
    keep = [b for b in boxes if b.w >= 40 and b.w >= boxes[0].w * 0.3][:max(1, max_faces)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, box in enumerate(keep):
        path = out_path if i == 0 else out_path.with_name(f"{out_path.stem}-{i + 1}{out_path.suffix}")
        try:
            cutout = make_cutout(bgr, box)
        except FaceError:
            if i == 0:
                raise
            continue
        if not cv2.imwrite(str(path), cutout):
            raise FaceError("Couldn't save the cutout.")
        paths.append(path)
    return paths
