import pytest
from PIL import Image

from app.filters import CaptionError, clean_caption
from app.meme import MemeError, fit_text, layers_from_template, load_font, parse_layers, render_meme, wrap_text
from app.pipeline import _split_caption


@pytest.mark.parametrize("text", ["homework vs gaming", "can't lose | if you never play", "100% real (trust me)"])
def test_clean_caption_accepts_normal_text(text):
    assert clean_caption(text, 80) == text


def test_clean_caption_collapses_whitespace():
    assert clean_caption("  so   much\n space ", 80) == "so much space"


@pytest.mark.parametrize("text, reason", [
    ("x" * 81, "too long"),
    ("visit www.spam-site.com", "links"),
    ("go to https://example.org", "links"),
    ("hi @someone", "@mentions"),
    ("you are a b1tch", "language filter"),
])
def test_clean_caption_refuses(text, reason):
    with pytest.raises(CaptionError, match=reason):
        clean_caption(text, 80)


@pytest.mark.parametrize("caption, slots, expected", [
    ("", 2, None),
    ("homework vs gaming", 2, ["homework", "gaming"]),
    ("a | b | c", 2, ["a", "b c"]),
    ("only one", 3, ["only one", "", ""]),
    ("no split here", 1, ["no split here"]),
])
def test_split_caption(caption, slots, expected):
    assert _split_caption(caption, slots) == expected


def test_wrap_and_fit_text():
    font = load_font(40)
    lines = wrap_text("the quick brown fox jumps over the lazy dog", font, 200)
    assert len(lines) > 1 and all(font.getlength(line) <= 200 or " " not in line for line in lines)
    _, size, lines = fit_text("A VERY LONG CAPTION THAT NEEDS TO SHRINK QUITE A LOT", 150, 60, 60)
    assert size < 60 and len(lines) * size * 1.1 <= 60 or size == 10


def test_parse_layers_validates():
    with pytest.raises(MemeError):
        parse_layers([{"type": "text", "color": "red"}], 400, 300)
    with pytest.raises(MemeError):
        parse_layers([{"type": "sticker"}], 400, 300)
    with pytest.raises(MemeError):
        parse_layers([{"type": "face"}], 400, 300)
    layers = parse_layers([{"type": "text", "text": "x" * 500, "x": -99999, "width": 1e9}], 400, 300)
    assert len(layers[0]["text"]) == 200 and layers[0]["x"] >= -400 and layers[0]["width"] <= 1200


def test_render_meme_pastes_face_and_resizes(app, tmp_path):
    store = app.extensions["template_store"]
    template = store.get("testmeme")
    layers = layers_from_template(template, 1, ["hello", "world"])
    image = render_meme(store.image_path(template), layers, {1: app.config["FACES_DIR"] / "face.png"}, out_width=200)
    assert image.size == (200, 150)
    big = render_meme(store.image_path(template), layers, {1: app.config["FACES_DIR"] / "face.png"})
    # The face slot is no longer the plain template colour.
    assert big.getpixel((200, 100)) != Image.open(store.image_path(template)).convert("RGB").getpixel((200, 100))
