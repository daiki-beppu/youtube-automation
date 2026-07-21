{
  description = "youtube-channels-automation dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        pnpmLatest = pkgs.stdenvNoCC.mkDerivation {
          pname = "pnpm";
          version = "11.12.0";
          src = pkgs.fetchurl {
            url = "https://registry.npmjs.org/pnpm/-/pnpm-11.12.0.tgz";
            hash = "sha256-HCvxCNdnuXY1PCwemtFNJAzruZ1L702Tp/Gp0Q2luBc=";
          };
          nativeBuildInputs = [ pkgs.makeWrapper ];
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/lib/pnpm" "$out/bin"
            cp -R . "$out/lib/pnpm/"
            makeWrapper "${pkgs.nodejs_24}/bin/node" "$out/bin/pnpm" \
              --add-flags "$out/lib/pnpm/bin/pnpm.cjs"
            runHook postInstall
          '';
        };
      in
      {
        devShells.extensions = pkgs.mkShell {
          packages = with pkgs; [
            nodejs_24
            pnpmLatest
          ];
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python314
            uv
            ffmpeg
            lefthook
          ];

          # ランタイム供給のみ。秘密は youtube_automation.utils.secrets から
          # op read で都度取得する。`op` (1Password CLI) は unfree のため
          # nixpkgs から外し、システム（Homebrew 等）の op を利用する想定。
          #
          # devShell 入室時に uv sync が自動実行される。
          # その後の利用:
          #   uv run yt-skills list
          #   uv run pytest
          shellHook = ''
            export UV_PYTHON_PREFERENCE=only-system
            export UV_PYTHON=${pkgs.python314}/bin/python
            # PyPI バイナリホイール (numpy 等) が dlopen する GCC ランタイムと zlib を
            # Nix 環境でも見えるようにする。Linux CI 用の救済で、darwin では無害。
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc pkgs.zlib ]}:''${LD_LIBRARY_PATH:-}"

            # 並列 run 間の共有 TMPDIR 競合を避けるため、共有 TMPDIR 配下に worktree
            # ごとの決定的なサブディレクトリを切って分離する（issue #2088）。takt worker
            # のように既に checkout 内へ隔離済みの値は worktree-tmpdir.sh 側が尊重する。
            # 失敗時は共有 TMPDIR のまま続行する（分離は品質ゲートではなく干渉回避の
            # ため fail-open）
            if git rev-parse --git-dir >/dev/null 2>&1; then
              if worktree_tmpdir="$(bash "${./.}/.lefthook/worktree-tmpdir.sh" 2>/dev/null)"; then
                export TMPDIR="$worktree_tmpdir"
                # shell 内で以後実行される nix コマンドの flake 評価キャッシュも
                # worktree 単位に分離する（issue #2089）。今回の入場自体の評価は
                # .envrc / setup-worktree.sh 側の export が分離を担う
                export NIX_CACHE_HOME="$worktree_tmpdir/nix-cache"
              else
                echo "warning: worktree 分離 TMPDIR の初期化に失敗しました。共有 TMPDIR のまま続行します。" >&2
              fi
            fi

            # Git hooks (lefthook) を有効化。stale な Nix store 固定パスを残さないよう
            # devShell 入室ごとに再生成し、失敗は commit / push 前に明示的に止める。
            # ただし sandbox 化された takt worker 等、hooks ディレクトリへ書込みできない
            # 環境では YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1 で安全にスキップする
            # （CHANGELOG 等のゲートは CI 側で担保される。issue #1999）。
            if git rev-parse --git-dir >/dev/null 2>&1; then
              if [ "''${YOUTUBE_AUTOMATION_SKIP_LEFTHOOK:-0}" = "1" ]; then
                echo "info: YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1 のため lefthook install をスキップします。" >&2
              else
                bash "${./.}/.lefthook/install.sh" || exit 1
              fi
            fi
            # 対話入場（direnv / nix develop）は依存同期失敗でも warning で継続する
            # （入場をブロックしない）。explicit setup 経路（.lefthook/setup-worktree.sh）
            # は .lefthook/sync-deps.sh により fail-closed（issue #2125）
            uv sync --quiet || echo "warning: uv sync failed; dependencies may be out of date." >&2
          '';
        };
      }
    );
}
