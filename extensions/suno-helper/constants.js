// popup ⇄ content script 間の契約文字列を 1 箇所に集約する。
// popup.html（<script>）と content_scripts（manifest）の双方が最初に読み込む。
globalThis.SUNO_HELPER = {
  STORAGE_KEY: "sunoServerUrl",
  PROMPTS_ROUTE: "/prompts.json",
  DEFAULT_URL: "http://localhost:7873",
  MSG: {
    RUN: "SUNO_RUN",
    STOP: "SUNO_STOP",
    PROGRESS: "SUNO_PROGRESS",
  },
  // PROGRESS メッセージの phase 値
  PHASE: {
    INJECTING: "injecting",
    GENERATING: "generating",
    DONE: "done",
    FINISHED: "finished",
    STOPPED: "stopped",
    ERROR: "error",
  },
};
