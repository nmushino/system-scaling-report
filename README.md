# ソフトウェア規模計測ツール (software_size.py)

## 参考資料

- [ソフトウェア開発 分析データ集 2022 (IPA)](https://www.ipa.go.jp/digital/software-survey/metrics/hjuojm000000c6it-att/000102171.pdf) からチェック

## 概要

`software_size.py` は、指定ディレクトリ配下をスキャンして SLOC・アーキテクチャ・データ・クラウドネイティブ・複雑度などのメトリクスを収集し、重み付けした「Software Size Score」を算出、Tiny〜Enterpriseに分類するツール。単一リポジトリでもマルチリポジトリのワークスペース全体でも実行可能。

```
python3 software_size.py [PATH] [--name NAME] [--json] [--weights FILE] [--effort]
                          [--productivity FILE] [--html FILE]
```

- `PATH` : スキャン対象ディレクトリ(省略時はカレントディレクトリ)
- `--name` : レポートに表示するプロジェクト名
- `--json` : メトリクス・スコア・人月試算を JSON でも出力
- `--weights FILE` : 重み設定を上書き(`weights.json` 参照)
- `--effort` : Java SLOC / Node(TS+JS) SLOC から算出した人月概算をテキストレポートにも表示(HTMLレポートには常に表示される)
- `--productivity FILE` : 人月換算の生産性テーブルを上書き(`productivity.json` 参照。詳細は「人月試算」の章)
- `--html FILE` : グラフ付きのリッチなHTMLレポートを指定パスに出力(詳細は「HTMLレポート」の章)

`sizecheck.sh` に以下を用意済み:

```
python3 software_size.py .. --name quarkusdroneshop --weights weights.json --effort --productivity productivity.json --html report.html
```

(このディレクトリ自身が測定対象ワークスペースのサブディレクトリという想定のため `..` を指定している。別プロジェクトで使う場合はパスを読み替える。)

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

## 使う上での注意点

- ベンダー取り込みコード(サードパーティのvendoring等)が含まれるディレクトリをそのままスキャンすると、SLOC・人月ともに実態より過大になる。自社開発分だけを見積もりたい場合は、対象サブディレクトリを絞って実行するか、`EXCLUDE_DIRS` の追加を検討すること。
- Coverageはjacoco.xml/coverage-summary.jsonが見つかった場合のみ算出され、無い場合はN/A。
- `--productivity` を省略するとビルトインのIPAデフォルトが使われる。企業独自の値を常用したい場合は `sizecheck.sh` に `--productivity productivity.json`(または自社ファイル)を含めておくこと。
