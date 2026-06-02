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
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python311
            uv
            ffmpeg
            lefthook
            bun
          ];

          # ランタイム供給のみ。秘密は youtube_automation.utils.secrets から
          # op read で都度取得する。`op` (1Password CLI) は unfree のため
          # nixpkgs から外し、システム（Homebrew 等）の op を利用する想定。
          #
          # 初回セットアップ:
          #   uv sync --extra dev --extra veo
          # その後の利用:
          #   uv run yt-skills list
          #   uv run pytest
          shellHook = ''
            export UV_PYTHON_PREFERENCE=only-system
            export UV_PYTHON=${pkgs.python311}/bin/python
            # PyPI バイナリホイール (numpy 等) が dlopen する GCC ランタイムと zlib を
            # Nix 環境でも見えるようにする。Linux CI 用の救済で、darwin では無害。
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc pkgs.zlib ]}:''${LD_LIBRARY_PATH:-}"

            # Git hooks (lefthook) を有効化。冪等なので devShell 入室ごとに実行してよい。
            if git rev-parse --git-dir >/dev/null 2>&1; then
              lefthook install >/dev/null 2>&1 || true
            fi
          '';
        };
      }
    );
}
