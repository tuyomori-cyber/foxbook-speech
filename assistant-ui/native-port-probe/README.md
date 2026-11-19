# Native Portのページ非依存検証

専用のダミーNative Hostを起動し、同じHostから90秒または5分後に送信されるイベントをFirefox拡張の背景処理が受け取れるか確認します。音声・マイク・ネットワーク・既存の `foxbook_speech` Host／serviceは使用しません。Content Scriptや定期heartbeatも使用しません。

## 準備

Firefoxが検証Hostを見つけられるよう、`install_probe_host.py` は `~/.mozilla/native-messaging-hosts/foxbook_native_port_probe.json` だけを登録します。既存の同名ファイルは上書きしません。登録は音声Hostと別名で、許可対象も検証拡張だけです。

```bash
python3 assistant-ui/native-port-probe/install_probe_host.py
```

## 検証

1. `about:debugging#/runtime/this-firefox` で `assistant-ui/native-port-probe/manifest.json` を一時読み込みします。
2. 拡張メニューから「Native Portの検証」を開き、観測時間を選択して **検証を開始** を押します。「接続中・遅延イベント待ち」とHost PIDを控えます。表示されなければ、メニューを一度閉じて開き直してください。
3. メニューを閉じ、`about:addons` などContent Scriptを表示できないページを開いて、選択時間以上待ちます。試験中はポップアップを開かないでください。
4. 再び拡張メニューを開き、「300秒後のイベントを受信」等の表示を確認し、**接続を終了** を押します。「イベント前に切断」や「Port不在」も結果として記録します。

## 拡張再読み込み時の回収

1. 検証を開始し、Host PIDを控えます。
2. `about:debugging` で「Native Portの検証」を **再読み込み** します。
3. ターミナルで `ps -p 控えたPID -o pid=,ppid=,stat=,args=` を実行します。何も表示されなければ、そのPIDのプロセスは存在しません。PIDが再利用される場合もあるため、表示された場合は内容を確認します。
4. 検証メニューから再び開始できるか確認し、終了ボタンで停止します。

この試験は一つのHostによる選択時間内の接続・遅延イベント到達を調べます。Wake Word、マイク、実際のアプリへの配送、選択時間を超える長時間動作やブラウザー再起動後の復帰は証明しません。ブラウザーを終了するとHostは終了します。

検証用登録が不要になった場合は、上記の専用JSONと内容を確認したうえで取り除いてください。既存の `foxbook_speech.json` は対象ではありません。
