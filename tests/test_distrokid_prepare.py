"""yt-distrokid-prepare CLI の unit / 統合テスト（#936）.

テスト境界:
- utils/distrokid_prepare.py の純関数（split_tracks / build_draft_spec /
  validate_spec / render_metadata_md / verify_roundtrip / resize_cover / write_release_date）
- scripts/distrokid_prepare.py の main() を argv 指定で呼ぶ統合テスト

probe_duration は monkeypatch で固定値 199.0 秒を返す。
fake mp3 は test_distrokid_disc_source.py と同じ bytes パターンを踏襲する。
load_config は CLI 統合テストで monkeypatch して Distrokid dataclass を返す fake に差し替える。

fixtures/sample_channel/ に distrokid.json が存在しないため、
CLI レベルのテストは load_config を monkeypatch する方針をとる（fixture への追加は不要）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from youtube_automation.utils.distrokid_prepare import (
    COVER_ART_FILENAME,
    DISTROKID_DIRNAME,
    INDIVIDUAL_MUSIC_DIRNAME,
    SPEC_FILENAME,
    build_draft_spec,
    render_metadata_md,
    resize_cover,
    split_tracks,
    validate_spec,
    verify_roundtrip,
    write_release_date,
)
from youtube_automation.utils.distrokid_spec import read_collection_spec
from youtube_automation.utils.exceptions import ConfigError, ValidationError

# fake mp3 bytes（test_distrokid_disc_source.py と同じパターン）
_MP3_BYTES = b"ID3\x03\x00\x00\x00fake-mp3-bytes"


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_collection(tmp_path: Path, *, n_tracks: int = 4) -> Path:
    """最小コレクション構造を tmp_path に作成して返す."""
    collection = tmp_path / "20260601-test-channel-my-theme-collection"
    music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
    music_dir.mkdir(parents=True)
    (collection / "01-master").mkdir()
    for i in range(1, n_tracks + 1):
        (music_dir / f"{i:02d}-track-{i:02d}.mp3").write_bytes(_MP3_BYTES)
    return collection


def _filenames(n: int) -> list[str]:
    """n 曲分のファイル名リストを生成する."""
    return [f"{i:02d}-track-{i:02d}.mp3" for i in range(1, n + 1)]


def _fake_config(*, enabled: bool = True, artist: str = ""):
    """load_config() の戻り値を模倣する fake config オブジェクト."""
    from youtube_automation.configuration.distrokid import (
        Distrokid,
        DistrokidProfile,
    )

    _profile = DistrokidProfile(
        artist=artist,
        language="English",
        main_genre="Electronic",
        sub_genre="Ambient",
    )
    _distrokid = Distrokid(enabled=enabled, profile=_profile)

    class _Meta:
        channel_name = "Test Artist"

    # クラス属性への代入時にローカル変数名が解決されるよう、明示的に dict を使う
    _Config = type(
        "_Config",
        (),
        {"meta": _Meta(), "distrokid": _distrokid},
    )

    return _Config()


# ---------------------------------------------------------------------------
# 1. split_tracks: 分割境界テスト
# ---------------------------------------------------------------------------


class TestSplitTracks:
    def test_35_tracks_yields_1_disc(self):
        """35 曲 → 1 disc（max_per_disc 境界）."""
        result = split_tracks(_filenames(35))
        assert len(result) == 1
        assert len(result[0]) == 35

    def test_36_tracks_yields_2_discs_18_18(self):
        """36 曲 → 2 discs [18, 18]."""
        result = split_tracks(_filenames(36))
        assert [len(c) for c in result] == [18, 18]

    def test_50_tracks_yields_2_discs_25_25(self):
        """50 曲 → 2 discs [25, 25]."""
        result = split_tracks(_filenames(50))
        assert [len(c) for c in result] == [25, 25]

    def test_70_tracks_yields_2_discs_35_35(self):
        """70 曲 → 2 discs [35, 35]."""
        result = split_tracks(_filenames(70))
        assert [len(c) for c in result] == [35, 35]

    def test_71_tracks_yields_3_discs_24_24_23(self):
        """71 曲 → 3 discs [24, 24, 23]（均等連続チャンク）."""
        result = split_tracks(_filenames(71))
        assert [len(c) for c in result] == [24, 24, 23]

    def test_discs_1_with_50_tracks_raises_config_error(self):
        """--discs 1 で 50 曲 → ConfigError（1 disc が 35 を超える）."""
        with pytest.raises(ConfigError, match="上限"):
            split_tracks(_filenames(50), discs=1)

    def test_315_plus_tracks_raises_config_error(self):
        """315 曲超（10 disc 以上）→ ConfigError."""
        with pytest.raises(ConfigError, match="上限"):
            split_tracks(_filenames(316))

    def test_empty_filenames_raises_config_error(self):
        """空リスト → ConfigError."""
        with pytest.raises(ConfigError):
            split_tracks([])

    def test_order_preserved(self):
        """分割後の全ファイル名が元の順序を維持する."""
        filenames = _filenames(71)
        chunks = split_tracks(filenames)
        assert [name for chunk in chunks for name in chunk] == filenames

    def test_9_discs_allowed(self):
        """9 discs（上限）は OK."""
        # 9 * 35 = 315 曲で自動 9 disc
        result = split_tracks(_filenames(315))
        assert len(result) == 9


# ---------------------------------------------------------------------------
# 2. build_draft_spec: draft spec の内容
# ---------------------------------------------------------------------------


class TestBuildDraftSpec:
    def _base_spec(self, filenames: list[str], **kwargs) -> dict:
        chunks = split_tracks(filenames)
        return build_draft_spec(
            "my-theme-collection",
            chunks,
            artist=kwargs.get("artist", "Test Artist"),
            language=kwargs.get("language", "English"),
            genre_primary=kwargs.get("genre_primary", "Electronic"),
            genre_secondary=kwargs.get("genre_secondary", "Ambient"),
        )

    def test_version_is_1(self):
        spec = self._base_spec(_filenames(4))
        assert spec["version"] == 1

    def test_artist_and_language_filled(self):
        spec = self._base_spec(_filenames(4))
        assert spec["artist"] == "Test Artist"
        assert spec["language"] == "English"

    def test_genre_primary_and_secondary_filled(self):
        spec = self._base_spec(_filenames(4))
        assert spec["genre_primary"] == "Electronic"
        assert spec["genre_secondary"] == "Ambient"

    def test_label_is_null(self):
        spec = self._base_spec(_filenames(4))
        assert spec["label"] is None

    def test_35_tracks_use_single_disc_slug_and_album_title(self):
        """35 曲の単一 disc は suffix なしの slug / album_title を生成する。"""
        spec = self._base_spec(_filenames(35))
        disc = spec["discs"][0]
        assert disc["slug"] == "my-theme"
        assert disc["album_title"] == "My Theme"

    def test_needs_unique_on_duplicate_titles(self):
        """重複する素タイトルを持つトラックには needs_unique=True が全件付く."""
        # 同じ stem を持つ mp3（例: 01-slip.mp3 / 02-slip.mp3 → "Slip"）
        filenames = [
            "01-slip.mp3",
            "02-slip.mp3",
            "03-unique.mp3",
        ]
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            "test-col",
            chunks,
            artist="Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )
        tracks = spec["discs"][0]["tracks"]
        slip_tracks = [t for t in tracks if t["title"] == "Slip"]
        assert len(slip_tracks) == 2
        # 全件に needs_unique が付く
        assert all(t.get("needs_unique") for t in slip_tracks)
        # ユニークなトラックには付かない
        unique_track = next(t for t in tracks if t["title"] == "Unique")
        assert "needs_unique" not in unique_track

    def test_no_needs_unique_when_no_duplicates(self):
        """重複がなければ needs_unique は一切付かない."""
        filenames = _filenames(4)
        spec = self._base_spec(filenames)
        for disc in spec["discs"]:
            for track in disc["tracks"]:
                assert "needs_unique" not in track

    def test_36_tracks_use_multi_disc_slug_and_album_title(self):
        """36 曲の複数 disc は disc / Vol. suffix を生成する。"""
        spec = self._base_spec(_filenames(36))
        assert [(disc["slug"], disc["album_title"]) for disc in spec["discs"]] == [
            ("disc1-my-theme-vol1", "My Theme Vol.1"),
            ("disc2-my-theme-vol2", "My Theme Vol.2"),
        ]


# ---------------------------------------------------------------------------
# 3. validate_spec: エラーケース
# ---------------------------------------------------------------------------


class TestValidateSpec:
    def _minimal_spec(self, filenames: list[str]) -> dict:
        """有効な minimal spec を返す."""
        chunks = split_tracks(filenames)
        return build_draft_spec(
            "test-col",
            chunks,
            artist="Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )

    def test_valid_spec_passes(self):
        """有効な spec は ValidationError を raise しない."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        validate_spec(spec, filenames)  # 例外なし

    def test_single_disc_kebab_slug_passes(self):
        """単一 disc の kebab-case slug は build 用 validation を通る。"""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        spec["discs"][0]["slug"] = "dark-techno"
        spec["discs"][0]["album_title"] = "Dark Techno"
        validate_spec(spec, filenames)  # 例外なし

    def test_title_duplicate_across_discs_raises(self):
        """disc 横断タイトル重複 → ValidationError."""
        filenames = [
            "01-slip.mp3",
            "02-slip.mp3",
        ]
        spec = self._minimal_spec(filenames)
        # needs_unique=True のまま submit（ユニーク化せずに validate）
        with pytest.raises(ValidationError, match="タイトル|重複"):
            validate_spec(spec, filenames)

    def test_missing_file_raises(self):
        """ファイル漏れ（music にあるが spec にない）→ ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        # music には 5 ファイル目を追加
        music_filenames = [*filenames, "05-extra.mp3"]
        with pytest.raises(ValidationError, match="漏れ"):
            validate_spec(spec, music_filenames)

    def test_unknown_file_raises(self):
        """未知ファイル（spec にあるが music にない）→ ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        # music には 3 ファイルのみ
        with pytest.raises(ValidationError, match="未知"):
            validate_spec(spec, filenames[:3])

    def test_duplicate_assignment_raises(self):
        """同一ファイルを 2 回割当 → ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        # tracks[0] を tracks[1] と同じファイル名に書き換え
        spec["discs"][0]["tracks"][1]["filename"] = spec["discs"][0]["tracks"][0]["filename"]
        with pytest.raises(ValidationError, match="重複割当"):
            validate_spec(spec, filenames)

    def test_too_many_tracks_in_disc_raises(self):
        """36 曲 disc → ValidationError."""
        filenames = _filenames(36)
        spec = self._minimal_spec(filenames)
        # 2 disc [18, 18] を 1 disc に強引にまとめる
        all_tracks = spec["discs"][0]["tracks"] + spec["discs"][1]["tracks"]
        spec["discs"] = [
            {
                "slug": "disc1-col-vol1",
                "album_title": "Vol 1",
                "tracks": all_tracks,
            }
        ]
        with pytest.raises(ValidationError, match="上限"):
            validate_spec(spec, filenames)

    def test_non_kebab_slug_raises(self):
        """非 kebab slug → ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        spec["discs"][0]["slug"] = "disc_1_badslug"
        with pytest.raises(ValidationError, match="kebab"):
            validate_spec(spec, filenames)

    def test_disc_number_out_of_order_raises(self):
        """disc 番号順不同（disc2 が disc1 より先）→ ValidationError."""
        filenames = _filenames(50)
        spec = self._minimal_spec(filenames)
        # slug を逆順にする
        spec["discs"][0]["slug"] = "disc2-col-vol2"
        spec["discs"][1]["slug"] = "disc1-col-vol1"
        with pytest.raises(ValidationError, match="番号順"):
            validate_spec(spec, filenames)

    def test_empty_artist_raises(self):
        """artist が空 → ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        spec["artist"] = ""
        with pytest.raises(ValidationError, match="artist"):
            validate_spec(spec, filenames)

    def test_empty_album_title_raises(self):
        """album_title が空 → ValidationError."""
        filenames = _filenames(4)
        spec = self._minimal_spec(filenames)
        spec["discs"][0]["album_title"] = ""
        with pytest.raises(ValidationError, match="album_title"):
            validate_spec(spec, filenames)


# ---------------------------------------------------------------------------
# 4. render_metadata_md / verify_roundtrip
# ---------------------------------------------------------------------------


class TestRenderMetadataMd:
    def _make_spec_disc(self, filenames: list[str]) -> dict:
        """単純な disc spec を生成する."""
        tracks = [{"filename": fn, "title": f"Track {i}"} for i, fn in enumerate(filenames, 1)]
        return {
            "slug": "disc1-my-theme-vol1",
            "album_title": "My Theme Vol.1",
            "tracks": tracks,
        }

    def test_album_title_in_header(self):
        """metadata.md のヘッダに album_title が含まれる."""
        disc_spec = self._make_spec_disc(["01-foo.mp3"])
        durations = {"01-foo.mp3": 199.0}
        global_numbers = {"01-foo.mp3": 1}
        md = render_metadata_md(
            disc_spec,
            durations,
            global_numbers,
            artist="Artist",
            language="English",
            genre_primary="Electronic",
        )
        assert "My Theme Vol.1" in md

    def test_track_filename_in_backticks(self):
        """filename がバッククォートで囲まれる."""
        disc_spec = self._make_spec_disc(["01-foo.mp3"])
        durations = {"01-foo.mp3": 199.0}
        global_numbers = {"01-foo.mp3": 1}
        md = render_metadata_md(disc_spec, durations, global_numbers)
        assert "`01-foo.mp3`" in md

    def test_duration_formatted_mss(self):
        """尺が m:ss 形式でフォーマットされる（199.0 → 3:19）."""
        disc_spec = self._make_spec_disc(["01-foo.mp3"])
        durations = {"01-foo.mp3": 199.0}
        global_numbers = {"01-foo.mp3": 1}
        md = render_metadata_md(disc_spec, durations, global_numbers)
        assert "3:19" in md

    def test_release_date_comment_when_none(self):
        """release_date=None の場合は HTML コメント枠が入る."""
        disc_spec = self._make_spec_disc(["01-foo.mp3"])
        md = render_metadata_md(disc_spec, {"01-foo.mp3": 199.0}, {"01-foo.mp3": 1})
        assert "<!-- YYYY-MM-DD" in md

    def test_release_date_written_when_provided(self):
        """release_date 指定時はその値が書き込まれる."""
        disc_spec = self._make_spec_disc(["01-foo.mp3"])
        md = render_metadata_md(disc_spec, {"01-foo.mp3": 199.0}, {"01-foo.mp3": 1}, release_date="2026-07-01")
        assert "2026-07-01" in md

    def test_global_number_in_disc2_starts_from_26(self, tmp_path):
        """disc2 の先頭トラックはグローバル番号 26 が入る."""
        filenames = [f"{i:02d}-track.mp3" for i in range(26, 31)]
        tracks = [{"filename": fn, "title": f"Track {i}"} for i, fn in enumerate(filenames, 26)]
        disc_spec = {
            "slug": "disc2-my-theme-vol2",
            "album_title": "My Theme Vol.2",
            "tracks": tracks,
        }
        durations = {fn: 199.0 for fn in filenames}
        global_numbers = {fn: int(fn[:2]) for fn in filenames}
        md = render_metadata_md(disc_spec, durations, global_numbers)
        assert "| 26 |" in md

    def test_roundtrip_verify_passes(self, tmp_path):
        """render → write → parse で album_title / title / filename が一致する."""
        disc_spec = {
            "slug": "disc1-test-vol1",
            "album_title": "Test Vol.1",
            "tracks": [
                {"filename": "01-slip.mp3", "title": "Slip"},
                {"filename": "02-easy.mp3", "title": "Easy"},
            ],
        }
        durations = {"01-slip.mp3": 198.0, "02-easy.mp3": 205.0}
        global_numbers = {"01-slip.mp3": 1, "02-easy.mp3": 2}
        md = render_metadata_md(
            disc_spec,
            durations,
            global_numbers,
            artist="Test Artist",
            language="English",
            genre_primary="Electronic",
        )
        md_path = tmp_path / "metadata.md"
        md_path.write_text(md, encoding="utf-8")

        # verify_roundtrip が例外を raise しないことを確認
        verify_roundtrip(md_path, disc_spec, [1, 2])

    def test_roundtrip_mismatch_raises_config_error(self, tmp_path):
        """タイトルが一致しない場合 ConfigError を raise する."""
        disc_spec = {
            "slug": "disc1-test-vol1",
            "album_title": "Test Vol.1",
            "tracks": [{"filename": "01-slip.mp3", "title": "Slip"}],
        }
        durations = {"01-slip.mp3": 199.0}
        global_numbers = {"01-slip.mp3": 1}
        md = render_metadata_md(disc_spec, durations, global_numbers)
        md_path = tmp_path / "metadata.md"
        md_path.write_text(md, encoding="utf-8")

        # spec のタイトルを変えて不一致を作る
        disc_spec_wrong = {**disc_spec, "tracks": [{"filename": "01-slip.mp3", "title": "Different"}]}
        with pytest.raises(ConfigError, match="ラウンドトリップ"):
            verify_roundtrip(md_path, disc_spec_wrong, [1])


# ---------------------------------------------------------------------------
# 5. cover: resize_cover
# ---------------------------------------------------------------------------


class TestResizeCover:
    def _make_square_png(self, tmp_path: Path, size: int = 512) -> Path:
        """テスト用正方形 PNG を生成する."""
        from PIL import Image

        img = Image.new("RGB", (size, size), color=(128, 64, 32))
        path = tmp_path / "input.png"
        img.save(str(path), format="PNG")
        return path

    def _make_rect_png(self, tmp_path: Path, w: int = 600, h: int = 400) -> Path:
        """テスト用非正方形 PNG を生成する."""
        from PIL import Image

        img = Image.new("RGB", (w, h), color=(128, 64, 32))
        path = tmp_path / "input_rect.png"
        img.save(str(path), format="PNG")
        return path

    def test_square_512_converted_to_3000x3000_jpeg(self, tmp_path):
        """512×512 PNG → 3000×3000 JPEG に変換される."""
        from PIL import Image

        input_path = self._make_square_png(tmp_path)
        output_path = tmp_path / COVER_ART_FILENAME
        resize_cover(input_path, output_path)

        img = Image.open(output_path)
        assert img.size == (3000, 3000)
        assert img.format == "JPEG"

    def test_non_square_raises_config_error(self, tmp_path):
        """600×400 非正方形 → ConfigError（--crop なし）."""
        input_path = self._make_rect_png(tmp_path)
        output_path = tmp_path / COVER_ART_FILENAME
        with pytest.raises(ConfigError, match="正方形"):
            resize_cover(input_path, output_path)

    def test_crop_flag_allows_non_square(self, tmp_path):
        """--crop 指定時は非正方形も処理できる."""
        from PIL import Image

        input_path = self._make_rect_png(tmp_path, 600, 400)
        output_path = tmp_path / COVER_ART_FILENAME
        resize_cover(input_path, output_path, crop=True)

        img = Image.open(output_path)
        assert img.size == (3000, 3000)

    def test_existing_cover_without_force_raises(self, tmp_path):
        """既存 cover_art_3000.jpg + --force なし → ConfigError."""
        input_path = self._make_square_png(tmp_path)
        output_path = tmp_path / COVER_ART_FILENAME
        output_path.write_bytes(b"dummy")

        with pytest.raises(ConfigError, match="既に存在"):
            resize_cover(input_path, output_path)

    def test_force_flag_overwrites_existing(self, tmp_path):
        """--force 指定時は既存 cover を上書きする."""
        from PIL import Image

        input_path = self._make_square_png(tmp_path)
        output_path = tmp_path / COVER_ART_FILENAME
        output_path.write_bytes(b"dummy")

        resize_cover(input_path, output_path, force=True)
        img = Image.open(output_path)
        assert img.size == (3000, 3000)

    def test_broken_image_raises_config_error(self, tmp_path):
        """壊れた画像 → ConfigError（UnidentifiedImageError / OSError を変換）."""
        broken = tmp_path / "broken.jpg"
        broken.write_bytes(b"not-an-image")
        output_path = tmp_path / COVER_ART_FILENAME

        with pytest.raises(ConfigError, match="画像を開けません"):
            resize_cover(broken, output_path)


# ---------------------------------------------------------------------------
# 6. write_release_date
# ---------------------------------------------------------------------------


class TestWriteReleaseDate:
    def test_creates_new_file(self, tmp_path):
        """workflow-state.json が無い場合は新規作成する."""
        ws_path = tmp_path / "workflow-state.json"
        write_release_date(ws_path, "2026-08-01")

        data = json.loads(ws_path.read_text())
        assert data["planning"]["publish_target_at"] == "2026-08-01"

    def test_preserves_existing_keys(self, tmp_path):
        """既存キー（例 planning.theme）を保持する."""
        ws_path = tmp_path / "workflow-state.json"
        existing = {"planning": {"theme": "my-theme", "status": "done"}, "other": "value"}
        ws_path.write_text(json.dumps(existing), encoding="utf-8")

        write_release_date(ws_path, "2026-09-15")

        data = json.loads(ws_path.read_text())
        assert data["planning"]["theme"] == "my-theme"
        assert data["planning"]["status"] == "done"
        assert data["planning"]["publish_target_at"] == "2026-09-15"
        assert data["other"] == "value"

    def test_invalid_date_format_raises(self, tmp_path):
        """不正な日付形式 → ConfigError."""
        ws_path = tmp_path / "workflow-state.json"
        with pytest.raises(ConfigError, match="YYYY-MM-DD"):
            write_release_date(ws_path, "not-a-date")

    def test_overwrites_existing_publish_target(self, tmp_path):
        """既存の publish_target_at を上書きする（冪等）."""
        ws_path = tmp_path / "workflow-state.json"
        ws_path.write_text(json.dumps({"planning": {"publish_target_at": "2026-01-01"}}))

        write_release_date(ws_path, "2026-12-31")
        data = json.loads(ws_path.read_text())
        assert data["planning"]["publish_target_at"] == "2026-12-31"

    def test_corrupt_json_raises_instead_of_overwriting(self, tmp_path):
        """壊れた JSON は黙って上書きせず ConfigError で中断する（データ消失防止）（#936）."""
        ws_path = tmp_path / "workflow-state.json"
        ws_path.write_text("{ not valid json", encoding="utf-8")

        with pytest.raises(ConfigError, match="不正な JSON"):
            write_release_date(ws_path, "2026-12-31")
        # 元の内容が保持されていること（上書きされていない）
        assert ws_path.read_text(encoding="utf-8") == "{ not valid json"

    def test_non_dict_toplevel_raises(self, tmp_path):
        """トップレベルが object でない JSON は ConfigError で中断する（#936）."""
        ws_path = tmp_path / "workflow-state.json"
        ws_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")

        with pytest.raises(ConfigError, match="object ではありません"):
            write_release_date(ws_path, "2026-12-31")


# ---------------------------------------------------------------------------
# 7. plan 統合テスト（CLI main() を argv 指定で呼ぶ）
# ---------------------------------------------------------------------------


class TestPlanIntegration:
    """main() を直接呼んで plan サブコマンドの config 反映を検証する。"""

    @pytest.mark.parametrize(
        ("n_tracks", "expected_discs"),
        [
            (35, [("channel-my-theme", "Channel My Theme")]),
            (
                36,
                [
                    ("disc1-channel-my-theme-vol1", "Channel My Theme Vol.1"),
                    ("disc2-channel-my-theme-vol2", "Channel My Theme Vol.2"),
                ],
            ),
        ],
    )
    def test_plan_emits_single_or_multi_disc_naming_at_35_track_boundary(
        self, tmp_path, monkeypatch, n_tracks, expected_discs
    ):
        """公開 plan 入口が 35 曲境界に応じた slug / album_title を書き出す。"""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=n_tracks)
        out = tmp_path / "spec.json"
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: _fake_config(artist="Test Artist"),
        )

        sys.argv = ["yt-distrokid-prepare", "plan", "--output", str(out), str(collection)]
        dp_script.main()

        spec = json.loads(out.read_text(encoding="utf-8"))
        assert [(disc["slug"], disc["album_title"]) for disc in spec["discs"]] == expected_discs

    def test_plan_uses_profile_artist_when_configured(self, tmp_path, monkeypatch):
        """profile.artist が非空なら draft spec.artist に優先反映する."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=4)
        out = tmp_path / "spec.json"
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: _fake_config(artist="ABYSS MI"),
        )

        sys.argv = ["yt-distrokid-prepare", "plan", "--output", str(out), str(collection)]
        dp_script.main()

        spec = json.loads(out.read_text(encoding="utf-8"))
        assert spec["artist"] == "ABYSS MI"

    def test_plan_falls_back_to_channel_name_when_profile_artist_empty(self, tmp_path, monkeypatch):
        """profile.artist が空なら draft spec.artist は channel.name に fallback する."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=4)
        out = tmp_path / "spec.json"
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: _fake_config(artist=""),
        )

        sys.argv = ["yt-distrokid-prepare", "plan", "--output", str(out), str(collection)]
        dp_script.main()

        spec = json.loads(out.read_text(encoding="utf-8"))
        assert spec["artist"] == "Test Artist"


# ---------------------------------------------------------------------------
# 8. build 統合テスト（CLI main() を argv 指定で呼ぶ）
# ---------------------------------------------------------------------------


class TestBuildIntegration:
    """main() を直接呼んで build サブコマンドをエンドツーエンドで検証する。"""

    def _make_spec(self, collection: Path, filenames: list[str]) -> Path:
        """spec.json を生成して保存し、パスを返す."""
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            collection.name,
            chunks,
            artist="Test Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary="Ambient",
        )
        # needs_unique トラックのタイトルをユニーク化（実 spec と同条件）
        _unique_spec_inplace(spec)

        spec_path = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
        return spec_path

    def test_build_generates_mp3_copies_and_metadata(self, tmp_path, monkeypatch):
        """build 実行で mp3 コピー・metadata.md・README.md が生成される."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=4)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)

        # probe_duration を monkeypatch（scripts 層でインポートされている）
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        distrokid_dir = collection / DISTROKID_DIRNAME
        disc_dirs = [d for d in distrokid_dir.iterdir() if d.is_dir()]
        assert len(disc_dirs) >= 1

        # mp3 コピーが存在する
        for disc_dir in disc_dirs:
            mp3_count = len(list(disc_dir.glob("*.mp3")))
            assert mp3_count > 0
            # metadata.md が存在する
            assert (disc_dir / "metadata.md").is_file()

        # README.md が存在する
        assert (distrokid_dir / "README.md").is_file()

    def test_build_accepts_single_disc_kebab_slug(self, tmp_path, monkeypatch):
        """公開 build 入口が単一 disc の kebab-case slug を成果物まで処理する。"""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=4)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        spec["discs"][0]["slug"] = "dark-techno"
        spec["discs"][0]["album_title"] = "Dark Techno"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda path: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        disc_dir = collection / DISTROKID_DIRNAME / "dark-techno"
        assert len(list(disc_dir.glob("*.mp3"))) == 4
        assert (disc_dir / "metadata.md").is_file()

    def test_build_metadata_parseable_by_parser(self, tmp_path, monkeypatch):
        """生成した metadata.md が parse_album_metadata / parse_track_table で読み戻せる."""
        from youtube_automation.scripts import distrokid_prepare as dp_script
        from youtube_automation.utils.distrokid_metadata import (
            parse_album_metadata,
            parse_track_table,
        )

        collection = _make_collection(tmp_path, n_tracks=4)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)
        spec = json.loads(spec_path.read_text())

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        disc = spec["discs"][0]
        slug = disc["slug"]
        md_path = collection / DISTROKID_DIRNAME / slug / "metadata.md"

        meta = parse_album_metadata(md_path)
        assert meta["album_title"] == disc["album_title"]

        tracks = parse_track_table(md_path)
        assert len(tracks) == len(disc["tracks"])
        assert tracks[0]["filename"] == disc["tracks"][0]["filename"]

    def test_build_global_numbers_start_from_26_in_disc2(self, tmp_path, monkeypatch):
        """disc2 の先頭トラックのグローバル番号が 26 から始まる（50 曲 split）."""
        from youtube_automation.scripts import distrokid_prepare as dp_script
        from youtube_automation.utils.distrokid_metadata import parse_track_table

        # 50 曲コレクション
        collection = _make_collection(tmp_path, n_tracks=50)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        spec = json.loads(spec_path.read_text())
        disc2 = spec["discs"][1]
        slug2 = disc2["slug"]
        md_path = collection / DISTROKID_DIRNAME / slug2 / "metadata.md"

        tracks = parse_track_table(md_path)
        assert tracks[0]["number"] == 26

    def test_find_distrokid_discs_returns_spec_order(self, tmp_path, monkeypatch):
        """find_distrokid_discs が spec 順（disc1 → disc2）で列挙する."""
        from youtube_automation.scripts import distrokid_prepare as dp_script
        from youtube_automation.scripts.collection_serve import find_distrokid_discs

        collection = _make_collection(tmp_path, n_tracks=4)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)
        spec = json.loads(spec_path.read_text())

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        discs_found = find_distrokid_discs(collection)
        spec_slugs = [d["slug"] for d in spec["discs"]]
        assert discs_found == spec_slugs

    def test_mp3_content_matches_original(self, tmp_path, monkeypatch):
        """コピーされた mp3 の内容がオリジナルと一致する."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=2)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)
        spec = json.loads(spec_path.read_text())

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        disc = spec["discs"][0]
        slug = disc["slug"]
        for track in disc["tracks"]:
            src = music_dir / track["filename"]
            dst = collection / DISTROKID_DIRNAME / slug / track["filename"]
            assert dst.read_bytes() == src.read_bytes()


# ---------------------------------------------------------------------------
# 8. 冪等性テスト
# ---------------------------------------------------------------------------


class TestBuildIdempotency:
    def _make_spec(self, collection: Path, filenames: list[str]) -> Path:
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            collection.name,
            chunks,
            artist="Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )
        _unique_spec_inplace(spec)
        spec_path = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec))
        return spec_path

    def test_second_build_without_force_raises_config_error(self, tmp_path, monkeypatch):
        """2 回目 build（--force なし）→ ConfigError."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=2)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        # 1 回目
        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        # 2 回目（--force なし）→ ConfigError で exit 1
        with pytest.raises(SystemExit) as exc_info:
            dp_script.main()
        assert exc_info.value.code == 1

    def test_force_rebuild_succeeds_and_keeps_cover_and_spec(self, tmp_path, monkeypatch):
        """--force で再生成成功かつ cover_art_3000.jpg と spec.json が残存する."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=2)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        spec_path = self._make_spec(collection, filenames)

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        # 1 回目
        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

        # cover_art_3000.jpg を手動作成（--force で保護されることを確認）
        cover_path = collection / DISTROKID_DIRNAME / COVER_ART_FILENAME
        cover_path.write_bytes(b"cover-dummy")

        # 2 回目（--force あり）
        sys.argv = [
            "yt-distrokid-prepare",
            "build",
            "--spec",
            str(spec_path),
            str(collection),
            "--force",
        ]
        dp_script.main()

        # spec.json と cover_art_3000.jpg は残存
        assert spec_path.is_file()
        assert cover_path.is_file()
        assert cover_path.read_bytes() == b"cover-dummy"


# ---------------------------------------------------------------------------
# 9. verify サブコマンド
# ---------------------------------------------------------------------------


class TestVerify:
    """verify サブコマンドの happy path とエラーケース."""

    def _build_collection(self, tmp_path: Path, monkeypatch) -> Path:
        """build まで実行したコレクションを返す."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=4)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            collection.name,
            chunks,
            artist="Test Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )
        _unique_spec_inplace(spec)
        spec_path = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(spec))

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()
        return collection

    def test_verify_happy_path(self, tmp_path, monkeypatch):
        """happy path: cover + workflow-state あり → exit 0（例外なし）."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = self._build_collection(tmp_path, monkeypatch)

        # cover_art_3000.jpg を生成
        from PIL import Image

        cover_path = collection / DISTROKID_DIRNAME / COVER_ART_FILENAME
        img = Image.new("RGB", (3000, 3000))
        img.save(str(cover_path), format="JPEG")

        # workflow-state.json
        ws = collection / "workflow-state.json"
        ws.write_text(json.dumps({"planning": {"publish_target_at": "2026-08-01"}}))

        # load_config monkeypatch
        fake_cfg = _fake_config()
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: fake_cfg,
        )

        sys.argv = ["yt-distrokid-prepare", "verify", str(collection)]
        dp_script.main()  # 例外なし

    def test_verify_without_cover_raises(self, tmp_path, monkeypatch):
        """cover_art_3000.jpg が欠落 → ConfigError で exit 1."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = self._build_collection(tmp_path, monkeypatch)

        fake_cfg = _fake_config()
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: fake_cfg,
        )

        sys.argv = ["yt-distrokid-prepare", "verify", str(collection)]
        with pytest.raises(SystemExit) as exc_info:
            dp_script.main()
        assert exc_info.value.code == 1

    def test_verify_wrong_cover_size_raises(self, tmp_path, monkeypatch):
        """cover_art_3000.jpg のサイズが不正 → ConfigError で exit 1."""
        from PIL import Image

        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = self._build_collection(tmp_path, monkeypatch)

        # 間違ったサイズの JPEG
        cover_path = collection / DISTROKID_DIRNAME / COVER_ART_FILENAME
        img = Image.new("RGB", (1000, 1000))
        img.save(str(cover_path), format="JPEG")

        fake_cfg = _fake_config()
        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.load_config",
            lambda: fake_cfg,
        )

        sys.argv = ["yt-distrokid-prepare", "verify", str(collection)]
        with pytest.raises(SystemExit) as exc_info:
            dp_script.main()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------


def _unique_spec_inplace(spec: dict) -> None:
    """needs_unique なトラックにバリエーションサフィックスを付けてユニーク化する（テスト用）."""
    seen: dict[str, int] = {}
    for _disc_idx, disc in enumerate(spec.get("discs", [])):
        for track in disc.get("tracks", []):
            title = track["title"]
            if track.get("needs_unique"):
                count = seen.get(title, 0)
                if count > 0:
                    track["title"] = f"{title} — Reprise {count}"
                seen[title] = count + 1
                track.pop("needs_unique", None)
            else:
                seen[title] = seen.get(title, 0) + 1


# ---------------------------------------------------------------------------
# 10. spec.json canonical 書き込み（#941）
# ---------------------------------------------------------------------------


class TestBuildWritesCanonicalSpec:
    """build サブコマンドが canonical 30-distrokid/spec.json を書くことを検証する（#941）."""

    def _run_build(self, collection: Path, spec_path: Path, monkeypatch) -> None:
        """build を実行するヘルパー."""
        from youtube_automation.scripts import distrokid_prepare as dp_script

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )
        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(spec_path), str(collection)]
        dp_script.main()

    def _prepare(self, tmp_path: Path, n_tracks: int = 2) -> tuple[Path, Path]:
        """コレクションと外部 spec パスを用意して返す."""
        collection = _make_collection(tmp_path, n_tracks=n_tracks)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            collection.name,
            chunks,
            artist="Test Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )
        _unique_spec_inplace(spec)
        # canonical パス外（/tmp 相当）に spec を置く（canonical 外パス指定のテスト）
        external_spec_path = tmp_path / "external-spec.json"
        external_spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        return collection, external_spec_path

    def test_build_writes_canonical_spec_json(self, tmp_path, monkeypatch):
        """Given --spec に canonical パス外のファイルを指定
        When build を実行する
        Then 30-distrokid/spec.json が書き込まれる（canonical パス書き込み）。
        (#941)
        """
        collection, external_spec_path = self._prepare(tmp_path)

        self._run_build(collection, external_spec_path, monkeypatch)

        canonical = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        assert canonical.is_file()

    def test_build_canonical_spec_content_matches_loaded_spec(self, tmp_path, monkeypatch):
        """Given 外部 spec ファイルで build
        When 完了後に 30-distrokid/spec.json を read_collection_spec で読む
        Then 外部 spec の内容と一致する。
        (#941)
        """
        collection, external_spec_path = self._prepare(tmp_path)
        original_spec = json.loads(external_spec_path.read_text(encoding="utf-8"))

        self._run_build(collection, external_spec_path, monkeypatch)

        result = read_collection_spec(collection / DISTROKID_DIRNAME)

        assert result is not None
        assert result["artist"] == original_spec["artist"]
        assert result["discs"] == original_spec["discs"]

    def test_build_force_rewrites_canonical_spec(self, tmp_path, monkeypatch):
        """Given 1 回目 build で spec.json が書かれた後、--force で再 build
        When 2 回目の build を実行する
        Then spec.json が更新される（再書き込み冪等）。
        (#941)
        """
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection, external_spec_path = self._prepare(tmp_path)

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        # 1 回目
        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(external_spec_path), str(collection)]
        dp_script.main()

        canonical = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        assert canonical.is_file()
        first_mtime = canonical.stat().st_mtime

        # 少し待って mtime を変化させる
        import time

        time.sleep(0.05)

        # 2 回目（--force）
        sys.argv = [
            "yt-distrokid-prepare",
            "build",
            "--spec",
            str(external_spec_path),
            str(collection),
            "--force",
        ]
        dp_script.main()

        second_mtime = canonical.stat().st_mtime
        # 2 回目の build で spec.json が更新された（mtime が変わった）
        assert second_mtime >= first_mtime

    def test_refused_build_does_not_touch_canonical_spec(self, tmp_path, monkeypatch):
        """Given 1 回目 build 済み、外部 spec の内容を変更して --force なしで再 build
        When 冪等性チェックで build が拒否される（exit 1）
        Then canonical spec.json は 1 回目の内容のまま変更されない
        （build が拒否されたらディスク上の状態を一切変更しない）。
        (#941)
        """
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection, external_spec_path = self._prepare(tmp_path)

        self._run_build(collection, external_spec_path, monkeypatch)

        canonical = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        first_content = canonical.read_text(encoding="utf-8")

        # 外部 spec の artist を変更して --force なしで再 build → 拒否される
        modified = json.loads(external_spec_path.read_text(encoding="utf-8"))
        modified["artist"] = "Changed Artist"
        external_spec_path.write_text(json.dumps(modified, ensure_ascii=False, indent=2), encoding="utf-8")

        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(external_spec_path), str(collection)]
        with pytest.raises(SystemExit) as exc_info:
            dp_script.main()
        assert exc_info.value.code == 1

        # 拒否された build は canonical spec を書き換えない
        assert canonical.read_text(encoding="utf-8") == first_content

    def test_build_canonical_path_spec_self_overwrite_ok(self, tmp_path, monkeypatch):
        """Given --spec に canonical パス（30-distrokid/spec.json）を直接指定
        When build を実行する
        Then 自己上書きで問題なく完了する（canonical と同一パスでも OK）。
        (#941)
        """
        from youtube_automation.scripts import distrokid_prepare as dp_script

        collection = _make_collection(tmp_path, n_tracks=2)
        music_dir = collection / INDIVIDUAL_MUSIC_DIRNAME
        filenames = sorted(f.name for f in music_dir.glob("*.mp3"))
        chunks = split_tracks(filenames)
        spec = build_draft_spec(
            collection.name,
            chunks,
            artist="Test Artist",
            language="English",
            genre_primary="Electronic",
            genre_secondary=None,
        )
        _unique_spec_inplace(spec)

        # canonical パス = 30-distrokid/spec.json に spec を書く
        canonical = collection / DISTROKID_DIRNAME / SPEC_FILENAME
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr(
            "youtube_automation.scripts.distrokid_prepare.probe_duration",
            lambda p: 199.0,
        )

        # canonical パス自体を --spec に渡す（自己上書き）
        sys.argv = ["yt-distrokid-prepare", "build", "--spec", str(canonical), str(collection)]
        dp_script.main()  # 例外なし

        # spec.json が残存している
        assert canonical.is_file()
        result = read_collection_spec(collection / DISTROKID_DIRNAME)
        assert result is not None
