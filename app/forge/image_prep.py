"""이미지 모델에 보내기 전 그림 손질.

투명 배경을 흰색으로 눕히는 게 핵심이다. 그리기 캔버스는 알파 0으로 배경을
비워 보내는데, 이미지 모델이 RGB로 변환하면서 그 영역이 **검정**이 된다.
그러면 img2img가 검정 배경을 그대로 보존해 버린다 — 프롬프트로 "흰 배경"을
요구해도 입력이 검정이면 이기지 못한다. (실제로 검은 배경 결과를 받고 알았다.)
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

WHITE = (255, 255, 255)

# 배경 제거용 센티넬 — 생성 결과에 나올 일이 없는 색을 쓴다
_SENTINEL = (255, 0, 255)

# 밝은 배경으로 볼 허용 오차. 생성 결과의 배경은 모서리 243~254, 테두리 표준편차
# 3 정도로 거의 균일했다. 프롬프트로 막아도 옅은 유령 실루엣이나 글자가 끼는데,
# 그것들도 전부 옅어서 이 오차 안에 들어온다.
_BACKGROUND_TOLERANCE = 46


def flatten_to_white(png: bytes, size: int | None = None) -> bytes:
    """투명 배경을 흰색으로 합성한 PNG를 돌려준다.

    size를 주면 정사각형으로 맞춘다 — 입력 비율이 들쭉날쭉하면 모델이 구도를
    잃기 쉬워서, 크기를 고정해 두는 편이 결과가 안정적이다.
    """
    with Image.open(io.BytesIO(png)) as opened:
        source = opened.convert("RGBA")

        background = Image.new("RGBA", source.size, (*WHITE, 255))
        flattened = Image.alpha_composite(background, source).convert("RGB")

        if size is not None and flattened.size != (size, size):
            flattened = flattened.resize((size, size), Image.LANCZOS)

        buffer = io.BytesIO()
        flattened.save(buffer, format="PNG")
        return buffer.getvalue()


def remove_light_background(png: bytes, tolerance: int = _BACKGROUND_TOLERANCE) -> bytes:
    """생성 이미지의 밝은 배경을 투명하게 만든 PNG를 돌려준다.

    프롬프트로 "순백 배경"을 요구해도 SD는 옅은 유령 실루엣이나 글자를 배경에
    끼워 넣는다. 프롬프트를 조여봐도 계속 새서, 결과에서 직접 지우는 쪽으로 갔다.

    네 모서리와 각 변 중앙에서 플러드 필로 번져 나간다 — 바깥과 이어진 밝은
    영역만 지우므로 무기 안쪽의 흰 하이라이트는 남는다.
    (같은 방식이 클라이언트 WhiteBackgroundKey에도 있고, 여기서 이미 투명해지면
    그쪽은 자연히 할 일이 없어진다.)
    """
    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("RGB")

    width, height = image.size
    seeds = [
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    ]

    for seed in seeds:
        if image.getpixel(seed) == _SENTINEL:
            continue  # 이미 앞선 씨앗이 삼킨 영역
        ImageDraw.floodfill(image, seed, _SENTINEL, thresh=tolerance)

    keyed = image.convert("RGBA")
    pixels = keyed.load()
    for y in range(height):
        for x in range(width):
            r, g, b, _ = pixels[x, y]
            if (r, g, b) == _SENTINEL:
                pixels[x, y] = (255, 255, 255, 0)

    buffer = io.BytesIO()
    keyed.save(buffer, format="PNG")
    return buffer.getvalue()


class SubjectVanished(RuntimeError):
    """손질 후 남은 게 거의 없을 때.

    SD는 매번 다르게 나오고, 드물게 거의 빈 이미지를 낸다. 그런 판을 손질하면
    전부 투명해져 게임에 '보이지 않는 무기'가 들어간다 — 실제로 한 번 겪었다.
    그 경우는 생성 실패로 취급하고 플레이어가 그린 그림을 쓰는 게 맞다.
    """


def opaque_ratio(png: bytes) -> float:
    """불투명 픽셀 비율. 손질이 그림을 통째로 먹었는지 판단하는 데 쓴다."""
    with Image.open(io.BytesIO(png)) as opened:
        alpha = opened.convert("RGBA").getchannel("A")

    opaque = sum(1 for value in alpha.get_flattened_data() if value > 8)
    return opaque / (alpha.width * alpha.height)


def drop_small_islands(png: bytes, min_ratio: float = 0.08) -> bytes:
    """떨어져 있는 작은 얼룩을 지운다.

    배경을 지워도 색이 있는 조각(모델이 끼워 넣은 글자 파편 같은 것)은 허용 오차를
    넘어 살아남는다. 게임에서는 무기 옆에 떠다니는 점으로 보인다.

    무기는 보통 이어진 한 덩어리이므로, 가장 큰 덩어리의 <paramref name="min_ratio"/>
    미만인 조각은 버린다. 비율로 판단하는 이유는 일부러 떼어 그린 부품(떠 있는 구슬
    같은 것)을 살리기 위해서다 — 그런 건 얼룩보다 훨씬 크다.
    """
    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("RGBA")

    width, height = image.size
    pixels = image.load()
    opaque = [pixels[x, y][3] > 8 for y in range(height) for x in range(width)]

    labels = [-1] * (width * height)
    sizes: list[int] = []

    for start in range(width * height):
        if not opaque[start] or labels[start] != -1:
            continue

        label = len(sizes)
        stack = [start]
        labels[start] = label
        count = 0

        while stack:
            index = stack.pop()
            count += 1
            x, y = index % width, index // width

            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbour = ny * width + nx
                    if opaque[neighbour] and labels[neighbour] == -1:
                        labels[neighbour] = label
                        stack.append(neighbour)

        sizes.append(count)

    if not sizes:
        return png

    threshold = max(sizes) * min_ratio
    doomed = {label for label, size in enumerate(sizes) if size < threshold}
    if not doomed:
        return png

    for y in range(height):
        for x in range(width):
            if labels[y * width + x] in doomed:
                pixels[x, y] = (255, 255, 255, 0)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
