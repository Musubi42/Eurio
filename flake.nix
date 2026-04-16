{
  description = "Eurio – Android + ML + Admin dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = {
            allowUnfree = true;
            android_sdk.accept_license = true;
          };
        };

        androidComposition = pkgs.androidenv.composeAndroidPackages {
          platformVersions = [ "36" "35" ];
          buildToolsVersions = [ "36.0.0" "35.0.0" ];
          includeNDK = true;
          ndkVersions = [ "27.0.12077973" ];
          includeSources = false;
          includeSystemImages = false;
          includeEmulator = false;
          cmakeVersions = [ "3.22.1" ];
        };

        androidSdk = androidComposition.androidsdk;

        # Maestro CLI — mobile UI automation for parity screenshot capture.
        # Not in nixpkgs; packaged from the GitHub release zip.
        maestro = pkgs.stdenv.mkDerivation rec {
          pname = "maestro";
          version = "2.4.0";
          src = pkgs.fetchzip {
            url = "https://github.com/mobile-dev-inc/Maestro/releases/download/cli-${version}/maestro.zip";
            hash = "sha256-4M+1KaIU6xlV8Rpq8kNCLWc5AMcrAifDZoXOiJbyu6s=";
            stripRoot = false;
          };
          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;
          installPhase = ''
            mkdir -p $out/bin $out/lib
            cp -r maestro/* $out/lib/
            chmod +x $out/lib/bin/maestro
            makeWrapper $out/lib/bin/maestro $out/bin/maestro \
              --set JAVA_HOME "${pkgs.jdk17}"
          '';
        };

        pythonEnv = pkgs.python312.withPackages (ps: with ps; [
          torch
          torchvision
          pillow
          numpy
          matplotlib
          scikit-learn
          tqdm
          # Referential bootstrap (Phase 2C)
          httpx
          beautifulsoup4
          lxml
          anyascii
          # ML API (FastAPI)
          fastapi
          uvicorn
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            # Android
            pkgs.jdk17
            androidSdk
            pkgs.gradle
            pkgs.kotlin

            # ML / Python
            pythonEnv
            pkgs.uv

            # Task runner
            pkgs.go-task

            # Parity viewer — Maestro UI automation
            maestro

            # Admin web (Vue 3 + Vite)
            # Node 22 LTS — nodejs_25 n'est plus disponible dans nixpkgs (EOL avril 2025).
            # Prochaine version disponible : nodejs_22 (LTS jusqu'en 2027).
            pkgs.nodejs_22
            pkgs.pnpm
          ];

          JAVA_HOME = "${pkgs.jdk17}";
          ANDROID_HOME = "${androidSdk}/libexec/android-sdk";
          ANDROID_SDK_ROOT = "${androidSdk}/libexec/android-sdk";

          shellHook = ''
            echo "Eurio dev shell loaded"
            echo "  Java:    $(java -version 2>&1 | head -1)"
            echo "  Gradle:  $(gradle --version 2>/dev/null | grep '^Gradle' || echo 'available')"
            echo "  Android: $ANDROID_HOME"
            echo "  Python:  $(python3 --version)"
            echo "  Node:    $(node --version)"
            echo "  pnpm:    $(pnpm --version)"
            echo "  Maestro: $(maestro --version 2>/dev/null || echo 'not available')"
            echo ""
            echo "  Secrets admin : exporter via .envrc (direnv) :"
            echo "    export VITE_SUPABASE_URL=..."
            echo "    export VITE_SUPABASE_ANON_KEY=..."
            echo "  Aucun .env file — Vite lit VITE_* depuis l'environnement shell."
          '';
        };
      }
    );
}
