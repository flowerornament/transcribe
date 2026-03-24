{
  description = "transcribe - Audio transcription CLI using Parakeet V3 on Apple Silicon";

  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "aarch64-darwin";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3.withPackages (ps: [ ps.rich ]);
    in {
      packages.${system}.default = pkgs.writeShellApplication {
        name = "transcribe";
        runtimeInputs = [ python pkgs.yt-dlp pkgs.ffmpeg ];
        text = ''
          exec ${python}/bin/python3 ${./transcribe.py} "$@"
        '';
      };
    };
}
