import { useEffect, useRef, useState } from "react";

/**
 * 数値を表示用の文字列に整形する。
 * - 絶対値が 1e5 以上、または 0 でなく 1e-3 未満のときは指数表記
 *   (例: `1.356e7`, `1e14`, `5.6e-10`) にする。
 *   有効数字は最大6桁程度に丸め、末尾の 0 は自動的に削られる。
 * - それ以外は通常の10進表記(従来通り)。
 * RF周波数(13.56MHz → 13.56e6)や dt、密度など、桁の大きい/小さい値を
 * 羅列表示("100000000000000" など)にしないための共通処理。
 */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1e5 || abs < 1e-3)) {
    // 有効数字約6桁に丸めてから指数表記の文字列に戻し、末尾の0を削る。
    // "e+" の "+" は見た目が煩雑になるため取り除く。
    return parseFloat(value.toExponential(6)).toExponential().replace("e+", "e");
  }
  return String(value);
}

/**
 * 数値入力の「確定時コミット」用コンポーネント。
 * - 入力中はローカル state (draft) だけを更新して見た目を追従させ、
 *   blur または Enter で初めて onCommit を呼ぶ。
 *   これにより onChange の度に Undo 履歴が積まれるのを防ぐ。
 * - Undo/Redo やファイル読込で外部から value が変わった場合は、
 *   フォーカスされていないときに限りローカル表示値を同期する
 *   (編集中に上書きされないようにするため)。
 * - `type="text"` + `inputMode="decimal"` にすることで `13.56e6` や
 *   `1e14`、`-1.5E-3` のような指数表記もそのまま入力・確定できる
 *   (ブラウザの number 入力の制約を避けるため)。
 */
interface NumberProps {
  value: number;
  step?: string;
  className?: string;
  disabled?: boolean;
}

export function CommitNumberInput({
  value,
  step,
  className,
  disabled,
  onCommit,
}: NumberProps & { onCommit: (value: number) => void }) {
  const [draft, setDraft] = useState(formatNumber(value));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setDraft(formatNumber(value));
  }, [value]);

  const commit = () => {
    // 全角スペースの混入などを軽く吸収しつつ Number() でパース。
    // 13.56e6 / 1e14 / -1.5E-3 のような指数表記もそのまま解釈される。
    const n = Number(draft.trim());
    if (draft.trim() !== "" && Number.isFinite(n)) {
      onCommit(n);
      setDraft(formatNumber(n)); // 確定値を整形して表示に反映
    } else {
      setDraft(formatNumber(value)); // パース不能なら元の値に戻す
    }
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      step={step}
      className={className}
      disabled={disabled}
      value={draft}
      onFocus={() => {
        focusedRef.current = true;
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focusedRef.current = false;
        commit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(formatNumber(value));
          e.currentTarget.blur();
        }
      }}
    />
  );
}

/**
 * null 許容の数値入力 (dt の「空欄=自動」など) の確定時コミット版 (prompts/59)。
 * - 空欄で確定すると onCommit(null)
 * - CommitNumberInput と同様に blur/Enter で確定するため、`3e-11` のような
 *   指数表記を途中入力で弾かれずに入力できる
 */
export function CommitNullableNumberInput({
  value,
  placeholder,
  className,
  disabled,
  onCommit,
}: {
  value: number | null;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  onCommit: (value: number | null) => void;
}) {
  const [draft, setDraft] = useState(value === null ? "" : formatNumber(value));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setDraft(value === null ? "" : formatNumber(value));
  }, [value]);

  const commit = () => {
    const t = draft.trim();
    if (t === "") {
      onCommit(null);
      setDraft("");
      return;
    }
    const n = Number(t);
    if (Number.isFinite(n)) {
      onCommit(n);
      setDraft(formatNumber(n));
    } else {
      setDraft(value === null ? "" : formatNumber(value)); // パース不能なら元に戻す
    }
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      className={className}
      disabled={disabled}
      placeholder={placeholder}
      value={draft}
      onFocus={() => {
        focusedRef.current = true;
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focusedRef.current = false;
        commit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(value === null ? "" : formatNumber(value));
          e.currentTarget.blur();
        }
      }}
    />
  );
}

interface TextProps {
  value: string;
  className?: string;
}

export function CommitTextInput({
  value,
  className,
  onCommit,
}: TextProps & { onCommit: (value: string) => void }) {
  const [draft, setDraft] = useState(value);
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setDraft(value);
  }, [value]);

  const commit = () => {
    if (draft !== value) onCommit(draft);
  };

  return (
    <input
      type="text"
      className={className}
      value={draft}
      onFocus={() => {
        focusedRef.current = true;
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        focusedRef.current = false;
        commit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(value);
          e.currentTarget.blur();
        }
      }}
    />
  );
}
