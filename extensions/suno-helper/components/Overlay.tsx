// Suno UI 上に注入する draggable overlay の shell (#892)。
// 既存 <App /> をそのまま埋め込み、drag handle・最小化・表示 toggle・位置永続化だけを足す。
// overlay の実マウント（Shadow DOM）は entrypoints/overlay.content.ts が担う。
import { useCallback, useEffect, useRef, useState } from "react";

import { onMessage, sendMessage } from "../lib/messaging";
import {
  clampPosition,
  hiddenStyle,
  type OverlayState,
  readOverlayState,
  toggleHidden,
  topRightPosition,
  writeOverlayState,
} from "../lib/overlay-state";
import { App } from "./App";
import { ReloadRequiredNotice } from "./ReloadRequiredNotice";
import { useDraggable } from "./useDraggable";

/** overlay shell の固定幅 (px)。clamp の初期サイズと top-right 初期位置の算出に使う。 */
const OVERLAY_WIDTH = 360;

interface Point {
  x: number;
  y: number;
}

/**
 * 永続化状態を読み込むゲート。読み込み完了まで何も描画せず、完了後に初期状態を OverlayShell へ渡す。
 * useDraggable の初期位置は mount 時に一度だけ確定するため、非同期読み込み後に shell を mount する。
 */
export function Overlay() {
  // undefined=読み込み中 / null=未保存 / OverlayState=復元。
  const [initial, setInitial] = useState<OverlayState | null | undefined>(undefined);
  const [reloadRequired, setReloadRequired] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const version = browser.runtime.getManifest().version;
        const handshake = await sendMessage("extensionVersionHandshake", { version });
        if (!handshake.matches) {
          setReloadRequired(true);
          return;
        }
        setInitial((await readOverlayState()) ?? null);
      } catch (error) {
        console.warn(
          "[suno-helper] overlay の初期化に失敗しました（拡張更新後はタブを再読み込みしてください）:",
          error,
        );
        setReloadRequired(true);
      }
    })();
  }, []);

  if (reloadRequired) {
    return <ReloadRequiredNotice />;
  }
  if (initial === undefined) {
    return null;
  }
  return <OverlayShell initial={initial} />;
}

function initialPosition(initial: OverlayState | null): Point {
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  // 高さは mount 後に getBoundingClientRect で実測されるため、初期 clamp は幅のみ厳密に効かせる。
  const size = { width: OVERLAY_WIDTH, height: 0 };
  // 復元時は保存位置を現在 viewport へ clamp する (要件2)。未保存は右上に出す (要件1)。
  return initial ? clampPosition(initial.position, viewport, size) : topRightPosition(viewport, size);
}

function OverlayShell({ initial }: { initial: OverlayState | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [minimized, setMinimized] = useState(initial?.minimized ?? false);
  const [hidden, setHidden] = useState(initial?.hidden ?? false);
  const [reloadRequired, setReloadRequired] = useState(false);

  const persist = useCallback((state: OverlayState) => {
    void writeOverlayState(state).catch((error: unknown) => {
      console.warn(
        "[suno-helper] overlay state の保存に失敗しました（拡張更新後はタブを再読み込みしてください）:",
        error,
      );
      setReloadRequired(true);
    });
  }, []);

  // 一度だけ登録する toggle リスナーや非同期 commit から最新値を読むための ref。
  // ref はレンダー中に書かず commit 後の effect で同期する（react-hooks/refs。読み手は全て非同期ハンドラ）。
  const minimizedRef = useRef(minimized);
  const hiddenRef = useRef(hidden);
  useEffect(() => {
    minimizedRef.current = minimized;
    hiddenRef.current = hidden;
  }, [minimized, hidden]);

  const onCommit = useCallback(
    (position: Point) => persist({ position, minimized: minimizedRef.current, hidden: hiddenRef.current }),
    [persist],
  );

  const { position, dragging, onPointerDown } = useDraggable({
    initial: initialPosition(initial),
    elementRef: containerRef,
    onCommit,
  });
  // position も同様にレンダー中ではなく commit 後の effect で ref へ同期する（読み手は非同期ハンドラ）。
  const positionRef = useRef(position);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  // action クリック（background → toggleOverlay）で表示を切り替える (要件5)。
  // hidden=true でも OverlayShell は unmount せず CSS で隠すため（要件1/3）、この effect は
  // 表示状態に関わらず常に生存し、hidden→visible への復帰メッセージを受け取れる (#897)。
  useEffect(() => {
    const unwatch = onMessage("toggleOverlay", () => {
      setHidden((prev) => {
        const next = toggleHidden({ position: positionRef.current, minimized: minimizedRef.current, hidden: prev });
        persist(next);
        return next.hidden;
      });
    });
    return () => unwatch();
  }, [persist]);

  const toggleMinimize = useCallback(() => {
    setMinimized((prev) => {
      const next = !prev;
      persist({ position: positionRef.current, minimized: next, hidden: hiddenRef.current });
      return next;
    });
  }, [persist]);

  if (reloadRequired) {
    return <ReloadRequiredNotice />;
  }

  // hidden は unmount でなく display:none で表現する (要件1/3)。unmount すると toggleOverlay
  // リスナーが消え拡張アイコンで復帰不能になるため (#897)、DOM に残したまま CSS で隠す。
  return (
    <div
      ref={containerRef}
      className="fixed overflow-hidden rounded-lg border border-gray-300 bg-white shadow-xl"
      style={{
        left: position.x,
        top: position.y,
        width: OVERLAY_WIDTH,
        zIndex: 2147483647,
        ...hiddenStyle(hidden),
      }}
    >
      {/* handle: 常に pointer-events:auto。最小化中もここだけ残り再展開を受け付ける (要件4)。 */}
      <div
        onPointerDown={onPointerDown}
        className="flex items-center justify-between rounded-t-lg bg-gray-800 px-3 py-2 text-sm font-semibold text-white select-none"
        style={{ cursor: dragging ? "grabbing" : "grab", pointerEvents: "auto" }}
      >
        <span>Suno Helper</span>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={toggleMinimize}
          aria-label={minimized ? "展開" : "最小化"}
          className="rounded px-2 leading-none hover:bg-gray-700"
        >
          {minimized ? "▢" : "—"}
        </button>
      </div>
      {/* 最小化中は panel を display:none + pointer-events:none で Suno UI 操作を邪魔しない (要件4)。 */}
      <div
        className="overflow-y-auto"
        style={{
          pointerEvents: minimized ? "none" : "auto",
          display: minimized ? "none" : "block",
          maxHeight: "calc(100vh - 120px)",
        }}
      >
        <App />
      </div>
    </div>
  );
}
