"""japanize-matplotlib（2020 年から未更新）の font 登録が壊れたら検知する回帰テスト。

壊れた場合の症状は日本語ラベルの豆腐化で、matplotlib は描画時に
"Glyph NNNN ... missing from font(s)" の UserWarning を出す。それを検知する。
"""

import warnings

import matplotlib

matplotlib.use("Agg")


def test_japanese_glyphs_render_without_missing_font_warnings():
    import japanize_matplotlib  # noqa: F401 — フォント登録の副作用が本テストの対象
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.set_title("日本語ラベル描画テスト（再生回数・視聴維持率）")
    ax.plot([0, 1], [0, 1], label="テスト系列")
    ax.legend()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig.canvas.draw()
    plt.close(fig)

    missing = [w for w in caught if "missing from font" in str(w.message)]
    assert not missing, f"日本語 glyph が描画できていない: {[str(w.message) for w in missing]}"
