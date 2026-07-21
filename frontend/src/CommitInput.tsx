import { useEffect, useRef, useState } from "react";

/**
 * 数値入力の「確定時コミット」用コンポーネント。
 * - 入力中はローカル state (draft) だけを更新して見た目を追従させ、
 *   blur または Enter で初めて onCommit を呼ぶ。
 *   これにより onChange の度に Undo 履歴が積まれるのを防ぐ。
 * - Undo/Redo やファイル読込で外部から value が変わった場合は、
 *   フォーカスされていないときに限りローカル表示値を同期する
 *   (編集中に上書きされないようにするため)。
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
  const [draft, setDraft] = useState(String(value));
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) setDraft(String(value));
  }, [value]);

  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n)) {
      onCommit(n);
    } else {
      setDraft(String(value)); // 不正値は元の値に戻す
    }
  };

  return (
    <input
      type="number"
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
          setDraft(String(value));
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
