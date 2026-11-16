# foxbook-speech 作業規約

## 共有コンテキスト

- 作業開始時は `../foxbook/.context/root-todo.md`、続けて `../foxbook/.context/session.md` を読む。
- 横断構成、Native Messagingの登録名、共有API、導入手順、検証条件を変更する場合は、同じ変更単位で `../foxbook/docs/cross-repo-ledger.md` と該当する `../foxbook/docs/interfaces/` を更新する。
- このリポジトリ固有の実装・保留事項は `TODO.md` に、共有状態のNow/Nextだけは `../foxbook/.context/root-todo.md` に記載する。

## 境界

- Native Messaging Host は Firefox との固定JSON入出力とサービスへの中継だけを担当する。録音状態・認識モデル・マイク排他をHostプロセス内へ保持しない。
- service は録音・変換・認識・取消・タイムアウト・一時ファイル回収を担当する。認識テキストの編集、履歴、定型、コマンド解釈、他拡張固有の操作を担当しない。
- 拡張から任意のコマンド、パス、モデル指定、音声ファイル、音声バイト列を受け取らない。受理する操作・エンジン・設定はservice側で固定・検証する。
- 各要求の所有者は、FirefoxがNative Messaging Hostを起動した拡張IDとHost接続で決める。要求本文の `clientId` は認可根拠にしない。
- 録音リースは、正常終了、取消、Native Host／socket切断、service異常、タイムアウトの全てで回収する。

## 検証

- 単独録音、`BUSY`、停止、取消、空結果、変換／認識失敗、Host切断、拡張再読み込み、service再起動、ReazonSpeech Worker再利用を自動試験する。
- Surfaceではマイク補正、モデル初期化時間、連続録音、CPU・メモリ、Worker回収を実機確認する。
