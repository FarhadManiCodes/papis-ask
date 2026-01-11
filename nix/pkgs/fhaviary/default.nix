{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "fhaviary";
  version = "0.31.0";

  format = "pyproject";

  src = pkgs.fetchFromGitHub {
    owner = "Future-House";
    repo = "aviary";
    rev = "refs/tags/v${version}";
    hash = "sha256-G7ga9fr7JDW6k9Tz9yOmJpvXHDVJaxkt0NV7H2CQxP8=";
  };

  propagatedBuildInputs = with python3Packages; [
    docstring-parser
    httpx
    httpx-aiohttp
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
