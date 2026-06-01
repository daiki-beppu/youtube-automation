# ADR-001: thumbnail スキルへの imagegen Shared prompt schema 導入

- **Status**: Accepted (試験導入のみ・実本番フローは未接続)
- **Date**: 2026-06-01
- **Related**: issue #654 / PR #651 (#650) / `docs/skill-design/thumbnail-codex-imagegen-diff-report.md`
- **Stakeholders**: thumbnail スキル保守者

## Context

PR #651（issue #650）で `.claude/skills/thumbnail/SKILL.md` を OpenAI codex 公式
`imagegen` SKILL.md の構造へ部分準拠させた。差分レポート
（`docs/skill-design/thumbnail-codex-imagegen-diff-report.md`）では 20 項目を
「寄せる/維持/一部寄せる」で判定し、19 項目は実装済みまたは永続維持と確定した。

唯一残った「**提案 5: Shared prompt schema の導入（差分 E-2）**」だけが
「**維持する（ただし将来的に寄せる余地あり）**」と判定されていた。
判定理由:

- **メリット**: imagegen の 14 項目スキーマに揃えると Codex が prompt を
  構造化しやすく、他スキル（masterup / suno / lyria 等）との整合性も向上する。
- **デメリット**: 現在の手順型記述（skill-config の YAML 値を埋める方式）は
  チャンネル設定と密結合しており、スキーマ形式への移行には skill-config との
  対応マッピングが必要で移行コストが高い。

issue #654 は将来検討用に立てられたが（`takt:none`）、本 issue で
**設計フェーズの 1 ステップ目**として bridge 層 + 対応表 + ADR を確定する。

## Decision

**部分採用**: imagegen の 14 項目 Shared prompt schema を **試験導入レイヤ**
として提供する。実本番のプロンプト構築フローは触らない。

### 採用範囲

| 採否 | 項目 | 配置 |
|---|---|---|
| ✅ 採用 | 14 項目 `PromptSchema` dataclass | `src/youtube_automation/utils/image_provider/prompt_schema.py` |
| ✅ 採用 | `from_skill_config()` bridge（既存 `image_generation.gemini.*` キーから 14 項目へ機械マッピング） | 同上 |
| ✅ 採用 | `render()` で imagegen 互換の `Label: value` テキスト出力 | 同上 |
| ✅ 採用 | 対応マッピング表（14 項目 × config キー） | `.claude/skills/thumbnail/references/prompt-schema.md` |
| ✅ 採用 | bridge の単体テスト | `tests/test_prompt_schema.py` |
| ❌ 不採用 | 実本番フロー（`composition.py` / `scripts/generate_image.py`）の schema 化 | gating: skill-config 管理見直し epic 待ち |
| ❌ 不採用 | `config.default.yaml` のキー再編・schema 寄せ | gating: 同上 |
| ❌ 不採用 | `image_generation.gemini.diff_prompt_template` の撤去・置換 | gating: 同上 |
| ❌ 不採用 | TTP / Two-Phase / 視認性検証 / 固定キャラ / stock 退避 等の本体改修 | issue #654 §スコープ外（不変・refactor 対象外） |

### 段階移行パス

`references/prompt-schema.md` の「段階移行パスと並存設計」に明示。要点:

1. **試験フェーズ（本 ADR で確定）**: bridge ヘルパ + 対応表 + ADR のみ。
2. **opt-in フェーズ**: feature flag で並存運用。
3. **default 切替**: 観測良好なら default を schema 経由に。
4. **legacy 撤去**: skill-config 管理見直し epic と同期。

ステップ 2 以降は本 ADR では **不採用**。issue #654 §制約「トリガ条件」
（`skill-config の管理方法を見直すタイミング`）が発火するまで保留する。

## Consequences

### Positive

- imagegen 14 項目スキーマとの対応関係が **対応マッピング表** として
  明文化され、将来の移行コスト見積もりが格段に容易になる。
- bridge ヘルパが揃ったことで、外部スキル（codex 経路 / masterup 等）が
  prompt を構造化したい場合に `from_skill_config()` を経由して使える。
- TTP / Two-Phase / 視認性検証 / 固定キャラ / stock 退避 / 複数プロバイダー
  切替・コレクション連携など、thumbnail 独自機能の振る舞いは
  **完全に温存**される（実本番フロー未接続のため）。
- 既存 `tests/test_thumbnail_skill_assets.py` 4 件は影響を受けず、本 PR で
  も pass を維持する。

### Negative

- 実本番フロー未接続のため、本 ADR 時点では **実 prompt 改善効果はゼロ**。
  bridge 経由の生成試験は別 issue（`takt:default` で再起票）で行う。
- bridge の対応マッピングは現在の `gemini` ブロックのみを参照する。
  `openai` / `gemini_cli` / `codex` provider 個別のキーは未マッピング。
  provider 横断の schema 化は将来課題。
- 14 項目のうち `Lighting` は `config.default.yaml` に対応キーが無く、
  常に `None`。チャンネル側で必要なら `dataclasses.replace()` で明示マージ
  する運用になる（自動マッピングは不可）。

### Neutral

- SKILL.md には 1 行の参照リンク追記のみ（`references/prompt-schema.md` への
  pointer）。既存セクション順序・固定化テストの対象テキストには触れない。
- `image_provider.__init__` の `__all__` に `PromptSchema` / `prompt_schema`
  を追加するため、`from youtube_automation.utils.image_provider import ...`
  経由のインターフェースが拡張される（破壊的変更なし）。

## Trigger（再評価条件）

以下のいずれかが発火した時点で、本 ADR を Superseded に切り替えて次の
段階移行 ADR（opt-in フェーズ）を起こす:

- **skill-config の管理方法見直し epic** が起票されて着手される
- thumbnail 以外のスキル（masterup / suno / lyria 等）で同様の 14 項目
  schema bridge を必要とする要件が複数発生する
- imagegen 14 項目スキーマ自体が大きく改訂され、対応表を再構築する必要が
  発生する

## References

- issue #654: `refactor(thumbnail): Shared prompt schema 導入を将来検討（imagegen 準拠）`
- PR #651（issue #650）: `[#650] issue-650-refactor-thumbnail-c`（imagegen 部分準拠）
- 差分レポート: `docs/skill-design/thumbnail-codex-imagegen-diff-report.md`
- 対応マッピング表: `.claude/skills/thumbnail/references/prompt-schema.md`
- imagegen 公式 SKILL.md:
  `https://raw.githubusercontent.com/openai/codex/main/codex-rs/skills/src/assets/samples/imagegen/SKILL.md`
