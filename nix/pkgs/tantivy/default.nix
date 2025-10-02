{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "tantivy";
  version = "0.25.0";

  format = "pyproject";

  src = pkgs.fetchFromGitHub {
    owner = "quickwit-oss";
    repo = "tantivy-py";
    rev = version;
    hash = "sha256-ZVQOzKojBf7yNkgiOV4huNnuxCmiFwJb610sD4M2/MU=";
  };

  cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
    inherit src;
    name = "${pname}-${version}";
    hash = "sha256-/OADcVm01PbHp3bcw62Zt6+9ZmT96Bic+EBbPUhdoOI=";
  };

  nativeBuildInputs = with pkgs.rustPlatform; [
    cargoSetupHook
    maturinBuildHook
  ];

  pythonImportsCheck = [ "tantivy" ];

  meta = {
    description = " Python bindings for Tantivy ";
    homepage = "https://github.com/quickwit-oss/tantivy-py";
    license = pkgs.lib.licenses.mit;
  };
}
