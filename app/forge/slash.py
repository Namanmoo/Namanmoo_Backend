"""검기 참격 모양 생성 — 5×5 그리드 공식.

맨 윗줄과 맨 아랫줄에 점 하나씩, 사이 줄에 2~4개 점을 랜덤으로 찍고
위→아래로 이어 닫은 다각형을 채운다. 잇는 방식은 전부 직선이거나
전부 곡선 — 렌더링은 Unity(SlashSprites)가 하고, 여기서는 좌표만 정한다.

무기를 만들 때 한 번 뽑아 응답에 실어 저장한다 — 모양이 무기의 일부가 된다.
"""

from __future__ import annotations

import random

from .schema import SlashShape

GRID = 5

# 그리드 가장자리가 텍스처 가장자리에 닿지 않게 두는 여백 (정규화 -1~1 기준)
EXTENT = 0.92

MIN_MIDDLE_POINTS = 2
MAX_MIDDLE_POINTS = 4


# 이보다 얇으면 다시 뽑는다 — 점들이 한 줄에 몰리면 참격이 실처럼 가늘어진다
MIN_AREA = 0.6
MAX_ROLLS = 12


def _shoelace_area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def _roll(rng: random.Random) -> list[tuple[float, float]]:
    def cell(index: int) -> float:
        half = (GRID - 1) / 2
        return (index - half) / half * EXTENT

    points = [(cell(rng.randrange(GRID)), EXTENT)]  # 맨 윗줄 — 무조건 하나

    count = rng.randint(MIN_MIDDLE_POINTS, MAX_MIDDLE_POINTS)
    # 사이 점들이 한 줄에 몰리지 않게 줄부터 나눠 갖는다 (3줄 초과분만 중복)
    rows = rng.sample(range(1, GRID - 1), k=min(count, GRID - 2))
    rows += [rng.randrange(1, GRID - 1) for _ in range(count - len(rows))]
    middles = [(cell(rng.randrange(GRID)), cell(row)) for row in rows]
    # 위→아래로 이어지게 — 같은 줄이면 찍은 순서를 지킨다 (sort는 안정적이다)
    middles.sort(key=lambda p: p[1], reverse=True)

    points += middles
    points.append((cell(rng.randrange(GRID)), -EXTENT))  # 맨 아랫줄
    return points


def make_slash_shape(rng: random.Random | None = None) -> SlashShape:
    rng = rng or random.Random()

    points = _roll(rng)
    for _ in range(MAX_ROLLS):
        if _shoelace_area(points) >= MIN_AREA:
            break
        points = _roll(rng)

    return SlashShape(
        curved=bool(rng.getrandbits(1)),
        points=[coord for point in points for coord in point],
    )
