"""LXCat 形式断面積ファイルのパーサー (prompts/19)。

対応する2形式:

1. 標準ブロック形式 (Morgan 電子データ等):
   タイプ行 (ELASTIC/EFFECTIVE/EXCITATION/IONIZATION/ATTACHMENT)
   → 2行目 種名 → 3行目 パラメータ (elastic/effective: m/M、
   excitation/ionization: 閾値 eV。attachment はパラメータ行なし)
   → コメント行 (数字で始まらない) → `-----` (5個以上のダッシュ) で
   挟まれた 2 列テーブル (eV, m²)

2. タイプ行なし形式 (Phelps イオンデータ等):
   `SPECIES:`/`PROCESS:` 行 + テーブルのブロック。
   PROCESS 行の末尾語で判定: `Backscat` → backscat、`Isotropic` → isotropic

- `EFFECTIVE` は警告付きで elastic として取り込む
- `ATTACHMENT` は警告を出してスキップする
- species="electron" では elastic/excitation/ionization のみ、
  "ion" では isotropic/backscat のみ許可 (他は警告付きスキップ)
- ヘッダ・説明文・`xxxx`/`****` 区切り行は読み飛ばす
- 構造が壊れている場合 (テーブル区切りなし等) は ValueError
  (server.py が 422 に変換する)
"""

from __future__ import annotations

from .schema import XsProcess

# タイプ行キーワード → 内部 kind
_TYPE_KINDS = {
    "ELASTIC": "elastic",
    "EFFECTIVE": "effective",
    "EXCITATION": "excitation",
    "IONIZATION": "ionization",
    "ATTACHMENT": "attachment",
}

# 粒子種ごとに許可する kind
_ALLOWED = {
    "electron": {"elastic", "excitation", "ionization"},
    "ion": {"isotropic", "backscat"},
}

# タイプ行なし形式: PROCESS 行の末尾語 → kind
_TAIL_KINDS = {"backscat": "backscat", "isotropic": "isotropic"}


def _is_dash_line(s: str) -> bool:
    """テーブル区切り行 (5個以上のダッシュのみ) か判定する。"""
    return len(s) >= 5 and set(s) == {"-"}


def _read_table(lines: list[str], i: int) -> tuple[list[float], list[float], int]:
    """位置 i 以降で最初の `-----` 区切りから 2 列テーブルを読む。

    戻り値: (energy_ev, sigma_m2, 終了区切りの次の行番号)。
    """
    n = len(lines)
    while i < n and not _is_dash_line(lines[i].strip()):
        i += 1
    if i >= n:
        raise ValueError("断面積テーブルの開始区切り (-----) が見つかりません")
    i += 1
    e: list[float] = []
    s: list[float] = []
    while i < n:
        st = lines[i].strip()
        if _is_dash_line(st):
            i += 1
            break
        parts = st.split()
        if len(parts) < 2:
            raise ValueError(f"{i + 1} 行目: テーブル行を解釈できません: '{st}'")
        try:
            e.append(float(parts[0]))
            s.append(float(parts[1]))
        except ValueError as exc:
            raise ValueError(f"{i + 1} 行目: 数値を解釈できません: '{st}'") from exc
        i += 1
    else:
        raise ValueError("断面積テーブルの終了区切り (-----) が見つかりません")
    if not e:
        raise ValueError("断面積テーブルが空です")
    return e, s, i


def _parse_standard_block(lines: list[str], i: int):
    """標準ブロック (タイプ行あり) を解釈する。

    戻り値: (kind, label, threshold_ev, mass_ratio, energy, sigma, 次の行番号)。
    """
    kind_word = lines[i].strip()
    kind = _TYPE_KINDS[kind_word]
    if i + 1 >= len(lines):
        raise ValueError(f"{i + 1} 行目: {kind_word} ブロックの種名行がありません")
    target = lines[i + 1].strip()

    threshold_ev = 0.0
    mass_ratio = 0.0
    j = i + 2
    if kind != "attachment":  # attachment のみ 3 行目 (パラメータ行) が無い
        if j >= len(lines):
            raise ValueError(f"{kind_word} ブロックのパラメータ行がありません")
        try:
            val = float(lines[j].split()[0])
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"{j + 1} 行目: {kind_word} のパラメータ行を解釈できません: '{lines[j].strip()}'"
            ) from exc
        if kind in ("elastic", "effective"):
            mass_ratio = val
        else:
            threshold_ev = val
        j += 1

    # コメント行から PROCESS 行を探してラベルにする (テーブル開始まで)
    label = f"{kind_word} {target}"
    k = j
    while k < len(lines) and not _is_dash_line(lines[k].strip()):
        st = lines[k].strip()
        if st.startswith("PROCESS:"):
            label = st[len("PROCESS:"):].strip()
        k += 1

    e, s, i_next = _read_table(lines, j)
    return kind, label, threshold_ev, mass_ratio, e, s, i_next


def _parse_species_block(lines: list[str], i: int, warnings: list[str]):
    """タイプ行なし形式 (SPECIES:/PROCESS: ブロック) を解釈する。

    戻り値: (kind | None, label, energy, sigma, 次の行番号)。
    kind が None の場合は末尾語が未知 (警告済み) を意味する。
    """
    label = ""
    k = i + 1
    while k < len(lines) and not _is_dash_line(lines[k].strip()):
        st = lines[k].strip()
        if st.startswith("PROCESS:"):
            label = st[len("PROCESS:"):].strip()
        k += 1
    if not label:
        raise ValueError(f"{i + 1} 行目: SPECIES ブロックに PROCESS 行がありません")

    tail = label.replace(",", " ").split()[-1].strip(".").lower()
    kind = _TAIL_KINDS.get(tail)
    if kind is None:
        warnings.append(f"未知のプロセス種 '{tail}' をスキップしました: {label}")

    e, s, i_next = _read_table(lines, i + 1)
    return kind, label, e, s, i_next


def _append_process(
    processes: list[XsProcess],
    warnings: list[str],
    species: str,
    kind: str,
    label: str,
    threshold_ev: float,
    mass_ratio: float,
    energy: list[float],
    sigma: list[float],
) -> None:
    """種別フィルタ・EFFECTIVE 変換・単調性チェックを行いプロセスを登録する。"""
    if kind == "attachment":
        warnings.append(f"ATTACHMENT は未対応のためスキップしました: {label}")
        return
    if kind == "effective":
        warnings.append(
            f"EFFECTIVE (全運動量移行断面積) を elastic として取り込みました: {label}"
        )
        kind = "elastic"
    if kind not in _ALLOWED[species]:
        warnings.append(
            f"species='{species}' では kind='{kind}' は使えないためスキップしました: {label}"
        )
        return
    if any(energy[k + 1] < energy[k] for k in range(len(energy) - 1)):
        raise ValueError(f"エネルギー列が昇順ではありません: {label}")
    processes.append(
        XsProcess(
            kind=kind,
            label=label,
            threshold_ev=threshold_ev,
            mass_ratio=mass_ratio,
            energy_ev=energy,
            sigma_m2=sigma,
        )
    )


def parse_lxcat(text: str, species: str) -> tuple[list[XsProcess], list[str]]:
    """LXCat 形式テキストをパースして (processes, warnings) を返す。

    ブロックが 1 つも見つからない場合は ValueError を送出する
    (フィルタで全てスキップされた場合は空リスト + 警告)。
    """
    if species not in _ALLOWED:
        raise ValueError(f"species は 'electron' か 'ion' を指定してください: '{species}'")

    lines = text.splitlines()
    processes: list[XsProcess] = []
    warnings: list[str] = []
    n_blocks = 0

    i = 0
    while i < len(lines):
        st = lines[i].strip()
        if st in _TYPE_KINDS:
            kind, label, th, mr, e, s, i = _parse_standard_block(lines, i)
            n_blocks += 1
            _append_process(processes, warnings, species, kind, label, th, mr, e, s)
        elif st.startswith("SPECIES:"):
            # 標準ブロック内の SPECIES: 行はブロック解釈で消費済みなので、
            # ここに来るのはタイプ行なし形式のブロック先頭のみ
            kind, label, e, s, i = _parse_species_block(lines, i, warnings)
            n_blocks += 1
            if kind is not None:
                _append_process(processes, warnings, species, kind, label, 0.0, 0.0, e, s)
        else:
            i += 1  # ヘッダ・説明文・xxxx/**** 区切り等は読み飛ばす

    if n_blocks == 0:
        raise ValueError(
            "LXCat の断面積ブロックが見つかりません "
            "(タイプ行または SPECIES:/PROCESS: ブロックが必要です)"
        )
    return processes, warnings
