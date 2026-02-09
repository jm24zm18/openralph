from __future__ import annotations

import math
import struct

from openralph.openralph_cli.memory.query import _apply_path_boost, _cosine, _unpack_f32


def test_cosine_basic() -> None:
    score = _cosine([1.0, 0.0], [1.0, 0.0])
    assert math.isclose(score, 1.0)


def test_apply_path_boost_prefix() -> None:
    score = _apply_path_boost("docs/PRD.md", 1.0, [("docs/PRD.md", 1.3)])
    assert math.isclose(score, 1.3)


def test_unpack_f32() -> None:
    blob = struct.pack("2f", 1.5, -2.0)
    vec = _unpack_f32(blob, 2)
    assert len(vec) == 2
    assert math.isclose(vec[0], 1.5)
    assert math.isclose(vec[1], -2.0)
