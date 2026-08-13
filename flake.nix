{
  description = "Reproducible development and evidence environment for futhark-bessel";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/2fcb964de67fcf60b43471c55d5d99e61a9ccb5a";
    flake-utils.url = "github:numtide/flake-utils/11707dc2f618dd54ca8739b309ec4fc024de578b";
    futhark-src.url = "github:diku-dk/futhark/8d6d12f0c31e133d7b5bd39c1254c541aa6ef70a";
    futhark-src.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      futhark-src,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        emscripten = pkgs.emscripten;
        futhark = futhark-src.packages.${system}.default;
        python = pkgs.python3.withPackages (ps: [
          ps.mpmath
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            just
            git
            gh
            gitleaks
            jq
            nixfmt
            clang
            emscripten
            flint
            futhark
            python
          ];
          shellHook = ''
            export NIX_CONFIG="max-jobs = 4''${NIX_CONFIG:+
            $NIX_CONFIG}"
            echo "futhark-bessel development shell"
            echo "Entrypoint: just"
          '';
        };

        checks.contract = pkgs.runCommand "futhark-bessel-contract" { } ''
          test -s ${self}/LICENSE
          test -s ${self}/RELEASE.md
          test -s ${self}/futhark.pkg
          touch "$out"
        '';

        checks.toolchain =
          pkgs.runCommand "futhark-bessel-toolchain"
            {
              nativeBuildInputs = [
                emscripten
                futhark
              ];
            }
            ''
              emcc --version | grep -F "6.0.5"
              test "${emscripten.version}" = "6.0.5"
              futhark --version | grep -F "Futhark 0.27.0"
              test "$(cat ${futhark}/commit-id)" = "8d6d12f0c31e133d7b5bd39c1254c541aa6ef70a"
              touch "$out"
            '';

        formatter = pkgs.nixfmt;
      }
    );
}
