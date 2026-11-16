# foxbook-speech ToDo

更新日: 2026-11-16

## 現在

- [x] 共通Host＋単一音声serviceの責務、境界、初期API、接続所有権、録音リース、engine共有、Voice Editor二Portを仕様化した。
- [x] serviceの所有権・録音リース・状態遷移を外部プロセスから独立した状態コアと自動試験で実装した。
- [x] serviceのUnix socket入口、接続開始検証、socket切断によるリース回収を実装した。
- [x] `foxbook_speech` Native Messaging adapterとFirefox用manifest登録スクリプトを実装した。
- [x] Whisperの録音・変換・CLI認識・取消・一時ファイル回収をservice状態機械へ接続し、socket経由の状態遷移を自動試験で確認した。
- [x] systemd --user serviceを実機で起動し、ユーザー専用socketとNative Messaging manifestの登録を確認した。
- [x] socket API経由で録音から結果までを確認する診断クライアントを追加し、実録音を確認した。
- [x] 実機で5秒録音し、Whisperの変換・認識・結果返却まで確認した。修正後は変換101ms、モデル準備129ms、認識1317ms、停止から結果まで1581ms。
- [x] ReazonSpeech K2 Worker、全serviceでの共有、認識結果統合、通常の認識完了後の5分アイドル解放を実装した。
- [x] ReazonSpeech K2の実機録音・認識を確認した（変換100ms、認識170ms、停止から結果まで276ms、Worker世代1）。
- [x] 同一Workerの再利用を実機確認した（2回目もWorker世代1、認識171ms、停止から結果まで313ms）。
- [x] 5分アイドル解放後のWorker再生成を実機確認した（Worker世代2、認識160ms、停止から結果まで264ms）。
- [x] `fox-voice-editor` の音声Portと編集保存Portを分離し、Firefoxで両engineの録音・保存を確認した。
- [ ] 【優先】録音中にキャンセルした場合、ReazonSpeech Workerが5分後も残る不具合を修正する。実機で`arecord`は終了、Workerは5分後も残存。`service/server.py`の`_cancel`経由では`_finish`内の`mark_idle()`が呼ばれない。準備のみ・切断・認識中取消も含め寿命管理を見直し、他session利用への影響と競合を考慮した自動試験・実機再確認を行う。
- [ ] 録音・変換・認識中の取消／接続断で子プロセス、一時ファイル、リースの回収を検証する。

## 設計・実装前の確認

- [x] Native Host起動元ID、Host接続、service側sessionを対応付ける方式を決めた。
- [x] `BUSY`、録音リース、取消、接続切断、古いイベント破棄の状態遷移を決めた。
- [ ] Surface Pro 4で常駐serviceとReazonSpeech Workerのメモリ、初回準備、アイドル解放を測り、systemdの常駐／socket activationを選ぶ。
- [ ] 端末固有マイク補正の設定スキーマと誤適用防止を決める。
