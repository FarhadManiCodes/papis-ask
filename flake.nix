{
  description = "Papis-ask";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    papis = {
      url = "github:papis/papis";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      papis,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3.override {
          packageOverrides = self: super: {
            paper-qa = import ./nix/pkgs/paper-qa { inherit pkgs python3Packages; };
            paper-qa-pypdf = import ./nix/pkgs/paper-qa-pypdf { inherit pkgs python3Packages; };
            fhlmi = import ./nix/pkgs/fhlmi { inherit pkgs python3Packages; };
            fhaviary = import ./nix/pkgs/fhaviary { inherit pkgs python3Packages; };
            papis = papis.packages."${system}".default;
          };
        };
        python3Packages = python.pkgs;
      in
      {
        packages = {
          papis-ask = python3Packages.buildPythonPackage {
            pname = "papis-ask";
            version = if (self ? rev) then self.shortRev else self.dirtyShortRev;

            format = "pyproject";

            src = ./.;

            build-system = [ python3Packages.hatchling ];

            buildInputs = [
              python3Packages.papis
            ];

            dependencies = [
              python3Packages.paper-qa
              python3Packages.click-default-group
              python3Packages.rich
            ]
            ++ python3Packages.paper-qa.optional-dependencies.paper-qa-pypdf;

            pythonImportsCheck = [ "papis_ask" ];

            # nativeCheckInputs = [
            #   python3Packages.pytestCheckHook
            #   python3Packages.pytest-asyncio
            #   python3Packages.pytest-mock # TODO: needed?
            # ];

            meta = {
              description = "Use AI to search your Papis library";
              homepage = "https://papis.readthedocs.io/";
              license = pkgs.lib.licenses.gpl3Plus;
              maintainers = [
                {
                  name = "Julian Hauser";
                  email = "julian@julianhauser.com";
                }
              ];
            };
          };
          default = self.packages.${system}.papis-ask;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            python3Packages.papis
            self.packages.${system}.papis-ask
            python3Packages.pytest
            python3Packages.pytest-asyncio
            python3Packages.pytest-mock
          ];
          shellHook = ''
            export PYTHONPATH="$(pwd):$PYTHONPATH"
          '';
        };
      }
    );
}
