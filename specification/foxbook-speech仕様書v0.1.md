# foxbook-speech 仕様書 v0.1

- 文書バージョン: 0.1
- 作成日: 2026-11-16
- 状態: 一部実装（Whisper経路とsystemd unit templateは自動試験済み、実機・ReazonSpeechは未実装）
- 対象: Linux / Firefox Native Messaging / Unix domain socket / Whisper / ReazonSpeech

## 1. 目的と非目標

foxbook-speechは、許可されたFoxbook Firefox拡張にローカル音声認識テキストを返す共通基盤である。単一の論理serviceがマイク利用と認識資源を調停する。

本仕様の範囲は、録音、音声変換、ローカル認識、状態通知、取消、回収である。認識結果の編集、履歴・定型文、自然言語コマンドの意味解釈、コマンド実行、Focodex・OSK・端末制御・ローカルファイル操作は範囲外とする。

## 2. 構成

```text
許可済み Firefox 拡張
  → foxbook_speech Native Messaging Host
  → 所有者限定 Unix domain socket
  → foxbook-speech service
  → arecord / ffmpeg / Whisper CLI / ReazonSpeech Worker
```

Native Messaging Hostは接続ごとに起動される軽量adapterであり、録音・モデル状態を保持しない。serviceはユーザー単位で一つだけ稼働し、全adapterからの要求を処理する。初期実装ではsystemd --userによりserviceを起動し、socket activationの採否はSurface実測後に決める。

adapterとservice間のIPCはUTF-8の改行区切りJSONとする。adapterは接続直後に`{"type":"open","extensionId":"…"}`を一度だけ送る。serviceは許可済みIDなら`{"type":"opened","version":1}`を返し、以後は共通音声API v1だけを処理する。この接続開始メッセージは内部IPC専用であり、Firefox拡張へは転送しない。

## 3. 固定された資源と設定

- 録音はservice側が固定した入力設定で行い、初期上限は30秒とする。
- 変換は16 kHz、モノラル、PCM WAVへ固定する。
- `whisper` と `reazonspeech_k2` だけをエンジン名として受け入れる。モデル・実行ファイル・言語・端末設定のパスはservice設定で固定し、拡張は指定できない。初期実装の標準許可設定はWhisperだけとし、ReazonSpeechはWorker実装後に有効化する。
- Whisperは要求ごとのCLI起動を基本とする。ReazonSpeechはengine設定ごとのWorkerをservice側で管理し、互換性・メモリ上限を満たす範囲で再利用する。
- Surface固有のマイク補正は端末識別を含むservice側設定で明示有効にした場合だけ実施する。他端末に同じミキサー操作を適用しない。

## 4. 認可と接続所有権

- Native Messaging manifestの`allowed_extensions`には固定の拡張IDだけを登録する。
- adapterはFirefoxから渡される起動元拡張IDを既知の許可リストと照合する。Host manifestの想定外パス、引数不足、許可外IDではserviceへ接続せず終了する。
- adapterはHost接続ごとに一つのUnix socket接続を開く。serviceはそのsocket接続を一つの内部sessionとして扱い、ランダムな`sessionId`を内部だけで発行する。`sessionId`はFirefoxへ公開せず、要求本文の`clientId`も受理しない。
- `recordingId`はserviceが発行し、所有sessionへ束縛する。`stop_recording`と`cancel_recording`は、その`recordingId`を所有する同一sessionだけが要求できる。結果・状態イベントも所有socketだけへ返す。
- Unix socketは当該Linuxユーザーだけが扱えるruntime directory内へ作る。同一Linuxユーザーの任意プロセスを敵対者とみなす認証は本仕様の範囲外であり、Firefox拡張の認可境界はNative Messaging manifestとadapterの起動元ID検証で維持する。
- Native Messagingとservice IPCの入力はJSONオブジェクトだけとし、サイズ上限は1 MiB以下で統一する。未知のキー、未知の操作、未知のエンジンを拒否する。

## 5. 共通音声API v1（案）

すべての要求とイベントは`version: 1`を持つ。各要求の必須キーは`version`と`action`であり、表の「追加本文」に示すキー以外を含めない。初期版では一つのadapter接続に一件だけの操作を許可し、音声データ・任意パス・任意コマンド・`clientId`は含めない。

| 要求 | 追加本文 | 成功時 | 主な拒否 |
| --- | --- | --- | --- |
| `prepare_microphone` | なし | `microphone_prepared` | `BUSY`, `MICROPHONE_PREPARATION_FAILED` |
| `prepare_engine` | `engine` | `engine_prepared` | `UNKNOWN_ENGINE`, `ENGINE_FILES_MISSING` |
| `start_recording` | なし | `started` とservice発行の`recordingId` | `BUSY`, `MICROPHONE_NOT_READY`, `ENGINE_NOT_READY` |
| `stop_recording` | `recordingId` | `stopping`、後続の処理イベント | `NOT_RECORDING`, `STALE_RECORDING` |
| `cancel_recording` | `recordingId` | `cancelled` | `STALE_RECORDING` |
| `get_status` | なし | `status` | `INVALID_REQUEST` |

結果イベントは`result`とし、`recordingId`、`engine`、`engineGeneration`、`text`、`conversionMs`、`modelStartupMs`、`recognitionMs`、`elapsedMs`、`modelName`を含める。エラーは`error`とし、対応する`recordingId`または`null`、固定エラーコード、利用者に表示可能なメッセージを含める。すべてのイベントにも`version: 1`を含める。

Voice Editor移行時に既存要求との相違がある場合は、adapterまたは利用側で明示変換する。変換は一時的な互換措置とし、最終的なAPIの意味を曖昧にしない。

## 6. マイクのリースと状態遷移

serviceの録音要求は次の状態を取る。

```text
idle → recording → stopping → converting → recognizing → idle
                  └──────────────────────────────→ error / cancelled → idle
```

- `prepare_microphone`と選択engineの`prepare_engine`が成功するまで`start_recording`を拒否する。マイク準備はservice全体で直列化し、録音リース中は`BUSY`で拒否する。
- `start_recording`は、マイク・engine準備と所有sessionを原子的に確認してから、全serviceで一件だけの録音リースを作る。リースは`recordingId`、所有session、engine、現在phase、各phaseの期限を持つ。
- リースは`start_recording`から`result`、`error`、`cancelled`のいずれかまで保持する。したがって録音中だけでなく、変換・認識中の新規開始も`BUSY`で拒否する。待ち行列は持たない。
- 初期値の期限は録音30秒、停止待ち2秒、変換10秒、Whisper／ReazonSpeech認識60秒とする。期限超過は該当プロセスを終了し、固定のtimeoutエラーを返す。
- `recordingId`はserviceが生成し、停止・取消・結果・エラーで照合する。別セッションのIDは`STALE_RECORDING`として拒否する。
- adapterのsocket切断、Native Host終了、service停止、録音・変換・認識タイムアウトでは、子プロセスを終了し一時ファイルとリースを回収する。利用側の取消要求だけに依存しない。
- 遅延したイベントは、利用側が`recordingId`とengine世代を照合して破棄できる形式を維持する。

## 7. エンジンの共有単位

- engine選択はsessionごとの準備状態であり、service全体の選択状態ではない。ある利用者の`prepare_engine`や切替が、別利用者の準備済みengineを停止・切替しない。
- `whisper`は固定モデル設定のCLIを要求ごとに起動する。準備は実行ファイル・モデル・設定の検証だけであり、常駐Workerを持たない。
- `reazonspeech_k2`は`engine名 + service側モデル設定revision`をキーに、最大一つのWorkerをserviceが保持する。同じキーへの同時`prepare_engine`は一回のロードに合流させ、ロード完了を待つ全sessionへ状態イベントを返す。
- Workerの`engineGeneration`は作成ごとに増加させる。異常終了、設定revision変更、明示したアイドル解放の後に作り直したWorkerは新しい世代とする。
- ReazonSpeech Workerは最後の利用から5分後に解放する。保持時間とメモリ上限はSurface実測後にservice側設定だけで変更し、ブラウザAPIには公開しない。
- 拡張ごとに利用を許可するengineはservice側許可設定で固定する。要求本文で未知のengineや許可されないengineを指定しても実行しない。

## 8. Voice Editorの二つのPort

Voice Editorは一つの`port`を次の二つへ分割する。

| Port | 接続先 | 担当 | 切断時の扱い |
| --- | --- | --- | --- |
| `speechPort` | `foxbook_speech` | マイク準備、engine準備、録音・停止・取消、状態・認識結果 | 録音中のservice sessionは回収される。録音UIだけを無効化し、手入力・既存編集は維持する。 |
| `libraryPort` | `fox_voice_editor` | `load_library`、`save_library`だけ | ライブラリ未読込・保存失敗は既存と同じく編集開始を抑止し、ローカル状態を勝手に破棄しない。 |

- 接続と再接続、エラー表示、状態変数、メッセージ検証はPortごとに独立させる。片方から受けたイベントをもう片方の状態として扱わない。
- Voice Editorはライブラリの初期読込成功と`speechPort`のマイク・選択engine準備成功の両方を確認してから録音ボタンを有効にする。
- `pagehide`でbfcacheへ入る場合は明示切断しない。`pageshow`時に各Portが切断済みならそのPortだけを再接続する。
- 既存のFocodex配送、FX-OSK、文書ブロック、履歴・定型文のスキーマは変更しない。

## 9. 運用と検証

自動試験では、Native Messagingフレーム、adapterとserviceの接続所有権、擬似コマンドによるWhisperの録音・停止・変換・認識・取消・一時ファイル回収、`BUSY`、socket経由のphase順序を確認済みである。空結果、各タイムアウト、Host切断、service再起動、ReazonSpeechの再利用・異常終了は追加対象とする。

Surface Pro 4では、マイク補正、連続3回以上の録音、初回・継続時の時間、CPU・メモリ、Worker回収、拡張再読み込み後の回復を実機確認する。

## 10. 導入と移行

最初の利用者はfox-voice-editorである。同拡張は`foxbook_speech`へ音声操作を送るPortと、編集履歴・定型文を保存する`fox_voice_editor`へのPortを分離する。編集ブロック、履歴、Focodex配送、FX-OSK連携の契約は変更しない。

共通Hostへ端末制御やファイル操作の権限を統合しない。新しい利用者は本APIで認識テキストを取得し、用途固有のコマンド解釈・実行を自身の責務として実装する。
