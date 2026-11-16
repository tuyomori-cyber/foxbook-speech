# foxbook-speech

Foxbook の Firefox 拡張へ、ローカル音声認識を共通機能として提供するための基盤です。Native Messaging Host は Firefox との入出力と許可済み拡張の入口だけを担当し、録音・変換・マイク排他・Whisper／ReazonSpeech の実行は単一のローカルサービスが担当します。

`foxbook_speech` Native Messaging adapter、Unix socket service、Whisper／ReazonSpeechの録音・認識とsystemd --user unitは実装済みです。Voice Editorの二Port移行と、両エンジンの実機録音・Firefox経由の動作を確認しています。Surfaceでの共有service測定などの残作業は[TODO](TODO.md)を参照してください。

## 責務

- `foxbook_speech` Native Messaging Host の登録・要求検証・サービスへの中継
- ユーザー単位の音声サービス、Unix domain socket、systemd --user の運用
- マイク利用の排他、録音・変換・取消・タイムアウト・一時ファイルの回収
- 固定されたローカル設定による Whisper と ReazonSpeech の実行・Worker管理
- 共通音声API、導入手順、自動試験と実機試験

認識テキストの編集、履歴・定型文、音声コマンドの意味解釈、Focodex／OSK連携、端末制御やファイル操作は担当しません。

## 構成

```text
Firefox 拡張
  → connectNative("foxbook_speech")
  → 接続ごとの Native Messaging Host adapter
  → 所有者限定 Unix domain socket
  → 単一の foxbook-speech service
  → マイク / Whisper CLI / ReazonSpeech Worker
```

Native Messaging Host のコードと登録名は一つですが、Firefox は接続ごとにHostプロセスを起動します。そのためマイク状態とモデルをHost自身へ保持せず、serviceで一元管理します。

`native_host/foxbook_speech.py` はNative Messagingのバイナリフレームを検証してUnix socketへ中継します。HostをFirefoxへ登録するスクリプトは `scripts/install_host.py` です。serviceは`arecord`、`ffmpeg`と固定されたエンジン・モデルを使います。

`systemd/foxbook-speech.service.in` はユーザー単位の常駐service templateです。導入時は次を順に実行します。`--enable` はserviceを起動するため、実機の固定パスと依存ファイルを確認した後にだけ指定します。

```bash
python3 scripts/install_host.py
python3 scripts/install_service.py
python3 scripts/install_service.py --enable
```

service単体の実機録音は、Voice Editorを使わず次で確認できる。実行中は指定秒数だけ話し、最後の`result`イベントの`text`を確認する。`Ctrl+C`なら録音を取消する。

```bash
python3 scripts/diagnose_recording.py --seconds 5
```

## 状態

- 文書の正本: [仕様書 v0.1](specification/foxbook-speech仕様書v0.1.md)
- Foxbook全体の設計: [Foxbook 全体アーキテクチャ](../foxbook/docs/Foxbook_全体アーキテクチャ_2026-11-16.md)
- 実装・検証の保留事項: [TODO](TODO.md)
- Voice Editorとの現行契約: [IF-VE-SP-001](../foxbook/docs/interfaces/fox-voice-editor--foxbook-speech.md)

## 初期の利用方針

初期版では利用者の明示操作で録音を開始し、同時要求は待ち行列に入れず `BUSY` で拒否します。ブラウザから任意コマンド、モデル／実行ファイル／音声ファイルのパス、音声バイト列は受け取りません。

Whisper は認識要求ごとにCLIを起動します。ReazonSpeech K2はservice全体で一つのWorkerを再利用し、最後の利用から5分で解放します。録音は最大30秒で、自動停止して認識へ進みます。モデルの配置はservice側で固定しています。端末固有のマイク補正は共有serviceでは未実装で、設定方式も未決定です。実機診断では `--engine reazonspeech_k2` を指定します。
