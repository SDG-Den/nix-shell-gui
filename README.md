# nix-shell-gui

GTK app store for nixpkgs: search packages, mark favourites, flag software
already in the nix store, and temporarily launch it via `nix run` / `nix shell`
in an embedded VTE terminal. Nothing is ever installed.

## Usage

    nix run .#            # from this repo
    nix run github:you/nix-shell-gui

## Flake outputs

- `packages.<sys>.default` - the app
- `apps.<sys>.default` - same, via `nix run`
- `devShells.<sys>.default` - dev environment (nix, python3, pygobject3, gtk3, vte, pytest)
- `nixosModules.default` - adds the app to `environment.systemPackages`:

      services.nix-shell-gui.enable = true;

- `checks.<sys>.default` - pytest unit tests, run with `nix flake check`

## Launch behaviour

Packages are classified automatically (exact via desktop-file probe when
already in the store, otherwise by build-input libraries):

- GUI - `nix run nixpkgs#Pkg` directly, no terminal
- TUI - `nix run nixpkgs#Pkg` in a VTE tab
- everything else (fail-safe default) - `nix shell nixpkgs#Pkg` in a VTE tab

Favourites are stored in `~/.config/nix-shell-gui/favourites.json`.