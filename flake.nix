{
  description = "BigLinux Parental Controls";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages.default = pkgs.callPackage ./default.nix { };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (python3.withPackages (ps: with ps; [
              pygobject3
              pycairo
              pytest
            ]))
            ruff
            cargo
            rustc
            rust-analyzer
            clippy
            rustfmt
            pkg-config
            gobject-introspection
            gtk4
            libadwaita
            wrapGAppsHook4
          ];

          shellHook = ''
            export GI_TYPELIB_PATH="${pkgs.lib.makeSearchPath "lib/girepository-1.0" [
              pkgs.gtk4
              pkgs.libadwaita
              pkgs.gobject-introspection
            ]}"
          '';
        };
      }
    );
}
