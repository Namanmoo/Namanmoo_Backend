"""이미지 손질 — 실제로 겪은 실패를 고정해 둔다.

1. 투명 배경을 그대로 보냈더니 모델이 검정으로 읽고 검은 배경을 보존했다.
2. "순백 배경"을 요구해도 옅은 유령 실루엣과 글자 파편이 끼었다.
3. 배경을 지워도 색이 있는 조각은 살아남아 무기 옆에 점으로 떠다녔다.
"""

from __future__ import annotations

import io

from PIL import Image

from app.forge.image_prep import (
    drop_small_islands,
    flatten_to_white,
    opaque_ratio,
    remove_light_background,
)


def to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def opened(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGBA")


def transparent_drawing(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for x in range(12, 52):
        for y in range(28, 36):
            image.putpixel((x, y), (220, 40, 40, 255))
    return image


def test_transparent_background_becomes_white_not_black():
    # 검정으로 바뀌면 img2img가 검은 배경을 그대로 보존한다
    result = opened(flatten_to_white(to_png(transparent_drawing())))

    assert result.getpixel((0, 0))[:3] == (255, 255, 255)
    assert result.getpixel((20, 32))[:3] == (220, 40, 40)


def test_flatten_can_force_a_square_size():
    tall = Image.new("RGBA", (40, 90), (0, 0, 0, 0))

    result = opened(flatten_to_white(to_png(tall), size=64))

    assert result.size == (64, 64)


def test_light_background_is_removed_but_subject_survives():
    image = Image.new("RGB", (64, 64), (250, 250, 252))
    for x in range(20, 44):
        for y in range(28, 36):
            image.putpixel((x, y), (200, 30, 30))

    result = opened(remove_light_background(to_png(image)))

    assert result.getpixel((0, 0))[3] == 0, "배경은 투명해야 한다"
    assert result.getpixel((30, 32))[3] == 255, "무기는 남아야 한다"


def test_faint_ghost_in_the_background_is_removed():
    # 모델이 끼워 넣는 유령 실루엣은 아주 옅어서 배경과 함께 지워져야 한다
    image = Image.new("RGB", (64, 64), (252, 252, 252))
    for x in range(4, 24):
        for y in range(4, 24):
            image.putpixel((x, y), (238, 240, 246))  # 옅은 얼룩
    for x in range(20, 44):
        for y in range(28, 36):
            image.putpixel((x, y), (30, 60, 200))  # 무기

    result = opened(remove_light_background(to_png(image)))

    assert result.getpixel((10, 10))[3] == 0
    assert result.getpixel((30, 32))[3] == 255


def test_white_enclosed_by_the_subject_survives():
    # 무기 안쪽 하이라이트가 뚫리면 안 된다 — 가장자리에서 번지는 방식이라 남는다
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(16, 48):
        for y in range(16, 48):
            image.putpixel((x, y), (20, 20, 20))
    for x in range(28, 36):
        for y in range(28, 36):
            image.putpixel((x, y), (255, 255, 255))

    result = opened(remove_light_background(to_png(image)))

    assert result.getpixel((32, 32))[3] == 255, "둘러싸인 흰 픽셀은 남아야 한다"
    assert result.getpixel((0, 0))[3] == 0


def test_small_islands_are_dropped():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(10, 50):  # 큰 덩어리 = 무기
        for y in range(28, 38):
            image.putpixel((x, y), (200, 30, 30, 255))
    image.putpixel((5, 5), (30, 60, 200, 255))  # 떠다니는 점
    image.putpixel((60, 60), (240, 200, 20, 255))

    result = opened(drop_small_islands(to_png(image)))

    assert result.getpixel((5, 5))[3] == 0
    assert result.getpixel((60, 60))[3] == 0
    assert result.getpixel((30, 32))[3] == 255


def test_deliberately_detached_parts_are_kept():
    # 일부러 떼어 그린 부품(떠 있는 구슬 같은 것)은 얼룩보다 훨씬 크다
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(6, 40):
        for y in range(28, 38):
            image.putpixel((x, y), (200, 30, 30, 255))
    for x in range(46, 58):  # 떨어진 구슬 — 큰 덩어리의 약 35%
        for y in range(28, 38):
            image.putpixel((x, y), (30, 160, 90, 255))

    result = opened(drop_small_islands(to_png(image)))

    assert result.getpixel((50, 32))[3] == 255


def test_all_islands_equal_keeps_everything():
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(2, 10):
        image.putpixel((x, 5), (0, 0, 0, 255))
    for x in range(20, 28):
        image.putpixel((x, 5), (0, 0, 0, 255))

    result = opened(drop_small_islands(to_png(image)))

    assert result.getpixel((5, 5))[3] == 255
    assert result.getpixel((24, 5))[3] == 255


def test_fully_transparent_input_is_returned_unchanged():
    png = to_png(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))

    assert drop_small_islands(png) == png


def test_opaque_ratio_counts_only_visible_pixels():
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for x in range(5):
        image.putpixel((x, 0), (0, 0, 0, 255))

    assert opaque_ratio(to_png(image)) == 0.05


def test_blank_generation_is_detected_as_vanished():
    """SD가 드물게 거의 빈 이미지를 낸다. 손질하면 전부 투명해져 무기가 안 보인다."""
    blank = Image.new("RGB", (64, 64), (252, 252, 253))

    cleaned = drop_small_islands(remove_light_background(to_png(blank)))

    assert opaque_ratio(cleaned) < 0.005
