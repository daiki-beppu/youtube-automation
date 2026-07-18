# community-helper DOM map

Issue: #1708  
調査日: 2026-07-18  
調査環境: Chrome / YouTube 日本語 UI / チャンネル所有者としてログイン済み

## 結論

現行のコミュニティ投稿作成 UI は `studio.youtube.com` 内にはない。YouTube Studio の
「投稿を作成」は次の YouTube 本体ページへ遷移する。

```text
https://www.youtube.com/channel/<channel-id>/posts?show_create_dialog=1
```

`https://studio.youtube.com/channel/<channel-id>/posts` は調査時点でエラー画面になった。
したがって、後続実装では content script の match を投稿ページ
（`https://www.youtube.com/channel/*/posts*`）へ限定して更新する必要がある。Studio origin だけを
対象にする現在の #1712 の骨格では投稿 UI に注入できない。一方、localhost の投稿 JSON・画像を
`www.youtube.com` origin へ CORS 公開してはならない。extension origin の background/popup が取得し、
typed messaging で content script へ relay する。権限は activeTab + 動的注入を優先し、静的 content
script を使う場合も matches は投稿ページに限定する。

この発見に合わせ、accepted ADR-0019 の対象 origin と fetch 境界も本変更で改訂する。

作成フォームは `ytd-backstage-post-dialog-renderer` 配下の Polymer 要素で構成される。
ただし調査時の DOM は ShadyDOM として document に平坦化されており、open な Shadow Root は
0 個だった。まず通常の `document.querySelector` で解決し、open Shadow DOM の再導入に備えた
再帰走査を fallback として持つのが妥当である。

## 調査時の安全措置

本文の値反映を確認するため、一時的に検証文字列を入力した。操作メニューの schedule 項目は
クリックして日時 panel を開いたが、投稿を確定する `#submit-button button`（panel 表示中の
label は「スケジュールを設定」）はクリックしていない。調査終了時にスケジュール画面を
キャンセルし、本文を空にして `input` event を送信した後、次を確認した。

- 投稿ボタン: `disabled === true` / `aria-disabled === "true"`
- 検証文字列: document 内に 0 件
- 作成フォーム: キャンセル後に折りたたみ状態
- 画像: 1x1 PNG を一時添付し、thumbnail 生成を確認後に作成フォームをキャンセルして 0 件へ戻した
- 日時: 日付を Jul 20, 2026、時刻を 9:15 AM へ一時変更し、選択状態を確認後に取り消した
- 投稿・予約投稿: 作成していない

## セレクタ戦略

すべての検索は、非表示テンプレートの同名要素を避けるため、表示中の
`ytd-backstage-post-dialog-renderer` を起点にする。候補が複数ある場合は表示状態も検査し、
一意に解決できなければ処理を止める。日本語の表示文言や `aria-label` は診断情報には使えるが、
主セレクタには使わない。

| 対象 | 推奨セレクタ | 備考 |
| --- | --- | --- |
| 作成フォーム | `ytd-backstage-post-dialog-renderer` | 表示中の要素を一意に選ぶ |
| 折りたたみ時の起動要素 | `#commentbox-placeholder[role="button"]` | `aria-label` は locale 依存 |
| 投稿 editor | `ytd-commentbox#commentbox #contenteditable-root[contenteditable="true"]` | `div`。textarea/input ではない |
| 画像ボタン | `ytd-commentbox#commentbox #image-button button` | ボタン文言・`aria-label` は locale 依存 |
| 画像 file input | `ytd-commentbox#commentbox #dropzone input[type="file"][name="Filedata"][accept="image/*"]` | hidden input。active commentbox に scope する |
| 画像 thumbnail | `ytd-commentbox#commentbox #thumbnail-images-container ytd-backstage-multi-image-thumbnail-renderer img.thumbnail-image[src]` | `src` なしの hidden template を除外する |
| 操作メニュー | `ytd-commentbox#commentbox #option-menu button` | schedule 入口。重複ボタンは visible/enabled を選ぶ |
| 投稿/予約確定 | `ytd-commentbox#commentbox #submit-button button` | label は通常投稿/予約で変わる |
| 作成キャンセル | `ytd-commentbox#commentbox #footer #cancel-button button` | locale 非依存の ID を使う |
| schedule panel | `ytd-commentbox#commentbox #scheduling-panel ytd-date-time-picker-renderer` | custom component |
| schedule 取消 | `#scheduling-panel #cancel-button-wrapper button` | 投稿確定ボタンとは別 |
| 日付 trigger | `ytd-calendar-date-picker #date-picker` | `tp-yt-paper-button` |
| 日付 text input | `ytd-calendar-date-picker #calendar-dialog #textbox` | native `input[type=text]`、表示形式は locale 依存 |
| 前月/翌月 | `ytd-calendar-date-picker #prev-month button` / `#next-month button` | label は locale 依存 |
| 月コンテナ | `ytd-calendar-date-picker .calendar-month[role="listitem"]` | 内部 label と日セルを組にする |
| 日セル | `.calendar-month .calendar-day:not(.invisible):not(.disabled)` | 日だけでは月を識別できない |
| 時刻 trigger | `ytd-date-time-picker-renderer #time-picker` | `tp-yt-paper-button` |
| 時刻 list | `ytd-date-time-picker-renderer #time-listbox[role="listbox"]` | custom listbox |
| 時刻 option | `#time-listbox tp-yt-paper-item[role="option"]` | 15分刻み、値属性なし |
| timezone | `ytd-date-time-picker-renderer #timezone-picker` | 調査時は現地時間 GMT+0900 |
| visibility 表示 | `#header-default-visibility` | 調査時は固定「公開」 |
| visibility slot | `#access-restrictions-selector` | 調査時は空。切替 UI なし |

## テキスト入力

実要素は次の経路にある contenteditable `div` だった。

```text
ytd-backstage-post-dialog-renderer
  > ytd-commentbox#commentbox
    > div#creation-box
      > ytd-emoji-input#emoji
        > yt-user-mention-autosuggest-input
          > yt-formatted-string#contenteditable-textarea
            > div#contenteditable-root[contenteditable=true]
```

次の操作で Polymer の内部状態まで更新され、空文字時に disabled だった投稿ボタンが enabled に
変わることを確認した。

```ts
editor.focus();
editor.textContent = text;
editor.dispatchEvent(
  new InputEvent("input", {
    bubbles: true,
    inputType: "insertText",
    data: text,
  }),
);
```

単なる `textContent` 代入だけに依存せず、bubbling `InputEvent` を必ず送る。注入後は
`#submit-button button` が enabled になるまで待ち、変化しなければ DOM 変更として失敗させる。
クリア時も空の `textContent` と `inputType: "deleteContentBackward"` の bubbling
`InputEvent` を組み合わせる。

## 画像アップロード

画像ボタンは `#image-button button`、実際の file input はそのボタンではなく
`ytd-backstage-multi-image-select-renderer > #dropzone` 配下にある。ページ全体には hidden
テンプレート由来の同種 input が複数存在したため、表示中の `ytd-commentbox#commentbox` と
`#dropzone` に scope する必要がある。

後続実装では取得した画像 Blob から `File` を作り、`DataTransfer` 経由で `input.files` に設定して
bubbling `change` event を送る。

```ts
const file = new File([blob], filename, { type: blob.type });
const transfer = new DataTransfer();
transfer.items.add(file);
fileInput.files = transfer.files;
fileInput.dispatchEvent(new Event("change", { bubbles: true }));
```

専用の 1x1 PNG で `DataTransfer` + bubbling `change` を実行し、input の File readback と thumbnail
生成を実機確認した。生成された要素は `#thumbnail-images-container` 配下の
`ytd-backstage-multi-image-thumbnail-renderer[selected] img.thumbnail-image[src]` だった。一方、同じ
component の hidden template には `src` のない `img.thumbnail-image` が複数存在した。そのため
単なる preview container の存在や表示状態を成功条件にせず、change 前後で `src` が新しく設定された
thumbnail 要素を識別する。File の filename / MIME readback と、その thumbnail の接続・`src` を組に
して投稿直前まで保持する。確認後は作成フォームをキャンセルし、thumbnail が 0 件で投稿が作成されて
いないことを確認した。

## スケジュール日時

### schedule panel の開き方

本文入力後に `#option-menu button` を開くと、`ytd-menu-popup-renderer` 内に
「投稿のスケジュールを設定」項目が現れた。項目自体には locale-independent な ID や value が
なかったため、表示文言との一致だけを本番コードに埋め込むのは避ける。

推奨戦略は、visible/enabled な操作メニュー項目を列挙し、クリック後に
`#scheduling-panel ytd-date-time-picker-renderer` が現れる項目を探索すること。ただし誤った menu
action を試行クリックするのは危険なので、既知の schedule 文言を日本語・英語の補助条件として
絞り込み、候補が一意でない場合は fail-loud とする。YouTube が schedule 項目に安定属性を追加したら
それを最優先に更新する。

### 日付

日付 UI は `ytd-calendar-date-picker` という custom component である。trigger は
`#date-picker`、開いた dialog 内には native `input#textbox[type=text]` と、仮想スクロールされる
`.calendar-month` / `.calendar-day` がある。日セルに date/value/aria-label はなく、数値だけが
入っていた。月 label は調査時 `Jul 2026` のような locale 依存表示だった。

調査では `#textbox` に `Jul 20, 2026` を設定し、bubbling `input` / `change` event の後に
Enter を送った。dialog が閉じ、trigger が `Jul 19, 2026` から `Jul 20, 2026` へ変わり、
該当月の `.calendar-day.selected` も 20 へ移動し、invalid/error がないことを確認した。ただし
この文字列形式は日本語 UI でも英語月名だったという観測にすぎず、他 locale の契約ではない。

locale-independent な推奨順序:

1. `#date-picker` を開く。
2. 月の移動回数を現在日との差から計算し、`#prev-month` / `#next-month` で対象月へ移動する。
3. `.calendar-container` の表示領域上端と重なる `.calendar-month[role=listitem]` を active month
   として一意に解決し、その中に scope して日番号を選ぶ。仮想リストが複数月を描画するため、
   month label の文言や global な日番号では選ばない。
4. trigger、対象月の `.calendar-day.selected`、エラー不在を検証する。
5. `#textbox` への文字列入力は、受理形式を実機確認済みの locale に限る fallback とする。

日番号だけの global query は別月の同じ日を誤選択するため禁止する。`#textbox` の受理形式も locale
依存なので、後続実装ではブラウザ locale ごとの fixture と実機確認が必要である。active month が
0 件または複数件、あるいは移動回数と trigger の変化が一致しない場合は選択せず停止する。

### 時刻

時刻 UI も native time input ではない。`#time-picker` を開くと
`#time-listbox[role=listbox]` が現れ、96 個の `tp-yt-paper-item[role=option]` が15分刻みで並ぶ。
option に value 属性はなく、表示文字列は `12:00 AM` のような12時間制だった。

調査では96個の option のうち index 37 をクリックし、label が `12:00 AM` から `9:15 AM` へ
変わり、同じ option の `aria-selected` が `true` になることを確認した。この event model は
custom option の click であり、native `input` / `change` event は使用しない。

文字列比較では narrow no-break space や locale の12/24時間制を正規化する必要がある。
より安全なのは `HH:mm` を15分単位の index（`hour * 4 + minute / 15`）へ変換し、listbox 内の
option を DOM 順で選ぶ方法である。分が15分単位でなければ選択前に入力エラーとして止める。
選択後は `#time-label-text` の更新を確認する。

## Shadow DOM

document 内の全要素を走査した結果、`element.shadowRoot` が存在する open Shadow Root は 0 個、
最大深度も 0 だった。HTML には `css-build:shady` コメントがあり、現在の Polymer/ShadyDOM は
通常 DOM に平坦化されている。

後続実装の query helper は次の順序にする。

1. document / 表示中の form root に対して通常 query を行う。
2. 見つからない場合だけ、document と発見済み open Shadow Root を幅優先で再帰走査する。
3. closed Shadow Root は走査不能なので、対象が見つからなければ selector drift として失敗する。

過去の UI を前提に固定した Shadow Root チェーンや、常に `shadowRoot!` を辿る実装は採用しない。

## 公開範囲（optional）

調査したチャンネルでは header に `#header-default-visibility` があり、値は「公開」だった。
切替用とみられる `#access-restrictions-selector` は空で、メンバー限定を選ぶ control は描画されて
いなかった。そのため現時点では公開範囲の自動変更を実装対象にせず、既定表示を診断情報として
読むだけにする。将来 control が描画されるチャンネルで再調査し、この文書を更新する。

## 完了判定と失敗条件

投稿確定は `#submit-button button` だが、今回の調査では destructive action のため押していない。
後続実装ではクリック前に本文・画像 preview・日時表示を再検証し、クリック後は次のいずれかを
完了条件として観測する必要がある。

- 作成フォームが reset / 折りたたみ状態へ戻り、editor が空かつ submit が disabled になる
- 予約投稿一覧に対象投稿を識別できる項目が出現する
- YouTube が明示的な成功通知を表示する

単なる click 完了を投稿成功とは扱わない。セレクタが 0 件または複数件、日時が15分境界外、
注入後も submit が disabled、画像 preview が現れない、成功条件を timeout した場合は、後続投稿へ
進まず fail-loud とする。

## 変更検知時の更新手順

1. `www.youtube.com/channel/<channel-id>/posts?show_create_dialog=1` を実ブラウザで開く。
2. origin、root、editor、file input、schedule/date/time、submit の順に再確認する。
3. 文言ではなく ID・role・DOM 関係を優先して selector を更新する。
4. open Shadow Root の件数と深度を再計測する。
5. この文書、`extensions/shared/community-dom.ts`、DOM fixture test を同じ変更で更新する。
6. 実投稿を伴う確認は専用テスト投稿と明示的な許可がある場合だけ行う。
