{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "fhaviary";
  version = "0.35.0";

  format = "pyproject";

  src = pkgs.fetchFromGitHub {
    owner = "Future-House";
    repo = "aviary";
    rev = "refs/tags/v${version}";
    hash = "sha256-mLEm+JYhSQCU+H9CzFrLVaq1uQtxtXW2nuJ1dVsJ0EA=";
  };

  propagatedBuildInputs = with python3Packages; [
    docstring-parser
    httpx
    httpx-aiohttp
    packaging
    pydantic
    setuptools
    setuptools-scm
  ];

  pythonImportsCheck = [ "aviary" ];

  meta = {
    description = "Gymnasium framework for training language model agents on constructive tasks";
    homepage = "https://github.com/Future-House/aviary";
    license = pkgs.lib.licenses.asl20;
  };
}
