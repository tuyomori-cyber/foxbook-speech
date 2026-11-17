# foxbook-speech ToDo

更新日: 2026-11-16

## 現在

- [ ] 【THE SESSION TOOLS音声操作v1】Native Messaging、ネイティブKWS、3秒ReazonSpeech、結果後の再待機と再生・停止／BPM／音量／Division操作を実機確認済み。音色は対象外。切断回収、Voice Editorとの同時利用、Surface、KWSと録音の自動試験を残す。Voice Editorの任意録音経路は変更しない。
- [ ] 【次回】USBマイク・閾値0.25・入力レベル表示ありでは、ネイティブ版（CPU 7.24〜8.06%、RSS 52,608KiB）がPython版（CPU 11.58〜11.86%、RSS 68,244〜68,252KiB）より軽かった。ネイティブ版の2秒区間ピークは4.3〜20.7%で、飽和は再現していない。発話回数を定めた検出率、長時間誤検出率、dynabook／Surfaceの同条件比較を行う。[検討メモ](specification/ウェイクワード常時待機検討.md)を参照。
- [ ] 登録拡張の利用中だけウェイクワード待機を起動する運用を検討する。複数接続の所有権、最後の切断や異常終了での停止・回収、マイク排他、録音への引き継ぎ・監視再開は未設計。現状は独立診断で、service・Firefox連携は未実装。
- [x] dynabook G83/HSでは既定ALSAのKWS初期化が`Operation not permitted`で失敗し、PortAudioも既定入力を発見できなかった。`arecord`入力方式を追加し、実マイクで検出できることを確認した。
- [ ] dynabook G83/HSのarecord入力で`HEY FOX`と`FOX`単体を検出。`FOX`は閾値0.1で「まぁまぁ反応し、使えそう」との定性的な評価。テレビ音下5分以上の待機中に誤検出なし。同一診断の`ps`で検出Python CPU平均3.6%・RSS 68,880KB、arecord CPU平均0.0%・RSS 7,828KBを確認。発話回数と成功率、長時間の誤検出率、Surfaceの負荷・電力は未測定。
- [x] 録音の30秒上限で自動的に変換・認識へ進む処理を実装・自動試験済み。dynabook G83/HSで自動停止後の結果表示と次の録音を確認した。
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
- [x] 録音中キャンセル後のWorker解放漏れを修正。新端末で5分後のWorker解放と再読込後の復旧を実機確認した。準備のみの解放、複数利用者、録音中取消・切断は自動試験でも確認した。
- [x] 変換中とWhisper／ReazonSpeech認識中の取消・接続断について、擬似子プロセスを待機させる自動試験でプロセス、一時ファイル、録音リースの回収を確認した。ReazonSpeechの変換中はWorkerのアイドル解放も確認した。

## 設計・実装前の確認

- Surface Pro 4ではWhisperの性能が実用に足りないため、Whisper固有の計測や改善の優先度はかなり低い。ReazonSpeechを優先する。
- [x] Native Host起動元ID、Host接続、service側sessionを対応付ける方式を決めた。
- [x] `BUSY`、録音リース、取消、接続切断、古いイベント破棄の状態遷移を決めた。
- [ ] Surface Pro 4で常駐serviceとReazonSpeech Workerのメモリ、初回準備、アイドル解放を測り、systemdの常駐／socket activationを選ぶ。
- [ ] 端末固有マイク補正の設定スキーマと誤適用防止を決める。
