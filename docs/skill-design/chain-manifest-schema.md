# チェーン定義マニフェスト schema

## 目的と採用方式

スキルチェーンの順序制御を、同梱デフォルトのマニフェストと下流チャンネルの
`config/channel/workflow.json` に分けて宣言する。インタープリタ skill はこの
宣言を読み、判定 script の結果に従って子 skill へ一段ずつ委譲する薄い層とする。
子 skill の内部ロジックは再実装しない。

この方式はオーケストレーション調査の案 A に従う。hooks は Codex と takt で
実行されず、ヘッドレス runner は対話型の承認ゲートを扱えないため、いずれも
この schema の実行方式には採用しない。マニフェストは Claude Code / Codex 共用の
テキスト指示と reference script だけを前提にする。

この文書は schema の契約を定める設計成果物である。インタープリタ、manifest
loader、下流 config の新規キー、および既存 `/wf-next` の書き換えは実装しない。

## 用語と配置

- **同梱デフォルト**: `yt-skills sync` で配布される完全なチェーン定義。step 列、
  成果物、ゲート、冪等判定をすべて持つ。
- **チャンネル上書き**: 下流リポジトリの `config/channel/workflow.json` に置く
  チェーン固有の宣言。共用の SKILL.md を編集せず、チャンネルごとのゲートや
  運用オプションだけを変える。
- **前提成果物** / **出力成果物**: 実行対象チャンネルのルートからの相対 glob。
  glob はファイル存在の候補を表すだけで、鮮度や完了の最終判定はしない。
- **冪等判定 script**: `references/` 配下の script への相対参照。再実行時に
  step を実行・再開・skip のいずれにするかを決め、必要なら既存 state を更新する。

## JSON Schema

次の JSON Schema は、完全定義の `bundledManifest` とチャンネル上書きの
`channelWorkflowFile` を同じ文書で定義する。`steps` は JSON array の順序で実行する。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://youtube-automation.dev/schemas/chain-manifest.schema.json",
  "title": "Skill chain manifest",
  "oneOf": [
    { "$ref": "#/$defs/bundledManifest" },
    { "$ref": "#/$defs/channelWorkflowFile" }
  ],
  "$defs": {
    "artifactGlob": {
      "type": "string",
      "minLength": 1,
      "pattern": "^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$)).+$",
      "description": "Glob relative to the target channel root."
    },
    "artifactGlobs": {
      "type": "array",
      "items": { "$ref": "#/$defs/artifactGlob" },
      "uniqueItems": true
    },
    "approvalGate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["enabled"],
      "properties": {
        "enabled": {
          "type": "boolean",
          "default": false,
          "description": "Whether the interpreter asks for approval immediately before this step."
        },
        "configPath": {
          "type": "string",
          "minLength": 1,
          "description": "Optional config/channel/workflow.json path that supplies enabled."
        }
      }
    },
    "idempotency": {
      "type": "object",
      "additionalProperties": false,
      "required": ["script"],
      "properties": {
        "script": {
          "type": "string",
          "pattern": "^references/(?!\\.\\.(?:/|$))(?!.*?/\\.\\.(?:/|$)).+",
          "description": "Reference-script path relative to the owning skill."
        }
      }
    },
    "step": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id",
        "skill",
        "prerequisiteArtifacts",
        "outputArtifacts",
        "approvalGate",
        "idempotency"
      ],
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9-]*$",
          "description": "Stable step identifier, unique within its chain."
        },
        "skill": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9-]*$",
          "description": "Delegated skill name without a leading slash."
        },
        "prerequisiteArtifacts": {
          "$ref": "#/$defs/artifactGlobs",
          "description": "Artifacts that must be available before the delegated skill runs."
        },
        "outputArtifacts": {
          "$ref": "#/$defs/artifactGlobs",
          "description": "Artifacts expected after the delegated skill completes; an empty array means no file output is required."
        },
        "approvalGate": { "$ref": "#/$defs/approvalGate" },
        "idempotency": { "$ref": "#/$defs/idempotency" }
      }
    },
    "bundledManifest": {
      "type": "object",
      "additionalProperties": false,
      "required": ["chainId", "steps"],
      "properties": {
        "chainId": {
          "type": "string",
          "pattern": "^[a-z][a-z0-9-]*$",
          "description": "Identifier used to select channel overrides."
        },
        "steps": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/step" },
          "description": "Ordered execution sequence."
        }
      }
    },
    "wfNextChannelOverride": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "approval_gates": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "audio": { "type": "boolean", "default": false },
            "upload": { "type": "boolean", "default": false }
          }
        },
        "skip_manual_mastering": { "type": "boolean", "default": false }
      }
    },
    "genericChainOverride": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "approval_gates": {
          "type": "object",
          "propertyNames": {
            "pattern": "^[a-z][a-z0-9-]*$"
          },
          "additionalProperties": { "type": "boolean" },
          "description": "Per-step approvalGate.enabled overrides for this chain."
        }
      }
    },
    "channelWorkflowFile": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "workflow": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "wf_next": { "$ref": "#/$defs/wfNextChannelOverride" }
          },
          "patternProperties": {
            "^(?!wf_next$)[a-z][a-z0-9-]*$": {
              "$ref": "#/$defs/genericChainOverride"
            }
          }
        }
      }
    }
  }
}
```

### フィールド

| スキーマ | フィールド | 必須 | 説明 |
|---|---|---:|---|
| `bundledManifest` | `chainId` | Yes | 同梱デフォルトと channel override を対応付ける stable ID。 |
| `bundledManifest` | `steps` | Yes | 実行順を持つ 1 件以上の step 配列。 |
| document | `$schema` / `$id` / `title` | Yes | JSON Schema draft、schema の識別子、schema の表題。 |
| document | `oneOf` | Yes | 完全定義または channel workflow file のいずれかとして検証する。 |
| document | `$defs` | Yes | 以下の再利用可能な sub-schema 群。 |
| `step` | `id` | Yes | チェーン内で一意な step ID。 |
| `step` | `skill` | Yes | 委譲先 skill 名。先頭の `/` は付けない。 |
| `step` | `prerequisiteArtifacts` | Yes | 実行前に確認するチャンネルルート相対 glob。入力が不要な step は `[]`。 |
| `step` | `outputArtifacts` | Yes | 実行後に期待するチャンネルルート相対 glob。ファイル出力を契約にしない step は `[]`。 |
| `step` | `approvalGate.enabled` | Yes | step 直前の承認要否。schema の default は必ず `false`。 |
| `step` | `approvalGate.configPath` | No | `enabled` のチャンネル上書き元となる `workflow.json` 内のパス。 |
| `step` | `idempotency.script` | Yes | 判定を委譲する owning skill の `references/` 内 script。判定ロジックを manifest に埋め込まない。 |
| `channelWorkflowFile` | `workflow.wf_next` | No | 既存 `/wf-next` 用 channel override。完全な step 定義ではない。 |
| `channelWorkflowFile` | `workflow.<chain_id>`（`wf_next` 以外） | No | `chainId` と同名の generic chain override。chain 固有の専用 schema がある場合を除き、許可するキーは `approval_gates` のみ。 |
| `genericChainOverride` | `approval_gates.<step_id>` | No | 対応する同梱 step の `approvalGate.enabled` を上書きする boolean。`step_id` は英小文字で始まる kebab-case。 |
| `wfNextChannelOverride` | `approval_gates.audio` | No | 音源確定 step の承認。未指定時は `false`。 |
| `wfNextChannelOverride` | `approval_gates.upload` | No | upload step の承認。未指定時は `false`。 |
| `wfNextChannelOverride` | `skip_manual_mastering` | No | raw master を最終音源として直採用する既存の運用オプション。未指定時は `false`。 |

`default` は JSON Schema の注釈であり、値の注入を行うものではない。将来の
interpreter / loader は、解決済みの値を使用する責務を持つ。

`steps[*].id` の重複は JSON Schema の `uniqueItems` では表現できない（step object
全体の一致しか検査できない）ため、構造検証の後に semantic validation を必ず行う。
interpreter / loader は、同じ `id` を持つ step が 2 件以上あれば manifest を reject
し、override の解決または skill の実行へ進んではならない。この検証により、
`approval_gates.<step_id>` の上書き先は常に一意になる。

## 解決順序

1. 同梱 `bundledManifest` を schema で構造検証し、`steps[*].id` の重複を semantic
   validation で reject してから、チェーンの step 列・成果物・gate の既定値・
   idempotency script を得る。`approvalGate.enabled` は完全定義の必須 field なので、
   同梱 manifest に未指定のままにしてはならない。
2. `chainId` が `wf-next` の既存チェーンは、専用の
   `config/channel/workflow.json::workflow.wf_next` を `$defs.wfNextChannelOverride`
   として解決する。既存キーの意味は「`wf-next` との整合検証」の対応表に従う。
3. それ以外の `chainId` は、`workflow.<chain_id>` を
   `$defs.genericChainOverride` として解決する。各
   `approval_gates.<step_id>` は、同梱 manifest 内で同じ `id` を持つ step の
   `approvalGate.enabled` だけを上書きする。
4. override に存在しない field は同梱 manifest の明示値を使う。各 step の
   `approvalGate.enabled` は同梱 manifest で必ず明示し、承認なしの既定値には
   `false` を記載する。

したがって下流側に `workflow.json`、`workflow.<chain_id>`、または
`approval_gates` が存在しなくても、承認なしの既定動作（全自動）が維持される。
この解決処理自体は後続 issue の interpreter / loader の責務であり、本 issue では
実装しない。

`genericChainOverride` は構造を検証し、対象 manifest を読む interpreter / loader は
`chain_id` と `step_id` が実在することを検証する。存在しない ID を無視して既定値へ
fallback してはならない。chain 固有の運用オプションが必要になったときは、
`wfNextChannelOverride` と同様に専用 override schema を追加してから許可する。

## `wf-next` との整合検証

`config/channel/workflow.json::workflow.wf_next` は `$defs.wfNextChannelOverride`
の一インスタンスである。これは同梱された `/wf-next` の完全な step 列を置換せず、
チャンネル別に既存の gate と運用オプションを上書きする。

| 既存キー | schema のフィールド | `/wf-next` 内の対象 | 既定値 |
|---|---|---|---:|
| `workflow.wf_next.approval_gates.audio` | `wfNextChannelOverride.approval_gates.audio` → 音源確定 step の `approvalGate.enabled` | `prepared` phase 2-B。最終 master 候補を `assets.master_audio` に採用し、`phase: "mastered"` にする直前。 | `false` |
| `workflow.wf_next.approval_gates.upload` | `wfNextChannelOverride.approval_gates.upload` → upload step の `approvalGate.enabled` | `mastered` phase 3-B。`/video-upload` の直前。 | `false` |
| `workflow.wf_next.skip_manual_mastering` | `wfNextChannelOverride.skip_manual_mastering` | `prepared` phase 2-B で最終候補がないとき、`assets.raw_master` を `assets.master_audio` として直採用するか。 | `false` |

この三つは既存の `workflow.wf_next` object をラップ、改名、または変換せずに説明する。
既存 loader は三値を boolean として読み、未指定時はすべて `false` にする。

`/wf-next` の再開判定は既存の `workflow-state.json` の `assets` と `phase` が担う。
完了済みの asset は skip し、`phase: "publishing"` で中断した場合は未完了 step から
再開する。`wf-next/references/master_audio_transition.py` は音源確定 2-B の候補選択、
承認結果の検証、`assets.master_audio` と `phase` の更新を担う。今回の schema は
これらの state schema、step 列、script の責務を変更しない。

## analytics 初期マニフェスト例

以下は後続の `/analytics-run` issue が同梱デフォルトの初期値として転記する完全な
`bundledManifest` 例である。各判定 script は後続 issue で `references/` に実装する。
`report` は既存レポートを表示する read-only 経路なので、追加ファイル出力を要求しない。

```json
{
  "chainId": "analytics",
  "steps": [
    {
      "id": "collect",
      "skill": "analytics-collect",
      "prerequisiteArtifacts": [],
      "outputArtifacts": ["data/analytics_data_*.json"],
      "approvalGate": {
        "enabled": false,
        "configPath": "workflow.analytics.approval_gates.collect"
      },
      "idempotency": {
        "script": "references/analytics-chain-state.py"
      }
    },
    {
      "id": "analyze",
      "skill": "analytics-analyze",
      "prerequisiteArtifacts": ["data/analytics_data_*.json"],
      "outputArtifacts": [
        "reports/analysis_*.md",
        "reports/analysis_*.json"
      ],
      "approvalGate": {
        "enabled": false,
        "configPath": "workflow.analytics.approval_gates.analyze"
      },
      "idempotency": {
        "script": "references/analytics-chain-state.py"
      }
    },
    {
      "id": "report",
      "skill": "analytics-report",
      "prerequisiteArtifacts": ["reports/analysis_*.md"],
      "outputArtifacts": [],
      "approvalGate": {
        "enabled": false,
        "configPath": "workflow.analytics.approval_gates.report"
      },
      "idempotency": {
        "script": "references/analytics-chain-state.py"
      }
    }
  ]
}
```

analytics は外部反映をしないため、三 step とも `approvalGate.enabled: false` を初期値に
する。収集・分析の既存鮮度判定と将来の再実行判定は、manifest の glob だけでなく
reference script が担う。

### analytics のチャンネル上書きと解決例

次は analytics の `analyze` step だけに承認を求める channel override である。
`workflow.analytics` は `chainId: "analytics"` に対応し、`wf_next` 以外のため
`$defs.genericChainOverride` で検証する。

```json
{
  "workflow": {
    "analytics": {
      "approval_gates": {
        "analyze": true
      }
    }
  }
}
```

この override を同梱 analytics manifest と解決すると、`collect` と `report` は同梱の
`false` のまま、`analyze` だけが `true` になる。`workflow.analytics` が存在しない
ときは、三 step とも同梱 default の `false` を使う。
