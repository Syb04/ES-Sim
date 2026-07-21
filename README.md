# ES-Sim

2Dスケッチ CAD + 静電場シミュレーション(FEM → 粒子軌道 → PIC)

仕様の全体像は **[docs/SPEC.md](docs/SPEC.md)** を参照。

## 構成

- `backend/` — Python 計算コア(FastAPI ローカルサーバー、gmsh メッシュ、P1-FEM)
- `frontend/` — Tauri 2 + React + TypeScript(CADキャンバス・結果ビューア)
- `examples/` — サンプルプロジェクト(JSON)
- `docs/SPEC.md` — 仕様書

## 必要環境

- Python 3.11+
- Node.js 20+
- Rust(stable。[rustup](https://rustup.rs/) で導入。Tauri のビルドに必要)
- (GPUオプション)NVIDIA GPU + CUDA 12.x → `pip install -e ".[gpu]"`

## セットアップと起動

### 1. バックエンド

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn es_sim.server:app --port 8317
```

テスト(解析解との比較):

```powershell
python -m pytest tests/
```

### 2. フロントエンド(別ターミナル)

```powershell
cd frontend
npm install
npm run tauri dev
```

アプリが起動したらツールバー右上に `backend v0.1.0` と表示されれば疎通OK。
「Solve (サンプル)」で平行平板+誘電体ブロックの電位分布が描画される。

Tauri を使わずブラウザで動作確認する場合は `npm run dev` → http://localhost:1420

## 現在の状態(フェーズ0: 雛形)

- [x] プロジェクトJSONスキーマ(pydantic)
- [x] gmsh 三角形メッシュ生成(電極=穴+Dirichlet、誘電体/電荷=領域タグ)
- [x] P1-FEM 静電場ソルバー(ベクトル化組み立て、splu 直接法、E・エネルギー算出)
- [x] 解析解テスト4件(平行平板の V/E/エネルギー、誘電体)
- [x] Tauri+React 雛形(パン/ズーム付きビューア、電位カラーマップ表示)

## フェーズ1 進捗

- [x] スケッチツール(選択/ポリライン/矩形/円、グリッドスナップ、Delete削除)
- [x] 材料割当UI(電極V/誘電体εr/電荷ρ)、境界条件パネル(4辺のNeumann/Dirichlet)
- [x] プロジェクトJSON保存/読込
- [x] 等電位線・|E|表示モード・電場ベクトル矢印・カラーバー
- [x] ラインプロファイル(`POST /profile` + 2点指定ツール・V/|E|グラフ・CSV保存)
- [x] 図形のドラッグ移動・矢印キー微動、Undo/Redo(Ctrl+Z/Y、履歴100件)
- [x] 頂点グリップ編集(頂点ドラッグ・中点挿入・ダブルクリック削除)
- [x] キャンバスルーラー、選択ヒットテスト改善、カラーバーラベル修正
- [x] 同軸円筒のメッシュ収束検証(`backend/verification/`、L2誤差の収束次数~2を確認)
- [x] 円領域のパラメトリック化(中心+半径で保存、メッシュ生成時に分割数をメッシュサイズへ連動)
## フェーズ2 進捗

- [x] 粒子軌道トレーサ(`POST /trace`: 隣接要素walk探索、リープフロッグ、境界吸収、dt自動推定)
- [x] 解析解テスト(一様場での加速エネルギー・飛行時間・放物軌道、いずれも誤差<1%)
- [x] エミッタ配置ツール(line/point)、粒子設定パネル(種・エネルギー・方向・広がり・dt/ステップ)
- [x] 軌道オーバーレイ表示・着地点・結果サマリ(吸収数/平均TOF/最終エネルギー)
- [ ] 着地点分布のヒストグラム表示
- [ ] フェーズ3: FEM-PIC

サブエージェントへの作業指示は `prompts/` に残している。

ロードマップ詳細と完了基準は仕様書 §12。
