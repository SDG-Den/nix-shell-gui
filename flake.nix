{
  description = "GTK app store for temporarily launching nixpkgs packages via nix run / nix shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      nixosModule = { config, lib, pkgs, ... }: {
        options.services.nix-shell-gui.enable = lib.mkEnableOption
          "nix-shell-gui, a GTK app store for temporarily launching nixpkgs packages";

        config = lib.mkIf config.services.nix-shell-gui.enable {
          environment.systemPackages = [ self.packages.${pkgs.system}.default ];
        };
      };
    in
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        nix-shell-gui = python.pkgs.buildPythonApplication {
          pname = "nix-shell-gui";
          version = "0.1.0";
          src = ./.;
          pyproject = true;

          nativeBuildInputs = [
            pkgs.wrapGAppsHook3
            python.pkgs.setuptools
            python.pkgs.wheel
          ];

          buildInputs = [
            pkgs.glib
            pkgs.gtk3
            pkgs.pango
            pkgs.cairo
            pkgs.gdk-pixbuf
            pkgs.atk
            pkgs.at-spi2-atk
            pkgs.at-spi2-core
            pkgs.harfbuzz
            pkgs.gobject-introspection
            pkgs.gsettings-desktop-schemas
          ];

          propagatedBuildInputs = [
            python.pkgs.pygobject3
          ];

          postInstall = ''
            install -Dm644 ${./nix-shell-gui.desktop} \
              "$out/share/applications/nix-shell-gui.desktop"
          '';

          preFixupPhases = [ "collectGiPaths" ];

          collectGiPaths = ''
            gappsWrapperArgs+=(--prefix GI_TYPELIB_PATH : "${
              pkgs.lib.makeSearchPath "lib/girepository-1.0" [
                pkgs.glib
                pkgs.gobject-introspection
                pkgs.gtk3
                pkgs.pango.out
                pkgs.gdk-pixbuf
                pkgs.harfbuzz
                pkgs.at-spi2-core
              ]
            }")
            gappsWrapperArgs+=(--prefix LD_LIBRARY_PATH : "${
              pkgs.lib.makeLibraryPath [
                pkgs.glib
                pkgs.gtk3
                pkgs.pango
                pkgs.cairo
                pkgs.gdk-pixbuf
                pkgs.atk
                pkgs.harfbuzz
              ]
            }")
          '';
        };
      in
      {
        packages.default = nix-shell-gui;
        apps.default = { type = "app"; program = "${nix-shell-gui}/bin/nix-shell-gui"; };

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.nix
            nix-shell-gui
            python
            python.pkgs.pygobject3
            python.pkgs.pytest
            pkgs.pyright
            pkgs.ruff
          ];
          shellHook = ''
            export PYTHONPATH="${nix-shell-gui}/${python.sitePackages}"
          '';
        };

        checks.default = pkgs.runCommand "nix-shell-gui-tests" {
          nativeBuildInputs = [ python python.pkgs.pytest ];
        } ''
          export PYTHONPATH="${nix-shell-gui}/${python.sitePackages}"
          cp -r ${./.}/tests tests
          cd tests
          pytest -q
          mkdir -p $out
        '';
      }
    ) // {
      nixosModules.default = nixosModule;
    };
}
