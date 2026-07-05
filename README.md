日本語 | [English](#software-size-measurement-tool-software_sizepy)

# ソフトウェア規模計測ツール (software_size.py)

## 参考資料

- [ソフトウェア開発 分析データ集 2022 (IPA)](https://www.ipa.go.jp/digital/software-survey/metrics/hjuojm000000c6it-att/000102171.pdf) からチェック

## 概要

`software_size.py` は、指定ディレクトリ配下をスキャンして SLOC・アーキテクチャ・データ・クラウドネイティブ・複雑度などのメトリクスを収集し、重み付けした「Software Size Score」を算出、Tiny〜Enterpriseに分類するツール。単一リポジトリでもマルチリポジトリのワークスペース全体でも実行可能。テキストレポート・HTMLレポートいずれも **サマリ(Score/分類/SLOC/人月)を先頭、詳細セクションをその後** に表示する。

## レポートの見方

実際の出力(`quarkusdroneshop-web`に対して全オプション有効で実行した例)に沿って、各行が何を意味するかを説明する。

```
python3 software_size.py ../quarkusdroneshop-web --name quarkusdroneshop-web \
  --weights weights.json --effort --productivity productivity.json \
  --ai --ai-since "90 days ago" --ai-metrics ai-metrics.example.json --assess
```

### 1. Summary(最初に見る場所)

```
Summary
-------
Name           : quarkusdroneshop-web
Score          : 115 points -> Small
SLOC           : 8,441
Files          : 172
Size Bands     : Tiny(<100) / Small(100-300) / Medium(300-700) / Large(700-1500) / Enterprise(1500+)
```

- **Score / 分類**: `weights.json`の重みを各メトリクスの生値に掛けて合算した値(算出方法は「スコア算出とサイズ分類」章)。分類は下の`Size Bands`の帯のどこに入るかを示すだけで、それ以上の意味(良し悪し)は持たない。あくまで「相対的な規模感」の指標。
- **SLOC / Files**: スキャン対象の総行数・総ファイル数。ベンダー取り込みコードを含むと過大になる点は「使う上での注意点」を参照。

### 2. Overall Assessment(`--assess`指定時。あくまで診断用スコアカード)

```
Overall Assessment (heuristic scorecard, --assess)
------------------------------------------------------------
Project Size        : Small

Maintainability     : A-  (90/100)
Architecture        : F  (50/100)
Cloud Native        : F  (40/100)
Documentation       : C-  (70/100)
AI Readiness        : 69/100
Overall Score       : 67/100 (D)
```

- 5つのカテゴリ(Maintainability/Architecture/Cloud Native/Documentation/AI Readiness)をそれぞれ0-100点でスコアリングし、レター評価(A+〜F、一般的な学校の成績表と同じ換算)に変換したもの。各カテゴリの採点ルール(ルーブリック)は「Overall Assessment (--assess)」章に**全項目明記**しているので、なぜその評価になったかを追跡できる。
- **Effort Estimate(人月)には一切影響しない**。ScoreやAI Readinessと同じく、あくまで規模・成熟度の相対比較用の診断情報。
- カテゴリの重み付け(既定: Maintainability35% / Architecture25% / Cloud Native15% / Documentation15% / AI Readiness10%)は`assessment.json`に外部化されており、`--assessment FILE`で自社の判断に合わせて調整できる。
- 該当データが無いカテゴリ(例: `--ai`も`--ai-metrics`も指定していない場合のAI Readiness)は`N/A`となり、Overall Scoreの計算からは除外(残りカテゴリの重みで再正規化)される。
- この`quarkusdroneshop-web`の例でArchitecture/Cloud Nativeが`F`なのは、単にこのプロジェクトがMicroservices構成でもK8sマニフェストを持ってもいないため(ルーブリックの加点条件を満たしていないだけ)であり、「悪いコード」という意味ではない。

### 3. Effort Estimate(`--effort`指定時。契約・計画にはここだけ見ればよい)

```
Effort Estimate (productivity: productivity.json)
  Java SLOC    : 3,323  (rate 3.94 SLOC/人時) -> 5.3 人月
  Node SLOC    : 3,720  (TS+JS, rate 3.94 SLOC/人時) -> 5.9 人月
  Total        : 11.2 人月  <- Base PM (contract/planning figure)
```

- **Base PM(= Total行)**: SLOCと`productivity.json`だけから機械的に再現できる、契約・計画用の人月。同じコード規模なら常に同じ値になる。
- APFを使わない場合はここで終わり。**この数字だけを見積りに使えばよい。**

```
  APF (AI Productivity Factor): 0.82  (source: ai-metrics.example.json)
  Estimated PM (AI-adjusted)  : 9.2 人月  (= 11.2 base x 0.82)
    Java: 4.3 人月, Node: 4.8 人月
  Basis (judged by whoever set APF, not computed by this tool):
    AI Generated Ratio (%)  : 40
    AI Accept Rate (%)      : 65
    AI Test Generation      : Yes
    AI Review Used          : Yes
    AI Refactoring Used     : Yes
```

- `--ai-metrics`のファイルに`ai_productivity_factor`(APF)が入っている場合のみ表示される追加ブロック。**Base PMは変わらず、APFを掛けた別の数字が追加で出るだけ**。
- `Estimated PM (AI-adjusted)`は「AIを使うと前提した場合の参考値」であり、**Base PMの代わりに使うかどうかは見積り側の判断**。ツールはどちらが正しいかを決めない。
- `Basis`は、APFの値(0.82)を入力した人が何を根拠に判断したかの記録。ツールはこの根拠からAPFを計算していない(計算式にすると閾値の決め方が編集判断になるため、意図的にそうしていない)。数字の妥当性を後から確認するための情報。

### 4. Project 〜 Dependencies(規模の内訳)

Score算出の元になった生の数値。「スコア算出とサイズ分類」の重み表と対応させて見ると、どの要素がScoreを押し上げているかが分かる(例: `Modules`が多い/`REST APIs`が多いプロジェクトほどAPI・Module項目の寄与が大きくなる)。各項目の集計方法は「計測項目」章を参照。`Complexity`の`Coverage`はjacoco.xml等が無ければ`N/A`(推測しない)。

### 5. AI Development(`--ai`指定時。見積りには使わない診断情報)

```
AI Development (git-derived + optional external metrics)
------------------------------------------------------------
Repos analyzed    : 1
Commits analyzed  : 57
Lines Added       : 7,958
Lines Deleted     : 2,530
Net Change        : +5,428
Refactoring Ratio : 40.0% (balanced-churn heuristic: ...)
                    0.0% of commits mention "refactor" in the message (keyword heuristic)
AI Co-authored    : 52.6% of commits (30/57), 13.7% of lines added
```

- これは**Effort Estimateとは独立した診断セクション**であり、ここの数値がPMを変えることはない(APFはあくまで`ai-metrics.json`の値を直接使うのみ)。
- `AI Co-authored`はコミットトレーラーで検出できたAI関与の**下限値**。実際の支援率はこれより高い可能性が高い(詳細は「AI Development」章の注意を参照)。
- `External AI metrics`テーブルは`--ai-metrics`で読み込んだ生の値をそのまま表示しているだけ(Accept Rateやレビュー時間など)。

### 6. HTMLレポート(`--html`)

上記と同じ内容を、**トップにサマリ・人月カード**→**Overall Assessment**→**Size Classificationゲージ**→**SLOC/Score内訳グラフ**→**Effort Estimate(APF込み)**→**AI Development**→**詳細テーブル**の順にグラフ付きで表示する。ブラウザで開くだけで全体が見渡せるので、テキストレポートより説明resource向き。生成方法・構成の詳細は「HTMLレポート」章を参照。

### 一言でまとめると

- **契約・計画に使う数字は1つだけ: `Effort Estimate`の`Total`(Base PM)。**
- AIの影響を加味した参考値が欲しければ`Estimated PM (AI-adjusted)`を見る(ただしAPFは人が判断した数値であることを理解した上で)。
- `Overall Assessment`・`AI Development`セクションとScore/分類は、あくまで規模感・開発実態の**診断情報**であり、人月には反映されない。

```
python3 software_size.py [PATH] [--name NAME] [--json] [--weights FILE] [--effort]
                          [--productivity FILE] [--html FILE]
                          [--ai] [--ai-since WHEN] [--ai-metrics FILE]
                          [--assess] [--assessment FILE]
```

- `PATH` : スキャン対象ディレクトリ(省略時はカレントディレクトリ)
- `--name` : レポートに表示するプロジェクト名
- `--json` : メトリクス・スコア・人月試算を JSON でも出力
- `--weights FILE` : 重み設定を上書き(`weights.json` 参照)
- `--effort` : Java SLOC / Node(TS+JS) SLOC から算出した人月概算をテキストレポートにも表示(HTMLレポートには常に表示される)
- `--productivity FILE` : 人月換算の生産性テーブルを上書き(`productivity.json` 参照。詳細は「人月試算」の章)
- `--html FILE` : グラフ付きのリッチなHTMLレポートを指定パスに出力(詳細は「HTMLレポート」の章)
- `--ai` : AI Development節(git由来のLines Added/Deleted・Refactoring Ratio・AI共著コミット比率)を追加(詳細は「AI Development」の章)
- `--ai-since WHEN` : `--ai`のgit解析対象を絞り込む(例 `"90 days ago"`)。大きい/ベンダー取り込みの履歴では推奨
- `--ai-metrics FILE` : gitからは出せないAI関連メトリクス(AI生成コード比率・Copilot Accept Rate等)を外部ファイルから読み込む(`ai-metrics.example.json`参照。未指定なら推測せずN/A表示)。`ai_productivity_factor`を含む場合は`--ai`の有無に関わらずBase PMに乗算した調整後PMも表示(詳細は「見積りモデルと診断モデルの分離」参照)
- `--assess` : Overall Assessmentスコアカード(Maintainability/Architecture/Cloud Native/Documentationのレター評価、AI Readiness、Overall Score)を追加(詳細は「Overall Assessment」の章)
- `--assessment FILE` : Overall Assessmentのカテゴリ重み付けを上書き(`assessment.json` 参照)

`sizecheck.sh` はアプリケーション名・HTML生成有無・AI Development節・Overall Assessment節の有無を外部パラメータ化したラッパー(実行時にヘッダーを表示):

```
bash sizecheck.sh [APP_NAME] [GENERATE_HTML] [GENERATE_AI] [GENERATE_ASSESS]
# または環境変数で指定
APP_NAME=myapp GENERATE_HTML=false GENERATE_AI=true GENERATE_ASSESS=false bash sizecheck.sh
```

- `APP_NAME` : レポートに表示するアプリケーション名(省略時 `quarkusdroneshop`)
- `GENERATE_HTML` : `true`/`false` で `report.html` の生成有無を切り替え(省略時 `true`)
- `GENERATE_AI` : `true`/`false` でAI Development節の追加有無を切り替え(省略時 `false`)。`true`の場合、直下に`ai-metrics.json`があれば自動で`--ai-metrics`として読み込む
- `GENERATE_ASSESS` : `true`/`false` でOverall Assessment節の追加有無を切り替え(省略時 `true`)。直下に`assessment.json`があれば自動で`--assessment`として読み込む

実行例:

```
$ bash sizecheck.sh
============================================================
 Software Size Report
------------------------------------------------------------
 Application  : quarkusdroneshop
 Generate HTML: true
 Generate AI  : false
 Generate Assess: true
============================================================
Software Size Summary
...
```

(このディレクトリ自身が測定対象ワークスペースのサブディレクトリという想定のため内部で `..` を指定している。別プロジェクトで使う場合は `sizecheck.sh` 内のパスを読み替える。)

## 計測項目

- **Code**: `cloc`(インストール済みなら利用、無ければ簡易フォールバック実装)で言語別SLOC・ファイル数を集計
- **Architecture**: Modules(pom.xml/package.json/build.gradle/go.mod/pyproject.toml等の設置ディレクトリ数)、Microservices(Dockerfile/Containerfile設置ディレクトリ数)、REST APIs(`@Path`/NestJS `@Get`等/Express `router.get`等/FastAPI・Flaskデコレータ)、GraphQL APIs(`.graphql(s)`ファイル、`@GraphQLApi`、`@Resolver`)、Camel Routes(`from("...")`)、Kafka Topics(`mp.messaging.*.topic=`、Strimzi `KafkaTopic` CR、`@Channel`/`@Topic`)
- **Data**: DB Tables(`@Table(name=...)`、SQLの`CREATE TABLE`)、Entities(`@Entity`)、OpenAPI/AsyncAPI Specs(YAML/JSONの先頭キー検出)
- **Cloud Native**: `kind: Deployment/StatefulSet/CronJob`、Helm Chart(`Chart.yaml`)、Operator(`kind: ClusterServiceVersion`)
- **Complexity**: 正規表現で関数本体を波括弧マッチングして抽出し、if/for/while/case/catch/&&/||/三項演算子をカウントする簡易サイクロマティック複雑度(lizard等の静的解析ツールの代替、精度は概算)
- **Dependencies**: Maven Modules(`pom.xml`数)、Node Packages(全`package.json`のdependencies+devDependenciesのユニーク名数)、Container Images(Dockerfile設置ディレクトリ数)

いずれも正規表現ベースのヒューリスティックであり、静的解析ツールによる厳密な計測ではない(相対比較・概算把握が目的)。

## スコア算出とサイズ分類

`weights.json` の重みをそのままメトリクスの生値に掛けて合算(正規化なし):

| 指標 | 重み | 対象 |
|---|---|---|
| KLOC | 1 | Total SLOC / 1000 |
| API | 5 | REST APIs + GraphQL APIs |
| Camel Route | 3 | Camel Routes |
| Kafka Topic | 2 | Kafka Topics |
| DB Table | 2 | Database Tables |
| Deployment | 2 | Deployments |
| Module | 4 | Modules |
| Complexity | 10 | Average CC |

分類しきい値(スコアは上限が排他的):

| Score | 分類 |
|---|---|
| <100 | Tiny |
| 100-300 | Small |
| 300-700 | Medium |
| 700-1500 | Large |
| 1500+ | Enterprise |

`--weights` に別の JSON を渡せば重みだけ差し替えて再計算できる。

## 人月試算 (--effort) と生産性テーブルの外部化 (--productivity)

Java SLOCとNode(TypeScript+JavaScript合算)SLOCそれぞれから人月を概算する。計算式は共通:

```
人月 = SLOC ÷ (該当SLOC規模帯の rate_sloc_per_hour × hours_per_person_month)
```

生産性テーブルは `productivity.json` に外部化されており、`--productivity FILE` で企業独自の値に差し替えられる。デフォルト(`productivity.json`、リポジトリに同梱)は **IPA「ソフトウェア開発分析データ集2022」表A1-2-4(新規開発:全年度, n=1,246)** のSLOC規模帯別・生産性中央値(SLOC/人時)をそのまま採用している:

```json
{
  "hours_per_person_month": 160,
  "java": {
    "bands": [
      {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
      {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
      {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
      {"max_sloc": null, "rate_sloc_per_hour": 5.92}
    ]
  },
  "node": {
    "bands": [
      {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
      {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
      {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
      {"max_sloc": null, "rate_sloc_per_hour": 5.92}
    ]
  }
}
```

- `bands` は SLOC規模の昇順で並べる。`max_sloc` はその帯の上限(排他的)。最後の帯は上限なしなので `null` を指定する。
- `java` / `node` を別々に指定できるので、自社の実測生産性がJavaとNodeで異なる場合はそれぞれ違う値を入れられる(IPAの公開データにはこの区分が無いため、本ツールのデフォルトはJava/Nodeとも同じテーブルを使っている)。
- `--productivity` を渡さない場合は上記の埋め込みデフォルトがそのまま使われる(`productivity.json` を編集しても、明示的に `--productivity productivity.json` を渡さない限り反映されない点に注意)。

**企業独自の生産性を使う例**: 実測で「Javaは800 SLOC/人月」「Nodeは1200 SLOC/人月」(規模帯によらずフラットレート)と分かっている場合、`productivity.example.json` (同梱)のように1本の帯だけを定義すればよい:

```json
{
  "hours_per_person_month": 160,
  "java": {
    "bands": [
      {"max_sloc": null, "rate_sloc_per_hour": 5.0}
    ]
  },
  "node": {
    "bands": [
      {"max_sloc": null, "rate_sloc_per_hour": 7.5}
    ]
  }
}
```

(5.0 SLOC/時 × 160時間 = 800 SLOC/人月、7.5 × 160 = 1200 SLOC/人月)

```
python3 software_size.py . --weights weights.json --effort --productivity productivity.example.json
```

**重要な注意(デフォルト値について)**: IPAの公開データには、JavaとJavaScript/Node.jsを分けた生産性テーブルは存在しない。開発言語の集計はプロジェクト件数の分布(Java 42.4%、JavaScript 1.9%、対象1,476件中)のみで、生産性は全言語混在・SLOC規模帯別にしか公開されていない。またNode.js単体のカテゴリはIPAの調査項目にそもそも存在しない。そのため `productivity.json` のデフォルトは「Java用」「Node用」の区別ではなく、**同じ全体テーブルをJavaのSLOC規模とNodeのSLOC規模それぞれに当てはめているだけ**であり、精度の高い言語別ベンチマークではなくROM(概算)見積もりとして扱うこと。自社の実測値がある場合は `--productivity` で必ず差し替えることを推奨する。

## HTMLレポート (--html)

`--html FILE` を付けると、外部ライブラリ・インターネット接続不要の自己完結型HTMLファイル(インラインSVGグラフ)を生成する。

```
python3 software_size.py . --name quarkusdroneshop --weights weights.json --effort \
  --productivity productivity.json --html report.html
```

`sizecheck.sh` にはこのコマンドを既に設定済みなので `bash sizecheck.sh` を実行するだけで `report.html` が生成される。生成後はブラウザで直接開くか、簡易サーバーで確認する:

```
python3 -m http.server 8000
# → http://localhost:8000/report.html
```

レポート構成:

1. **トップ(サマリ)**: Software Size Score・分類(Tiny〜Enterprise)・Total SLOC・**Java/Node/合計の人月**をカード形式で最上部に配置
2. **Size Classification**: スコアが Tiny〜Enterprise のどこに位置するかを示すゲージ
3. **SLOC by Language** / **Score Breakdown by Weight Category**: 棒グラフ
4. **Effort Estimate (Person-Months)**: Java/Nodeの人月を棒グラフで比較、使用した生産性テーブルの出典も明記
5. **Architecture / Data / Cloud Native / Complexity / Dependencies**: 詳細テーブル

`report.html` は生成物のため `.gitignore` に含めてコミット対象から除外している。

## AI Development (--ai)

2025〜2026年にかけて米国企業(GitHub/Microsoft/Google/McKinsey/ISBSGなど)が議論している「コード量だけでなく、AIがどれだけ支援したか・人間が何に時間を使ったか」という観点を、opt-inの`--ai`で追加できる。**gitから実際に検証できる指標だけを自動計算し、検証できない指標は捏造せず外部ファイルからのみ受け取る**という方針で実装している。

### git由来の指標(自動計算、常に実データ)

`--ai`を付けると、スキャン対象配下に存在する**すべての`.git`リポジトリ**(このツールはマルチリポジトリのワークスペースを想定しているため、サブプロジェクトごとの`.git`を横断集計する)から以下を算出する:

| 指標 | 内容 |
|---|---|
| Lines Added / Lines Deleted | `git log --no-merges --numstat` の合算 |
| Refactoring Ratio(balanced-churn) | コミットごとに `2×min(追加,削除)/(追加+削除)` を churn 重み付けで平均したもの。純粋な追加・削除より「既存コードの書き換え」に近いほど高くなるヒューリスティック |
| Refactoring Ratio(keyword) | コミットメッセージ1行目に `refactor` を含む比率 |
| AI Co-authored Commit Ratio | `Co-Authored-By: <tool>` トレーラー(Claude, Copilot, Cursor, Codeium, ChatGPT/OpenAI, Gemini, Devin, Windsurf, Tabnine, CodeWhisperer, Amazon Q 等を正規表現でマッチ)を含むコミットの比率、および該当コミットの追加行数比率 |

```
python3 software_size.py . --ai --ai-since "90 days ago"
```

**重要な注意**: `AI Co-authored`はコミットトレーラーを付与するツール(Claude Codeはデフォルトで付与)しか検出できない。GitHub Copilotの通常のオートコンプリート補完のようにコミットへ痕跡を残さない支援は捕捉できないため、**この数値はAI関与の下限値**であり、実際のAI支援率はこれより高い可能性がある。「Refactoring Ratio」も同様にヒューリスティックであり、ASTレベルでリファクタリングを判定しているわけではない。

**パフォーマンス上の注意**: このワークスペースのように大量のベンダー取り込みリポジトリ(例: `developerhub-skeleton/backstage`は約71,000コミット)を含む場合、全履歴を対象にすると `git log --numstat` だけで1リポジトリ40秒以上かかることがある。`--ai-since "90 days ago"` のように直近の期間へ絞ることを強く推奨する(このリポジトリでは16リポジトリ・約720コミットに絞っても20秒程度で完了する)。

### gitでは出せない指標(--ai-metrics FILEでのみ反映、未指定ならN/A)

AI生成コード比率・Copilot/アシスタントのAccept Rate・レビュー時間・コーディング時間・プロンプト数・テスト生成比率などは、**gitにもファイルシステムにも実データが存在しない**(GitHub Copilot Metrics API、Cursorのアナリティクス、IDEプラグインのテレメトリなど、AIツール側の実測データが必要)。それらしい数値を推測で埋めることはしないため、`--ai-metrics FILE`を渡さない限りレポート上は「not provided」と表示される。

`ai-metrics.example.json`(同梱、サンプル値):

```json
{
  "source": "GitHub Copilot Metrics API export, 2026-06 (example -- replace with real data)",
  "ai_generated_sloc": 18200,
  "ai_generated_ratio_pct": 43,
  "copilot_accept_rate_pct": 38,
  "estimated_review_hours": 120,
  "estimated_coding_hours": 420,
  "prompt_count": null,
  "test_generation_ratio_pct": null,
  "ai_productivity_factor": 0.82
}
```

```
python3 software_size.py . --ai --ai-metrics ai-metrics.example.json
```

値が分からない項目は `null` のままでよい(レポートには表示されない)。実運用では実測値を入れた `ai-metrics.json` を用意し、`sizecheck.sh` の `GENERATE_AI=true` 実行時に自動で読み込ませるとよい。

### 見積りモデルと診断モデルの分離、AI Productivity Factor (APF)

見積り(人月)で重要なのは「同じ入力なら同じ結果になる」「なぜその数字なのか説明できる」ことなので、本ツールは次の2つを明確に分離している:

- **見積りモデル**(`--effort`/`--productivity`): SLOC → IPA/COCOMO的な生産性テーブル → Base PM。契約・計画に使う数字で、SLOCと`productivity.json`だけから常に再現できる。
- **AI診断**(`--ai`): git由来のLines Added/Deleted・Refactoring Ratio・AI共著コミット比率。あくまで観測・診断用であり、**Base PMの計算には一切使わない**。

AIをそれでも人月へ反映したい場合、`AI Readiness`のような品質スコアを直接掛け合わせるのではなく、`ai-metrics.json`の `ai_productivity_factor` に**実測または合意済みの倍率をそのまま数値で指定**する方式にした:

```
Estimated PM (AI-adjusted) = Base PM × APF
例: 714.2 × 0.82 = 585.6
```

- `ai_productivity_factor`を指定すると、`--ai`の有無に関わらずEffort Estimateセクションに `Base PM` と `Estimated PM (AI-adjusted)` が両方表示される(Base PMは常に変更されず契約用の数字として残る)。
- APFをAIコード生成率・受入率・テスト生成有無などから自動算出する式は、閾値・重み付けの決め方自体が編集判断になるため実装していない。**その代わり、AIコード生成率・受入率・テスト生成/レビュー利用/リファクタリング利用の有無を`ai-metrics.json`に記録できるようにし、APFの「根拠(basis)」としてAPFの数値と一緒に表示する形にした**。APFの値そのものは自動計算せず、入力者(実測データを見て判断する人)がこれらの項目を踏まえて判断した数値をそのまま入力する:

```json
{
  "ai_generated_ratio_pct": 40,
  "copilot_accept_rate_pct": 65,
  "ai_test_generation_used": true,
  "ai_review_used": true,
  "ai_refactoring_used": true,
  "ai_productivity_factor": 0.82,
  "ai_productivity_factor_note": "Judged by <name/team>, <date>: ..."
}
```

これにより、Effort Estimateセクションには次のように表示される:

```
APF (AI Productivity Factor): 0.82  (source: ai-metrics.json)
Estimated PM (AI-adjusted)  : 585.6 人月  (= 714.2 base x 0.82)
Basis (judged by whoever set APF, not computed by this tool):
  AI Generated Ratio (%)  : 40
  AI Accept Rate (%)      : 65
  AI Test Generation      : Yes
  AI Review Used          : Yes
  AI Refactoring Used     : Yes
Note: Judged by <name/team>, <date>: ...
```

`ai_productivity_factor_note`は任意項目で、誰がいつどう判断したかの記録用(監査・再確認のため)。

## Overall Assessment (--assess)

`--assess`は、規模(Score)や人月(PM)とは別に、**Maintainability・Architecture・Cloud Native・Documentation・AI Readiness**の5カテゴリを0-100点でスコアリングし、レター評価(A+〜F)と、重み付き合成の**Overall Score**を出すヒューリスティックなスコアカード。**Base PM/APFには一切影響しない**(見積りモデルと完全に独立)。

### レター評価のしきい値

一般的な学校の成績表と同じ、標準的な換算を採用(このツール独自の恣意的な区切りではない):

| Score | Grade | Score | Grade | Score | Grade |
|---|---|---|---|---|---|
| 97-100 | A+ | 83-86 | B | 60-69 | D |
| 93-96 | A | 80-82 | B- | 0-59 | F |
| 90-92 | A- | 77-79 | C+ | | |
| 87-89 | B+ | 73-76 | C | | |
| | | 70-72 | C- | | |

### 各カテゴリの採点ルール(ルーブリック)

すべて「何を満たすと何点になるか」を明記したチェックリスト形式にしている。既存メトリクスの比率をそのまま点数化する(例: OpenAPI仕様ファイル数÷REST APIエンドポイント数)ような、単位の異なる値同士を比べる指標は、見かけ上精密でも実態を反映しないため採用していない。

- **Maintainability**: Average CC(低いほど高得点: ≤5→100, ≤8→90, ≤12→75, ≤20→55, それ以上→35)と、Coverageが分かればその値、を平均。両方無ければ`N/A`。**Maximum CC はスコアに使わない**(このツールの複雑度計測は正規表現による波括弧マッチングのため、ミニファイ済み/ベンダー取り込みのフロントエンドバンドルなどで実態と無関係に跳ね上がることがあり、外れ値1つに評価を左右されないようにするため)。
- **Architecture**: 基礎点50点 + Modules≥2で+15 + Microservices≥2で+15 + OpenAPI Specsが1つでもあれば+10 + AsyncAPI Specsが1つでもあれば+10(満点100)。
- **Cloud Native**: 基礎点40点 + Deploymentsが1つでもあれば+20 + Helm Chartsが1つでもあれば+15 + StatefulSetsまたはCronJobsがあれば+10 + Deployments数がMicroservices数の半分以上あれば+15(満点100)。
- **Documentation**: Markdown SLOC ÷ Total SLOC の比率で採点(≥8%→100, ≥4%→85, ≥2%→70, ≥0.5%→55, それ未満→35) + OpenAPI/AsyncAPI仕様があれば+10のボーナス。ベンダー取り込みのMarkdown(upstreamのCHANGELOG等)を含むと過大評価になる点はSLOCと同様。
- **AI Readiness**: `--ai`のAI共著コミット比率、および`--ai-metrics`のAI生成率・Accept Rate・テスト生成/レビュー/リファクタリング利用フラグを、取得できたものだけ平均。**どちらも無ければ`N/A`**(データが無いのに推測はしない)。

### カテゴリの重み付け(assessment.json)

既定の重み(`assessment.json`、合計100%):

```json
{
  "maintainability": 35,
  "architecture": 25,
  "cloud_native": 15,
  "documentation": 15,
  "ai_readiness": 10
}
```

`--assessment FILE`で自社の判断に合わせて重みを差し替えられる。あるカテゴリが`N/A`の場合、そのカテゴリの重みを除外して残りの重みで再正規化した上でOverall Scoreを算出する(例: AI Readinessが`N/A`なら残り90%分の重みで100%相当に計算し直す)。

### 重要な注意

- 各カテゴリのしきい値(CC≤5=100点、Markdown比率8%=100点、など)は**このツールが決めた基準であり、絶対的な品質基準ではない**。組織によって適正な値は異なるため、まずは自プロジェクト内での相対比較・時系列比較に使うことを推奨する。
- Architecture/Cloud NativeでMicroservices構成でないプロジェクトが低評価になるのは「単一責務のシンプルな構成」を罰しているわけではなく、ルーブリックが「複数モジュール・複数サービス・K8sマニフェスト」を加点対象にしているという設計上の帰結。モノリシックな設計が悪いという意味ではない。
- Overall Assessmentは`Score`(規模)・`Effort Estimate`(人月)のどちらにも影響しない。3つのモデル(規模スコア/見積りモデル/診断スコアカード)は完全に独立している。

## 使う上での注意点

- ベンダー取り込みコード(サードパーティのvendoring等)が含まれるディレクトリをそのままスキャンすると、SLOC・人月ともに実態より過大になる。自社開発分だけを見積もりたい場合は、対象サブディレクトリを絞って実行するか、`EXCLUDE_DIRS` の追加を検討すること。
- Coverageはjacoco.xml/coverage-summary.jsonが見つかった場合のみ算出され、無い場合はN/A。
- `--productivity` を省略するとビルトインのIPAデフォルトが使われる。企業独自の値を常用したい場合は `sizecheck.sh` に `--productivity productivity.json`(または自社ファイル)を含めておくこと。
- `--ai`はデフォルトで無効(opt-in)。有効にする場合、ベンダー取り込みリポジトリを含む大きなワークスペースでは `--ai-since` で期間を絞ること(パフォーマンス上の注意を参照)。
- `--assess`のレター評価はこのツール独自のルーブリックによる相対評価であり、業界標準の品質認証ではない。閾値は`README`に全て明記しているので、社内基準と合わない場合は`assessment.json`で重みを、または`software_size.py`のスコア関数(`score_maintainability`等)のしきい値を直接調整すること。

## 更新履歴(主な機能追加)

1. **初期版**: SLOC/アーキテクチャ/データ/クラウドネイティブ/複雑度/依存関係を計測し、`weights.json`の重み付けでScoreを算出、Tiny〜Enterpriseに分類。
2. **人月試算の追加**(`--effort`): IPA表A1-2-4のSLOC規模帯別生産性を使い、Java/Node SLOCから人月を概算。
3. **生産性テーブルの外部化**(`--productivity`): IPAデフォルトを`productivity.json`に外部化し、企業独自の値に差し替え可能に(`productivity.example.json`も追加)。
4. **テキストレポートの表示順を変更**: 「詳細→サマリ」だった従来順を「サマリ(Score/人月)→詳細」に統一。
5. **HTMLレポート追加**(`--html`): 外部ライブラリ・インターネット接続不要のインラインSVGグラフ付き自己完結HTML。サマリ・人月をトップに配置。
6. **`sizecheck.sh`の外部パラメータ化**: `APP_NAME`/`GENERATE_HTML`/`GENERATE_AI`を引数・環境変数で指定可能に(実行時ヘッダー表示)。
7. **AI Development追加**(`--ai`): 全`.git`リポジトリを横断してLines Added/Deleted・Refactoring Ratio・AI共著コミット比率をgitから実測。gitで測れない指標(AI生成率・Accept Rate等)は`--ai-metrics FILE`で外部入力(捏造しない)。
8. **AI Productivity Factor (APF) 追加**: 見積りモデル(Base PM)とAI診断モデルを分離したまま、AIの影響を人月に反映したい場合のみ`ai-metrics.json`の`ai_productivity_factor`(人が判断した数値)をBase PMに乗算。判断根拠(AI生成率・Accept Rate・テスト生成/レビュー/リファクタリング利用の有無)も併記して監査可能にした。
9. **Overall Assessment追加**(`--assess`): Maintainability/Architecture/Cloud Native/Documentationのレター評価、AI Readiness・Overall Scoreをサマリに追加。カテゴリ重みは`assessment.json`に外部化、各カテゴリの採点ルーブリックは全てREADMEに明記。Base PM/APFには一切影響しない、独立した第3のモデルとして実装。

---

[日本語](#ソフトウェア規模計測ツール-software_sizepy) | English

# Software Size Measurement Tool (software_size.py)

## Reference

- [Software Development Data White Book / Analysis Data Collection 2022 (IPA)](https://www.ipa.go.jp/digital/software-survey/metrics/hjuojm000000c6it-att/000102171.pdf) -- checked against this source

## Overview

`software_size.py` scans a directory tree and collects SLOC, architecture, data, cloud-native and complexity metrics, computes a weighted "Software Size Score", and classifies the project into a size band (Tiny through Enterprise). It works on a single repository or across a whole multi-repo workspace. Both the text report and the HTML report show the **Summary (Score / classification / SLOC / person-months) first, with detail sections after it**.

## How to read the report

Walking through real output (run against `quarkusdroneshop-web` with every option enabled) to explain what each line means.

```
python3 software_size.py ../quarkusdroneshop-web --name quarkusdroneshop-web \
  --weights weights.json --effort --productivity productivity.json \
  --ai --ai-since "90 days ago" --ai-metrics ai-metrics.example.json --assess
```

### 1. Summary (look here first)

```
Summary
-------
Name           : quarkusdroneshop-web
Score          : 115 points -> Small
SLOC           : 8,441
Files          : 172
Size Bands     : Tiny(<100) / Small(100-300) / Medium(300-700) / Large(700-1500) / Enterprise(1500+)
```

- **Score / classification**: the raw value of each metric multiplied by the weight in `weights.json` and summed (see "Scoring and size classification" for the formula). The classification just shows which `Size Bands` bucket the score falls into -- it carries no further meaning (good/bad). It is purely a relative-size indicator.
- **SLOC / Files**: total lines and files scanned. Including vendored/third-party code inflates this -- see "Notes on usage".

### 2. Overall Assessment (with `--assess`; a diagnostic scorecard only)

```
Overall Assessment (heuristic scorecard, --assess)
------------------------------------------------------------
Project Size        : Small

Maintainability     : A-  (90/100)
Architecture        : F  (50/100)
Cloud Native        : F  (40/100)
Documentation       : C-  (70/100)
AI Readiness        : 69/100
Overall Score       : 67/100 (D)
```

- Five categories (Maintainability / Architecture / Cloud Native / Documentation / AI Readiness) are each scored 0-100 and converted into a letter grade (A+ through F, the same conversion used on an ordinary school report card). Every category's rubric is **spelled out in full** in the "Overall Assessment (--assess)" section, so you can always trace why a grade came out the way it did.
- **This never affects the Effort Estimate (person-months)**. Like Score, it's purely a diagnostic, relative-comparison figure for scale and maturity.
- Category weights (default: Maintainability 35% / Architecture 25% / Cloud Native 15% / Documentation 15% / AI Readiness 10%) are externalized to `assessment.json`, and can be rebalanced to your organization's judgment via `--assessment FILE`.
- A category with no available data (e.g. AI Readiness when neither `--ai` nor `--ai-metrics` was passed) shows `N/A` and is excluded from the Overall Score calculation (the remaining categories' weights are renormalized).
- In this `quarkusdroneshop-web` example, Architecture/Cloud Native score `F` simply because the project has no microservices decomposition and no Kubernetes manifests (the rubric's bonus conditions aren't met) -- it does not mean "bad code".

### 3. Effort Estimate (with `--effort`; for contracts/planning this is the only number you need)

```
Effort Estimate (productivity: productivity.json)
  Java SLOC    : 3,323  (rate 3.94 SLOC/hour) -> 5.3 PM
  Node SLOC    : 3,720  (TS+JS, rate 3.94 SLOC/hour) -> 5.9 PM
  Total        : 11.2 PM  <- Base PM (contract/planning figure)
```

- **Base PM (the Total line)**: a contract/planning-grade person-months figure, mechanically reproducible from SLOC and `productivity.json` alone. The same code size always yields the same value.
- If you're not using APF, this is the end of the story. **Use this number alone for estimation.**

```
  APF (AI Productivity Factor): 0.82  (source: ai-metrics.example.json)
  Estimated PM (AI-adjusted)  : 9.2 PM  (= 11.2 base x 0.82)
    Java: 4.3 PM, Node: 4.8 PM
  Basis (judged by whoever set APF, not computed by this tool):
    AI Generated Ratio (%)  : 40
    AI Accept Rate (%)      : 65
    AI Test Generation      : Yes
    AI Review Used          : Yes
    AI Refactoring Used     : Yes
```

- An additional block that only appears when `--ai-metrics`'s file contains `ai_productivity_factor` (APF). **Base PM is unchanged; a separate number obtained by multiplying by APF is simply added.**
- `Estimated PM (AI-adjusted)` is "a reference figure assuming AI usage" -- **whether to use it instead of Base PM is the estimator's call**. The tool does not decide which one is "correct".
- `Basis` is a record of what the person who entered the APF value (0.82) based their judgment on. The tool does not compute APF from this basis (deliberately -- turning it into a formula would mean the threshold-setting itself becomes an editorial judgment call). It exists purely so the number can be checked for reasonableness after the fact.

### 4. Project through Dependencies (the size breakdown)

The raw figures that feed into the Score. Cross-reference them with the weight table in "Scoring and size classification" to see which factors are pushing the Score up (e.g. a project with many `Modules` or many `REST APIs` gets a larger contribution from the API/Module terms). See "Metrics collected" for how each item is derived. `Coverage` under `Complexity` is `N/A` unless a jacoco.xml or similar file is found (never guessed).

### 5. AI Development (with `--ai`; diagnostic only, not used for estimation)

```
AI Development (git-derived + optional external metrics)
------------------------------------------------------------
Repos analyzed    : 1
Commits analyzed  : 57
Lines Added       : 7,958
Lines Deleted     : 2,530
Net Change        : +5,428
Refactoring Ratio : 40.0% (balanced-churn heuristic: ...)
                    0.0% of commits mention "refactor" in the message (keyword heuristic)
AI Co-authored    : 52.6% of commits (30/57), 13.7% of lines added
```

- This is a **section independent of Effort Estimate**; nothing here changes PM (APF only ever uses the value you put directly in `ai-metrics.json`).
- `AI Co-authored` is a **lower bound** on AI involvement detectable via commit trailers -- actual AI assistance is likely higher (see the caveat in "AI Development" for details).
- The `External AI metrics` table just displays the raw values loaded from `--ai-metrics` as-is (accept rate, review time, etc.).

### 6. HTML report (with `--html`)

The same content, rendered with charts, in the order: **top summary + PM cards** -> **Overall Assessment** -> **Size Classification gauge** -> **SLOC/Score breakdown charts** -> **Effort Estimate (with APF)** -> **AI Development** -> **detail tables**. Since it's all visible just by opening it in a browser, it's better suited than the text report for explaining results to others. See "HTML report" for generation and layout details.

### In short

- **There is exactly one number to use for contracts/planning: the `Total` line under `Effort Estimate` (Base PM).**
- If you want a reference figure that accounts for AI's effect, look at `Estimated PM (AI-adjusted)` (understanding that APF is a human-judged number).
- The `Overall Assessment` and `AI Development` sections, and Score/classification, are all **diagnostic information** about scale and development reality -- none of it is reflected in person-months.

```
python3 software_size.py [PATH] [--name NAME] [--json] [--weights FILE] [--effort]
                          [--productivity FILE] [--html FILE]
                          [--ai] [--ai-since WHEN] [--ai-metrics FILE]
                          [--assess] [--assessment FILE]
```

- `PATH`: directory to scan (default: current directory)
- `--name`: project name shown in the report
- `--json`: also print metrics/score/PM estimate as JSON
- `--weights FILE`: override the weight table (see `weights.json`)
- `--effort`: also show the person-months estimate from Java SLOC / Node (TS+JS) SLOC in the text report (the HTML report always shows it)
- `--productivity FILE`: override the person-months productivity table (see `productivity.json`; details under "Person-months estimate")
- `--html FILE`: write a rich, chart-enabled HTML report to the given path (details under "HTML report")
- `--ai`: add the AI Development section (git-derived Lines Added/Deleted, Refactoring Ratio, AI-coauthored-commit ratio; details under "AI Development")
- `--ai-since WHEN`: narrow the git history analyzed by `--ai` (e.g. `"90 days ago"`); recommended for large/vendored histories
- `--ai-metrics FILE`: load AI-related metrics that git can't provide (AI-generated code ratio, Copilot accept rate, etc.) from an external file (see `ai-metrics.example.json`; never guessed if omitted). If it contains `ai_productivity_factor`, the adjusted PM is also shown regardless of whether `--ai` is passed (details under "Separating the estimation model from the diagnostic model")
- `--assess`: add the Overall Assessment scorecard (letter grades for Maintainability/Architecture/Cloud Native/Documentation, AI Readiness, Overall Score; details under "Overall Assessment")
- `--assessment FILE`: override the Overall Assessment category weights (see `assessment.json`)

`sizecheck.sh` is a wrapper that externalizes the application name, whether to generate HTML, the AI Development section, and the Overall Assessment section as parameters (and prints a header when run):

```
bash sizecheck.sh [APP_NAME] [GENERATE_HTML] [GENERATE_AI] [GENERATE_ASSESS]
# or via environment variables
APP_NAME=myapp GENERATE_HTML=false GENERATE_AI=true GENERATE_ASSESS=false bash sizecheck.sh
```

- `APP_NAME`: application name shown in the report (default: `quarkusdroneshop`)
- `GENERATE_HTML`: `true`/`false`, toggles whether `report.html` is generated (default: `true`)
- `GENERATE_AI`: `true`/`false`, toggles the AI Development section (default: `false`). When `true`, `ai-metrics.json` is automatically loaded as `--ai-metrics` if present in the current directory
- `GENERATE_ASSESS`: `true`/`false`, toggles the Overall Assessment section (default: `true`). `assessment.json` is automatically loaded as `--assessment` if present

Example run:

```
$ bash sizecheck.sh
============================================================
 Software Size Report
------------------------------------------------------------
 Application  : quarkusdroneshop
 Generate HTML: true
 Generate AI  : false
 Generate Assess: true
============================================================
Software Size Summary
...
```

(This directory is itself assumed to be a subdirectory of the workspace being measured, hence the internal `..`. When using this for another project, adjust the path inside `sizecheck.sh`.)

## Metrics collected

- **Code**: per-language SLOC and file counts via `cloc` (used if installed, otherwise a simple built-in fallback)
- **Architecture**: Modules (directories containing pom.xml/package.json/build.gradle/go.mod/pyproject.toml etc.), Microservices (directories containing a Dockerfile/Containerfile), REST APIs (`@Path` / NestJS `@Get` etc. / Express `router.get` etc. / FastAPI & Flask decorators), GraphQL APIs (`.graphql(s)` files, `@GraphQLApi`, `@Resolver`), Camel Routes (`from("...")`), Kafka Topics (`mp.messaging.*.topic=`, Strimzi `KafkaTopic` CRs, `@Channel`/`@Topic`)
- **Data**: DB Tables (`@Table(name=...)`, SQL `CREATE TABLE`), Entities (`@Entity`), OpenAPI/AsyncAPI Specs (detected via leading keys in YAML/JSON)
- **Cloud Native**: `kind: Deployment/StatefulSet/CronJob`, Helm Charts (`Chart.yaml`), Operators (`kind: ClusterServiceVersion`)
- **Complexity**: a simple cyclomatic-complexity heuristic that extracts function bodies via regex + brace matching and counts if/for/while/case/catch/&&/||/ternary operators (a stand-in for a static-analysis tool like lizard; approximate)
- **Dependencies**: Maven Modules (`pom.xml` count), Node Packages (unique dependency+devDependency names across all `package.json`), Container Images (directories containing a Dockerfile)

All of these are regex-based heuristics, not measurements from a certified static-analysis tool (the goal is relative comparison and rough sizing, not precision).

## Scoring and size classification

`weights.json`'s weights are applied directly to each metric's raw value and summed (no normalization):

| Metric | Weight | Target |
|---|---|---|
| KLOC | 1 | Total SLOC / 1000 |
| API | 5 | REST APIs + GraphQL APIs |
| Camel Route | 3 | Camel Routes |
| Kafka Topic | 2 | Kafka Topics |
| DB Table | 2 | Database Tables |
| Deployment | 2 | Deployments |
| Module | 4 | Modules |
| Complexity | 10 | Average CC |

Classification thresholds (score upper bound is exclusive):

| Score | Classification |
|---|---|
| <100 | Tiny |
| 100-300 | Small |
| 300-700 | Medium |
| 700-1500 | Large |
| 1500+ | Enterprise |

Pass a different JSON to `--weights` to swap out just the weights and recompute.

## Person-months estimate (--effort) and externalizing the productivity table (--productivity)

Estimates person-months separately from Java SLOC and Node (TypeScript+JavaScript combined) SLOC. The formula is the same for both:

```
Person-months = SLOC / (rate_sloc_per_hour of the matching SLOC band x hours_per_person_month)
```

The productivity table is externalized to `productivity.json`, and `--productivity FILE` lets you swap in your own company's values. The default (`productivity.json`, shipped in this repo) adopts, as-is, the SLOC-band productivity medians (SLOC/hour) from **IPA's "Software Development Analysis Data Collection 2022" Table A1-2-4 (New Development: All Years, n=1,246)**:

```json
{
  "hours_per_person_month": 160,
  "java": {
    "bands": [
      {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
      {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
      {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
      {"max_sloc": null, "rate_sloc_per_hour": 5.92}
    ]
  },
  "node": {
    "bands": [
      {"max_sloc": 40000, "rate_sloc_per_hour": 3.94},
      {"max_sloc": 100000, "rate_sloc_per_hour": 5.15},
      {"max_sloc": 300000, "rate_sloc_per_hour": 5.76},
      {"max_sloc": null, "rate_sloc_per_hour": 5.92}
    ]
  }
}
```

- List `bands` in ascending SLOC order. `max_sloc` is that band's (exclusive) upper bound; the last band has no upper bound, so use `null`.
- `java` and `node` can be set independently, so if your company's measured productivity differs between Java and Node you can enter different values for each (IPA's public data makes no such distinction, so this tool's default uses the same table for both).
- If `--productivity` isn't passed, the embedded default above is used as-is (note: editing `productivity.json` has no effect unless you explicitly pass `--productivity productivity.json`).

**Example of using your own company's productivity**: if you know from measurement that "Java delivers 800 SLOC/person-month" and "Node delivers 1200 SLOC/person-month" (a flat rate regardless of size band), just define a single band each, as in the bundled `productivity.example.json`:

```json
{
  "hours_per_person_month": 160,
  "java": {
    "bands": [
      {"max_sloc": null, "rate_sloc_per_hour": 5.0}
    ]
  },
  "node": {
    "bands": [
      {"max_sloc": null, "rate_sloc_per_hour": 7.5}
    ]
  }
}
```

(5.0 SLOC/hour x 160 hours = 800 SLOC/person-month; 7.5 x 160 = 1200 SLOC/person-month)

```
python3 software_size.py . --weights weights.json --effort --productivity productivity.example.json
```

**Important caveat (about the default values)**: IPA's public data does not include a productivity table split by Java vs. JavaScript/Node.js. Programming languages are only tallied as a distribution of project counts (Java 42.4%, JavaScript 1.9%, out of 1,476 projects), and productivity is only published as an overall, mixed-language table by SLOC size band. Node.js doesn't even exist as its own category in IPA's survey items. So `productivity.json`'s default is not a "for Java" vs. "for Node" distinction -- **it's simply the same overall table applied to Java's SLOC size and Node's SLOC size separately** -- treat it as a rough-order-of-magnitude estimate, not a precise per-language benchmark. If you have your own measured values, you're strongly encouraged to override them via `--productivity`.

## HTML report (--html)

Passing `--html FILE` generates a self-contained HTML file (inline SVG charts) that needs no external libraries or internet connection.

```
python3 software_size.py . --name quarkusdroneshop --weights weights.json --effort \
  --productivity productivity.json --html report.html
```

`sizecheck.sh` already has this command set up, so running `bash sizecheck.sh` alone generates `report.html`. Once generated, open it directly in a browser, or check it via a simple server:

```
python3 -m http.server 8000
# -> http://localhost:8000/report.html
```

Report layout:

1. **Top (summary)**: Software Size Score, classification (Tiny-Enterprise), Total SLOC, and **Java/Node/total person-months** as cards at the very top
2. **Size Classification**: a gauge showing where the score falls between Tiny and Enterprise
3. **SLOC by Language** / **Score Breakdown by Weight Category**: bar charts
4. **Effort Estimate (Person-Months)**: a bar chart comparing Java/Node person-months, with the productivity table's source noted
5. **Architecture / Data / Cloud Native / Complexity / Dependencies**: detail tables

`report.html` is a generated artifact, so it's listed in `.gitignore` and excluded from commits.

## AI Development (--ai)

Adds, opt-in via `--ai`, the perspective being discussed by US companies (GitHub/Microsoft/Google/McKinsey/ISBSG, etc.) through 2025-2026: not just "how much code", but "how much did AI help, and what did humans spend their time on". Implemented on the principle that **only metrics that can actually be verified from git are computed automatically; anything that can't be verified is never fabricated and is only accepted from an external file.**

### Git-derived metrics (computed automatically, always real data)

With `--ai`, the following is computed across **every `.git` repository** found under the scanned path (this tool assumes a multi-repo workspace, so it aggregates across each subproject's `.git`):

| Metric | What it is |
|---|---|
| Lines Added / Lines Deleted | sum from `git log --no-merges --numstat` |
| Refactoring Ratio (balanced-churn) | per commit, `2 x min(added,deleted) / (added+deleted)`, averaged weighted by churn. A heuristic that trends higher the more a change looks like "rewriting existing code" rather than pure addition/deletion |
| Refactoring Ratio (keyword) | fraction of commits whose first message line contains "refactor" |
| AI Co-authored Commit Ratio | fraction of commits containing a `Co-Authored-By: <tool>` trailer (regex-matched against Claude, Copilot, Cursor, Codeium, ChatGPT/OpenAI, Gemini, Devin, Windsurf, Tabnine, CodeWhisperer, Amazon Q, etc.), plus the fraction of added lines in those commits |

```
python3 software_size.py . --ai --ai-since "90 days ago"
```

**Important caveat**: `AI Co-authored` can only detect tools that add a commit trailer (Claude Code does so by default). Assistance that leaves no trace in the commit, like GitHub Copilot's ordinary autocomplete, cannot be captured, so **this number is a lower bound on AI involvement** -- actual AI-assistance rates may well be higher. `Refactoring Ratio` is likewise a heuristic, not an AST-level determination of what counts as refactoring.

**Performance note**: when the workspace includes a large amount of vendored/third-party history (e.g. `developerhub-skeleton/backstage`, roughly 71,000 commits, in this workspace), running against the full history can take over 40 seconds for `git log --numstat` on that repo alone. Scoping to a recent period with `--ai-since "90 days ago"` is strongly recommended (in this repo, even 16 repos / ~720 commits completes in about 20 seconds when scoped).

### Metrics git can't provide (only reflected via --ai-metrics FILE; N/A if omitted)

AI-generated code ratio, Copilot/assistant accept rate, review time, coding time, prompt count, test-generation ratio, and so on **have no real data in git or on the filesystem** (you need actual measurements from the AI tool side: the GitHub Copilot Metrics API, Cursor's analytics, IDE plugin telemetry, etc.). Since plausible-looking numbers are never filled in by guesswork, the report shows "not provided" unless you pass `--ai-metrics FILE`.

`ai-metrics.example.json` (bundled, sample values):

```json
{
  "source": "GitHub Copilot Metrics API export, 2026-06 (example -- replace with real data)",
  "ai_generated_sloc": 18200,
  "ai_generated_ratio_pct": 43,
  "copilot_accept_rate_pct": 38,
  "estimated_review_hours": 120,
  "estimated_coding_hours": 420,
  "prompt_count": null,
  "test_generation_ratio_pct": null,
  "ai_productivity_factor": 0.82
}
```

```
python3 software_size.py . --ai --ai-metrics ai-metrics.example.json
```

Fields you don't know can stay `null` (they won't be shown in the report). In production, prepare an `ai-metrics.json` with real measured values and have it loaded automatically when running `sizecheck.sh` with `GENERATE_AI=true`.

### Separating the estimation model from the diagnostic model; AI Productivity Factor (APF)

For an estimate (person-months) to be useful, it matters that "the same input always produces the same result" and "the number can be explained" -- so this tool keeps the following two things clearly separate:

- **The estimation model** (`--effort`/`--productivity`): SLOC -> an IPA/COCOMO-style productivity table -> Base PM. The number used for contracts/planning, always reproducible from SLOC and `productivity.json` alone.
- **The AI diagnostic** (`--ai`): git-derived Lines Added/Deleted, Refactoring Ratio, AI-coauthored-commit ratio. Purely observational/diagnostic, **never used to compute Base PM**.

If you still want AI to be reflected in person-months, rather than directly multiplying in a quality score like `AI Readiness`, this tool adopts the approach of entering, as a plain number, a **measured or agreed-upon multiplier** into `ai-metrics.json`'s `ai_productivity_factor`:

```
Estimated PM (AI-adjusted) = Base PM x APF
Example: 714.2 x 0.82 = 585.6
```

- If `ai_productivity_factor` is set, the Effort Estimate section shows both `Base PM` and `Estimated PM (AI-adjusted)`, regardless of whether `--ai` is also passed (Base PM is never altered and remains the contract figure).
- A formula that auto-derives APF from AI code-generation rate, acceptance rate, whether test generation was used, etc. is not implemented, because deciding the thresholds/weights for such a formula is itself an editorial judgment call. **Instead, `ai-metrics.json` lets you record the AI generation/accept rate and whether test generation/review/refactoring were used, and these are displayed alongside the APF value as its "basis"**. APF itself is never computed automatically -- the person entering it (whoever is looking at the actual measured data and making the call) enters a plain number that reflects their judgment of these items:

```json
{
  "ai_generated_ratio_pct": 40,
  "copilot_accept_rate_pct": 65,
  "ai_test_generation_used": true,
  "ai_review_used": true,
  "ai_refactoring_used": true,
  "ai_productivity_factor": 0.82,
  "ai_productivity_factor_note": "Judged by <name/team>, <date>: ..."
}
```

This results in the following being shown in the Effort Estimate section:

```
APF (AI Productivity Factor): 0.82  (source: ai-metrics.json)
Estimated PM (AI-adjusted)  : 585.6 PM  (= 714.2 base x 0.82)
Basis (judged by whoever set APF, not computed by this tool):
  AI Generated Ratio (%)  : 40
  AI Accept Rate (%)      : 65
  AI Test Generation      : Yes
  AI Review Used          : Yes
  AI Refactoring Used     : Yes
Note: Judged by <name/team>, <date>: ...
```

`ai_productivity_factor_note` is optional, for recording who judged it, when, and how (for auditing/re-verification).

## Overall Assessment (--assess)

`--assess` produces a heuristic scorecard, separate from size (Score) and person-months (PM), that scores five categories -- **Maintainability, Architecture, Cloud Native, Documentation, AI Readiness** -- each 0-100, converts them into letter grades (A+ through F), and combines them into a weighted **Overall Score**. **It has zero effect on Base PM/APF** (fully independent from the estimation model).

### Letter grade thresholds

Uses a standard conversion, the same as an ordinary school report card (not an arbitrary cutoff invented for this tool):

| Score | Grade | Score | Grade | Score | Grade |
|---|---|---|---|---|---|
| 97-100 | A+ | 83-86 | B | 60-69 | D |
| 93-96 | A | 80-82 | B- | 0-59 | F |
| 90-92 | A- | 77-79 | C+ | | |
| 87-89 | B+ | 73-76 | C | | |
| | | 70-72 | C- | | |

### Per-category scoring rules (rubrics)

Every one is a checklist that spells out exactly "what earns how many points". Indicators that turn an existing metric's ratio directly into a score (e.g. number of OpenAPI spec files divided by number of REST API endpoints) are deliberately not used, because comparing values in mismatched units looks precise while not actually reflecting reality.

- **Maintainability**: averages Average CC (lower is better: <=5 -> 100, <=8 -> 90, <=12 -> 75, <=20 -> 55, above that -> 35) with Coverage if known. `N/A` if neither is available. **Maximum CC is deliberately not used** (this tool's complexity measurement is a regex-based brace-matching heuristic that can spike unrealistically on minified/vendored front-end bundles, so a single outlier shouldn't be allowed to swing the grade).
- **Architecture**: base score 50 + 15 if Modules >= 2 + 15 if Microservices >= 2 + 10 if any OpenAPI Spec exists + 10 if any AsyncAPI Spec exists (capped at 100).
- **Cloud Native**: base score 40 + 20 if any Deployments exist + 15 if any Helm Charts exist + 10 if any StatefulSets or CronJobs exist + 15 if Deployments count is at least half of Microservices count (capped at 100).
- **Documentation**: scored from the ratio of Markdown SLOC to Total SLOC (>=8% -> 100, >=4% -> 85, >=2% -> 70, >=0.5% -> 55, below that -> 35), plus a +10 bonus if any OpenAPI/AsyncAPI spec exists. Vendored Markdown (e.g. an upstream project's CHANGELOG) inflates this just like it inflates SLOC.
- **AI Readiness**: averages whichever of the following are available: `--ai`'s AI-coauthored-commit ratio, and `--ai-metrics`'s AI generation rate / accept rate / test-generation, review, and refactoring usage flags. **`N/A` if neither is available** (never guessed when there's no data).

### Category weights (assessment.json)

Default weights (`assessment.json`, sum to 100%):

```json
{
  "maintainability": 35,
  "architecture": 25,
  "cloud_native": 15,
  "documentation": 15,
  "ai_readiness": 10
}
```

Use `--assessment FILE` to swap in weights that match your organization's judgment. If a category is `N/A`, its weight is excluded and the Overall Score is computed by renormalizing across the remaining categories' weights (e.g. if AI Readiness is `N/A`, the calculation is redone as if the remaining 90% of weight were 100%).

### Important caveats

- Each category's thresholds (CC <=5 = 100 points, Markdown ratio 8% = 100 points, etc.) are **standards this tool has chosen, not an absolute quality bar**. What's appropriate varies by organization, so first use this for relative and time-series comparison within your own project(s).
- A project without a microservices setup scoring low on Architecture/Cloud Native does not mean "a simple, single-responsibility design is being penalized" -- it's a consequence of the rubric awarding points for "multiple modules, multiple services, K8s manifests". It does not mean a monolithic design is bad.
- Overall Assessment affects neither `Score` (size) nor `Effort Estimate` (person-months). The three models (size score / estimation model / diagnostic scorecard) are completely independent.

## Notes on usage

- Scanning a directory that includes vendored code (third-party vendoring, etc.) as-is inflates both SLOC and person-months beyond reality. If you want to estimate only your own development, either scope down to the relevant subdirectory or consider adding to `EXCLUDE_DIRS`.
- Coverage is only computed if a jacoco.xml or coverage-summary.json is found; otherwise it's N/A.
- Omitting `--productivity` uses the built-in IPA default. If you want to always use your own company's values, include `--productivity productivity.json` (or your own file) in `sizecheck.sh`.
- `--ai` is disabled by default (opt-in). If you enable it on a large workspace containing vendored repositories, scope the period with `--ai-since` (see the performance note).
- `--assess`'s letter grades are a relative evaluation from this tool's own rubric, not an industry-standard certification. Every threshold is documented in this README, so if it doesn't match your internal standards, adjust the weights via `assessment.json`, or adjust the thresholds directly in `software_size.py`'s scoring functions (`score_maintainability`, etc.).

## Changelog (major feature additions)

1. **Initial version**: measures SLOC/architecture/data/cloud-native/complexity/dependencies, computes a Score via `weights.json`'s weights, classifies into Tiny-Enterprise.
2. **Added person-months estimate** (`--effort`): estimates person-months from Java/Node SLOC using IPA Table A1-2-4's SLOC-band productivity.
3. **Externalized the productivity table** (`--productivity`): externalized the IPA default to `productivity.json`, swappable for your own company's values (also added `productivity.example.json`).
4. **Changed the text report's display order**: unified the previous "details -> summary" order into "summary (Score/PM) -> details".
5. **Added an HTML report** (`--html`): a self-contained HTML with inline SVG charts, no external libraries or internet connection needed. Summary/PM placed at the top.
6. **Parameterized `sizecheck.sh`**: `APP_NAME`/`GENERATE_HTML`/`GENERATE_AI` can now be set via arguments or environment variables (with a printed header at run time).
7. **Added AI Development** (`--ai`): measures Lines Added/Deleted, Refactoring Ratio, and AI-coauthored-commit ratio from git, across every `.git` repository. Metrics git can't measure (AI generation rate, accept rate, etc.) are input externally via `--ai-metrics FILE` (never fabricated).
8. **Added AI Productivity Factor (APF)**: while keeping the estimation model (Base PM) and the AI diagnostic model separate, multiplies Base PM by `ai-metrics.json`'s `ai_productivity_factor` (a human-judged number) only when you want AI's effect reflected in person-months. The basis for that judgment (AI generation rate, accept rate, whether test generation/review/refactoring were used) is also shown alongside it, for auditability.
9. **Added Overall Assessment** (`--assess`): adds letter grades for Maintainability/Architecture/Cloud Native/Documentation, plus AI Readiness and Overall Score, to the summary. Category weights are externalized to `assessment.json`, and every category's scoring rubric is documented in full in this README. Has zero effect on Base PM/APF -- implemented as an independent, third model.
