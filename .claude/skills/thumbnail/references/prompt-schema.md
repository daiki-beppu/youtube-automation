# imagegen Shared prompt schema bridge（試験導入）

> 試験導入レイヤ。実本番のプロンプト構築フロー（`composition.py` / `scripts/generate_image.py`）
> からは **未接続**。issue #654 で導入。本ファイルは差分レポート
> （`docs/skill-design/thumbnail-codex-imagegen-diff-report.md`）の「提案 5: Shared
> prompt schema の導入（差分 E）」に対応する。設計判断は
> `docs/skill-design/ADR-001-thumbnail-prompt-schema.md` を参照。

## 14 項目スキーマと skill-config キーの対応マッピング

imagegen 公式 SKILL.md の Shared prompt schema は次の 14 項目を持つ:

```
Use case / Asset type / Primary request / Input images / Scene / Subject /
Style / Composition / Lighting / Color / Materials / Text / Constraints / Avoid
```

bridge `youtube_automation.utils.image_provider.prompt_schema.from_skill_config()`
は thumbnail の `config.default.yaml` キーを次のように 14 項目へ流し込む。

| # | imagegen 項目 | 取得元キー | 備考 |
|---|---|---|---|
| 1 | `Use case` | （固定） | `"product-mockup (YouTube thumbnail variant)"` を bridge が常に埋める。imagegen 19 スラグの `product-mockup` に対応（差分 E-1 / SKILL.md L12 と整合） |
| 2 | `Asset type` | （固定） | `"YouTube thumbnail (1280x720, 16:9, JPEG)"` を bridge が常に埋める |
| 3 | `Primary request` | `image_generation.gemini.prompt_prefix` | 空文字は `None` に正規化 |
| 4 | `Input images` | `image_generation.gemini.reference_images.default` | str 1 件 / list 複数件の両方を受け、tuple へ正規化（既存 `normalize_reference_default()` と同セマンティクス） |
| 5 | `Scene` | `composition_rules.environment` + `composition_rules.background` | `". "` で結合。両方未設定なら `None` |
| 6 | `Subject` | `fixed_character.{species, description, outfit, accessories, expression, pose}` + `composition_rules.character_pose` | 設定済みの値のみを `". "` で結合 |
| 7 | `Style` | `image_generation.gemini.style` | 空文字は `None` に正規化 |
| 8 | `Composition` | `composition_rules.character_size` + `composition_rules.character_pose` + `thumbnail_text.copy_position` | `". "` で結合 |
| 9 | `Lighting` | （未マッピング） | `config.default.yaml` に対応キーなし。チャンネル側で必要なら `dataclasses.replace()` で明示マージする |
| 10 | `Color` | `image_generation.gemini.brand_background` + `thumbnail_text.color` | `". "` で結合 |
| 11 | `Materials` | `thumbnail_text.decoration` | 装飾要素を materials に流す |
| 12 | `Text` | `thumbnail_text.{title_format, title_prefix, channel_name, channel_name_style, font.copy, font.genre_tag}` + `composition_rules.text_lines` | 設定済みの値のみを `". "` で結合 |
| 13 | `Constraints` | `composition_rules.text_lines` | 既存 default.yaml の `"タイトルは 2 行以内"` 等が流れる |
| 14 | `Avoid` | `composition_rules.ng_actions` | NG パターン |

未指定キーは `None` / 空 tuple として残り、`render()` 時にスキップされる。

## ブリッジ層 API 仕様

`src/youtube_automation/utils/image_provider/prompt_schema.py` に試験導入。

### `PromptSchema` dataclass（frozen）

14 項目をそのままフィールドとして持つ `@dataclass(frozen=True)`。
全フィールドはデフォルト `None`（`input_images` のみ `()`）。

```python
from youtube_automation.utils.image_provider import PromptSchema

schema = PromptSchema(
    primary_request="A jazz bar at night",
    style="matte painting",
    input_images=("benchmarks/a.jpg", "benchmarks/b.jpg"),
)
```

### `from_skill_config(skill_config: dict) -> PromptSchema`

`load_skill_config("thumbnail")` の戻り値（ネスト dict）から `PromptSchema` を
組み立てる bridge。上記対応マッピング表に従って機械的に項目を埋める。
未設定キーは `None` / 空 tuple として残る。

```python
from youtube_automation.utils.image_provider import prompt_schema
from youtube_automation.utils.skill_config import load_skill_config

schema = prompt_schema.from_skill_config(load_skill_config("thumbnail"))
```

### `render(schema: PromptSchema) -> str`

`PromptSchema` を imagegen 形式の `"Label: value"` 改行区切りテキストへ
レンダリングする。未指定項目はスキップ。

```python
text = prompt_schema.render(schema)
# Use case: product-mockup (YouTube thumbnail variant)
# Asset type: YouTube thumbnail (1280x720, 16:9, JPEG)
# Primary request: A jazz bar at night
# ...
```

## 段階移行パスと並存設計

本 bridge は実本番フロー（`composition.py::apply_composition_rules` /
`scripts/generate_image.py` の prompt 組み立て）から **未接続**。既存の
`diff_prompt_template` ベースの手順型プロンプト構築は完全に温存される。

将来の段階移行は以下の順序を想定する（本 issue のスコープ外、別 epic で着手）:

1. **試験フェーズ**（本 issue）: bridge ヘルパ提供 + 対応表 + ADR のみ。
   実本番フローは触らない。
2. **opt-in フェーズ**: `image_generation.gemini.prompt_schema.enabled: true`
   のような明示フラグで bridge 経由のプロンプト構築を選択可能にする。
   既存 `diff_prompt_template` 経路と並存（feature flag）。
3. **default 切替**: 試験フェーズの観測結果が良ければ default を schema 経由
   に切り替える。`diff_prompt_template` は legacy 経路として残す。
4. **legacy 撤去**: skill-config 全体の管理方法見直し epic と同期して
   `diff_prompt_template` を撤去。

ステップ 2 以降は **skill-config 全体の責務分割・配布経路の見直し**
（issue #654 §制約「トリガ条件」）が発火するまで着手しない。

## 既存独自機能との関係

差分レポートで「維持」と判定された 14 項目（TTP / Two-Phase / 視認性検証 /
固定キャラ / stock 退避 / 複数プロバイダー切替 / コレクション連携 / etc.）
は本 bridge の導入後も振る舞いとして温存される。bridge はあくまで
「skill-config の値を 14 項目へ並べ替えるレイヤ」であり、生成モード
（`single_step` / `two_phase` / `diff_from_reference`）や CTR 最適化フロー
には触れない。
