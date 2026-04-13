{
  description = "Eurio – Android + ML dev environment";

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
          '';
        };
      }
    );
}
