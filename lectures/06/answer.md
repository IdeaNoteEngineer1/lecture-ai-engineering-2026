# 第6回 解答

## 演習

<!-- [tool call] の行は、表示された行をそのまま貼り付けてください。終わらなかった STEP は、空欄のままでかまいません。 -->

- STEP 1 のツールの名前：glossary_search_glossary
- STEP 2 の [tool call]：glossary_search_glossary({'query': 'Aレベル'})
- STEP 3 の [tool call]：fetch_fetch({'url': 'https://modelcontextprotocol.io/'})
- STEP 4 の [tool call]：aws_aws___search_documentation({'topics': ['general'], 'search_phrase': 'Amazon S3 versioning overview'})
- 気づき・疑問：STEP 2 では、モデルが選んだ検索語が「Aレベル」だったため、用語集の項目「宿題の3レベル」にヒットせず、2回実行しても同じ結果でした。ツール自体は正しく呼ばれていたので、答えが用語集にあっても、モデルが選ぶ検索語によっては届かないことがあると感じました。STEP 3・4 では、設定ファイルに書き足すだけで公開サーバーや外部のサーバーが使えるようになり、エージェント本体を変えていないのにツールが増えるのが印象的でした。

## 宿題

<!-- 基礎・実装・発展のどれか1つに取り組めば完了です。 -->

- 取り組んだレベル：基礎
- やったこと：app/mcp_server.py の TODO の下に server.tool()(tools.get_lecture_summary) を1行追加して、get_lecture_summary を MCP ツールとして公開しました。エージェント側のファイルは変更していません。
- 結果：--list-tools でモデルに見えているツールが7個から8個に増え、glossary_get_lecture_summary が表示されました。「第2回では何を学びますか？」と質問すると glossary_get_lecture_summary({'lecture': 2}) が呼ばれ、第2回の要点をもとに回答が返りました。uv run pytest -q は 29 passed で、テストもすべて通りました。
- 気づき・疑問：サーバー側に1行足すだけで新しいツールが使えるようになるのは、エージェントが起動のたびにサーバーへツールの一覧を問い合わせているためだと分かりました。ツールを作る側と使う側を分けられるので、直すときもサーバー側の1か所で済むと感じました。