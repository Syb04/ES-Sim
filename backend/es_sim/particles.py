"""荷電粒子軌道追跡 (フェーズ2)。仕様書 §8 参照。

予定 API:
    trace(project, mesh, solution, source, dt, n_steps) -> Trajectories

実装方針:
- 粒子位置 → 所属三角形の特定: walk 探索 + 前回要素キャッシュ
- E 補間: P1 要素なので要素内一定 (将来、節点平均場の重心座標補間に変更可)
- 積分器: リープフロッグ (静電場のみ。磁場を導入する際に Boris 化)
- 全粒子を numpy 一括で進め、backend.get_xp() で CuPy に切り替え可能にする
- 電極・外周到達で吸収し、衝突位置・エネルギーを記録
"""

from __future__ import annotations

QE = 1.602176634e-19   # 電気素量 [C]
ME = 9.1093837015e-31  # 電子質量 [kg]
MP = 1.67262192369e-27 # 陽子質量 [kg]

# TODO(phase2): 実装
