{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "paper-qa-pypdf";
  format = "pyproject";
  version = "2026.08.12";

  src = pkgs.fetchFromGitHub {
    owner = "Future-House";
    repo = "paper-qa";
    rev = "refs/tags/v${version}";
    hash = "sha256-RzxLFdf8druzat4YtT7wKtTp8CKLbtblNb7yrDYXmGM=";
  };

  sourceRoot = "source/packages/paper-qa-pypdf";

  propagatedBuildInputs = with python3Packages; [
    pypdf
    paper-qa
  ];

  build-system = with python3Packages; [
    setuptools
    setuptools-scm
  ];

  pythonImportsCheck = [ "paperqa_pypdf" ];

  meta = {
    description = "PaperQA readers implemented using PyPDF";
    homepage = "https://github.com/Future-House/paper-qa";
    license = pkgs.lib.licenses.asl20;
  };
}
