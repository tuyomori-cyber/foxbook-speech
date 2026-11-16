# foxbook-speech 仕様書 v0.1

- 文書バージョン: 0.1
- 作成日: 2026-11-16
- 状態: 設計案（未実装）
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

## 3. 固定された資源と設定

- 録音はservice側が固定した入力設定で行い、初期上限は30秒とする。
- 変換は16 kHz、モノラル、PCM WAVへ固定する。
- `whisper` と `reazonspeech_k2` だけをエンジン名として受け入れる。モデル・実行ファイル・言語・端末設定のパスはservice設定で固定し、拡張は指定できない。
- Whisperは要求ごとのCLI起動を基本とする。ReazonSpeechはengine設定ごとのWorkerをservice側で管理し、互換性・メモリ上限を満たす範囲で再利用する。
- Surface固有のマイク補正は端末識別を含むservice側設定で明示有効にした場合だけ実施する。他端末に同じミキサー操作を適用しない。

## 4. 認可と接続所有権

- Native Messaging manifestの`allowed_extensions`には固定の拡張IDだけを登録する。
- adapterはFirefoxから渡される起動元拡張IDを既知の許可リストと照合し、受け付けたHost接続ごとにserviceセッションを作る。
- serviceはUnix socketの接続、adapterが発行した接続識別子、要求IDを対応付ける。本文で申告する`clientId`は認可に使わない。
- socketは当該Linuxユーザー以外から接続できない場所・権限で作る。WebページからsocketまたはHostへ直接到達する経路を作らない。
- Native Messagingとservice IPCの入力はJSONオブジェクトだけとし、サイズ上限は1 MiB以下で統一する。未知のキー、未知の操作、未知のエンジンを拒否する。

## 5. 共通音声API v1（案）

すべての要求とイベントは`version: 1`を持つ。初期版では一つのadapter接続に一件だけの操作を許可し、音声データ・任意パス・任意コマンドは含めない。

| 要求 | 本文 | 成功時 | 主な拒否 |
| --- | --- | --- | --- |
| `prepare_microphone` | `action` | `microphone_prepared` | `BUSY`, `MICROPHONE_PREPARATION_FAILED` |
| `prepare_engine` | `action`, `engine` | `engine_prepared` | `UNKNOWN_ENGINE`, `ENGINE_FILES_MISSING` |
| `start_recording` | `action` | `started` とservice発行の`recordingId` | `BUSY`, `MICROPHONE_NOT_READY`, `ENGINE_NOT_READY` |
| `stop_recording` | `action`, `recordingId` | `stopping`、後続の処理イベント | `NOT_RECORDING`, `STALE_RECORDING` |
| `cancel_recording` | `action`, `recordingId` | `cancelled` | `STALE_RECORDING` |
| `get_status` | `action` | `status` | `INVALID_REQUEST` |

結果イベントは`result`とし、`recordingId`、`engine`、`engineGeneration`、`text`、`conversionMs`、`modelStartupMs`、`recognitionMs`、`elapsedMs`、`modelName`を含める。エラーは`error`とし、対応する`recordingId`または`null`、固定エラーコード、利用者に表示可能なメッセージを含める。

Voice Editor移行時に既存要求との相違がある場合は、adapterまたは利用側で明示変換する。変換は一時的な互換措置とし、最終的なAPIの意味を曖昧にしない。

## 6. 状態と調停

serviceの録音要求は次の状態を取る。

```text
idle → recording → stopping → converting → recognizing → idle
                  └──────────────────────────────→ error / cancelled → idle
```

- `prepare_microphone`と選択engineの`prepare_engine`が成功するまで`start_recording`を拒否する。
- `start_recording`から`result`、`error`、`cancelled`のいずれかまで、serviceは録音リースを一件だけ保持する。新規開始要求は`BUSY`で拒否する。
- `recordingId`はserviceが生成し、停止・取消・結果・エラーで照合する。別セッションのIDは`STALE_RECORDING`として拒否する。
- adapterのsocket切断、Native Host終了、service停止、録音・変換・認識タイムアウトでは、子プロセスを終了し一時ファイルとリースを回収する。利用側の取消要求だけに依存しない。
- 遅延したイベントは、利用側が`recordingId`とengine世代を照合して破棄できる形式を維持する。

## 7. 運用と検証

自動試験は、Native Messagingフレーム、adapterとserviceの接続所有権、単独録音、停止、取消、空結果、各タイムアウト、Host切断、service再起動、`BUSY`、ReazonSpeechの再利用・異常終了を対象とする。

Surface Pro 4では、マイク補正、連続3回以上の録音、初回・継続時の時間、CPU・メモリ、Worker回収、拡張再読み込み後の回復を実機確認する。

## 8. 導入と移行

最初の利用者はfox-voice-editorである。同拡張は`foxbook_speech`へ音声操作を送るPortと、編集履歴・定型文を保存する`fox_voice_editor`へのPortを分離する。編集ブロック、履歴、Focodex配送、FX-OSK連携の契約は変更しない。

共通Hostへ端末制御やファイル操作の権限を統合しない。新しい利用者は本APIで認識テキストを取得し、用途固有のコマンド解釈・実行を自身の責務として実装する。
