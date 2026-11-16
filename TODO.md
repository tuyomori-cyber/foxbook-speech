# foxbook-speech ToDo

更新日: 2026-11-16

## 現在

- [x] 共通Host＋単一音声serviceの責務、境界、初期APIを仕様化した。
- [ ] `foxbook_speech` Native Messaging Host、Unix socket service、systemd --userの最小実装を作る。
- [ ] `fox-voice-editor` を音声Portと編集保存Portへ分離し、最初の利用者として移行する。

## 設計・実装前の確認

- [ ] Native Host起動引数から取得する拡張ID、Host接続、service側セッションを対応付ける方式を決める。
- [ ] `BUSY`、録音リース、取消、接続切断、古いイベント破棄の状態遷移を試験可能な契約にする。
- [ ] Surface Pro 4で常駐serviceとReazonSpeech Workerのメモリ、初回準備、アイドル解放を測り、systemdの常駐／socket activationを選ぶ。
- [ ] 端末固有マイク補正の設定スキーマと誤適用防止を決める。
