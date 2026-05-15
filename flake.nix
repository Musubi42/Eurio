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
          # S3-compatible storage client (MinIO via boto3).
          # See docs/harmonisation-images/.
          boto3
          botocore
        ]);

        # ─── Profile building blocks ──────────────────────────────────────────
        baseInputs = [
          pkgs.go-task
          # Secrets : SOPS + age. Voir README.md §Secrets.
          pkgs.sops
          pkgs.age
        ];

        androidInputs = [
          pkgs.jdk17
          androidSdk
          pkgs.gradle
          pkgs.kotlin
          maestro
        ];

        mlInputs = [
          pythonEnv
          pkgs.uv
        ];

        adminInputs = [
          pkgs.nodejs_22
          pkgs.pnpm
        ];

        vpsInputs = [
          pkgs.minio-client
        ];

        fullInputs = androidInputs ++ mlInputs ++ adminInputs;

        commonEnv = {
          JAVA_HOME = "${pkgs.jdk17}";
          ANDROID_HOME = "${androidSdk}/libexec/android-sdk";
          ANDROID_SDK_ROOT = "${androidSdk}/libexec/android-sdk";
        };

        bannerHook = profile: ''
          echo "Eurio dev shell [${profile}]"
        '';

        fullBannerHook = profile: ''
          ${bannerHook profile}
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

        # NixOS uniquement : expose le driver NVIDIA (/run/opengl-driver/lib,
        # libcuda.so.1) + les libs C++ servies par nix-ld (libstdc++.so.6, …)
        # via LD_LIBRARY_PATH, pour que les wheels PyPI chargés via dlopen
        # (torch+cu121, opencv-python-headless, …) trouvent ce qu'il leur faut.
        nvidiaHook = ''
          if [ -d /run/opengl-driver/lib ]; then
            export LD_LIBRARY_PATH="/run/opengl-driver/lib:''${NIX_LD_LIBRARY_PATH:-}:''${LD_LIBRARY_PATH:-}"
          fi
        '';

        # ─── Profiles ─────────────────────────────────────────────────────────
        macShell = pkgs.mkShell (commonEnv // {
          buildInputs = baseInputs ++ fullInputs;
          shellHook = fullBannerHook "mac";
        });

        pcShell = pkgs.mkShell (commonEnv // {
          buildInputs = baseInputs ++ fullInputs;
          shellHook = ''
            ${nvidiaHook}
            ${fullBannerHook "pc"}
          '';
        });

        vpsShell = pkgs.mkShell {
          buildInputs = baseInputs ++ vpsInputs;
          shellHook = ''
            ${bannerHook "vps"}
            echo "  go-task: $(go-task --version 2>/dev/null || echo 'available')"
            echo "  mc:      $(mc --version 2>/dev/null | head -1 || echo 'available')"
          '';
        };
      in
      {
        devShells = {
          mac = macShell;
          pc = pcShell;
          vps = vpsShell;
          # Fallback pour `nix develop` hors direnv : full stack sans bits NVIDIA.
          default = macShell;
        };
      }
    );
}
