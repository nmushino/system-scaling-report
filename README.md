# ソフトウェア規模計測ツール (software_size.py)

## 参考資料

- [ソフトウェア開発 分析データ集 2022 (IPA)](https://www.ipa.go.jp/digital/software-survey/metrics/hjuojm000000c6it-att/000102171.pdf) からチェック

## 概要

`software_size.py` は、指定ディレクトリ配下をスキャンして SLOC・アーキテクチャ・データ・クラウドネイティブ・複雑度などのメトリクスを収集し、重み付けした「Software Size Score」を算出、Tiny〜Enterpriseに分類するツール。単一リポジトリでもマルチリポジトリのワークスペース全体でも実行可能。

```
python3 software_size.py [PATH] [--name NAME] [--json] [--weights FILE] [--effort]
```

- `PATH` : スキャン対象ディレクトリ(省略時はカレントディレクトリ)
- `--name` : レポートに表示するプロジェクト名
- `--json` : メトリクス・スコア・人月試算を JSON でも出力
- `--weights FILE` : 重み設定を上書き(`weights.json` 参照)
- `--effort` : Java SLOC / Node(TS+JS) SLOC から IPA基準の人月概算を追加表示

`sizecheck.sh` に `python3 software_size.py . --name migration-toolkit --weights weights.json` を用意済み。

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

## 人月試算 (--effort) と IPA データの扱いについて

`--effort` はJava SLOCとNode(TypeScript+JavaScript合算)SLOCそれぞれから人月を概算する。根拠は **IPA「ソフトウェア開発分析データ集2022」表A1-2-4(新規開発:全年度, n=1,246)** のSLOC規模帯別・生産性中央値(SLOC/人時)テーブル。

| SLOC規模 | 生産性中央値 [SLOC/人時] |
|---|---|
| 40,000未満 | 3.94 |
| 40,000〜100,000未満 | 5.15 |
| 100,000〜300,000未満 | 5.76 |
| 300,000以上 | 5.92 |

1人月 = 160人時 換算(IPA資料の記載に準拠)。人月 = SLOC ÷ (生産性 × 160)。

**重要な注意**: IPAの公開データには、JavaとJavaScript/Node.jsを分けた生産性テーブルは存在しない。開発言語の集計はプロジェクト件数の分布(Java 42.4%、JavaScript 1.9%、対象1,476件中)のみで、生産性は全言語混在・SLOC規模帯別にしか公開されていない。またNode.js単体のカテゴリはIPAの調査項目にそもそも存在しない。そのため `--effort` は「Java用」「Node用」という区別ではなく、**同じ全体テーブルをJavaのSLOC規模とNodeのSLOC規模それぞれに当てはめているだけ**であり、精度の高い言語別ベンチマークではなくROM(概算)見積もりとして扱うこと。

## 実行結果例(本リポジトリ)

```
python3 software_size.py . --name migration-toolkit --weights weights.json --effort
```

- Total SLOC: 41,787(YAML 22,144 / Java 9,037 / Markdown 5,510 / TypeScript 3,724 / Python 1,323 / SQL 49)
- Score: 391点 → Medium
- Java 9,037 SLOC → 14.3人月、Node(TS+JS) 3,724 SLOC → 5.9人月、合計 20.2人月(IPA中央値ベースの概算)

## 使う上での注意点

- ベンダー取り込みコード(サードパーティのvendoring等)が含まれるディレクトリをそのままスキャンすると、SLOC・人月ともに実態より過大になる。自社開発分だけを見積もりたい場合は、対象サブディレクトリを絞って実行するか、`EXCLUDE_DIRS` の追加を検討すること。
- Coverageはjacoco.xml/coverage-summary.jsonが見つかった場合のみ算出され、無い場合はN/A。
