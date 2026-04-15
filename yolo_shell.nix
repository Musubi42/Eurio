{ pkgs ? import <nixpkgs> {
    config.allowUnfree = true;
    config.cudaSupport = true;
  }
}:

(pkgs.buildFHSEnv {
  name = "yolo-cuda-env";
  targetPkgs = pkgs: with pkgs; [
    python310
    python310Packages.pip
    python310Packages.virtualenv
    cudaPackages.cudatoolkit
    cudaPackages.cudnn
    linuxPackages.nvidia_x11
    libGL
    glib
    zlib
    stdenv.cc.cc.lib
    # utilitaires
    git
    which
  ];
  runScript = "zsh";
}).env