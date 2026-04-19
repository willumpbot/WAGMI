from __future__ import annotations

from memegine import auto_codex


def test_extract_lens_focal_and_aperture():
    p = "Trader, shot on 35mm f/1.4, Portra 400, window light, dusk"
    patterns = auto_codex.extract(p)
    assert any("35mm" in l for l in patterns.lens)
    assert "portra" in patterns.film


def test_extract_multiple_lenses_deduped():
    p = "Using 35mm f/1.4 then later 35mm f/1.4 again"
    patterns = auto_codex.extract(p)
    # De-duped:
    assert len(patterns.lens) == 1


def test_extract_camera_move():
    p = "slow push-in across the room, rack focus at 3s"
    patterns = auto_codex.extract(p)
    assert "push-in" in patterns.camera_move
    assert "rack focus" in patterns.camera_move


def test_extract_empty_on_bare_text():
    patterns = auto_codex.extract("just some random words")
    assert patterns.is_empty()


def test_record_winner_writes_codex(tmp_path, monkeypatch):
    codex_path = tmp_path / "style.md"
    import memegine.style_codex as sc_mod
    monkeypatch.setattr(sc_mod.settings, "codex_path", codex_path, raising=False)

    patterns = auto_codex.record_winner(
        "Trader, 35mm f/1.4, Portra 400, window light, dusk, rule of thirds",
        "landed because of film grain",
    )
    assert not patterns.is_empty()
    text = codex_path.read_text(encoding="utf-8")
    assert "Proven Prompt Patterns" in text
    assert "Compounded Patterns" in text
    assert "35mm" in text


def test_distill_filters_by_frequency():
    prompts = [
        "35mm f/1.4, Portra 400, window light",
        "35mm f/1.4, Cinestill 800T, neon",
        "50mm f/1.8, Portra 400, dusk",
    ]
    dist = auto_codex.distill(prompts, min_frequency=2)
    # 35mm f/1.4 appears twice
    lens_vals = [v for v, _ in dist["lens"]]
    assert any("35mm" in v for v in lens_vals)
    # Portra 400 appears twice
    assert any("portra" in v for v, _ in dist["film"])


def test_distill_empty_on_high_threshold():
    prompts = ["35mm f/1.4", "50mm f/1.8"]
    dist = auto_codex.distill(prompts, min_frequency=3)
    # Nothing appeared 3 times
    for v in dist.values():
        assert v == []


def test_as_codex_line_formats_cleanly():
    from memegine.auto_codex import ExtractedPatterns
    p = ExtractedPatterns(
        lens=["35mm f/1.4"], film=["portra"], lighting=["window light"],
        time_of_day=["dusk"], composition=["rule of thirds"],
    )
    line = p.as_codex_line()
    assert "lens=35mm f/1.4" in line
    assert "film=portra" in line
    assert "lighting=window light" in line
